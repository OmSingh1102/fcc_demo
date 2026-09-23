# FinCrime KYC/KYB Operations Hub — demo

A Straive demo of a unified back-office case-management hub for creator and
seller KYC/KYB: document confirmation, name screening against a simulated
World-Check console, L1 → L2 → EDD escalation, SLA clocks, audit trail and
analytics. Built the same way as the ChargeShield demo: one Flask `app.py`,
Jinja templates, a single stylesheet, a SQLite state store, no JS framework.

All people, companies, documents and screening records are fictional. The
identity documents are drawn as SVGs from the seed data and carry a
"SPECIMEN" watermark.

## Run

```
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:8010 — sign in with any analyst profile and the demo
password shown on the card (`1234`).

Always run through the project `.venv`: the Anaconda Python on this machine has
a broken `_sqlite3` and the plain Python 3.13 has no Flask.

## Tests

```
.venv\Scripts\python.exe -m unittest -v
```

## Layout

| Path | What lives there |
|---|---|
| `app.py` | Flask app: sign-in, tenant switch, thin routes, state glue |
| `fincrime/data/` | vocabularies, seed builders, the 16 scenarios, loader, SQLite state store |
| `fincrime/engines/` | KYC workflow state machine, name-screening, World-Check logic, SLA, segregation, PDF export |
| `fincrime/documents/` | synthetic ID / proof-of-address SVG cards |
| `fincrime/analytics/` | view-model builders for the list, queues and dashboard |
| `fincrime/adapters/` | mock IDV vendor, in-house CMS and Skopenow |
| `templates/` | flat Jinja templates; `_name.html` are partials/macros |
| `static/css/style.css` | the one stylesheet (light console + dark `body.wc-theme`) |
| `tests/` | end-to-end flow tests on the Flask test client |

Reset the demo from the header at any time; it clears the state store and
reloads the seed.
