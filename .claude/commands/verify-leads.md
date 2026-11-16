---
description: Check each store's Instagram, phone and website against the store's own site
---
Run the live contact check on the deployed dashboard and act on the results.

1. `python ops.py verify`. It runs on the server (which can reach store websites) in batches,
   saves to the `VERIFICATION` tab as it goes, and skips stores already checked, so it can be
   re-run at any time and survives the server restarting. `--recheck` checks everything again.
   If it reports a network problem, that batch was not saved; try again later.
2. `python ops.py export verification -o /tmp/verification.csv` and read it.
3. `python refresh.py /tmp/verification.csv --dry-run`, read what it would change, then run it
   without `--dry-run`. It applies what a store's own website proves and lists the rest under
   `needs_a_look`. Settle those by hand only from the evidence; use only what the store's own
   site shows.
4. Rows whose website is `unreachable`: check whether the URL is a typo before clearing it.
5. Validate, test, summarise the corrections for Goldie, commit, then `/sync-leads`.

Instagram blocks automated lookups, so `ig_status: unverified` means "not confirmed", not "wrong".
