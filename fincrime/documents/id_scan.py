"""Scan an ID: one uploaded identity document, read and checked, with no
case behind it.

The image is checked and cleaned first (uploads.prepare: a real image,
turned upright, resized, EXIF and GPS removed). Then two readers work on it
at once:
  - a vision model through Straive's LLM Foundry gateway (the one picked on
    the page: Claude, Gemini or GPT, the models the document benchmark
    measured) transcribes every printed field, the MRZ lines, and what
    spoils the photo;
  - Tesseract on this machine reads the page's text and, on a passport,
    the MRZ with its check digits (documents/ocr).
The checks are code, not the model's opinion: the check digits of the MRZ
the model transcribed and of the one Tesseract read, the two reads held to
each other field by field, the expiry, the age, the fields an ID must carry.

A scan is kept (StateStore kind "scan", the image under uploads/scans/)
until someone deletes it: its record has the read, the OCR, the checks, the
model, its tokens and cost. Without LLM_FOUNDRY_KEY only Tesseract runs.
"""
import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fincrime import benchmark
from fincrime.documents import ocr
from fincrime.filebook import llm, similarity

# The models offered on the page: the document benchmark's that read every
# field right, and Gemini 2.5 Flash, the cheapest (benchmark.MODELS has the prices).
MODEL_IDS = ("claude-opus-4-8", "claude-sonnet-5-5", "gemini-2.5-pro", "gemini-2.5-flash", "gpt-5", "gpt-5-mini")
DEFAULT_MODEL = llm.MODEL if llm.MODEL in MODEL_IDS else MODEL_IDS[0]

FIELDS = (("full_name", "Full name"), ("surname", "Surname"), ("given_names", "Given names"),
          ("date_of_birth", "Date of birth"), ("sex", "Sex"), ("nationality", "Nationality"),
          ("document_number", "Document number"), ("personal_number", "Personal / national number"),
          ("date_of_issue", "Date of issue"), ("date_of_expiry", "Date of expiry"), ("place_of_birth", "Place of birth"),
          ("address", "Address"), ("father_or_spouse_name", "Father's / spouse's name"),
          ("issuing_authority", "Issuing authority"))
FIELD_LABEL = dict(FIELDS)
DOC_TYPES = ("Passport", "National ID card", "Driving licence", "Residence permit", "Aadhaar card", "PAN card",
             "Voter ID", "Other identity document", "Not an identity document")
PROBLEMS = ("blurred", "glare", "cut off", "covered", "too dark", "low resolution", "not the data page")

SYSTEM = """You read one photo or scan of an identity document for a KYC onboarding team, the way an OCR / ID-document service would. Transcribe what is printed; never guess and never fill a field from what is usual for the document.

- document_type: the kind of document; issuing_country: the country (or state, for a US driving licence: "United States (California)") that issued it.
- fields: each value exactly as printed, in Latin script, keeping diacritics (NGUYỄN, not NGUYEN). Empty when the document does not print it or it is not legible. full_name: the holder's name in the order the document prints it. Dates as YYYY-MM-DD (a US document prints MM/DD/YYYY; elsewhere DD/MM/YYYY is usual: read the document's own format). sex: M, F or X as printed. nationality: as printed (a code such as IND or a word).
- mrz: the machine-readable lines exactly as printed, one string per line, with every < filler; [] when there is none.
- uncertain: the names of the fields you read but are not sure of (a character you could not make out, glare over a digit).
- readable: false when the photo is too poor to read the document's main fields. problems: what spoils the photo, from the list; [] for a good photo. A slight angle or a scan is fine.
- note: one short sentence on anything an analyst should know (a field crossed out, a handwritten change, a second document in the picture); else empty."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["document_type", "issuing_country", "readable", "problems", "fields", "mrz", "uncertain", "note"],
    "properties": {
        "document_type": {"type": "string", "enum": list(DOC_TYPES)},
        "issuing_country": {"type": "string"},
        "readable": {"type": "boolean"},
        "problems": {"type": "array", "items": {"type": "string", "enum": list(PROBLEMS)}},
        "fields": {"type": "object", "additionalProperties": False, "required": [k for k, _ in FIELDS],
                   "properties": {k: {"type": "string"} for k, _ in FIELDS}},
        "mrz": {"type": "array", "items": {"type": "string"}},
        "uncertain": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
}


def models():
    """The models the page offers, with their list prices."""
    by_id = {m["id"]: m for m in benchmark.MODELS}
    return [by_id[i] for i in MODEL_IDS if i in by_id]


def model_ready():
    return bool(llm.KEY)


def _model_read(jpeg, model):
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(jpeg).decode("ascii")}},
               {"type": "text", "text": "Read this document."}]
    started = time.monotonic()
    read, t_in, t_out = benchmark.call(model, content, SYSTEM, SCHEMA)
    fields = read.get("fields") or {}
    read["fields"] = {k: str(fields.get(k) or "").strip() for k, _ in FIELDS}
    read["mrz"] = [str(x).replace(" ", "").strip() for x in (read.get("mrz") or []) if str(x).strip()]
    price_in, price_out = model["price"]
    return read, {"model": model["id"], "label": model["label"], "tokens_in": t_in, "tokens_out": t_out,
                  "cost": round((t_in * price_in + t_out * price_out) / 1e6, 4),
                  "seconds": round(time.monotonic() - started, 1)}


def _tesseract(jpeg):
    if not ocr.available():
        return {"available": False, "text": "", "mrz": None}
    started = time.monotonic()
    found = ocr.mrz(jpeg)
    return {"available": True, "text": ocr.text(jpeg), "mrz": found, "seconds": round(time.monotonic() - started, 1)}


def scan(jpeg, model_id=None):
    """Both readers on one prepared image (at once), and the checks.
    Returns {read, model, tesseract, checks, error}: read is None when no
    model ran (no key) or its call failed (error says why)."""
    model = next((m for m in models() if m["id"] == (model_id or DEFAULT_MODEL)), models()[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        tess = pool.submit(_tesseract, jpeg)
        job = pool.submit(_model_read, jpeg, model) if model_ready() else None
        read, used, error = None, None, ""
        if job is not None:
            try:
                read, used = job.result()
            except Exception as exc:            # the page shows the reason; Tesseract's read still stands
                error = f"{model['label']} could not read the image: {type(exc).__name__}: {str(exc)[:200]}"
        else:
            error = "No model is configured (LLM_FOUNDRY_KEY): only Tesseract read the image."
        tesseract = tess.result()
    return {"read": read, "model": used, "tesseract": tesseract, "checks": checks(read, tesseract), "error": error}


# ── the checks ───────────────────────────────────────────────────────────────

def _iso(text):
    try:
        return date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def _letters(text):
    return "".join(ch for ch in similarity.fold(text) if ch.isalnum())


def _same(field, printed, coded):
    """A printed value and the MRZ's, alike once the MRZ's limits are set
    aside: no diacritics, no punctuation, names cut at the zone's width."""
    if field in ("dob", "expiry"):
        return printed.strip()[:10] == coded.strip()[:10]
    p, c = _letters(printed), _letters(coded)
    if field in ("surname", "given"):
        return bool(c) and (p == c or p.startswith(c))       # a long name is truncated in the zone
    return p == c


def _mrz_vs(read, parsed, who):
    """The printed fields held to an MRZ's: (agreeing labels, differing).
    Nationality only when the document prints it as a code, as the zone does
    ("VIETNAMESE" against VNM is no disagreement)."""
    f, m = read["fields"], parsed["fields"]
    pairs = [("Surname", "surname", f["surname"], m["surname"]), ("Given names", "given", f["given_names"], m["given_names"]),
             ("Document number", "number", f["document_number"], m["number"]), ("Date of birth", "dob", f["date_of_birth"], m["dob"]),
             ("Date of expiry", "expiry", f["date_of_expiry"], m["expiry"])]
    if len(_letters(f["nationality"])) == 3:
        pairs.append(("Nationality", "nationality", f["nationality"], m["nationality"]))
    agree, differ = [], []
    for label, key, printed, coded in pairs:
        if not printed or not coded:
            continue
        if _same(key, printed, coded):
            agree.append(label)
        else:
            differ.append(f"{label}: printed {printed}, {who} {coded}")
    return agree, differ


def _fillers_to(line, width=44):
    """A line whose longest run of < fillers is lengthened or shortened so
    the line is `width` long: models miscount a run of <. Fillers carry no
    data, and the check digits then test the result."""
    runs = [(m.end() - m.start(), m.start()) for m in re.finditer(r"<+", line)]
    if not runs or abs(len(line) - width) > 6:
        return line
    size, start = max(runs)
    keep = size + width - len(line)
    if keep < 1:
        return line
    return line[:start] + "<" * keep + line[start + size:]


def _td3(lines):
    """A model's transcription of a passport zone, each line's fillers
    counted out to 44."""
    return tuple(_fillers_to(x) for x in lines)


def _in_step(parsed):
    """An OCR'd zone whose first line is in step: the issuing state on line
    1 is the nationality on line 2 (true of a passport). Line 1 has no check
    digit, so a character OCR adds or drops there shifts the names unseen."""
    f = parsed["fields"]
    return bool(f["issuer"]) and f["issuer"] == f["nationality"]


def checks(read, tesseract, today=None):
    """[{label, state: ok | warn | fail | info, detail}] for a scan."""
    today = today or date.today()
    out = []

    def add(label, state, detail):
        out.append({"label": label, "state": state, "detail": detail})

    if read is not None:
        if read.get("document_type") == "Not an identity document":
            add("Identity document", "fail", "The model does not take this for an identity document.")
        if not read.get("readable", True):
            add("Photo", "fail", "Too poor to read the main fields" + (f": {', '.join(read['problems'])}." if read.get("problems") else "."))
        elif read.get("problems"):
            add("Photo", "warn", f"Readable, but {', '.join(read['problems'])}.")
        else:
            add("Photo", "ok", "Clear: nothing spoils it.")
        f = read["fields"]
        missing = [FIELD_LABEL[k] for k in ("full_name", "date_of_birth", "document_number") if not f.get(k)]
        add("Main fields", "warn" if missing else "ok",
            f"Not read: {', '.join(missing)}." if missing else "Name, date of birth and document number read.")
        if read.get("uncertain"):
            names = [FIELD_LABEL.get(u, u) for u in read["uncertain"]]
            add("Fields the model is unsure of", "warn", ", ".join(names) + ": check them against the image.")
        exp = _iso(f.get("date_of_expiry"))
        if exp:
            add("Expiry", "fail" if exp < today else "ok",
                f"Expired on {exp.isoformat()}." if exp < today else f"Valid until {exp.isoformat()}.")
        elif f.get("date_of_expiry"):
            add("Expiry", "warn", f"Printed as {f['date_of_expiry']}: not a date the check can read.")
        dob = _iso(f.get("date_of_birth"))
        if dob:
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            add("Age", "warn" if age < 18 else "ok", f"{age} years old" + (": a minor." if age < 18 else "."))
        printed = read.get("mrz") or []
        if len(printed) == 2:
            parsed = ocr.parse(*_td3(printed))
            if not parsed:
                add("MRZ", "info", "Transcribed below, but not as a passport zone's two 44-character lines: its check digits are not tested.")
            else:
                bad = [k for k, v in parsed["checks"].items() if not v]
                add("MRZ check digits (the model's transcription)", "ok" if parsed["valid"] else "warn",
                    "All five add up." if parsed["valid"] else f"Do not add up: {', '.join(bad)} (a misread character, or a forged zone).")
                agree, differ = _mrz_vs(read, parsed, "MRZ")
                if differ:
                    add("Printed fields against the MRZ", "fail", "; ".join(differ) + ".")
                elif agree:
                    add("Printed fields against the MRZ", "ok", f"{len(agree)} agree: {', '.join(agree)}.")
        elif len(printed) == 3:
            add("MRZ", "info", "An ID-card zone (three lines): transcribed below; its check digits are not tested here.")
    mrz = (tesseract or {}).get("mrz")
    if tesseract and not tesseract.get("available"):
        add("OCR cross-check (Tesseract)", "info", "Tesseract is not installed on this machine.")
    elif mrz:
        add("OCR cross-check (Tesseract)", "ok" if mrz["valid"] else "warn",
            "Tesseract read the passport MRZ and its check digits add up." if mrz["valid"]
            else "Tesseract found an MRZ but its check digits do not all add up (the photo, or the zone).")
        if read is not None and mrz["valid"]:
            if not _in_step(mrz):
                mrz = dict(mrz, fields=dict(mrz["fields"], surname="", given_names=""))
                add("OCR's first MRZ line", "info", "Out of step (a character added or dropped; that line has no check digit): "
                    "the names are not compared with it.")
            agree, differ = _mrz_vs(read, mrz, "OCR")
            if differ:
                add("Model's read against OCR", "fail", "; ".join(differ) + ".")
            elif agree:
                add("Model's read against OCR", "ok", f"{len(agree)} fields agree: {', '.join(agree)}.")
    elif tesseract:
        add("OCR cross-check (Tesseract)", "info", "No passport MRZ found by OCR (an ID card, a licence, or the zone not in the picture).")
    return out


def verdict(result):
    """One word for the scan: "Fail" when a check failed, "Check" when one
    warns, "Pass" when every check is ok; "Not read" with no model read."""
    if result.get("read") is None:
        return "Not read"
    states = {c["state"] for c in result["checks"]}
    return "Fail" if "fail" in states else "Check" if "warn" in states else "Pass"
