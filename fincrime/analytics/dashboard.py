"""View-model for the Analytics page: the metrics the earlier prototype
promised (backlog, SLA pressure, escalations, throughput per reviewer,
screening outcomes) computed from the live case book."""
from collections import Counter

from fincrime.data import vocab
from fincrime.engines import sla
from fincrime.utils import dates
from fincrime.utils.text import display_name


class AnalyticsConsole:

    @staticmethod
    def compute(kyc_cases, alert_cases, wc_cases, tenant, now=None):
        cases = [c for c in kyc_cases if c["tenant"] == tenant]
        open_cases = [c for c in cases if c["status"] in vocab.OPEN_STATUSES]
        closed = [c for c in cases if c["status"] in vocab.CLOSED_STATUSES]
        waiting = [c for c in cases if c["status"].startswith("Resubmit")]
        breached = [c for c in open_cases if sla.breached(c, now)]
        at_risk = [c for c in open_cases if not sla.breached(c, now) and sla.remaining_hours(c, now) <= 12]

        status_counts = [(s, sum(1 for c in cases if c["status"] == s)) for s in vocab.STATUSES]
        status_counts = [(s, n) for s, n in status_counts if n]

        # Throughput: closures per reviewer, from the audit trail's closing entry.
        per_reviewer = Counter()
        for c in closed:
            per_reviewer[c["previous_reviewer"] or "system"] += 1
        throughput = [(display_name(e) if "@" in e else e, n) for e, n in per_reviewer.most_common(8)]

        # Turnaround for closed cases (hours from submission to close).
        tats = []
        for c in closed:
            a, b = dates.parse(c["submitted_at"]), dates.parse(c["closed_at"])
            if a and b:
                tats.append((b - a).total_seconds() / 3600)
        tat_avg = round(sum(tats) / len(tats), 1) if tats else 0.0

        # Screening: alert outcomes across the tenant's screening cases.
        tenant_ids = {c["id"] for c in cases}
        alerts = [a for ac in alert_cases if ac["kyc_case_id"] in tenant_ids for a in ac["alerts"]]
        outcome_counts = [(o, sum(1 for a in alerts if a["outcome"] == o)) for o in vocab.ALERT_OUTCOMES]
        auto = sum(1 for a in alerts if a["review_mode"] == "Smart Review")
        manual = sum(1 for a in alerts if a["outcome"] != "Pending" and a["review_mode"] != "Smart Review")
        rationale_counts = Counter(a["rationale"] for a in alerts if a["rationale"]).most_common(6)

        reasons = Counter(r for c in open_cases for r in c["manual_review_reason"]).most_common(6)
        escalations = [c for c in cases if c["status"] == "DataEscalatingL2"]

        return {
            "kpis": [
                ("Open backlog", len(open_cases), "Data Confirming, Screening and L2", "info"),
                ("SLA breached", len(breached), "open cases past the 48 h / 14 d clock", "danger" if breached else "success"),
                ("At risk", len(at_risk), "due within 12 hours", "warning" if at_risk else "success"),
                ("Escalated", len(escalations), "waiting at L2 / EDD", ""),
                ("Waiting on user", len(waiting), "resubmission requested", ""),
                ("Closed", len(closed), f"avg turnaround {tat_avg} h", "success"),
            ],
            "status_counts": status_counts,
            "throughput": throughput,
            "outcome_counts": outcome_counts,
            "auto_vs_manual": [("Auto-resolved (rules)", auto), ("Manually reviewed", manual),
                               ("Pending", sum(1 for a in alerts if a["outcome"] == "Pending"))],
            "rationales": rationale_counts,
            "reasons": reasons,
            "breached": [{"case": c, "sla": sla.chip(c, now)} for c in sorted(breached + at_risk, key=lambda c: sla.remaining_hours(c, now))][:8],
            "total_alerts": len(alerts),
        }
