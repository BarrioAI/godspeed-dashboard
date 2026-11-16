---
description: Check each store's Instagram, phone and website against the store's own site
---
Run the live contact check on the deployed dashboard and act on the results.

1. `python ops.py verify`. It runs on the server (which can reach store websites) in batches,
   saves to the `VERIFICATION` tab as it goes, and skips stores already checked, so it can be
   re-run at any time and survives the server restarting. `--recheck` checks everything again.
   If it reports a network problem, that batch was not saved; try again later.
2. `python ops.py export verification -o /tmp/verification.csv` and read it.
3. `python super_clean.py --apply-verification /tmp/verification.csv --changes /tmp/changes.csv`
   puts what the check found into `data/godspeed_leads_final.csv`: blanks are filled, and a phone
   or Instagram the store's own site contradicts is replaced. It only trusts a page when the store's
   name matches the website, and prints what it skipped and why.
4. Read `/tmp/changes.csv`. Open the store's site for anything that looks off and revert that row.
   Rows whose website is `unreachable` are not changed: check whether the URL is a typo.
5. Validate, test, summarise the corrections for Goldie, commit, then `/sync-leads`, then
   `python ops.py verify` once more so the corrected stores are re-checked.

Instagram blocks automated lookups, so `ig_status: unverified` means "not confirmed", not "wrong".
