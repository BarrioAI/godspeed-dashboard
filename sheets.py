"""
Google Sheets access for the dashboard and the CLI.

Only the low-level values API is used (values_batch_get / values_update /
values_append / values_clear), so the whole workbook is read in two requests
and the layer is easy to fake in tests. Everything is written RAW, so a phone
number or a note starting with '+' or '=' can never turn into a formula.
"""

from __future__ import annotations

import json
import os
import threading
import time

SPREADSHEET_ID = os.environ.get("GODSPEED_SPREADSHEET_ID", "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA")
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")

STORES_TAB = "STORES"
OUTREACH_TAB = "OUTREACH_LOG"
ORDERS_TAB = "ORDERS"
# Added by the quality layer. Both are keyed by store name + city so they
# survive STORES being re-synced from the CSV.
REVIEW_TAB = "REVIEW"
REVIEW_HEADERS = ["store_name", "city", "decision", "decided_at"]
VERIFY_TAB = "VERIFICATION"
VERIFY_HEADERS = [
    "store_name", "city", "website", "instagram", "phone",
    "web_status", "ig_status", "phone_status",
    "found_instagram", "found_phone", "found_email", "site_mentions",
    "suggested_fixes", "checked_at",
]

_lock = threading.Lock()
_spreadsheet = None
_opened_at = 0.0


class SheetsNotConfigured(Exception):
    pass


def _credentials():
    from google.oauth2.credentials import Credentials

    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if token_json and creds_json:
        token_data, creds_data = json.loads(token_json), json.loads(creds_json)
    elif os.path.exists(TOKEN_PATH) and os.path.exists(CREDS_PATH):
        with open(TOKEN_PATH) as f:
            token_data = json.load(f)
        with open(CREDS_PATH) as f:
            creds_data = json.load(f)
    else:
        raise SheetsNotConfigured(
            "Google credentials not configured. Set GOOGLE_TOKEN_JSON and "
            "GOOGLE_CREDENTIALS_JSON (or GOOGLE_TOKEN_PATH / GOOGLE_CREDS_PATH).")

    installed = creds_data.get("installed") or creds_data.get("web") or creds_data
    # No stored access token on purpose: it is always stale, and leaving it out
    # makes google-auth refresh before the first request.
    return Credentials(
        token=None,
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=installed["client_id"],
        client_secret=installed["client_secret"],
    )


def open_spreadsheet():
    """The spreadsheet handle (re-opened every 30 minutes)."""
    global _spreadsheet, _opened_at
    with _lock:
        if _spreadsheet is None or time.time() - _opened_at > 1800:
            dev_xlsx = os.environ.get("GODSPEED_DEV_XLSX")
            local_dir = os.environ.get("GODSPEED_LOCAL_DIR")
            if dev_xlsx or local_dir:
                # Local dev: a copy of the data, writes stay in memory.
                from fake_sheets import FakeSpreadsheet
                _spreadsheet = (FakeSpreadsheet.from_xlsx(dev_xlsx) if dev_xlsx
                                else FakeSpreadsheet.from_csv_dir(local_dir))
            else:
                import gspread
                _spreadsheet = gspread.authorize(_credentials()).open_by_key(SPREADSHEET_ID)
            _opened_at = time.time()
        return _spreadsheet


def use_spreadsheet(ss):
    """Inject a spreadsheet (tests, local demo)."""
    global _spreadsheet, _opened_at
    _spreadsheet, _opened_at = ss, time.time() + 10 ** 9


def _a1(tab: str, cells: str = "") -> str:
    quoted = "'" + tab.replace("'", "''") + "'"
    return f"{quoted}!{cells}" if cells else quoted


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def tab_titles(ss) -> list[str]:
    return [ws.title for ws in ss.worksheets()]


def read_tabs(ss, tabs: list[str]) -> dict[str, list[list]]:
    """Several tabs in one batch request. Tabs that do not exist come back empty."""
    existing = set(tab_titles(ss))
    wanted = [t for t in tabs if t in existing]
    out = {t: [] for t in tabs}
    if wanted:
        result = ss.values_batch_get([_a1(t) for t in wanted])
        for t, vr in zip(wanted, result.get("valueRanges", [])):
            out[t] = vr.get("values") or []
    return out


def read_tab(ss, tab: str) -> list[list]:
    return ss.values_get(_a1(tab)).get("values") or []


def ensure_tab(ss, tab: str, headers: list[str], rows: int = 1000):
    """Create the tab if missing; write headers only into an empty first row."""
    if tab not in tab_titles(ss):
        ss.add_worksheet(title=tab, rows=rows, cols=len(headers) + 2)
        existing = []
    else:
        existing = (ss.values_get(_a1(tab, "1:1")).get("values") or [[]])[0]
    if not any(str(c).strip() for c in existing):
        ss.values_update(_a1(tab, "A1"), params={"valueInputOption": "RAW"},
                         body={"values": [headers]})
        return headers
    return existing


def replace_tab(ss, tab: str, rows: list[list]):
    """
    Replace a tab's contents with `rows` (header row first), creating it if needed.

    The new data is written over the old first and leftovers are cleared after,
    so a failed request can never leave the tab empty.
    """
    width = max(len(r) for r in rows)
    need_rows, need_cols = len(rows) + 50, width + 2
    ws = next((w for w in ss.worksheets() if w.title == tab), None)
    if ws is None:
        ss.add_worksheet(title=tab, rows=need_rows, cols=need_cols)
        had_rows = had_cols = 0
    else:
        had_rows, had_cols = ws.row_count, ws.col_count
        if had_rows < need_rows or had_cols < need_cols:
            ws.resize(rows=max(had_rows, need_rows), cols=max(had_cols, need_cols))
    rows = [list(r) + [""] * (width - len(r)) for r in rows]
    ss.values_update(_a1(tab, "A1"), params={"valueInputOption": "RAW"}, body={"values": rows})
    if had_rows > len(rows):                           # old rows below the new data
        ss.values_clear(_a1(tab, f"A{len(rows) + 1}:{_col_letter(max(had_cols, width))}{had_rows}"))
    if had_cols > width:                               # old columns to the right of it
        ss.values_clear(_a1(tab, f"{_col_letter(width + 1)}1:{_col_letter(had_cols)}{len(rows)}"))


def update_row_cells(ss, tab: str, row_number: int, headers: list[str], changes: dict):
    """Set named columns on one row (row_number is the 1-based sheet row)."""
    data = []
    for header, value in changes.items():
        if header not in headers:
            continue
        col = _col_letter(headers.index(header) + 1)
        data.append({"range": _a1(tab, f"{col}{row_number}"), "values": [[value]]})
    if data:
        ss.values_batch_update(body={"valueInputOption": "RAW", "data": data})


def append_rows(ss, tab: str, rows: list[list]):
    ss.values_append(_a1(tab, "A1"),
                     params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                     body={"values": rows})


def append_by_header(ss, tab: str, default_headers: list[str], entries: list[dict]):
    """Append dicts to a tab by its own header names. Never clears or rewrites the tab."""
    headers = ensure_tab(ss, tab, default_headers)
    append_rows(ss, tab, [[e.get(h, "") for h in headers] for e in entries])
