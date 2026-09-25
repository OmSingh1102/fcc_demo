"""View-model for the case list: the rows for the current tenant plus every
distinct value the filter grid offers, so the template never computes."""
from fincrime.data import vocab
from fincrime.engines import sla
from fincrime.utils.text import display_name


def _short(email):
    return display_name(email) if email else ""


class CaseListConsole:

    @staticmethod
    def compute(cases, tenant, analyst_email="", now=None):
        rows = []
        for c in cases:
            if c["tenant"] != tenant:
                continue
            client = c["client"]
            rows.append({
                "case": c,
                "id": c["id"], "client_id": c["client_id"], "name": client["legal_name"], "dob": client["dob"],
                "status": c["status"], "pending_reason": c["pending_reason"], "tags": c["tags"],
                "previous_reviewer": _short(c["previous_reviewer"]), "current_reviewer": _short(c["current_reviewer"]),
                "vendor": (c["vendor_check"]["vendor"] or "").split("_")[0],
                "source": c["source"], "created_at": c["created_at"], "submitted_at": c["submitted_at"],
                "nationality": client["nationality"], "issuing": client["id_issuing_place"], "id_number": client["id_number"],
                "poa": "Yes" if c["poa_required"] else "No", "level": c["case_review_level"],
                "mrr": "; ".join(c["manual_review_reason"]), "qc_reviewer": _short(c["qc_reviewer"]),
                "qc_reason": c["qc_reason"], "qc_result": c["qc_result"],
                "gifter": next((t for t in c["tags"] if t.startswith("Gifter")), ""),
                "edd_rfi": "Yes" if c["pending_reason"] in ("Pending EDD", "RFI Sent") else "No",
                "sla": sla.chip(c, now), "mine": bool(analyst_email) and c["current_reviewer"] == analyst_email,
                "workflow": c["screening"].get("workflow", ""),
            })
        rows.sort(key=lambda r: r["created_at"], reverse=True)

        def distinct(key):
            return sorted({r[key] for r in rows if r[key]})

        return {
            "rows": rows, "total": len(rows),
            "filters": {
                "statuses": vocab.STATUSES,
                "sources": vocab.SOURCES,
                "reviewers": distinct("previous_reviewer") + [x for x in distinct("current_reviewer") if x not in distinct("previous_reviewer")],
                "tags": vocab.TAGS,
                "issuing": distinct("issuing"),
                "pending": [p for p in vocab.PENDING_REASONS if p],
                "mrr": vocab.MANUAL_REVIEW_REASONS,
                "levels": vocab.CASE_REVIEW_LEVELS,
                "qc_results": [q for q in vocab.QC_RESULTS if q],
                "vendors": sorted({r["vendor"] for r in rows if r["vendor"]}),
            },
        }
