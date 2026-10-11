"""Fresh copies of the seed for boot and for reset.

SEED_VERSION is stamped in the state store at boot, together with the case
book. Bump it whenever a builder's output shape changes — a stored record
from an older shape would be missing keys the templates read, and clearing
the store is the honest answer.

Two case books (CONSOLE_CASES in the environment picks one; app.py reads it):
"file", the default, is the 1,000 cases of the reconciliation log
(fincrime/data/recon_book.py); "demo" is the nineteen scripted scenarios and
the filler rows the test suite and the original walkthrough use.
"""
from fincrime.data.seed import assemble

SEED_VERSION = "2026-10-11.1"
BOOKS = ("file", "demo")
DEFAULT_BOOK = "file"


def book_from(value):
    """The case book a setting names; anything unknown is the default."""
    value = (value or "").strip().lower()
    return value if value in BOOKS else DEFAULT_BOOK


def load_seed(book=DEFAULT_BOOK):
    """(analysts, kyc_cases, alert_cases, wc_cases) as brand-new objects."""
    return assemble(book_from(book))


def index_by_id(records):
    return {r["id"]: r for r in records}
