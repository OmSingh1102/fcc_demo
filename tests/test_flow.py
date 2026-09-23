"""End-to-end flow tests on the Flask test client.

The state store is pointed at a temp file BEFORE app.py is imported — the
import restores stored state, so importing first would read the real
fincrime_state.db beside app.py.

Run:  .venv\\Scripts\\python.exe -m unittest -v
"""
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_DB = os.path.join(tempfile.mkdtemp(prefix="fcc-test-"), "state.db")
os.environ["FCC_STATE_DB"] = _DB
from fincrime.data.state_store import StateStore  # noqa: E402
StateStore.path = _DB
import app as fcc  # noqa: E402

AMARA, JON, MARIO, NISHA, RYAN = ("amara.iyer@straive.com", "jon.miranda@straive.com", "mario.kim@straive.com",
                                  "nisha.rao@straive.com", "ryan.lee@straive.com")


def flash_text(response):
    return " | ".join(re.findall(r'role="status"[^>]*>\s*<span[^>]*>[^<]*</span>\s*<span>([^<]+)</span>',
                                 response.data.decode("utf-8")))


class FlowTestCase(unittest.TestCase):

    def setUp(self):
        fcc.app.testing = True
        fcc.app.secret_key = "test"
        StateStore.clear()
        fcc._load_seed()
        self.c = fcc.app.test_client()
        self.K = {k["key"]: k for k in fcc.KYC_CASES if k.get("key")}

    # helpers ---------------------------------------------------------------
    def login(self, key):
        r = self.c.post("/login", data={"analyst": key, "password": "1234"})
        self.assertEqual(r.status_code, 302)

    def post(self, path, **data):
        return self.c.post(path, data=data, follow_redirects=True)

    def confirm(self, case):
        self.post(f"/kyc/{case['id']}/reserve")
        c = case["client"]
        return self.post(f"/kyc/{case['id']}/data_confirm", name=c["legal_name"], name_ok="1", dob=c["dob"], dob_ok="1",
                         nationality=c["nationality"], nationality_ok="1", summary="Checked against the document.")

    # tests -----------------------------------------------------------------
    def test_login_and_gate(self):
        self.assertEqual(self.c.get("/kyc/list").status_code, 302)          # signed out → portal
        r = self.c.post("/login", data={"analyst": "amara.iyer", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.login("amara.iyer")
        self.assertEqual(self.c.get("/kyc/list").status_code, 200)
        self.assertEqual(self.c.get("/state/version").get_json()["v"], fcc.STATE_VERSION)

    def test_golden_path(self):
        self.login("amara.iyer")
        m = self.K["mercer"]
        aid = m["screening"]["alert_case_id"]
        alert, wc = fcc.ALERT_BY_ID[aid], fcc.WC_BY_ID[aid]
        audit_len = len(m["audit"])

        r = self.confirm(m)
        self.assertEqual(m["status"], "DataScreening", flash_text(r))
        self.assertTrue(m["verification_points"][2]["at"])
        self.assertIn(AMARA, m["reviewers_by_level"]["L1"])
        self.assertGreater(len(m["audit"]), audit_len)
        audit_len = len(m["audit"])

        self.post(f"/name_screening/{aid}/handle")
        self.assertEqual(alert["status"], "Handling")
        unresolved = next(x for x in wc["matches"] if x["resolution"]["status"] == "Unresolved")
        r = self.post(f"/wc/{aid}/match/{unresolved['id']}/resolve", status="False positive", risk="Low",
                      reason="Date of Birth mismatch", comment="Different person: UK national born 1962.")
        self.assertEqual(unresolved["resolution"]["by"], AMARA, flash_text(r))
        self.post(f"/wc/{aid}/export")
        self.assertEqual(len(wc["exports"]), 1)
        pdf = self.c.get(f"/wc/{aid}/export.pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))

        pending = next(a for a in alert["alerts"] if a["outcome"] == "Pending")
        r = self.post(f"/name_screening/{aid}/alert_outcome", alert_id=pending["id"], review_mode="Manual Review",
                      result_label="False Positive", rationale="DOB Mismatch", comment="Not the same person.", risk_level="Low")
        self.assertEqual(pending["outcome"], "False Positive", flash_text(r))
        page = self.c.get(f"/name_screening/case/{aid}").data
        self.assertIn("Approve - False Positive · Recommended".encode("utf-8"), page)
        r = self.post(f"/name_screening/{aid}/case_outcome", outcome="Approve - False Positive", comment="All FP.")
        self.assertEqual(alert["status"], "Closed", flash_text(r))

        r = self.post(f"/kyc/{m['id']}/edd_review", decision="False positive", summary="FP-Approve.",
                      attachment=wc["exports"][0]["filename"])
        self.assertEqual(m["status"], "Verified", flash_text(r))
        self.assertEqual(m["previous_reviewer"], AMARA)
        self.assertEqual(m["current_reviewer"], "")
        self.assertEqual(m["review_decisions"][4]["report"], wc["exports"][0]["filename"])
        self.assertGreater(len(m["audit"]), audit_len)
        # A closed case that was never escalated shows five verification points.
        self.assertEqual(len(fcc.workflow.verification_points(m)), 5)

    def test_edd_review_refused_while_alerts_pending(self):
        self.login("amara.iyer")
        m = self.K["mercer"]
        self.confirm(m)
        r = self.post(f"/kyc/{m['id']}/edd_review", decision="False positive", summary="x", attachment="x.pdf")
        self.assertEqual(m["status"], "DataScreening")
        self.assertIn("pending", flash_text(r).lower())

    def test_mandatory_comment(self):
        self.login("amara.iyer")
        sd = self.K["sidorov"]
        self.post(f"/kyc/{sd['id']}/reserve")
        r = self.post(f"/kyc/{sd['id']}/escalate", reason="Other", comment="   ")
        self.assertEqual(sd["status"], "DataConfirming")
        self.assertIn("comment is required", flash_text(r).lower())
        aid = sd["screening"]["alert_case_id"]
        self.post(f"/name_screening/{aid}/handle")
        wc = fcc.WC_BY_ID[aid]
        mid = wc["matches"][0]["id"]
        self.post(f"/wc/{aid}/match/{mid}/resolve", status="True positive", risk="High", reason="Confirmed by identification", comment="")
        self.assertEqual(wc["matches"][0]["resolution"]["status"], "Unresolved")

    def test_confirm_flags_required(self):
        self.login("amara.iyer")
        m = self.K["mercer"]
        self.post(f"/kyc/{m['id']}/reserve")
        r = self.post(f"/kyc/{m['id']}/data_confirm", name=m["client"]["legal_name"], name_ok="1",
                      dob=m["client"]["dob"], dob_ok="0", nationality="US", nationality_ok="1")
        self.assertEqual(m["status"], "DataConfirming")
        self.assertIn("Birthday", flash_text(r))

    def test_resubmit(self):
        self.login("amara.iyer")
        n = self.K["nguyen"]
        self.post(f"/kyc/{n['id']}/reserve")
        self.post(f"/kyc/{n['id']}/resubmit", decision="Resubmit ID", id_reason="Cropped")
        self.assertEqual(n["status"], "ResubmitID")
        self.assertEqual(n["review_decisions"][3]["fail_reason"], "Cropped")
        self.assertEqual(n["current_reviewer"], "")

    def test_segregation(self):
        self.login("mario.kim")
        h = self.K["hassan"]
        self.post(f"/kyc/{h['id']}/reserve")
        self.post(f"/kyc/{h['id']}/escalate", reason="Non-US person with potential match", comment="Unresolved records.")
        self.assertEqual(h["status"], "DataEscalatingL2")
        queue = self.c.get("/queue/l2").data.decode("utf-8")
        self.assertNotIn(h["id"], queue)                                   # hidden from Mario at L2
        self.post(f"/kyc/{h['id']}/reserve")
        r = self.post(f"/kyc/{h['id']}/l2_decision", decision="Approve", comment="fine")
        self.assertEqual(h["status"], "DataEscalatingL2")
        self.assertIn("earlier level", flash_text(r))
        self.login("nisha.rao")
        self.assertIn(h["id"], self.c.get("/queue/l2").data.decode("utf-8"))  # visible to Nisha

    def test_l2_and_edd_decisions(self):
        md = self.K["mendoza"]
        self.login("nisha.rao")
        self.post(f"/kyc/{md['id']}/reserve")
        self.post(f"/kyc/{md['id']}/l2_decision", decision="Escalate to EDD", comment="SoW review.")
        self.assertEqual(md["pending_reason"], "Pending EDD")
        self.login("ryan.lee")
        self.post(f"/kyc/{md['id']}/reserve")
        self.post(f"/kyc/{md['id']}/l2_decision", decision="Approve", comment="SoW verified.")
        self.assertEqual(md["status"], "Verified")
        self.assertIn(RYAN, md["reviewers_by_level"]["EDD"])

    def test_skopenow_path(self):
        self.login("amara.iyer")
        p = self.K["petrova"]
        self.post(f"/kyc/{p['id']}/reserve")
        self.post(f"/kyc/{p['id']}/edd_review", decision="Request Skopenow report", summary="US person, medium risk.")
        self.assertEqual(p["pending_reason"], "Pending Skopenow")
        self.post(f"/kyc/{p['id']}/skopenow", outcome="Cleared", notes="All four comparisons distinct.")
        self.post(f"/kyc/{p['id']}/edd_review", decision="Approve after Skopenow", summary="Cleared.")
        self.assertEqual(p["status"], "Verified")

    def test_skopenow_only_for_us_persons(self):
        self.login("jon.miranda")
        y = self.K["yusuf"]
        self.post(f"/kyc/{y['id']}/reserve")
        r = self.post(f"/kyc/{y['id']}/edd_review", decision="Request Skopenow report", summary="x")
        self.assertEqual(y["status"], "DataScreening")
        self.assertIn("US persons", flash_text(r))

    def test_ttshop_recalculate_risk(self):
        self.login("jon.miranda")
        self.c.post("/tenant", data={"tenant": "ttshop", "next": "/kyc/list"})
        v = self.K["vanguard"]
        r = self.post(f"/kyc/{v['id']}/recalculate_risk")
        self.assertIn(v["risk_rating"], ("Medium", "High"), flash_text(r))
        listing = self.c.get("/kyc/list").data.decode("utf-8")
        self.assertIn(v["id"], listing)
        self.assertNotIn(self.K["mercer"]["id"], listing)                  # tenant scope

    def test_documents(self):
        self.login("amara.iyer")
        r = self.c.get(f"/documents/{self.K['sidorov']['id']}/d1.svg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/svg+xml")
        self.assertIn(b"SPECIMEN", r.data)
        self.assertIn("Анатолий".encode("utf-8"), r.data)
        cropped = self.c.get(f"/documents/{self.K['nguyen']['id']}/d1.svg").data
        self.assertNotIn(b'viewBox="0 0 640 400"', cropped)

    def test_wc_pagination_and_facets(self):
        self.login("amara.iyer")
        aid = self.K["hassan"]["screening"]["alert_case_id"]
        page5 = self.c.get(f"/wc/{aid}?page=5").data.decode("utf-8")
        self.assertIn("201–212", page5)
        self.assertIn("(209)", page5)
        self.assertEqual(self.c.get(f"/wc/{aid}?page=99").status_code, 200)

    def test_recommendation(self):
        alert = fcc.ALERT_BY_ID[self.K["mercer"]["screening"]["alert_case_id"]]
        self.assertIsNone(fcc.recommendation.recommend_case_outcome(alert))
        pep = fcc.ALERT_BY_ID[self.K["mendoza"]["screening"]["alert_case_id"]]
        self.assertEqual(fcc.recommendation.recommend_case_outcome(pep, fcc.WC_BY_ID[pep["id"]])["value"], "Escalate - True Positive")
        san = fcc.ALERT_BY_ID[self.K["almansoor"]["screening"]["alert_case_id"]]
        self.assertEqual(fcc.recommendation.recommend_case_outcome(san, fcc.WC_BY_ID[san["id"]])["value"], "Reject - True Positive")

    def test_persistence_and_reset(self):
        self.login("amara.iyer")
        s = self.K["solis"]
        self.confirm(s)
        self.post(f"/kyc/{s['id']}/edd_review", decision="No match - Approve", summary="Clean.")
        self.assertEqual(s["status"], "Verified")
        self.assertGreaterEqual(StateStore.count(), 1)
        fcc._load_seed()                                                   # simulated restart
        self.assertEqual(fcc.KYC_BY_ID[s["id"]]["status"], "Verified")
        self.post("/reset")
        self.assertEqual(fcc.KYC_BY_ID[s["id"]]["status"], "DataConfirming")
        self.assertEqual(StateStore.count(), 0)

    def test_analytics_and_queue_render(self):
        self.login("nisha.rao")
        self.assertEqual(self.c.get("/analytics").status_code, 200)
        self.assertEqual(self.c.get("/queue/l2").status_code, 200)
        self.assertEqual(self.c.get("/name_screening/queue").status_code, 200)


if __name__ == "__main__":
    unittest.main()
