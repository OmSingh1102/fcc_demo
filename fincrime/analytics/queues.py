"""View-model for the L2 / EDD queue: escalated cases the signed-in analyst
is allowed to see, with the segregation rule applied and the hidden ones
counted so the page can say why."""
from fincrime.engines import segregation, sla


class QueueConsole:

    @staticmethod
    def compute(cases, tenant, analyst_email, levels):
        rows, hidden = [], 0
        for c in cases:
            if c["tenant"] != tenant or c["status"] != "DataEscalatingL2":
                continue
            level = "EDD" if c["pending_reason"] == "Pending EDD" else "L2"
            if level not in levels and not ("QC" in levels):
                continue
            if segregation.hidden_from(c, analyst_email, level):
                hidden += 1
                continue
            rows.append({"case": c, "level": level, "sla": sla.chip(c),
                         "mine": c["current_reviewer"] == analyst_email})
        rows.sort(key=lambda r: r["case"]["edd_due_at"] or r["case"]["sla_due_at"])
        return {"rows": rows, "hidden": hidden,
                "l2": sum(1 for r in rows if r["level"] == "L2"), "edd": sum(1 for r in rows if r["level"] == "EDD")}
