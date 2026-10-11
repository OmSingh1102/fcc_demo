# FinCrime KYC/KYB Operations Hub — demo

A Straive demo of a unified back-office case-management hub for creator and
seller KYC/KYB. It reproduces the client's as-is screens — the internal case
manager and a simulated World-Check console — driven by the SOP's L1 → L2 →
L3 workflow, and adds the "Unified Back-Office Case Management" layer the
SOP proposes (§5.2): automated skill-based routing, case on-demand with
capacity, a live tier pipeline with hand-off lag, tracker views that replace
the spreadsheets, an investigation file per escalation, a global audit log,
QC sampling with a scorecard, and a four-eyes Checker 2 on seller approvals.

Screening runs in two workflows. **Auto-verified**: no match on any list, or
every watchlist record cleared by the *AI screening rules*, so the screening
case closes itself and a TT Live case completes with no analyst step.
**Human-in-the-loop**: at least one record the rules could not clear, so an
analyst handles only what is left. The "AI" is a deterministic rule book, not
a model — date-of-birth mismatch, gender mismatch, an optional nationality
rule and a sanctions guard, each switchable by the team lead on the AI
Screening page — because a compliance team must be able to read and audit
why a record was cleared.

**The case book.** By default the console opens on the client's
reconciliation log, the same 1,000-row file the hub reads
(`fincrime/hub/data/kyc_wc_recon_log.csv`): every row is an open onboarding
case at L1 Data Confirming with its World-Check hit, carrying the file's own
case ids, passport numbers, names as the CRM captured them (swapped,
nicknamed or garbled: the confirming task) and World-Check records.
Individuals are TT Live cases (943); companies are TT Shop sellers with
their UBO (57). The AI screening rules clear 592 hits at intake, every one
recorded in the file as a false positive, and leave 408 for analysts, among
them every exact or day/month-transposed date of birth and every company.
Each case page ends with what the file's analyst recorded, for comparison.
`CONSOLE_CASES=demo` brings back the nineteen scripted scenarios (the
walkthrough further down, and what the test suite runs on).

Built the same way as the ChargeShield demo: one Flask `app.py`, Jinja
templates, a single stylesheet, a SQLite state store, no JS framework.
A second demo with its own look, the **Straive KYC Operations Hub**, lives
under `/hub` (see below): AI agents with a human in the loop over a
1,000-case reconciliation log.

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

The startup line names the console's case book. Set `CONSOLE_CASES=demo`
(in the environment or `.env`) for the scripted scenarios instead of the
reconciliation log; switching books clears the console's stored state and
leaves the hub's alone.

## Deploy — a link anyone can open

**Permanent, free (Render).** Push the repo to GitHub, then in Render choose
*New → Blueprint*, connect the repo and create: `render.yaml` sets it up
(one gunicorn worker, debug off, a generated secret key). The free plan
sleeps after 15 minutes idle, so the first visit after a pause takes about
a minute, and its disk is wiped on every deploy or restart, which only
brings the seeded case book back. `Procfile` covers Railway and similar
hosts the same way. Keep the repository private: the demo copies the
client's internal screens.

**Right now, from this laptop.** Run a production copy (debug off, its own
state file) and open a Cloudflare quick tunnel to it. No account needed;
the link lives while both commands run, and changes on every restart.

```
set DEBUG=0 & set SECRET_KEY=<any long random string> & set FCC_STATE_DB=%TEMP%\fcc_public.db
.venv\Scripts\python.exe -m waitress --listen=127.0.0.1:8020 --threads=8 app:app
cloudflared tunnel --url http://127.0.0.1:8020
```

Either way the sign-in card shows the demo password. Set
`STRAIVE_DEMO_PASSWORD` (see `.env.example`) to hide it behind a password of
your own.

**Model assessment (a real model).** Set `LLM_FOUNDRY_KEY` (and, if
needed, `LLM_FOUNDRY_URL` and `LLM_MODEL`; see `.env.example`) and every
screening case gains an **AI assessment** button: Claude, reached through
Straive's LLM Foundry gateway, reads the client record and the watchlist
record side by side and writes a verdict, a confidence, its reasons and the
data it found missing on the ticked alerts (or every pending one), with an
audit row on each case. It is advisory: it resolves nothing, never runs at
intake, and the AI Screening page shows its status and a switch. On Render
the blueprint asks for the key; leave it blank to run without the feature.
The case data is fictional, so nothing sensitive leaves the demo.

## Straive KYC Operations Hub (`/hub`)

A second demo in the same app, in Straive's own look rather than the
client's tools, for pitching the AI-plus-human model to a new client:
`http://127.0.0.1:8010/hub` (set `HUB_DEFAULT=1` and `/` lands there). Same
demo password; its own profiles: eight L1 analysts (M. Chen, P. Nair,
A. Gupta, K. Iyer, D. Brooks, R. Fernandes, S. Rahman, L. Tran), J. Vance
(L2 Compliance, who decides confirmed matches) and H. Pham (Team Lead, who
owns the agents' settings, the re-run and the reset).

The case book is the reconciliation log in `fincrime/hub/data/` (synthetic:
every person, company and watchlist subject is fictional): 1,000 onboarding
cases across Indian, Vietnamese and US passports, each with one watchlist
hit, the names and addresses on the CRM record, the passport's visual and
machine-readable zones, the secondary ID and the proof of address, and the
analyst's historical disposition. Four deterministic agents run over every
case at boot, in under two seconds, and leave a trail on each case:

- **Identity Normalisation** – repairs the CRM name from the passport and
  the secondary ID (mojibake, Đ typings, honorifics, FNU fillers, suffixes,
  initials, nicknames, prefix and compound surnames, swapped fields,
  married and maiden names) and reconciles the four addresses (USPS, ZIP and
  PIN codes, PO Boxes, legacy and district city names, Vietnamese
  abbreviations, alley numbering, the 2025 mergers). The passport name is
  screened; every other form is an AKA.
- **Document Intake** – checks the synthetic uploads the way an onboarding
  system should: camera photo or flat scan, edges and MRZ present, check
  digits, visual zone against the MRZ, expiry, proof-of-address type, age
  and address. Rejections go back to the customer with a message; a page
  whose check digits fail is referred to L2 as a possible fraud upload.
- **Watchlist Adjudication** – compares the normalised client with the
  record: name similarity over every form, the date of birth read from the
  record itself (exact, day/month transposed, conflict, year only, range,
  not listed), the jurisdiction. Clears or confirms only above the
  confidence gate; a sanctions record never clears while the guard is on.
- **Triage & Routing** – status, queue (auto-closed, back to the customer,
  L1, L2, EDD), priority and SLA.

Claude, with the same `LLM_FOUNDRY_KEY`, runs on demand from a case: a
second opinion on the match, a draft compliance narrative, a draft customer
message. Advisory only; it never reads the historical outcome.

The split is measured, not assumed. At the default gate of 85 about 77% of
the book is AI-adjudicated (62% needs no analyst at all; a confirmed match
is routed to L2 or EDD for the relationship decision) and 23% goes to a
person: year-only, range or missing dates of birth, day/month
transpositions, the sanctions guard, fraud referrals. Every record the
agents clear is a historical false positive, every exact-date true match
is flagged, and the 22 transpositions are held. The Agents page moves the
gate and re-runs the pipeline over every case nobody has decided; the
Accuracy page compares the agents with the analysts' record, by variance
type and by country. The agents read the raw fields only.

A demo path: sign in as H. Pham → Overview → Screening review (tick two
rows, *Clear as false positive*) → Intake & documents (a flat-scan
rejection; open the passport in the viewer) → case `KYC-2026-3012`
(swapped name fields, a confirmed match) → *Second opinion* from Claude →
Agents: gate 85 → 95, *Re-run the pipeline*, watch the split move →
Accuracy. Reset hub puts the book back.

The hub landed as four commits (engine, screens, Claude agents, this
section); `git revert` them newest first to take it out again. The console
and its tests are untouched apart from the blueprint registration, the
sign-in guard skipping `/hub`, Reset demo reseeding the hub, and the second
tile on the portal.

## Tests

```
.venv\Scripts\python.exe -W error::ResourceWarning -m unittest -v
```

122 tests: `tests/test_console_book.py` (the console on the reconciliation
log: the book's shape, the rules at intake against what the file records,
the documents, Data Confirm on cleared, held, garbled-name, old-POA and
company cases, the paged lists, routing and search), `tests/test_hub.py`
(the hub's engine: the parsers, the
normalisation rules on example rows from the log, the DOB table, the
agents, the split and its precision, the documents, the actions, the
persistence), `tests/test_hub_ui.py` (every hub screen, the bulk outcome,
the settings and re-run, both resets, the two apps leaving each other
alone) and `tests/test_hub_llm.py` (the Claude agents through the seam),
plus the console's 47 end-to-end tests on the Flask test client, run on the
scripted book: the golden path, resubmit,
escalate, segregation of duties, L2/EDD decisions, Skopenow, TT Shop risk
recalculation, routing by skill and capacity, case on-demand, immediate
hand-offs, capacity overrides, trackers and CSV, the investigation-file ZIP,
the global audit log, QC sampling, Checker 2, role enforcement at EDD, POA
checks, fraud typology, World-Check links and the screening Details
button opening in a new tab, the document viewer's controls, the greyed Review button's reasons, refused
actions staying on the page with the error as a notification, the AI
screening rules (the rule book, what it did at intake, auto-verification on
Data Confirm, sellers keeping the human close, rule switches that persist),
the workflow labels across the screens, one outcome written to several
ticked alerts at once, the case list and screening queue filtered and paged
on the server, a routing run that passes over a full tier, a day/month-swapped
date of birth held for an analyst, and the model assessment (with the model
stood in for; the suite never calls the gateway).

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
**Change Status** (moving a case by hand) is for L2 and QC; the moved case
still needs the stage's level to Review — Data Confirming is an L1 step —
and a greyed Review button says so in text beside it. Mario holds both L1
and L2.

## A demo script on the reconciliation log (the default book)

1. **Amara** → *Due Diligence*: 943 TT Live cases, 100 a page. The filters,
   the sort and the page run on the server and live in the URL; *Review
   workflow* = Human-in-the-loop leaves the 351 the rules could not clear.
2. *My Work* → **KYC-2026-3011** (Nguyen Ngoc Phuong). The header says
   *Auto-verified*: World-Check record WC-554473 lists a 1967 birth date
   against her 2001. Preview the passport, the CCCD and the CT07 residence
   confirmation: the file's printed names, MRZ line and addresses. The
   *Recorded Outcome* section at the foot shows what the file's analyst
   decided (False Positive - Cleared, M. Chen). Reserve → Review → OK → the
   case verifies itself, signed by System User.
3. **KYC-2026-3146**: the CRM captured the name garbled; the vendor read
   VŨ CÔNG KHÁNH off the MRZ. Correct the name in Data Confirm: the Change
   Log keeps the edit and the case verifies itself.
4. **KYC-2026-3012** (Upadhyay Ashish): an exact date of birth on an
   adverse-media record, so the rules hold it. Confirm → the screening case
   → World-Check record WC-675768 → resolve; the file recorded *True
   Positive - Application Rejected*.
5. **Jon**: **KYC-2026-3046**, a record listing the client's date with day
   and month swapped, is held (the file recorded 14 of its 22 such cases as
   true matches). **KYC-2026-3037**: the proof of address is 223 days old,
   so Data Confirm refuses it and Resubmit POA is the move. Tenant TT Shop →
   **KYC-2026-3029** Ramasamy Agro Exports Pvt Ltd: the certificate of
   incorporation and the UBO's passport; a seller goes through Checker 1
   and Checker 2.
6. **Mario**: **KYC-2026-3118** is a flat scan the vendor declined (Resubmit
   ID); **KYC-2026-3040**'s passport fails its MRZ check digit (escalate as a
   fraud ID); **KYC-2026-3043** lists a year of birth only and is held.
7. *AI Screening* → *Against the reconciliation log*: 592 cleared by the
   rules, 592 recorded as false positives; the 351 left for analysts hold
   every true match.
8. **Nisha** → *Routing*: 935 unassigned, the 100 most urgent with the
   router's pick; **Route selected now** fills the free slots and stops.
9. **Reset demo** reloads the file book.

The document images are drawn from the file's data (it carries none); the
capture defects on about 9% of cases are planted, as in the hub, and the
case page says so.

## A demo script on the scripted book (`CONSOLE_CASES=demo`)

0. The case list's filter panel folds behind the arrow at its top right and
   stays folded through live refreshes; the buttons row keeps working and a
   folded panel says how many filters are active.
1. **Amara** → *Operations Hub › My Work* → **Get next case**: the router picks
   the most urgent case her skill book allows and opens it, reserved. The
   header shows the routing chip and the reason.
2. Open **Dmitri Volkov** (Russian passport, Russian proof of address) →
   *Review*: the Data Confirm modal shows the POA checks; two fail, OK stays
   off, **Escalate** preselects the sanctioned-country reason. Escalate with
   a fraud typology → the case is handed to L2 at once; the flash names who.
   The document panel here, and the **Preview** dialog on the case page,
   zoom with the mouse wheel, pan by drag, and have zoom, fit and rotate
   buttons.
3. Open **Michael James Taylor** for the auto-verified workflow: the header
   already says *Auto-verified* — the AI screening rules cleared his two
   namesakes at intake (a 23-year date-of-birth gap, a female record) and
   the screening case closed itself. Reserve → confirm the three fields →
   the case is Verified with no analyst step, signed by System User, the
   export attached. Then open **Daniel Mercer** for the human-in-the-loop
   golden path: six of seven records cleared by the rules, one record with
   no listed date of birth left for Amara → Reserve → confirm → screening
   case → World-Check resolve + export → alert and case outcome → EDD
   Review → Verified.
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
   capacity, raise it, **Route selected now**. *AI Screening*: switch the
   nationality rule on, then confirm Mercer's data as Amara — the seventh
   record clears and the case auto-verifies; the change sits in the history.
8. *Analytics*: tier pipeline, backlog ageing, shift progress, hand-off lag,
   quality scorecard, auto-verified vs human-in-the-loop, rules fired.
   *Audit Log*: one stream across every record; the rules sign their own.
9. **Reset demo** in the header brings the seeded case book back.

## Layout

| Path | What lives there |
|---|---|
| `app.py` | Flask app: sign-in, tenant switch, thin routes, state glue, the Operations Hub routes |
| `fincrime/data/` | vocabularies, seed builders, the 19 scenarios, the reconciliation-log book (`recon_book.py`), loader, SQLite state store |
| `fincrime/engines/` | KYC workflow state machine, AI screening rules, routing (skill book, capacity, hand-offs), work log, name-screening, World-Check logic, SLA, segregation, QC sampling, investigation file, PDF export |
| `fincrime/documents/` | synthetic ID / proof-of-address SVG cards |
| `fincrime/analytics/` | view-model builders: case list, queues, My Work, pipeline, trackers, audit log, routing console, AI screening, dashboard |
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
| §5.1 current automation: rule-based disposition of screening hits; the auto-verified and human-in-the-loop workflows | AI screening rules at intake and at the re-screen, auto-verification on Data Confirm, AI Screening page, workflow badge and filter |
| §4.2 TT Shop Checker 1 / Checker 2, risk rating, Pending EDD | Agency panel, EDD Review, Checker 2 sign-off, L2 / EDD queue |
| §5.2.1 automated routing, no spreadsheets | routing engine on every hand-off, Routing console, Trackers |
| §5.2.2 dynamic capacity, case on-demand | My Work (Get next case / Request cases), capacity per analyst |
| §5.2.3 L1 → L2 → L3, real-time pipeline, no hand-off lag | Pipeline page, hand-off feed, lag metric |
| §5.2.4 live dashboards, audit logs | Analytics, Audit Log, live refresh on every page |

The state store keeps every action across restarts; a change to the seed's
shape bumps `SEED_VERSION` and clears it. Uploads are never stored — only
the file name is echoed into the audit trail.
