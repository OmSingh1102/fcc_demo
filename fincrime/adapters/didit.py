"""Didit ID verification: an uploaded ID checked by Didit's standalone ID
Verification API (is it genuine, unaltered, valid: screen captures, printed
copies, a replaced portrait, covered fields, the MRZ, expiry), with the API
key entered on the Settings page. Nothing about the account is in the code;
without a key no case is sent to Didit.

Written from Didit's public API reference (POST /v3/id-verification/, a
multipart upload with the x-api-key header) and NOT YET RUN against the
service (no account so far): the base URL and the path are settings. A
sandbox key answers every call with a fixed "Approved" sample ("Sandbox
User", SANDBOX-0001) without looking at the image: it is kept as a sandbox
answer, free, and never counts as an approval. Face match
and liveness need a selfie, which an uploaded ID does not bring: they are
not called.

The answer kept with the case: Approved or Declined, the warnings (each
with whether it declines), the document type, the name, date of birth and
number Didit read, and the photo-quality scores.

AML screening (POST /v3/aml/, JSON, the same key): the person on the ID
against Didit's watchlists, chosen on Settings as where the console screens
(see aml_screen below).
"""
import json
import re
import secrets
import time
import urllib.error
import urllib.request

from fincrime.data import countries

DEFAULTS = {"api_key": "", "base_url": "https://verification.didit.me", "path": "/v3/id-verification/", "auto": True,
            "document_liveness": True, "price_per_call": 0.20,
            # AML screening: its path, its price, whether the news is searched too, a sandbox key's fixed answer
            "aml_path": "/v3/aml/", "aml_price": 0.20, "aml_adverse_media": False, "aml_sandbox_scenario": ""}
TIMEOUT = 120


class DiditError(Exception):
    """A call Didit refused or did not answer; the message says why."""


def configured(cfg):
    return bool((cfg or {}).get("api_key"))


def _send(req):
    """(status, body bytes) of one request (the seam the tests stand in for)."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def multipart(fields, files):
    """(body, content type) of a multipart/form-data request."""
    boundary = "----fcc" + secrets.token_hex(12)
    out = []
    for name, value in fields.items():
        out += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode("utf-8"),
                str(value).encode("utf-8"), b"\r\n"]
    for name, (filename, data, mime) in files.items():
        out += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n".encode("utf-8"), data, b"\r\n"]
    out.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


_REFUSED = {401: ("Didit does not accept the API key (401): it is wrong, revoked or expired. In the Business Console, "
                  "Developers > API keys of the live application: create a key, copy it at once, and save it on Settings."),
            403: "Didit refused the call (403): a wrong or revoked key, a key without access to sessions, or no credits left.",
            429: "Didit's rate limit (429): try again in a minute."}


def _refused(status, raw):
    """Say why, when Didit refused the call: no credits, the key, the rate limit."""
    if status == 403 and b"enough credits" in raw:
        raise DiditError("Didit accepted the key, but the account has no credits left (403): top up in the Business Console, "
                         "Settings > Organization > Billing and plan > Top up ($50 minimum; a check is about $0.20).")
    if status in _REFUSED:
        raise DiditError(_REFUSED[status] + f" {raw[:160].decode('utf-8', 'replace')}")


def verify(cfg, jpeg, reference=""):
    """Didit's verdict on one ID image, as kept with the case."""
    body, ctype = multipart({"perform_document_liveness": "true" if cfg.get("document_liveness", True) else "false",
                             "vendor_data": reference, "save_api_request": "true"},
                            {"front_image": ("id.jpg", jpeg, "image/jpeg")})
    url = cfg["base_url"].rstrip("/") + "/" + cfg["path"].lstrip("/")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"x-api-key": cfg["api_key"], "Content-Type": ctype, "Accept": "application/json"})
    started = time.monotonic()
    try:
        status, raw = _send(req)
    except (urllib.error.URLError, OSError) as exc:
        raise DiditError(f"Didit did not answer ({type(exc).__name__}): {str(exc)[:160]}") from exc
    _refused(status, raw)
    if status == 400:
        raise DiditError(f"Didit could not use the image (400): {raw[:200].decode('utf-8', 'replace')}")
    if status >= 400:
        raise DiditError(f"Didit answered {status}: {raw[:200].decode('utf-8', 'replace')}")
    return summary(json.loads(raw), float(cfg.get("price_per_call") or 0), round(time.monotonic() - started, 1))


def is_sandbox(v):
    """Is this the sandbox's fixed sample ("Sandbox User", SANDBOX-0001) rather
    than a check of the image? (Didit's answer, or the summary kept of it.)"""
    return "sandbox" in f"{v.get('full_name') or ''} {v.get('document_number') or ''}".lower()


def summary(answer, price=0.0, seconds=0.0):
    """The parts of Didit's answer kept with the case."""
    v = answer.get("id_verification") or {}
    q = v.get("front_image_quality_score") or {}
    sandbox = is_sandbox(v)
    return {"provider": "Didit", "status": v.get("status") or "Unknown", "request_id": answer.get("request_id", ""), "sandbox": sandbox,
            "document_type": v.get("document_type") or "", "full_name": v.get("full_name") or "",
            "date_of_birth": v.get("date_of_birth") or "", "document_number": v.get("document_number") or "",
            "expiration_date": v.get("expiration_date") or "", "issuing_state": v.get("issuing_state_name") or v.get("issuing_state") or "",
            "warnings": [{"risk": w.get("risk", ""), "declines": w.get("log_type") == "error",
                          "text": w.get("short_description") or w.get("risk", "")} for w in v.get("warnings") or []],
            "quality": {k: q.get(k) for k in ("overall_score", "focus_score", "brightness_issue", "is_document_fully_visible")} if q else {},
            "cost": round(price, 4) if v.get("status") in ("Approved", "Declined") and not sandbox else 0.0, "seconds": seconds}


# ── AML screening: the person on the ID against Didit's watchlists ───────────
# Sanctions, PEPs, warnings and enforcement, and the news when Settings asks.
# Didit scores each hit (its match score weighs the name, the date of birth
# and the country; the same document number makes it a sure match) and marks
# those under its own threshold "False Positive". Every hit it returns comes
# to the console, where the AI decides it under the SOP as it does a
# World-Check hit, with Didit's scores beside it; a person confirms.

AML_SCENARIOS = ("", "decline_aml_hit", "review_aml_possible_match")     # a sandbox key's fixed answers ("": a live key)


def _url(cfg, key):
    return cfg["base_url"].rstrip("/") + "/" + (cfg.get(key) or DEFAULTS[key]).lstrip("/")


def _post_json(cfg, url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                                 headers={"x-api-key": cfg["api_key"], "Content-Type": "application/json", "Accept": "application/json"})
    try:
        return _send(req)
    except (urllib.error.URLError, OSError) as exc:
        raise DiditError(f"Didit did not answer ({type(exc).__name__}): {str(exc)[:160]}") from exc


def aml_query(person, reference="", cfg=None):
    """What Didit's AML screening is sent for the person on the ID: the name,
    and the date of birth, nationality (two letters) and document number
    when the ID gives them."""
    cfg = cfg or {}
    body = {"full_name": (person.get("name") or "").strip(), "entity_type": "person", "save_api_request": True}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", person.get("dob") or ""):
        body["date_of_birth"] = person["dob"]
    if countries.alpha2(person.get("nationality")):
        body["nationality"] = countries.alpha2(person["nationality"])
    number = (person.get("document_number") or "").strip()
    if 2 <= len(number) <= 50:
        body["document_number"] = number
    if reference:
        body["vendor_data"] = reference
    if cfg.get("aml_adverse_media"):
        body["include_adverse_media"] = True
    if cfg.get("aml_sandbox_scenario") in AML_SCENARIOS[1:]:
        body["sandbox_scenario"] = cfg["aml_sandbox_scenario"]
    return body


def _values(props, *keys):
    out = []
    for k in keys:
        for v in props.get(k) or []:
            v = str(v).strip()
            if v and v not in out:
                out.append(v)
    return out


def _compare(breakdown, part):
    """Didit's score for the date of birth or the country, in the console's
    words: Matched, Not matched, Partly matched (the same year), Unknown
    (missing on either side)."""
    if not breakdown.get(f"{part}_weight_normalized") or breakdown.get(f"{part}_score") is None:
        return "Unknown"
    score = float(breakdown[f"{part}_score"])
    return "Matched" if score >= 100 else "Not matched" if score < 0 else "Partly matched"


def _joined(v):
    return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v or "")


def _narrative(h):
    """What the lists say of the matched entity, as the hit's trigger."""
    parts = []
    for m in h.get("sanction_matches") or []:
        parts.append(f"Sanctions ({_joined(m.get('list_name'))}): "
                     + "; ".join(str(m[k]) for k in ("reason", "sanction_program", "sanctioning_authority", "listed_on") if m.get(k)))
    for m in h.get("pep_matches") or []:
        parts.append(f"PEP ({_joined(m.get('list_name')) or m.get('publisher', '')}): {m.get('pep_position') or m.get('description') or ''}")
    for m in h.get("warning_matches") or []:
        parts.append(f"Warning ({_joined(m.get('list_name'))}): {m.get('description') or m.get('reason') or ''}")
    for m in (h.get("adverse_media_matches") or [])[:3]:
        parts.append(f"News {str(m.get('publication_date') or '')[:10]}: {m.get('headline', '')}")
    props = h.get("properties") or {}
    parts += [f"Position: {p}" for p in _values(props, "position")[:2]] + _values(props, "notes")[:2]
    if h.get("rca_name"):
        parts.append(f"Matched through a relative or close associate: {h['rca_name']}")
    return " ".join(q.rstrip(".") + "." for q in (p.strip().rstrip(":;").strip() for p in parts) if q)[:1500]


def aml_hit(h, i=0):
    """One of Didit's hits as a console hit (the strength is the console's, by its match score)."""
    props, breakdown = h.get("properties") or {}, h.get("score_breakdown") or {}
    raw = h.get("match_score") if h.get("match_score") is not None else float(h.get("score") or 0) * 100
    caption = h.get("caption") or (_values(props, "name") or [""])[0]
    return {"uid": re.sub(r"[^A-Za-z0-9_.-]", "-", str(h.get("id") or f"hit-{i + 1}"))[:64], "name": caption,
            "aka": [a for a in _values(props, "name", "alias") if a != caption][:6],
            "dob_text": ", ".join(_values(props, "birthDate")) or "Not listed",
            "places": "; ".join(_values(props, "nationality", "country", "citizenship", "birthPlace")) or "Not listed",
            "category": ", ".join(h.get("datasets") or []) or "Watchlist",
            "narrative": _narrative(h) or "See the hit in Didit's Business Console.",
            "score": int(round(float(raw or 0))), "strength": "",
            "dob_result": _compare(breakdown, "dob"), "country_result": _compare(breakdown, "country"),
            "source": "Didit AML", "row": "", "risk_score": h.get("risk_score"), "didit_review": h.get("review_status") or "",
            "document_match": breakdown.get("document_number_match_type") or "", "url": h.get("url") or ""}


def aml_screen(cfg, person, limit=5, reference=""):
    """Screen the person on Didit's AML lists. Returns (the hits, best match
    first, at most `limit`; the screening as kept with the case)."""
    started = time.monotonic()
    status, raw = _post_json(cfg, _url(cfg, "aml_path"), aml_query(person, reference, cfg))
    _refused(status, raw)
    if status == 400:
        raise DiditError(f"Didit could not screen the name (400): {raw[:200].decode('utf-8', 'replace')}")
    if status >= 400:
        raise DiditError(f"Didit answered {status}: {raw[:200].decode('utf-8', 'replace')}")
    try:
        answer = json.loads(raw)
    except ValueError as exc:
        raise DiditError("Didit's answer was not JSON.") from exc
    aml = answer.get("aml") or {}
    found = sorted(aml.get("hits") or [], key=lambda h: -float(h.get("match_score") or 0))
    hits, seen = [], set()
    for i, h in enumerate(found[:limit]):
        hit = aml_hit(h, i)
        if hit["uid"] in seen:
            hit["uid"] = f"{hit['uid']}-{i + 1}"
        seen.add(hit["uid"])
        hits.append(hit)
    sandbox = cfg.get("aml_sandbox_scenario") in AML_SCENARIOS[1:]
    return hits, {"provider": "Didit", "status": aml.get("status") or "Unknown", "score": aml.get("score"),
                  "total_hits": aml.get("total_hits", len(aml.get("hits") or [])), "request_id": answer.get("request_id", ""),
                  "adverse_media": bool(cfg.get("aml_adverse_media")), "sandbox": sandbox,
                  "warnings": [w.get("short_description") or w.get("risk", "") for w in aml.get("warnings") or []],
                  "cost": 0.0 if sandbox else round(float(cfg.get("aml_price") or 0), 4),
                  "seconds": round(time.monotonic() - started, 1)}


def aml_test(cfg):
    """Is AML screening ready with the saved key? Didit is sent an empty
    name: it checks the key and the credits first, then refuses the name
    (400), so nobody is screened and nothing is billed."""
    status, raw = _post_json(cfg, _url(cfg, "aml_path"), {"full_name": ""})
    _refused(status, raw)
    if status == 404:
        raise DiditError("Didit has no AML screening at that path (404): check the AML path on Settings.")
    if status == 400:
        return "Didit accepted the key and the account has credits: AML screening is ready. (The test screened no one and cost nothing.)"
    if status >= 400:
        raise DiditError(f"Didit answered {status}: {raw[:200].decode('utf-8', 'replace')}")
    return f"Didit answered {status} to the test: AML screening is reachable."
