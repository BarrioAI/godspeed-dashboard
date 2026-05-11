#!/usr/bin/env python3
"""
Deep Clean: Godspeed Lead Database v2
Removes junk rows from MASTER DATABASE and ACQUISITION LEADS
Updated criteria: Remove chains (10+ locations), mono-brand flagships
Target: Independent boutiques, multi-brand streetwear shops
Author: Wilmar Barrios
Purpose: Pre-outreach quality control before Monday drop
"""

import json
import os
import csv
import re
from datetime import datetime
from typing import List, Tuple

import gspread
from google.oauth2.credentials import Credentials

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
TOKEN_PATH = "/Users/elbarrio/.openclaw/drive-token.json"
CREDS_PATH = "/Users/elbarrio/.openclaw/google-credentials.json"

BACKUP_PATH = "/Users/elbarrio/.openclaw/workspace/godspeed-dashboard/data/master_backup_pre_deepclean.csv"

# ─────────────────────────────────────────
#  JUNK DETECTION: KEYWORDS & CRITERIA
# ─────────────────────────────────────────

JUNK_KEYWORDS = {
    "auto": [
        "dealership", "automotive", "car dealer", "car sales", "car wash", "car inventory",
        "auto dealer", "auto sales", "auto repair", "auto shop", "auto group", "auto value",
        "nissan", "gmc", "buick", "honda", "toyota", "chevy", "chevrolet", "ford motors",
        "car rental", "tires", "mechanic", "transmission", "oil change"
    ],
    "food": [
        "restaurant", "cafe", "coffee", "pizza", "taco", "sushi", "bar", "grill", 
        "bakery", "diner", "eatery", "catering", "burger", "sandwich", "donut",
        "pancake", "wing", "bbq", "barbeque", "ramen", "pasta", "deli"
    ],
    "medical": [
        "dental", "dentist", "clinic", "medical", "therapy", "spa", "salon", 
        "massage", "chiropractic", "pharmacy", "urgent care", "physical therapy",
        "doctor", "physician", "hospital", "orthopedic"
    ],
    "jobs": [
        "careers", "jobs", "hiring", "staffing", "recruiter", "recruitment",
        "employment", "career opportunity", "now hiring"
    ],
    "other": [
        "real estate", "realtor", "mortgage", "bank", "financial", "insurance",
        "attorney", "law firm", "legal", "school", "university", "college",
        "church", "nonprofit", "charity", "government", "post office"
    ]
}

# Flatten for easier checking
JUNK_KEYWORDS_FLAT = []
for category, keywords in JUNK_KEYWORDS.items():
    JUNK_KEYWORDS_FLAT.extend(keywords)

# ─────────────────────────────────────────
#  CHAIN STORES TO REMOVE (10+ locations nationally)
# ─────────────────────────────────────────
CHAIN_STORES_TO_REMOVE = [
    "kith", "dtlr", "shoe gallery", "snipes",
    "foot locker", "footlocker", "foot-locker", "foot locker shoes",
    "foot action", "footaction",
    "finish line", "finish-line", "finishline",
    "hibbett", "hibbett sports",
    "dillards", "dillard's",
    "macy's", "macys", "nordstrom", "saks", "saks fifth",
    "champs sports", "champs",
    "journeys", "journeys shoes",
    "jd sports", "jd sport",
    "jcpenney", "jc penney",
    "target", "walmart", "dick's sporting", "dicks sporting",
    "athletics", "modells", "modell's",
    "sports authority",
    "eastbay",
    "zappos",
    "shoe carnival",
    "payless",
    "famous footwear",
    "dsw",
]

# ─────────────────────────────────────────
#  MONO-BRAND FLAGSHIP STORES TO REMOVE
#  (Stores that ONLY carry one brand)
# ─────────────────────────────────────────
MONO_BRAND_KEYWORDS = [
    "nike store", "nike retail", "nike only",
    "adidas store", "adidas shop", "adidas retail",
    "puma store", "puma shop",
    "jordan store", "jordan retail",
    "off-white store", "off white store", "off white retail",
    "supreme store", "supreme retail",
    "bape store", "bape retail", "bape shop", "bape only",
    "vans store", "vans shop",
    "converse store", "converse shop",
    "new balance store", "new balance retail",
    "reebok store", "reebok shop",
    "asics store", "asics shop",
    "under armour store", "under armour retail",
    "saucony store",
    "brooks store",
]

# ─────────────────────────────────────────
#  KEEP INDICATORS
#  Stores with these keywords are likely legitimate independents
# ─────────────────────────────────────────
KEEPER_INDICATORS = [
    "boutique", "independent", "local", "family-owned", "family owned",
    "consignment", "vintage", "thrift", "resale",
    "multi-brand", "multibrand", "multi brand",
    "kicks", "sole", "collection", "collective",
    "closet", "swap", "exchange",
]

# ─────────────────────────────────────────
#  AUTH HELPERS
# ─────────────────────────────────────────

def get_creds():
    """Load and refresh Google credentials."""
    with open(TOKEN_PATH) as f:
        token_data = json.load(f)
    with open(CREDS_PATH) as f:
        creds_data = json.load(f)

    installed = creds_data.get("installed", creds_data)

    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=installed["client_id"],
        client_secret=installed["client_secret"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    return creds


def get_sheet_client():
    """Authenticate and return gspread client."""
    creds = get_creds()
    return gspread.authorize(creds)


# ─────────────────────────────────────────
#  JUNK DETECTION LOGIC
# ─────────────────────────────────────────

def is_junk_row(row: dict) -> Tuple[bool, str]:
    """
    Determine if a row should be removed.
    Returns (is_junk, reason).
    
    REMOVAL CRITERIA:
    1. Missing store name or broken data
    2. Matches food/auto/medical/jobs/other junk keywords
    3. Is a chain store (10+ locations)
    4. Is a mono-brand flagship store
    
    KEEP IF:
    - Has keeper indicator words (boutique, consignment, vintage, etc.)
    """
    
    # Safe conversion to string + strip
    def safe_str(val):
        if val is None:
            return ""
        return str(val).strip()
    
    store_name = safe_str(row.get("Store Name", ""))
    city = safe_str(row.get("City", ""))
    state = safe_str(row.get("State", ""))
    description = safe_str(row.get("Store Description", ""))
    category = safe_str(row.get("Category", ""))
    address = safe_str(row.get("Address", ""))
    
    # Missing store name = junk
    if not store_name:
        return True, "Missing Store Name"
    
    # Combine all text fields for keyword matching
    full_text = " ".join([
        store_name.lower(),
        city.lower(),
        state.lower(),
        description.lower(),
        category.lower(),
        address.lower()
    ])
    
    # Check for broken data patterns
    if store_name == "N/A" or store_name == "NA" or store_name == "undefined":
        return True, "Broken data: invalid store name"
    
    if len(store_name) < 2:
        return True, "Broken data: store name too short"
    
    # ─────────────────────────────────────────
    #  CHECK: Is this a KEEPER (boutique/independent/consignment)?
    # ─────────────────────────────────────────
    for keeper in KEEPER_INDICATORS:
        if keeper.lower() in full_text:
            # Found a keeper indicator — but still check for mono-brand
            # (e.g., "Supreme Boutique" should still be removed)
            for mono_brand in MONO_BRAND_KEYWORDS:
                if mono_brand.lower() in full_text:
                    return True, f"Mono-brand flagship: '{mono_brand}'"
            # Not a mono-brand, so keep it
            return False, ""
    
    # ─────────────────────────────────────────
    #  CHECK: Is this a CHAIN STORE?
    # ─────────────────────────────────────────
    for chain in CHAIN_STORES_TO_REMOVE:
        if chain.lower() in full_text:
            return True, f"Chain store: '{chain}'"
    
    # ─────────────────────────────────────────
    #  CHECK: Is this a MONO-BRAND FLAGSHIP?
    # ─────────────────────────────────────────
    for mono_brand in MONO_BRAND_KEYWORDS:
        if mono_brand.lower() in full_text:
            return True, f"Mono-brand flagship: '{mono_brand}'"
    
    # ─────────────────────────────────────────
    #  CHECK: Generic junk keywords
    # ─────────────────────────────────────────
    for keyword in JUNK_KEYWORDS_FLAT:
        if keyword.lower() in full_text:
            return True, f"Junk keyword: '{keyword}'"
    
    # ─────────────────────────────────────────
    #  If we got here: likely a legitimate retail store
    #  But we're being CONSERVATIVE — if it doesn't have clear indicators,
    #  it might be a chain we don't have in our list.
    #  KEEP it if it has ANY of: address, city, state (real business info)
    # ─────────────────────────────────────────
    
    has_address = bool(address and address != "N/A")
    has_city = bool(city and city != "N/A")
    
    if has_address and has_city:
        return False, ""  # Looks like a real store
    
    # No address/city info + no clear category = questionable
    # But be generous and keep it (Goldie can review manually)
    return False, ""


# ─────────────────────────────────────────
#  CLEANING LOGIC
# ─────────────────────────────────────────

def clean_sheet(sheet_name: str) -> dict:
    """
    Clean a single sheet. Remove junk rows, save backup, return stats.
    """
    
    print(f"\n{'='*70}")
    print(f"CLEANING: {sheet_name}")
    print(f"{'='*70}\n")
    
    client = get_sheet_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(sheet_name)
    
    # Get all rows
    all_rows = worksheet.get_all_records()
    print(f"Total rows in {sheet_name}: {len(all_rows)}")
    
    # Backup before cleaning (for MASTER DATABASE only)
    if sheet_name == "MASTER DATABASE" and all_rows:
        os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
        with open(BACKUP_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"✓ Backup saved: {BACKUP_PATH}\n")
    
    # Identify rows to remove
    rows_to_remove = []
    rows_to_keep = []
    
    for idx, row in enumerate(all_rows, start=2):  # start=2 because row 1 is headers
        is_junk, reason = is_junk_row(row)
        if is_junk:
            rows_to_remove.append((idx, row, reason))
        else:
            rows_to_keep.append((idx, row))
    
    print(f"Rows to remove: {len(rows_to_remove)}")
    print(f"Rows to keep: {len(rows_to_keep)}")
    
    # Print first 20 rows to be removed for spot-checking
    if rows_to_remove:
        print(f"\n{'─'*70}")
        print("FIRST 20 ROWS TO BE REMOVED (spot-check):")
        print(f"{'─'*70}\n")
        for i, (idx, row, reason) in enumerate(rows_to_remove[:20], 1):
            print(f"{i}. [Row {idx}] {row.get('Store Name', 'N/A')} | {row.get('City', 'N/A')}, {row.get('State', 'N/A')}")
            print(f"   Reason: {reason}")
            print()
    
    # Delete rows (from bottom to top to avoid index shifting)
    print(f"\n{'─'*70}")
    print("DELETING JUNK ROWS...")
    print(f"{'─'*70}\n")
    
    deleted_count = 0
    for row_num, _, _ in reversed(rows_to_remove):
        try:
            worksheet.delete_rows(row_num, 1)
            deleted_count += 1
            if deleted_count % 10 == 0:
                print(f"  Deleted {deleted_count}/{len(rows_to_remove)} rows...")
        except Exception as e:
            print(f"ERROR deleting row {row_num}: {e}")
    
    print(f"  Deleted total: {deleted_count}/{len(rows_to_remove)} rows")
    
    # Summary
    print(f"\n{'='*70}")
    print(f"SUMMARY: {sheet_name}")
    print(f"{'='*70}")
    print(f"Removed: {len(rows_to_remove)} junk/chain/mono-brand rows")
    print(f"Kept: {len(rows_to_keep)} legitimate independent/boutique retailers")
    print(f"Final count: {len(rows_to_keep)} rows")
    print(f"{'='*70}\n")
    
    return {
        "sheet": sheet_name,
        "removed": len(rows_to_remove),
        "kept": len(rows_to_keep),
        "removed_samples": [
            {
                "store": row.get("Store Name", "N/A"),
                "city": row.get("City", "N/A"),
                "state": row.get("State", "N/A"),
                "reason": reason
            }
            for _, row, reason in rows_to_remove[:5]
        ]
    }


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    print("\n" + "="*70)
    print("GODSPEED DEEP CLEAN v2 — Remove Chains & Mono-Brand Stores")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    print("TARGETING: Independent boutiques, multi-brand streetwear, consignment")
    print("REMOVING: Chains (10+ locations), mono-brand flagships\n")
    
    results = []
    
    # Clean MASTER DATABASE first
    try:
        result = clean_sheet("MASTER DATABASE")
        results.append(result)
    except Exception as e:
        print(f"ERROR cleaning MASTER DATABASE: {e}")
        results.append({
            "sheet": "MASTER DATABASE",
            "error": str(e)
        })
    
    # Clean ACQUISITION LEADS second
    try:
        result = clean_sheet("ACQUISITION LEADS")
        results.append(result)
    except Exception as e:
        print(f"ERROR cleaning ACQUISITION LEADS: {e}")
        results.append({
            "sheet": "ACQUISITION LEADS",
            "error": str(e)
        })
    
    # Final report
    print("\n" + "="*70)
    print("FINAL REPORT")
    print("="*70 + "\n")
    
    total_removed = 0
    total_kept = 0
    
    for result in results:
        if "error" in result:
            print(f"✗ {result['sheet']}: ERROR - {result['error']}")
        else:
            print(f"✓ {result['sheet']}")
            print(f"  - Removed: {result['removed']} (chains, mono-brand, junk)")
            print(f"  - Kept: {result['kept']} (independent, boutique, multi-brand)")
            total_removed += result['removed']
            total_kept += result['kept']
    
    print(f"\n{'─'*70}")
    print(f"TOTAL IMPACT:")
    print(f"  - Rows removed: {total_removed}")
    print(f"  - Rows kept: {total_kept}")
    print(f"  - Backup saved: {BACKUP_PATH}")
    print(f"  - Target: {total_kept} qualified boutique/streetwear accounts")
    print(f"{'─'*70}\n")
    
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    return results


if __name__ == "__main__":
    main()
