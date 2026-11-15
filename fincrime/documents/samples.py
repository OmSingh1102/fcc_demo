"""Sample IDs for the demo: made-up documents drawn by documents/svg_cards,
each with a SPECIMEN watermark, a grey silhouette for a photo and "Not a
real document" printed on it, so nobody has to upload a real person's ID.

Each sample shows one thing the console does: a clean passport that closes
by itself, a name on the watchlist (a sanctions record, a PEP, an adverse
media name with another date of birth), an expired passport, a holder under
the age limit, a printed date of birth that differs from the MRZ, a blurred
photo, a US driving licence, and a document that is not an ID. A sample
goes through the console exactly as an upload does (the AI reads it, the
checks run, the name is screened, the AI decides each hit): only the image
is the console's. Didit's ID verification declines every drawn one (no
real photo, no real document template), so with Didit's check on a sample
always goes to an analyst; with it off, each does what its card says. Dates
are drawn from today's date, so the clean ones stay
in date and the under-age holder stays under the limit. The made-up names
match no record of the stand-in watchlist; the three listed names are
records of it.

One sample is a photo, not a drawing: the sample ID card Nebraska's DMV
publishes (holder SAMPLECARD, JOHN ALEXANDER), kept in sample_images/. It
has a real photo and a real card design, so it is the one to show Didit's
check on; its fields are written below as the card prints them.
"""
from datetime import date
from functools import lru_cache
from pathlib import Path

from fincrime.documents import raster, svg_cards

SAMPLES = (
    {"id": "clean-passport", "title": "Clean passport", "group": "Passes",
     "shows": "Every check passes and the name matches no record.",
     "expect": "With Didit's check off, it closes by itself (auto-verify). With it on, Didit declines it (a made-up document) and an analyst confirms.",
     "kind": "passport", "name": "Elena Marie Castellano", "nationality": "US", "gender": "F", "dob": "1989-04-17",
     "number": "X48213976", "address": "1842 Larkspur Lane, Sacramento, CA 95822"},
    {"id": "driving-licence", "title": "US driving licence", "group": "Passes",
     "shows": "A card with no machine-readable zone: the fields are read from the print alone.",
     "expect": "No watchlist match; the checks pass.",
     "kind": "driving_licence", "name": "Daniel Robert Ashford", "nationality": "US", "gender": "M", "dob": "1986-09-12",
     "number": "D7315528", "address": "77 Harbor View Road, Portland, OR 97205"},
    {"id": "nebraska-id-card", "title": "Nebraska ID card (the state's sample)", "group": "Passes",
     "shows": "The sample card Nebraska's DMV publishes: a real photo and a real card design, no MRZ.",
     "expect": "No watchlist match and the checks pass: with Didit's check off it closes by itself. With it on, Didit judges a real card design with a photo (it may still flag the state's published sample).",
     "kind": "id_card", "name": "John Alexander Samplecard", "nationality": "US", "gender": "M", "dob": "1990-05-25",
     "number": "123456789", "address": "1234 Example St, South Sioux City, SA 12345-0000", "image": "nebraska-id-card.png"},
    {"id": "adverse-media-dob-differs", "title": "Name on the watchlist, another date of birth", "group": "Watchlist",
     "shows": "The name matches an adverse-media record exactly, but the record's date of birth is 25 years earlier.",
     "expect": "The AI should call both hits false positives; with Didit's check off, the rule clears them and closes the case.",
     "kind": "passport", "name": "Sarah Louise Murphy", "nationality": "US", "gender": "F", "dob": "1991-03-14",
     "number": "X60442183", "address": "310 Maple Court, Columbus, OH 43215"},
    {"id": "pep-match", "title": "A politically exposed person", "group": "Watchlist",
     "shows": "The name and birth year match a city council member (PEP Level 3).",
     "expect": "A PEP record always goes to an analyst, whatever the AI says.",
     "kind": "passport", "name": "Veronica Teresa Cruz", "nationality": "US", "gender": "F", "dob": "1960-05-02",
     "number": "X31957740", "address": "905 Pine Street, Seattle, WA 98101"},
    {"id": "sanctions-match", "title": "A sanctions match, among namesakes", "group": "Watchlist",
     "shows": "The name and date of birth match a UN / MHA designated person; four others share the name.",
     "expect": "The AI weighs every hit; the sanctions record goes to an analyst.",
     "kind": "passport", "name": "Abdul Kareem Khan", "nationality": "IN", "gender": "M", "dob": "1988-12-19",
     "number": "Z4471902", "address": "12 Residency Road, Bengaluru, KA 560025"},
    {"id": "expired-passport", "title": "Expired passport", "group": "Fails a check",
     "shows": "The passport's expiry date has passed (it carries an EXPIRED stamp).",
     "expect": "The expiry check fails: the case goes to an analyst.",
     "kind": "passport", "name": "Oliver James Pemberton", "nationality": "GB", "gender": "M", "dob": "1979-08-23",
     "number": "548213097", "address": "14 Elm Grove, Bristol, BS6 6AH", "quality": "expired"},
    {"id": "mrz-mismatch", "title": "Printed date differs from the MRZ", "group": "Fails a check",
     "shows": "The printed date of birth is 02 NOV 1984; the machine-readable zone says 20 NOV 1984: a sign of tampering.",
     "expect": "The MRZ check fails: the case goes to an analyst.",
     "kind": "passport", "name": "Hannah Grace Whitfield", "nationality": "US", "gender": "F", "dob": "1984-11-20",
     "printed_dob": "1984-11-02", "number": "X77120534", "address": "48 Willow Bend, Austin, TX 78701"},
    {"id": "under-age", "title": "Holder under the age limit", "group": "Needs a person",
     "shows": "The holder is 16; Settings warns under the age limit.",
     "expect": "The age check asks an analyst to look.",
     "kind": "passport", "name": "Lucas Andre Moreau", "nationality": "FR", "gender": "M", "age": 16,
     "number": "19FR44821", "address": "8 Rue des Lilas, Lyon, 69003"},
    {"id": "blurred-photo", "title": "Blurred photo", "group": "Needs a person",
     "shows": "The whole card is out of focus, as a shaky phone photo is.",
     "expect": "The AI reports the blur (or cannot read the fields): an analyst looks.",
     "kind": "passport", "name": "Tomas Erik Lindqvist", "nationality": "SE", "gender": "M", "dob": "1992-06-05",
     "number": "91552038", "address": "Storgatan 21, Uppsala, 753 31", "quality": "blurred"},
    {"id": "not-an-id", "title": "Not an ID (a utility bill)", "group": "Needs a person",
     "shows": "An electricity bill sent where an ID was asked for.",
     "expect": "The AI says it is not an identity document: nobody is screened.",
     "kind": "utility_bill", "name": "Priya Anjali Raghavan", "nationality": "IN", "gender": "F", "dob": "1993-01-28",
     "number": "", "address": "21 Lake View Apartments, Pune, MH 411001"},
)
GROUPS = ("Passes", "Watchlist", "Fails a check", "Needs a person")
IMAGES = Path(__file__).with_name("sample_images")


def get(sample_id):
    return next((s for s in SAMPLES if s["id"] == sample_id), None)


def _dob(s, today):
    if s.get("age"):
        try:
            return today.replace(year=today.year - s["age"]).isoformat()
        except ValueError:                           # 29 February
            return today.replace(year=today.year - s["age"], day=28).isoformat()
    return s["dob"]


def svg(sample_id, today=None):
    """The sample drawn, as SVG (for the page's thumbnails); None when there is
    no such sample, or it is a photo (see png)."""
    s = get(sample_id)
    if not s or s.get("image"):
        return None
    today = today or date.today()
    dob = _dob(s, today)
    case = {"client": {"legal_name": s["name"], "nationality": s["nationality"], "gender": s["gender"], "dob": dob,
                       "id_number": s["number"], "address": s["address"]},
            "created_at": today.isoformat() + " 09:00:00",
            "documents": [{"kind": s["kind"], "quality": s.get("quality", "ok"), "side": "front"}]}
    out = svg_cards.render(case, case["documents"][0])
    if s.get("printed_dob"):                          # the printed date changed, the MRZ left as it was
        out = out.replace(svg_cards._long_date(dob), svg_cards._long_date(s["printed_dob"]), 1)
    return out


@lru_cache(maxsize=32)
def _png(sample_id, day):
    s = get(sample_id)
    if s.get("image"):
        return (IMAGES / s["image"]).read_bytes()
    return raster.svg_to_png(svg(sample_id, date.fromisoformat(day)), zoom=1.5)


def png(sample_id):
    """The sample as the image an upload would be (PNG); None when there is no such sample."""
    return _png(sample_id, date.today().isoformat()) if get(sample_id) else None
