"""End-to-end test for the CANDIDATES validate-on-write gate.

Test 1 hits the live CANDIDATES tab (then cleans up after itself).
Tests 2-3 exercise the validator directly with an injected `existing` list
so they don't depend on (or pollute) the live sheet.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.validate_intake import intake_candidate, validate_candidate  # noqa: E402


def _stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _delete_by_name(name):
    """Best-effort cleanup of a test row we just inserted."""
    import gspread
    from app import get_creds, SPREADSHEET_ID, CANDIDATES_SHEET

    gc = gspread.authorize(get_creds())
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(CANDIDATES_SHEET)
    headers = ws.row_values(1)
    if "name" not in headers:
        return
    name_col = headers.index("name") + 1
    col_values = ws.col_values(name_col)
    # iterate from bottom so deletes don't shift unread rows
    for i in range(len(col_values), 1, -1):
        if col_values[i - 1] == name:
            ws.delete_rows(i)


def test_valid_insert():
    name = f"TEST_INTAKE_VALID_{_stamp()}"
    row = {
        "name": name,
        "source": "test_harness",
        "instagram": "@test_handle",
        "website": "https://example.test",
        "city": "Testville",
        "market": "TEST",
        "brands_detected": "Brand A, Brand B",
        "raw_payload": "{}",
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    try:
        cid = intake_candidate(row)
        print(f"  [PASS] valid insert accepted → candidate_id={cid}")
        ok = True
    except Exception as e:
        print(f"  [FAIL] valid insert was rejected: {e}")
        ok = False
    finally:
        try:
            _delete_by_name(name)
        except Exception as e:
            print(f"  (cleanup warning: {e})")
    return ok


def test_duplicate_rejected():
    existing = [{"name": "Broken Chains", "city": "Medellín"}]
    row = {
        "name": "Broken Chains",
        "city": "Medellín",
        "scraped_at": "2026-06-29 12:00",
    }
    ok, reason = validate_candidate(row, existing=existing)
    if not ok and "duplicate" in (reason or "").lower():
        print(f"  [PASS] duplicate rejected → {reason}")
        return True
    print(f"  [FAIL] duplicate NOT rejected (ok={ok}, reason={reason})")
    return False


def test_url_name_rejected():
    row = {
        "name": "https://shop.example.com/brokenchains",
        "city": "Medellín",
        "scraped_at": "2026-06-29 12:00",
    }
    ok, reason = validate_candidate(row, existing=[])
    if not ok and "url" in (reason or "").lower():
        print(f"  [PASS] URL-as-name rejected → {reason}")
        return True
    print(f"  [FAIL] URL-as-name NOT rejected (ok={ok}, reason={reason})")
    return False


def main():
    print(f"GODSPEED INTAKE TEST — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("Test 1: valid candidate insert (hits live CANDIDATES tab)")
    r1 = test_valid_insert()
    print("Test 2: duplicate (name + city) rejected")
    r2 = test_duplicate_rejected()
    print("Test 3: name-as-URL rejected")
    r3 = test_url_name_rejected()

    print()
    print(f"RESULTS: t1={'PASS' if r1 else 'FAIL'}  t2={'PASS' if r2 else 'FAIL'}  t3={'PASS' if r3 else 'FAIL'}")
    sys.exit(0 if all([r1, r2, r3]) else 1)


if __name__ == "__main__":
    main()
