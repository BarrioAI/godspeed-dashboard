"""
Godspeed Sheets Sync — push clean CSV (data/godspeed_leads_final.csv)
into the STORES tab of the dashboard spreadsheet.

Maps CSV columns -> snake_case Sheet columns the dashboard expects.
Clears the STORES tab (keeps the header row) then appends in chunks of 500
with a 2-second pause between chunks to stay under gspread/Sheets rate limits.

Auth mirrors clean_live_sheet.py / app.py (OAuth user creds at
~/.openclaw/drive-token.json + google-credentials.json).
"""

import os
import csv
import json
import time
from datetime import datetime

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
STORES_SHEET   = "STORES"
CSV_PATH       = "data/godspeed_leads_final.csv"
CHUNK_SIZE     = 500
SLEEP_BETWEEN  = 2.0

TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")

# Sheet column order (snake_case) — must match what app.py reads.
SHEET_HEADERS = [
    "store_name",
    "city",
    "market",
    "country",
    "website",
    "instagram",
    "email",
    "phone",
    "pipeline_stage",
    "account_status",
    "last_order_date",
    "notes",
    "lead_score",
    "priority_tier",
    "score_breakdown",
]

# CSV column -> Sheet column. None means "leave blank".
COLUMN_MAP = {
    "store_name":      "Store Name",
    "city":            "City",
    "market":          "State",
    "country":         "Country",
    "website":         "Website",
    "instagram":       "Instagram",
    "email":           "Email",
    "phone":           "Phone",
    "pipeline_stage":  "Outreach Status",
    "account_status":  None,
    "last_order_date": "Last Order Date",
    "notes":           "Notes",
    "lead_score":      "Lead Score",
    "priority_tier":   "Priority Tier",
    "score_breakdown": "Score Breakdown",
}


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
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data["access_token"] = creds.token
        with open(TOKEN_PATH, "w") as f:
            json.dump(token_data, f, indent=2)
    return creds


def load_rows(path):
    rows = []
    with open(path, newline="", encoding="latin-1") as f:
        reader = csv.DictReader(f)
        for r in reader:
            out = []
            for sheet_col in SHEET_HEADERS:
                csv_col = COLUMN_MAP[sheet_col]
                val = "" if csv_col is None else (r.get(csv_col, "") or "").strip()
                if sheet_col == "pipeline_stage" and not val:
                    val = "Not Contacted"
                out.append(val)
            rows.append(out)
    return rows


def main():
    t0 = time.time()
    print(f"GODSPEED SHEETS SYNC — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Source: {CSV_PATH}")
    print(f"Target: spreadsheet={SPREADSHEET_ID} tab={STORES_SHEET}")

    print("\nLoading CSV...")
    rows = load_rows(CSV_PATH)
    print(f"  Loaded {len(rows)} rows")

    print("\nAuthorizing Google Sheets...")
    gc = gspread.authorize(get_creds())
    ss = gc.open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet(STORES_SHEET)

    print(f"Clearing '{STORES_SHEET}' (keeping header row)...")
    ws.clear()
    ws.update("A1", [SHEET_HEADERS], value_input_option="USER_ENTERED")

    total = len(rows)
    num_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"\nUploading {total} rows in {num_chunks} chunk(s) of {CHUNK_SIZE}...")

    uploaded = 0
    for i in range(num_chunks):
        start = i * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, total)
        chunk = rows[start:end]
        print(f"  Uploading chunk {i+1}/{num_chunks} (rows {start+1}-{end})...")
        ws.append_rows(chunk, value_input_option="USER_ENTERED")
        uploaded += len(chunk)
        if i < num_chunks - 1:
            time.sleep(SLEEP_BETWEEN)

    elapsed = time.time() - t0
    print(f"\n✅ Done — uploaded {uploaded} rows in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
