# FinCrime KYC/KYB Operations Hub — demo

A Straive demo of a unified back-office case-management hub for creator and
seller KYC/KYB. It reproduces the client's as-is screens — the internal case
manager and a simulated World-Check console — driven by the SOP's L1 → L2 →
L3 workflow, and adds the "Unified Back-Office Case Management" layer the
SOP proposes (§5.2): automated skill-based routing, case on-demand with
capacity, a live tier pipeline with hand-off lag, tracker views that replace
the spreadsheets, an investigation file per escalation, a global audit log,
QC sampling with a scorecard, and a four-eyes Checker 2 on seller approvals.

Built the same way as the ChargeShield demo: one Flask `app.py`, Jinja
templates, a single stylesheet, a SQLite state store, no JS framework.

All people, companies, documents and screening records are fictional. The
identity documents are drawn as SVGs from the seed data and carry a
"SPECIMEN" watermark. Vendor names appear as text labels only.

Links that open the World-Check console, from the in-house CMS case, its
Alert Outcome dialog and the Audit Log, open it in a new tab marked with a
small arrow-box icon, so the screening case stays where the analyst left it.
Every other link stays in the same tab.

## Run

```
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:8010 — sign in with any analyst profile and the demo
password shown on the card (`1234`). Always run through the project `.venv`:
the Anaconda Python on this machine has a broken `_sqlite3` and the plain
Python 3.13 has no Flask.

## Tests

```
.venv\Scripts\python.exe -W error::ResourceWarning -m unittest -v
```

31 end-to-end tests on the Flask test client: the golden path, resubmit,
escalate, segregation of duties, L2/EDD decisions, Skopenow, TT Shop risk
recalculation, routing by skill and capacity, case on-demand, immediate
hand-offs, capacity overrides, trackers and CSV, the investigation-file ZIP,
the global audit log, QC sampling, Checker 2, role enforcement at EDD, POA
checks, fraud typology, and World-Check links opening in a new tab.

## Analyst profiles

| Profile | Roles | Tenants | Skill book | Capacity |
|---|---|---|---|---|
| Amara Iyer | L1 | TT Live | latin, cyrillic | 6 |
| Jon Miranda | L1 | TT Live, TT Shop | latin, arabic, KYB | 6 |
| Mario Kim | L1 + L2 | both | latin, KYB | 5 |
| Nisha Rao | L2 | both | latin, cyrillic, arabic, KYB | 4 |
| Ryan Lee | EDD (L3 / PIC) | both | all scripts, KYB | 3 |
| Leah Fernandez | QC / team lead | both | — (takes no cases) | 0 |

The header's analyst switcher jumps between profiles without signing out.

## A demo script

1. **Amara** → *Operations Hub › My Work* → **Get next case**: the router picks
   the most urgent case her skill book allows and opens it, reserved. The
   header shows the routing chip and the reason.
2. Open **Dmitri Volkov** (Russian passport, Russian proof of address) →
   *Review*: the Data Confirm modal shows the POA checks; two fail, OK stays
   off, **Escalate** preselects the sanctioned-country reason. Escalate with
   a fraud typology → the case is handed to L2 at once; the flash names who.
3. Open **Daniel Mercer** for the as-is golden path: Reserve → confirm the
   three fields and the POA → screening case → World-Check resolve + export
   → alert and case outcome → EDD Review → Verified.
4. **Nisha** → *My Work* shows the hand-off; *Pipeline* shows the L2 column
   and the hand-off feed with lag 0 s against the bot-era history.
5. **Jon**, tenant TT Shop → a seller in Data Screening → Recalculate Risk
   Rating → EDD Review "No match - Approve" → the seller waits for
   **Checker 2**; Jon cannot sign it off. **Nisha** → L2 / EDD Queue → the
   Checker 2 row → Review → Approve → Verified.
6. *Trackers*: the Productivity / Time, Fraud and EDD / TT Shop Escalation
   trackers, filled by the system, with CSV. Open an escalated case's
   **Investigation File** and download the ZIP.
7. **Leah** → *QC Sampling* → fail one sampled case with a reason → the
   closing analyst's My Work shows the feedback to acknowledge. *Routing*:
   lower an L2's capacity to 1, escalate another case, watch it wait for
   capacity, raise it, **Route selected now**.
8. *Analytics*: tier pipeline, backlog ageing, shift progress, hand-off lag,
   quality scorecard. *Audit Log*: one stream across every record.
9. **Reset demo** in the header brings the seeded case book back.

## Layout

| Path | What lives there |
|---|---|
| `app.py` | Flask app: sign-in, tenant switch, thin routes, state glue, the Operations Hub routes |
| `fincrime/data/` | vocabularies, seed builders, the 19 scenarios, loader, SQLite state store |
| `fincrime/engines/` | KYC workflow state machine, routing (skill book, capacity, hand-offs), work log, name-screening, World-Check logic, SLA, segregation, QC sampling, investigation file, PDF export |
| `fincrime/documents/` | synthetic ID / proof-of-address SVG cards |
| `fincrime/analytics/` | view-model builders: case list, queues, My Work, pipeline, trackers, audit log, routing console, dashboard |
| `fincrime/adapters/` | mock IDV vendor, in-house CMS and Skopenow |
| `templates/` | flat Jinja templates; `_name.html` are partials/macros |
| `static/css/style.css` | the one stylesheet (light console + dark `body.wc-theme`) |
| `tests/` | end-to-end flow tests on the Flask test client |

## How the hub maps to the SOP

| SOP | Where |
|---|---|
| §2.1 QC sampling, scorecards, coaching | QC Sampling page, scorecard on Analytics, feedback on My Work |
| §3.1 SLAs 48 h / 14 d | SLA chips, breach KPIs, pipeline flags |
| §4.1.2 Data Confirming, POA checks, resubmit reasons | Data Confirm modal |
| §4.1.3 screening, WC export, Skopenow, escalation, fraud typology, EDD tracker, investigation folder | screening case, World-Check console, EDD Review, Escalate dialog, Trackers, Investigation File |
| §4.2 TT Shop Checker 1 / Checker 2, risk rating, Pending EDD | Agency panel, EDD Review, Checker 2 sign-off, L2 / EDD queue |
| §5.2.1 automated routing, no spreadsheets | routing engine on every hand-off, Routing console, Trackers |
| §5.2.2 dynamic capacity, case on-demand | My Work (Get next case / Request cases), capacity per analyst |
| §5.2.3 L1 → L2 → L3, real-time pipeline, no hand-off lag | Pipeline page, hand-off feed, lag metric |
| §5.2.4 live dashboards, audit logs | Analytics, Audit Log, live refresh on every page |

The state store keeps every action across restarts; a change to the seed's
shape bumps `SEED_VERSION` and clears it. Uploads are never stored — only
the file name is echoed into the audit trail.
