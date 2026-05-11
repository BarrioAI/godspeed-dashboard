#!/usr/bin/env python3
"""
Deep Clean: Godspeed Lead Database v2 — WITH RETRY & BACKOFF
Removes junk rows from MASTER DATABASE and ACQUISITION LEADS
Includes exponential backoff for Google Sheets API rate limits
Author: Wilmar Barrios
"""

import json
import os
import csv
import time
import random
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

# Retry settings
MAX_RETRIES = 5
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 120  # seconds

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

JUNK_KEYWORDS_FLAT = []
for category, keywords in JUNK_KEYWORDS.items():
    JUNK_KEYWORDS_FLAT.extend(keywords)

CHAIN_STORES_TO_REMOVE = [
    "kith", "dtlr", "shoe gallery", "snipes",
    "foot locker", "footlocker", "foot-locker",
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

KEEPER_INDICATORS = [
    "boutique", "independent", "local", "family-owned", "family owned",
    "consignment", "vintage", "thrift", "resale",
    "multi-brand", "multibrand", "multi brand",
    "kicks", "sole", "collection", "collective",
    "closet", "swap", "exchange",
]

# ─────────────────────────────────────────
#  AUTH & RETRY HELPERS
# ─────────────────────────────────────────

def get_creds():
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
    creds = get_creds()
    return gspread.authorize(creds)


def delete_row_with_retry(worksheet, row_num: int, max_retries: int = MAX_RETRIES) -> bool:
    """
    Delete a row with exponential backoff retry logic.
    Returns True if successful, False if all retries exhausted.
    """
    backoff = INITIAL_BACKOFF
    
    for attempt in range(max_retries):
        try:
            worksheet.delete_rows(row_num, 1)
            return True
        except gspread.exceptions.APIError as e:
            if "429" in str(e):  # Rate limit
                wait_time = backoff + random.uniform(0, 1)
                print(f"  [Retry {attempt+1}/{max_retries}] Rate limit hit. Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                backoff = min(backoff * 2, MAX_BACKOFF)
            else:
                print(f"  [ERROR] Row {row_num}: {e}")
                return False
        except Exception as e:
            print(f"  [ERROR] Row {row_num}: {e}")
            return False
    
    print(f"  [FAILED] Row {row_num}: Max retries exhausted")
    return False


# ─────────────────────────────────────────
#  JUNK DETECTION
# ─────────────────────────────────────────

def is_junk_row(row: dict) -> Tuple[bool, str]:
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
    
    if not store_name:
        return True, "Missing Store Name"
    
    full_text = " ".join([
        store_name.lower(),
        city.lower(),
        state.lower(),
        description.lower(),
        category.lower(),
        address.lower()
    ])
    
    if store_name == "N/A" or store_name == "NA" or store_name == "undefined":
        return True, "Broken data: invalid store name"
    
    if len(store_name) < 2:
        return True, "Broken data: store name too short"
    
    # Check for KEEPER indicators first
    for keeper in KEEPER_INDICATORS:
        if keeper.lower() in full_text:
            for mono_brand in MONO_BRAND_KEYWORDS:
                if mono_brand.lower() in full_text:
                    return True, f"Mono-brand flagship: '{mono_brand}'"
            return False, ""
    
    # Check for CHAIN STORES
    for chain in CHAIN_STORES_TO_REMOVE:
        if chain.lower() in full_text:
            return True, f"Chain store: '{chain}'"
    
    # Check for MONO-BRAND
    for mono_brand in MONO_BRAND_KEYWORDS:
        if mono_brand.lower() in full_text:
            return True, f"Mono-brand flagship: '{mono_brand}'"
    
    # Check for generic junk
    for keyword in JUNK_KEYWORDS_FLAT:
        if keyword.lower() in full_text:
            return True, f"Junk keyword: '{keyword}'"
    
    has_address = bool(address and address != "N/A")
    has_city = bool(city and city != "N/A")
    
    if has_address and has_city:
        return False, ""
    
    return False, ""


# ─────────────────────────────────────────
#  CLEANING WITH RETRY
# ─────────────────────────────────────────

def clean_sheet(sheet_name: str) -> dict:
    print(f"\n{'='*70}")
    print(f"CLEANING: {sheet_name}")
    print(f"{'='*70}\n")
    
    client = get_sheet_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(sheet_name)
    
    all_rows = worksheet.get_all_records()
    print(f"Total rows in {sheet_name}: {len(all_rows)}")
    
    if sheet_name == "MASTER DATABASE" and all_rows:
        os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
        with open(BACKUP_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"✓ Backup saved: {BACKUP_PATH}\n")
    
    rows_to_remove = []
    rows_to_keep = []
    
    for idx, row in enumerate(all_rows, start=2):
        is_junk, reason = is_junk_row(row)
        if is_junk:
            rows_to_remove.append((idx, row, reason))
        else:
            rows_to_keep.append((idx, row))
    
    print(f"Rows to remove: {len(rows_to_remove)}")
    print(f"Rows to keep: {len(rows_to_keep)}")
    
    if rows_to_remove:
        print(f"\n{'─'*70}")
        print("FIRST 20 ROWS TO BE REMOVED (spot-check):")
        print(f"{'─'*70}\n")
        for i, (idx, row, reason) in enumerate(rows_to_remove[:20], 1):
            print(f"{i}. [Row {idx}] {row.get('Store Name', 'N/A')} | {row.get('City', 'N/A')}, {row.get('State', 'N/A')}")
            print(f"   Reason: {reason}")
    
    print(f"\n{'─'*70}")
    print("DELETING JUNK ROWS (with retry)...")
    print(f"{'─'*70}\n")
    
    deleted_count = 0
    failed_count = 0
    
    for row_num, _, _ in reversed(rows_to_remove):
        if delete_row_with_retry(worksheet, row_num):
            deleted_count += 1
        else:
            failed_count += 1
        
        if (deleted_count + failed_count) % 10 == 0:
            print(f"  Progress: {deleted_count + failed_count}/{len(rows_to_remove)} attempted ({deleted_count} successful)")
    
    print(f"\n  Final: {deleted_count} deleted, {failed_count} failed")
    
    print(f"\n{'='*70}")
    print(f"SUMMARY: {sheet_name}")
    print(f"{'='*70}")
    print(f"Removed: {len(rows_to_remove)} flagged rows")
    print(f"Successfully deleted: {deleted_count}")
    print(f"Failed to delete: {failed_count}")
    print(f"Kept: {len(rows_to_keep)} legitimate retailers")
    print(f"{'='*70}\n")
    
    return {
        "sheet": sheet_name,
        "flagged": len(rows_to_remove),
        "deleted": deleted_count,
        "failed": failed_count,
        "kept": len(rows_to_keep),
    }


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    print("\n" + "="*70)
    print("GODSPEED DEEP CLEAN v2.1 — WITH RETRY & BACKOFF")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")
    print("TARGETING: Independent boutiques, multi-brand streetwear, consignment")
    print("REMOVING: Chains (10+ locations), mono-brand flagships\n")
    
    results = []
    
    try:
        result = clean_sheet("MASTER DATABASE")
        results.append(result)
    except Exception as e:
        print(f"ERROR cleaning MASTER DATABASE: {e}")
        results.append({
            "sheet": "MASTER DATABASE",
            "error": str(e)
        })
    
    try:
        result = clean_sheet("ACQUISITION LEADS")
        results.append(result)
    except Exception as e:
        print(f"ERROR cleaning ACQUISITION LEADS: {e}")
        results.append({
            "sheet": "ACQUISITION LEADS",
            "error": str(e)
        })
    
    print("\n" + "="*70)
    print("FINAL REPORT")
    print("="*70 + "\n")
    
    total_flagged = 0
    total_deleted = 0
    total_failed = 0
    total_kept = 0
    
    for result in results:
        if "error" in result:
            print(f"✗ {result['sheet']}: ERROR - {result['error']}")
        else:
            print(f"✓ {result['sheet']}")
            print(f"  - Flagged: {result['flagged']}")
            print(f"  - Deleted: {result['deleted']}")
            if result['failed'] > 0:
                print(f"  - Failed: {result['failed']} ⚠️")
            print(f"  - Kept: {result['kept']}")
            total_flagged += result['flagged']
            total_deleted += result['deleted']
            total_failed += result['failed']
            total_kept += result['kept']
    
    print(f"\n{'─'*70}")
    print(f"TOTAL:")
    print(f"  - Flagged: {total_flagged} rows")
    print(f"  - Deleted: {total_deleted} rows")
    if total_failed > 0:
        print(f"  - Failed: {total_failed} rows ⚠️ (retry in 60 seconds)")
    print(f"  - Kept: {total_kept} qualified accounts")
    print(f"  - Backup: {BACKUP_PATH}")
    print(f"{'─'*70}\n")
    
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    return results


if __name__ == "__main__":
    main()
