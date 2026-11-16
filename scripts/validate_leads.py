#!/usr/bin/env python3
"""Schema guard for data/godspeed_leads_final.csv.

Run: python3 scripts/validate_leads.py <path-to-csv>
Exit 0 on success (prints summary), exit 1 on violation (prints violations).
"""
import csv
import re
import sys
from collections import Counter

CANONICAL_HEADER = [
    "Store Name",
    "City",
    "State",
    "Country",
    "Website",
    "Instagram",
    "Email",
    "Phone",
    "Carries Supreme",
    "Carries Hellstar",
    "Carries Godspeed",
    "Last Order Date",
    "Outreach Status",
    "Outreach Channel",
    "Notes",
    "Date Added",
    "Lead Score",
    "Priority Tier",
    "Brands Carried",
    "Score Reasons",
    "Score Breakdown",
]

VALID_TIERS = {"A-Tier", "B-Tier", "C-Tier", ""}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DIGITS_RE = re.compile(r"^\+?[\d\s\-\(\)\.]+$")


def main(path: str) -> int:
    violations: list[str] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            print(f"FAIL: {path} is empty")
            return 1

        if header != CANONICAL_HEADER:
            print("FAIL: header mismatch")
            print(f"  expected ({len(CANONICAL_HEADER)} cols): {CANONICAL_HEADER}")
            print(f"  got      ({len(header)} cols): {header}")
            missing = [c for c in CANONICAL_HEADER if c not in header]
            extra = [c for c in header if c not in CANONICAL_HEADER]
            if missing:
                print(f"  missing: {missing}")
            if extra:
                print(f"  extra: {extra}")
            return 1

        idx = {col: i for i, col in enumerate(header)}
        store_city_seen: Counter = Counter()
        row_count = 0
        tier_counts: Counter = Counter()

        for line_no, row in enumerate(reader, start=2):
            if not row or all(c.strip() == "" for c in row):
                continue
            if len(row) != len(CANONICAL_HEADER):
                violations.append(
                    f"line {line_no}: wrong column count "
                    f"({len(row)} vs {len(CANONICAL_HEADER)})"
                )
                continue

            row_count += 1
            store = row[idx["Store Name"]].strip()
            city = row[idx["City"]].strip()
            insta = row[idx["Instagram"]].strip()
            email = row[idx["Email"]].strip()
            phone = row[idx["Phone"]].strip()
            score = row[idx["Lead Score"]].strip()
            tier = row[idx["Priority Tier"]].strip()

            if store == "Store Name":
                violations.append(f"line {line_no}: embedded header row")
                continue

            if insta.lower().startswith(("http://", "https://", "www.")):
                violations.append(
                    f"line {line_no} ({store}): URL in Instagram column: {insta!r}"
                )

            if insta and DIGITS_RE.match(insta) and re.sub(r"\D", "", insta):
                digit_count = len(re.sub(r"\D", "", insta))
                if digit_count >= 7:
                    violations.append(
                        f"line {line_no} ({store}): phone number in Instagram column: {insta!r}"
                    )

            if phone and EMAIL_RE.match(phone):
                violations.append(
                    f"line {line_no} ({store}): email in Phone column: {phone!r}"
                )

            if score and not _is_numeric(score):
                violations.append(
                    f"line {line_no} ({store}): non-numeric Lead Score: {score!r}"
                )

            if tier not in VALID_TIERS:
                violations.append(
                    f"line {line_no} ({store}): invalid Priority Tier: {tier!r}"
                )
            if tier:
                tier_counts[tier] += 1

            if store and city:
                store_city_seen[(store.lower(), city.lower())] += 1

    dupes = [(k, n) for k, n in store_city_seen.items() if n > 1]
    for (store, city), n in dupes:
        violations.append(f"duplicate Store Name + City: ({store!r}, {city!r}) x{n}")

    if violations:
        print(f"FAIL: {len(violations)} violation(s) in {path}")
        for v in violations[:50]:
            print(f"  - {v}")
        if len(violations) > 50:
            print(f"  ... and {len(violations) - 50} more")
        return 1

    print(f"OK: {path}")
    print(f"  rows: {row_count}")
    print(f"  columns: {len(CANONICAL_HEADER)}")
    print(
        f"  tiers: A={tier_counts['A-Tier']} "
        f"B={tier_counts['B-Tier']} "
        f"C={tier_counts['C-Tier']}"
    )
    return 0


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: validate_leads.py <csv-path>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
