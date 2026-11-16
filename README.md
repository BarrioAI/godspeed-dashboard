# Godspeed Retail Intelligence Dashboard

Finds, cleans and tracks independent streetwear / sneaker / boutique stores for
Godspeed wholesale outreach. Data lives in the "Godspeed Retail Intelligence"
Google Sheet.

## How it works

```
source tabs (ACQUISITION LEADS, STORES, city tabs, old backup)   never modified
      │  Rebuild — merge duplicates, clean contact fields, classify
      ▼
MASTER DATABASE tab                    the one tab the dashboard reads
      │  Verify — open each store's website, confirm Instagram / phone
      ▼
Leads · Retailers · Outreach · Data Quality
```

Every store lands in one of three views on the Leads page:

| View | What is in it |
|---|---|
| **Qualified** | Independent stores with a streetwear signal. Ready to pitch. |
| **Needs review** | Looks like a real store, but nothing on the row proves the fit. Approve or reject by hand. |
| **Rejected** | Chains, brand-owned stores, restaurants and dealerships, scraped articles and posts. |

Nothing is deleted. A person's Approve / Reject decision always overrides the
automatic flag, and survives rebuilds, as do outreach statuses.

Both jobs run from the **Data Quality** page:

- **Rebuild** re-reads every store tab. Run it after stores are added to the other tabs.
- **Verify** fetches each store's website and compares the Instagram profile and phone
  number shown there with the sheet. Matches are marked verified, blanks are filled in,
  and disagreements become suggestions (existing values are never overwritten).
  Instagram itself blocks most automated lookups, so a handle that could not be confirmed
  from the store's site is marked `unverified`, not `ok`.

Pitches are **logged** (OUTREACH LOG tab + the store's Outreach Status). The dashboard
does not send DMs or emails.

## Files

| File | Purpose |
|---|---|
| `quality.py` | The rules: chain / brand / junk lists, fit signals, phone / Instagram / email validation |
| `pipeline.py` | Builds MASTER DATABASE from the source tabs |
| `verify.py` | Live website / Instagram / phone checks |
| `sheets.py` | Google Sheets access |
| `app.py` | The dashboard |
| `super_clean.py` | The same two jobs from a terminal |

To change what counts as a chain or a good fit, edit the lists at the top of `quality.py`
and press Rebuild.

## Run

Deployed on Render (`render.yaml`). It needs `GOOGLE_TOKEN_JSON` and
`GOOGLE_CREDENTIALS_JSON` (the OAuth token and client JSON). Set `DASHBOARD_PASSWORD`
to put the site behind a password.

Locally:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests                              # 46 tests, no network or credentials needed
GODSPEED_DEV_XLSX=export.xlsx python app.py         # run against a downloaded copy of the sheet
python super_clean.py build                         # preview the clean database as data/master_preview.csv
python super_clean.py build --apply                 # write the MASTER DATABASE tab
python super_clean.py verify --apply                # live-check contact info and save
```
