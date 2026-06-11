#!/usr/bin/env python3
"""Clean junk stores and chains out of the Godspeed lead database."""
from __future__ import annotations

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

US_INPUT = DATA_DIR / "master_backup_20260511_144030.csv"
US_OUTPUT = DATA_DIR / "master_cleaned.csv"

CO_INPUT = DATA_DIR / "colombia_stores_final.csv"
CO_OUTPUT = DATA_DIR / "colombia_cleaned.csv"

SCORED_INPUT = DATA_DIR / "godspeed_leads_scored.csv"
SCORED_OUTPUT = DATA_DIR / "godspeed_leads_final.csv"

CHAIN_KEYWORDS = [
    "culture kings", "men's wearhouse", "banana republic", "dick's sporting",
    "jd sports", "hollister", "foot locker", "finish line", "champs sports",
    "zumiez", "dtlr", "villa", "snipes", "hibbett", "jimmy jazz",
    "shoe carnival", "journeys", "pacsun", "hot topic", "urban outfitters",
    "nordstrom", "target", "walmart", "gap", "h&m", "forever 21", "zara",
    "old navy", "express", "american eagle", "academy sports", "big 5 sporting",
]

JUNK_SUBSTRINGS = [
    "near me", "locations in", "stores in", "| gap", "contact lenses",
    "prescription glasses", "optical",
]

LOCAL_BOUTIQUE_WHITELIST = {
    # Local multi-location boutiques to KEEP even if they hit the 5+ heuristic.
    "solefly",
    "unknwn",
    "kith",
    "shoe gallery",
    "sneaker politics",
    "extra butter",
    "concepts",
    "kicks",
    "atmos",
    "bodega",
    "rsvp gallery",
    "saint alfred",
    "undefeated",
    "a ma maniere",
}


def is_chain_keyword(name: str) -> str | None:
    low = name.lower()
    for kw in CHAIN_KEYWORDS:
        # Word-boundary-ish guard so "gap" doesn't kill "Gappy's Boutique".
        # Most keywords are multi-word brand names; a few are short.
        if kw in {"gap", "villa", "express", "target"}:
            # Require the keyword as a standalone token.
            if re.search(rf"\b{re.escape(kw)}\b", low):
                return kw
        else:
            if kw in low:
                return kw
    return None


def is_junk_artifact(name: str) -> str | None:
    if not name or not name.strip():
        return "blank name"
    low = name.lower()
    for s in JUNK_SUBSTRINGS:
        if s in low:
            return f"junk substring '{s}'"
    if len(name) > 80:
        return "name >80 chars (scraped title)"
    return None


def brand_prefix(name: str) -> str:
    """First 3 tokens of the name, lowercased, stripped of paren-suffixes."""
    base = re.split(r"[(\-|–]", name, 1)[0].strip().lower()
    tokens = re.findall(r"[a-z0-9'&]+", base)
    if not tokens:
        return name.strip().lower()
    return " ".join(tokens[:3])


def first_token(name: str) -> str:
    base = re.split(r"[(\-|–]", name, 1)[0].strip().lower()
    tokens = re.findall(r"[a-z0-9'&]+", base)
    return tokens[0] if tokens else ""


def is_whitelisted(name: str) -> bool:
    low = name.lower()
    return any(w in low for w in LOCAL_BOUTIQUE_WHITELIST)


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    return fieldnames, rows


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean(path_in: Path, path_out: Path, label: str) -> dict:
    fieldnames, rows = load_rows(path_in)
    total_before = len(rows)

    removed_chain_kw: list[tuple[str, str]] = []
    removed_junk: list[tuple[str, str]] = []
    removed_freq: list[tuple[str, str]] = []
    survivors: list[dict] = []

    # First pass: chain keywords + junk artifacts.
    pass1_survivors: list[dict] = []
    for row in rows:
        name = (row.get("Store Name") or "").strip()
        kw = is_chain_keyword(name)
        if kw:
            removed_chain_kw.append((name, kw))
            continue
        junk = is_junk_artifact(name)
        if junk:
            removed_junk.append((name, junk))
            continue
        pass1_survivors.append(row)

    # Second pass: frequency-based chain removal.
    # Group by 3-word brand prefix; if >=5 occurrences AND not whitelisted, drop them.
    prefix_counts: Counter = Counter()
    for row in pass1_survivors:
        name = (row.get("Store Name") or "").strip()
        prefix_counts[brand_prefix(name)] += 1

    chain_prefixes: set[str] = set()
    for prefix, n in prefix_counts.items():
        if n < 5:
            continue
        # Whitelist check: examine any representative row using the prefix.
        sample = next(
            (r for r in pass1_survivors
             if brand_prefix((r.get("Store Name") or "").strip()) == prefix),
            None,
        )
        if sample and is_whitelisted((sample.get("Store Name") or "").strip()):
            continue
        # Single-word generic prefix like "the" / "los" — try the first token.
        if len(prefix.split()) < 2 and prefix in {"the", "los", "el", "la"}:
            continue
        chain_prefixes.add(prefix)

    for row in pass1_survivors:
        name = (row.get("Store Name") or "").strip()
        p = brand_prefix(name)
        if p in chain_prefixes:
            removed_freq.append((name, f"prefix '{p}' x{prefix_counts[p]}"))
            continue
        survivors.append(row)

    write_rows(path_out, fieldnames, survivors)

    return {
        "label": label,
        "input": str(path_in),
        "output": str(path_out),
        "total_before": total_before,
        "total_after": len(survivors),
        "removed_chain_kw": removed_chain_kw,
        "removed_junk": removed_junk,
        "removed_freq": removed_freq,
        "chain_prefixes": sorted(chain_prefixes),
        "prefix_counts": prefix_counts,
    }


def print_report(reports: list[dict]) -> None:
    print("=" * 78)
    print("GODSPEED STORE DATABASE — CLEANUP REPORT")
    print("=" * 78)
    grand_before = grand_after = 0
    for r in reports:
        print(f"\n### {r['label']}")
        print(f"  input : {r['input']}")
        print(f"  output: {r['output']}")
        print(f"  rows before : {r['total_before']}")
        print(f"  rows after  : {r['total_after']}")
        print(f"  removed     : {r['total_before'] - r['total_after']}")
        print(f"    - by chain keyword       : {len(r['removed_chain_kw'])}")
        print(f"    - by junk/artifact rule  : {len(r['removed_junk'])}")
        print(f"    - by 5+ frequency        : {len(r['removed_freq'])}")
        grand_before += r["total_before"]
        grand_after += r["total_after"]

    print("\n" + "-" * 78)
    print(f"GRAND TOTAL: {grand_before} -> {grand_after} "
          f"({grand_before - grand_after} removed)")
    print("-" * 78)

    # Detail: removed names grouped by reason.
    for r in reports:
        print(f"\n--- REMOVED NAMES [{r['label']}] ---")

        if r["removed_chain_kw"]:
            print(f"\n  [Chain keyword] ({len(r['removed_chain_kw'])} rows)")
            by_kw: dict[str, list[str]] = defaultdict(list)
            for name, kw in r["removed_chain_kw"]:
                by_kw[kw].append(name)
            for kw in sorted(by_kw):
                names = by_kw[kw]
                print(f"    * '{kw}' ({len(names)}): "
                      f"{', '.join(sorted(set(names))[:8])}"
                      f"{' ...' if len(set(names)) > 8 else ''}")

        if r["removed_junk"]:
            print(f"\n  [Junk/artifact] ({len(r['removed_junk'])} rows)")
            by_rule: dict[str, list[str]] = defaultdict(list)
            for name, reason in r["removed_junk"]:
                by_rule[reason].append(name)
            for reason in sorted(by_rule):
                names = by_rule[reason]
                shown = [n[:60] + ("..." if len(n) > 60 else "") for n in names[:6]]
                print(f"    * {reason} ({len(names)}): {', '.join(shown)}"
                      f"{' ...' if len(names) > 6 else ''}")

        if r["removed_freq"]:
            print(f"\n  [Chain by 5+ locations] ({len(r['removed_freq'])} rows)")
            by_prefix: dict[str, list[str]] = defaultdict(list)
            for name, reason in r["removed_freq"]:
                prefix = reason.split("'")[1] if "'" in reason else reason
                by_prefix[prefix].append(name)
            for prefix in sorted(by_prefix, key=lambda p: -len(by_prefix[p])):
                names = by_prefix[prefix]
                examples = sorted(set(names))[:5]
                print(f"    * '{prefix}' x{len(names)}: "
                      f"{', '.join(examples)}"
                      f"{' ...' if len(set(names)) > 5 else ''}")


def main() -> int:
    reports = []
    if not US_INPUT.exists():
        print(f"ERROR: US input missing: {US_INPUT}", file=sys.stderr)
        return 1
    reports.append(clean(US_INPUT, US_OUTPUT, "US stores"))

    if not CO_INPUT.exists():
        print(f"ERROR: Colombia input missing: {CO_INPUT}", file=sys.stderr)
        return 1
    reports.append(clean(CO_INPUT, CO_OUTPUT, "Colombia stores"))

    if SCORED_INPUT.exists():
        reports.append(clean(SCORED_INPUT, SCORED_OUTPUT, "Scored leads"))
    else:
        print(f"(note) {SCORED_INPUT.name} not present — skipping scored output.")

    print_report(reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
