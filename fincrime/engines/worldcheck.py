"""The simulated watchlist console: resolve a match, record an export, and
the read models the case and match pages need (facet counts, filtering,
paging, prev/next, the submitted-vs-matched comparison)."""
from fincrime.data import vocab
from fincrime.engines.errors import WorkflowError
from fincrime.utils import dates

STATUS_ORDER = ["Unresolved", "True positive", "Potential match", "False positive", "Unspecified"]


def _audit(record, actor, action, detail="", at=None):
    record.setdefault("audit", []).append({"at": at or dates.now_str(), "actor": actor, "action": action, "detail": detail})


def _require(cond, msg):
    if not cond:
        raise WorkflowError(msg)


def find_match(wc, match_id):
    return next((m for m in wc["matches"] if m["id"] == match_id), None)


def resolve_match(wc, actor, match_id, status, reason, comment):
    """The risk level is set from the status (vocab.RISK_FOR_OUTCOME), never
    picked: a true positive is always High, a false positive always Low."""
    m = find_match(wc, match_id)
    _require(m is not None, "Unknown match.")
    _require(status in vocab.WC_STATUSES, "Pick a status.")
    _require(reason in vocab.WC_REASONS or status == "Unspecified", "Select a reason.")
    comment = (comment or "").strip()
    _require(comment, "A review comment is required.")
    risk = vocab.RISK_FOR_OUTCOME[status]
    m["resolution"] = {"status": status, "risk": risk, "reason": reason, "remark": reason, "comment": comment,
                       "by": actor, "at": dates.now_str()}
    wc["last_updated"] = dates.now_str()
    _audit(wc, actor, f"Match resolved: {status}", f"{m['name']} (WC {m['wc_id']}) — {risk} risk, {reason}. {comment}")
    return m


def record_export(wc, actor, at=None):
    """`at` lets the AI screening rules date an export at the moment they
    closed the screening case (the seed builds cases in the past)."""
    now = at or dates.now_str()
    stamp = now.replace("-", "").replace(":", "").replace(" ", "_")
    name = "".join(ch for ch in wc["primary_name"].title() if ch.isalnum())
    export = {"id": f"exp-{len(wc['exports']) + 1}", "filename": f"WorldCheck_{name}_{stamp}.pdf", "at": now, "by": actor}
    wc["exports"].append(export)
    _audit(wc, actor, "Case exported", export["filename"], at=now)
    return export


def facets(matches):
    by_status = {s: 0 for s in STATUS_ORDER}
    by_type = {}
    for m in matches:
        by_status[m["resolution"]["status"]] = by_status.get(m["resolution"]["status"], 0) + 1
        for t in m["types"]:
            by_type[t] = by_type.get(t, 0) + 1
    return {"status": by_status, "type": dict(sorted(by_type.items()))}


def filter_matches(matches, status="", mtype=""):
    out = matches
    if status:
        out = [m for m in out if m["resolution"]["status"] == status]
    if mtype:
        out = [m for m in out if mtype in m["types"]]
    return out


def paginate(items, page, size=vocab.WC_PAGE_SIZE):
    total = len(items)
    pages = max(1, (total + size - 1) // size)
    page = min(max(1, page), pages)
    start = (page - 1) * size
    return {"items": items[start:start + size], "page": page, "pages": pages, "total": total,
            "start": start + 1 if total else 0, "end": min(start + size, total)}


def match_nav(wc, match_id, status="", mtype=""):
    ordered = [m["id"] for m in filter_matches(wc["matches"], status, mtype)]
    if match_id not in ordered:
        ordered = [m["id"] for m in wc["matches"]]
    i = ordered.index(match_id) if match_id in ordered else 0
    return {"index": i + 1, "total": len(ordered),
            "prev": ordered[i - 1] if i > 0 else "", "next": ordered[i + 1] if i + 1 < len(ordered) else ""}


def comparison_rows(wc, m):
    sub_dob = dates.wc_date(wc["dob"] + " 00:00:00") if wc.get("dob") else ""
    rows = [
        ("Name", wc["primary_name"], m["name"], _names_match(wc["primary_name"], m["name"])),
        ("Gender", wc["gender"], m["gender"], bool(m["gender"]) and wc["gender"].lower() == m["gender"].lower()),
        ("Date of Birth", sub_dob, ", ".join(m["dobs"]), _dob_match(wc.get("dob", ""), m["dobs"])),
        ("Country", wc["case_details"].get("Country", ""), m["country"], False),
        ("Citizenship", "", m["citizenship"], False),
    ]
    return [{"field": f, "submitted": s, "matched": md, "match": ok} for f, s, md, ok in rows]


def _names_match(a, b):
    ta = {t.strip(",").lower() for t in a.split()}
    tb = {t.strip(",").lower() for t in b.split()}
    return len(ta & tb) >= 2 or (ta and ta <= tb)


def _dob_match(sub, dobs):
    if not sub or not dobs:
        return False
    year = sub[:4]
    for d in dobs:
        if d.endswith(year) or d == year or sub in d:
            return True
    return False
