"""Our own sanctions lists (fincrime/sanctions) and the API in front of them:
the four formats read, a person on several lists one hit, an uploaded ID
screened on them, a list change caught for a watched person (with the signed
webhook), and the API's calls, keys and usage. The downloads are the lists'
real formats in miniature; nothing goes to the network."""
import hashlib
import hmac
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# A database of its own, always: the suite clears the store it opens, and without
# this the screening book would open the console's real fincrime_screening.db.
_DB = os.path.join(tempfile.mkdtemp(prefix="fcc-sanctions-"), "state.db")
os.environ["FCC_STATE_DB"] = _DB
os.environ.setdefault("CONSOLE_CASES", "demo")      # the suite's default; the tests switch to the screening book

from fincrime.data.state_store import StateStore  # noqa: E402
StateStore.path = _DB

import app as fcc  # noqa: E402
assert StateStore.path == _DB, "the suite must never open the console's own database"
from fincrime import id_screening, sanctions  # noqa: E402
from fincrime.documents import id_scan  # noqa: E402

OFAC_SDN = b'''306,"BANCO NACIONAL DE CUBA",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"a.k.a. 'BNC'."
7002,"PUTIN, Vladimir Vladimirovich",individual,"RUSSIA-EO14024",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"DOB 07 Oct 1952; POB Leningrad, Russia; nationality Russia."
8000,"SEA STAR",vessel,"IRAN",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0-
'''
OFAC_ALT = b'''306,12,"aka","NATIONAL BANK OF CUBA",-0-
7002,13,"aka","PUTIN, Vladimir",-0-
'''
UN = '''<?xml version="1.0" encoding="UTF-8"?>
<CONSOLIDATED_LIST dateGenerated="2026-11-13T00:00:03.669Z"><INDIVIDUALS>
 <INDIVIDUAL><DATAID>1</DATAID><FIRST_NAME>AIMAN</FIRST_NAME><SECOND_NAME>MUHAMMED</SECOND_NAME><THIRD_NAME>RABI</THIRD_NAME>
  <FOURTH_NAME>AL-ZAWAHIRI</FOURTH_NAME><UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE><REFERENCE_NUMBER>QDi.006</REFERENCE_NUMBER>
  <LISTED_ON>2001-01-25</LISTED_ON><COMMENTS1>Leader of Al-Qaida.</COMMENTS1><NATIONALITY><VALUE>Egypt</VALUE></NATIONALITY>
  <INDIVIDUAL_ALIAS><QUALITY>Good</QUALITY><ALIAS_NAME>Ayman al-Zawahari</ALIAS_NAME></INDIVIDUAL_ALIAS>
  <INDIVIDUAL_ALIAS><QUALITY>Low</QUALITY><ALIAS_NAME>Abu Mohammed</ALIAS_NAME></INDIVIDUAL_ALIAS>
  <INDIVIDUAL_DATE_OF_BIRTH><TYPE_OF_DATE>EXACT</TYPE_OF_DATE><DATE>1951-06-19</DATE></INDIVIDUAL_DATE_OF_BIRTH>
  <INDIVIDUAL_PLACE_OF_BIRTH><CITY>Giza</CITY><COUNTRY>Egypt</COUNTRY></INDIVIDUAL_PLACE_OF_BIRTH></INDIVIDUAL>
</INDIVIDUALS><ENTITIES>
 <ENTITY><DATAID>2</DATAID><FIRST_NAME>ADF</FIRST_NAME><UN_LIST_TYPE>DRC</UN_LIST_TYPE><REFERENCE_NUMBER>CDe.001</REFERENCE_NUMBER>
  <ENTITY_ALIAS><QUALITY>Good</QUALITY><ALIAS_NAME>Allied Democratic Forces</ALIAS_NAME></ENTITY_ALIAS></ENTITY>
</ENTITIES></CONSOLIDATED_LIST>'''.encode()
UK_HEAD = '''<?xml version="1.0" encoding="utf-8"?><Designations><DateGenerated>12/11/2026</DateGenerated>
 <Designation><UniqueID>AQD0104</UniqueID><UNReferenceNumber>QDi.006</UNReferenceNumber><DateDesignated>25/01/2001</DateDesignated>
  <Names><Name><Name1>Ayman</Name1><Name6>AL-ZAWAHIRI</Name6><NameType>Primary Name</NameType></Name></Names>
  <RegimeName>ISIL (Da'esh) and Al-Qaida</RegimeName><IndividualEntityShip>Individual</IndividualEntityShip><SanctionsImposed>Asset freeze</SanctionsImposed>
  <IndividualDetails><Individual><DOBs><DOB>19/06/1951</DOB></DOBs><Nationalities><Nationality>Egypt</Nationality></Nationalities></Individual></IndividualDetails>
 </Designation>
 <Designation><UniqueID>RUS0251</UniqueID><DateDesignated>25/02/2022</DateDesignated>
  <Names><Name><Name1>Vladimir</Name1><Name2>Vladimirovich</Name2><Name6>PUTIN</Name6><NameType>Primary Name</NameType></Name>
   <Name><Name6>Volodya</Name6><NameType>Alias</NameType><AliasStrength>Low quality a.k.a</AliasStrength></Name></Names>
  <RegimeName>Russia</RegimeName><IndividualEntityShip>Individual</IndividualEntityShip>
  <IndividualDetails><Individual><DOBs><DOB>07/10/1952</DOB></DOBs><Nationalities><Nationality>Russia</Nationality></Nationalities></Individual></IndividualDetails>
 </Designation>
 <Designation><UniqueID>RUS9999</UniqueID><Names><Name><Name6>NORTH WIND</Name6><NameType>Primary Name</NameType></Name></Names>
  <IndividualEntityShip>Ship</IndividualEntityShip></Designation>'''
UK_ADDED = '''
 <Designation><UniqueID>IND0001</UniqueID><DateDesignated>13/11/2026</DateDesignated>
  <Names><Name><Name1>Ashish</Name1><Name6>UPADHYAY</Name6><NameType>Primary Name</NameType></Name></Names>
  <RegimeName>Test regime</RegimeName><IndividualEntityShip>Individual</IndividualEntityShip>
  <IndividualDetails><Individual><DOBs><DOB>29/06/1962</DOB></DOBs><Nationalities><Nationality>India</Nationality></Nationalities></Individual></IndividualDetails>
 </Designation>'''
UK_1 = (UK_HEAD + "</Designations>").encode()
UK_2 = (UK_HEAD + UK_ADDED + "</Designations>").encode()
EU_PUTIN = '''
 <sanctionEntity designationDetails="" unitedNationId="" euReferenceNumber="EU.7510.16" logicalId="1">
  <regulation programme="RUS" entryIntoForceDate="2022-02-25"/><subjectType code="person" classificationCode="P"/>
  <nameAlias wholeName="Влади́мир Влади́мирович ПУ́ТИН" strong="true"/><nameAlias wholeName="Vladimir Vladimirovich PUTIN" strong="true"/>
  <citizenship countryDescription="RUSSIAN FEDERATION"/><birthdate birthdate="1952-10-07" year="1952" circa="false" countryDescription="RUSSIAN FEDERATION"/>
 </sanctionEntity>
 <sanctionEntity euReferenceNumber="EU.9.9" logicalId="3"><subjectType code="enterprise"/><nameAlias wholeName="Example Trading LLC" strong="true"/></sanctionEntity>'''
EU_ASHISH = '''
 <sanctionEntity euReferenceNumber="EU.1.1" logicalId="2"><regulation programme="TEST"/><subjectType code="person"/>
  <nameAlias wholeName="Ashish Kumar UPADHYAYA" strong="true"/><nameAlias wholeName="A K U" strong="false"/>
  <citizenship countryDescription="INDIA"/><birthdate birthdate="1970-01-01" year="1970"/>
 </sanctionEntity>'''


def eu(*parts):
    return ('<?xml version="1.0" encoding="UTF-8"?><export xmlns="http://eu.europa.ec/fpi/fsd/export" '
            'generationDate="2026-10-23T17:05:43.888+02:00">' + "".join(parts) + "</export>").encode()


FILES_1 = {"ofac_url": OFAC_SDN, "ofac_alt_url": OFAC_ALT, "un_url": UN, "uk_url": UK_1, "eu_url": eu(EU_PUTIN, EU_ASHISH)}
FILES_2 = dict(FILES_1, uk_url=UK_2, eu_url=eu(EU_PUTIN))          # the UK lists Ashish Upadhyay; the EU takes its record off


def a_read(name="ASHISH UPADHYAY", surname="UPADHYAY", given="ASHISH", dob="1962-06-29"):
    fields = {k: "" for k, _ in id_scan.FIELDS}
    fields.update(full_name=name, surname=surname, given_names=given, date_of_birth=dob, sex="M", nationality="IND",
                  document_number="S3321051", date_of_expiry="2033-06-02")
    return {"document_type": "Passport", "issuing_country": "India", "readable": True, "problems": [], "fields": fields,
            "mrz": [], "uncertain": [], "note": ""}


class ListFormatTests(unittest.TestCase):

    def test_the_four_formats(self):
        ofac = sanctions.parse_ofac(OFAC_SDN, OFAC_ALT)
        self.assertEqual([(p["uid"], p["type"]) for p in ofac], [("OFAC-306", "entity"), ("OFAC-7002", "person")])  # the vessel left out
        putin = ofac[1]
        self.assertEqual((putin["name"], putin["aka"], putin["dobs"], putin["countries"]),
                         ("Vladimir Vladimirovich PUTIN", ["Vladimir PUTIN"], [{"kind": "full", "date": "1952-10-07"}], ["Russia"]))
        un, published = sanctions.parse_un(UN)
        self.assertEqual((published, un[0]["uid"], un[0]["un_ref"], un[0]["aka"], un[1]["type"]),
                         ("2026-11-13", "UN-QDi.006", "QDI.006", ["Ayman al-Zawahari"], "entity"))         # the low-quality alias left out
        uk, published = sanctions.parse_uk(UK_1)
        self.assertEqual((published, [p["uid"] for p in uk], uk[1]["aka"], uk[1]["dobs"]),
                         ("2026-11-12", ["UK-AQD0104", "UK-RUS0251"], [], [{"kind": "full", "date": "1952-10-07"}]))
        eu_list, published = sanctions.parse_eu(eu(EU_PUTIN, EU_ASHISH))
        self.assertEqual((published, [p["uid"] for p in eu_list], eu_list[2]["aka"]), ("2026-10-23", ["EU-EU.7510.16", "EU-EU.9.9", "EU-EU.1.1"], []))
        self.assertEqual([sanctions._dob(t) for t in ("10 Dec 1948", "dd/mm/1968", "1948 to 1950", "circa 1960", "")],
                         [{"kind": "full", "date": "1948-12-10"}, {"kind": "year", "year": 1968},
                          {"kind": "range", "year": 1948, "year_to": 1950}, {"kind": "year", "year": 1960}, None])
        self.assertEqual({sanctions.country_key(c) for c in ("Russian Federation", "RUS", "russian")}, {"RUSSIA"})
        self.assertEqual(sanctions.country_key("KOREA (DEMOCRATIC PEOPLE'S REPUBLIC OF)"), "NORTH KOREA")


class SanctionsListsTests(unittest.TestCase):

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
        for kind in ("scan", "api_aml", "api_event"):
            StateStore.delete(kind, [r["id"] for r in StateStore.records(kind)])
        fcc.SCREEN_SETTINGS.clear()
        fcc.SCREEN_SETTINGS.update(id_screening.default_settings(), auto_verify=False)
        self.dir_before, sanctions.DIR = sanctions.DIR, tempfile.mkdtemp()
        sanctions._cache.clear()
        fcc.LISTS_JOB.update(running=False, last=None)
        self.files, self.posted = FILES_1, []

    def tearDown(self):
        shutil.rmtree(sanctions.DIR, ignore_errors=True)
        sanctions.DIR = self.dir_before
        sanctions._cache.clear()

    def get(self, url, timeout):
        return self.files[next(k for k, v in sanctions.DEFAULTS.items() if v == url)]

    def download(self, c, files):
        self.files = files
        with mock.patch.object(sanctions, "_get", self.get), mock.patch.object(fcc, "_webhook_post", self.post):
            return c.post("/screening/lists/update", follow_redirects=True).data.decode("utf-8")

    def post(self, url, body, headers):
        self.posted.append((url, body, headers))
        return 200

    def client(self, who="amara.iyer"):
        c = fcc.app.test_client()
        c.post("/login", data={"analyst": who, "password": "1234"})
        return c

    def decide(self, case_id, who, hit, sop, settings):
        return {"status": "done", "outcome": "clear", "label": "Clear (false positive)", "suggested": "False positive",
                "confidence": 80, "reasons": ["Different date of birth"], "dob_finding": "", "request": "", "examples": [],
                "name_variance": "", "address_variance": "", "model": "m", "model_label": "Model", "sop": sop["version"],
                "seconds": 1.0, "cost": 0.0}

    def upload(self, c, read):
        from PIL import Image
        png = io.BytesIO()
        Image.new("RGB", (900, 600), "white").save(png, "PNG")
        result = {"read": read, "model": {"model": "m", "label": "Model", "tokens_in": 1, "tokens_out": 1, "cost": 0.0, "seconds": 1.0},
                  "checks": id_scan.checks(read), "error": ""}
        with mock.patch.object(id_scan, "scan", lambda jpeg, *a, **k: dict(result)), mock.patch.object(id_screening, "decide", self.decide), \
                mock.patch.object(fcc, "_webhook_post", self.post):
            r = c.post("/scan", data={"image": (io.BytesIO(png.getvalue()), "id.png")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        return r.headers["Location"].rsplit("/", 1)[-1]

    def api_key(self):
        qc = self.client("leah.fernandez")
        qc.post("/screening/settings/intake-keys", data={"name": "Onboarding app"})
        page = qc.get("/screening/settings").data.decode("utf-8")
        return page.split('id="intake-new-key"')[1].split("<code>")[1].split("</code>")[0]

    def test_a_person_on_several_lists_is_one_hit(self):
        c = self.client()
        self.assertIn("not downloaded yet", c.get("/screening/lists").data.decode("utf-8"))
        self.assertFalse(sanctions.ready(fcc.SCREEN_SETTINGS["sanctions"]))
        page = self.download(c, FILES_1)
        self.assertIn('id="lists-last"', page)
        self.assertEqual({l["key"]: (l["people"], l["entities"]) for l in sanctions.lists(fcc.SCREEN_SETTINGS["sanctions"])},
                         {"ofac": (1, 1), "un": (1, 1), "uk": (2, 0), "eu": (2, 1)})
        cfg = fcc.SCREEN_SETTINGS["sanctions"]
        hits = sanctions.search({"name": "Vladimir Putin", "dob": "1952-10-07", "nationality": "RUS"}, cfg)
        self.assertEqual((hits[0]["uid"], hits[0]["lists"], hits[0]["list_ids"], hits[0]["dob_result"], hits[0]["country_result"]),
                         ("OFAC-7002", ["UK", "EU", "OFAC"], ["EU-EU.7510.16", "OFAC-7002", "UK-RUS0251"], "Matched", "Matched"))   # its alias "Vladimir PUTIN" scores 100
        z = sanctions.search({"name": "Ayman al Zawahiri"}, cfg)[0]                              # the UN reference the UK carries
        self.assertEqual((z["lists"], z["list_ids"], z["score"]), (["UN", "UK"], ["UK-AQD0104", "UN-QDi.006"], 100))
        self.assertEqual(sanctions.search({"name": "Banco Nacional de Cuba"}, cfg, kind="entity")[0]["uid"], "OFAC-306")
        self.assertEqual(sanctions.search({"name": "Banco Nacional de Cuba"}, cfg), [])           # not a person
        self.assertEqual(sanctions.search({"name": "A K U"}, cfg), [])                            # initials alone screen nobody
        page = c.get("/screening/lists?name=Vladimir+Putin").data.decode("utf-8")
        self.assertIn('id="lists-found"', page)
        self.assertIn("OFAC-7002", page)
        self.assertIn('id="lists-none"', c.get("/screening/lists?name=Nobody+Atall").data.decode("utf-8"))
        # the same files again: nothing changes, nothing is written
        self.download(c, FILES_1)
        self.assertFalse(any(r["changed"] for r in fcc.LISTS_JOB["last"]["result"].values()))
        # a list that cannot be fetched keeps the old download and says why
        with mock.patch.object(sanctions, "_get", mock.Mock(side_effect=sanctions.ListError("the publisher answered 503"))):
            page = c.post("/screening/lists/update", follow_redirects=True).data.decode("utf-8")
        self.assertIn("the publisher answered 503", page)
        self.assertTrue(sanctions.ready(cfg))

    def test_an_uploaded_id_screened_on_the_lists_and_watched(self):
        c = self.client()
        fcc.SCREEN_SETTINGS.update(screening_source="own_lists", webhook_url="https://client.example/hook", webhook_secret="whsec_test")
        self.assertEqual(id_screening.source(fcc.SCREEN_SETTINGS), "stand-in")                    # not downloaded: the stand-in
        self.download(c, FILES_1)
        self.assertEqual(id_screening.source(fcc.SCREEN_SETTINGS), "own_lists")
        self.assertIn("Our sanctions lists: OFAC, UN, UK, EU", id_screening.source_label(fcc.SCREEN_SETTINGS))
        sid = self.upload(c, a_read())
        sc = fcc._scan(sid)["screening"]
        self.assertEqual((sc["source"], [h["uid"] for h in sc["hits"]], sc["hits"][0]["dob_result"], sc["hits"][0]["country_result"]),
                         ("Sanctions lists", ["EU-EU.1.1"], "Not matched", "Matched"))
        self.assertEqual((sc["lists"]["monitoring"], sc["lists"]["known"], sorted(sc["lists"]["versions"])),
                         (True, ["EU-EU.1.1"], ["eu", "ofac", "uk", "un"]))
        self.assertIn("Sanctions list record (EU) EU-EU.1.1", id_screening.facts(sc["person"], sc["hits"][0]))
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        for needle in ('id="lists-line"', 'id="lists-monitoring"', "Open in console", "Not screened again yet"):
            self.assertIn(needle, page)
        self.assertIn("sanctions-list hits", c.get(f"/wc/{sid}").data.decode("utf-8"))           # the console, simulated
        self.assertIn("· watched", c.get("/scan").data.decode("utf-8"))
        # the lists change: the UK lists him, the EU takes its record off; he is screened again and the change kept
        page = self.download(c, FILES_2)
        self.assertIn("a change for " + sid, page)
        ch = fcc._scan(sid)["screening"]["lists"]["history"]
        self.assertEqual((ch["runs"], [a["uid"] for a in ch["changes"][0]["added"]], ch["changes"][0]["delisted"]),
                         (1, ["UK-IND0001"], ["EU-EU.1.1"]))
        self.assertEqual(fcc._scan(sid)["screening"]["lists"]["known"], ["UK-IND0001"])
        page = c.get(f"/scan/{sid}").data.decode("utf-8")
        self.assertIn("1 with a change", page)
        self.assertIn("taken off the lists: EU-EU.1.1", page)
        self.assertIn("List change", c.get("/scan").data.decode("utf-8"))
        # the webhook: told, and signed
        url, body, headers = next(p for p in self.posted if p[2]["X-Webhook-Event"] == "aml.list_change")
        expected = "sha256=" + hmac.new(b"whsec_test", headers["X-Webhook-Timestamp"].encode() + b"." + body, hashlib.sha256).hexdigest()
        self.assertEqual((url, headers["X-Webhook-Signature"]), ("https://client.example/hook", expected))
        self.assertEqual(json.loads(body)["data"]["change"]["added"][0]["uid"], "UK-IND0001")
        self.assertTrue(StateStore.records("api_event")[0]["ok"])
        # screened again by hand: nothing new; then no longer watched
        with mock.patch.object(fcc, "_webhook_post", self.post):
            self.assertIn("nothing changed", c.post(f"/scan/{sid}/lists-rescreen", follow_redirects=True).data.decode("utf-8"))
            c.post(f"/scan/{sid}/lists-unwatch")
        self.assertIn("No longer watched", c.get(f"/scan/{sid}").data.decode("utf-8"))
        self.assertFalse(fcc._lists_watched(fcc._scan(sid)))
        # a case closed is sent too
        sid2 = self.upload(c, a_read("ZORAN QUILLFEATHER", "QUILLFEATHER", "ZORAN", "1990-01-01"))
        self.assertEqual(fcc._scan(sid2)["screening"]["hits"], [])
        with mock.patch.object(fcc, "_webhook_post", self.post):
            c.post(f"/scan/{sid2}/close", data={"note": "no match"})
        closed = json.loads(next(p[1] for p in self.posted if p[2]["X-Webhook-Event"] == "case.closed"))["data"]
        self.assertEqual((closed["scan_id"], closed["status"]), (sid2, "closed"))
        self.assertEqual(c.get(f"/scan/{sid}/data.json").get_json()["screening"]["sanctions_lists"]["known"], ["UK-IND0001"])

    def test_our_api(self):
        key = self.api_key()
        api = fcc.app.test_client()
        h = {"X-API-Key": key}
        self.assertEqual(api.post("/api/v1/aml", headers=h, json={"full_name": "Vladimir Putin"}).status_code, 503)  # no list yet
        self.download(self.client(), FILES_1)
        fcc.SCREEN_SETTINGS.update(api_price_aml=0.1, api_price_watch=0.5)
        self.assertEqual(api.post("/api/v1/aml", json={"full_name": "Vladimir Putin"}).status_code, 401)
        self.assertEqual(api.post("/api/v1/aml", headers=h, json={}).status_code, 400)
        self.assertEqual(api.post("/api/v1/aml", headers=h, json={"full_name": "X", "entity_type": "ship"}).status_code, 400)
        self.assertEqual(api.post("/api/v1/aml", headers=h, json={"full_name": "X", "date_of_birth": "7 Oct"}).status_code, 400)
        r = api.post("/api/v1/aml", headers=h, json={"full_name": "Vladimir Putin", "date_of_birth": "1952-10-07", "nationality": "Russia",
                                                     "reference": "CUST-9", "monitoring": False})
        self.assertEqual(r.status_code, 201, r.data)
        b = r.get_json()
        self.assertEqual((b["status"], b["total_hits"] >= 1, b["hits"][0]["lists"], b["hits"][0]["dob_result"], b["monitoring"], b["reference"]),
                         ("In Review", True, ["UK", "EU", "OFAC"], "Matched", False, "CUST-9"))
        self.assertTrue(r.headers["Location"].endswith("/api/v1/aml/" + b["request_id"]))
        company = api.post("/api/v1/aml", headers=h, json={"full_name": "Banco Nacional de Cuba", "entity_type": "company"}).get_json()
        self.assertEqual(company["hits"][0]["uid"], "OFAC-306")
        self.assertEqual(api.post("/api/v1/aml", headers=h, json={"full_name": "Zoran Quillfeather"}).get_json()["status"], "Approved")
        watched = api.post("/api/v1/aml", headers=h, json={"full_name": "Ashish Upadhyay", "date_of_birth": "1962-06-29", "monitoring": True}).get_json()
        self.assertEqual([x["uid"] for x in watched["hits"]], ["EU-EU.1.1"])
        self.assertEqual(api.get(f"/api/v1/aml/{b['request_id']}", headers=h).get_json()["query"]["full_name"], "Vladimir Putin")
        self.assertEqual(api.get("/api/v1/aml/AML-none", headers=h).status_code, 404)
        # a list change: the watched name is screened again; the history says what changed
        self.download(self.client(), FILES_2)
        hist = api.get(f"/api/v1/aml/{watched['request_id']}/history", headers=h).get_json()
        self.assertEqual((hist["count"], hist["results"][0]["added"][0]["uid"], hist["results"][0]["delisted"]), (1, "UK-IND0001", ["EU-EU.1.1"]))
        self.assertEqual(api.get(f"/api/v1/aml/{b['request_id']}/history", headers=h).get_json()["count"], 0)   # not watched
        self.assertFalse(api.delete(f"/api/v1/aml/{watched['request_id']}/monitoring", headers=h).get_json()["monitoring"])
        self.assertFalse(api.get(f"/api/v1/aml/{watched['request_id']}", headers=h).get_json()["monitoring"])
        lists = api.get("/api/v1/lists", headers=h).get_json()["lists"]
        self.assertEqual([(l["key"], l["downloaded"]) for l in lists], [("ofac", True), ("un", True), ("uk", True), ("eu", True)])
        use = api.get("/api/v1/usage", headers=h).get_json()
        self.assertEqual((use["calls"], use["amount"], use["key"]), ({"aml": 4}, 0.4, "Onboarding app"))
        self.assertEqual(api.get("/api/v1/usage?month=11-2026", headers=h).status_code, 400)
        # another client's key does not see these screenings
        other = self.api_key()
        self.assertEqual(api.get(f"/api/v1/aml/{b['request_id']}", headers={"X-API-Key": other}).status_code, 404)
        page = self.client().get("/screening/lists").data.decode("utf-8")
        for needle in ('id="api-docs"', 'id="api-usage"', "Onboarding app", "$0.40", "Vladimir Putin", 'id="api-events"'):
            self.assertIn(needle, page)

    def test_the_lists_and_the_api_are_settings(self):
        qc, analyst = self.client("leah.fernandez"), self.client()
        page = analyst.get("/screening/settings").data.decode("utf-8")
        for needle in ('id="settings-lists"', 'id="settings-api"', 'name="sl_use_ofac"', 'name="webhook_url"', "(not downloaded yet)"):
            self.assertIn(needle, page)
        analyst.post("/screening/settings", data={"lists_form": "1", "sl_update_hours": "6"})
        self.assertEqual(fcc.SCREEN_SETTINGS["sanctions"]["update_hours"], 24)                    # only the QC lead
        self.assertIn("1 to 720", qc.post("/screening/settings", data={"lists_form": "1", "sl_use_un": "1", "sl_update_hours": "0"},
                                          follow_redirects=True).data.decode("utf-8"))
        self.assertIn("at least one", qc.post("/screening/settings", data={"lists_form": "1", "sl_update_hours": "6"},
                                              follow_redirects=True).data.decode("utf-8"))
        self.assertIn("https://", qc.post("/screening/settings", data={"api_form": "1", "webhook_url": "ftp://x"},
                                          follow_redirects=True).data.decode("utf-8"))
        qc.post("/screening/settings", data={"lists_form": "1", "sl_use_un": "1", "sl_use_uk": "1", "sl_update_hours": "6",
                                             "sl_monitoring": "1", "api_form": "1", "api_price_aml": "0.15",
                                             "webhook_url": "https://client.example/hook"})
        cfg = fcc.SCREEN_SETTINGS["sanctions"]
        self.assertEqual((sanctions.enabled(cfg), cfg["update_hours"], cfg["auto_update"], cfg["monitoring"]), (["un", "uk"], 6, False, True))
        self.assertEqual((fcc.SCREEN_SETTINGS["api_price_aml"], fcc.SCREEN_SETTINGS["webhook_url"]), (0.15, "https://client.example/hook"))
        secret = fcc.SCREEN_SETTINGS["webhook_secret"]
        self.assertTrue(secret.startswith("whsec_"))
        page = qc.get("/screening/settings").data.decode("utf-8")
        self.assertIn('id="webhook-new-secret"', page)
        self.assertIn(secret, page)
        self.assertNotIn(secret, qc.get("/screening/settings").data.decode("utf-8"))              # shown once
        with mock.patch.object(fcc, "_webhook_post", lambda url, body, headers: 204):
            self.assertIn("answered 204", qc.post("/screening/settings/webhook-test", follow_redirects=True).data.decode("utf-8"))
        with mock.patch.object(fcc, "_webhook_post", mock.Mock(side_effect=OSError("refused"))):
            self.assertIn("not delivered", qc.post("/screening/settings/webhook-test", follow_redirects=True).data.decode("utf-8"))
        self.assertIn("Lists and API", analyst.get("/scan").data.decode("utf-8"))                 # in the menu


if __name__ == "__main__":
    unittest.main()
