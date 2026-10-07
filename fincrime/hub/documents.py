"""Synthetic uploads for the hub's cases.

The reconciliation log carries no document images, so the demo plants a
deterministic defect plan on each case (a hash of the case id decides) and
draws the uploads as SPECIMEN SVGs the way the console's svg_cards does.
The Document Intake Agent then runs real checks on them - the MRZ check
digits, the VIZ against the MRZ, the expiry, the proof-of-address age - so
the defect is synthetic but the detection is not, and the screens say so.
"""
import hashlib
from datetime import timedelta

from fincrime.documents import svg_cards
from fincrime.documents.svg_cards import (FONT, ISO3, MONO, _check_digit, _defs, _field, _footer, _label, _mrz_lines, _pad,
                                          _silhouette, _stamp, _value, _watermark)
from fincrime.utils import dates
from fincrime.utils.text import esc, mrz_field

CAPTURE_PER_MILLE = 80             # cases with a capture defect on the passport photo
TAMPER_PER_MILLE = 20              # cases whose passport fails its own check digits
POA_OLD_PER_MILLE = 30             # cases whose proof of address is 7-11 months old
_CAPTURE_BUCKETS = ("flat_scan", "flat_scan", "flat_scan", "partial", "partial", "partial", "glare", "glare",
                    "blur", "blur", "expired", "expired")
DEFECT_LABEL = {"flat_scan": "Flat scan / PDF, not a camera photo", "partial": "Partial image: edges and MRZ cut off",
                "glare": "Glare over the data page", "blur": "Blurred image", "expired": "Expired document",
                "tampered": "Data page and MRZ disagree"}
COUNTRY_HEADER = {"IN": "REPUBLIC OF INDIA", "VN": "SOCIALIST REPUBLIC OF VIET NAM", "US": "UNITED STATES OF AMERICA"}
SECONDARY_TITLE = {"PAN Card": "PERMANENT ACCOUNT NUMBER CARD", "Aadhaar": "AADHAAR", "Voter ID (EPIC)": "ELECTOR PHOTO IDENTITY CARD",
                   "Driving Licence": "DRIVING LICENCE", "CCCD (chip Citizen ID)": "CĂN CƯỚC CÔNG DÂN",
                   "Căn cước (2024 ID card)": "CĂN CƯỚC", "Certificate of Naturalization": "CERTIFICATE OF NATURALIZATION"}


def _h(seed, case_id):
    return int(hashlib.sha256(f"{seed}:{case_id}".encode("utf-8")).hexdigest(), 16)


def _iso(dt):
    return dt.strftime("%Y-%m-%d")


def synthesise(case):
    """Decide the uploads and their defects for one case. Deterministic:
    the same case always gets the same plan."""
    cid = case["id"]
    h = _h("hub-doc", cid)
    tampered = _h("hub-tamper", cid) % 1000 < TAMPER_PER_MILLE
    capture = "none"
    if not tampered and h % 1000 < CAPTURE_PER_MILLE:
        capture = _CAPTURE_BUCKETS[(h >> 8) % len(_CAPTURE_BUCKETS)]
    poa_old = _h("hub-poa", cid) % 1000 < POA_OLD_PER_MILLE
    received = dates.BOOT - timedelta(hours=h % 96, minutes=(h >> 16) % 60)
    poa_age = 210 + (h >> 24) % 120 if poa_old else 7 + (h >> 24) % 140
    issued = received - timedelta(days=poa_age)
    years_held = 1 + (h >> 32) % 9
    pp_issue = received - timedelta(days=365 * years_held + (h >> 40) % 300)
    if capture == "expired":
        pp_expiry = received - timedelta(days=30 + (h >> 48) % 370)
    else:
        pp_expiry = pp_issue + timedelta(days=3652)
    sex = "F" if (h >> 56) % 2 else "M"
    docs = case["documents"]
    defects = []
    if capture != "none":
        defects.append(capture)
    if tampered:
        defects.append("tampered")
    files = [
        {"id": "passport", "kind": "passport", "side": "front", "label": "Passport data page", "defects": defects,
         "capture": "flat_scan" if capture == "flat_scan" else "photo"},
        {"id": "passport-back", "kind": "passport", "side": "back", "label": "Passport back page", "defects": [], "capture": "photo"},
        {"id": "secondary", "kind": docs["secondary"]["kind"], "side": "front", "label": docs["secondary"]["type"],
         "defects": [], "capture": "photo"},
        {"id": "poa", "kind": docs["poa"]["kind"], "side": "page 1", "label": docs["poa"]["type"], "defects": [],
         "capture": "flat_scan", "issued_on": _iso(issued)},
    ]
    case["synth"] = {"capture": capture, "tampered": tampered, "poa_age_days": poa_age, "poa_issued_on": _iso(issued),
                     "received_at": dates.fmt(received), "passport_issued": _iso(pp_issue), "passport_expiry": _iso(pp_expiry),
                     "sex": sex, "id_number": f"{_h('hub-id', cid) % 10 ** 10:010d}"}
    case["files"] = files
    return case


# ── MRZ line 2 ───────────────────────────────────────────────────────────────

def _yymmdd(iso):
    d = dates.parse(iso)
    return d.strftime("%y%m%d") if d else "000000"


def mrz_line2(case, tampered=None):
    """Line 2 of the passport MRZ with its 7-3-1 check digits, from the
    passport number, the date of birth and the expiry. A tampered page
    carries a wrong date-of-birth check digit."""
    s = case["synth"]
    issuer = case["documents"]["passport"]["mrz"].get("issuer") or ISO3.get(case["country"], "XXX")
    num = _pad(mrz_field(case["documents"]["passport"]["number"]), 9)
    dob = _yymmdd(case["customer"]["dob"])
    exp = _yymmdd(s["passport_expiry"])
    dob_cd = _check_digit(dob)
    if tampered if tampered is not None else s.get("tampered"):
        dob_cd = str((int(dob_cd) + 1) % 10)
    body = num + _check_digit(num) + issuer + dob + dob_cd + "<" + exp + _check_digit(exp) + "<" * 14
    composite = _check_digit(num + _check_digit(num) + dob + dob_cd + exp + _check_digit(exp) + "<" * 14)
    return _pad(body + "<" + composite, 44)


def mrz_checks(case):
    """Verify the check digits of line 2 as the intake agent sees it.
    Returns (ok, detail)."""
    line = mrz_line2(case)
    num, num_cd = line[0:9], line[9]
    dob, dob_cd = line[13:19], line[19]
    exp, exp_cd = line[21:27], line[27]
    problems = []
    if _check_digit(num) != num_cd:
        problems.append("document number check digit")
    if _check_digit(dob) != dob_cd:
        problems.append("date-of-birth check digit")
    if _check_digit(exp) != exp_cd:
        problems.append("expiry check digit")
    return (not problems), problems, line


# ── drawing ──────────────────────────────────────────────────────────────────

def _long_date(iso):
    d = dates.parse(iso)
    return d.strftime("%d %b %Y").upper() if d else ""


def _wrap_hub(W, H, body, file):
    """Close the SVG with the capture look and the planted defect."""
    defects = set(file.get("defects") or [])
    view = f"0 0 {W} {H}"
    inner = body
    if "partial" in defects:
        view = f"{int(W * 0.08)} 0 {int(W * 0.84)} {int(H * 0.72)}"
    if "blur" in defects:
        inner = f'<g filter="url(#blur)">{inner}</g>'
    if "glare" in defects:
        inner += (f'<defs><radialGradient id="glare" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#fff" stop-opacity="0.98"/>'
                  f'<stop offset="0.55" stop-color="#fff" stop-opacity="0.85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>'
                  f'<ellipse cx="{W * 0.62}" cy="{H * 0.74}" rx="{W * 0.34}" ry="{H * 0.3}" fill="url(#glare)"/>')
    if file.get("capture") == "flat_scan" or "flat_scan" in defects:
        inner = (f'<defs><filter id="scan"><feColorMatrix type="saturate" values="0.35"/></filter></defs>'
                 f'<g filter="url(#scan)">{inner}</g>'
                 f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" fill="none" stroke="#b7b7b2" stroke-width="1"/>')
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{W}" height="{H}" font-family="{FONT}" '
                f'style="background:#e9e9e6" data-capture="flat_scan"><rect x="-2000" y="-2000" width="5000" height="5000" fill="#e9e9e6"/>{inner}</svg>')
    # a camera photo: the card lies on a dark table, slightly turned, with a shadow
    inner = (f'<rect x="-2000" y="-2000" width="5000" height="5000" fill="#2b2b2b"/>'
             f'<g transform="rotate(-1.6 {W / 2} {H / 2}) translate(4 6)"><rect x="0" y="0" width="{W}" height="{H}" rx="14" fill="#000" opacity="0.45"/></g>'
             f'<g transform="rotate(-1.6 {W / 2} {H / 2})">{inner}</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{W}" height="{H}" font-family="{FONT}" '
            f'style="background:#2b2b2b" data-capture="photo">{inner}</svg>')


def passport_page(case, file):
    s, docs = case["synth"], case["documents"]
    pp = docs["passport"]
    W, H = 640, 440
    tampered = "tampered" in (file.get("defects") or [])
    country = COUNTRY_HEADER.get(case["country"], case["country_name"].upper())
    body = _defs()
    body += f'<rect width="{W}" height="{H}" rx="14" fill="#f4efe4"/><rect width="{W}" height="{H}" rx="14" fill="url(#guilloche)"/>'
    body += f'<rect x="0" y="0" width="{W}" height="54" rx="14" fill="#5b2a86"/>'
    body += _value(24, 34, country, 15, "700", "#fff")
    body += f'<text x="{W - 24}" y="34" text-anchor="end" font-family="{FONT}" font-size="13" font-weight="700" fill="#e4d4f5">PASSPORT / PASSEPORT</text>'
    body += _silhouette(28, 78, 150, 190)
    x = 210
    body += _label(x, 86, "Type / Type") + _value(x, 102, "P", 13)
    body += _label(x + 70, 86, "Code / Code") + _value(x + 70, 102, pp["mrz"].get("issuer") or ISO3.get(case["country"], ""), 13)
    body += _label(x + 170, 86, "Passport No. / No du passeport") + _value(x + 170, 102, pp["number"], 14, family=MONO)
    body += _field(x, 130, "Surname / Nom", pp["viz"]["surname"] or "", 15)
    body += _field(x, 166, "Given names / Prenoms", pp["viz"]["given"], 14)
    body += _field(x, 202, "Nationality / Nationalite", case["country_name"], 12)
    dob_value = _long_date(case["customer"]["dob"])
    if tampered:
        body += _label(x + 230, 202, "Date of birth / Date de naissance")
        body += _value(x + 230, 216, dob_value, 12, "700", "#111", family=MONO)
    else:
        body += _field(x + 230, 202, "Date of birth / Date de naissance", dob_value, 12)
    body += _field(x, 238, "Place of birth / Lieu de naissance", pp["address"]["pob"] or case["wc"]["location"].get("city", "") or case["country_name"], 11)
    body += _field(x + 230, 238, "Sex / Sexe", s["sex"], 12)
    body += _field(x, 274, "Date of issue / Date de delivrance", _long_date(s["passport_issued"]), 12)
    body += _field(x + 230, 274, "Date of expiry / Date d'expiration", _long_date(s["passport_expiry"]), 12)
    if pp["address"]["printed"]:
        body += _label(x, 312, "Address / Adresse")
        text = pp["address"]["text"]
        body += _value(x, 326, text[:62], 9, "600")
        if len(text) > 62:
            body += _value(x, 338, text[62:124], 9, "600")
    body += _mrz_lines(28, 396, [pp["mrz"]["line1"], mrz_line2(case, tampered)], W - 46)
    if "expired" in (file.get("defects") or []):
        body += _stamp(W - 130, 300, "EXPIRED")
    body += _watermark(W, H) + _footer(W, H)
    return _wrap_hub(W, H, body, file)


def passport_back(case, file):
    W, H = 640, 440
    country = COUNTRY_HEADER.get(case["country"], case["country_name"].upper())
    body = _defs()
    body += f'<rect width="{W}" height="{H}" rx="14" fill="#f4efe4"/><rect width="{W}" height="{H}" rx="14" fill="url(#guilloche)"/>'
    body += f'<rect x="0" y="0" width="{W}" height="54" rx="14" fill="#5b2a86"/>'
    body += _value(24, 34, country, 15, "700", "#fff")
    body += _label(24, 90, "ENDORSEMENTS / OBSERVATIONS") + _value(24, 112, "NONE", 12, "600")
    body += _label(24, 150, "EMERGENCY CONTACT") + _value(24, 170, "Not recorded", 12, "500", "#444")
    body += _label(24, 210, "ISSUING AUTHORITY") + _value(24, 230, f"PASSPORT OFFICE - {case['documents']['passport']['mrz'].get('issuer') or ''}", 12, "600")
    body += f'<rect x="{W - 200}" y="80" width="160" height="60" fill="url(#bars)"/>' + _label(W - 200, 158, "SPECIMEN BARCODE")
    body += _watermark(W, H) + _footer(W, H)
    return _wrap_hub(W, H, body, file)


def _adapter(case, name, address, native=""):
    s = case["synth"]
    return {"client": {"legal_name": name, "native_name": native, "dob": case["customer"]["dob"], "nationality": case["country"],
                       "gender": s["sex"], "id_number": s["id_number"], "address": address, "country": case["country_name"]},
            "created_at": s["received_at"], "documents": [], "agency": None}


def render(case, file_id):
    """The SVG for one upload, or None when the id is unknown."""
    file = next((f for f in case.get("files", []) if f["id"] == file_id), None)
    if file is None:
        return None
    docs = case["documents"]
    if file["id"] == "passport":
        return passport_page(case, file)
    if file["id"] == "passport-back":
        return passport_back(case, file)
    sec, poa = docs["secondary"], docs["poa"]
    if file["id"] == "secondary":
        name = sec["name"] or case["identity"].get("name", {}).get("canonical", case["customer"]["name"])
        native = name if any(ord(ch) > 127 for ch in name) else ""
        address = sec["address"]["text"] or case["customer"]["address"]
        adapter = _adapter(case, name if not native else svg_cards.translit(name), address, native)
        doc = {"id": "secondary", "kind": sec["kind"], "side": "front", "quality": "ok", "country": case["country"]}
        if sec["kind"] == "driving_licence" and case["country"] == "US":
            adapter["client"]["address"] = address
            return svg_cards.driving_licence_svg(adapter, doc)
        title = SECONDARY_TITLE.get(sec["type"], sec["type"].upper())
        return svg_cards.national_id_svg(adapter, doc, title=title, code="ID")
    if file["id"] == "poa":
        name = case["identity"].get("name", {}).get("canonical", case["customer"]["name"])
        adapter = _adapter(case, name, poa["address"])
        doc = {"id": "poa", "kind": "utility_bill", "side": "page 1", "quality": "ok", "country": case["country"],
               "issued_on": file.get("issued_on", "")}
        kind, ptype = poa["kind"], poa["type"]
        if kind == "bank_statement":
            return svg_cards.bank_statement_svg(adapter, doc)
        if kind == "aadhaar":
            doc2 = dict(doc, side="back")
            return svg_cards.national_id_svg(adapter, doc2, title="AADHAAR", code="ID")
        if kind == "lease":
            return svg_cards.utility_bill_svg(adapter, doc, provider="Residential lease", kind=ptype.upper())
        if kind == "residence_confirmation":
            return svg_cards.utility_bill_svg(adapter, doc, provider="Công an phường", kind="XÁC NHẬN THÔNG TIN CƯ TRÚ (CT07)")
        if kind == "military_orders":
            return svg_cards.utility_bill_svg(adapter, doc, provider="Department of Defense", kind="LEAVE AND EARNINGS STATEMENT")
        provider = "EVN - Điện lực" if "EVN" in ptype else "Northgate Utilities"
        return svg_cards.utility_bill_svg(adapter, doc, provider=provider, kind=ptype.upper())
    return None
