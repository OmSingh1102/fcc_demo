# Demo data snapshot

A copy of the console's data as it stood on 16 November 2026, so the demo can
run on another machine with the same cases.

| File | What it holds |
|---|---|
| `screening.sqlite` | The ID screening book: 6 cases and the Settings. **The Didit API key is blank.** |
| `state.sqlite` | The case book built from `fincrime/filebook/data/kyc_wc_recon_log.csv` (the 1,000 records). |
| `images/` | The ID images the cases point to. Every one is a made-up specimen marked SPECIMEN / SYNTHETIC DEMO DOCUMENT, or the sample card Nebraska's DMV publishes. No real person's ID. |

No key is included: not the LLM Foundry key (`.env`) and not Didit's.

## Use it

From the project folder, with the app stopped:

```
copy demo_data\screening.sqlite fincrime_screening.db
copy demo_data\state.sqlite fincrime_state.db
xcopy /E /I demo_data\images uploads
```

Then:
1. Put the LLM Foundry key in `.env` (see `.env.example`).
2. Start the app.
3. If the Didit check is wanted, the QC lead enters the Didit key on Settings.

The live files (`fincrime_*.db`, `uploads/`) stay out of git. This folder is
a snapshot, so later changes in the app don't show up here until a new
snapshot is taken.
