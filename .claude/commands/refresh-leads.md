---
description: The weekly run — re-verify every store, apply what the websites prove, re-rank, push live, report
---
Run the weekly refresh end to end. Goal: Goldie opens the dashboard to a Qualified list that is
ranked by real fit and has contact details that work. Do the whole run without stopping to ask;
the only things that wait for Goldie are listed in step 8.

0. Run `/source-leads` first (new prospects for this week's market) and carry its new rows through
   the steps below in the same pull request.
1. `git checkout main && git pull`, then `python ops.py status`. Stop and report if the dashboard
   is down or `sheets_error` is not null.
2. `python ops.py sync --dry-run`. If the sheet is behind the file, `python ops.py sync` first, so
   verification checks the current values.
3. `python ops.py verify --recheck` on the first run of each month (sites change, stores close);
   `python ops.py verify` on the other weeks (only new or changed stores). It resumes if cut off.
4. `python ops.py export verification -o /tmp/verification.csv`, then
   `python refresh.py /tmp/verification.csv --log /tmp/refresh_log.csv`. It applies only what a
   store's own website proves (see the rules at the top of `refresh.py`), records the peer brands
   each store stocks, and re-scores. Read `needs_a_look`: fix the ones you can settle from the
   evidence in the export, leave the rest for the report. Do not guess.
5. Read a sample of the new ranking: the top 30 Qualified by score, and 20 random rows from Review.
   A non-store near the top, or a real boutique stuck in Review or Rejected, means a rule in
   `quality.py` is wrong: fix the rule, add a test case for it, never delete the row.
6. `python scripts/validate_leads.py data/godspeed_leads_final.csv` and `python -m pytest tests -q`
   must both pass. Commit on a branch, push, open a pull request, and merge it when its checks are
   green (Goldie has asked for this run to go live without waiting). Wait for Render to deploy:
   `/api/job/status` returns a new `boot` value.
7. `python ops.py sync --dry-run`, check `added` is 0 unless stores were added, then
   `python ops.py sync`, then `python ops.py verify` so the changed rows are checked again.
8. Report to Goldie, short and in plain language:
   - Qualified / Review / Rejected and A / B / C counts, against last week's.
   - **This week's call list**: the top 20 Qualified stores not yet pitched
     (`python ops.py leads --view qualified`), each with city, the brands it stocks, and the best
     way to reach it.
   - **New this week**: the stores `/source-leads` added, by market, and which ones verification
     confirmed.
   - **Outreach**: stores waiting on a reply and those due a follow-up (`python ops.py threads`).
   - What changed: contact details corrected, filled and cleared; stores that moved bucket.
   - What needs Goldie: `needs_a_look` items you could not settle, websites that have failed to
     load two runs in a row (probably closed), and any store whose site mentions Godspeed.

Never send a DM or an email to a store. Outreach is Goldie's.
