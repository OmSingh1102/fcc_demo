"""The AI Agent on the file book: Claude's read of the ID and the proof of
address (stood in for here, so no call leaves the machine), the fixed checks,
and what the agent does with the case.

Run:  .venv\\Scripts\\python.exe -m unittest -v tests.test_ai_agent
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_DB = os.path.join(tempfile.mkdtemp(prefix="fcc-agent-"), "state.db")
os.environ.setdefault("FCC_STATE_DB", _DB)
os.environ["CONSOLE_CASES"] = "demo"      # the suite's default; this class switches to the file book itself
from fincrime.data.state_store import StateStore  # noqa: E402
if StateStore.path != os.environ["FCC_STATE_DB"]:
    StateStore.path = os.environ["FCC_STATE_DB"]
import app as fcc  # noqa: E402
from fincrime.data import recon_book  # noqa: E402
from fincrime.documents.raster import svg_to_png  # noqa: E402
from fincrime.documents.svg_cards import ISO3  # noqa: E402
from fincrime.engines import ai_agent  # noqa: E402
from fincrime.engines.errors import WorkflowError  # noqa: E402


def perfect_read(case, **id_overrides):
    """What the document images print, as a flawless reader would return it."""
    v = recon_book.view(case["recon"]["id"])
    pp, s = v["documents"]["passport"], v["synth"]
    idr = {"readable": True, "problems": [], "surname": pp["viz"]["surname"], "given_names": pp["viz"]["given"],
           "dob": v["customer"]["dob"], "nationality_code": ISO3.get(case["client"]["nationality"], ""),
           "document_number": pp["number"], "expiry": s["passport_expiry"], "address": "", "issued_on": s["passport_issued"],
           "note": ""}
    idr.update(id_overrides)
    poa = {"readable": True, "problems": [], "surname": "", "given_names": "", "dob": "", "nationality_code": "",
           "document_number": "", "expiry": "", "address": v["documents"]["poa"]["address"], "issued_on": s["poa_issued_on"],
           "note": ""}
    return {"id": idr, "poa": poa}


class Stub:
    """Stands in for llm.call: records what it was sent, answers `answer`."""

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.sent = answer, error, []

    def __call__(self, system, content, schema, max_tokens=3000):
        self.sent.append(content)
        if self.error:
            raise self.error
        return self.answer, {"input": 3000, "output": 200, "cached": 0}, 8.5


class AiAgentTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fcc.app.testing = True
        fcc.app.secret_key = "test"
        cls.book_before = fcc.CASE_BOOK
        fcc.CASE_BOOK = "file"

    @classmethod
    def tearDownClass(cls):
        fcc.CASE_BOOK = cls.book_before
        StateStore.clear()
        fcc._load_seed()

    def setUp(self):
        StateStore.clear()
        fcc._load_seed()
        self.K = fcc.KYC_BY_ID

    def run_agent(self, case, answer=None, error=None, **id_overrides):
        stub = Stub(answer or perfect_read(case, **id_overrides), error)
        alert, wc = fcc._linked(case)
        return ai_agent.run_case(case, alert, wc, fcc._render_document, call=stub, sleep=lambda s: None), stub

    def pick(self, test):
        return next(c for c in fcc.KYC_CASES if ai_agent.eligible(c) and test(c))

    # ── the clean path ──────────────────────────────────────────────────────
    def test_a_clean_case_is_verified_with_no_person(self):
        c = self.clean(lambda c: c["screening"]["workflow"] == "auto-verified")
        rec, stub = self.run_agent(c)
        self.assertEqual(rec["decision"], "verified", rec["reasons"])
        self.assertEqual((c["status"], c["closed_by"], c["previous_reviewer"]), ("Verified", "System User", "AI Agent"))
        self.assertEqual(c["confirmations"]["dob"]["confirmed_by"], "AI Agent")
        self.assertIn("Data confirmed by AI Agent", c["audit"][-1]["detail"])
        self.assertEqual([b["type"] for b in stub.sent[0]], ["text", "image", "text", "image"])
        self.assertEqual(stub.sent[0][1]["source"]["media_type"], "image/png")

    def test_a_case_the_rules_held_goes_to_screening(self):
        c = self.K["KYC-2026-3012"]
        c["current_reviewer"] = ""                                  # a starter case; free it for the agent
        rec, _ = self.run_agent(c)
        self.assertEqual(rec["decision"], "screening", rec["reasons"])
        self.assertEqual((c["status"], c["screening"]["workflow"]), ("DataScreening", "human-in-the-loop"))
        self.assertEqual(fcc.ALERT_BY_ID[c["screening"]["alert_case_id"]]["alerts"][0]["outcome"], "Pending")

    # ── what sends a case to a person ───────────────────────────────────────
    def assert_human(self, case, needle, **id_overrides):
        rec, _ = self.run_agent(case, **id_overrides)
        self.assertEqual(rec["decision"], "human")
        self.assertEqual((case["status"], case["screening"]["workflow"]), ("DataConfirming", "human-in-the-loop"))
        self.assertTrue(any(needle in r for r in rec["reasons"]), rec["reasons"])
        self.assertEqual((case["audit"][-1]["actor"], case["audit"][-1]["action"]), ("AI Agent", "Sent to a person"))
        return rec

    def clean(self, also=lambda c: True):
        """A case every check passes on a perfect read."""
        return self.pick(lambda c: also(c) and all(x["ok"] for x in ai_agent.checks(c, perfect_read(c))[0]))

    def test_unreadable_id(self):
        self.assert_human(self.clean(), "ID could not be read: blurred", readable=False, problems=["blurred"])
        self.assert_human(self.clean(), "ID could not be read: cut off", problems=["cut_off"])

    def test_date_of_birth_missing_or_different(self):
        self.assert_human(self.clean(), "Date of birth missing on the ID", dob="")
        self.assert_human(self.clean(), "Date of birth on the ID 1999-01-02", dob="1999-01-02")

    def test_expired_id(self):
        self.assert_human(self.clean(), "ID expired on 2025-03-01", expiry="2025-03-01")

    def test_name_that_is_somebody_else(self):
        self.assert_human(self.clean(), "Name on the ID differs from the CRM", surname="OKONKWO", given_names="CHIDI")

    def test_vendor_declined_and_old_proof_of_address(self):
        declined = self.pick(lambda c: c["vendor_check"]["result"] == "Declined")
        self.assert_human(declined, "ID declined by the vendor")
        old = self.pick(lambda c: ai_agent.workflow.poa_failures(c))
        self.assert_human(old, "Issued within the last 6 months")

    def test_gateway_error_goes_to_a_person(self):
        c = self.clean()
        rec, _ = self.run_agent(c, error=WorkflowError("The model gateway answered 500: busy"))
        self.assertEqual(rec["decision"], "human")
        self.assertIn("could not read the documents", rec["reasons"][0])
        self.assertEqual(c["status"], "DataConfirming")

    def test_rate_limit_waits_and_tries_again(self):
        c = self.clean()
        calls = []

        def flaky(system, content, schema, max_tokens=3000):
            calls.append(1)
            if len(calls) == 1:
                raise WorkflowError("The model gateway answered 429: too many connections")
            return perfect_read(c), {}, 5.0
        alert, wc = fcc._linked(c)
        rec = ai_agent.run_case(c, alert, wc, fcc._render_document, call=flaky, sleep=lambda s: None)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(rec["decision"], "human", rec["reasons"])

    # ── the name rules ──────────────────────────────────────────────────────
    def test_name_rules(self):
        v = ai_agent.name_verdict
        self.assertEqual(v("NGUYEN NGOC PHUONG", "NGUYỄN", "NGỌC PHƯƠNG"), (True, "NGUYEN NGOC PHUONG"))
        self.assertEqual(v("JEFF WILLIAMS", "WILLIAMS", "JEFFREY DEAN"), (True, "JEFFREY DEAN WILLIAMS"))   # nickname
        self.assertEqual(v("PILLAI NEETHU", "PILLAI", "NEETHU"), (True, "PILLAI NEETHU"))                    # order
        self.assertEqual(v("BALAJI K", "KRISHNAN", "BALAJI"), (True, "BALAJI KRISHNAN"))                     # patronymic initial
        self.assertEqual(v("PRABHU FNU", "", "PRABHU"), (True, "PRABHU"))                                    # single name
        self.assertEqual(v("VÅ© CÃ´ng KhÃ¡nh", "VŨ", "CÔNG KHÁNH")[0], True)                                # mojibake
        self.assertFalse(v("PATRICIA WILSON", "ROBERTS", "PATRICIA MARIE")[0])                              # another surname
        self.assertTrue(v("KEVIN NGUYEN", "NGUYEN", "KHOA QUOC")[0])                                        # the hub knows Kevin for Khoa
        self.assertFalse(v("BRANDON NGUYEN", "NGUYEN", "KHOA QUOC")[0])                                     # another given name

    def test_reserved_and_company_cases_are_not_taken(self):
        self.assertFalse(ai_agent.eligible(self.K["KYC-2026-3011"]))     # reserved by Amara
        self.assertFalse(ai_agent.eligible(self.K["KYC-2026-3029"]))     # a company
        self.assertTrue(svg_to_png('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>').startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
