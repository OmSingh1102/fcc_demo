"""The KYC case state machine.

Every analyst action on a case is a function here. Each one validates the
state it needs, refuses with a WorkflowError it does not, mutates the record
in place, and appends an audit event — so nothing changes on a case without a
line in its history saying who did it and why. The routes stay thin: gather
the form, call one of these, save, redirect.

Two rules the earlier prototype got wrong are enforced here on purpose:
every outcome needs the analyst's own comment (nothing is ever written into
the audit trail on their behalf), and `reviewers_by_level` is append-only so
the segregation check still knows who touched a case at L1 after it has been
returned and picked up by somebody else.

    Submitted → IDVerification → DataConfirming ──OK──▶ DataScreening ──review: FP / no match──▶ Verified
                                      │  │                     │
                                      │  └─Resubmit─▶ ResubmitID / ResubmitPOA
                                      └────Escalate─▶ DataEscalatingL2 ◀──review: TP / potential match──┘
                                                              └─ L2/EDD: Approve → Verified | Reject → Rejected | Escalate to EDD
"""
from fincrime.adapters import cms, skopenow
from fincrime.data import vocab
from fincrime.engines import segregation
from fincrime.engines.errors import WorkflowError
from fincrime.utils import dates

HIGH_RISK_COUNTRIES = {"RU", "IR", "KP", "SY", "AF", "MM", "BY", "VE", "CU"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _audit(case, actor, action, detail=""):
    case.setdefault("audit", []).append({"at": dates.now_str(), "actor": actor, "action": action, "detail": detail})


def _change(case, actor, field, before, after):
    case.setdefault("change_log", []).append({"at": dates.now_str(), "by": actor, "field": field,
                                             "from": before, "to": after})


def _point(case, label, at=None):
    for p in case["verification_points"]:
        if p["label"] == label:
            p["at"] = at or dates.now_str()
            return


def _decision(case, check_point, **fields):
    for row in case["review_decisions"]:
        if row["check_point"] == check_point:
            row.update(fields)
            return


def _touch_level(case, level, actor):
    levels = case.setdefault("reviewers_by_level", {"L1": [], "L2": [], "EDD": []})
    if actor and actor not in levels.setdefault(level, []):
        levels[level].append(actor)


def _require(condition, message):
    if not condition:
        raise WorkflowError(message)


def _require_text(value, what):
    if not (value or "").strip():
        raise WorkflowError(f"{what} is required.")
    return value.strip()


def _require_open(case):
    _require(case["status"] not in vocab.CLOSED_STATUSES, "This case is closed.")


def _require_reserved(case, actor):
    _require(case["current_reviewer"] == actor,
             "Reserve the case first — only the current reviewer can act on it.")


def _hand_back(case, actor):
    """The reviewer's turn is over: they become the previous reviewer."""
    case["previous_reviewer"] = actor
    case["current_reviewer"] = ""


# ── read models ──────────────────────────────────────────────────────────────

def verification_points(case):
    """The six steps with a state each: done | current | todo."""
    status = case["status"]
    step = vocab.STATUS_STEP.get(status, 0)
    closed = status in vocab.CLOSED_STATUSES
    out = []
    for i, p in enumerate(case["verification_points"]):
        # A case that closed without ever being escalated shows five steps,
        # not six — the L2 step drops out, as it does on the real page.
        if closed and p["label"] == "Data Escalating L2" and not p["at"]:
            continue
        if closed:
            state = "done"
        elif i < step:
            state = "done"
        elif i == step:
            state = "current"
        else:
            state = "todo"
        out.append({"label": p["label"], "at": p["at"], "state": state, "n": i + 1})
    return out


def review_action(case, levels):
    """Which modal the Review button opens for an analyst holding `levels`."""
    s = case["status"]
    if s == "DataConfirming" and "L1" in levels:
        return "dc"
    if s == "DataScreening" and levels & {"L1", "L2"}:
        return "edd"
    if s == "DataEscalatingL2" and levels & {"L2", "EDD"}:
        return "l2"
    return ""


# ── ownership ────────────────────────────────────────────────────────────────

def reserve(case, actor):
    _require_open(case)
    _require(not case["current_reviewer"] or case["current_reviewer"] == actor,
             f"Already reserved by {case['current_reviewer']}. Ask them to release it or use Assign to Others.")
    case["current_reviewer"] = actor
    _audit(case, actor, "Reserved", "Case reserved for review.")


def release(case, actor):
    _require(case["current_reviewer"], "The case is not reserved.")
    _require(case["current_reviewer"] == actor, "Only the current reviewer can release the case.")
    case["current_reviewer"] = ""
    _audit(case, actor, "Released", "Case returned to the queue.")


def assign(case, actor, assignee):
    _require_open(case)
    assignee = _require_text(assignee, "An assignee")
    before = case["current_reviewer"]
    case["current_reviewer"] = assignee
    _audit(case, actor, "Assigned", f"Assigned to {assignee}" + (f" (was {before})" if before else "") + ".")


# ── L1: data confirming ──────────────────────────────────────────────────────

CONFIRM_FIELDS = (("name", "legal_name", "Name", "text"), ("dob", "dob", "Birthday", "date"),
                  ("nationality", "nationality", "Nationality", "text"))
CONFIRM_FIELDS_KYB = (("name", "legal_name", "Legal name", "text"), ("id_number", "id_number", "Registration number", "text"),
                      ("nationality", "nationality", "Country of incorporation", "text"))


def confirm_fields(case):
    """(form field, client key, label, input type) × 3 — a person confirms
    name / birthday / nationality; a seller confirms name / registration /
    country of incorporation."""
    return CONFIRM_FIELDS_KYB if case.get("agency") else CONFIRM_FIELDS


def data_confirm(case, actor, form):
    """OK on the Data Confirm modal: all three fields confirmed (or edited and
    confirmed), optional summary and attachment. Moves the case to Data
    Screening and re-runs the name screen on the confirmed data."""
    _require(case["status"] == "DataConfirming", "Data confirming is only available while the case is in Data Confirming.")
    _require_reserved(case, actor)
    now = dates.now_str()
    edited = []
    for field, client_key, label, _type in confirm_fields(case):
        _require(form.get(f"{field}_ok") == "1", f"Confirm {label} before pressing OK.")
        value = _require_text(form.get(field, ""), label)
        if field == "dob":
            _require(dates.parse(value) is not None, "Birthday must be a date (YYYY-MM-DD).")
        before = case["client"].get(client_key, "")
        changed = value != before
        if changed:
            _change(case, actor, label, before, value)
            case["client"][client_key] = value
            edited.append(label)
        case["confirmations"][field] = {"value": value, "confirmed_by": actor, "at": now, "edited": changed}
    summary = (form.get("summary") or "").strip()[:200]
    attachment = (form.get("attachment_name") or "").strip()
    if attachment:
        case["attachments"].append({"name": attachment, "at": now, "by": actor, "ref": "data_confirm"})

    _point(case, "Data Confirming", now)
    _decision(case, "Data Confirming", decision="Pass", operated_at=now, by=actor,
              id_summary=summary, report=attachment)
    _touch_level(case, "L1", actor)
    case["status"] = "DataScreening"
    case["pending_reason"] = ""
    # The tool re-screens on the confirmed data; the second run appears as a
    # further pair of rows under Screening Result.
    case["screening"]["rows"].extend(cms.rescreen_rows(case, now))
    detail = "Name, date of birth and nationality confirmed against the document."
    if edited:
        detail += f" Edited: {', '.join(edited)}."
    if summary:
        detail += f" Summary: {summary}"
    _audit(case, actor, "Data confirmed", detail)


def resubmit(case, actor, decisions, id_reason, poa_reason, note):
    """Ask the user to upload again. The case leaves the queue; the intake
    SLA clock keeps running."""
    _require(case["status"] == "DataConfirming", "Resubmission can only be requested during Data Confirming.")
    _require_reserved(case, actor)
    decisions = [d for d in (decisions or []) if d in ("Resubmit ID", "Resubmit POA")]
    _require(decisions, "Choose what the user must resubmit.")
    if "Resubmit ID" in decisions:
        _require(id_reason in vocab.RESUBMIT_ID_REASONS, "Pick a Resubmit ID reason.")
    if "Resubmit POA" in decisions:
        _require(poa_reason in vocab.RESUBMIT_POA_REASONS, "Pick a Resubmit POA reason.")
    now = dates.now_str()
    prior = (case.get("resubmit") or {}).get("count", 0)
    case["resubmit"] = {"decisions": decisions, "id_reason": id_reason if "Resubmit ID" in decisions else "",
                        "poa_reason": poa_reason if "Resubmit POA" in decisions else "", "note": (note or "").strip(),
                        "at": now, "by": actor, "count": prior + 1}
    case["status"] = "ResubmitID" if "Resubmit ID" in decisions else "ResubmitPOA"
    case["pending_reason"] = "Pending Resubmission"
    _decision(case, "Data Confirming", decision="Resubmit", operated_at=now, by=actor,
              fail_reason=case["resubmit"]["id_reason"], poa_fail_reason=case["resubmit"]["poa_reason"])
    _touch_level(case, "L1", actor)
    _hand_back(case, actor)
    reasons = "; ".join(r for r in (case["resubmit"]["id_reason"], case["resubmit"]["poa_reason"]) if r)
    _audit(case, actor, "Resubmission requested",
           f"{', '.join(decisions)} (#{prior + 1}). {reasons}" + (f" Note: {note.strip()}" if (note or '').strip() else ""))


def escalate(case, actor, reason, comment):
    _require(case["status"] in ("DataConfirming", "DataScreening"),
             "Only a case in Data Confirming or Data Screening can be escalated from L1.")
    _require_reserved(case, actor)
    _require(reason in vocab.ESCALATE_REASONS, "Pick an escalation reason.")
    comment = _require_text(comment, "A comment")
    now = dates.now_str()
    case["status"] = "DataEscalatingL2"
    case["pending_reason"] = "Pending L2"
    case["case_review_level"] = "L2"
    case["escalated_at"] = now
    case["edd_due_at"] = dates.add_hours(now, vocab.SLA_HOURS_EDD)
    _point(case, "Data Escalating L2", now)
    _decision(case, "Data Escalating L2", decision="Escalated", operated_at=now, by=actor, rejection_reason=reason)
    _touch_level(case, "L1", actor)
    _hand_back(case, actor)
    _audit(case, actor, "Escalated to L2", f"{reason}. {comment}")


def rfi(case, actor, message):
    _require_open(case)
    _require_reserved(case, actor)
    message = _require_text(message, "The RFI message")
    case["pending_reason"] = "RFI Sent"
    case.setdefault("rfi", []).append({"at": dates.now_str(), "by": actor, "message": message, "status": "Sent"})
    _audit(case, actor, "RFI sent", message)


# ── L1: screening review ─────────────────────────────────────────────────────

def edd_review(case, actor, decision, summary, attachment, alert_case=None):
    """OK on the EDD Review modal, after the screening case is dealt with."""
    _require(case["status"] == "DataScreening", "The screening review is only available while the case is in Data Screening.")
    _require_reserved(case, actor)
    summary = _require_text(summary, "A summary")
    hit = case["screening"]["hit"]
    options = list(vocab.EDD_DECISIONS) + (["No match - Approve"] if not hit else [])
    _require(decision in options, "Pick a decision.")
    now = dates.now_str()

    if hit and alert_case is not None and decision in ("False positive", "No match - Approve"):
        pending = [a for a in alert_case["alerts"] if a["outcome"] == "Pending"]
        _require(not pending, f"{len(pending)} screening alert(s) are still pending. Resolve them in the screening case first.")
        _require(alert_case.get("case_outcome"), "Record the screening case outcome before closing the KYC case.")
        _require(attachment, "Attach the World-Check export to the review.")

    if decision in ("False positive", "No match - Approve", "Approve after Skopenow"):
        if decision == "Approve after Skopenow":
            _require((case.get("skopenow") or {}).get("status") == "Cleared",
                     "The Skopenow report has not cleared this person yet.")
        _close(case, actor, "Verified", now, decision, summary, attachment)
        return
    if decision == "Request Skopenow report":
        _require(case["client"]["us_person"], "Skopenow reports are only requested for US persons (SOP 4.1.3). Escalate instead.")
        case["pending_reason"] = "Pending Skopenow"
        case["skopenow"] = skopenow.request_report(case, actor)
        _touch_level(case, "L1", actor)
        _audit(case, actor, "Skopenow report requested", summary)
        return
    # True positive / potential match: hand to L2.
    reason = "Unresolved medium or high risk screening hit" if decision.startswith("Potential") else "Other"
    if attachment:
        case["attachments"].append({"name": attachment, "at": now, "by": actor, "ref": "edd_review"})
    _decision(case, "Data Screening", decision=decision, operated_at=now, by=actor, id_summary=summary, report=attachment)
    escalate(case, actor, reason, summary)


def _close(case, actor, status, now, decision, summary, attachment=""):
    case["status"] = status
    case["pending_reason"] = ""
    case["closed_at"] = now
    _point(case, "Completed", now)
    if attachment:
        case["attachments"].append({"name": attachment, "at": now, "by": actor, "ref": "edd_review"})
    _decision(case, "Data Screening", decision=decision, operated_at=now, by=actor,
              approve_reason=summary if status == "Verified" else "", id_summary=summary, report=attachment)
    _touch_level(case, "L1", actor)
    _hand_back(case, actor)
    _audit(case, actor, f"Case {status.lower()}", f"{decision}. {summary}")


def skopenow_clear(case, actor, outcome, notes):
    _require((case.get("skopenow") or {}).get("status") == "Requested", "No Skopenow report is outstanding.")
    _require_reserved(case, actor)
    notes = _require_text(notes, "Your review of the report")
    _require(outcome in ("Cleared", "Inconclusive"), "Pick an outcome.")
    case["skopenow"] = skopenow.complete_report(case["skopenow"], outcome, actor, notes)
    case["pending_reason"] = "" if outcome == "Cleared" else "Pending L2"
    _audit(case, actor, f"Skopenow report {outcome.lower()}", notes)
    if outcome == "Inconclusive":
        escalate(case, actor, "Inconclusive Skopenow report", notes)


# ── L2 / EDD ─────────────────────────────────────────────────────────────────

def l2_decision(case, actor, level, decision, comment):
    """Approve / Reject / Escalate to EDD at L2, or Approve / Reject at EDD."""
    _require(case["status"] == "DataEscalatingL2", "Only an escalated case can be decided here.")
    _require(level in ("L2", "EDD"), "Unknown level.")
    _require_reserved(case, actor)
    segregation.assert_may_decide(case, actor, level)
    comment = _require_text(comment, "A comment")
    _require(decision in vocab.L2_DECISIONS, "Pick a decision.")
    if level == "EDD":
        _require(case["pending_reason"] == "Pending EDD", "This case has not been escalated to EDD.")
        _require(decision != "Escalate to EDD", "The case is already at EDD.")
    now = dates.now_str()
    _touch_level(case, level, actor)
    if decision == "Escalate to EDD":
        case["pending_reason"] = "Pending EDD"
        case["case_review_level"] = "L3"
        case["current_reviewer"] = ""
        case["previous_reviewer"] = actor
        _decision(case, "Data Escalating L2", decision="Escalated to EDD", operated_at=now, by=actor, rejection_reason=comment)
        _audit(case, actor, "Escalated to EDD", comment)
        return
    status = "Verified" if decision == "Approve" else "Rejected"
    case["status"] = status
    case["pending_reason"] = ""
    case["closed_at"] = now
    _point(case, "Completed", now)
    _decision(case, "Data Escalating L2", decision="Approved" if status == "Verified" else "Rejected",
              operated_at=now, by=actor,
              approve_reason=comment if status == "Verified" else "", rejection_reason=comment if status == "Rejected" else "")
    case["previous_reviewer"] = actor
    case["current_reviewer"] = ""
    _audit(case, actor, f"{level} decision: {decision}", comment)


# ── TT Shop: Checker 1 ───────────────────────────────────────────────────────

def recalculate_risk(case, actor):
    """SOP 4.2.2: recalculate the seller's risk rating before approving."""
    _require(case["tenant"] == "ttshop", "Risk rating recalculation applies to TT Shop sellers.")
    score = 0
    reasons = []
    agency = case.get("agency") or {}
    for ubo in agency.get("ubos", []):
        if ubo.get("nationality") in HIGH_RISK_COUNTRIES:
            score += 2
            reasons.append(f"UBO {ubo['name']} ({ubo['nationality']}) is in a high-risk jurisdiction")
        if ubo.get("pct", 0) >= 50 and ubo.get("nationality") in HIGH_RISK_COUNTRIES:
            score += 1
            reasons.append("majority owner in a high-risk jurisdiction")
    if case["client"]["nationality"] in HIGH_RISK_COUNTRIES:
        score += 2
        reasons.append("incorporated in a high-risk jurisdiction")
    if case["screening"]["hit"]:
        score += 1
        reasons.append("open screening hit")
    if case["status"] == "DataEscalatingL2":
        score += 1
        reasons.append("escalated")
    rating = "High" if score >= 3 else ("Medium" if score >= 1 else "Low")
    before = case["risk_rating"]
    case["risk_rating"] = rating
    case["risk_recalculated_at"] = dates.now_str()
    _change(case, actor, "Risk rating", before, rating)
    _audit(case, actor, "Risk rating recalculated", f"{before or 'unrated'} → {rating}. " + ("; ".join(reasons) if reasons else "No risk factors."))
    return rating


def set_pending(case, actor, reason):
    _require(reason in vocab.PENDING_REASONS, "Unknown pending reason.")
    before = case["pending_reason"]
    case["pending_reason"] = reason
    _audit(case, actor, "Pending reason set", f"{before or '-'} → {reason or '-'}")


# ── small edits ──────────────────────────────────────────────────────────────

def add_tag(case, actor, tag):
    _require(tag in vocab.TAGS, "Unknown tag.")
    if tag not in case["tags"]:
        case["tags"].append(tag)
        _audit(case, actor, "Tag added", tag)


def modify_user_info(case, actor, form):
    """Modify User Info: correct a client field outside the confirm modal."""
    changed = []
    for field, client_key, label, _type in confirm_fields(case):
        value = (form.get(field) or "").strip()
        if value and value != case["client"].get(client_key, ""):
            if field == "dob":
                _require(dates.parse(value) is not None, "Birthday must be a date (YYYY-MM-DD).")
            _change(case, actor, label, case["client"].get(client_key, ""), value)
            case["client"][client_key] = value
            changed.append(label)
    _require(changed, "Nothing changed.")
    _audit(case, actor, "User info modified", ", ".join(changed))


def change_status(case, actor, status, comment):
    _require(status in vocab.STATUSES, "Unknown status.")
    comment = _require_text(comment, "A reason")
    before = case["status"]
    _require(status != before, "The case is already in that status.")
    case["status"] = status
    if status in vocab.CLOSED_STATUSES:
        case["closed_at"] = dates.now_str()
        _point(case, "Completed", case["closed_at"])
    _change(case, actor, "Status", before, status)
    _audit(case, actor, "Status changed", f"{before} → {status}. {comment}")
