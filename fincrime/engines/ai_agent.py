"""The AI Agent: it works an L1 Data Confirming case the way an analyst does,
and hands the case to a person whenever it cannot be sure.

1. Claude reads the passport data page and the proof of address from their
   images (one call through Straive's LLM Foundry, fincrime/hub/llm.call):
   what is printed, whether it can be read, and what spoils the capture.
2. Fixed checks - code, not the model - compare that read with the case:
   readable, name, date of birth, nationality, ID number, expiry, the
   vendor's result, the proof of address and its address.
3. Every check passes: the agent confirms the data through the analysts'
   own path (workflow.confirm_data), the AI screening rules re-run, and a
   case they leave nothing on verifies itself. Any check fails, or Claude
   cannot be reached: the case stays in Data Confirming, labelled
   human-in-the-loop, with the reasons and what the agent read.

It only takes TT Live individuals whose screening the rules already
cleared (the auto-verified workflow); a company (KYB) and every case with an
alert left stay with people. The result sits on the case as case["ai_agent"].
"""
import base64
import time

from fincrime.data import vocab
from fincrime.documents.raster import svg_to_png
from fincrime.documents.svg_cards import ISO3
from fincrime.engines import workflow
from fincrime.engines.errors import WorkflowError
from fincrime.hub import addresses, llm, names, similarity
from fincrime.utils import dates

ACTOR = vocab.AI_AGENT
MODEL = llm.MODEL
ALPHA2 = {v: k for k, v in ISO3.items()}
SPOILERS = {"blurred": "blurred", "cut_off": "cut off", "glare": "glare"}
FILLERS = {"FNU", "LNU", "NFN", "NLN", "-", "."}
RETRIES = 3           # the gateway allows few concurrent calls; a 429 waits and tries again
RETRY_WAIT = 10.0

SYSTEM = ("You read identity documents for a KYC check at a bank. You are given images of a customer's documents. "
          "Report only what is printed and legible in the images. Never guess, infer or complete a value: if a field "
          "is not printed, cut off, blurred or hidden by glare, return an empty string for it. Mark a document "
          "unreadable when any of name, date of birth, document number or expiry on an ID cannot be read with "
          "certainty. Dates as YYYY-MM-DD.")

_DOC = {"type": "object", "additionalProperties": False, "properties": {
    "readable": {"type": "boolean"},
    "problems": {"type": "array", "items": {"type": "string", "enum": ["blurred", "cut_off", "glare", "other"]}},
    "surname": {"type": "string", "description": "Surname as printed (on a proof of address: the holder's full name)"},
    "given_names": {"type": "string", "description": "Given names as printed, else empty"},
    "dob": {"type": "string"},
    "nationality_code": {"type": "string", "description": "Three-letter code printed on the ID (e.g. VNM), else empty"},
    "document_number": {"type": "string"},
    "expiry": {"type": "string"},
    "address": {"type": "string", "description": "The address printed on the document, else empty"},
    "issued_on": {"type": "string", "description": "Issue or statement date, else empty"},
    "note": {"type": "string", "description": "One short sentence on anything wrong with the document, else empty"}},
    "required": ["readable", "problems", "surname", "given_names", "dob", "nationality_code", "document_number", "expiry", "address",
                 "issued_on", "note"]}
SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"id": _DOC, "poa": _DOC},
          "required": ["id", "poa"]}


# ── which case, which images ─────────────────────────────────────────────────

def eligible(case):
    """A TT Live individual in Data Confirming whose screening the rules
    cleared (auto-verified): the agent confirms it so it verifies itself.
    Everything else is an analyst's from the start."""
    return (case["tenant"] == "ttlive" and case["status"] == "DataConfirming" and not case.get("agency")
            and case["screening"].get("workflow") == "auto-verified")


def _id_doc(case):
    return next((d for d in case["documents"] if d.get("category") == "Passport"), None) or case["documents"][0]


def _image(png):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}}


def read(case, render, call=None, sleep=time.sleep):
    """Claude's read of the ID and the proof of address: (read, usage, seconds)."""
    call = call or llm.call
    content = [{"type": "text", "text": "Image 1 is the customer's ID (passport data page). Read it into `id`."},
               _image(svg_to_png(render(case, _id_doc(case))))]
    poa = workflow.poa_docs(case)
    if poa:
        content += [{"type": "text", "text": "Image 2 is the customer's proof of address. Read it into `poa`."},
                    _image(svg_to_png(render(case, poa[0])))]
    else:
        content.append({"type": "text", "text": "There is no proof of address: return `poa` unreadable with empty fields."})
    for attempt in range(RETRIES):
        try:
            return call(SYSTEM, content, SCHEMA, max_tokens=3000)
        except WorkflowError as exc:
            if " 429" not in str(exc) or attempt == RETRIES - 1:
                raise
            sleep(RETRY_WAIT * (attempt + 1))


# ── the checks ───────────────────────────────────────────────────────────────

def _name_key(text):
    return sorted(similarity.tokens(text))


def name_verdict(crm, surname, given):
    """Is the CRM name the person the ID names? The hub's own name rules
    decide: the ID's surname is among the CRM's names (any typing, a
    compound part, a spelling variant) and a given name agrees (exact,
    nickname, short form or spelling variant; an initial alone is not
    enough). Returns (same, value to confirm)."""
    crm_fixed, repaired = names.repair_mojibake(crm)
    c, s, g = similarity.tokens(crm_fixed), similarity.tokens(surname), similarity.tokens(given)
    if not c or not (s or g):
        return False, crm
    if _name_key(crm_fixed) == sorted(s + g):
        return True, (similarity.fold(" ".join(c)) if repaired else crm)
    if not s:
        # a single-name passport: the CRM's other tokens are fillers (FNU),
        # repeats or initials the record system added
        core = {t for t in c if t not in FILLERS and not names.is_initial(t)}
        return (bool(core) and core <= set(g)), " ".join(g)
    sur_ok = names.surname_score(c, s) >= 0.8 or (
        # a patronymic initial: BALAJI K for KRISHNAN BALAJI
        any(names.is_initial(t) and t[0] == s[0][0] for t in c))
    rest = [t for t in c if t not in names.surname_forms(s)]
    giv_ok = not g or any(names.given_match(a, b) >= 0.9 for a in g for b in rest)
    if not (sur_ok and giv_ok):
        return False, crm
    # the ID's spelling, in the order the CRM keeps (surname first or last)
    surname_first = c[0] in names.surname_forms(s)
    return True, " ".join(s + g if surname_first else g + s)


def _poa_address(read, country):
    """The demo's proof-of-address images print the passport country after
    every address, so an overseas one reads '..., CA 92683, USA, Vietnam'.
    Drop that tail when the address before it names another country."""
    name = vocab.COUNTRY_NAMES.get(country, "")
    head, _, tail = read.rpartition(",")
    if name and head and similarity.fold(tail) == similarity.fold(name)             and addresses.normalise(head, country)["country"] not in ("", country):
        return head.strip()
    return read


def _check(out, check, crm, document, ok, note=""):
    out.append({"check": check, "crm": crm or "", "document": document or "", "ok": bool(ok), "note": note})


def checks(case, got, now=None):
    """Every check the agent makes on Claude's read, in order; each says why
    it failed. Also returns the values to confirm when they all pass."""
    now = now or dates.now()
    client = case["client"]
    idr, poa = got.get("id") or {}, got.get("poa") or {}
    out = []
    spoilt = [SPOILERS[p] for p in idr.get("problems", []) if p in SPOILERS]
    _check(out, "ID readable", "", "readable" if idr.get("readable") and not spoilt else "not readable",
           idr.get("readable") and not spoilt,
           "" if idr.get("readable") and not spoilt else f"ID could not be read: {', '.join(spoilt) or idr.get('note') or 'unclear'}")

    printed = " ".join(x for x in (idr.get("surname", ""), idr.get("given_names", "")) if x)
    same, name_value = name_verdict(client["legal_name"], idr.get("surname", ""), idr.get("given_names", ""))
    _check(out, "Name", client["legal_name"], printed, same,
           "" if same else ("Name not readable on the ID" if not printed else "Name on the ID differs from the CRM"))

    dob = idr.get("dob", "")
    ok = bool(dob) and dob == client["dob"]
    _check(out, "Date of birth", client["dob"], dob or "not on the ID", ok,
           "" if ok else ("Date of birth missing on the ID" if not dob else f"Date of birth on the ID {dob}, CRM {client['dob']}"))

    code = (idr.get("nationality_code") or "").upper()
    nat = ALPHA2.get(code, code[:2] if len(code) == 2 else "")
    ok = nat == client["nationality"]
    _check(out, "Nationality", client["nationality"], code, ok, "" if ok else "Nationality on the ID differs from the CRM")

    number = similarity.squash(similarity.fold(idr.get("document_number", "")))
    ok = bool(number) and number == similarity.squash(similarity.fold(client.get("id_number", "")))
    _check(out, "ID number", client.get("id_number", ""), idr.get("document_number", ""), ok,
           "" if ok else "ID number on the document differs from the CRM")

    expiry = dates.parse(idr.get("expiry", ""))
    ok = expiry is not None and expiry >= now
    _check(out, "Expiry", "", idr.get("expiry", "") or "not readable", ok,
           "" if ok else (f"ID expired on {idr['expiry']}" if expiry else "Expiry date not readable"))

    vc = case.get("vendor_check") or {}
    ok = vc.get("result") != "Declined"
    _check(out, "Vendor check", "", vc.get("result", ""), ok,
           "" if ok else "ID declined by the vendor" + (f": {vc['vendor_reason']}" if vc.get("vendor_reason") else ""))

    if case.get("poa_required"):
        _check(out, "Proof of address readable", "", "readable" if poa.get("readable") else "not readable",
               poa.get("readable"), "" if poa.get("readable") else "Proof of address could not be read")
        country = client.get("nationality", "")
        verdict = addresses.compare(addresses.normalise(client.get("address", ""), country),
                                    addresses.normalise(_poa_address(poa.get("address", ""), country), country))
        _check(out, "Address", client.get("address", ""), poa.get("address", ""), verdict == "same",
               "" if verdict == "same" else f"Address on the proof of address does not match the CRM ({verdict.replace('_', ' ')})")
        failures = workflow.poa_failures(case, now)
        issued = dates.parse(poa.get("issued_on", ""))
        if issued is not None and (now - issued).days > vocab.POA_MAX_AGE_DAYS:
            failures.append({"label": "Issued within the last 6 months", "detail": f"the document reads {poa['issued_on']}"})
        _check(out, "Proof of address checks", "", "; ".join(f["detail"] for f in failures) or "passed", not failures,
               "; ".join(f"{f['label']}: {f['detail']}" for f in failures))
    values = {"name": name_value, "dob": client["dob"], "nationality": client["nationality"]}
    return out, values


# ── one case ─────────────────────────────────────────────────────────────────

def perceive(case, render, call=None, sleep=time.sleep):
    """The slow half, safe to run outside any lock: Claude's read of the
    documents, or the error that stopped it. Touches nothing."""
    started = time.monotonic()
    out = {"at": dates.now_str(), "model": MODEL, "read": {}, "usage": {}, "seconds": 0.0, "error": ""}
    try:
        got, usage, seconds = read(case, render, call=call, sleep=sleep)
        out.update(read=got, usage=usage, seconds=seconds)
    except WorkflowError as exc:
        out["error"] = str(exc)
    out["seconds"] = out["seconds"] or round(time.monotonic() - started, 1)
    return out


def decide(case, alert_case, wc, perceived):
    """The quick half: check the read and act on it. Mutates the case (and,
    when it confirms, the screening and watchlist cases the rules touch);
    the caller saves them."""
    record = dict(perceived, checks=[], reasons=[])
    values = {}
    if record["error"]:
        record["reasons"] = [f"AI Agent could not read the documents: {record['error']}"]
    else:
        record["checks"], values = checks(case, record["read"])
        record["reasons"] = [c["note"] for c in record["checks"] if not c["ok"]]
    if not record["reasons"]:
        workflow._audit(case, ACTOR, "Documents read", f"{MODEL} read the ID and the proof of address; every check passed.")
        try:
            workflow.confirm_data(case, ACTOR, values, "Confirmed by the AI Agent against the ID and the proof of address.",
                                  alert_case=alert_case, wc=wc)
        except WorkflowError as exc:
            record["reasons"] = [str(exc)]
    if record["reasons"]:
        record["decision"] = "human"
        case["screening"]["workflow"] = "human-in-the-loop"
        workflow._audit(case, ACTOR, "Sent to a person", "; ".join(record["reasons"]))
    else:
        record["decision"] = "verified" if case["status"] == "Verified" else "screening"
    case["ai_agent"] = record
    return record


def run_case(case, alert_case, wc, render, call=None, sleep=time.sleep):
    """Read, check, decide - one case, start to finish."""
    return decide(case, alert_case, wc, perceive(case, render, call=call, sleep=sleep))
