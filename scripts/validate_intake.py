"""Validate-on-write gate for CANDIDATES intake (Raj — wholesale loop, stage 0→1).

Rejects bad data at the door so Vito's scoring rubric never sees garbage:
  - blank names, URLs as names, IG fields that are actually phone numbers,
  - missing scraped_at, and (name, city) duplicates against the live CANDIDATES tab.

Public surface:
  validate_candidate(row, existing=None) -> (ok: bool, reason: str | None)
  intake_candidate(row) -> appends to CANDIDATES on pass, raises ValueError on fail.
"""

import os
import re
import sys
from datetime import datetime

# Allow `python3 scripts/validate_intake.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (  # noqa: E402
    SPREADSHEET_ID,
    CANDIDATES_SHEET,
    get_creds,
    _next_id,
    _read_records,
)

CANDIDATES_HEADERS = [
    "candidate_id", "name", "source", "instagram", "website",
    "brands_detected", "city", "market", "raw_payload", "scraped_at",
]

_DIGITS_ONLY = re.compile(r"^\+?[\d\s\-\(\)\.]+$")


def _norm(s):
    return (s or "").strip().lower()


def validate_candidate(row, existing=None):
    """Return (True, None) on pass, (False, reason) on fail.

    `existing` lets tests inject a fake list; in production it's read from Sheets.
    """
    name = (row.get("name") or "").strip()
    if not name:
        return False, "name is blank"
    if name.lower().startswith(("http://", "https://")):
        return False, "name looks like a URL, not a store name"

    instagram = (row.get("instagram") or "").strip()
    if instagram and _DIGITS_ONLY.match(instagram):
        # All-digits / phone-shaped — IG handles always contain letters.
        return False, "instagram field looks like a phone number, not a handle"

    if not (row.get("scraped_at") or "").strip():
        return False, "scraped_at is required"

    if existing is None:
        existing, _ = _read_records(CANDIDATES_SHEET)
    city = _norm(row.get("city"))
    nm = _norm(name)
    for r in existing:
        if _norm(r.get("name")) == nm and _norm(r.get("city")) == city:
            return False, f"duplicate of existing candidate (name + city already in CANDIDATES): {name} / {row.get('city','')}"

    return True, None


def intake_candidate(row):
    """Validate then append to CANDIDATES. Raises ValueError on rejection."""
    import gspread

    existing, _ = _read_records(CANDIDATES_SHEET)
    ok, reason = validate_candidate(row, existing=existing)
    if not ok:
        raise ValueError(f"intake rejected: {reason}")

    gc = gspread.authorize(get_creds())
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(CANDIDATES_SHEET)

    row = dict(row)
    row.setdefault("candidate_id", _next_id(existing, "candidate_id", "CAND", 5))
    row.setdefault("scraped_at", datetime.now().strftime("%Y-%m-%d %H:%M"))

    ws.append_row(
        [row.get(h, "") for h in CANDIDATES_HEADERS],
        value_input_option="USER_ENTERED",
    )
    return row["candidate_id"]
