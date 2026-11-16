#!/usr/bin/env python3
"""
Godspeed store audit — command line.

Runs the dashboard's quality layer over the STORES tab (or a file) and prints
what it finds. Read-only unless --verify --apply is given, and even then only
the VERIFICATION tab is written; STORES is never modified.

  python super_clean.py                               # audit the live STORES tab
  python super_clean.py --csv data/godspeed_leads_final.csv
  python super_clean.py --xlsx export.xlsx            # a downloaded copy of the workbook
  python super_clean.py --report audit.csv            # also write one row per store
  python super_clean.py --verify --limit 50           # live-check 50 stores, save nothing
  python super_clean.py --verify --apply              # live-check all, save to VERIFICATION
  python super_clean.py --fix                         # clean data/godspeed_leads_final.csv in place

--fix is the one mode that rewrites data: it blanks fake phones and junk
Instagram / email values in the leads file, moves Instagram links out of the
Website column, and recomputes the Contact and Reach parts of each score (the
score_leads.py rubric) so that removed junk no longer earns points. Brand and
Market points are left as scored. No row is deleted.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re

import sheets

# data/godspeed_leads_final.csv columns -> STORES columns (same mapping as sync_to_sheets.py)
CSV_TO_STORES = {
    "Store Name": "store_name", "City": "city", "State": "market", "Country": "country",
    "Website": "website", "Instagram": "instagram", "Email": "email", "Phone": "phone",
    "Outreach Status": "pipeline_stage", "Last Order Date": "last_order_date", "Notes": "notes",
    "Lead Score": "lead_score", "Priority Tier": "priority_tier", "Score Breakdown": "score_breakdown",
}


def _from_csv(path: str):
    from fake_sheets import FakeSpreadsheet
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = [CSV_TO_STORES.get(h, h) for h in rows[0]]
    return FakeSpreadsheet({sheets.STORES_TAB: [header] + rows[1:]})


LEADS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "godspeed_leads_final.csv")


def fix_leads(path: str):
    import score_leads
    import stores

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    changed = stores.scrub_leads(rows)
    tiers_before = {t: sum(1 for r in rows if r.get("Priority Tier") == t) for t in ("A-Tier", "B-Tier", "C-Tier")}
    for row in rows:
        score, tier, breakdown = score_leads.score_row(row)
        # Contact and Reach are recomputed from the row's current contact details
        # (so junk no longer earns points); Brand and Market stay as scored.
        old = re.fullmatch(r"Contact:(\d+)/Brand:(\d+)/Market:(\d+)/Reach:(\d+)", row.get("Score Breakdown") or "")
        new = re.fullmatch(r"Contact:(\d+)/Brand:(\d+)/Market:(\d+)/Reach:(\d+)", breakdown)
        if old and new:
            contact, reach = int(new.group(1)), int(new.group(4))
            brand, market = int(old.group(2)), int(old.group(3))
            score = contact + brand + market + reach
            tier = "A-Tier" if score >= 75 else "B-Tier" if score >= 45 else "C-Tier"
            breakdown = f"Contact:{contact}/Brand:{brand}/Market:{market}/Reach:{reach}"
        row["Lead Score"], row["Priority Tier"], row["Score Breakdown"] = str(score), tier, breakdown
    tiers_after = {t: sum(1 for r in rows if r.get("Priority Tier") == t) for t in tiers_before}
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"file": path, "rows": len(rows), "contact_cells_changed": changed,
                      "tiers_before": tiers_before, "tiers_after": tiers_after}, indent=2))
    print("Now run: python scripts/validate_leads.py", path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", help="audit a leads CSV instead of the live sheet")
    parser.add_argument("--xlsx", help="audit an .xlsx export of the workbook instead of the live sheet")
    parser.add_argument("--report", help="write one row per store (with flag and reasons) to this CSV")
    parser.add_argument("--verify", action="store_true", help="also run the live website / Instagram checks")
    parser.add_argument("--apply", action="store_true", help="with --verify: save results to the VERIFICATION tab")
    parser.add_argument("--limit", type=int, help="with --verify: only the top N stores")
    parser.add_argument("--fix", action="store_true", help="clean and re-score the leads CSV in place")
    args = parser.parse_args()

    if args.fix:
        return fix_leads(args.csv or LEADS_CSV)

    offline = bool(args.csv or args.xlsx)
    if args.csv:
        sheets.use_spreadsheet(_from_csv(args.csv))
    elif args.xlsx:
        from fake_sheets import FakeSpreadsheet
        sheets.use_spreadsheet(FakeSpreadsheet.from_xlsx(args.xlsx))

    import app
    import stores

    if args.verify:
        if not args.apply and not offline:
            # keep the write in memory: work on a copy of the tabs
            from fake_sheets import FakeSpreadsheet
            live = sheets.open_spreadsheet()
            sheets.use_spreadsheet(FakeSpreadsheet(sheets.read_tabs(
                live, [sheets.STORES_TAB, sheets.REVIEW_TAB, sheets.VERIFY_TAB])))
        try:
            result = app.verify_stores(progress=lambda msg, *_: print(msg, end="\r"), limit=args.limit)
        except RuntimeError as exc:
            raise SystemExit(f"\nVerification stopped: {exc}")
        print("\n" + json.dumps(result, indent=2))
        if not args.apply or offline:
            print("Nothing saved — re-run with --verify --apply against the live sheet to keep these results.")

    data = app.load_data(force=True)
    if data["error"]:
        raise SystemExit(data["error"])
    print(json.dumps(stores.summarize(data["stores"]), indent=2))

    if args.report:
        fields = ["store_name", "Store Name", "City", "State", "Country", "Website", "Instagram", "Email",
                  "Phone", "lead_score", "Priority Tier", "_bucket", "Cleanup Flag", "Flag Reasons",
                  "IG Status", "Web Status", "Phone Status", "Suggested Fixes", "cleaning"]
        with open(args.report, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for s in data["stores"]:
                writer.writerow(dict(s, store_name=s["_name"], cleaning="; ".join(s["_cleaning"])))
        print("Report:", args.report)


if __name__ == "__main__":
    main()
