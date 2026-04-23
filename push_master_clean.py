"""
Push master_clean.csv to Google Sheet — ACQUISITION LEADS tab
Wilmar Barrios — Godspeed Master Database Push
"""
import csv
import json
import subprocess
import time
from datetime import date

SHEET_ID = '1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA'
ACCOUNT  = 'javier@varsitylg.com'
TAB      = 'ACQUISITION LEADS'
CSV_PATH = '/Users/elbarrio/.openclaw/workspace/godspeed-dashboard/data/master_clean.csv'

with open(CSV_PATH, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    stores = list(reader)

print(f"Loaded {len(stores)} clean leads from master_clean.csv")

# Headers for the sheet
headers = [
    'Store Name', 'City', 'State', 'Country', 'Territory',
    'Instagram', 'Email', 'Phone', 'Website', 'Warm Lead',
    'Outreach Status', 'Date Added'
]

today = str(date.today())

rows = [headers]
for s in stores:
    rows.append([
        s.get('Store Name', ''),
        s.get('City', ''),
        s.get('State', ''),
        s.get('Country', 'USA'),
        s.get('Territory', ''),
        s.get('Instagram', ''),
        s.get('Email', ''),
        s.get('Phone', ''),
        s.get('Website', ''),
        s.get('Warm_Lead', 'No'),
        'Not Contacted',
        today,
    ])

print(f"Pushing {len(rows)-1} stores to '{TAB}'...")

# Clear existing data
clear_result = subprocess.run([
    'gog', 'sheets', 'clear', SHEET_ID, f"'{TAB}'!A1:Z5000",
    '--account', ACCOUNT
], capture_output=True, text=True)
print("Clear:", clear_result.stdout.strip() or clear_result.stderr.strip()[:100])

time.sleep(2)

# Push in batches of 200
BATCH = 200
total_pushed = 0
errors = 0
for i in range(0, len(rows), BATCH):
    batch = rows[i:i+BATCH]
    start_row = i + 1
    range_str = f"'{TAB}'!A{start_row}:L{start_row + len(batch) - 1}"
    values_json = json.dumps(batch)

    result = subprocess.run([
        'gog', 'sheets', 'update', SHEET_ID, range_str,
        '--values-json', values_json,
        '--input', 'USER_ENTERED',
        '--account', ACCOUNT
    ], capture_output=True, text=True)

    if result.returncode == 0:
        total_pushed += len(batch)
        print(f"  ✅ Rows {start_row}–{start_row + len(batch) - 1} ({total_pushed} total)")
    else:
        errors += 1
        print(f"  ❌ Batch {i}: {result.stderr[:200]}")

    time.sleep(1)

print(f"\n{'✅' if not errors else '⚠️'} Done. {total_pushed-1} stores pushed. {errors} errors.")
