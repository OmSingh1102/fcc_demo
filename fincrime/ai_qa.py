"""The AI QA page: how far the AI can be trusted, measured on the console's
own cases, as an L2 / QC reviewer reads it.

  checked   every hit the AI gave a suggestion on, and what became of it: an
            analyst agreed or overrode it, the AI screening rule cleared it,
            it waits for an analyst, or the AI could not answer. The override
            that matters most is the AI calling a hit a false positive that
            the analyst then did not clear.
  bands     the analysts' agreement under and over the confidence bar on
            Settings: whether the bar the rule clears hits at is right.
  alone     the cases that closed by themselves (auto-verify), with the
            rule's reason, for a spot check.
  qc        the QC sample: cases the AI would have closed, kept for a person,
            and whether the person then did what the AI would have done.
  didit     where Didit's answer on the document and the console's own
            checks disagree, and Didit's warnings across the cases.

Built from the "scan" records each time the page is drawn; nothing stored.
"""
from collections import Counter

from fincrime import id_screening

DONE, FAILED = "done", "failed"


def _pct(a, b):
    return round(100 * a / b) if b else None


def _name(scan):
    return id_screening.person(scan.get("read"))["name"] or "—"


def _case(scan):
    return {"id": scan["id"], "name": _name(scan), "at": scan.get("at", ""), "sample": (scan.get("sample") or {}).get("title", "")}


def _result(hit):
    """What became of the AI's suggestion on a hit: (key, words)."""
    ai, res = hit.get("ai") or {}, hit.get("resolution") or {}
    if res.get("auto"):
        return "auto", "Cleared by the AI screening rule"
    if res and res.get("ai_suggested"):
        if res.get("agreed"):
            return "agreed", "The analyst agreed"
        if res["ai_suggested"] == "False positive" and res.get("status") != "False positive":
            return "missed", "Overridden: the AI would have cleared a match"
        return "overridden", "Overridden by the analyst"
    if res:
        return "analyst", "Decided by the analyst (no AI suggestion)"
    if ai.get("status") == FAILED:
        return "failed", "The AI could not answer: an analyst decides"
    if ai.get("status") != DONE:
        return "deciding", "The AI is deciding"
    return "waiting", "Waits for an analyst"


def checked(scans):
    """One row per hit, the overrides first, then the waiting ones."""
    order = {"missed": 0, "overridden": 1, "waiting": 2, "failed": 3, "deciding": 4, "agreed": 5, "analyst": 6, "auto": 7}
    rows = []
    for s in scans:
        for h in (s.get("screening") or {}).get("hits") or []:
            ai, res = h.get("ai") or {}, h.get("resolution") or {}
            key, words = _result(h)
            rows.append(dict(_case(s), uid=h.get("uid", ""), hit=h.get("name", ""), category=h.get("category", ""),
                             suggested=ai.get("suggested", "") if ai.get("status") == DONE else "",
                             confidence=ai.get("confidence") if ai.get("status") == DONE else None,
                             outcome=res.get("status", ""), by=res.get("by", ""), when=res.get("at", ""),
                             note=res.get("note", ""), key=key, result=words))
    return sorted(rows, key=lambda r: (order[r["key"]], r["at"]), reverse=False)


def bands(rows, bar):
    """The analysts' agreement on the AI's suggestions under and at or over the bar."""
    out = []
    for label, keep in ((f"Under {bar}% sure", lambda c: c < bar), (f"{bar}% sure or more", lambda c: c >= bar)):
        mine = [r for r in rows if r["confidence"] is not None and keep(r["confidence"])]
        scored = [r for r in mine if r["key"] in ("agreed", "overridden", "missed")]
        agreed = sum(r["key"] == "agreed" for r in scored)
        out.append({"label": label, "hits": len(mine), "scored": len(scored), "agreed": agreed, "pct": _pct(agreed, len(scored)),
                    "missed": sum(r["key"] == "missed" for r in scored), "auto": sum(r["key"] == "auto" for r in mine),
                    "waiting": sum(r["key"] == "waiting" for r in mine)})
    return out


def alone(scans):
    """The cases that closed by themselves, newest first."""
    rows = []
    for s in scans:
        c = s.get("closed") or {}
        if c.get("auto"):
            hits = (s.get("screening") or {}).get("hits") or []
            rows.append(dict(_case(s), closed_at=c.get("at", ""), outcome=c.get("outcome", ""), why=c.get("note", ""),
                             hits=len(hits), idv=(s.get("idv") or {}).get("status", "")))
    return sorted(rows, key=lambda r: r["closed_at"], reverse=True)


def qc(scans):
    """The QC sample: what the AI would have done, and what the person did."""
    rows = []
    for s in scans:
        if not s.get("qc_sample"):
            continue
        hits = (s.get("screening") or {}).get("hits") or []
        would = "Cleared" if hits else "No match"
        c = s.get("closed") or {}
        if s.get("status") == "closed":
            same = c.get("outcome") == would
            result = ("agreed", "The analyst did the same") if same else ("overridden", f"The analyst found: {c.get('outcome', '')}")
        else:
            result = ("waiting", "Waits for an analyst")
        rows.append(dict(_case(s), sampled_at=s["qc_sample"].get("at", ""), pct=s["qc_sample"].get("pct"), would=would,
                         hits=len(hits), outcome=c.get("outcome", ""), by=c.get("by", ""), key=result[0], result=result[1]))
    return sorted(rows, key=lambda r: ({"waiting": 0, "overridden": 1, "agreed": 2}[r["key"]], r["sampled_at"]))


_OURS = {"Pass": "our checks passed", "Check": "a check of ours asks for a look", "Fail": "a check of ours failed",
         "Not read": "the ID was not read"}


def didit(scans):
    """(rows, warnings): the cases where Didit's answer and our checks
    disagree, and how often each Didit warning came up across the cases."""
    rows, seen, checked = [], Counter(), 0
    for s in scans:
        idv = s.get("idv") or {}
        status, verdict = idv.get("status"), s.get("verdict", "")
        if status not in ("Approved", "Declined"):
            continue
        checked += 1
        for w in idv.get("warnings") or []:
            seen[w.get("text") or w.get("risk", "")] += 1
        if (status == "Declined" and verdict == "Pass") or (status == "Approved" and verdict in ("Check", "Fail")):
            rows.append(dict(_case(s), didit=status, verdict=verdict, ours=_OURS.get(verdict, verdict),
                             sandbox=bool(idv.get("sandbox")), warnings=[w.get("text") or w.get("risk", "") for w in idv.get("warnings") or []]))
    return {"rows": sorted(rows, key=lambda r: r["at"], reverse=True), "checked": checked,
            "warnings": [{"text": t, "cases": n} for t, n in seen.most_common()]}


def _where(scan):
    """Where a case is now: alone, analyst, qc or waiting."""
    if scan.get("status") == "closed":
        return "alone" if (scan.get("closed") or {}).get("auto") else "analyst"
    return "qc" if scan.get("qc_sample") else "waiting"


def flow(scans, rows):
    """The workflow's five steps, live: what each step saw and where it sent
    it. Each line is (mark, words, count): ok goes on by itself, warn and
    fail go to a person, wait is still in progress, info is a note; each step
    says how many it sent to a person."""
    read = [s for s in scans if id_screening.is_id(s.get("read"))]
    verdicts = Counter(s.get("verdict", "") for s in read)
    didit_said = Counter((s.get("idv") or {}).get("status") for s in read)
    sc = lambda s: s.get("screening") or {}                                     # noqa: E731
    screened = [s for s in read if sc(s) and not sc(s).get("error")]
    errors = sum(1 for s in read if sc(s).get("error"))
    with_hits = [s for s in screened if sc(s).get("hits")]
    keys = Counter(r["key"] for r in rows)
    where = Counter(_where(s) for s in scans)
    answered = len(rows) - keys["failed"] - keys["deciding"] - keys["analyst"]
    to_analyst = len(rows) - keys["auto"]
    steps = [
        {"id": "read", "kicker": "Extraction", "title": "Read the ID", "n": len(scans), "unit": "ID", "lines": [
            ("ok", "Read by the AI", len(read)), ("warn", "Not read, or not an ID", len(scans) - len(read))],
         "person": len(scans) - len(read)},
        {"id": "checks", "kicker": "SOP validation & fraud", "title": "Check the document", "n": len(read), "unit": "ID", "lines": [
            ("ok", "Every check passes", verdicts["Pass"]), ("warn", "A check to look at", verdicts["Check"]),
            ("fail", "A check failed", verdicts["Fail"])]
            + ([("ok", "Didit approved", didit_said["Approved"]), ("fail", "Didit declined", didit_said["Declined"])]
               if didit_said["Approved"] or didit_said["Declined"] else []),
         "person": verdicts["Check"] + verdicts["Fail"]},
        {"id": "screen", "kicker": "Compliance & sanctions", "title": "Screen the name", "n": len(screened), "unit": "name", "lines": [
            ("ok", "No record matched", len(screened) - len(with_hits)), ("info", f"Matched a record ({len(rows)} hit{'s' if len(rows) != 1 else ''})", len(with_hits))]
            + ([("fail", "The search failed", errors)] if errors else []),
         "person": errors, "next": f"{len(with_hits)} case{'s' if len(with_hits) != 1 else ''} to the AI" if with_hits else ""},
        {"id": "ai", "kicker": "AI decision", "title": "The AI decides each hit", "n": len(rows), "unit": "hit", "lines": [
            ("ok", "The AI answered", answered), ("warn", "The AI could not answer", keys["failed"] + keys["analyst"])]
            + ([("wait", "The AI is deciding", keys["deciding"])] if keys["deciding"] else [])
            + [("ok", "Cleared by the AI screening rule", keys["auto"])],
         "person": to_analyst},
        {"id": "outcome", "kicker": "Human in the loop", "title": "Outcome", "n": len(scans), "unit": "case", "lines": [
            ("ok", "Closed by the AI alone", where["alone"]), ("info", "Closed by an analyst", where["analyst"]),
            ("warn", "QC sample: kept for a person", where["qc"]), ("wait", "Waiting for an analyst", where["waiting"])],
         "person": where["qc"] + where["waiting"]},
    ]
    return steps


def _bar(parts, of):
    """A segmented bar's parts: (key, name, n) with their share; a part at
    zero draws nothing, and a part under 10% prints no figure inside."""
    total = sum(n for _k, _name, n in parts)
    out = [{"key": k, "name": name, "n": n, "pct": round(100 * n / total) if total else 0} for k, name, n in parts if n]
    for p in out:
        p["inside"] = p["pct"] >= 10
    return {"parts": out, "total": total, "of": of}


def charts(scans, rows, dd):
    where = Counter(_where(s) for s in scans)
    keys = Counter(r["key"] for r in rows)
    cases = _bar([("alone", "Closed by the AI alone", where["alone"]), ("qc", "QC sample: kept for a person", where["qc"]),
                  ("analyst", "Closed by an analyst", where["analyst"]), ("waiting", "Waiting for an analyst", where["waiting"])], "case")
    hits = _bar([("agreed", "The analyst agreed", keys["agreed"]), ("overridden", "Overridden by the analyst", keys["overridden"]),
                 ("missed", "Overridden: the AI would have cleared a match", keys["missed"]),
                 ("auto", "Cleared by the AI screening rule", keys["auto"]),
                 ("waiting", "Waiting for an analyst", keys["waiting"] + keys["deciding"]),
                 ("failed", "The AI could not answer", keys["failed"] + keys["analyst"])], "hit")
    top = max((w["cases"] for w in dd["warnings"]), default=0)
    warnings = [dict(w, width=round(100 * w["cases"] / top) if top else 0, share=_pct(w["cases"], dd["checked"])) for w in dd["warnings"]]
    return {"cases": cases, "hits": hits, "warnings": warnings}


def page(scans, settings):
    """Everything the page draws, with the headline counts."""
    rows = checked(scans)
    scored = [r for r in rows if r["key"] in ("agreed", "overridden", "missed")]
    agreed = sum(r["key"] == "agreed" for r in scored)
    gone, sample, dd = alone(scans), qc(scans), didit(scans)
    bar = int(settings.get("auto_min_confidence", 90))
    return {"rows": rows, "bands": bands(rows, bar), "bar": bar, "alone": gone, "qc": sample, "didit": dd,
            "flow": flow(scans, rows), "charts": charts(scans, rows, dd),
            "totals": {"cases": len(scans), "open": sum(s.get("status", "open") == "open" for s in scans),
                       "closed_auto": len(gone), "closed_analyst": sum(s.get("status") == "closed" and not (s.get("closed") or {}).get("auto")
                                                                       for s in scans),
                       "hits": len(rows), "suggested": sum(r["suggested"] != "" for r in rows), "scored": len(scored),
                       "agreed": agreed, "agree_pct": _pct(agreed, len(scored)),
                       "overridden": sum(r["key"] in ("overridden", "missed") for r in rows), "missed": sum(r["key"] == "missed" for r in rows),
                       "waiting": sum(r["key"] == "waiting" for r in rows), "failed": sum(r["key"] == "failed" for r in rows),
                       "auto_cleared": sum(r["key"] == "auto" for r in rows),
                       "qc": len(sample), "qc_waiting": sum(r["key"] == "waiting" for r in sample),
                       "qc_agreed": sum(r["key"] == "agreed" for r in sample), "qc_pct": int(settings.get("auto_qc_pct") or 0),
                       "disagree": len(dd["rows"])}}
