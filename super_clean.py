#!/usr/bin/env python3
"""
Godspeed data cleaning — command line.

The dashboard's Data Quality page runs these same two jobs from a button; this
script is for running them from a terminal or a scheduled task.

  python super_clean.py build              # preview: writes data/master_preview.csv
  python super_clean.py build --apply      # writes the MASTER DATABASE tab
  python super_clean.py verify --limit 50  # live-check 50 stores, preview only
  python super_clean.py verify --apply     # live-check all, save results to the sheet
  python super_clean.py build --xlsx export.xlsx   # work from a downloaded copy

Without --apply nothing is written to Google Sheets. The source tabs are never
modified either way; only the MASTER DATABASE tab is (re)written.
"""

from __future__ import annotations

import argparse
import csv
import json
import os

import pipeline
import sheets

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _write_csv(name: str, rows: list[list]) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build", "verify"])
    parser.add_argument("--apply", action="store_true", help="write the result to the MASTER DATABASE tab")
    parser.add_argument("--limit", type=int, help="verify only the top N stores")
    parser.add_argument("--xlsx", help="read from an .xlsx export instead of Google Sheets (never writes back)")
    args = parser.parse_args()

    if args.xlsx:
        from fake_sheets import FakeSpreadsheet
        sheets.use_spreadsheet(FakeSpreadsheet.from_xlsx(args.xlsx))
    ss = sheets.open_spreadsheet()

    if args.command == "build":
        records, stats = pipeline.build_master(sheets.read_all_tabs(ss))
        stats.pop("per_tab", None)
        print(json.dumps(stats, indent=2))
        rows = pipeline.to_rows(records)
        print("Preview:", _write_csv("master_preview.csv", rows))
        if args.apply and not args.xlsx:
            sheets.write_master(ss, rows)
            print(f"Wrote {len(records)} stores to the '{pipeline.MASTER_TAB}' tab.")
        elif args.apply:
            print("--apply ignored: --xlsx is read-only.")
        return

    # verify
    import app
    if not args.apply or args.xlsx:
        # keep the write in memory: swap in a copy of the workbook
        from fake_sheets import FakeSpreadsheet
        if not args.xlsx:
            sheets.use_spreadsheet(FakeSpreadsheet(sheets.read_all_tabs(ss)))
    if pipeline.MASTER_TAB not in sheets.tab_titles(sheets.open_spreadsheet()):
        app.rebuild_master(print)
    result = app.verify_master(progress=lambda msg, *_: print(msg, end="\r"), limit=args.limit)
    print("\n" + json.dumps(result, indent=2))
    final = sheets.read_tab(sheets.open_spreadsheet(), pipeline.MASTER_TAB)
    print("Report:", _write_csv("verify_report.csv", final))
    if not args.apply or args.xlsx:
        print("Preview only — re-run with --apply (and without --xlsx) to save to the sheet.")


if __name__ == "__main__":
    main()
