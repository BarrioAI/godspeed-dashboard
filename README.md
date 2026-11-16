# Godspeed Retail Intelligence Dashboard

Tracks stores, outreach, orders and commission for Godspeed wholesale. Data lives in the
"Godspeed Retail Intelligence" Google Sheet: `STORES` / `OUTREACH_LOG` / `ORDERS`
(see `SPEC-wholesale-loop.md` for the operating loop).

## Quality layer

`STORES` still contains a lot of scraper output: chain store-locator pages, brand sites,
articles and Instagram posts, fake phone numbers repeated across hundreds of rows. The
dashboard shows it through a read-side filter instead of rewriting it:

| Leads view | What is in it |
|---|---|
| **Qualified** | Independent stores with a streetwear signal whose name matches their own site. |
| **Needs review** | Looks like a real store, but nothing on the row proves the fit. Approve or reject by hand. |
| **Rejected** | Chains, brand-owned stores, non-retail, scraped articles and posts, duplicate listings. |

- Junk contact values are hidden, not deleted. `STORES` keeps its raw cells.
- **Approve / Reject** decisions go to a `REVIEW` tab and override the automatic flag.
- **Verify** (Quality page) fetches each store's website and compares the Instagram profile
  and phone number shown there with the sheet. Results go to a `VERIFICATION` tab: matches
  are marked verified, missing details found on the site are shown as "from site", and
  disagreements are listed as suggestions. Instagram blocks most automated lookups, so a
  handle that could not be confirmed from the store's own site is marked `unverified`.
- Both tabs are keyed by store name + city, so they survive `sync_to_sheets.py` rewriting
  `STORES`.
- The only `STORES` cell the dashboard writes is `pipeline_stage`, when a pitch is logged
  as Sent. Pitches are logged to `OUTREACH_LOG`; the dashboard does not send DMs or emails.

To change what counts as a chain or a good fit, edit the lists at the top of `quality.py`.

| File | Purpose |
|---|---|
| `quality.py` | Rules: chain / brand / not-a-store lists, fit signals, phone / Instagram / email validation |
| `stores.py` | Applies the rules to `STORES` rows (hide junk contacts, flag, mark duplicates) |
| `verify.py` | Live website / Instagram / phone checks |
| `sheets.py` | Google Sheets access (batched reads, failure-safe writes) |
| `app.py` | The dashboard |
| `super_clean.py` | The same audit from a terminal |

## Run

Deployed on Render (`render.yaml`). Needs `GOOGLE_TOKEN_JSON` and `GOOGLE_CREDENTIALS_JSON`.
Set `DASHBOARD_PASSWORD` to put the site behind a password. Run with one gunicorn worker:
verify progress is held in memory.

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests                                      # no network or credentials needed
python super_clean.py --csv data/godspeed_leads_final.csv   # audit the leads file
GODSPEED_LOCAL_DIR=/path/to/csvs python app.py              # run on STORES.csv, OUTREACH_LOG.csv, ...
```
