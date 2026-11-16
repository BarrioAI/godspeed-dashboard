---
description: Permanently clean the leads file (fake phones, junk Instagram/emails) and re-score it
---
Clean `data/godspeed_leads_final.csv` in place.

1. `python super_clean.py --fix` — blanks fake phones and junk Instagram / email values, moves
   Instagram links out of the Website column, recomputes the contact-driven part of each score.
   It never deletes a row and never changes a store name.
2. `python scripts/validate_leads.py data/godspeed_leads_final.csv` must print `OK`.
3. `python -m pytest tests -q` must pass.
4. Show Goldie what changed (cells per column, tier counts before and after) and a few examples
   from `git diff`. Commit only after that summary; then offer `/sync-leads`.
