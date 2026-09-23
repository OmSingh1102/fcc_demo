"""Fresh copies of the seed for boot and for reset.

SEED_VERSION is stamped in the state store at boot. Bump it whenever a
builder's output shape changes — a stored record from an older shape would be
missing keys the templates read, and clearing the store is the honest answer.
"""
from fincrime.data.seed import assemble

SEED_VERSION = "2026-09-24.1"


def load_seed():
    """(analysts, kyc_cases, alert_cases, wc_cases) as brand-new objects."""
    return assemble()


def index_by_id(records):
    return {r["id"]: r for r in records}
