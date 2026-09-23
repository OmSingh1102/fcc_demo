"""Seed builders.

Every record in the demo is produced by one of the builders here from a short
keyword call in scenarios.py, so a scenario reads as a description of a case
rather than as a 90-line dict. Ids come from fincrime.utils.ids, timestamps
are offsets from boot (fincrime.utils.dates), and nothing here is copied from
a real system.

Record shapes (the templates and engines depend on these keys):

Analyst
    id (== key), key, name, email, roles[], role, tenants[], role_label,
    skills{scripts[], kyb}, capacity, shift

KycCase
    id, client_id, tenant, tags[], status, pending_reason, source,
    manual_review_reason[], poa_required, case_review_level,
    created_at, submitted_at, sla_due_at, escalated_at, edd_due_at, closed_at,
    closed_by, assigned_at,
    current_reviewer, previous_reviewer, reviewers_by_level{L1[],L2[],EDD[]},
    qc_reviewer, qc_result, qc_reason, qc_at, qc_comment, qc_ack,
    client{legal_name, native_name, dob, nationality, gender, id_number,
           id_type, id_issuing_place, phone, email, us_person, address, country},
    agency{...} | None,
    vendor_check{vendor, result, vendor_reason, extracted{}, checked_at},
    documents[{id, name, category, kind, side, quality, issued_on?, country?}],
    confirmations{name, dob, nationality, poa → {value, confirmed_by, at, edited} | None},
    verification_points[{label, at}] (six, in STEP_LABELS order),
    review_decisions[{check_point, decision, fail_reason, poa_fail_reason,
                      approve_reason, rejection_reason, id_summary, report,
                      operated_at, by}],
    screening{hit, alert_case_id, rows[{platform, user_name, screen_time,
                                        list, result, alert_id}]},
    risk_rating, risk_recalculated_at, skopenow, attachments[], resubmit,
    fraud_typology, escalate_reason,
    routing{status, to, trigger, reason, at} | None,
    work[{level, analyst, from, to, outcome}],
    handoffs[{from, to, at, assigned_to, assigned_at, lag_seconds, via}],
    investigation_file{name, created_at, created_by} | None,
    checker1{by, at, decision, summary} | None, checker2{by, at, decision, comment} | None,
    audit[{at, actor, action, detail}], change_log[]

ScreeningAlertCase
    id, kyc_case_id, case_level, status, assigned_to, created_at, wc_group,
    business_line, event, merchant_uid, is_test, kyc_triggered, need_audit,
    last_screen_time, latest_updated, screening_info{}, platform_rows[],
    alerts[{id, match_id, vendor, watchlist_id, outcome, review_mode,
            result_label, rationale, comment, risk_level, attachment,
            resolved_by, resolved_at, smart_strategy, name, matched_alias,
            score, type, dob, gender}],
    case_outcome{value, rationale, comment, by, at} | None, rfi[], audit[]

WcCase
    id (== alert case id), alert_case_id, kyc_case_id, primary_name, gender,
    dob, group, assignee, rating, ongoing_screening, last_updated,
    case_details{}, matches[{id, wc_id, name, matched_alias, strength,
    types[], gender, dobs[], pob, citizenship, country, entered, updated,
    matched, resolution{status, risk, reason, remark, comment, by, at},
    key_data{category, sub_category, pep_status, special_interest[],
    position, location{}}, further_info{biography, identification,
    reports[[date, text]]}, aliases[], keywords[], sources[[date, url]]}],
    exports[], audit[]
"""
import copy
import random

from fincrime.data import vocab
from fincrime.utils import dates, ids

# ── Analysts ────────────────────────────────────────────────────────────────


def analyst(key, name, roles, tenants, *, scripts=("latin",), kyb=False, capacity=5, shift=""):
    """One analyst profile with the skill book the router reads (SOP 5.2.1:
    cases are matched to the analyst's skills) and a capacity (5.2.2)."""
    labels = ", ".join(vocab.TENANTS[t]["label"] for t in tenants)
    return {
        "id": key, "key": key, "name": name, "email": f"{key}@straive.com",
        "roles": list(roles), "role": roles[0], "tenants": list(tenants),
        "role_label": f"{' / '.join(roles)} · {labels}",
        "skills": {"scripts": list(scripts), "kyb": bool(kyb)},
        "capacity": int(capacity), "shift": shift,
    }


ANALYSTS = [
    analyst("amara.iyer", "Amara Iyer", ["L1"], ["ttlive"], scripts=("latin", "cyrillic"), capacity=6, shift="06:00–14:00 UTC"),
    analyst("jon.miranda", "Jon Miranda", ["L1"], ["ttlive", "ttshop"], scripts=("latin", "arabic"), kyb=True, capacity=6, shift="14:00–22:00 UTC"),
    analyst("mario.kim", "Mario Kim", ["L1", "L2"], ["ttlive", "ttshop"], scripts=("latin",), kyb=True, capacity=5, shift="22:00–06:00 UTC"),
    analyst("nisha.rao", "Nisha Rao", ["L2"], ["ttlive", "ttshop"], scripts=("latin", "cyrillic", "arabic"), kyb=True, capacity=4, shift="08:00–16:00 UTC"),
    analyst("ryan.lee", "Ryan Lee", ["EDD"], ["ttlive", "ttshop"], scripts=("latin", "cyrillic", "arabic"), kyb=True, capacity=3, shift="08:00–16:00 UTC"),
    analyst("leah.fernandez", "Leah Fernandez", ["QC"], ["ttlive", "ttshop"], scripts=("latin", "cyrillic", "arabic"), kyb=True, capacity=0, shift="08:00–16:00 UTC"),
]
EMAIL = {a["key"]: a["email"] for a in ANALYSTS}
AMARA, JON, MARIO, NISHA, RYAN, LEAH = (EMAIL[k] for k in
                                        ("amara.iyer", "jon.miranda", "mario.kim", "nisha.rao", "ryan.lee", "leah.fernandez"))

# ── Documents ───────────────────────────────────────────────────────────────

ID_KINDS = {"passport": "Passport", "driving_licence": "DrivingLicense", "national_id": "NationalID",
            "residence_permit": "ResidencePermit", "trade_licence": "TradeLicense"}
POA_KINDS = {"utility_bill": "ProofOfAddress", "bank_statement": "ProofOfAddress"}


def doc(kind, side="front", quality="ok", *, issued_days_ago=None, country=""):
    """A document row. `quality` drives the synthetic image: ok | blurred |
    cropped | expired. A proof of address also carries when it was issued and
    by which country — the two facts the SOP's POA checks read; kyc_case()
    fills the defaults from the case."""
    if kind in ID_KINDS:
        return {"name": "Photos of ID document", "category": ID_KINDS[kind], "kind": kind, "side": side, "quality": quality}
    return {"name": "Photos of Proof of Address", "category": POA_KINDS[kind], "kind": kind, "side": side, "quality": quality,
            "issued_days_ago": issued_days_ago, "country": country}


def std_docs(id_kind="passport", poa=True, id_quality="ok", *, poa_kind="utility_bill", poa_issued_days_ago=None, poa_country=""):
    out = [doc(id_kind, "front", id_quality), doc(id_kind, "back")]
    if poa:
        out += [doc(poa_kind, "page 1", issued_days_ago=poa_issued_days_ago, country=poa_country),
                doc(poa_kind, "page 2", issued_days_ago=poa_issued_days_ago, country=poa_country)]
    return out


# ── Audit / hand-off helpers ────────────────────────────────────────────────


def event(at, actor, action, detail=""):
    return {"at": at, "actor": actor, "action": action, "detail": detail}


def handoff(from_level, to_level, at, assigned_to="", lag_hours=None, via="bot"):
    """A tier hand-off as the pipeline records it. `lag_hours` None means the
    case is still waiting for somebody to take it."""
    assigned_at = dates.add_hours(at, lag_hours) if (assigned_to and lag_hours is not None) else ""
    return {"from": from_level, "to": to_level, "at": at, "assigned_to": assigned_to if assigned_at else "",
            "assigned_at": assigned_at, "lag_seconds": int(lag_hours * 3600) if assigned_at else None, "via": via}


def _level_for(status, pending_reason):
    if status in ("DataConfirming", "DataScreening"):
        return "L2" if pending_reason == "Pending Checker 2" else "L1"
    if status == "DataEscalatingL2":
        return "EDD" if pending_reason == "Pending EDD" else "L2"
    return ""


# ── KYC case ────────────────────────────────────────────────────────────────


def kyc_case(*, key, name, nationality, dob, tenant="ttlive", status="DataConfirming",
             id_type="Passport", issuing="", native_name="", gender="M", us_person=False,
             tags=("Creator G3",), poa_required=False, source=None,
             manual_review_reason=("Namescreen hit - WC or CMS",), created_hours_ago=20.0,
             vendor="shufti_pro_ios_webview", vendor_result="Approved", vendor_reason="",
             docs=None, address="", country="", phone="", email="",
             screening_hit=False, screening_key=None,
             l1=(), l2=(), edd=(), current_reviewer="", previous_reviewer="",
             pending_reason="", confirmed_hours_after=None, escalated_hours_after=None,
             closed_hours_after=None, agency=None, risk_rating="", case_review_level="L1",
             resubmit=None, extra_audit=(),
             routed_to="", routed_hours_after=None, handoffs=(), fraud_typology="", escalate_reason="",
             qc=None, poa_country="", confirmed=True):
    """One onboarding case.

    Timestamps are derived from `created_hours_ago`; the *_hours_after
    arguments place the later verification points relative to creation. A
    status past Data Confirming without a confirmed_hours_after gets a
    sensible default so the stepper is never missing a tick it should have.

    `routed_to` seeds an open case already given to an analyst by the router
    (with the routing chip and audit row that implies); `handoffs` seeds the
    tier hand-offs of an escalated case, so the pipeline's lag metrics have
    history; `qc` seeds a QC review on a closed case.
    """
    t = vocab.TENANTS[tenant]
    source = source or t["source"]
    created = dates.hours_ago(created_hours_ago)
    idv_at = dates.add_minutes(created, 2)
    screened_at = dates.add_minutes(created, 2.5)
    step = vocab.STATUS_STEP[status]

    if confirmed_hours_after is None and confirmed and (step >= 3 or status in vocab.CLOSED_STATUSES):
        confirmed_hours_after = 1.2
    confirmed_at = dates.add_hours(created, confirmed_hours_after) if confirmed_hours_after is not None else ""
    if escalated_hours_after is None and (step >= 4 and status != "Verified"):
        escalated_hours_after = (confirmed_hours_after or 1.2) + 0.6
    escalated_at = dates.add_hours(created, escalated_hours_after) if escalated_hours_after is not None else ""
    if closed_hours_after is None and status in vocab.CLOSED_STATUSES:
        closed_hours_after = (escalated_hours_after or confirmed_hours_after or 1.2) + 0.8
    closed_at = dates.add_hours(created, closed_hours_after) if closed_hours_after is not None else ""

    surname_first = name.upper()
    id_number = ids.id_number(key, id_type)
    extracted = {"name": surname_first, "dob": dob, "nationality": nationality, "id_number": id_number,
                 "id_type": id_type, "expiry": dates.add_days(dates.date_only(created) + " 00:00:00", 1460)[:10]}
    l1 = list(l1)
    docs = docs if docs is not None else std_docs("passport" if id_type == "Passport" else "national_id", poa_required)
    documents = []
    poa_default_days = 30 + ids._h(key, "poa") % 90
    for n, d in enumerate(docs, start=1):
        row = dict(d)
        row["id"] = ids.doc_id(n)
        if row["category"] == "ProofOfAddress":
            days = row.pop("issued_days_ago", None)
            days = poa_default_days if days is None else days
            row["issued_on"] = dates.add_days(created, -days)[:10]
            row["country"] = row.get("country") or poa_country or nationality
        documents.append(row)

    points = [
        {"label": "Submitted", "at": created},
        {"label": "ID Verification", "at": idv_at},
        {"label": "Data Confirming", "at": confirmed_at},
        {"label": "Data Screening", "at": screened_at},
        {"label": "Data Escalating L2", "at": escalated_at},
        {"label": "Completed", "at": closed_at},
    ]

    def decision(check_point, **kw):
        row = {"check_point": check_point, "decision": "", "fail_reason": "", "poa_fail_reason": "",
               "approve_reason": "", "rejection_reason": "", "id_summary": "", "report": "", "operated_at": "", "by": ""}
        row.update(kw)
        return row

    confirmer = l1[-1] if l1 else previous_reviewer
    escalate_reason = escalate_reason or ("Unresolved medium or high risk screening hit" if escalated_at else "")
    review_decisions = [
        decision("Submitted"),
        decision("System Review"),
        decision("Data Matching"),
        decision("Data Confirming", decision="Pass" if confirmed_at else "", operated_at=confirmed_at, by=confirmer if confirmed_at else ""),
        decision("Data Screening", operated_at=screened_at),
        decision("Data Escalating L2", decision="Escalated" if escalated_at else "", operated_at=escalated_at,
                 by=confirmer if escalated_at else "", rejection_reason=escalate_reason if escalated_at else ""),
    ]
    if status == "Verified":
        review_decisions[4].update(decision="False positive" if screening_hit else "No match",
                                   approve_reason="All alerts resolved" if screening_hit else "No screening hit",
                                   by=confirmer)
        review_decisions[5].update(decision="Approved" if escalated_at else "", approve_reason="EDD completed" if escalated_at else "")
    if status == "Rejected":
        review_decisions[5].update(decision="Rejected", rejection_reason=fraud_typology or "True positive confirmed")

    confirmations = {"name": None, "dob": None, "nationality": None, "poa": None}
    if confirmed_at:
        for fld, val in (("name", surname_first), ("dob", dob), ("nationality", nationality)):
            confirmations[fld] = {"value": val, "confirmed_by": confirmer, "at": confirmed_at, "edited": False}
        if poa_required:
            confirmations["poa"] = {"value": "checked", "confirmed_by": confirmer, "at": confirmed_at, "edited": False}

    alert_case_id = ids.alert_case_id(screening_key or key) if screening_hit else ""
    rows = [
        {"platform": "In-house CMS", "user_name": surname_first, "screen_time": screened_at,
         "list": "Law Enforcement/Special Interest Categories/Regulatory Enforcement" if screening_hit else "Sanctions/PEP/Adverse Media",
         "result": "Hit" if screening_hit else "No Match", "alert_id": alert_case_id},
        {"platform": "Internal_blacklist", "user_name": surname_first, "screen_time": screened_at,
         "list": "Internal_blacklist", "result": "No Match", "alert_id": ""},
    ]

    closed_by = (list(edd) or list(l2) or [confirmer or "system"])[-1] if closed_at else ""
    audit = [
        event(created, "system", "Case created", f"{source} submission received from the onboarding flow."),
        event(idv_at, vendor, "ID verification", f"Vendor result: {vendor_result}." + (f" {vendor_reason}" if vendor_reason else "")),
        event(screened_at, "screening", "Name screening run",
              "Hit on In-house CMS — screening case opened." if screening_hit else "No match on any list."),
    ]
    if confirmed_at:
        audit.append(event(confirmed_at, confirmer, "Data confirmed", "Name, date of birth and nationality confirmed against the document."))
    if escalated_at:
        audit.append(event(escalated_at, confirmer, "Escalated to L2",
                           f"{escalate_reason}." + (f" Fraud typology: {fraud_typology}." if fraud_typology else "")))
    if closed_at:
        audit.append(event(closed_at, closed_by, f"Case {status.lower()}", "Review complete."))
    audit.extend(extra_audit)

    # Tier hand-offs. Explicit ones come from the scenario; an escalated case
    # without any gets one L1 → L2 record still waiting for a taker, which is
    # exactly what bot allocation looked like.
    handoffs = [dict(h) for h in handoffs]
    if escalated_at and not handoffs:
        taker = (list(l2) or [""])[0] or (routed_to if status == "DataEscalatingL2" and pending_reason != "Pending EDD" else "")
        handoffs.append(handoff("L1", "L2", escalated_at, taker, 3.0 if taker else None, via="bot"))

    # Who held the case when — the entries the Productivity / Time Tracker shows.
    work = []
    level_now = _level_for(status, pending_reason)
    if confirmer and (confirmed_at or escalated_at or closed_at):
        start = dates.add_hours(created, 0.3)
        if escalated_at:
            end, outcome = escalated_at, "Escalated to L2"
        elif closed_at and not (l2 or edd):
            end, outcome = closed_at, f"Closed — {status}"
        elif routed_to == confirmer and level_now == "L1":
            end, outcome = "", ""
        else:
            end, outcome = confirmed_at, "Data confirmed"
        work.append({"level": "L1", "analyst": confirmer, "from": start, "to": end, "outcome": outcome})
    for h in handoffs:
        if not h.get("assigned_at"):
            continue
        level = h["to"]
        later = [x for x in handoffs if x["from"] == level and x["at"] > h["assigned_at"]]
        if later:
            end, outcome = later[0]["at"], f"Escalated to {later[0]['to']}"
        elif closed_at:
            end, outcome = closed_at, f"Closed — {status}"
        else:
            end, outcome = "", ""
        work.append({"level": level, "analyst": h["assigned_to"], "from": h["assigned_at"], "to": end, "outcome": outcome})

    routing = None
    current = current_reviewer
    if routed_to and status not in vocab.CLOSED_STATUSES:
        if routed_hours_after is None:
            base = escalated_at or confirmed_at or created
            routed_at = dates.add_minutes(base, 12) if base != created else dates.add_hours(created, 0.3)
        else:
            routed_at = dates.add_hours(created, routed_hours_after)
        analyst_rec = next((a for a in ANALYSTS if a["email"] == routed_to), None)
        script = "cyrillic" if any("Ѐ" <= ch <= "ӿ" for ch in native_name) else "latin"
        reason = f"{level_now} · {script} script{' · KYB' if agency else ''} · skill match"
        routing = {"status": "routed", "to": routed_to, "trigger": "seed", "reason": reason, "at": routed_at}
        current = routed_to
        if not any(w["analyst"] == routed_to and not w["to"] for w in work):
            work.append({"level": level_now, "analyst": routed_to, "from": routed_at, "to": "", "outcome": ""})
        audit.append(event(routed_at, "FCC Router", "Auto-routed",
                           f"→ {analyst_rec['name'] if analyst_rec else routed_to} · {reason} · Routed at intake"))
        for h in reversed(handoffs):
            if not h.get("assigned_at") and h["to"] == level_now:
                h.update(assigned_to=routed_to, assigned_at=routed_at, via="hub",
                         lag_seconds=int((dates.parse(routed_at) - dates.parse(h["at"])).total_seconds()))
                break
    audit.sort(key=lambda e: e["at"])

    qc_fields = {"qc_reviewer": "", "qc_result": "", "qc_reason": "", "qc_at": "", "qc_comment": "", "qc_ack": False}
    if qc and closed_at:
        qc_at = qc.get("at") or dates.add_hours(closed_at, 6)
        qc_fields.update(qc_reviewer=qc["reviewer"], qc_result=qc["result"], qc_reason=qc.get("reason", ""),
                         qc_at=qc_at, qc_comment=qc.get("comment", ""), qc_ack=bool(qc.get("ack")))
        audit.append(event(qc_at, qc["reviewer"], f"QC review: {qc['result']}", f"{qc.get('reason', '')}. {qc.get('comment', '')}".strip(". ")))
        if qc["result"] == "Fail" and not qc.get("ack"):
            pending_reason = "Pending QC"

    investigation_file = None
    if escalated_at:
        investigation_file = {"name": f"{ids.client_id(key)} ({ids.kyc_case_id(key)})", "created_at": escalated_at,
                              "created_by": confirmer}

    return {
        "id": ids.kyc_case_id(key), "key": key, "client_id": ids.client_id(key), "tenant": tenant,
        "tags": list(tags), "status": status, "pending_reason": pending_reason, "source": source,
        "manual_review_reason": list(manual_review_reason), "poa_required": bool(poa_required),
        "case_review_level": case_review_level,
        "created_at": created, "submitted_at": created,
        "sla_due_at": dates.add_hours(created, vocab.SLA_HOURS_L1),
        "escalated_at": escalated_at,
        "edd_due_at": dates.add_hours(escalated_at, vocab.SLA_HOURS_EDD) if escalated_at else "",
        "closed_at": closed_at, "closed_by": closed_by,
        "assigned_at": (routing or {}).get("at", "") or (dates.add_hours(created, 0.3) if current else ""),
        "current_reviewer": current, "previous_reviewer": previous_reviewer,
        "reviewers_by_level": {"L1": l1, "L2": list(l2), "EDD": list(edd)},
        **qc_fields,
        "client": {
            "legal_name": surname_first, "native_name": native_name, "dob": dob, "nationality": nationality,
            "gender": gender, "id_number": id_number, "id_type": id_type,
            "id_issuing_place": issuing or nationality, "phone": phone, "email": email,
            "us_person": bool(us_person), "address": address, "country": country or nationality,
        },
        "agency": agency,
        "vendor_check": {"vendor": vendor, "result": vendor_result, "vendor_reason": vendor_reason,
                         "extracted": extracted, "checked_at": idv_at},
        "documents": documents,
        "confirmations": confirmations,
        "verification_points": points,
        "review_decisions": review_decisions,
        "screening": {"hit": bool(screening_hit), "alert_case_id": alert_case_id, "rows": rows},
        "risk_rating": risk_rating, "risk_recalculated_at": "",
        "skopenow": None, "attachments": [], "resubmit": resubmit,
        "fraud_typology": fraud_typology, "escalate_reason": escalate_reason if escalated_at else "",
        "routing": routing, "work": work, "handoffs": handoffs,
        "investigation_file": investigation_file, "checker1": None, "checker2": None,
        "audit": audit, "change_log": [],
    }


def agency_info(*, company, registration_number, incorporation_country, address, representative,
                rep_email="", rep_phone="", ubos=(), agency_id="", agency_name="", onboarding_time=""):
    return {
        "agency_id": agency_id, "agency_name": agency_name, "onboarding_time": onboarding_time,
        "company_name": company, "registration_number": registration_number,
        "incorporation_country": incorporation_country, "registered_address": address,
        "representative": representative, "email": rep_email, "phone": rep_phone,
        "ubos": [{"name": n, "pct": p, "nationality": c} for n, p, c in ubos],
    }


# ── World-Check (simulated) ─────────────────────────────────────────────────


def wc_match(*, key, name, alias="", strength=0.9, types=("SIC",), gender="Male", dobs=(), pob="",
             citizenship="", country="", category="", sub_category="", pep_status="",
             special_interest=(), position="", location=None, bio="", identification="",
             reports=(), aliases=(), keywords=(), sources=(), entered="2014-10-29", updated="2020-12-09"):
    return {
        "id": ids.wc_id(key), "wc_id": ids.wc_id(key), "name": name, "matched_alias": alias,
        "strength": float(strength), "types": list(types), "gender": gender, "dobs": list(dobs),
        "pob": pob, "citizenship": citizenship, "country": country or citizenship,
        "entered": entered, "updated": updated, "matched": "",
        "resolution": {"status": "Unresolved", "risk": "", "reason": "", "remark": "", "comment": "", "by": "", "at": ""},
        "key_data": {"category": category, "sub_category": sub_category, "pep_status": pep_status,
                     "special_interest": list(special_interest), "position": position, "location": location or {}},
        "further_info": {"biography": bio, "identification": identification, "reports": [list(r) for r in reports]},
        "aliases": list(aliases), "keywords": list(keywords), "sources": [list(s) for s in sources],
    }


def auto_fp(match, remark="Date of Birth mismatch", at=""):
    """A match the screening rules cleared before any analyst saw it."""
    match["resolution"] = {"status": "False positive", "risk": "Low", "reason": remark, "remark": remark,
                           "comment": "Auto-resolved by screening rule.", "by": "System User", "at": at}
    return match


def resolved(match, status, risk, reason, by, at, comment=""):
    match["resolution"] = {"status": status, "risk": risk, "reason": reason, "remark": reason,
                           "comment": comment, "by": by, "at": at}
    return match


_OUTCOME_FOR = {"False positive": "False Positive", "Potential match": "Potential Match",
                "True positive": "True Positive"}
_LABEL_FOR = {"False positive": "False Positive", "Potential match": "Potential Match",
              "True positive": "True Positive"}
_RATIONALE_FOR = {"Date of Birth mismatch": "DOB Mismatch", "Nationality mismatch": "Nationality Mismatch",
                  "Gender mismatch": "Gender Mismatch", "Name mismatch": "Name Mismatch",
                  "Confirmed by identification": "Confirmed Identity", "Confirmed by adverse media": "Same Person - Adverse Media"}


def alert_from_match(key, i, match, screened_at):
    res = match["resolution"]
    auto = res["by"] == "System User"
    outcome = _OUTCOME_FOR.get(res["status"], "Pending")
    return {
        "id": ids.alert_id(f"{key}-{i}"), "match_id": match["id"], "vendor": "WC",
        "watchlist_id": match["wc_id"], "outcome": outcome,
        "review_mode": "Smart Review" if auto else ("Manual Review" if outcome != "Pending" else ""),
        "result_label": _LABEL_FOR.get(res["status"], ""),
        "rationale": _RATIONALE_FOR.get(res["reason"], res["reason"]) if outcome != "Pending" else "",
        "comment": res["comment"] if outcome != "Pending" else "",
        "risk_level": res["risk"] if outcome != "Pending" else "",
        "attachment": "", "resolved_by": res["by"], "resolved_at": res["at"],
        "smart_strategy": "DOB mismatch" if auto else "",
        "name": match["name"], "matched_alias": match["matched_alias"] or match["name"],
        "score": round(match["strength"] * 100, 2), "type": match["types"][0] if match["types"] else "",
        "dob": match["dobs"][0] if match["dobs"] else "", "gender": match["gender"],
    }


def alert_case(*, kyc, key, matches, level=None, status="Init", assigned_to="", case_outcome=None,
               handled_at=""):
    t = vocab.TENANTS[kyc["tenant"]]
    screened_at = kyc["verification_points"][3]["at"]
    c = kyc["client"]
    alerts = [alert_from_match(key, i, m, screened_at) for i, m in enumerate(matches)]
    audit = [event(screened_at, "screening", "Screening case created", f"{len(matches)} watchlist match(es) returned.")]
    if handled_at:
        audit.append(event(handled_at, assigned_to, "Case handled", "Analyst took the case."))
    if case_outcome:
        audit.append(event(case_outcome["at"], case_outcome["by"], "Case outcome", case_outcome["value"]))
    # A screening case whose KYC case was escalated sits at L2 (SOP 2.1: L2
    # conducts the deep-dive on escalation hits).
    if level is None:
        level = "L2" if kyc.get("escalated_at") else "L1"
    return {
        "id": ids.alert_case_id(key), "key": key, "kyc_case_id": kyc["id"], "case_level": level,
        "status": status, "assigned_to": assigned_to, "created_at": screened_at,
        "wc_group": t["wc_group"], "business_line": t["business_line"], "event": t["event"],
        "merchant_uid": kyc["client_id"], "is_test": "No", "kyc_triggered": "No", "need_audit": "Need Audit",
        "last_screen_time": screened_at, "latest_updated": handled_at or screened_at,
        "screening_info": {
            "search_type": "Individual" if kyc["agency"] is None else "Entity",
            "name": c["legal_name"], "dob": c["dob"], "gender": "Female" if c["gender"] == "F" else "Male",
            "country": c["country"], "registered_country": c["country"] if kyc["agency"] else "",
            "nationality": c["nationality"], "pob": "", "id_type": c["id_type"], "id_number": c["id_number"],
        },
        "platform_rows": [dict(r) for r in kyc["screening"]["rows"]],
        "alerts": alerts, "case_outcome": case_outcome, "rfi": [], "audit": audit,
    }


def wc_case(*, alert, kyc, matches, assignee="Case Unassigned", rating="Not Rated"):
    t = vocab.TENANTS[kyc["tenant"]]
    c = kyc["client"]
    screened_at = kyc["verification_points"][3]["at"]
    for m in matches:
        m["matched"] = m["matched"] or screened_at
        if m["resolution"]["by"] == "System User" and not m["resolution"]["at"]:
            m["resolution"]["at"] = screened_at
    return {
        "id": alert["id"], "key": alert["key"], "alert_case_id": alert["id"], "kyc_case_id": kyc["id"],
        "primary_name": c["legal_name"], "gender": "Female" if c["gender"] == "F" else "Male", "dob": c["dob"],
        "group": t["wc_group"], "assignee": assignee, "rating": rating, "ongoing_screening": "Daily",
        "last_updated": screened_at,
        "case_details": {
            "MCF01": ids.mcf_id(alert["key"]), "ManuallyReview": "true", "EventName": t["event"],
            "Version": "20240314", "KYCStatus": kyc["status"], "BusinessLine": t["business_line"],
            "UserID": kyc["client_id"], "RequestID": ids.request_id(alert["key"]),
        },
        "matches": matches, "exports": [],
        "audit": [event(screened_at, "screening", "Case screened", f"{len(matches)} record(s) matched; ongoing screening daily.")],
    }


# ── Generators ──────────────────────────────────────────────────────────────

_FIRST_VARIANTS = {
    "Ahmed": ["Ahmed", "Ahmad", "Ahmed Ali", "Ahmed Bilal", "Ahmed Raza", "Ahmed Khan"],
}
_PK_CITIES = ["Karachi", "Lahore", "Peshawar", "Islamabad", "Quetta", "Faisalabad", "Multan"]
_PK_REGIONS = {"Karachi": "Sindh", "Lahore": "Punjab", "Peshawar": "Khyber Pakhtunkhwa", "Islamabad": "Islamabad Capital Territory",
               "Quetta": "Balochistan", "Faisalabad": "Punjab", "Multan": "Punjab"}
_SIC_POOL = ["Fraud", "Violent Crime", "Terror Related", "Conspiracy or Collusion", "Human Rights Violation",
             "Crimes Against the State", "Narcotics Trafficking", "Illegal Possession or Sale", "Organised Crime"]


def auto_fp_matches(*, first, surname, n=212, seed="common", dob_years=(1958, 2008), citizenship="Pakistan",
                    cities=None, keep_unresolved=3, screened_at=""):
    """`n` watchlist records for a very common name. All but the last
    `keep_unresolved` are auto-resolved as date-of-birth mismatches, the way a
    screening rule clears the obvious ones before an analyst sees the case."""
    rng = random.Random(seed)
    cities = cities or _PK_CITIES
    variants = _FIRST_VARIANTS.get(first, [first, f"{first} Ali", f"{first} Khan"])
    out = []
    for i in range(n):
        given = rng.choice(variants)
        name = f"{given} {surname.upper()}"
        alias = f"{surname.upper()}, {given}" if rng.random() < 0.3 else ""
        year = rng.randint(*dob_years)
        types = rng.choice([("SIC",), ("SIC", "OB"), ("LE",), ("LE", "SIC"), ("RE",), ("PEP",)])
        city = rng.choice(cities)
        m = wc_match(
            key=f"{seed}-{i}", name=name, alias=alias, strength=round(rng.uniform(0.72, 0.99), 2),
            types=types, gender="Male", dobs=[str(year)] if rng.random() < 0.85 else [],
            citizenship=citizenship, country=citizenship,
            category="POST CONVICTION" if "SIC" in types or "LE" in types else ("PEP" if "PEP" in types else "REGULATORY"),
            sub_category="PEP Sub-National Government" if "PEP" in types else "",
            special_interest=rng.sample(_SIC_POOL, k=rng.randint(1, 3)) if "SIC" in types else [],
            location={"city": city, "region": _PK_REGIONS.get(city, ""), "country": f"{citizenship} (PAK)"},
            entered=f"{rng.randint(2005, 2024)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            updated=f"{rng.randint(2022, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        )
        if i < n - keep_unresolved:
            auto_fp(m, at=screened_at)
        out.append(m)
    return out


_FILLER_PEOPLE = [
    ("Lucas Ferreira", "BR", "Passport", "1993-04-02", "M"), ("Hannah Schmidt", "DE", "NationalID", "1990-11-23", "F"),
    ("Kenji Sato", "JP", "Passport", "1987-06-30", "M"), ("Priya Menon", "IN", "Passport", "1996-01-17", "F"),
    ("Oliver Brooks", "GB", "DrivingLicense", "1985-09-09", "M"), ("Camila Torres", "CO", "NationalID", "1998-12-05", "F"),
    ("Noah Williams", "US", "DrivingLicense", "1992-03-14", "M"), ("Aisha Bello", "NG", "Passport", "1994-07-21", "F"),
    ("Mateo Rossi", "IT", "NationalID", "1989-02-28", "M"), ("Yuki Tanaka", "JP", "Passport", "1999-10-10", "F"),
    ("Liam O'Connor", "IE", "Passport", "1991-05-19", "M"), ("Sara Haddad", "LB", "Passport", "1995-08-08", "F"),
    ("Ethan Clarke", "AU", "DrivingLicense", "1988-12-12", "M"), ("Ines Moreau", "FR", "NationalID", "1997-03-03", "F"),
    ("Daniel Park", "KR", "Passport", "1990-07-07", "M"), ("Zara Ahmed", "GB", "Passport", "2001-01-25", "F"),
    ("Tomas Novak", "CZ", "NationalID", "1986-04-16", "M"), ("Leila Nasser", "EG", "Passport", "1993-09-27", "F"),
    ("Arjun Patel", "IN", "Passport", "1984-06-06", "M"), ("Emma Larsen", "DK", "NationalID", "1996-11-11", "F"),
    ("Diego Alvarez", "MX", "NationalID", "1992-02-02", "M"), ("Chloe Dubois", "FR", "Passport", "1998-05-05", "F"),
    ("Samuel Adeyemi", "NG", "DrivingLicense", "1987-08-18", "M"), ("Mia Andersson", "SE", "NationalID", "1994-10-30", "F"),
    ("Rafael Costa", "PT", "NationalID", "1991-12-01", "M"), ("Anya Volkova", "KZ", "Passport", "1995-04-22", "F"),
    ("Ibrahim Khalil", "MA", "Passport", "1989-01-09", "M"), ("Grace Kim", "US", "Passport", "1997-06-15", "F"),
]

_FILLER_SELLERS = [
    ("Sunrise Home Goods LLC", "US", "Ava Robinson"), ("Lumen Beauty Trading Sdn Bhd", "MY", "Nur Aisyah"),
    ("Northwind Apparel Ltd", "GB", "James Whitfield"), ("Bayline Electronics Pte Ltd", "SG", "Wei Ling Ong"),
    ("Casa Verde Decor SA de CV", "MX", "Valeria Ortiz"), ("Kite & Co Toys GmbH", "DE", "Jonas Weber"),
    ("Orchid Lane Cosmetics FZ-LLC", "AE", "Maryam Al Ali"), ("Pine Street Books Inc", "CA", "Owen Fraser"),
]

_INTAKE = [("Sofia Bianchi", "IT", "Passport", "1995-09-12", "F"), ("Marcus Oyelaran", "NG", "NationalID", "1990-02-27", "M")]


def filler_cases(seed="filler"):
    """Background rows so the list paginates and the analytics have volume.
    Mostly closed; a few open with no screening hit, so nothing here needs a
    screening or watchlist case. The open screening-stage ones are already
    routed, so My Work and the pipeline have something to show at boot; the
    Data Confirming ones are left for the presenter to pull."""
    rng = random.Random(seed)
    out = []
    statuses = ["Verified"] * 12 + ["DataScreening"] * 4 + ["DataConfirming"] * 4 + ["ResubmitID", "ResubmitPOA", "Rejected", "Verified"]
    for i, (name, nat, id_type, dob, gender) in enumerate(_FILLER_PEOPLE):
        status = statuses[i % len(statuses)]
        hours = rng.uniform(6, 240) if status in vocab.CLOSED_STATUSES else rng.uniform(2, 40)
        l1 = [rng.choice([AMARA, JON, MARIO])] if i else [AMARA]
        qc = None
        if i == 0:
            qc = {"reviewer": LEAH, "result": "Fail", "reason": "Rationale insufficient",
                  "comment": "Closing note says 'ok' — the SOP asks for a single line saying what was checked and why it clears."}
        elif status == "Verified" and i % 5 == 2:
            qc = {"reviewer": LEAH, "result": "Pass", "reason": "Decision correct and evidenced", "comment": "Rationale and evidence complete."}
        case = kyc_case(
            key=f"{seed}-{i}", name=name, nationality=nat, dob=dob, id_type=id_type, gender=gender,
            tags=[rng.choice(vocab.TAGS[:4])], status=status,
            poa_required=rng.random() < 0.3, manual_review_reason=[rng.choice(["Manual referral", "Age verification", "Vendor rejected", "Duplicate account"])],
            created_hours_ago=hours, vendor=rng.choice(vocab.VENDORS),
            l1=l1 if status not in ("DataConfirming",) else [],
            previous_reviewer=l1[0] if status not in ("DataConfirming",) else "",
            pending_reason="Pending Resubmission" if status.startswith("Resubmit") else "",
            docs=std_docs("passport" if id_type == "Passport" else ("driving_licence" if id_type == "DrivingLicense" else "national_id"), rng.random() < 0.3),
            routed_to=l1[0] if status == "DataScreening" else "",
            qc=qc,
        )
        out.append(case)
    for i, (name, nat, id_type, dob, gender) in enumerate(_INTAKE):
        out.append(kyc_case(key=f"{seed}-intake-{i}", name=name, nationality=nat, dob=dob, id_type=id_type, gender=gender,
                            tags=["Creator G3"], status="IDVerification", manual_review_reason=["Manual referral"],
                            created_hours_ago=0.2 + i * 0.4, vendor=rng.choice(vocab.VENDORS)))
    for i, (company, country, rep) in enumerate(_FILLER_SELLERS):
        status = ["Verified", "Verified", "DataScreening", "DataConfirming", "Verified", "Rejected", "Verified", "DataScreening"][i]
        hours = rng.uniform(6, 200) if status in vocab.CLOSED_STATUSES else rng.uniform(3, 30)
        l1 = [rng.choice([JON, MARIO])]
        case = kyc_case(
            key=f"{seed}-shop-{i}", name=company, nationality=country, dob="", tenant="ttshop", status=status,
            id_type="TradeLicense", gender="", tags=["Agency"] if i % 3 == 0 else ["Priority Review"],
            poa_required=True, manual_review_reason=["Manual referral"], created_hours_ago=hours,
            vendor="shufti_pro_android_webview", l1=l1 if status != "DataConfirming" else [],
            previous_reviewer=l1[0] if status != "DataConfirming" else "",
            docs=[doc("trade_licence", "page 1"), doc("passport", "front"), doc("utility_bill", "page 1")],
            agency=agency_info(company=company, registration_number=f"{country}-{rng.randint(100000, 999999)}",
                               incorporation_country=country, address=f"{rng.randint(1, 400)} Commerce Street, {country}",
                               representative=rep, ubos=[(rep, 100, country)]),
            risk_rating=rng.choice(["Low", "Medium"]),
            routed_to=l1[0] if status == "DataScreening" and i == 2 else "",
        )
        out.append(case)
    return out


def assemble():
    """(analysts, kyc_cases, alert_cases, wc_cases) — fresh objects every call.
    Analysts are deep-copied: a capacity edited at runtime lives on the app's
    copy and must not leak into the module-level roster that /reset rebuilds."""
    from fincrime.data import scenarios   # lazy: scenarios imports the builders above
    kyc, alerts, wc = scenarios.build()
    kyc = kyc + filler_cases()
    return copy.deepcopy(ANALYSTS), kyc, alerts, wc
