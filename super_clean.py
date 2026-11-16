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
  python super_clean.py --apply-verification v.csv --changes changes.csv
                                                      # put what the live check found into the leads file

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


def _rescore(rows: list[dict]):
    """Recompute Contact and Reach from the row's current contact details; Brand and Market stay as scored."""
    import score_leads
    pattern = r"Contact:(\d+)/Brand:(\d+)/Market:(\d+)/Reach:(\d+)"
    for row in rows:
        score, tier, breakdown = score_leads.score_row(row)
        old = re.fullmatch(pattern, row.get("Score Breakdown") or "")
        new = re.fullmatch(pattern, breakdown)
        if old and new:
            contact, reach = int(new.group(1)), int(new.group(4))
            brand, market = int(old.group(2)), int(old.group(3))
            score = contact + brand + market + reach
            tier = "A-Tier" if score >= 75 else "B-Tier" if score >= 45 else "C-Tier"
            breakdown = f"Contact:{contact}/Brand:{brand}/Market:{market}/Reach:{reach}"
        row["Lead Score"], row["Priority Tier"], row["Score Breakdown"] = str(score), tier, breakdown


def fix_leads(path: str):
    import stores

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)
    changed = stores.scrub_leads(rows)
    tiers_before = {t: sum(1 for r in rows if r.get("Priority Tier") == t) for t in ("A-Tier", "B-Tier", "C-Tier")}
    _rescore(rows)
    tiers_after = {t: sum(1 for r in rows if r.get("Priority Tier") == t) for t in tiers_before}
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"file": path, "rows": len(rows), "contact_cells_changed": changed,
                      "tiers_before": tiers_before, "tiers_after": tiers_after}, indent=2))
    print("Now run: python scripts/validate_leads.py", path)


_PHONE_FIX_RE = re.compile(r"Phone: website shows (\(\d{3}\) \d{3}-\d{4})")
_IG_FIX_RE = re.compile(r"Instagram: website links (@[A-Za-z0-9._]+)")


def apply_verification(verification_csv: str, path: str, changes_out: str | None = None):
    """
    Put what the live check found on each store's own website into the leads file.

    Applied only where the store's name matches its website, so the page that
    was read is known to be the store's and not an article or a directory:
      * a blank Instagram / phone / email is filled with the one the site shows
      * a phone the site contradicts is replaced with the site's
      * an Instagram handle the site contradicts is replaced only when the
        site's handle itself matches the store's name
    Everything else is left alone and listed as skipped.
    """
    import app
    import quality as q

    with open(verification_csv, newline="", encoding="utf-8") as f:
        checks = {app.store_key(v.get("store_name", ""), v.get("city", "")): v for v in csv.DictReader(f)}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, rows = reader.fieldnames, list(reader)

    changes, skipped = [], []
    for row in rows:
        check = checks.get(app.store_key(row.get("Store Name", ""), row.get("City", "")))
        if not check:
            continue
        wanted = []                                   # (column, new value, why)
        for column, found in (("Instagram", "found_instagram"), ("Phone", "found_phone"), ("Email", "found_email")):
            if check.get(found) and not q.s(row.get(column)):
                wanted.append((column, check[found], "blank filled from website"))
        fixes = check.get("suggested_fixes", "")
        m = _PHONE_FIX_RE.search(fixes)
        if m:
            wanted.append(("Phone", m.group(1), "website shows a different number"))
        m = _IG_FIX_RE.search(fixes)
        if m:
            wanted.append(("Instagram", m.group(1).lower(), "website links a different profile"))
        if not wanted:
            continue

        # The check only counts if it read the values this row still has.
        current = (q.s(row.get("Website")), q.s(row.get("Instagram")), q.s(row.get("Phone")))
        if (check.get("website", ""), check.get("instagram", ""), check.get("phone", "")) != current:
            skipped.append((row["Store Name"], "row changed since it was checked"))
            continue
        site_only = {"Website": row.get("Website", ""), "Instagram": "", "City": row.get("City", "")}
        if q.name_matches_site(site_only, row["Store Name"]) is not True:
            skipped.append((row["Store Name"], "name does not match the website, so the page may not be the store's"))
            continue
        for column, value, why in wanted:
            if column == "Instagram" and q.name_matches_site(
                    {"Instagram": value, "City": row.get("City", "")}, row["Store Name"]) is not True:
                skipped.append((row["Store Name"], f"website's Instagram {value} does not match the store's name"))
                continue
            if column == "Email" and not q.normalize_email(value):
                continue
            changes.append({"Store Name": row["Store Name"], "City": row.get("City", ""), "Column": column,
                            "Before": q.s(row.get(column)), "After": value, "Why": why})
            row[column] = value

    touched = {(c["Store Name"], c["City"]) for c in changes}
    _rescore([r for r in rows if (r["Store Name"], r.get("City", "")) in touched])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if changes_out:
        with open(changes_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Store Name", "City", "Column", "Before", "After", "Why"])
            writer.writeheader()
            writer.writerows(changes)
    by_kind: dict = {}
    for c in changes:
        key = f"{c['Column']}: {c['Why']}"
        by_kind[key] = by_kind.get(key, 0) + 1
    skip_kinds: dict = {}
    for _, why in skipped:
        why = why.split(" @")[0] if why.startswith("website's Instagram") else why
        skip_kinds[why] = skip_kinds.get(why, 0) + 1
    print(json.dumps({"checks_read": len(checks), "stores_changed": len(touched), "cells_changed": len(changes),
                      "by_kind": by_kind, "skipped": skip_kinds, "changes_file": changes_out}, indent=2))
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
    parser.add_argument("--apply-verification", metavar="VERIFICATION_CSV",
                        help="apply what the live check found (an export of the VERIFICATION tab) to the leads CSV")
    parser.add_argument("--changes", help="with --apply-verification: write the list of changes to this CSV")
    args = parser.parse_args()

    if args.fix:
        return fix_leads(args.csv or LEADS_CSV)
    if args.apply_verification:
        return apply_verification(args.apply_verification, args.csv or LEADS_CSV, args.changes)

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
