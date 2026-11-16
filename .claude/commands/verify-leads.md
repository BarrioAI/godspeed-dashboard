---
description: Check each store's Instagram, phone and website against the store's own site
---
Run the live contact check on the deployed dashboard and act on the results.

1. `python ops.py verify`. It runs on the server (which can reach store websites) in batches,
   saves to the `VERIFICATION` tab as it goes, and skips stores already checked, so it can be
   re-run at any time and survives the server restarting. `--recheck` checks everything again.
   If it reports a network problem, that batch was not saved; try again later.
2. `python ops.py export verification -o /tmp/verification.csv` and read it.
3. For rows with `suggested_fixes` (the website disagrees with the sheet) or `found_*` values
   (the website has a detail the sheet lacks): open the store's site if there is any doubt, then
   put the correct value in `data/godspeed_leads_final.csv`. Use only what the store's own site shows.
4. Rows whose website is `unreachable`: check whether the URL is a typo before clearing it.
5. Validate, test, summarise the corrections for Goldie, commit, then `/sync-leads`.

Instagram blocks automated lookups, so `ig_status: unverified` means "not confirmed", not "wrong".
