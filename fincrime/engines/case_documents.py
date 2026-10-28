"""Real document images arriving on a case: which document row each image
fills, and what the case does when they land. The route (app.py) reads the
files; documents/uploads.py checks, cleans and stores them.

An uploaded image replaces the drawn one in its slot (the row keeps its id,
so every link to it still works) and carries `upload`: where the file is,
who sent it and when. The ID vendor never saw the new image, so its result
becomes "Not run". A case waiting for a resubmission is back in Data
Confirming. A case in Data Confirming sets the agent's earlier read aside
(ai_agent_history), so the AI Agent reads the new images when the case is
its to take."""
from fincrime.data import vocab
from fincrime.documents import uploads
from fincrime.engines import workflow
from fincrime.engines.errors import WorkflowError
from fincrime.utils import dates

UPLOADED = "Documents uploaded"
RECEIVED = "Documents received"
PASSIVE_ACTIONS = (UPLOADED, RECEIVED)      # a person sent images; they did not work the case (ai_agent.eligible)
HISTORY_KEPT = 5

_NEW_ROW = {
    "passport": {"name": "Passport", "category": "Passport", "kind": "passport", "side": "front"},
    "passport_back": {"name": "Passport", "category": "Passport", "kind": "passport", "side": "back"},
    "secondary": {"name": "Secondary ID", "category": "NationalID", "kind": "national_id", "side": "front"},
    "poa": {"name": "Proof of address", "category": "ProofOfAddress", "kind": "utility_bill", "side": "page 1"},
}


def slot_row(case, slot):
    """The document row a slot fills, or None."""
    docs = case.get("documents", [])
    if slot == "passport":
        return next((d for d in docs if d.get("category") == "Passport" and d.get("side") != "back"), None)
    if slot == "passport_back":
        return next((d for d in docs if d.get("category") == "Passport" and d.get("side") == "back"), None)
    if slot == "secondary":
        return next((d for d in docs if d.get("category") not in ("Passport", "ProofOfAddress")), None)
    return next((d for d in docs if d.get("category") == "ProofOfAddress"), None)


def has_uploads(case):
    return any(d.get("upload") for d in case.get("documents", []))


def poa_details(form, case):
    """The proof of address's type, issue date and country from the upload
    form, checked. The date may be left empty: the agent then takes the one
    it reads off the document."""
    row = slot_row(case, "poa") or {}
    kind = (form.get("poa_kind") or row.get("kind") or "").strip()
    if kind not in vocab.ACCEPTED_POA_TYPES and kind != "other":
        raise WorkflowError("Choose the proof of address's type.")
    issued = (form.get("poa_issued_on") or "").strip()
    if issued and dates.parse(issued) is None:
        raise WorkflowError("The proof of address's issue date must be a date (YYYY-MM-DD).")
    country = (form.get("poa_country") or row.get("country") or case["client"].get("nationality") or "").strip().upper()
    if country not in vocab.COUNTRY_NAMES:
        raise WorkflowError("Choose the country that issued the proof of address.")
    return {"kind": kind, "issued_on": issued[:10], "country": country}


def attach(case, images, actor, poa=None):
    """Put prepared images (slot -> (jpeg, info, original file name)) on the
    case; `poa` is poa_details() when a proof of address is among them.
    Returns the labels of the slots filled."""
    _require_open(case)
    now = dates.now_str()
    filled = []
    for slot, _label in uploads.SLOTS:
        if slot not in images:
            continue
        jpeg, info, original = images[slot]
        row = slot_row(case, slot)
        if row is None:
            row = dict(_NEW_ROW[slot], id=_next_id(case))
            case["documents"].append(row)
        previous = (row.get("upload") or {}).get("path", "")
        path = uploads.store(case["id"], row["id"], jpeg, previous=previous)
        row.pop("hub_file", None)
        row["quality"] = "ok"
        row["upload"] = {"path": path, "media_type": info["media_type"], "sha256": info["sha256"],
                         "width": info["width"], "height": info["height"], "original_name": _display_name(original),
                         "by": actor, "at": now}
        if slot == "poa" and poa:
            row.update(kind=poa["kind"], country=poa["country"], issued_on=poa["issued_on"],
                       name="Proof of address — " + vocab.ACCEPTED_POA_TYPES.get(poa["kind"], "other document"))
            row["issued_on_source"] = "upload" if poa["issued_on"] else ""
        filled.append(uploads.SLOT_LABELS[slot])
    if not filled:
        raise WorkflowError("Choose at least one image to upload.")
    if "passport" in images:
        case["vendor_check"].update(result="Not run", reason="", checked_at="", extracted={},
                                    vendor_reason="The ID image was uploaded in the console; no ID vendor checked it.")
    names = ", ".join(n for n in (_display_name(images[s][2]) for s, _ in uploads.SLOTS if s in images) if n)
    workflow._audit(case, actor, UPLOADED, f"{', '.join(filled)} uploaded as image(s)" + (f" ({names})" if names else "") + ".")
    case["documents_uploaded_at"] = now
    if case["status"].startswith("Resubmit"):
        case["status"] = "DataConfirming"
        case["pending_reason"] = ""
        workflow._audit(case, actor, RECEIVED, "The customer's new documents arrived; the case is back in Data Confirming.")
    if case["status"] == "DataConfirming" and case.get("ai_agent"):
        history = case.setdefault("ai_agent_history", [])
        history.append(case.pop("ai_agent"))
        del history[:-HISTORY_KEPT]
    return filled


def date_from_read(case, got):
    """An uploaded proof of address whose issue date nobody typed takes the
    one Claude read off it, so the proof-of-address checks have a date."""
    rows = workflow.poa_docs(case)
    row = rows[0] if rows else None
    read = ((got or {}).get("poa") or {}).get("issued_on", "")
    if row and row.get("upload") and not row.get("issued_on") and dates.parse(read):
        row["issued_on"] = read[:10]
        row["issued_on_source"] = "read"


def _require_open(case):
    if case["status"] in vocab.CLOSED_STATUSES:
        raise WorkflowError("The case is closed; documents can only be added to an open case.")
    if case.get("agency"):
        raise WorkflowError("Image upload takes an individual's documents (passport, secondary ID, proof of address).")


def _next_id(case):
    nums = [int(d["id"][1:]) for d in case.get("documents", []) if str(d.get("id", ""))[1:].isdigit()]
    return f"d{max(nums, default=0) + 1}"


def _display_name(name):
    """A file name as the analyst's computer gave it, shown only: no path,
    printable, short."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(ch for ch in name if ch.isprintable())[:120]
