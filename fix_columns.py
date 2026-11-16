"""
Column Fix Script — MASTER DATABASE
Raj Patel | El Barrio | 2026-04-23

PROBLEM: Instagram handles (@xyz) are sitting in column D (Country index 3)
         instead of column F (Instagram index 5).

STEPS:
  1. Audit first 20 rows and report findings
  2. Fix: move @handles from col D → col F, clear col D
  3. Skip rows where col F already has a value (keep col F, discard col D handle)
  4. Batch write corrected data back to sheet
"""

import json
import os
import time
from datetime import datetime

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")

# Column indices (0-based)
COL_D = 3   # Country / (incorrectly) Instagram handles
COL_F = 5   # Instagram (correct destination)

# ─── AUTH ─────────────────────────────────────────────────────────────────────

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
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file"
        ]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data["access_token"] = creds.token
        with open(TOKEN_PATH, "w") as f:
            json.dump(token_data, f, indent=2)
    return creds


def get_sheet():
    creds = get_creds()
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def _col(row, idx, default=''):
    try:
        return row[idx].strip() if len(row) > idx else default
    except Exception:
        return default


# ─── STEP 1: AUDIT ────────────────────────────────────────────────────────────

def audit(data_rows, sample=20):
    print()
    print("=" * 70)
    print(f"AUDIT — First {sample} data rows")
    print("=" * 70)
    print(f"{'#':<5} {'Store Name':<30} {'Col D (Country)':<25} {'Col F (Instagram)':<25}")
    print("-" * 70)

    ig_in_d_count = 0
    country_in_d_count = 0
    d_empty_count = 0
    f_has_value = 0
    both_have_value = 0

    for i, row in enumerate(data_rows[:sample]):
        store = _col(row, 0)[:28]
        col_d = _col(row, COL_D)
        col_f = _col(row, COL_F)

        d_is_ig = col_d.startswith('@') and len(col_d) > 2
        d_is_country = col_d.upper() in ('US', 'USA', 'UNITED STATES', 'U.S.', 'U.S.A.') or (col_d and not d_is_ig)

        flag = ''
        if d_is_ig:
            flag = '⚠️  IG IN COUNTRY'
            ig_in_d_count += 1
        elif not col_d:
            flag = '(D empty)'
            d_empty_count += 1
        else:
            flag = '✓ real country'
            country_in_d_count += 1

        if col_f:
            f_has_value += 1
            if d_is_ig:
                both_have_value += 1
                flag += ' + F filled'

        print(f"{i+1:<5} {store:<30} {col_d[:23]:<25} {col_f[:23]:<25}  {flag}")

    print()
    print("AUDIT SUMMARY (first 20 rows):")
    print(f"  Instagram handles in col D : {ig_in_d_count}")
    print(f"  Real country values in D   : {country_in_d_count}")
    print(f"  Col D empty                : {d_empty_count}")
    print(f"  Col F already has value    : {f_has_value}")
    print(f"  Both D and F have value    : {both_have_value}")
    print()


# ─── STEP 2: FIX ALL ROWS ─────────────────────────────────────────────────────

def fix_columns(data_rows):
    """
    For each row:
      - If col D starts with '@': move to col F (if F is empty), clear col D
      - If col F already has a value and D has @: discard D handle, keep F
      - Otherwise: leave the row untouched
    Returns: (fixed_d_col_values, fixed_f_col_values, stats)
    """
    fixed_d = []
    fixed_f = []

    moved_count = 0
    discarded_count = 0
    left_alone_count = 0

    for row in data_rows:
        col_d = _col(row, COL_D)
        col_f = _col(row, COL_F)

        d_is_ig = col_d.startswith('@') and len(col_d) > 2

        if d_is_ig:
            if col_f:
                # F already has a value — discard the D handle
                fixed_d.append([''])   # clear D
                fixed_f.append([col_f])  # keep F unchanged
                discarded_count += 1
            else:
                # Move D → F, clear D
                fixed_d.append([''])
                fixed_f.append([col_d])
                moved_count += 1
        else:
            # Not an Instagram handle in D — leave both untouched
            fixed_d.append([col_d])
            fixed_f.append([col_f])
            left_alone_count += 1

    stats = {
        'moved': moved_count,
        'discarded': discarded_count,
        'left_alone': left_alone_count,
        'total': len(data_rows),
    }
    return fixed_d, fixed_f, stats


# ─── WRITE BACK ───────────────────────────────────────────────────────────────

def write_column(ws, col_values, col_idx_1based, label, total):
    """Batch write a list of [value] lists to a specific column (1-based)."""
    start_cell = gspread.utils.rowcol_to_a1(2, col_idx_1based)
    end_cell = gspread.utils.rowcol_to_a1(len(col_values) + 1, col_idx_1based)
    rng = f"{start_cell}:{end_cell}"
    print(f"  Writing {label} to column {col_idx_1based} (range {rng})…")
    ws.update(rng, col_values)
    print(f"  → Done: {len(col_values)} rows written")
    time.sleep(2)  # Respect Sheets API rate limits


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now():%H:%M:%S}] Connecting to Google Sheets…")
    sheet = get_sheet()
    ws = sheet.worksheet("MASTER DATABASE")

    print(f"[{datetime.now():%H:%M:%S}] Reading MASTER DATABASE…")
    all_values = ws.get_all_values()
    headers = all_values[0]
    data_rows = all_values[1:]
    total = len(data_rows)
    print(f"  → {total} data rows loaded")
    print(f"  → Headers: {headers}")

    # Confirm actual header names for cols D and F (0-indexed: 3, 5)
    col_d_header = headers[COL_D] if len(headers) > COL_D else '(missing)'
    col_f_header = headers[COL_F] if len(headers) > COL_F else '(missing)'
    print(f"  → Col D (index 3) header: '{col_d_header}'")
    print(f"  → Col F (index 5) header: '{col_f_header}'")
    print()

    # ── STEP 1: AUDIT ─────────────────────────────────────────────────────────
    audit(data_rows, sample=20)

    # ── STEP 2: FIX COLUMNS ───────────────────────────────────────────────────
    print(f"[{datetime.now():%H:%M:%S}] Fixing columns across all {total} rows…")
    fixed_d, fixed_f, stats = fix_columns(data_rows)

    print()
    print("FIX STATS:")
    print(f"  ✅ Handles moved (D → F)         : {stats['moved']}")
    print(f"  🗑️  Handles discarded (F had value): {stats['discarded']}")
    print(f"  ✓  Rows left untouched           : {stats['left_alone']}")
    print(f"  Total rows processed             : {stats['total']}")
    print()

    if stats['moved'] + stats['discarded'] == 0:
        print("⚠️  No Instagram handles found in column D. No changes needed.")
        print("    Run aborted — sheet unchanged.")
        return stats

    # Write corrected Col D (Country) — cleared of @ handles
    write_column(ws, fixed_d, COL_D + 1, "Col D (Country, cleaned)", total)

    # Write corrected Col F (Instagram) — now populated
    write_column(ws, fixed_f, COL_F + 1, "Col F (Instagram, filled)", total)

    print()
    print("=" * 70)
    print(f"COLUMN FIX COMPLETE — {stats['moved']} handles moved, {stats['discarded']} discarded")
    print("=" * 70)

    return stats


if __name__ == "__main__":
    main()
