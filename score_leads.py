"""
Godspeed Lead Scoring System
Built by Vito Corleone — El Barrio Data Intelligence
Scoring criteria per Goldie's exact specification (2026-04-23)

COLUMN MAP (MASTER DATABASE):
  0  Store Name
  1  City
  2  State
  3  Country  ← often holds @instagram handles (data quirk)
  4  Website
  5  Instagram
  6  Email
  7  Phone
  8  Carries Supreme
  9  Carries Hellstar
  10 Carries Godspeed
  11 Last Order Date  ← actually holds store descriptions / brand notes
  12 Outreach Status
  13 Outreach Channel
  14 Notes
  15 Date Added

Brand data lives in col[11] (description field) + col[8]/col[9] dedicated columns.
Instagram: col[5] OR col[3] if it starts with @
Email: col[6] only if it contains a valid email pattern
"""

import json
import os
import re
import csv
import time
from datetime import datetime

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ─── CONFIG ───────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")
TOP50_CSV = os.path.join(OUTPUT_DIR, "top50_priority_leads.csv")

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

# ─── SCORING ENGINE ───────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r'[\w.+\-]+@[\w\-]+\.[a-z]{2,}', re.I)

# Broad streetwear/fashion signals for "no brands" penalty
STREETWEAR_SIGNALS = [
    'hellstar', 'rhude', 'vale forever', 'supreme', 'denim tears', 'sp5der',
    'gallery dept', 'off-white', 'fear of god', 'bape', 'amiri', 'chrome hearts',
    'nike', 'jordan', 'adidas', 'new balance', 'kith', 'palace', 'stussy',
    'carhartt', 'yeezy', 'travis scott', 'essentials', 'fog', 'vlone',
    'anti social social club', 'huf', 'thrasher', 'vans', 'converse',
    'streetwear', 'sneaker', 'hypebeast', 'skate', 'hype', 'kicks',
    'boutique', 'luxury', 'designer', 'fashion', 'apparel', 'clothing',
]

def _col(row, idx, default=''):
    """Safe column accessor."""
    try:
        return row[idx].strip() if len(row) > idx else default
    except Exception:
        return default

def detect_instagram(row):
    """Instagram: col[5] OR col[3] if it starts with @."""
    ig_col = _col(row, 5)
    country_col = _col(row, 3)
    if ig_col:
        return ig_col
    if country_col.startswith('@') and len(country_col) > 2:
        return country_col
    return ''

def detect_email(row):
    """Email: col[6] must match an actual email pattern."""
    raw = _col(row, 6)
    if EMAIL_RE.search(raw):
        return raw
    return ''

def is_current_account(row):
    """Flag rows that already carry Godspeed."""
    carries_gs = _col(row, 10).lower()
    if carries_gs in ('yes', 'true', '1'):
        return True
    full_text = ' '.join(row).lower()
    # Only flag if explicitly mentioned as carrying it
    if 'carries godspeed' in full_text or 'godspeed account' in full_text:
        return True
    return False

def score_row(row):
    """
    Score a single row per Goldie's exact system.
    Returns (score: int, tier: str, reasons: list, ig: str, email: str, brands_found: list)
    Returns None if current account.
    """
    if is_current_account(row):
        return None  # Current account — do not score

    full_text = ' '.join(row).lower()
    score = 0
    reasons = []
    brands_found = []

    # ── POSITIVE SIGNALS ──────────────────────────────────────────────────────

    # Hellstar +25
    carries_hellstar = _col(row, 9).lower() in ('yes', 'true', '1')
    if carries_hellstar or 'hellstar' in full_text:
        score += 25
        reasons.append('Hellstar +25')
        brands_found.append('Hellstar')

    # Rhude +20
    if 'rhude' in full_text:
        score += 20
        reasons.append('Rhude +20')
        brands_found.append('Rhude')

    # Vale Forever +20
    if 'vale forever' in full_text:
        score += 20
        reasons.append('Vale Forever +20')
        brands_found.append('Vale Forever')

    # Supreme +15
    carries_supreme = _col(row, 8).lower() in ('yes', 'true', '1')
    if carries_supreme or 'supreme' in full_text:
        score += 15
        reasons.append('Supreme +15')
        brands_found.append('Supreme')

    # Denim Tears +15
    if 'denim tears' in full_text:
        score += 15
        reasons.append('Denim Tears +15')
        brands_found.append('Denim Tears')

    # Sp5der +15
    if 'sp5der' in full_text:
        score += 15
        reasons.append('Sp5der +15')
        brands_found.append('Sp5der')

    # Gallery Dept +15
    if 'gallery dept' in full_text:
        score += 15
        reasons.append('Gallery Dept +15')
        brands_found.append('Gallery Dept')

    # Instagram +10
    ig = detect_instagram(row)
    if ig:
        score += 10
        reasons.append('Instagram +10')

    # Email +10
    email = detect_email(row)
    if email:
        score += 10
        reasons.append('Email +10')

    # ── NEGATIVE SIGNALS ──────────────────────────────────────────────────────

    # No streetwear brands at all → -40
    has_streetwear = any(signal in full_text for signal in STREETWEAR_SIGNALS)
    if not has_streetwear:
        score -= 40
        reasons.append('No streetwear signals -40')

    # ── TIER ASSIGNMENT ───────────────────────────────────────────────────────
    if score >= 40:
        tier = '🔥 TIER 1 — Hot'
    elif score >= 20:
        tier = '⭐ TIER 2 — Strong'
    elif score >= 1:
        tier = '📋 TIER 3 — Warm'
    else:
        tier = '❄️ TIER 4 — Cold'

    return score, tier, reasons, ig, email, brands_found

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

    # Ensure output dir exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── SCORE ALL ROWS ────────────────────────────────────────────────────────
    print(f"[{datetime.now():%H:%M:%S}] Scoring leads…")

    score_col = []    # values to write back for "Lead Score"
    tier_col = []     # values to write back for "Priority Tier"
    current_accounts = []
    scored_leads = []  # (row_idx, store_name, city, state, ig, email, phone, score, tier, reasons, brands)

    tier_counts = {'TIER 1': 0, 'TIER 2': 0, 'TIER 3': 0, 'TIER 4': 0, 'CURRENT': 0, 'EMPTY': 0}

    for i, row in enumerate(data_rows):
        store_name = _col(row, 0)
        if not store_name:
            score_col.append([''])
            tier_col.append([''])
            tier_counts['EMPTY'] += 1
            continue

        result = score_row(row)

        if result is None:
            # Current account
            score_col.append(['—'])
            tier_col.append(['🏷️ CURRENT ACCOUNT'])
            tier_counts['CURRENT'] += 1
            current_accounts.append({
                'store': store_name,
                'city': _col(row, 1),
                'state': _col(row, 2),
            })
        else:
            score, tier, reasons, ig, email, brands_found = result
            score_col.append([score])
            tier_col.append([tier])

            if '🔥' in tier:
                tier_counts['TIER 1'] += 1
            elif '⭐' in tier:
                tier_counts['TIER 2'] += 1
            elif '📋' in tier:
                tier_counts['TIER 3'] += 1
            else:
                tier_counts['TIER 4'] += 1

            scored_leads.append({
                'row_idx': i,
                'Store Name': store_name,
                'City': _col(row, 1),
                'State': _col(row, 2),
                'Instagram': ig,
                'Email': email,
                'Phone': _col(row, 7),
                'Lead Score': score,
                'Priority Tier': tier,
                'Brands Carried': ', '.join(brands_found),
                'Score Reasons': ' | '.join(reasons),
            })

        if (i + 1) % 500 == 0:
            print(f"  → Scored {i+1}/{total}…")

    print(f"[{datetime.now():%H:%M:%S}] Scoring complete.")
    print(f"  Tier 1: {tier_counts['TIER 1']} | Tier 2: {tier_counts['TIER 2']} | "
          f"Tier 3: {tier_counts['TIER 3']} | Tier 4: {tier_counts['TIER 4']} | "
          f"Current Accounts: {tier_counts['CURRENT']} | Empty rows: {tier_counts['EMPTY']}")

    # ── CHECK / ADD HEADER COLUMNS ─────────────────────────────────────────────
    print(f"[{datetime.now():%H:%M:%S}] Updating sheet headers…")
    score_header_col = None
    tier_header_col = None

    for idx, h in enumerate(headers):
        if h.strip().lower() == 'lead score':
            score_header_col = idx + 1  # 1-based
        if h.strip().lower() == 'priority tier':
            tier_header_col = idx + 1   # 1-based

    # Add headers if missing
    next_col = len(headers) + 1  # 1-based col after last existing header
    if score_header_col is None:
        score_header_col = next_col
        next_col += 1
        # Write header cell
        ws.update_cell(1, score_header_col, 'Lead Score')
        print(f"  → Added 'Lead Score' header at col {score_header_col}")
        time.sleep(1)

    if tier_header_col is None:
        tier_header_col = next_col
        ws.update_cell(1, tier_header_col, 'Priority Tier')
        print(f"  → Added 'Priority Tier' header at col {tier_header_col}")
        time.sleep(1)

    # ── BATCH WRITE SCORES ─────────────────────────────────────────────────────
    print(f"[{datetime.now():%H:%M:%S}] Writing Lead Scores to sheet (col {score_header_col})…")
    score_range = gspread.utils.rowcol_to_a1(2, score_header_col) + ':' + gspread.utils.rowcol_to_a1(len(score_col) + 1, score_header_col)
    ws.update(score_range, score_col)
    print(f"  → Wrote {len(score_col)} score values")
    time.sleep(2)

    print(f"[{datetime.now():%H:%M:%S}] Writing Priority Tiers to sheet (col {tier_header_col})…")
    tier_range = gspread.utils.rowcol_to_a1(2, tier_header_col) + ':' + gspread.utils.rowcol_to_a1(len(tier_col) + 1, tier_header_col)
    ws.update(tier_range, tier_col)
    print(f"  → Wrote {len(tier_col)} tier values")
    time.sleep(1)

    # ── TOP 50 CSV (Tier 1 + top Tier 2) ──────────────────────────────────────
    print(f"[{datetime.now():%H:%M:%S}] Generating Top 50 CSV…")
    # Sort by score descending
    sorted_leads = sorted(scored_leads, key=lambda x: x['Lead Score'], reverse=True)
    # Filter: Tier 1 and Tier 2 only
    priority_leads = [l for l in sorted_leads if l['Lead Score'] >= 20]
    top50 = priority_leads[:50]

    csv_fields = ['Store Name', 'City', 'State', 'Instagram', 'Email', 'Phone',
                  'Lead Score', 'Priority Tier', 'Brands Carried', 'Score Reasons']
    with open(TOP50_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(top50)
    print(f"  → Saved {len(top50)} leads to {TOP50_CSV}")

    # ── FINAL REPORT ──────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("GODSPEED LEAD SCORING REPORT")
    print(f"Run: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 65)

    print(f"\n📊 TIER BREAKDOWN (of {total} rows):")
    print(f"  🔥 TIER 1 (40+ pts)  — {tier_counts['TIER 1']:>5} leads")
    print(f"  ⭐ TIER 2 (20–39 pts) — {tier_counts['TIER 2']:>5} leads")
    print(f"  📋 TIER 3 (1–19 pts)  — {tier_counts['TIER 3']:>5} leads")
    print(f"  ❄️  TIER 4 (≤0 pts)    — {tier_counts['TIER 4']:>5} leads")
    print(f"  🏷️  CURRENT ACCOUNTS   — {tier_counts['CURRENT']:>5}")
    print(f"  ⬜ EMPTY ROWS          — {tier_counts['EMPTY']:>5}")

    print(f"\n🏆 TOP 10 LEADS BY SCORE:")
    for rank, lead in enumerate(sorted_leads[:10], 1):
        print(f"  {rank:>2}. {lead['Store Name'][:35]:<35} | {lead['City'][:20]:<20} | "
              f"Score: {lead['Lead Score']:>3} | {lead['Score Reasons']}")

    # Data gap analysis
    total_scored = len(scored_leads)
    has_email_count = sum(1 for l in scored_leads if l['Email'])
    has_ig_count = sum(1 for l in scored_leads if l['Instagram'])
    has_brands_count = sum(1 for l in scored_leads if l['Brands Carried'])

    print(f"\n⚠️  DATA GAP ANALYSIS (of {total_scored} scored leads):")
    print(f"  Has Instagram  : {has_ig_count:>5} ({has_ig_count/total_scored*100:.1f}%)")
    print(f"  Has Email      : {has_email_count:>5} ({has_email_count/total_scored*100:.1f}%)")
    print(f"  Has Brand Info : {has_brands_count:>5} ({has_brands_count/total_scored*100:.1f}%)")
    print(f"  Missing Email  : {total_scored - has_email_count:>5} ({(total_scored - has_email_count)/total_scored*100:.1f}%) — OUTREACH GAP")

    if current_accounts:
        print(f"\n🏷️  CURRENT ACCOUNTS (flagged, not scored): {len(current_accounts)}")
        for ca in current_accounts[:10]:
            print(f"  - {ca['store']} ({ca['city']}, {ca['state']})")

    print(f"\n📁 Top 50 CSV saved to: {TOP50_CSV}")
    print("=" * 65)

    return tier_counts, sorted_leads[:10]


if __name__ == "__main__":
    main()
