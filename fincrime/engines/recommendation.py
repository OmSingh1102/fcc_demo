"""The "Recommended" tag on Change Case Outcome, and the prefill on Change
Alert Outcome. Deterministic rules over what the analyst has already decided
— no model, and it never decides for them: a Pending alert means no
recommendation at all."""

_LABEL = {"False positive": "False Positive", "Potential match": "Potential Match", "True positive": "True Positive"}
_RATIONALE = {"Date of Birth mismatch": "DOB Mismatch", "Nationality mismatch": "Nationality Mismatch",
              "Gender mismatch": "Gender Mismatch", "Name mismatch": "Name Mismatch", "Age mismatch": "DOB Mismatch",
              "Identification mismatch": "Different Person - Public Records", "Location mismatch": "Different Person - Public Records",
              "Confirmed by identification": "Confirmed Identity", "Confirmed by adverse media": "Same Person - Adverse Media",
              "Insufficient information": "Insufficient Information"}


def recommend_case_outcome(alert, wc=None):
    outcomes = [a["outcome"] for a in alert["alerts"]]
    if not outcomes:
        return {"value": "Approve - False Positive", "why": "No watchlist matches were returned."}
    if "Pending" in outcomes:
        return None
    if "True Positive" in outcomes:
        pep = False
        if wc:
            tp_ids = {a["match_id"] for a in alert["alerts"] if a["outcome"] == "True Positive"}
            pep = any("PEP" in m["types"] or "RCA" in m["types"] for m in wc["matches"] if m["id"] in tp_ids)
        if pep:
            return {"value": "Escalate - True Positive", "why": "A confirmed PEP or close associate needs enhanced due diligence, not a rejection."}
        return {"value": "Reject - True Positive", "why": "A sanctions, law-enforcement or regulatory record was confirmed as this person."}
    if "Potential Match" in outcomes:
        return {"value": "Escalate - Potential Match", "why": "A match could not be cleared at L1."}
    return {"value": "Approve - False Positive", "why": "Every alert was resolved as a false positive."}


def recommend_alert_outcome(alert_row, match):
    if not match:
        return {"result_label": "", "rationale": "", "risk_level": ""}
    res = match["resolution"]
    return {"result_label": _LABEL.get(res["status"], ""), "rationale": _RATIONALE.get(res["reason"], ""),
            "risk_level": res["risk"] or ""}
