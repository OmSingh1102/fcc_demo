"""Screening an uploaded ID (fincrime/watchlist.py, fincrime/id_screening.py,
fincrime/adapters/world_check.py and the screening book of app.py): the
stand-in World-Check's name search, what the deciding model is given and
never given, the SOP versions, the analyst's confirmation closing a case,
the World-Check One request signing and result mapping, and the pages on the
screening book (an empty start, upload to closed case, an SOP change sending
open hits to the model again, the settings). No network: the model call and
World-Check One are stood in for.

Run:  .venv\\Scripts\\python.exe -m unittest -v tests.test_screening
"""
import base64
import hashlib
import hmac
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_DB = os.path.join(tempfile.mkdtemp(prefix="fcc-screen-"), "state.db")
os.environ.setdefault("FCC_STATE_DB", _DB)
os.environ.setdefault("CONSOLE_CASES", "demo")      # the suite's default; the page tests switch to the screening book
from fincrime.data.state_store import StateStore  # noqa: E402
if StateStore.path != os.environ["FCC_STATE_DB"]:
    StateStore.path = os.environ["FCC_STATE_DB"]
import app as fcc  # noqa: E402
from fincrime import benchmark, decision_model, id_screening, upload_eval, watchlist  # noqa: E402
from fincrime.adapters import didit, world_check  # noqa: E402
import json as _json  # noqa: E402
from fincrime.documents import id_scan  # noqa: E402
from fincrime.filebook import llm  # noqa: E402

WHO = {"name": "ASHISH UPADHYAY", "surname": "UPADHYAY", "given_names": "ASHISH", "dob": "1962-06-29", "sex": "M",
       "nationality": "IND", "issuing_country": "India", "place_of_birth": "Patna", "address": "", "father_or_spouse_name": "",
       "document_type": "Passport", "document_number": "S3321051", "mrz1": "P<INDUPADHYAY<<ASHISH<<<<<<<<<<<<<<<<<<<<<<<"}
ANSWER = {"name_variance": "None – consistent across documents", "address_variance": "None – consistent across documents",
          "dob_finding": "The record lists the customer's date.", "outcome": "true_match", "confidence": 88,
          "reasons": ["Exact date of birth", "Listed in Patna"], "request": ""}


def a_read(name="ASHISH UPADHYAY", surname="UPADHYAY", given="ASHISH", dob="1962-06-29"):
    fields = {k: "" for k, _ in id_scan.FIELDS}
    fields.update(full_name=name, surname=surname, given_names=given, date_of_birth=dob, sex="M", nationality="IND",
                  document_number="S3321051", date_of_expiry="2033-06-02")
    return {"document_type": "Passport", "issuing_country": "India", "readable": True, "problems": [], "fields": fields,
            "mrz": [], "uncertain": [], "note": ""}


def an_aml_answer(dob_score=100, scenario_hits=None):
    """Didit's AML answer, as its API reference shows it (trimmed)."""
    hits = scenario_hits if scenario_hits is not None else [
        {"id": "hit-002", "match_score": 88.0, "risk_score": 47.5, "caption": "Ashish K. Upadhyay", "datasets": ["PEP Level 2"],
         "review_status": "False Positive", "properties": {"name": ["Ashish K. Upadhyay"], "birthDate": ["1961"]},
         "pep_matches": [{"list_name": ["Every Politician"], "pep_position": "Member of a state assembly"}],
         "score_breakdown": {"name_score": 80, "name_weight_normalized": 60.0, "dob_score": 50, "dob_weight_normalized": 25.0,
                             "country_score": 100, "country_weight_normalized": 15.0, "document_number_match_type": "NEUTRAL"}},
        {"id": "hit-001", "url": "https://sanctions.example.org/entry/123", "match_score": 97.0, "risk_score": 86.0,
         "caption": "ASHISH UPADHYAY", "datasets": ["Sanctions"], "review_status": "Unreviewed",
         "properties": {"name": ["ASHISH UPADHYAY"], "alias": ["A. Upadhyay"], "birthDate": ["1970-01-01"], "nationality": ["India"]},
         "sanction_matches": [{"list_name": ["Example Sanctions List"], "reason": "Fraud.", "sanction_program": "Example"}],
         "score_breakdown": {"name_score": 95, "name_weight_normalized": 60.0, "dob_score": dob_score, "dob_weight_normalized": 25.0,
                             "country_score": 100, "country_weight_normalized": 15.0, "document_number_match_type": "NEUTRAL"}}]
    return {"request_id": "a1b2c3d4", "aml": {"status": "In Review" if hits else "Approved", "total_hits": len(hits), "hits": hits,
                                              "score": 86.0 if hits else 0, "warnings": [{"short_description": "Possible match found in AML screening"}] if hits else []}}


class WatchlistTests(unittest.TestCase):

    def test_the_names_of_the_file_are_the_watchlist(self):
        profiles = watchlist.profiles()
        self.assertEqual(len(profiles), 1000)
        self.assertEqual(len({p["uid"] for p in profiles}), 1000)
        # the analysts' note beside the listed date of birth is not the record
        self.assertFalse([p for p in profiles if "diff" in p["dob_text"] or "Match" in p["dob_text"]])

    def test_name_scores(self):
        s = watchlist.name_score
        self.assertEqual(s("Pham Hong Ha", "Hong Ha PHAM"), 100)                 # word order
        self.assertEqual(s("Lý Hữu Duy", "Huu Duy LY"), 100)                    # diacritics
        self.assertEqual(s("N. Ramesh", "N. RAMESH"), 100)                      # initials
        self.assertGreaterEqual(s("Javier Medina", "Javier Edward MEDINA"), 85)  # a middle name the ID lacks
        self.assertGreaterEqual(s("Barbara O Connor", "Barbara Michelle O'CONNOR"), 85)
        self.assertLess(s("Nguyen Thu Dung", "Thu Linh NGUYEN"), 75)            # a family name and a word in common
        self.assertEqual(s("John Smith", "Hong Ha PHAM"), 0)

    def test_search_reports_dob_and_country_but_never_drops_on_them(self):
        hits = watchlist.search(dict(WHO, dob="1999-01-01", issuing_country="Vietnam", nationality="VNM"))
        self.assertEqual([h["uid"] for h in hits], ["WC-675768"])
        self.assertEqual((hits[0]["dob_result"], hits[0]["country_result"], hits[0]["strength"]), ("Not matched", "Not matched", "Exact"))
        self.assertEqual(watchlist.search(dict(WHO, name="Zebediah Quartermaine")), [])
        self.assertEqual(watchlist.search(dict(WHO, name="")), [])
        loose = watchlist.search(dict(WHO, name="Nguyen Thu Dung"), threshold=60, limit=3)
        self.assertEqual(len(loose), 3)
        self.assertEqual(loose, sorted(loose, key=lambda h: -h["score"]))


class DecisionTests(unittest.TestCase):

    def hit(self):
        return watchlist.search(WHO)[0]

    def test_the_record_hit_is_never_an_example(self):
        hit = self.hit()
        text, used = id_screening.prompt("SCAN-1", WHO, hit, 6)
        self.assertEqual(len(used), 6)
        self.assertNotIn(hit["row"], used)
        rows = decision_model.rows()
        self.assertFalse([u for u in used if rows[u]["world_check_uid"] == hit["uid"]])
        case = text.split("### The case to decide")[1]
        self.assertIn("World-Check record WC-675768", case)
        self.assertNotIn("Analysts' outcome", case)            # the answer is only on the examples
        self.assertNotIn("SOP", text)                          # the SOP is the system prompt, not the case

    def test_decide(self):
        hit, sop = self.hit(), id_screening.sop_current([])
        settings = id_screening.default_settings()
        with mock.patch.object(llm, "KEY", ""):
            self.assertEqual(id_screening.decide("SCAN-1", WHO, hit, sop, settings)["status"], "failed")
        seen = {}

        def call(model, content, system=None, schema=None):
            seen.update(model=model["id"], system=system, schema=schema)
            return dict(ANSWER), 4000, 300
        with mock.patch.object(llm, "KEY", "x"), mock.patch.object(benchmark, "call", call):
            ai = id_screening.decide("SCAN-1", WHO, hit, sop, dict(settings, decision_model="gemini-2.5-flash", examples=0))
        self.assertEqual((ai["status"], ai["outcome"], ai["suggested"], ai["sop"]), ("done", "true_match", "True match", sop["version"]))
        self.assertEqual((seen["model"], ai["examples"]), ("gemini-2.5-flash", []))
        self.assertTrue(seen["system"].startswith(sop["text"][:40]))
        self.assertIn("Variance reference", seen["system"])
        self.assertGreater(ai["cost"], 0)
        with mock.patch.object(llm, "KEY", "x"), mock.patch.object(benchmark, "call", lambda *a, **k: (dict(ANSWER, outcome="maybe"), 1, 1)):
            self.assertEqual(id_screening.decide("SCAN-1", WHO, hit, sop, settings)["status"], "failed")

    def test_sop_versions(self):
        files = decision_model.sop_versions()
        current = id_screening.sop_current([])
        self.assertEqual(current["version"], files[-1])
        with self.assertRaises(ValueError):
            id_screening.sop_new([], current["text"], "", "qc@x")          # nothing changed
        with self.assertRaises(ValueError):
            id_screening.sop_new([], "too short", "", "qc@x")
        rec = id_screening.sop_new([], current["text"] + "\n\n## 9. A new rule\nAsk first.", "added 9", "qc@x")
        self.assertEqual(rec["version"], f"v{int(files[-1][1:]) + 1}")
        self.assertEqual(id_screening.sop_current([rec])["text"], rec["text"])
        self.assertEqual(id_screening.sop_new([rec], rec["text"] + " Twice.", "", "qc@x")["version"], f"v{int(files[-1][1:]) + 2}")

    def test_confirming_every_hit_closes_the_case(self):
        case = {"status": "open", "screening": {"hits": [{"uid": "A", "ai": {"status": "done", "suggested": "False positive"}},
                                                         {"uid": "B", "ai": {"status": "failed"}}]}}
        id_screening.resolve(case, "A", "False positive", "", "a@x")
        self.assertEqual(case["status"], "open")
        self.assertTrue(case["screening"]["hits"][0]["resolution"]["agreed"])
        with self.assertRaises(ValueError):
            id_screening.close(case, "a@x")
        with self.assertRaises(ValueError):
            id_screening.resolve(case, "B", "Maybe", "", "a@x")
        id_screening.resolve(case, "B", "Possible match", "ask for a second ID", "a@x")
        self.assertEqual((case["status"], case["closed"]["outcome"]), ("closed", "Possible match"))
        self.assertEqual(case["screening"]["hits"][1]["resolution"]["ai_suggested"], "")
        empty = {"status": "open", "screening": {"hits": []}}
        id_screening.close(empty, "a@x")
        self.assertEqual(empty["closed"]["outcome"], "No match")


class WorldCheckOneTests(unittest.TestCase):
    cfg = dict(world_check.DEFAULTS, api_key="KEY-1", api_secret="secret", group_id="G-1")

    def test_a_request_is_signed_with_the_secret(self):
        body = b'{"name":"A"}'
        h = world_check.signed_headers(self.cfg, "POST", "/v2/cases/screeningRequest", body, date="Tue, 07 Jun 2016 20:51:35 GMT")
        text = ("(request-target): post /v2/cases/screeningRequest\nhost: api-worldcheck.refinitiv.com\n"
                "date: Tue, 07 Jun 2016 20:51:35 GMT\ncontent-type: application/json\ncontent-length: 12\n" + body.decode())
        sig = base64.b64encode(hmac.new(b"secret", text.encode(), hashlib.sha256).digest()).decode()
        self.assertIn(f'signature="{sig}"', h["Authorization"])
        self.assertIn('keyId="KEY-1"', h["Authorization"])
        self.assertIn('headers="(request-target) host date content-type content-length"', h["Authorization"])
        self.assertNotIn("secret", json.dumps(h))
        self.assertFalse(world_check.configured(dict(self.cfg, api_secret="")))

    def test_screen_maps_the_results(self):
        sent = []
        result = {"referenceId": "e_tr_wci_1", "resultId": "r1", "matchStrength": "STRONG", "primaryName": "UPADHYAY, Ashish",
                  "matchedTerm": "ASHISH UPADHYAY", "categories": ["Crime - Financial"],
                  "events": [{"type": "BIRTH", "fullDate": "1962-06-29"}],
                  "countryLinks": [{"country": {"code": "IND", "name": "INDIA"}, "type": "NATIONALITY"}],
                  "secondaryFieldResults": [{"typeId": "SFCT_2", "fieldResult": "MATCHED"}]}

        def fake(req):
            sent.append(req)
            if req.get_method() == "POST":
                return 200, json.dumps({"caseSystemId": "C-9", "results": [result]}).encode()
            return 200, json.dumps({"details": [{"text": "Reported in a fraud case."}]}).encode()
        with mock.patch.object(world_check, "_send", fake):
            hits, csid = world_check.screen(self.cfg, WHO)
        payload = json.loads(sent[0].data)
        self.assertEqual((payload["groupId"], payload["name"], payload["entityType"]), ("G-1", "ASHISH UPADHYAY", "INDIVIDUAL"))
        self.assertIn({"typeId": "SFCT_2", "dateTimeValue": "1962-06-29"}, payload["secondaryFields"])
        self.assertEqual(sent[1].full_url, "https://api-worldcheck.refinitiv.com/v2/reference/profile/e_tr_wci_1")
        h = hits[0]
        self.assertEqual((csid, h["uid"], h["strength"], h["dob_text"], h["dob_result"]), ("C-9", "e_tr_wci_1", "Strong", "1962-06-29", "Matched"))
        self.assertEqual((h["places"], h["narrative"], h["source"]), ("India (nationality)", "Reported in a fraud case.", "World-Check One"))

    def test_a_refusal_is_said_plainly(self):
        with mock.patch.object(world_check, "_send", lambda req: (401, b"")):
            with self.assertRaises(world_check.WorldCheckError) as e:
                world_check.groups(self.cfg)
        self.assertIn("401", str(e.exception))
        with mock.patch.object(world_check, "_send", lambda req: (500, b"boom")):
            hits, source, error, _, _ = id_screening.search(WHO, {"world_check": self.cfg, "max_hits": 5, "name_threshold": 75})
        self.assertEqual((hits, source), ([], "World-Check One"))
        self.assertIn("500", error)


class ScreeningBookPageTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        fcc.app.testing = True
        fcc.app.secret_key = "test"
        cls.book_before = fcc.CASE_BOOK
        fcc.CASE_BOOK = "screening"
        StateStore.clear()
        fcc._load_seed()

    @classmethod
    def tearDownClass(cls):
        fcc.CASE_BOOK = cls.book_before
        StateStore.clear()
        fcc._load_seed()

    def setUp(self):
        for rec in StateStore.records("scan"):
            StateStore.delete("scan", [rec["id"]])
        StateStore.delete(id_screening.SOP_KIND, [r["id"] for r in StateStore.records(id_screening.SOP_KIND)])
        fcc.SCREEN_SETTINGS.clear()
        fcc.SCREEN_SETTINGS.update(id_screening.default_settings(), auto_verify=False)    # the auto-verify tests turn it on
        self.calls = []

    def client(self, who="amara.iyer"):
        c = fcc.app.test_client()
        c.post("/login", data={"analyst": who, "password": "1234"})
        return c

    def png(self, colour="white"):
        from PIL import Image
        out = io.BytesIO()
        Image.new("RGB", (900, 600), colour).save(out, "PNG")
        return out.getvalue()

    def decide(self, case_id, who, hit, sop, settings):
        self.calls.append((case_id, hit["uid"], sop["version"]))
        return {"status": "done", "outcome": "clear", "label": "Clear (false positive)", "suggested": "False positive",
                "confidence": 80, "reasons": ["Different date of birth"], "dob_finding": "", "request": "", "examples": ["KYC-1"],
                "name_variance": "", "address_variance": "", "model": "m", "model_label": "Model", "sop": sop["version"],
                "seconds": 1.0, "cost": 0.01}

    def upload(self, c, read, colour="white"):
        result = {"read": read, "model": {"model": "m", "label": "Model", "tokens_in": 1, "tokens_out": 1, "cost": 0.0, "seconds": 1.0},
                  "checks": id_scan.checks(read), "error": ""}
        with mock.patch.object(id_scan, "scan", lambda jpeg, *a, **k: dict(result)), \
                mock.patch.object(id_screening, "decide", self.decide):
            r = c.post("/scan", data={"image": (io.BytesIO(self.png(colour)), "id.png")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        return r.headers["Location"].rsplit("/", 1)[-1]

    def test_an_empty_start_and_a_screening_menu(self):
        self.assertEqual((len(fcc.KYC_CASES), len(fcc.ALERT_CASES), len(fcc.WC_CASES)), (0, 0, 0))
        c = self.client()
        self.assertTrue(c.get("/").headers["Location"].endswith("/scan"))
        page = c.get("/scan").data.decode("utf-8")
        for needle in ('id="scan-empty"', "Screening SOP", "Settings", "Stand-in World-Check"):
            self.assertIn(needle, page)
        self.assertNotIn("Due Diligence", page)

    def test_upload_to_closed_case(self):
        c = self.client()
        sid = self.upload(c, a_read())
        rec = fcc._scan(sid)
        hit = rec["screening"]["hits"][0]
        self.assertEqual((rec["status"], rec["screening"]["source"], hit["uid"]), ("open", "stand-in", "WC-675768"))
        self.assertEqual((hit["ai"]["status"], hit["ai"]["suggested"]), ("done", "False positive"))
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        for needle in ('id="case-rail"', 'id="scan-screening"', "Screening Alert Hit", f'href="/scan/{sid}/screening"',
                       "Human-in-the-loop", "AI Review", "S3321051", 'id="scan-decisions"'):
            self.assertIn(needle, page)
        for absent in ("jumio", "Merchant UID", "Business Line", "Breached"):   # nothing the upload does not have
            self.assertNotIn(absent, page)
        self.assertEqual([p["state"] for p in id_screening.progress(rec)], ["done", "done", "done", "done", "current"])
        page = c.get(f"/scan/{sid}/screening").data.decode("utf-8")
        for needle in ("Basic Information", "Screening Information", "List Screening (1 matches found)", "UPADHYAY, Ashish",
                       "Patna, Bihar, India", "False Positive · 80%", "Different date of birth", "Pending (1)", "Change Alert Outcome"):
            self.assertIn(needle, page)
        bad = c.post(f"/scan/{sid}/hits/outcome", data={"alert_id": hit["uid"], "outcome": "True Positive", "comment": ""},
                     follow_redirects=True)
        self.assertIn("Write a comment", bad.data.decode("utf-8"))
        c.post(f"/scan/{sid}/hits/outcome", data={"alert_id": hit["uid"], "outcome": "True Positive", "risk": "High",
                                                  "reason": "Confirmed by identification", "comment": "same date of birth"})
        rec = fcc._scan(sid)
        self.assertEqual((rec["status"], rec["closed"]["outcome"]), ("closed", "True match"))
        res = rec["screening"]["hits"][0]["resolution"]
        self.assertEqual((res["status"], res["risk"], res["reason"], res["agreed"]), ("True match", "High", "Confirmed by identification", False))
        self.assertEqual({p["state"] for p in id_screening.progress(rec)}, {"done"})
        page = c.get(f"/scan/{sid}/screening").data.decode("utf-8")
        self.assertIn("True Positive (1)", page)
        self.assertIn("The analyst decided True Positive", page)
        data = c.get(f"/scan/{sid}/data.json").get_json()
        self.assertEqual((data["outcome"], data["screening"]["hits"][0]["resolution"]["status"]), ("True match", "True match"))
        self.assertIn("Closed", c.get("/scan?status=closed").data.decode("utf-8"))

    def test_the_world_check_console_shows_and_resolves_the_case(self):
        c = self.client()
        sid = self.upload(c, a_read())
        uid = fcc._scan(sid)["screening"]["hits"][0]["uid"]
        self.assertIn(f'href="/wc/{sid}" target="_blank"', c.get(f"/scan/{sid}").data.decode("utf-8"))
        page = c.get(f"/scan/{sid}/screening").data.decode("utf-8")
        self.assertIn(f'href="/wc/{sid}" target="_blank"', page)
        self.assertIn(f'href="/wc/{sid}/match/{uid}" target="_blank"', page)
        page = c.get(f"/wc/{sid}").data.decode("utf-8")
        for needle in ("World-Check console", "UPADHYAY, Ashish", "UNRESOLVED", "Stand-in (reconciliation log)",
                       "<th>AI suggestion</th>", '<span class="badge emerald">False positive</span> <span class="tiny muted">80%</span>'):
            self.assertIn(needle, page)
        page = c.get(f"/wc/{sid}/match/{uid}").data.decode("utf-8")
        for needle in ("Comparison data", "Potential match", "Patna", "ponzi",
                       'id="wc-ai"', "Clear (false positive)", "confidence 80%", "Different date of birth", "Ask the AI again"):
            self.assertIn(needle, page)
        self.assertNotIn('value="Unspecified"', page)              # the three verdicts a hit can take
        with mock.patch.object(id_screening, "decide", self.decide):
            r = c.post(f"/scan/{sid}/hits/{uid}/ai", data={"back": "wc"})
        self.assertTrue(r.headers["Location"].endswith(f"/wc/{sid}/match/{uid}"))
        self.assertEqual(len(self.calls), 2)
        bad = c.post(f"/wc/{sid}/match/{uid}/resolve", data={"status": "True positive", "risk": "High", "reason": "", "comment": "x"},
                     follow_redirects=True)
        self.assertIn("Select a reason", bad.data.decode("utf-8"))
        c.post(f"/wc/{sid}/match/{uid}/resolve", data={"status": "True positive", "risk": "High",
                                                        "reason": "Confirmed by identification", "comment": "Same date and city"})
        rec = fcc._scan(sid)
        res = rec["screening"]["hits"][0]["resolution"]
        self.assertEqual((res["status"], res["risk"], res["reason"], rec["status"], rec["closed"]["outcome"]),
                         ("True match", "High", "Confirmed by identification", "closed", "True match"))
        self.assertIn("Match resolved: True positive", c.get(f"/wc/{sid}?tab=audit").data.decode("utf-8"))
        self.assertEqual(c.post(f"/wc/{sid}/export").status_code, 302)
        self.assertTrue(c.get(f"/wc/{sid}/export.pdf").data.startswith(b"%PDF"))
        self.assertTrue(fcc._scan(sid)["wc_exports"])

    def test_no_hit_is_confirmed_and_closed(self):
        c = self.client()
        sid = self.upload(c, a_read(name="ZEBEDIAH QUARTERMAINE", surname="QUARTERMAINE", given="ZEBEDIAH"))
        self.assertEqual(fcc._scan(sid)["screening"]["hits"], [])
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn('id="screen-none"', page)
        self.assertIn("No hit: confirm no match on the Screening tab", page)
        c.post(f"/scan/{sid}/close", data={"note": "nobody on the list"})
        self.assertEqual(fcc._scan(sid)["closed"]["outcome"], "No match")
        self.assertEqual(self.calls, [])

    def test_the_model_evaluation_follows_the_uploads(self):
        c = self.client()
        self.assertIn('id="eval-empty"', c.get("/model-evaluation").data.decode("utf-8"))
        sid = self.upload(c, a_read())
        uid = fcc._scan(sid)["screening"]["hits"][0]["uid"]
        c.post(f"/scan/{sid}/hits/outcome", data={"alert_id": uid, "outcome": "False Positive", "comment": "different person"})
        page = c.get("/model-evaluation").data.decode("utf-8")
        for needle in ('id="eval-reading-table"', 'id="eval-deciding-table"', 'id="eval-matrices"', 'id="eval-sop"', "1 · 100.0%"):
            self.assertIn(needle, page)
        for absent in ('id="eval-empty"', "Console rules today", "decision tree", "Tesseract"):
            self.assertNotIn(absent, page)
        sid = self.upload(c, a_read(), "ivory")                      # the AI says false positive; the analyst does not
        uid = fcc._scan(sid)["screening"]["hits"][0]["uid"]
        c.post(f"/scan/{sid}/hits/outcome", data={"alert_id": uid, "outcome": "True Positive", "comment": "same person"})
        [m] = upload_eval.deciding(fcc._scans())
        self.assertEqual((m["decided"], m["confirmed"], m["agreed"], m["cleared_wrongly"]), (2, 2, 1, 1))
        self.assertEqual(m["matrix"]["cells"]["True match"]["False positive"], 1)
        self.assertEqual(upload_eval.reading(fcc._scans())[0]["reads"], 2)
        page = c.get("/architecture").data.decode("utf-8")
        for needle in ('id="arch-pipeline"', 'id="arch-split"', 'id="arch-apis"', "2 uploaded IDs read", "agreeing with the AI on 1 of the 2"):
            self.assertIn(needle, page)
        for absent in ("Tesseract", "CSV", "second opinion"):
            self.assertNotIn(absent, page)

    def test_auto_verify_closes_the_safe_cases_only(self):
        fcc.SCREEN_SETTINGS.update(auto_verify=True, auto_qc_pct=0)
        c = self.client()
        sid = self.upload(c, a_read(name="ZEBEDIAH QUARTERMAINE", surname="QUARTERMAINE", given="ZEBEDIAH"))
        rec = fcc._scan(sid)                                         # no hit, every check passed
        self.assertEqual((rec["status"], rec["closed"]["outcome"], rec["closed"]["by"], rec["closed"].get("auto")),
                         ("closed", "No match", id_screening.AUTO_ACTOR, True))
        refused = c.post(f"/scan/{sid}/close", data={"note": "again"}, follow_redirects=True)
        self.assertIn("The case is closed", refused.data.decode("utf-8"))
        plain = self.decide
        with mock.patch.object(self, "decide", lambda *a, **k: dict(plain(*a, **k), confidence=95)):
            sid = self.upload(c, a_read(dob="1970-01-01"), "ivory")    # a different date of birth, an adverse-media record
        rec = fcc._scan(sid)
        res = rec["screening"]["hits"][0]["resolution"]
        self.assertEqual((rec["status"], rec["closed"]["outcome"], res["by"], res["auto"]), ("closed", "Cleared", id_screening.AUTO_ACTOR, True))
        self.assertIn("95%", res["note"])
        sid = self.upload(c, a_read(), "linen")                       # the same date of birth (and 80% sure): an analyst's
        self.assertEqual(fcc._scan(sid)["status"], "open")
        page = c.get("/scan").data.decode("utf-8")
        for needle in ('Auto-verified <span class="n">2</span>', 'Needs an analyst <span class="n">1</span>'):
            self.assertIn(needle, page)
        self.assertIn("Cleared by the rule", c.get(f"/scan/{rec['id']}").data.decode("utf-8"))
        self.assertIn("Cleared by the AI screening rule", c.get(f"/scan/{rec['id']}/screening").data.decode("utf-8"))
        [m] = upload_eval.deciding(fcc._scans())
        self.assertEqual((m["auto"], m["confirmed"]), (1, 0))      # the rule's clear is not an analyst's answer
        self.assertEqual(upload_eval.totals(fcc._scans())["auto_closed"], 2)
        self.assertIn('id="settings-auto"', c.get("/screening/settings").data.decode("utf-8"))

    def test_the_rule(self):
        s = id_screening.default_settings()
        case = {"id": "SCAN-1", "verdict": "Pass", "status": "open"}
        hit = {"uid": "WC-1", "category": "Adverse Media - Fraud", "dob_result": "Not matched",
               "ai": {"status": "done", "outcome": "clear", "confidence": 92}}
        self.assertTrue(id_screening.hit_is_safe(case, hit, s)[0])
        self.assertIn("ID check", id_screening.hit_is_safe(dict(case, verdict="Check"), hit, s)[1])
        for change, why in (({"category": "Sanctions (OFAC SDN)"}, "Sanctions"), ({"category": "PEP - Level 2"}, "PEP"),
                            ({"dob_result": "Matched"}, "date of birth"), ({"dob_result": "Unknown"}, "date of birth"),
                            ({"ai": dict(hit["ai"], confidence=85)}, "85%"), ({"ai": dict(hit["ai"], outcome="escalate")}, "false positive")):
            ok, said = id_screening.hit_is_safe(case, dict(hit, **change), s)
            self.assertFalse(ok)
            self.assertIn(why, said)
        self.assertTrue(id_screening.hit_is_safe(case, dict(hit, dob_result="Matched"), dict(s, auto_dob_differs=False))[0])
        two = {"id": "SCAN-2", "verdict": "Pass", "status": "open",
               "screening": {"hits": [dict(hit, uid="A"), dict(hit, uid="B", category="Sanctions")]}}
        self.assertEqual(id_screening.auto_verify(two, dict(s, auto_qc_pct=0)), "cleared")   # the sanctions hit stays
        self.assertEqual([h["uid"] for h in id_screening.open_hits(two)], ["B"])
        waiting = {"id": "SCAN-3", "verdict": "Pass", "status": "open",
                   "screening": {"hits": [dict(hit), dict(hit, uid="B", ai={"status": "pending"})]}}
        self.assertEqual(id_screening.auto_verify(waiting, s), "")                # not before the AI answered every hit
        sampled = {"id": "SCAN-4", "verdict": "Pass", "status": "open", "screening": {"hits": [dict(hit)]}}
        self.assertEqual(id_screening.auto_verify(sampled, dict(s, auto_qc_pct=100)), "qc sample")
        self.assertEqual((sampled["status"], bool(sampled["qc_sample"])), ("open", True))
        self.assertEqual(id_screening.auto_verify(sampled, dict(s, auto_verify=False)), "")

    def test_settings_say_who_can_edit(self):
        page = self.client().get("/screening/settings").data.decode("utf-8")
        self.assertIn('id="settings-locked"', page)
        self.assertIn("Leah Fernandez", page)
        page = self.client("leah.fernandez").get("/screening/settings").data.decode("utf-8")
        self.assertNotIn('id="settings-locked"', page)
        self.assertNotIn(" disabled>", page.split('id="settings-intake"')[0].split('id="settings-form"')[1].replace('disabled title=', ''))

    def test_the_intake_api(self):
        qc = self.client("leah.fernandez")
        self.assertEqual(self.client().post("/screening/settings/intake-keys", data={"name": "x"}).status_code, 302)
        self.assertEqual(fcc.SCREEN_SETTINGS["intake_keys"], [])                 # only the QC lead creates keys
        qc.post("/screening/settings/intake-keys", data={"name": "Onboarding app"})
        page = qc.get("/screening/settings").data.decode("utf-8")
        key = page.split('id="intake-new-key"')[1].split("<code>")[1].split("</code>")[0]
        self.assertTrue(key.startswith("fcc_"))
        self.assertNotIn(key, qc.get("/screening/settings").data.decode("utf-8"))   # shown once
        self.assertNotIn(key, str(fcc.SCREEN_SETTINGS["intake_keys"]))           # kept as a fingerprint only
        api = fcc.app.test_client()                                               # no session: the key is the login
        self.assertEqual(api.post("/api/v1/cases").status_code, 401)
        self.assertEqual(api.post("/api/v1/cases", headers={"X-API-Key": "fcc_wrong"}).status_code, 401)
        read = a_read()
        result = {"read": read, "model": {"model": "m", "label": "Model", "tokens_in": 1, "tokens_out": 1, "cost": 0.0, "seconds": 1.0},
                  "checks": id_scan.checks(read), "error": ""}
        with mock.patch.object(id_scan, "scan", lambda jpeg, *a, **k: dict(result)), \
                mock.patch.object(id_screening, "decide", self.decide):
            r = api.post("/api/v1/cases", headers={"X-API-Key": key}, content_type="multipart/form-data",
                         data={"image": (io.BytesIO(self.png()), "passport.png"), "reference": "CUST-1042"})
            self.assertEqual(r.status_code, 201, r.data)
            body = r.get_json()
            self.assertEqual((body["reference"], body["uploaded_by"], body["status"], body["screening"]["hits"][0]["ai"]["suggested"]),
                             ("CUST-1042", "Intake API (Onboarding app)", "open", "False positive"))
            import base64
            r = api.post("/api/v1/cases", headers={"Authorization": "Bearer " + key},
                         json={"image_base64": base64.b64encode(self.png("ivory")).decode(), "reference": "CUST-7"})
            self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(api.post("/api/v1/cases", headers={"X-API-Key": key}, json={"image_base64": "%%%"}).status_code, 400)
        sid = body["scan_id"]
        self.assertEqual(api.get(f"/api/v1/cases/{sid}", headers={"X-API-Key": key}).get_json()["scan_id"], sid)
        self.assertEqual(api.get("/api/v1/cases/SCAN-none", headers={"X-API-Key": key}).status_code, 404)
        found = api.get("/api/v1/cases?reference=CUST-1042", headers={"X-API-Key": key}).get_json()["cases"]
        self.assertEqual([c["scan_id"] for c in found], [sid])
        self.assertTrue(fcc.SCREEN_SETTINGS["intake_keys"][0]["last_used"])
        qc.post(f"/screening/settings/intake-keys/{fcc.SCREEN_SETTINGS['intake_keys'][0]['id']}/revoke")
        self.assertEqual(api.get(f"/api/v1/cases/{sid}", headers={"X-API-Key": key}).status_code, 401)

    def test_didit_verifies_the_id_and_holds_back_a_declined_one(self):
        from fincrime.adapters import didit
        fcc.SCREEN_SETTINGS.update(auto_verify=True, auto_qc_pct=0)
        fcc.SCREEN_SETTINGS["didit"]["api_key"] = "DD-KEY"
        answer = {"request_id": "R", "id_verification": {"status": "Declined", "document_type": "Passport", "warnings": [
            {"risk": "SCREEN_CAPTURE_DETECTED", "log_type": "error", "short_description": "Screen capture detected"}]}}
        import json as _json
        with mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(answer).encode())):
            c = self.client()
            sid = self.upload(c, a_read(name="ZEBEDIAH QUARTERMAINE", surname="QUARTERMAINE", given="ZEBEDIAH"))
        rec = fcc._scan(sid)
        self.assertEqual((rec["idv"]["status"], rec["status"]), ("Declined", "open"))   # no hit, but not auto-verified
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        for needle in ('id="id-vendor"', "Screen capture detected", "Verify again"):
            self.assertIn(needle, page)
        answer["id_verification"].update(status="Approved", warnings=[])
        with mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(answer).encode())):
            c.post(f"/scan/{sid}/idv")
        rec = fcc._scan(sid)
        self.assertEqual((rec["idv"]["status"], rec["status"], rec["closed"]["by"]), ("Approved", "closed", id_screening.AUTO_ACTOR))
        with mock.patch.object(didit, "_send", lambda req: (403, b'{"error": "no credits"}')):
            sid = self.upload(c, a_read(name="ZEBEDIAH QUARTERMAINE", surname="QUARTERMAINE", given="ZEBEDIAH"), "ivory")
        rec = fcc._scan(sid)
        self.assertEqual((rec["idv"]["status"], rec["status"]), ("error", "open"))      # not checked: an analyst's
        self.assertIn("refused the call", rec["idv"]["error"])
        self.assertEqual(c.get(f"/api/v1/cases/{sid}").status_code, 401)             # the API never takes a session

    def test_didit_must_approve_this_very_document(self):
        from fincrime.adapters import didit
        fcc.SCREEN_SETTINGS.update(auto_verify=True, auto_qc_pct=0)
        fcc.SCREEN_SETTINGS["didit"]["api_key"] = "DD-KEY"
        import json as _json
        zeb = a_read(name="ZEBEDIAH QUARTERMAINE", surname="QUARTERMAINE", given="ZEBEDIAH")

        def answered(**v):
            body = {"request_id": "R", "id_verification": dict({"status": "Approved", "warnings": []}, **v)}
            return mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(body).encode()))
        c = self.client()
        with answered(full_name="Sandbox User", date_of_birth="1990-01-15", document_number="SANDBOX-0001"):
            sid = self.upload(c, zeb)
        rec = fcc._scan(sid)
        self.assertEqual((rec["idv"]["status"], rec["idv"]["cost"], rec["status"]), ("Approved", 0.0, "open"))
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        for needle in ("Sandbox: not a real check", 'id="idv-sandbox"', "free (sandbox)", "Name differs"):
            self.assertIn(needle, page)
        self.assertEqual(c.get(f"/api/v1/cases/{sid}").status_code, 401)
        with answered(full_name="ZEBEDIAH OTHERNAME", document_number=zeb["fields"]["document_number"]):
            sid = self.upload(c, zeb, "ivory")
        rec = fcc._scan(sid)
        self.assertEqual(rec["status"], "open")                                   # approved, but another person's document
        self.assertEqual([d[0] for d in id_screening.idv_differences(rec)], ["Name"])
        self.assertIn("read a different name", id_screening.idv_approved(rec)[1])
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn('id="idv-differs"', page)
        self.assertIn("Approved a different document", page)
        with answered(status="Declined", full_name="ZEBEDIAH OTHERNAME", document_number=zeb["fields"]["document_number"]):
            sid = self.upload(c, zeb, "beige")
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn('Didit answered "Declined", and what it read differs from the ID', page)   # the decline counts
        self.assertNotIn("does not count", page)
        with answered(full_name="QUARTERMAINE ZEBEDIAH", date_of_birth=zeb["fields"]["date_of_birth"],
                      document_number=zeb["fields"]["document_number"]):
            sid = self.upload(c, zeb, "linen")
        rec = fcc._scan(sid)
        self.assertEqual((id_screening.idv_differences(rec), rec["status"]), ([], "closed"))   # the same, in another order

    def test_read_with_ai_or_with_ocr(self):
        from fincrime.documents import ocr
        fcc.SCREEN_SETTINGS.update(auto_verify=True, auto_qc_pct=0)
        c = self.client()
        with mock.patch.object(ocr, "available", lambda: True):
            page = c.get("/scan").data.decode("utf-8")
            self.assertIn('id="scan-submit-ocr"', page)
            self.assertIn("Read with AI", page)
            zeb = a_read(name="ZEBEDIAH QUARTERMAINE", surname="QUARTERMAINE", given="ZEBEDIAH")
            zeb.update(ocr_text="PASSPORT QUARTERMAINE", photo_judged=False, mrz_by="OCR's reading", fields_from_mrz=True)
            used = dict(ocr.MODEL, cost=0.0, seconds=9.1)
            with mock.patch.object(ocr, "id_read", lambda data, keys: (dict(zeb), dict(used))), \
                    mock.patch.object(id_scan, "scan", lambda *a, **k: self.fail("the AI must not read an OCR upload")):
                r = c.post("/scan", data={"image": (io.BytesIO(self.png()), "id.png"), "via": "ocr"}, content_type="multipart/form-data")
        rec = fcc._scan(r.headers["Location"].rsplit("/", 1)[-1])
        self.assertEqual((rec["model"]["model"], rec["verdict"], rec["status"]), ("tesseract-ocr", "Check", "open"))   # never auto-verified
        page = c.get(f"/scan/{rec['id']}").data.decode("utf-8")
        for needle in ('id="scan-ocr-text"', "PASSPORT QUARTERMAINE", "free (on this machine)", "Not judged"):
            self.assertIn(needle, page)
        with mock.patch.object(ocr, "available", lambda: False):
            self.assertIn('id="scan-submit-ocr" disabled', c.get("/scan").data.decode("utf-8"))
            r = c.post("/scan", data={"image": (io.BytesIO(self.png("ivory")), "id.png"), "via": "ocr"}, content_type="multipart/form-data")
        rec = fcc._scan(r.headers["Location"].rsplit("/", 1)[-1])
        self.assertIn("not installed", rec["error"])

    def test_a_middle_name_left_out_is_the_same_name(self):
        case = {"idv": {"status": "Approved", "full_name": "Margaret Wallace", "date_of_birth": "1965-09-08", "document_number": "623 984 704"},
                "read": {"fields": {"full_name": "WALLACE MARGARET MARIE", "date_of_birth": "1965-09-08", "document_number": "623984704"}}}
        self.assertEqual(id_screening.idv_approved(case), (True, ""))
        case["idv"]["date_of_birth"] = "1965-08-09"
        self.assertEqual([d[0] for d in id_screening.idv_differences(case)], ["Date of birth"])
        self.assertEqual(id_screening.idv_approved({}), (True, ""))                  # none set up

    def test_azure_reads_and_the_ai_model_stands_in_when_it_cannot(self):
        from fincrime.adapters import azure_docintel
        fcc.SCREEN_SETTINGS["azure"].update(endpoint="https://res.cognitiveservices.azure.com", api_key="AZ")
        fcc.SCREEN_SETTINGS["reader_model"] = "azure-docintel"
        result = {"pages": [{}], "documents": [{"docType": "idDocument.passport", "fields": {
            "FirstName": {"valueString": "ASHISH", "confidence": 0.99}, "LastName": {"valueString": "UPADHYAY", "confidence": 0.99},
            "DateOfBirth": {"valueDate": "1962-06-29", "confidence": 0.99}, "DocumentNumber": {"valueString": "S3321051", "confidence": 0.99},
            "CountryRegion": {"valueCountryRegion": "IND", "confidence": 0.99}}}]}
        c = self.client()
        self.assertIn("Azure AI Document Intelligence", c.get("/scan").data.decode("utf-8"))   # offered as a reader
        with mock.patch.object(azure_docintel, "analyze", lambda cfg, jpeg, sleep=None: result), \
                mock.patch.object(id_screening, "decide", self.decide):
            r = c.post("/scan", data={"image": (io.BytesIO(self.png()), "id.png")}, content_type="multipart/form-data")
        rec = fcc._scan(r.headers["Location"].rsplit("/", 1)[-1])
        self.assertEqual((rec["model"]["model"], rec["read"]["fields"]["full_name"], rec["screening"]["hits"][0]["uid"]),
                         ("azure-docintel", "ASHISH UPADHYAY", "WC-675768"))

        def refused(cfg, jpeg, sleep=None):
            raise azure_docintel.AzureError("Azure refused the key (401)")
        sid = self.upload(c, a_read(), "ivory")                                      # stands the AI model in
        with mock.patch.object(azure_docintel, "analyze", refused):
            sid = self.upload(c, a_read(), "linen")
        rec = fcc._scan(sid)
        self.assertEqual(rec["model"]["model"], "m")
        self.assertIn("Azure refused the key", rec["fallback"])
        self.assertIn("reader-fallback", c.get(f"/scan/{sid}").data.decode("utf-8"))
        self.assertIn("Azure key entered", c.get("/architecture").data.decode("utf-8"))

    def test_ai_assessment_sends_the_alerts_again(self):
        c = self.client()
        sid = self.upload(c, a_read())
        uid = fcc._scan(sid)["screening"]["hits"][0]["uid"]
        with mock.patch.object(id_screening, "decide", self.decide):
            r = c.post(f"/scan/{sid}/ai", data={"alert_id": uid})
            self.assertTrue(r.headers["Location"].endswith(f"/scan/{sid}/screening"))
            c.post(f"/scan/{sid}/ai")                                   # nothing ticked: every alert with no outcome
        self.assertEqual(len(self.calls), 3)
        refused = c.post(f"/scan/{sid}/hits/outcome", data={"outcome": "False Positive", "comment": "x"}, follow_redirects=True)
        self.assertIn("Tick at least one alert", refused.data.decode("utf-8"))

    def test_a_new_sop_version_sends_open_hits_again(self):
        c = self.client()
        sid = self.upload(c, a_read())
        before = fcc._scan(sid)["screening"]["hits"][0]["ai"]["sop"]
        current = id_screening.sop_current([])["text"]
        refused = self.client().post("/screening/sop", data={"text": current + "\nMore.", "note": "x"}, follow_redirects=True)
        self.assertIn("Only the QC lead", refused.data.decode("utf-8"))
        qc = self.client("leah.fernandez")
        with mock.patch.object(id_screening, "decide", self.decide):
            qc.post("/screening/sop", data={"text": current + "\n\n## 9. Extra\nAsk the customer first.", "note": "added 9"})
        after = fcc._scan(sid)["screening"]["hits"][0]["ai"]
        self.assertNotEqual(after["sop"], before)
        self.assertEqual(after["sop"], id_screening.sop_current(StateStore.records(id_screening.SOP_KIND))["version"])
        self.assertIn("added 9", qc.get("/screening/sop").data.decode("utf-8"))

    def test_settings_keep_the_secret_out_of_the_page(self):
        refused = self.client().post("/screening/settings", data={"examples": "3"}, follow_redirects=True)
        self.assertIn("Only the QC lead", refused.data.decode("utf-8"))
        qc = self.client("leah.fernandez")
        qc.post("/screening/settings", data={"api_key": "KEY-1", "api_secret": "top-secret-value", "group_id": "G-1",
                                             "host": "", "base_path": "/v2/", "screen_path": "cases/screeningRequest",
                                             "groups_path": "groups", "profile_path": "reference/profile/{id}",
                                             "reader_model": "gemini-2.5-flash", "decision_model": "gpt-5", "examples": "4",
                                             "name_threshold": "80", "max_hits": "3"})
        s = fcc.SCREEN_SETTINGS
        self.assertEqual((s["decision_model"], s["examples"], s["world_check"]["host"]), ("gpt-5", 4, world_check.DEFAULTS["host"]))
        page = qc.get("/screening/settings").data.decode("utf-8")
        self.assertNotIn("top-secret-value", page)
        self.assertIn("Live World-Check One", page)
        qc.post("/screening/settings", data={"api_secret": "", "examples": "4", "name_threshold": "80", "max_hits": "3"})
        self.assertEqual(fcc.SCREEN_SETTINGS["world_check"]["api_secret"], "top-secret-value")   # blank keeps it
        with mock.patch.object(world_check, "screen", lambda cfg, who, limit=5: ([], "C-1")) as _:
            sid = self.upload(self.client(), a_read())
        self.assertEqual(fcc._scan(sid)["screening"]["source"], "World-Check One")

    def test_the_checks_strengths_and_lists_are_settings(self):
        qc = self.client("leah.fernandez")
        form = {"checks_form": "1", "min_age": "70", "band_exact": "100", "band_strong": "95", "band_medium": "85",
                "alert_reasons": "Different person\nDifferent person\n  Same person  \n", "risk_levels": "Low\nHigh"}
        qc.post("/screening/settings", data=form)
        s = fcc.SCREEN_SETTINGS
        self.assertEqual((s["min_age"], s["strength_bands"], s["alert_reasons"], s["risk_levels"]),
                         (70, {"Exact": 100, "Strong": 95, "Medium": 85}, ["Different person", "Same person"], ["Low", "High"]))
        self.assertIn('id="settings-checks"', qc.get("/screening/settings").data.decode("utf-8"))
        bad = qc.post("/screening/settings", data=dict(form, band_medium="99"), follow_redirects=True).data.decode("utf-8")
        self.assertIn("The match strengths rise", bad)
        self.assertEqual(s["strength_bands"]["Medium"], 85)                       # nothing saved
        # the age limit goes to the reader's checks
        seen = []
        with mock.patch.object(id_scan, "scan", lambda jpeg, model_id=None, min_age=18, *a: seen.append(min_age) or
                               {"read": None, "model": None, "checks": [], "error": "not read"}):
            self.client().post("/scan", data={"image": (io.BytesIO(self.png()), "id.png")}, content_type="multipart/form-data")
        self.assertEqual(seen, [70])
        age = next(c for c in id_scan.checks(a_read(), min_age=70) if c["label"] == "Age")    # born 1962
        self.assertEqual((age["state"], "under 70" in age["detail"]), ("warn", True))
        self.assertEqual(next(c for c in id_scan.checks(a_read(), min_age=0) if c["label"] == "Age")["state"], "ok")
        # the bands name the stand-in's hits
        self.assertEqual((watchlist.strength(96, s["strength_bands"]), watchlist.strength(94, s["strength_bands"]),
                          watchlist.strength(94)), ("Strong", "Medium", "Strong"))
        # the lists are what the analyst picks from
        sid = self.upload(self.client(), a_read())
        page = self.client().get(f"/scan/{sid}/screening").data.decode("utf-8")
        self.assertIn("<option>Same person</option>", page)
        self.assertNotIn("Nationality mismatch", page)

    def test_the_models_are_settings(self):
        self.addCleanup(benchmark.RETRY.update, dict(benchmark.RETRY))
        qc = self.client("leah.fernandez")
        self.assertIn('id="model-catalogue"', qc.get("/screening/settings").data.decode("utf-8"))
        cat, form = fcc.SCREEN_SETTINGS["models"], {"models_form": "1", "llm_retries": "1", "llm_retry_wait": "5", "screen_workers": "2",
                                                    "reader_instructions": "", "examples": "6", "name_threshold": "65", "max_hits": "5"}
        for i, m in enumerate(cat):                                          # the table as the page sends it back
            form.update({f"m_id_{i}": m["id"], f"m_label_{i}": m["label"], f"m_provider_{i}": m["provider"],
                         f"m_in_{i}": str(m["price"][0]), f"m_out_{i}": str(m["price"][1])})
            form.update({f"m_{k}_{i}": "1" for k, on in (("reads", m["reads"]), ("decides", m["decides"]),
                                                          ("thinking", not m["no_thinking"])) if on})
        n = len(cat)
        form.update({"m_rows": str(n), f"m_id_{n}": "gemini-3-flash", f"m_label_{n}": "Gemini 3 Flash", f"m_provider_{n}": "gemini",
                     f"m_in_{n}": "0.5", f"m_out_{n}": "3", f"m_reads_{n}": "1", f"m_decides_{n}": "1", "m_remove_0": "1"})
        qc.post("/screening/settings", data=dict(form, reader_model="gemini-3-flash", decision_model="gemini-3-flash"))
        s = fcc.SCREEN_SETTINGS
        self.assertNotIn("claude-opus-4-8", [m["id"] for m in s["models"]])            # removed
        new = s["models"][-1]
        self.assertEqual((new["id"], new["price"], new["reads"], new["decides"], new["no_thinking"]),
                         ("gemini-3-flash", [0.5, 3.0], True, True, True))
        self.assertEqual((s["reader_model"], s["decision_model"], s["screen_workers"]), ("gemini-3-flash", "gemini-3-flash", 2))
        self.assertEqual(benchmark.RETRY, {"tries": 1, "wait": 5})
        # the reader and the decider are the catalogue's, the reader told the instructions on Settings
        text = "Read the identity document in the picture and transcribe every printed field exactly as printed. " * 2
        qc.post("/screening/settings", data=dict(form, m_rows=str(n + 1), reader_instructions=text, **{f"m_id_{n + 1}": ""}))
        self.assertEqual(s["reader_instructions"], text.strip())
        seen = []

        def call(model, content, system=None, schema=None):
            seen.append((model["id"], system))
            return (dict(a_read(), fields=a_read()["fields"]) if schema is id_scan.SCHEMA else dict(ANSWER)), 10, 10
        with mock.patch.object(llm, "KEY", "x"), mock.patch.object(benchmark, "call", call):
            fcc._read_id(b"jpeg", "gemini-3-flash")
            id_screening.decide("SCAN-1", WHO, watchlist.search(WHO)[0], id_screening.sop_current([]), s)
        self.assertEqual([(m, x == text.strip()) for m, x in seen], [("gemini-3-flash", True), ("gemini-3-flash", False)])
        # a catalogue with no decider is refused
        no_decider = {k: v for k, v in form.items() if not k.startswith("m_decides_")}
        page = qc.post("/screening/settings", data=no_decider, follow_redirects=True).data.decode("utf-8")
        self.assertIn("Keep at least one model that reads the ID and one that decides hits", page)

    def test_the_rules_are_settings(self):
        # what each ID check finding does: an expired ID fails by default, a rule can make it a note only
        old = dict(a_read(), fields=dict(a_read()["fields"], date_of_expiry="2020-01-01"))
        self.assertEqual(id_scan.verdict({"read": old, "checks": id_scan.checks(old)}), "Fail")
        noted = id_scan.checks(old, rules={"expired": "info", "nonsense": "fail", "under_age": "maybe"})
        self.assertEqual((next(c for c in noted if c["label"] == "Expiry")["state"], id_scan.verdict({"read": old, "checks": noted})),
                         ("info", "Pass"))
        # Settings keeps the rules; a wrong value saves nothing
        qc = self.client("leah.fernandez")
        page = qc.get("/screening/settings").data.decode("utf-8")
        for needle in ('id="settings-rules"', 'name="rule_expired"', 'name="suggest_escalate"', 'name="auto_needs_idv"',
                       'name="idv_agree_date_of_birth"'):
            self.assertIn(needle, page)
        form = {"rules_form": "1", "rule_expired": "warn", "suggest_escalate": "True match"}
        qc.post("/screening/settings", data=form)
        s = fcc.SCREEN_SETTINGS
        self.assertEqual((s["check_rules"]["expired"], s["check_rules"]["mrz_differs"], s["ai_suggestion"]["escalate"]),
                         ("warn", "fail", "True match"))
        bad = qc.post("/screening/settings", data=dict(form, rule_expired="ignore"), follow_redirects=True).data.decode("utf-8")
        self.assertIn("Each ID check finding", bad)
        self.assertEqual(s["check_rules"]["expired"], "warn")
        self.assertEqual(id_screening.settings_from({"check_rules": {"expired": "info"}})["check_rules"]["mrz_differs"], "fail")
        # the reader's checks follow them
        with mock.patch.object(id_scan, "model_ready", lambda: True), \
                mock.patch.object(id_scan, "_model_read", lambda jpeg, model, system=None: (old, {"model": model["id"]})):
            result = fcc._read_id(b"jpeg", s["reader_model"])
        self.assertEqual(id_scan.verdict(result), "Check")
        # the AI's answer suggests what the rule says
        self.assertEqual((id_screening.suggestion("escalate", s), id_screening.suggestion("clear", s)), ("True match", "False positive"))
        # Didit: what its read must agree on, and whether auto-verify needs it at all
        case = {"id": "SCAN-1", "verdict": "Pass", "status": "open", "read": a_read(),
                "idv": {"provider": "Didit", "status": "Approved", "full_name": "ASHISH UPADHYAY", "date_of_birth": "1970-01-01"}}
        hit = {"uid": "WC-1", "category": "Adverse Media", "dob_result": "Not matched",
               "ai": {"status": "done", "outcome": "clear", "suggested": "False positive", "confidence": 95}}
        self.assertIn("date of birth", id_screening.hit_is_safe(case, hit, s)[1])
        self.assertTrue(id_screening.hit_is_safe(case, hit, dict(s, idv_must_agree=["Name", "Document number"]))[0])
        declined = dict(case, idv=dict(case["idv"], status="Declined"))
        self.assertFalse(id_screening.hit_is_safe(declined, hit, s)[0])
        self.assertTrue(id_screening.hit_is_safe(declined, hit, dict(s, auto_needs_idv=False))[0])
        self.assertFalse(id_screening.hit_is_safe(case, dict(hit, ai=dict(hit["ai"], suggested="Possible match")),
                                                  dict(s, idv_must_agree=[]))[0])
        # the auto-verify card saves Didit's part
        qc.post("/screening/settings", data={"auto_form": "1", "auto_min_confidence": "90", "auto_qc_pct": "5",
                                             "idv_agree_full_name": "1"})
        self.assertEqual((s["auto_needs_idv"], s["idv_must_agree"]), (False, ["Name"]))

    def test_didit_aml_screening_is_a_third_place_to_screen(self):
        cfg = dict(didit.DEFAULTS, api_key="key", aml_adverse_media=True)
        who = id_screening.person(a_read())
        # what Didit is sent: the ID's name, date of birth, two-letter nationality, number, and the case
        body = didit.aml_query(who, "SCAN-1", cfg)
        self.assertEqual(body, {"full_name": "ASHISH UPADHYAY", "entity_type": "person", "save_api_request": True,
                                "date_of_birth": "1962-06-29", "nationality": "IN", "document_number": "S3321051",
                                "vendor_data": "SCAN-1", "include_adverse_media": True})
        self.assertNotIn("nationality", didit.aml_query(dict(who, nationality="INDIAN")))
        # its answer as console hits, best match first, with Didit's scores beside them
        sent = []
        with mock.patch.object(didit, "_send", lambda req: sent.append(req) or (200, _json.dumps(an_aml_answer(-100)).encode())):
            hits, aml = didit.aml_screen(cfg, who, 5, "SCAN-1")
        self.assertEqual((sent[0].full_url, sent[0].get_header("X-api-key")), ("https://verification.didit.me/v3/aml/", "key"))
        top = hits[0]
        self.assertEqual((top["uid"], top["name"], top["category"], top["score"], top["risk_score"], top["didit_review"]),
                         ("hit-001", "ASHISH UPADHYAY", "Sanctions", 97, 86.0, "Unreviewed"))
        self.assertEqual((top["dob_result"], top["country_result"], top["dob_text"], top["aka"], top["source"]),
                         ("Not matched", "Matched", "1970-01-01", ["A. Upadhyay"], "Didit AML"))
        self.assertIn("Example Sanctions List", top["narrative"])
        self.assertEqual((hits[1]["dob_result"], hits[1]["didit_review"]), ("Partly matched", "False Positive"))
        self.assertEqual((aml["status"], aml["score"], aml["request_id"], aml["cost"], aml["sandbox"]),
                         ("In Review", 86.0, "a1b2c3d4", 0.2, False))
        # refusals say why
        with mock.patch.object(didit, "_send", lambda req: (403, b'{"error": "You don\'t have enough credits"}')):
            with self.assertRaisesRegex(didit.DiditError, "no credits"):
                didit.aml_screen(cfg, who)
        # the free test: an empty name, refused after the key and credits are checked
        with mock.patch.object(didit, "_send", lambda req: sent.append(req) or (400, b'{"full_name": ["too short"]}')):
            self.assertIn("ready", didit.aml_test(cfg))
        self.assertEqual(_json.loads(sent[-1].data), {"full_name": ""})
        with mock.patch.object(didit, "_send", lambda req: (401, b"expired")):
            with self.assertRaisesRegex(didit.DiditError, "401"):
                didit.aml_test(cfg)

        # Settings: where the console screens; without the Didit key, the stand-in
        s = fcc.SCREEN_SETTINGS
        qc = self.client("leah.fernandez")
        qc.post("/screening/settings", data={"screening_source": "didit_aml"})
        self.assertEqual((s["screening_source"], id_screening.source(s)), ("didit_aml", "stand-in"))
        self.assertIn("is chosen, but its key is not on Settings", id_screening.source_label(s))
        s["didit"].update(api_key="key", auto=False)
        self.assertEqual(id_screening.source(s), "didit_aml")
        page = qc.get("/screening/settings").data.decode("utf-8")
        for needle in ('id="screening-source"', 'name="dd_aml_adverse_media"', 'name="dd_aml_sandbox_scenario"', "Live Didit AML",
                       'id="settings-didit-aml-test"'):
            self.assertIn(needle, page)
        with mock.patch.object(didit, "_send", lambda req: (400, b"{}")):
            self.assertIn("AML screening is ready", qc.post("/screening/settings/didit-aml-test", follow_redirects=True).data.decode("utf-8"))
        # an upload is screened on Didit; the AI sees Didit's scores; the case page says where it screened
        with mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(an_aml_answer(-100)).encode())):
            sid = self.upload(self.client(), a_read())
        rec = fcc._scan(sid)
        sc = rec["screening"]
        self.assertEqual((sc["source"], sc["case_system_id"], [h["uid"] for h in sc["hits"]], sc["hits"][0]["strength"]),
                         ("Didit AML", "a1b2c3d4", ["hit-001", "hit-002"], "Strong"))
        self.assertIn("Didit's own scoring: match 97 of 100, risk 86.0 of 100; Didit marked it Unreviewed",
                      id_screening.facts(sc["person"], sc["hits"][0]))
        page = self.client().get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn('id="didit-aml"', page)
        self.assertIn("In Review", page)
        self.assertEqual(self.client().get(f"/scan/{sid}/screening").status_code, 200)
        # a Didit error is the case's screening error
        with mock.patch.object(didit, "_send", lambda req: (500, b"down")):
            sid = self.upload(self.client(), a_read())
        self.assertIn("Didit answered 500", fcc._scan(sid)["screening"]["error"])
        # a sandbox scenario's fixed answer never closes a case, even with no hit
        s.update(auto_verify=True, auto_qc_pct=0)
        s["didit"]["aml_sandbox_scenario"] = "decline_aml_hit"
        with mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(an_aml_answer(scenario_hits=[])).encode())):
            sid = self.upload(self.client(), a_read())
        rec = fcc._scan(sid)
        self.assertEqual((rec["screening"]["aml"]["sandbox"], rec["screening"]["aml"]["cost"], rec["status"]), (True, 0.0, "open"))
        s["didit"]["aml_sandbox_scenario"] = ""
        with mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(an_aml_answer(scenario_hits=[])).encode())):
            sid = self.upload(self.client(), a_read())
        self.assertEqual(fcc._scan(sid)["status"], "closed")                                 # a live answer with no hit does
        # the case's pages name the list it was screened on, not World-Check
        self.assertEqual(fcc._scan(sid)["closed"]["note"], "No Didit AML record matched the name, and every ID check passed.")
        page = self.client().get(f"/scan/{sid}").data.decode("utf-8")
        panel = page.split('id="scan-screening"')[1].split('id="scan-decisions"')[0]
        self.assertIn("No Didit AML record matches the name.", panel)
        self.assertNotIn("World-Check", panel)
        self.assertIn("No Didit AML record matches the name", self.client().get(f"/scan/{sid}/screening").data.decode("utf-8"))
        self.assertIn("Didit AML hits", self.client().get(f"/wc/{sid}").data.decode("utf-8"))

    def test_didit_watches_the_people_it_screened_and_checks_aadhaar_with_uidai(self):
        s = fcc.SCREEN_SETTINGS
        s["didit"].update(api_key="key", auto=False, aml_monitoring=True)
        s["screening_source"] = "didit_aml"
        who = id_screening.person(a_read())
        self.assertTrue(didit.aml_query(who, "SCAN-1", s["didit"])["include_ongoing_monitoring"])
        # a watched screening: the case says so, the list offers to check every watched person
        sent = []
        with mock.patch.object(didit, "_send", lambda req: sent.append(req) or (200, _json.dumps(an_aml_answer(scenario_hits=[])).encode())):
            sid = self.upload(self.client(), a_read())
        self.assertTrue(_json.loads(sent[0].data)["include_ongoing_monitoring"])
        self.assertTrue(fcc._scan(sid)["screening"]["aml"]["monitoring"])
        c = self.client()
        self.assertIn('id="check-watched"', c.get("/scan").data.decode("utf-8"))
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn('id="aml-monitoring"', page)
        self.assertIn("· watched", page)
        # Didit's re-screens, read back: the newest change first
        history = {"count": 2, "next": None, "results": [
            {"outcome": "NO_CHANGE", "completed_at": "2026-11-20T10:00:00Z", "status": "Approved", "score": 0, "total_hits": 0},
            {"outcome": "CHANGED", "completed_at": "2026-12-01T09:00:00Z", "status": "In Review", "score": 81, "total_hits": 1}]}
        with mock.patch.object(didit, "_send", lambda req: sent.append(req) or (200, _json.dumps(history).encode())):
            c.post(f"/scan/{sid}/aml-history")
        self.assertEqual((sent[-1].full_url, sent[-1].get_method()),
                         ("https://verification.didit.me/v1/session/a1b2c3d4/aml-screening-history/", "GET"))
        hi = fcc._scan(sid)["screening"]["aml"]["history"]
        self.assertEqual((hi["runs"], [r["at"] for r in hi["changes"]], hi["latest"]["outcome"]), (2, ["2026-12-01 09:00:00"], "CHANGED"))
        self.assertIn("1 with a change", c.get(f"/scan/{sid}").data.decode("utf-8"))
        self.assertIn("List change", c.get("/scan").data.decode("utf-8"))
        with mock.patch.object(didit, "_send", lambda req: (200, _json.dumps(history).encode())):
            self.assertIn("a list change for " + sid, c.post("/scans/watched/check", follow_redirects=True).data.decode("utf-8"))
        # stop watching: Didit is asked for the case's vendor_data
        with mock.patch.object(didit, "_send", lambda req: sent.append(req) or (200, b'{"results": [{"vendor_data": "x", "outcome": "disabled"}]}')):
            c.post(f"/scan/{sid}/aml-unwatch")
        self.assertEqual(_json.loads(sent[-1].data), {"is_enabled": False, "vendor_data_list": [sid]})
        self.assertTrue(fcc._scan(sid)["screening"]["aml"]["monitoring_stopped"]["done"])
        self.assertIn("Didit stopped watching this person", c.get(f"/scan/{sid}").data.decode("utf-8"))
        self.assertNotIn('id="check-watched"', c.get("/scan").data.decode("utf-8"))

        # the Aadhaar check: what UIDAI needs, or nothing is sent
        with self.assertRaisesRegex(ValueError, "12-digit"):
            didit.aadhaar_query("ASHISH UPADHYAY", "1962-06-29", "XXXX XXXX 1234", "ABCDE1234F")
        with self.assertRaisesRegex(ValueError, "PAN"):
            didit.aadhaar_query("ASHISH UPADHYAY", "1962-06-29", "1234 5678 9012", "")
        self.assertEqual(didit.aadhaar_query("ASHISH UPADHYAY", "1962-06-29", "1234 5678 9012", "abcde1234f", "SCAN-1"),
                         {"issuing_state": "IND", "services": ["ind_aadhaar"], "full_name": "ASHISH UPADHYAY", "date_of_birth": "1962-06-29",
                          "personal_number": "123456789012", "pan": "ABCDE1234F", "consent": True, "vendor_data": "SCAN-1"})
        card = dict(a_read(), document_type="Aadhaar card")
        card["fields"] = dict(card["fields"], document_number="1234 5678 9012", date_of_expiry="")
        s["screening_source"] = "stand-in"
        sid = self.upload(c, card)
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn('id="aadhaar-form"', page)
        self.assertIn('value="123456789012"', page)
        form = {"full_name": "ASHISH UPADHYAY", "date_of_birth": "1962-06-29", "aadhaar": "123456789012", "pan": "ABCDE1234F"}
        with mock.patch.object(didit, "_send", lambda req: self.fail("sent without consent")):
            self.assertIn("consent", c.post(f"/scan/{sid}/aadhaar", data=form, follow_redirects=True).data.decode("utf-8"))
        answer = {"request_id": "r1", "database_validation": {"status": "Declined", "match_type": "partial_match", "validations": [
            {"service_id": "ind_aadhaar", "validation": {"full_name": "full_match", "date_of_birth": "no_match", "identification_number": "full_match"},
             "outcome_code": "NO_MATCH", "outcome_detail": "The date of birth differs"}],
            "warnings": [{"short_description": "Database validation: no match"}]}}
        with mock.patch.object(didit, "_send", lambda req: sent.append(req) or (200, _json.dumps(answer).encode())):
            c.post(f"/scan/{sid}/aadhaar", data=dict(form, consent="1"))
        self.assertEqual(sent[-1].full_url, "https://verification.didit.me/v3/database-validation/")
        a = fcc._scan(sid)["aadhaar"]
        self.assertEqual((a["status"], a["fields"], a["outcome"], a["number"], a["pan"], a["cost"], a["by"]),
                         ("Declined", [["Name", "Matched"], ["Date of birth", "Not matched"], ["Aadhaar number", "Matched"]],
                          "NO_MATCH", "XXXX XXXX 9012", "XXXXX1234F", 0.42, "amara.iyer@straive.com"))
        self.assertNotIn("123456789012", _json.dumps(a))                                       # kept masked
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn("Not matched", page)
        self.assertIn("The date of birth differs", page)
        # Didit's account switch: kept as the reason, not billed
        with mock.patch.object(didit, "_send", lambda req: (403, b'{"detail":"database validation is disabled until your organization\'s first top-up."}')):
            c.post(f"/scan/{sid}/aadhaar", data=dict(form, consent="1"))
        self.assertIn("first top-up", fcc._scan(sid)["aadhaar"]["error"])
        self.assertEqual(c.get(f"/scan/{sid}/data.json").get_json()["aadhaar_check"]["status"], "error")
        # Settings: the switches and prices are the QC lead's
        qc = self.client("leah.fernandez")
        page = qc.get("/screening/settings").data.decode("utf-8")
        for needle in ('name="dd_aml_monitoring"', 'name="dd_aml_monitoring_price"', 'name="dd_dbv_path"', 'name="dd_aadhaar_price"'):
            self.assertIn(needle, page)

    def test_the_team_and_the_password_are_settings(self):
        before = list(fcc.ANALYSTS)
        self.addCleanup(lambda: (fcc.ANALYSTS.__setitem__(slice(None), before), fcc._rebuild_indexes()))
        qc = self.client("leah.fernandez")
        self.assertIn('id="team-table"', qc.get("/screening/settings").data.decode("utf-8"))
        form = {"team_form": "1", "t_rows": "1", "t_name_0": "Leah Fernandez", "t_email_0": "leah.fernandez@straive.com",
                "t_role_QC_0": "1", "t_name_1": "Priya Shah", "t_email_1": "Priya.Shah@client.example", "t_role_L1_1": "1",
                "new_password": "s3cret-pass", "examples": "6", "name_threshold": "65", "max_hits": "5"}
        qc.post("/screening/settings", data=form)
        s = fcc.SCREEN_SETTINGS
        self.assertEqual([(a["key"], a["email"], a["roles"]) for a in fcc.ANALYSTS],
                         [("leah.fernandez", "leah.fernandez@straive.com", ["QC"]), ("priya.shah", "priya.shah@client.example", ["L1"])])
        self.assertTrue(s["password_hash"])
        self.assertNotIn("s3cret-pass", json.dumps(s))                               # a hash only
        c = fcc.app.test_client()
        self.assertNotIn("Demo password for every profile", c.get("/login").data.decode("utf-8"))
        self.assertEqual(c.post("/login", data={"analyst": "priya.shah", "password": "1234"}).status_code, 401)
        self.assertEqual(c.post("/login", data={"analyst": "amara.iyer", "password": "s3cret-pass"}).status_code, 400)   # not on the team
        self.assertEqual(c.post("/login", data={"analyst": "priya.shah", "password": "s3cret-pass"}).status_code, 302)
        page = qc.post("/screening/settings", data=dict(form, t_role_QC_0="", t_role_L1_0="1", new_password=""),
                       follow_redirects=True).data.decode("utf-8")
        self.assertIn("Keep at least one QC lead", page)
        qc.post("/screening/settings", data=dict(form, new_password="", demo_password="1"))
        self.assertEqual(s["password_hash"], "")
        self.assertEqual(fcc.app.test_client().post("/login", data={"analyst": "priya.shah", "password": "1234"}).status_code, 302)

    def test_reset_deletes_the_cases_only(self):
        c = self.client()
        self.upload(c, a_read())
        fcc.SCREEN_SETTINGS["examples"] = 2
        c.post("/reset")
        self.assertEqual(StateStore.records("scan"), [])
        self.assertEqual(fcc.SCREEN_SETTINGS["examples"], 2)


if __name__ == "__main__":
    unittest.main()
