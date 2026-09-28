"""View-model for the AI Screening page: the rule book with how often each
rule fired, the guards and rails, the tenant's split between auto-verified
and human-in-the-loop, and a feed of what the rules did most recently."""
from collections import Counter

from fincrime.data import vocab
from fincrime.engines import ai_review, ai_screening


class AiScreeningConsole:

    @staticmethod
    def compute(cases, alert_cases, wc_cases, tenant, settings):
        tenant_cases = [c for c in cases if c["tenant"] == tenant]
        ids = {c["id"] for c in tenant_cases}
        by_id = {c["id"]: c for c in tenant_cases}
        alerts = [a for a in alert_cases if a["kyc_case_id"] in ids]
        rows = [r for a in alerts for r in a["alerts"]]
        auto_rows = [r for r in rows if r.get("resolved_by") == vocab.SYSTEM_USER]
        fired = Counter(r.get("smart_strategy") for r in auto_rows)
        enabled, guards_on = settings.get("enabled", {}), settings.get("guards", {})
        rules = [dict(r, on=bool(enabled.get(r["key"], r["default"])), fired=fired.get(r["label"], 0)) for r in ai_screening.RULES]
        guards = [dict(g, on=bool(guards_on.get(g["key"], g["default"]))) for g in ai_screening.GUARDS]
        switches_on = settings.get("switches", {})
        model = dict(ai_review.status(), on=bool(switches_on.get("model_review", True)),
                     count=sum(1 for r in rows if r.get("ai_assessment")))

        hit = [c for c in tenant_cases if c["screening"]["hit"]]
        auto_hit = [c for c in hit if c["screening"].get("workflow") == "auto-verified"]
        human = [c for c in hit if c["screening"].get("workflow") == "human-in-the-loop"]
        no_hit = [c for c in tenant_cases if not c["screening"]["hit"]]
        closed_by_rules = [c for c in tenant_cases if c.get("closed_by") == vocab.SYSTEM_USER]
        pending = sum(1 for r in rows if r["outcome"] == "Pending")
        tiles = [
            ("Auto-verified", len(auto_hit), f"of {len(hit)} cases with a screening hit", "success"),
            ("Human-in-the-loop", len(human), f"{pending} alert(s) waiting for an analyst", "warning" if human else ""),
            ("No match", len(no_hit), "auto-verified with nothing to clear", ""),
            ("Records auto-resolved", len(auto_rows), f"of {len(rows)} watchlist records returned", "info"),
            ("Cases closed by the rules", len(closed_by_rules), "verified with no analyst step", "success"),
        ]

        feed = []
        for w in wc_cases:
            k = by_id.get(w["kyc_case_id"])
            if k is None:
                continue
            for e in w.get("audit", []):
                if e["action"] == ai_screening.ACTION:
                    feed.append({"at": e["at"], "kind": "World-Check case", "name": k["client"]["legal_name"], "detail": e["detail"],
                                 "endpoint": "wc_case", "args": {"wc_case_id": w["id"]}, "new_tab": True})
        for c in tenant_cases:
            for e in c.get("audit", []):
                if e["actor"] == vocab.SYSTEM_USER and e["action"] == "Case verified":
                    feed.append({"at": e["at"], "kind": "KYC case", "name": c["client"]["legal_name"], "detail": e["detail"],
                                 "endpoint": "kyc_detail", "args": {"case_id": c["id"]}, "new_tab": False})
        feed.sort(key=lambda r: r["at"], reverse=True)

        return {
            "tenant_label": vocab.TENANTS[tenant]["label"],
            "rules": rules, "guards": guards, "rails": ai_screening.RAILS, "model": model,
            "tiles": tiles, "hit": len(hit), "feed": feed[:10],
            "history": list(reversed(settings.get("history", [])))[:10],
        }
