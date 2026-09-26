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

## Tests

```
.venv\Scripts\python.exe -W error::ResourceWarning -m unittest -v
```

42 end-to-end tests on the Flask test client: the golden path, resubmit,
escalate, segregation of duties, L2/EDD decisions, Skopenow, TT Shop risk
recalculation, routing by skill and capacity, case on-demand, immediate
hand-offs, capacity overrides, trackers and CSV, the investigation-file ZIP,
the global audit log, QC sampling, Checker 2, role enforcement at EDD, POA
checks, fraud typology, World-Check links and the screening Details
button opening in a new tab, the document viewer's controls, the greyed Review button's reasons, refused
actions staying on the page with the error as a notification, the AI
screening rules (the rule book, what it did at intake, auto-verification on
Data Confirm, sellers keeping the human close, rule switches that persist)
and the workflow labels across the screens.

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

## A demo script

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
| `fincrime/data/` | vocabularies, seed builders, the 19 scenarios, loader, SQLite state store |
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
