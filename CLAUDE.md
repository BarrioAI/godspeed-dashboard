# Godspeed wholesale system — operating guide for Claude Code

Claude Code runs this system end to end. There are no other agents and nothing
runs on a laptop. Goldie (the owner) decides; Claude Code does the work: sources
stores, cleans and scores them, verifies contact details, syncs the live sheet,
ships the dashboard.

## The pieces

| Piece | Where | Who writes it |
|---|---|---|
| Leads file | `data/godspeed_leads_final.csv` | Claude Code, by commit. **Source of truth for stores.** |
| Live sheet | Google Sheet "Godspeed Retail Intelligence": `STORES`, `OUTREACH_LOG`, `ORDERS`, `REVIEW`, `VERIFICATION` | The dashboard only |
| Dashboard | Flask app on Render, https://godspeed-dashboard.onrender.com, deploys from `main` | — |
| Rules | `quality.py` (what is a chain / brand store / good fit), `stores.py`, `verify.py` | Claude Code |

The dashboard holds the Google credentials and has open network access. A Claude
Code session has neither, and does not need them: it works on the repo and
drives the live system through `ops.py`, which calls the dashboard's API.

```
Claude Code edits data/godspeed_leads_final.csv  ──commit, merge to main──▶  Render deploys
        │                                                                        │
        └── python ops.py sync ───────────────────────────────────────────▶  STORES updated
            python ops.py verify ─────────────────────────────────────────▶  VERIFICATION filled
            python ops.py export … ◀──────────────────────────────────────  live tabs as CSV
            python refresh.py verification.csv ──▶ leads file corrected and re-ranked
```

In Claude Code on the web, the session's environment must allow
`godspeed-dashboard.onrender.com` (the `godspeed-dashboard` environment does).

## Rules that keep the data clean

- Never hand-edit `STORES` in the sheet for store details; change the leads file and sync.
  Sync never deletes rows and never touches `pipeline_stage`, `account_status` or
  `last_order_date` (the dashboard owns those).
- Every change to the leads file must pass `python scripts/validate_leads.py data/godspeed_leads_final.csv`.
- Do not delete rows to "clean". Chains, brand stores and non-stores are filtered by
  `quality.py` and shown under Rejected; fix the rule, not the row. Remove a row only
  when Goldie asks.
- Contact details change only on evidence from the store's own website (`refresh.py` holds the
  rules: own site, not a mall or directory page; phone in the store's state). A US phone whose
  area code does not exist, or is from another state and not on the store's site, is cleared.
- A store goes in with at least a name, a city and one way to reach it. Do not invent
  contact details: a blank is better than a guess. Verification fills blanks from the
  store's own website.
- Goldie's Approve / Reject decisions (`REVIEW` tab) override every rule.
- Stores Goldie has held out are listed in `EXCLUDED_STORES` in `quality.py`.
- Outreach is sent by Goldie. The dashboard only logs it. Never send a DM or email
  to a store without being asked to for that store.

## Routine jobs

| Ask | Command |
|---|---|
| "How does the data look?" | `/audit-leads` |
| "Clean it" | `/clean-leads` |
| "Check the Instagram / phone / website" | `/verify-leads` |
| "Find stores in <market>" | `/add-leads <market>` |
| "Push it live" | `/sync-leads` |
| The weekly run (scheduled, or "refresh everything") | `/refresh-leads` |

`/refresh-leads` is the standing job: verify → `refresh.py` → validate → merge → sync → report.
It runs every week as a scheduled Claude Code task and may merge its own pull request when the
validator and the tests pass. Everything else still waits for Goldie.

## How a store is ranked

`Lead Score` (0–100) = Contact 30 + Brand 25 + Market 25 + Reach 20 (`score_leads.py`).
Brand is evidence, not a guess: `Brands Carried` lists the peer brands (`PEER_BRANDS` in
`quality.py`) seen on the store's own website by verification, and 1 / 2 / 3+ of them earn
10 / 18 / 25. A store that already sells Hellstar, Sp5der or Rhude and can be reached by Instagram
and email is A-Tier; that is who Goldie should pitch first. Do not type brands into
`Brands Carried` without a source (the store's site or stockist page).

## Develop

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q                                   # must pass before every push
python super_clean.py --csv data/godspeed_leads_final.csv   # audit the leads file, no credentials needed
GODSPEED_LOCAL_DIR=<dir of STORES.csv …> python app.py      # run the dashboard on files
```

`render.yaml` must keep one gunicorn worker (job progress is held in memory).
`SPEC-wholesale-loop.md` is the product spec. `deep_clean*.py`, `fix_columns.py`,
`clean_store_database.py` and `sync_to_sheets.py` are superseded leftovers that need
laptop credentials; do not use them.
