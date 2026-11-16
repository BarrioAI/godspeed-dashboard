---
description: Audit the Godspeed leads — how many are qualified, what is held back and why
---
Audit the store data and report to Goldie in plain language.

1. Run `python super_clean.py --csv data/godspeed_leads_final.csv --report /tmp/godspeed-audit.csv`.
2. If the live dashboard is reachable, run `python ops.py status` and compare its numbers with the file's.
   A difference means the sheet is behind the file (suggest `/sync-leads`) or stores were added in the dashboard.
3. Read a sample of the report: 25 qualified rows and 15 from each of review and rejected. Look for
   stores in the wrong bucket. A chain or brand store that got through, or a real boutique that was
   rejected, means a rule in `quality.py` needs fixing; propose the fix with the examples.
4. Report: counts per bucket, the top reasons stores are held back, contact coverage on qualified
   stores, and anything misfiled. Do not change data in this command.
