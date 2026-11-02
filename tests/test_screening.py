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
from fincrime.adapters import world_check  # noqa: E402
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

    def test_the_examples_are_the_analysts_own_outcomes(self):
        hit = self.hit()
        text, used = id_screening.prompt("SCAN-1", WHO, hit, 6)
        self.assertEqual(used, [])                               # nothing resolved yet: the SOP alone, no sample case
        self.assertNotIn("Example", text)
        other = dict(WHO, name="ASHISH KUMAR UPADHYAY")
        done = [{"id": "SCAN-1", "screening": {"person": WHO, "hits": [dict(hit, resolution={"status": "True match", "note": "mine"})]}},
                {"id": "SCAN-2", "screening": {"person": other, "hits": [dict(hit, resolution={"status": "False positive", "reason": "Date of Birth mismatch", "note": "older man"})]}},
                {"id": "SCAN-3", "screening": {"person": other, "hits": [dict(hit)]}}]          # no outcome yet: not an example
        library = id_screening.resolved(done)
        self.assertEqual([x["case"] for x in library], ["SCAN-1", "SCAN-2"])
        text, used = id_screening.prompt("SCAN-1", WHO, hit, 6, library)
        self.assertEqual(used, [f"SCAN-2:{hit['uid']}"])               # never the case's own
        examples, case = text.split("### The case to decide")
        self.assertIn("The analyst's outcome: False positive", examples)
        self.assertIn("reason: Date of Birth mismatch", examples)
        self.assertIn("World-Check record WC-675768", case)
        self.assertNotIn("outcome", case)                        # the answer is only on the examples
        self.assertNotIn("SOP", text)                            # the SOP is the system prompt, not the case
        self.assertEqual(id_screening.prompt("SCAN-9", WHO, hit, 0, library)[1], [])

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
            hits, source, error, _ = id_screening.search(WHO, {"world_check": self.cfg, "max_hits": 5, "name_threshold": 75})
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
        fcc.SCREEN_SETTINGS.update(id_screening.default_settings())
        self.calls, self.libraries = [], []

    def client(self, who="amara.iyer"):
        c = fcc.app.test_client()
        c.post("/login", data={"analyst": who, "password": "1234"})
        return c

    def png(self, colour="white"):
        from PIL import Image
        out = io.BytesIO()
        Image.new("RGB", (900, 600), colour).save(out, "PNG")
        return out.getvalue()

    def decide(self, case_id, who, hit, sop, settings, library=()):
        self.calls.append((case_id, hit["uid"], sop["version"]))
        self.libraries.append([x["case"] for x in library])
        return {"status": "done", "outcome": "clear", "label": "Clear (false positive)", "suggested": "False positive",
                "confidence": 80, "reasons": ["Different date of birth"], "dob_finding": "", "request": "", "examples": ["KYC-1"],
                "name_variance": "", "address_variance": "", "model": "m", "model_label": "Model", "sop": sop["version"],
                "seconds": 1.0, "cost": 0.01}

    def upload(self, c, read, colour="white"):
        result = {"read": read, "model": {"model": "m", "label": "Model", "tokens_in": 1, "tokens_out": 1, "cost": 0.0, "seconds": 1.0},
                  "checks": id_scan.checks(read), "error": ""}
        with mock.patch.object(id_scan, "scan", lambda jpeg, model_id=None: dict(result)), \
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
        first = sid
        sid = self.upload(c, a_read(), "ivory")                      # the AI says false positive; the analyst does not
        self.assertEqual(self.libraries[-1], [first])                # it learnt from the first case's outcome
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

    def test_reset_deletes_the_cases_only(self):
        c = self.client()
        self.upload(c, a_read())
        fcc.SCREEN_SETTINGS["examples"] = 2
        c.post("/reset")
        self.assertEqual(StateStore.records("scan"), [])
        self.assertEqual(fcc.SCREEN_SETTINGS["examples"], 2)


if __name__ == "__main__":
    unittest.main()
