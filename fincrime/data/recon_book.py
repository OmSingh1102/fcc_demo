"""The console's case book from the reconciliation log.

The 1,000 rows of fincrime/hub/data/kyc_wc_recon_log.csv (the file the user
uploaded; every person and company in it is fictional) become the console's
open onboarding cases: each row is one KYC case at L1 Data Confirming with
its one World-Check record, a screening case and a watchlist case, built by
the same seed builders as the scripted scenarios. The AI screening rules run
at intake exactly as they do for those (seed.pair_screening).

Parsing is the hub's (fincrime/hub/loader.py, parse.py: Flask-free, no state)
and so are the document images (fincrime/hub/documents.py): a case shows the
same passport, secondary ID and proof of address, with the same planted
capture defect, in both UIs. The file has no images; the hub's defect plan
is synthetic and the case page says so.

What an analyst recorded for the row (disposition, notes, variance types,
handling time) rides along as case["recon"]. Nothing in the console's logic
reads it: it is shown on the case page, and the AI Screening page measures
the rules against it.
"""
import hashlib
import re
from datetime import date, timedelta

from fincrime.data import vocab
from fincrime.data.seed import AMARA, JON, MARIO, agency_info, kyc_case, pair_screening, wc_match
from fincrime.hub import documents as hub_documents
from fincrime.hub import loader as hub_loader
from fincrime.hub import names as hub_names
from fincrime.utils import dates

KEY_PREFIX = "recon-"

# Analyst-facing words for the hub's synthetic capture defects: the console's
# document quality badge and what the ID-verification vendor said.
QUALITY = {"flat_scan": "scan", "partial": "cropped", "blur": "blurred", "glare": "glare", "expired": "expired"}
VENDOR_REASON = {
    "flat_scan": "The image is a flat scan or PDF of the document, not a camera photo.",
    "partial": "Document edges not visible.",
    "blur": "The image is too blurred to read the data page.",
    "glare": "Glare covers part of the data page.",
    "expired": "The passport has expired.",
    "tampered": "Security-feature check failed: the date-of-birth check digit in the MRZ does not match.",
}

# Proof-of-address kinds: the hub's parse.poa_type → the console's library
# (vocab.ACCEPTED_POA_TYPES); and the country an overseas POA was issued in.
POA_KIND = {"utility_bill": "utility_bill", "bank_statement": "bank_statement", "lease": "tenancy_agreement",
            "aadhaar": "aadhaar", "residence_confirmation": "residence_confirmation", "military_orders": "military_orders"}
POA_COUNTRY = (("Dubai", "AE"), ("Abu Dhabi", "AE"), ("Canada", "CA"), ("Qatar", "QA"), ("Oman", "OM"),
               ("Singapore", "SG"), ("Australia", "AU"))
SECONDARY = {"national_id": ("national_id", "NationalID"), "driving_licence": ("driving_licence", "DrivingLicense"),
             "certificate": ("national_id", "Certificate")}

# A company's registration document, from its name's suffix and its country.
LEGAL_FORM = (("Pvt Ltd", "Private Limited Company"), ("LLP", "Limited Liability Partnership"),
              ("LLC", "Limited Liability Company"), ("Inc", "Corporation"), ("JSC", "Joint Stock Company"),
              ("Co., Ltd", "Limited Liability Company"))
ACTIVITY = (("Agro Exports", "Export of agricultural produce"), ("Home Health", "Home health care services"),
            ("Construction", "Construction and civil works"), ("Logistics", "Freight forwarding and logistics"),
            ("Textiles", "Manufacture and trade of textiles"), ("Capital Partners", "Investment advisory and private capital"),
            ("Pharma Distributors", "Wholesale distribution of pharmaceuticals"),
            ("Infra Projects", "Infrastructure project contracting"),
            ("Precision Components", "Manufacture of precision engineering components"),
            ("Gems & Jewellery", "Trade in gems and jewellery"), ("Seafood", "Seafood processing and export"),
            ("Garment", "Garment manufacturing"), ("Import Export", "Import and export trading"),
            ("Imports", "Import and wholesale trade"), ("Auto Parts", "Wholesale of auto parts"),
            ("Trading", "General trading"))
IN_STATES = (("Tamil Nadu", "TN"), ("West Bengal", "WB"), ("Kolkata", "WB"), ("Maharashtra", "MH"), ("Gujarat", "GJ"),
             ("Uttar Pradesh", "UP"), ("Karnataka", "KA"), ("Kerala", "KL"), ("Andhra Pradesh", "AP"), ("Telangana", "TG"),
             ("Madhya Pradesh", "MP"), ("Delhi", "DL"))

# Showcase cases routed at intake, below capacity so "Request cases" still
# has room (checked by tests/test_console_book.py):
#   Amara  3011 AI-cleared, auto-verifies on confirm · 3012 exact DOB, swapped name fields, a true match
#          3146 garbled (mojibake) CRM name, AI-cleared
#   Jon    3046 day/month-transposed DOB, held · 3029 a company (KYB) · 3037 proof of address 223 days old
#   Mario  3118 flat scan, resubmit the ID · 3043 year-only DOB, held · 3040 passport fails its MRZ check digit
STARTERS = {
    "KYC-2026-3011": AMARA, "KYC-2026-3012": AMARA, "KYC-2026-3146": AMARA,
    "KYC-2026-3046": JON, "KYC-2026-3029": JON, "KYC-2026-3037": JON,
    "KYC-2026-3118": MARIO, "KYC-2026-3043": MARIO, "KYC-2026-3040": MARIO,
}

# The hub-shaped view of each case (build_case + synthesise), kept for the
# document images; rebuilt by every build().
VIEWS = {}


def _h(seed, case_id):
    return int(hashlib.sha256(f"{seed}:{case_id}".encode("utf-8")).hexdigest(), 16)


# ── documents ────────────────────────────────────────────────────────────────

def _poa_country(poa, home):
    for word, code in POA_COUNTRY:
        if word in poa["type"]:
            return code
    tail = poa["address"].rsplit(",", 1)[-1].strip().upper()
    if tail in ("USA", "U.S.A.", "UNITED STATES"):
        return "US"
    return home


def _docs(v, company):
    s, d = v["synth"], v["documents"]
    defect = QUALITY.get(s["capture"], "ok")
    sec, poa = d["secondary"], d["poa"]
    sec_kind, sec_category = SECONDARY.get(sec["kind"], ("national_id", "NationalID"))
    out = []
    if company:
        out.append({"name": company["document_title"].capitalize(), "category": "TradeLicense", "kind": "trade_licence",
                    "side": "page 1", "quality": "ok"})
    out += [
        {"name": "Passport", "category": "Passport", "kind": "passport", "side": "front", "quality": defect,
         "hub_file": "passport"},
        {"name": "Passport", "category": "Passport", "kind": "passport", "side": "back", "quality": "ok",
         "hub_file": "passport-back"},
        {"name": sec["type"], "category": sec_category, "kind": sec_kind, "side": "front", "quality": "ok",
         "hub_file": "secondary"},
        {"name": f"Proof of address — {poa['type']}", "category": "ProofOfAddress", "kind": POA_KIND[poa["kind"]],
         "side": "page 1", "quality": "ok", "hub_file": "poa", "issued_days_ago": s["poa_age_days"],
         "country": _poa_country(poa, v["country"])},
    ]
    return out


def view(case_id):
    """The hub-shaped record the document images are drawn from, with the
    canonical name the hub's identity agent would give the proof of address
    (worked out on first use: names.analyse is the costly step)."""
    v = VIEWS.get(case_id)
    if v is None:
        return None
    if not v["identity"]:
        pp = v["documents"]["passport"]
        v["identity"] = {"name": hub_names.analyse(v["country"], v["customer"]["name"], pp["viz"], pp["mrz"],
                                                   v["documents"]["secondary"]["name"], v["customer"]["corporate"],
                                                   v["customer"]["ubo"])}
    return v


def render(case, doc):
    """The SVG for a console document of a file-backed case, or None."""
    v = view((case.get("recon") or {}).get("id", ""))
    return hub_documents.render(v, doc["hub_file"]) if v and doc.get("hub_file") else None


# ── the company (KYB) ───────────────────────────────────────────────────────

def _company(v):
    name, country, cid = v["customer"]["name"], v["country"], v["id"]
    h = _h("recon-reg", cid)
    form = next((f for suffix, f in LEGAL_FORM if name.endswith(suffix)), "Company")
    activity = next((a for word, a in ACTIVITY if word in name), "General business")
    year = 2008 + h % 16
    if country == "US":
        state = (re.search(r",\s*([A-Z]{2})\s+\d{5}", v["customer"]["address"]) or [None, ""])[1]
        number = f"{h % 90 + 10}-{(h >> 8) % 10 ** 7:07d}"
        title = "CERTIFICATE OF FORMATION" if form == "Limited Liability Company" else "CERTIFICATE OF INCORPORATION"
        authority = f"SECRETARY OF STATE{' - ' + state if state else ''} (DEMO)"
    elif country == "IN":
        state = next((code for word, code in IN_STATES if word in v["customer"]["address"]), "MH")
        if form == "Limited Liability Partnership":
            number = f"AA{chr(65 + h % 26)}-{(h >> 8) % 10 ** 4:04d}"
            title = "CERTIFICATE OF REGISTRATION"
        else:
            number = f"U{(h >> 8) % 10 ** 5:05d}{state}{year}PTC{(h >> 32) % 10 ** 6:06d}"
            title = "CERTIFICATE OF INCORPORATION"
        authority = "MINISTRY OF CORPORATE AFFAIRS - REGISTRAR OF COMPANIES (DEMO)"
    else:
        number = f"0{(h >> 8) % 10 ** 9:09d}"
        title = "ENTERPRISE REGISTRATION CERTIFICATE"
        authority = "DEPARTMENT OF PLANNING AND INVESTMENT (DEMO)"
    return {"registration_number": number, "legal_form": form, "activity": activity, "document_title": title,
            "authority": authority}


# ── the World-Check record ──────────────────────────────────────────────────

def _category(w):
    """(types, category, sub_category, pep_status, special_interest, position)
    from the file's category text, e.g. 'PEP - Level 2 (State Legislator)'."""
    group, text = w["group"], w["category"]
    head, _, tail = text.partition(" - ")
    paren = re.search(r"\(([^()]*)\)", text)
    inner = paren.group(1) if paren else ""
    if group == "PEP":
        rca = "Relative" in text
        return (("RCA",) if rca else ("PEP",)), "PEP", tail, ("RCA" if rca else tail.split(" (")[0]), [], inner
    if group == "Adverse Media":
        return ("SIC",), "ADVERSE MEDIA", tail, "", [tail], ""
    code = {"Law Enforcement": "LE", "Regulatory Enforcement": "RE", "Sanctions": "SAN"}.get(group, "SIC")
    return (code,), group.upper(), inner or tail, "", [], ""


def _dobs(dob):
    """The record's date of birth the way the rules and the console read it:
    a full date, a bare year, a range (which the rules cannot read, so it
    stays with an analyst) or nothing."""
    if dob["kind"] == "full":
        return [dob["date"]]
    if dob["kind"] == "year":
        return [str(dob["year"])]
    if dob["kind"] == "range":
        return [f"{dob['year']}–{dob['year_to']}"]
    return []


def _match(v, key):
    w = v["wc"]
    types, category, sub, pep, special, position = _category(w)
    loc = w["location"]
    country = loc["country"] or v["country_name"]
    h = _h("recon-wc", v["id"])
    entered = date(2012, 1, 1) + timedelta(days=h % 4000)
    updated = min(entered + timedelta(days=30 + (h >> 16) % 1500), date(2026, 9, 30))
    name = w["surname"] if (w["mononym"] or not w["given"]) else f"{w['surname']}, {w['given']}"
    return wc_match(
        key=f"{key}-1", wc_id=w["uid"], name=name, strength=w["score"] / 100, types=types, gender="",
        dobs=_dobs(w["dob"]),
        citizenship=v["country_name"] if "Nationality" in w["matched_attributes"] else country, country=country,
        category=category, sub_category=sub, pep_status=pep, special_interest=special, position=position,
        location={"street": "", "city": loc["city"], "region": loc["region"], "country": country, "postcode": ""},
        bio=w["narrative"], aliases=w["aka"], entered=entered.isoformat(), updated=updated.isoformat(),
    )


# ── one row → three records ─────────────────────────────────────────────────

def _recorded(v):
    """What the file says an analyst did with the row: for comparison only."""
    hist, w = v["history"], v["wc"]
    return {"id": v["id"], "wc_uid": w["uid"], "disposition": hist["disposition"], "outcome": hist["outcome"],
            "action": hist["action"], "corrected": hist["corrected"], "analyst": hist["analyst"],
            "review_date": hist["review_date"], "notes": hist["notes"], "discrepancy": hist["discrepancy"],
            "matched_attributes": w["matched_attributes"], "category": w["category"], "wc_dob": w["dob"]["raw"],
            "jurisdiction": w["location"]["raw"], "name_variance": hist["name_variance"],
            "address_variance": hist["address_variance"], "pain_point": hist["pain_point"],
            "resolution": hist["resolution"], "impact": hist["impact"], "score": w["score"],
            "score_after": hist["score_after"], "minutes": hist["minutes"]}


def case_records(v, routed_to=""):
    """(kyc, alert, wc) for one hub-shaped view."""
    key = KEY_PREFIX + v["id"].rsplit("-", 1)[-1]
    cust, s, pp = v["customer"], v["synth"], v["documents"]["passport"]
    nat = v["country"]
    received = dates.parse(s["received_at"]) or dates.BOOT
    hours = max(0.25, (dates.BOOT - received).total_seconds() / 3600)
    defect = s["capture"] if s["capture"] != "none" else ("tampered" if s["tampered"] else "")
    company = _company(v) if cust["corporate"] else None
    common = dict(
        key=key, case_id=v["id"], nationality=nat, issuing=nat, status="DataConfirming", us_person=nat == "US",
        tags=["Priority Review"] if cust["risk"] == "High" else [], poa_required=True,
        manual_review_reason=["Namescreen hit - WC or CMS"] + (["Vendor rejected"] if defect else []),
        created_hours_ago=hours, vendor=vocab.VENDORS[_h("recon-vendor", v["id"]) % len(vocab.VENDORS)],
        vendor_result="Declined" if defect else "Approved", vendor_reason=VENDOR_REASON.get(defect, ""),
        docs=_docs(v, company), address=cust["address"], country=v["country_name"], screening_hit=True,
        risk_rating=cust["risk"], routed_to=routed_to,
    )
    if company:
        kyc = kyc_case(name=cust["name"], dob="", tenant="ttshop", id_type="TradeLicense", gender="",
                       id_number=company["registration_number"],
                       agency=dict(agency_info(company=cust["name"], registration_number=company["registration_number"],
                                               incorporation_country=v["country_name"], address=cust["address"],
                                               representative=cust["ubo"], ubos=[(cust["ubo"], 100, nat)],
                                               onboarding_time=dates.hours_ago(hours)),
                                   legal_form=company["legal_form"], activity=company["activity"],
                                   document_title=company["document_title"], authority=company["authority"]),
                       **common)
    else:
        viz = pp["viz"]
        printed = f"{viz['surname']} {viz['given']}".strip()
        kyc = kyc_case(name=cust["name"], dob=cust["dob"], id_type="Passport", id_number=pp["number"],
                       native_name=printed if any(ord(ch) > 127 for ch in printed) else "", gender=s["sex"], **common)
    mrz = pp["mrz"]
    kyc["vendor_check"]["extracted"].update(name=" ".join(mrz["primary_tokens"] + mrz["secondary"]), dob=cust["dob"],
                                            id_number=pp["number"], id_type="Passport", expiry=s["passport_expiry"])
    kyc["recon"] = _recorded(v)
    alert, wc = pair_screening(kyc, key, [_match(v, key)])
    return kyc, alert, wc


def build():
    """(kyc_cases, alert_cases, wc_cases) for the whole file."""
    VIEWS.clear()
    kyc, alerts, wcs = [], [], []
    for seq, row in enumerate(hub_loader.read_rows(), start=1):
        v = hub_documents.synthesise(hub_loader.build_case(row, seq))
        v.pop("raw", None)
        VIEWS[v["id"]] = v
        k, a, w = case_records(v, STARTERS.get(v["id"], ""))
        kyc.append(k)
        alerts.append(a)
        wcs.append(w)
    return kyc, alerts, wcs
