"""Our own sanctions screening: the official lists, downloaded free from the
governments that publish them, and searched here, so a name is screened
without a vendor and without sending it anywhere.

  OFAC  the US Treasury's Specially Designated Nationals list (SDN.CSV, with
        ALT.CSV for the other names)
  UN    the UN Security Council's consolidated list (XML), which India, like
        every UN member, enforces
  UK    the FCDO's UK Sanctions List (XML)
  EU    the European Commission's consolidated financial sanctions list (XML)

Each list is read into one shape (a profile: the names, the dates of birth,
the countries, the programme, why the person is listed) and kept as a JSON
file under DIR; the files are rebuilt when a list is downloaded again
(update), and the change since the last download (records added, records
taken off) is kept beside them. The name search is the stand-in's
(watchlist.name_score: word order, diacritics, hyphens and a missing middle
name set aside), with the date of birth and the country reported beside each
candidate, never used to drop one. A person on several lists (a UN listing
the UK and the EU carry too) is one hit naming every list.

What these lists are not: PEP lists, adverse media, or national lists beyond
these four. Those are bought (Didit, World-Check), not downloaded. The
download addresses and which lists are used are settings (Settings page),
not code.
"""
import csv
import gzip
import hashlib
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from fincrime import watchlist
from fincrime.filebook import similarity
from fincrime.utils import dates

LISTS = {
    "ofac": {"short": "OFAC", "label": "US OFAC SDN list", "publisher": "US Treasury, Office of Foreign Assets Control"},
    "un": {"short": "UN", "label": "UN Security Council consolidated list", "publisher": "United Nations Security Council"},
    "uk": {"short": "UK", "label": "UK Sanctions List", "publisher": "UK Foreign, Commonwealth & Development Office"},
    "eu": {"short": "EU", "label": "EU consolidated financial sanctions list", "publisher": "European Commission"},
}
ORDER = ("un", "uk", "eu", "ofac")              # which list's record speaks for a person on several
DEFAULTS = {
    "use_ofac": True, "use_un": True, "use_uk": True, "use_eu": True,
    "ofac_url": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
    "ofac_alt_url": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ALT.CSV",
    "un_url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
    "uk_url": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
    "eu_url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
    # downloaded again when the oldest is this many hours old (once one download was made); each
    # screened person screened again on every change; the seconds a download may take
    "auto_update": True, "update_hours": 24, "monitoring": True, "timeout": 240,
}
SOURCE = "Sanctions lists"                    # the screening's source, as the case keeps it
DIR = os.environ.get("SANCTIONS_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sanctions_lists")
_LOCK = threading.Lock()
_cache = {}


class ListError(Exception):
    pass


def enabled(cfg):
    cfg = cfg or {}
    return [k for k in LISTS if cfg.get("use_" + k, True)]


# ── reading dates, names and countries ───────────────────────────────────────

_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def _clean(text):
    t = re.sub(r"\s+", " ", (text or "").replace("-0-", "")).strip()
    return "" if t in ("-", "NA", "N/A") else t


def _dob(text):
    """One listed date of birth in the stand-in's form ({kind: full, date},
    {kind: year, year}, {kind: range, year, year_to}), or None."""
    t = _clean(text).lower().replace("circa ", "").replace("approximately ", "").replace("c. ", "").strip(" .")
    if not t:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", t)
    if m:
        return {"kind": "full", "date": t}
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", t)                      # the UK's dd/mm/yyyy
    if m:
        return {"kind": "full", "date": f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"}
    m = re.match(r"(\d{1,2}) ([a-z]{3})[a-z]* (\d{4})$", t)                 # OFAC's 10 Dec 1948
    if m and m[2] in _MONTHS:
        return {"kind": "full", "date": f"{m[3]}-{_MONTHS[m[2]]:02d}-{int(m[1]):02d}"}
    m = re.match(r"(\d{4}) to (\d{4})$", t) or re.match(r"(\d{4})\s*-\s*(\d{4})$", t)
    if m:
        return {"kind": "range", "year": int(m[1]), "year_to": int(m[2])}
    m = re.search(r"(?:^|\D)(\d{4})$", t)                                  # 1968, Dec 1948, dd/mm/1968
    if m:
        return {"kind": "year", "year": int(m[1])}
    return None


def _dob_text(d):
    return watchlist._dob_text(d) if d else "Not listed"


def _dob_result(dob_iso, dobs):
    """Matched when any listed date agrees with the ID's; Unknown when none is listed."""
    results = [watchlist._dob_result(dob_iso, d) for d in dobs] or ["Unknown"]
    return "Matched" if "Matched" in results else "Not matched" if "Not matched" in results else "Unknown"


def _country(text):
    t = _clean(text)
    return "" if not t or t.upper() in ("UNKNOWN", "00") else t.title() if t.isupper() else t


# the same country as the lists and the IDs write it (ISO codes, the people's word, the UN's long form)
_COUNTRY_NAMES = {
    "AFGHANISTAN": "AFG AFGHAN", "BANGLADESH": "BGD BANGLADESHI", "BELARUS": "BLR BELARUSIAN", "BURMA": "MMR MYANMAR BURMESE",
    "CHINA": "CHN CHINESE|PEOPLE'S REPUBLIC OF CHINA", "CUBA": "CUB CUBAN", "EGYPT": "EGY EGYPTIAN",
    "DR CONGO": "COD|DEMOCRATIC REPUBLIC OF THE CONGO|CONGO, DEMOCRATIC REPUBLIC OF THE|CONGO (DEMOCRATIC REPUBLIC)",
    "INDIA": "IND IN INDIAN", "INDONESIA": "IDN INDONESIAN", "IRAN": "IRN IRANIAN|IRAN (ISLAMIC REPUBLIC OF)|ISLAMIC REPUBLIC OF IRAN",
    "IRAQ": "IRQ IRAQI", "LEBANON": "LBN LEBANESE", "LIBYA": "LBY LIBYAN", "NEPAL": "NPL NEPALESE NEPALI", "NIGERIA": "NGA NIGERIAN",
    "NORTH KOREA": "PRK DPRK|NORTH KOREAN|KOREA, NORTH|DEMOCRATIC PEOPLE'S REPUBLIC OF KOREA|KOREA (DEMOCRATIC PEOPLE'S REPUBLIC OF)|KOREA, DEMOCRATIC PEOPLE'S REPUBLIC OF",
    "PAKISTAN": "PAK PAKISTANI", "PHILIPPINES": "PHL FILIPINO", "RUSSIA": "RUS RUSSIAN|RUSSIAN FEDERATION",
    "SAUDI ARABIA": "SAU SAUDI", "SOMALIA": "SOM SOMALI", "SRI LANKA": "LKA|SRI LANKAN", "SUDAN": "SDN SUDANESE",
    "SYRIA": "SYR SYRIAN|SYRIAN ARAB REPUBLIC", "TURKEY": "TUR TURKISH TURKIYE", "UKRAINE": "UKR UKRAINIAN",
    "UNITED ARAB EMIRATES": "ARE UAE EMIRATI", "UNITED KINGDOM": "GBR GB UK BRITISH|GREAT BRITAIN",
    "UNITED STATES": "USA US AMERICAN|UNITED STATES OF AMERICA", "VENEZUELA": "VEN VENEZUELAN|VENEZUELA (BOLIVARIAN REPUBLIC OF)",
    "VIETNAM": "VNM VN VIETNAMESE|VIET NAM", "YEMEN": "YEM YEMENI", "ZIMBABWE": "ZWE ZIMBABWEAN",
}
_COUNTRY_KEY = {}
for _name, _also in _COUNTRY_NAMES.items():           # before the first |: single words; after each |: a whole phrase
    _words_part, *_phrases = _also.split("|")
    for _w in [_name] + _words_part.split() + _phrases:
        _COUNTRY_KEY[similarity.fold(_w)] = _name


def country_key(text):
    """One spelling for a country (Russian Federation, RUS and Russian are Russia)."""
    t = similarity.fold(text)
    if t in _COUNTRY_KEY:
        return _COUNTRY_KEY[t]
    bare = similarity.fold(re.sub(r"\(.*?\)", " ", text or ""))
    return _COUNTRY_KEY.get(bare, watchlist._country_key(bare))


def _country_result(countries, person):
    mine = {country_key(person.get(k)) for k in ("issuing_country", "nationality")} - {""}
    if not mine or not countries:
        return "Unknown"
    return "Matched" if mine & {country_key(c) for c in countries} else "Not matched"


def _uniq(items):
    out, seen = [], set()
    for x in items:
        k = similarity.fold(x) if isinstance(x, str) else json.dumps(x, sort_keys=True)
        if x and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _profile(key, ref, kind, name, aka=(), dobs=(), countries=(), places="", programme="", listed_on="", narrative="", un_ref=""):
    names = _uniq([name] + list(aka))
    return {"uid": re.sub(r"[^A-Za-z0-9_.-]", "-", f"{LISTS[key]['short']}-{ref}")[:64], "list": key, "ref": str(ref),
            "type": kind, "name": name, "aka": names[1:12], "names": names[:24], "dobs": _uniq(list(dobs)),
            "countries": _uniq([_country(c) for c in countries]), "places": places[:300], "programme": programme[:200],
            "listed_on": listed_on, "narrative": re.sub(r"\s+", " ", narrative or "").strip()[:700],
            "un_ref": re.sub(r"\s+", "", un_ref or "").upper()}


def _given_surname(listed):
    """OFAC's and the UK's "SURNAME, Given" as the name is said: Given SURNAME."""
    if "," in listed:
        surname, given = listed.split(",", 1)
        return f"{given.strip()} {surname.strip()}".strip()
    return listed.strip()


# ── the four formats ─────────────────────────────────────────────────────────

def parse_ofac(sdn, alt=b""):
    """SDN.CSV (no header: ent_num, name, type, programme, title, ..., remarks)
    with ALT.CSV (ent_num, alt_num, type, name, remarks)."""
    others = {}
    for r in csv.reader(io.StringIO(alt.decode("utf-8", "replace"))):
        if len(r) >= 4 and _clean(r[3]):
            others.setdefault(r[0].strip(), []).append(_clean(r[3]))
    out = []
    for r in csv.reader(io.StringIO(sdn.decode("utf-8", "replace"))):
        if len(r) < 12 or not _clean(r[1]):
            continue
        sdn_type = _clean(r[2]).lower()
        if sdn_type in ("vessel", "aircraft"):
            continue
        person = sdn_type == "individual"
        remarks = _clean(r[11])
        listed = _clean(r[1])
        say = _given_surname if person else (lambda n: n)
        dobs = [d for d in (_dob(m) for m in re.findall(r"DOB ([^;]+)", remarks)) if d]
        countries = re.findall(r"(?:nationality|citizen) ([^;.]+)", remarks)
        births = re.findall(r"POB ([^;]+)", remarks)
        countries += [b.split(",")[-1] for b in births]
        out.append(_profile("ofac", r[0].strip(), "person" if person else "entity", say(listed),
                            [say(a) for a in others.get(r[0].strip(), [])], dobs, countries,
                            "; ".join(_uniq(births + re.findall(r"(?:nationality|citizen) ([^;.]+)", remarks))),
                            _clean(r[3]), "", f"OFAC SDN, programme {_clean(r[3]) or 'not given'}. {remarks}"))
    return out


def _t(el, path):
    return _clean(el.findtext(path) or "")


def parse_un(xml):
    root = ET.fromstring(xml)
    out = []
    for kind, tag, alias_tag, addr_tag in (("person", "INDIVIDUALS/INDIVIDUAL", "INDIVIDUAL_ALIAS", "INDIVIDUAL_ADDRESS"),
                                           ("entity", "ENTITIES/ENTITY", "ENTITY_ALIAS", "ENTITY_ADDRESS")):
        for e in root.findall(tag):
            name = " ".join(x for x in (_t(e, p) for p in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")) if x)
            if not name:
                continue
            aka = [_t(a, "ALIAS_NAME") for a in e.findall(alias_tag) if _t(a, "QUALITY").lower() != "low"]
            dobs = []
            for d in e.findall("INDIVIDUAL_DATE_OF_BIRTH"):
                if _t(d, "TYPE_OF_DATE").upper() == "BETWEEN" and _t(d, "FROM_YEAR"):
                    dobs.append(_dob(f"{_t(d, 'FROM_YEAR')} to {_t(d, 'TO_YEAR') or _t(d, 'FROM_YEAR')}"))
                else:
                    dobs.append(_dob(_t(d, "DATE")) or _dob(_t(d, "YEAR")))
            nats = [_t(v, ".") for v in e.findall("NATIONALITY/VALUE")]
            homes = [_t(a, "COUNTRY") for a in e.findall(addr_tag)]
            births = [_t(b, "COUNTRY") for b in e.findall("INDIVIDUAL_PLACE_OF_BIRTH")]
            out.append(_profile("un", _t(e, "REFERENCE_NUMBER") or _t(e, "DATAID"), kind, name, aka, [d for d in dobs if d],
                                nats + births + homes, "; ".join(_uniq(nats + homes)), _t(e, "UN_LIST_TYPE"), _t(e, "LISTED_ON"),
                                f"UN {_t(e, 'UN_LIST_TYPE')} sanctions ({_t(e, 'REFERENCE_NUMBER')}). {_t(e, 'COMMENTS1')}",
                                _t(e, "REFERENCE_NUMBER")))
    return out, (root.get("dateGenerated") or "")[:10]


def _uk_name(n):
    given = " ".join(x for x in (_t(n, f"Name{i}") for i in range(1, 6)) if x)
    return f"{given} {_t(n, 'Name6')}".strip()


def _uk_date(text):
    d = _dob(text)
    return d["date"] if d and d["kind"] == "full" else ""


def parse_uk(xml):
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("Designation"):
        kind = {"individual": "person", "entity": "entity"}.get(_t(e, "IndividualEntityShip").lower())
        if not kind:
            continue                                # ships
        names = e.findall("Names/Name")
        primary = next((n for n in names if _t(n, "NameType") == "Primary Name"), names[0] if names else None)
        if primary is None or not _uk_name(primary):
            continue
        aka = [_uk_name(n) for n in names if n is not primary and "low" not in _t(n, "AliasStrength").lower()]
        dobs = [_dob(x.text) for x in e.iter("DOB")]
        nats = [_t(x, ".") for x in e.iter("Nationality")]
        births = [_t(x, "CountryOfBirth") for x in e.iter("Location")]
        homes = [_t(a, "AddressCountry") for a in e.findall("Addresses/Address")]
        out.append(_profile("uk", _t(e, "UniqueID"), kind, _uk_name(primary), aka, [d for d in dobs if d], nats + births + homes,
                            "; ".join(_uniq(nats + homes)), _t(e, "RegimeName"), _uk_date(_t(e, "DateDesignated")),
                            f"{_t(e, 'RegimeName')}: {_t(e, 'SanctionsImposed')}. {_t(e, 'OtherInformation')}", _t(e, "UNReferenceNumber")))
    return out, _uk_date(_t(root, "DateGenerated"))


def parse_eu(xml):
    root = ET.fromstring(xml)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    out = []
    for e in root.findall(ns + "sanctionEntity"):
        st = e.find(ns + "subjectType")
        kind = {"person": "person", "enterprise": "entity"}.get(st.get("code") if st is not None else "")
        if not kind:
            continue
        names = [a.get("wholeName", "").strip() for a in e.findall(ns + "nameAlias")
                 if a.get("wholeName", "").strip() and a.get("strong", "true") != "false"]
        if not names:
            continue
        dobs = []
        for b in e.findall(ns + "birthdate"):
            if b.get("birthdate"):
                dobs.append(_dob(b.get("birthdate")))
            elif b.get("year"):
                dobs.append(_dob(b.get("year")))
            elif b.get("yearRangeFrom"):
                dobs.append(_dob(f"{b.get('yearRangeFrom')} to {b.get('yearRangeTo') or b.get('yearRangeFrom')}"))
        nats = [c.get("countryDescription", "") for c in e.findall(ns + "citizenship")]
        births = [b.get("countryDescription", "") for b in e.findall(ns + "birthdate")]
        homes = [a.get("countryDescription", "") for a in e.findall(ns + "address")]
        reg = e.find(ns + "regulation")
        programme = reg.get("programme", "") if reg is not None else ""
        remark = " ".join(_clean(r.text) for r in e.findall(ns + "remark"))
        out.append(_profile("eu", e.get("euReferenceNumber") or e.get("logicalId", ""), kind, names[0], names[1:],
                            [d for d in dobs if d], nats + births + homes, "; ".join(_uniq([_country(x) for x in nats + homes])),
                            programme, (reg.get("entryIntoForceDate", "") if reg is not None else "")[:10],
                            f"EU sanctions, programme {programme or 'not given'}. {remark}", e.get("unitedNationId", "")))
    return out, (root.get("generationDate") or "")[:10]


# ── downloading ──────────────────────────────────────────────────────────────

def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "sanctions-screening/1.0", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if (r.headers.get("Content-Encoding") or "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            return body
    except urllib.error.HTTPError as exc:
        raise ListError(f"the publisher answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, EOFError) as exc:
        raise ListError(f"no answer ({type(exc).__name__}: {str(exc)[:120]})") from exc


def fetch(cfg, key):
    """(raw bytes, profiles, the list's own date) for one list."""
    t = int(cfg.get("timeout") or DEFAULTS["timeout"])
    if key == "ofac":
        sdn = _get(cfg.get("ofac_url") or DEFAULTS["ofac_url"], t)
        alt = _get(cfg.get("ofac_alt_url") or DEFAULTS["ofac_alt_url"], t) if (cfg.get("ofac_alt_url") or DEFAULTS["ofac_alt_url"]) else b""
        return sdn + alt, parse_ofac(sdn, alt), ""
    raw = _get(cfg.get(key + "_url") or DEFAULTS[key + "_url"], t)
    try:
        profiles, published = {"un": parse_un, "uk": parse_uk, "eu": parse_eu}[key](raw)
    except ET.ParseError as exc:
        raise ListError(f"the file is not the list's XML ({exc})") from exc
    return raw, profiles, published


def _path(name):
    return os.path.join(DIR, name)


def stored(key):
    """The downloaded list (meta and profiles), or None; read once per file version."""
    p = _path(key + ".json")
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return None
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(p, encoding="utf-8") as fh:
        data = json.load(fh)
    _cache[key] = (mtime, data)
    _cache.pop("_index", None)
    return data


def _write(name, data):
    os.makedirs(DIR, exist_ok=True)
    tmp = _path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, _path(name))


def status():
    try:
        with open(_path("status.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def lists(cfg):
    """Every list as the pages show it: used or not, downloaded when, how many
    records, the last change, the last error."""
    st = status()
    out = []
    for key, meta in LISTS.items():
        d = stored(key)
        s = st.get(key) or {}
        out.append(dict(meta, key=key, used=key in enabled(cfg), downloaded=bool(d),
                        fetched_at=(d or {}).get("fetched_at", ""), published=(d or {}).get("published", ""),
                        people=(d or {}).get("people", 0), entities=(d or {}).get("entities", 0),
                        sha256=(d or {}).get("sha256", ""), checked_at=s.get("checked_at", ""), error=s.get("error", ""),
                        added=s.get("added", 0), removed=s.get("removed", 0), changed_at=s.get("changed_at", "")))
    return out


def ready(cfg):
    """Can a name be screened: at least one used list downloaded?"""
    return any(stored(k) for k in enabled(cfg))


def versions(cfg):
    """The downloads a screening is made against, kept with it."""
    return {k: {"fetched_at": d["fetched_at"], "published": d.get("published", ""), "sha256": d["sha256"][:16]}
            for k in enabled(cfg) for d in [stored(k)] if d}


def age_hours(cfg):
    """Hours since the oldest used list was downloaded (None: none downloaded)."""
    at = [d["fetched_at"] for k in enabled(cfg) for d in [stored(k)] if d]
    if not at:
        return None
    return (time.time() - time.mktime(time.strptime(min(at), "%Y-%m-%d %H:%M:%S"))) / 3600


def update(cfg, keys=None):
    """Download the used lists (or `keys`) again; a list whose file is
    unchanged is left as it is. Returns {key: {changed, added, removed,
    people, error}}. One update at a time."""
    if not _LOCK.acquire(blocking=False):
        raise ListError("The lists are being downloaded already.")
    try:
        st, out = status(), {}
        for key in keys or enabled(cfg):
            at = dates.now_str()
            entry = dict(st.get(key) or {}, checked_at=at, error="")
            try:
                raw, profiles, published = fetch(cfg, key)
            except ListError as exc:
                entry["error"] = str(exc)
                out[key] = {"changed": False, "added": 0, "removed": 0, "error": entry["error"]}
                st[key] = entry
                continue
            digest = hashlib.sha256(raw).hexdigest()
            old = stored(key)
            if old and old["sha256"] == digest:
                out[key] = {"changed": False, "added": 0, "removed": 0, "error": "", "people": old.get("people", 0)}
                st[key] = entry
                continue
            if not profiles:
                entry["error"] = "the file held no records: the old download is kept"
                out[key] = {"changed": False, "added": 0, "removed": 0, "error": entry["error"]}
                st[key] = entry
                continue
            before = {p["uid"] for p in (old or {}).get("profiles", [])}
            now = {p["uid"] for p in profiles}
            added, removed = sorted(now - before) if old else [], sorted(before - now)
            _write(key + ".json", {"key": key, "fetched_at": at, "published": published, "sha256": digest,
                                   "people": sum(1 for p in profiles if p["type"] == "person"),
                                   "entities": sum(1 for p in profiles if p["type"] == "entity"), "profiles": profiles})
            entry.update(changed_at=at, added=len(added), removed=len(removed), added_ids=added[:50], removed_ids=removed[:50])
            st[key] = entry
            out[key] = {"changed": True, "added": len(added), "removed": len(removed), "error": "",
                        "people": sum(1 for p in profiles if p["type"] == "person"), "first": not old}
        _write("status.json", st)
        return out
    finally:
        _LOCK.release()


# ── the name search ──────────────────────────────────────────────────────────

def _matchable(name):
    """A name the search may score: one word of two letters or more (a
    Cyrillic or Arabic name with a stray Latin letter reads as initials)."""
    return any(len(w) > 1 for w in watchlist._words(name))


def _profiles(cfg, kind):
    return [p for k in enabled(cfg) for d in [stored(k)] if d for p in d["profiles"] if p["type"] == kind]


def _index(cfg, kind):
    """The words of every listed name, each with the records whose names have
    it, so a search scores only the records sharing a near word with the
    name searched for (the same near words name_score counts)."""
    key = (tuple(enabled(cfg)), kind, tuple(stored(k)["sha256"] if stored(k) else "" for k in enabled(cfg)))
    hit = _cache.get("_index")
    if hit and hit[0] == key:
        return hit[1]
    profs = _profiles(cfg, kind)
    words = {}
    for i, p in enumerate(profs):
        for n in p["names"]:
            if _matchable(n):
                for w in watchlist._words(n):
                    words.setdefault(w, set()).add(i)
    by_first = {}
    for w in words:
        by_first.setdefault(w[:1], []).append(w)
    built = (profs, words, by_first)
    _cache["_index"] = (key, built)
    return built


def _near_words(w, words, by_first):
    """The listed words name_score gives some credit against w: an initial
    the words it starts; a word, the words of its first letter it scores
    against, and those of another first letter but the same second and third
    letters and a near length (a C/K or I/Y start). On 8 hard searches
    (Cyrillic, words shuffled, a middle name dropped, a letter changed) it
    found every record that scoring all 16,832 people did."""
    if len(w) == 1:
        return [x for x in by_first.get(w, [])]
    out = [x for x in by_first.get(w[:1], []) if watchlist._word_score(w, x) > 0]
    out += [x for x in words if x[:1] != w[:1] and len(w) >= 4 and abs(len(x) - len(w)) <= 2 and len(x) >= 4
            and x[1:3] == w[1:3] and watchlist._word_score(w, x) > 0]
    return out


def _years(p):
    years = set()
    for d in p["dobs"]:
        if d.get("kind") == "full":
            years.add(int(d["date"][:4]))
        elif d.get("kind") == "year":
            years.add(d["year"])
        elif d.get("kind") == "range":
            years.update(range(d["year"], d["year_to"] + 1))
    return years


def _same_people(found):
    """The found records in groups, one a person: the same UN reference, or
    the same full date of birth and a name alike (90 or more) between them
    (the EU lists Putin under his Cyrillic name, the UK and OFAC in Latin),
    or the same name and a birth year in common (the UN and the EU give only
    years for some)."""
    parent = list(range(len(found)))

    def top(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[top(i)] = top(j)
    by_ref, by_date, by_name = {}, {}, {}
    for i, (_, p) in enumerate(found):
        if p["un_ref"]:
            by_ref.setdefault(p["un_ref"], []).append(i)
        by_name.setdefault(tuple(sorted(watchlist._words(p["name"]))), []).append(i)
        for d in p["dobs"]:
            if d.get("kind") == "full":
                by_date.setdefault(d["date"], []).append(i)
    for same in by_ref.values():
        for i in same[1:]:
            join(i, same[0])
    for same in by_date.values():
        for a in range(len(same)):
            for b in range(a + 1, len(same)):
                i, j = same[a], same[b]
                if top(i) != top(j) and found[i][1]["list"] != found[j][1]["list"] and any(
                        watchlist.name_score(x, y) >= 90 for x in found[i][1]["names"][:8] for y in found[j][1]["names"][:8]):
                    join(i, j)
    for same in by_name.values():
        for a in range(len(same)):
            for b in range(a + 1, len(same)):
                i, j = same[a], same[b]
                if top(i) != top(j) and found[i][1]["list"] != found[j][1]["list"] and _years(found[i][1]) & _years(found[j][1]):
                    join(i, j)
    groups = {}
    for i, f in enumerate(found):
        groups.setdefault(top(i), []).append(f)
    return list(groups.values())


def search(person, cfg, threshold=65, limit=5, bands=None, kind="person"):
    """The listed records whose name scores `threshold` or more against the
    name, best first: a person on several lists is one hit naming them all
    (_same_people). At most `limit` hits."""
    name = (person.get("name") or "").strip()
    if not _matchable(name) or not ready(cfg):
        return []
    profs, words, by_first = _index(cfg, kind)
    cand = set()
    for w in watchlist._words(name):
        for x in _near_words(w, words, by_first):
            cand |= words[x]
    found = []
    for i in cand:
        p = profs[i]
        score = max(watchlist.name_score(name, n) for n in p["names"] if _matchable(n))
        if score >= threshold:
            found.append((score, p))
    hits = []
    for members in _same_people(found):
        members.sort(key=lambda t: (-t[0], ORDER.index(t[1]["list"])))
        score, lead = members[0]
        everyone = sorted({m["list"] for _, m in members}, key=ORDER.index)
        dobs = _uniq([d for _, m in members for d in m["dobs"]])
        countries = _uniq([c for _, m in members for c in m["countries"]])
        hits.append({
            "uid": lead["uid"], "name": lead["name"], "aka": _uniq([a for _, m in members for a in m["names"] if a != lead["name"]])[:8],
            "dob_text": "; ".join(_dob_text(d) for d in dobs[:4]) or "Not listed",
            "places": lead["places"] or "; ".join(countries) or "Not listed",
            "category": "Sanctions", "lists": [LISTS[k]["short"] for k in everyone],
            "list_ids": sorted(m["uid"] for _, m in members),
            "programme": lead["programme"], "listed_on": lead["listed_on"],
            "narrative": " | ".join(f"{LISTS[m['list']]['short']}: {m['narrative']}" for _, m in members[:3])[:1200],
            "score": score, "strength": watchlist.strength(score, bands),
            "dob_result": _dob_result(person.get("dob", ""), dobs),
            "country_result": _country_result(countries, person), "source": SOURCE, "row": ""})
    rank = {"Matched": 0, "Unknown": 1, "Not matched": 2}
    hits.sort(key=lambda h: (-h["score"], rank[h["dob_result"]], rank[h["country_result"]], h["uid"]))
    return hits[:limit]


def all_ids(cfg):
    """Every record ID on the used, downloaded lists (to tell a record taken off)."""
    return {p["uid"] for k in enabled(cfg) for d in [stored(k)] if d for p in d["profiles"]}


def rescreen(person, known, cfg, threshold=65, limit=5, bands=None, kind="person"):
    """A watched person screened again on today's lists: (the hits now, the
    hits with a record not seen before, the known records no longer listed)."""
    hits = search(person, cfg, threshold, limit, bands, kind)
    known = set(known or ())
    new = [h for h in hits if set(h["list_ids"]) - known]
    listed = all_ids(cfg)
    loaded = {LISTS[k]["short"] for k in enabled(cfg) if stored(k)}
    gone = sorted(u for u in known if u not in listed and u.split("-", 1)[0] in loaded)
    return hits, new, gone
