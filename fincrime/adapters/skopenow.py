"""Mock open-source-intelligence report for the US-person path (SOP 4.1.3,
step 4.2.1). A request is recorded, and completing it produces a short
comparison the analyst reads against the watchlist record — name, relatives,
location history and public records, the four things the SOP says to compare.
Everything is invented from the case's own data."""
from fincrime.utils import dates


def request_report(case, actor):
    return {"status": "Requested", "requested_at": dates.now_str(), "requested_by": actor,
            "report": None, "outcome": "", "reviewed_by": "", "reviewed_at": "", "notes": ""}


def complete_report(record, outcome, actor, notes):
    c_name = record.get("subject") or ""
    record = dict(record)
    record.update({
        "status": outcome, "outcome": outcome, "reviewed_by": actor, "reviewed_at": dates.now_str(), "notes": notes,
        "report": {
            "generated_at": dates.now_str(),
            "sections": [
                ("Name & aliases", "Legal name only; no aliases or alternate spellings found in public records."),
                ("Relatives & associates", "Two immediate family members identified; none appear on any watchlist."),
                ("Location history", "Consistent residence history in the state of the driving licence for the last 9 years."),
                ("Public records", "No criminal filings, liens or judgments. Two professional licence records, both current."),
                ("Adverse media", "No press mentions linked to the subject's identifiers."),
            ],
        },
    })
    return record
