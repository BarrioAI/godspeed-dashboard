---
description: Push the leads file to the live STORES tab
---
Make the live sheet match `data/godspeed_leads_final.csv`.

1. The file must be on `main` and deployed: the dashboard syncs from the copy in its own deploy.
   Check `python ops.py status` shows the dashboard up with no `sheets_error`.
2. `python ops.py sync --dry-run` and read the counts. A large `added` when you only fixed contact
   details, or `only_in_sheet_kept` far from what you expect, means the wrong build is live: stop
   and tell Goldie.
3. `python ops.py sync`.
4. `python ops.py status` again and report the new numbers.

Sync adds new stores and refreshes contact details and scores. It never deletes a row and never
touches pipeline stage, account status or last order date.
