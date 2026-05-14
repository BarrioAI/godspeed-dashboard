#!/usr/bin/env python3
"""
Super Clean: Godspeed Lead Database v3 — FLAG-ONLY + LIVE VERIFY
====================================================================

This is an *audit pass*, not a destructive cleaner. It writes flag columns
back to MASTER DATABASE so a human can review before any row is deleted.

What it flags
-------------
1. Chain stores and clothing-brand mono-stores (expanded list vs. deep_clean.py)
2. Stores with no streetwear signal anywhere in their text fields
3. Instagram handles that don't resolve on instagram.com
4. Phone numbers that aren't a valid US 10-digit format
5. Websites that 404, refuse connection, or are actually social-media URLs

Output
------
- Three new columns on MASTER DATABASE:
    "Cleanup Flag"  -> chain | mono-brand | low-fit | broken-data | OK | <combo>
    "IG Status"     -> ok | invalid-format | unreachable | empty
    "Web Status"    -> ok | invalid-format | unreachable | social-link | empty
    "Phone Status"  -> ok | invalid-format | empty
- A CSV report at data/super_clean_report.csv with every flag and reason

Run modes
---------
  python super_clean.py --dry-run            # Default. Report only, no sheet writes.
  python super_clean.py --apply              # Write flag columns back to the sheet.
  python super_clean.py --apply --limit 100  # Same but only first 100 rows (testing).
  python super_clean.py --skip-live          # Skip HTTP checks (format-only).

Author: built for Goldie's pre-outreach QC pass
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import gspread
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")

REPORT_DIR = os.path.join(os.path.dirname(__file__), "data")
REPORT_PATH = os.path.join(REPORT_DIR, "super_clean_report.csv")

# HTTP behaviour
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
HTTP_TIMEOUT = 8        # seconds per request
WEB_WORKERS = 16        # parallel website checks
IG_WORKERS = 4          # Instagram is rate-limit happy — keep low
IG_MIN_INTERVAL = 0.4   # seconds between IG requests across all threads

# ─────────────────────────────────────────
#  CHAIN / MONO-BRAND / STREETWEAR LISTS
# ─────────────────────────────────────────

# Chain stores (sneaker/streetwear chains we explicitly don't pitch)
CHAIN_STORES = [
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
    "jcpenney", "jc penney", "jc penny",
    "target", "walmart", "dick's sporting", "dicks sporting",
    "modells", "modell's", "sports authority",
    "eastbay", "zappos", "shoe carnival",
    "payless", "famous footwear", "dsw",
    "shoe palace", "shiekh", "snipes usa",
    # Mainstream apparel chains (clothing brand stores)
    "lululemon", "h&m", "h & m", "zara", "uniqlo",
    "gap", "gap factory", "gap kids", "old navy", "banana republic",
    "j.crew", "j crew", "jcrew",
    "abercrombie", "abercrombie & fitch", "hollister",
    "american eagle", "aerie",
    "express", "express factory",
    "forever 21", "forever21",
    "ross", "tj maxx", "tjmaxx", "marshalls", "burlington",
    "kohl's", "kohls", "sears",
    "primark", "topshop", "topman",
    "uniqlo us", "muji",
    "guess", "guess factory",
    "tommy hilfiger", "calvin klein", "ck store",
    "ralph lauren", "polo ralph lauren", "polo factory",
    "michael kors", "kate spade", "coach", "coach outlet",
    "true religion",
    "lacoste",
    "diesel",
    "armani exchange", "ax armani",
    "hugo boss", "boss store",
    "burberry",
    "victoria's secret", "victorias secret", "pink",
    "anthropologie", "free people", "urban outfitters",
    "madewell",
    "patagonia",
    "north face", "the north face",
    "columbia", "columbia sportswear",
    "rei", "academy sports", "big 5",
]

# Mono-brand flagship stores (single-brand only — not a fit for a wholesale brand)
MONO_BRAND_STORES = [
    "nike store", "nike retail", "nike factory", "niketown",
    "adidas store", "adidas shop", "adidas retail", "adidas originals store",
    "puma store", "puma shop", "puma factory",
    "jordan store", "jordan retail", "jordan world", "house of hoops",
    "off-white store", "off white store", "off white retail",
    "supreme store", "supreme retail", "supreme nyc", "supreme la",
    "bape store", "bape retail", "bape shop", "a bathing ape",
    "vans store", "vans shop", "vans factory",
    "converse store", "converse shop", "converse factory",
    "new balance store", "new balance retail",
    "reebok store", "reebok shop", "reebok outlet",
    "asics store", "asics shop",
    "under armour store", "under armour retail", "ua brand house",
    "saucony store", "brooks store",
    "carhartt store", "carhartt wip store",
    "stussy store", "stussy chapter",
    "palace skateboards", "palace store",
    "kith store",  # kith is also a chain but listed here for the flagship
    "fear of god flagship",
    "essentials store",
    "amiri store",
    "rhude store",
    "represent store",
    "chrome hearts",
]

# Generic non-retail junk (food/auto/medical/etc.)
JUNK_KEYWORDS = [
    # auto
    "dealership", "automotive", "car dealer", "car sales", "car wash",
    "auto dealer", "auto sales", "auto repair", "auto shop", "auto group",
    "nissan", "gmc", "buick", "honda", "toyota", "chevy", "chevrolet",
    "ford motors", "car rental", "tires", "mechanic", "transmission", "oil change",
    # food
    "restaurant", "cafe ", " cafe", "coffee", "pizza", "taco", "sushi",
    "bakery", "diner", "eatery", "catering", "burger", "sandwich", "donut",
    "pancake", "wing", "bbq", "barbeque", "ramen", "pasta", "deli",
    # medical
    "dental", "dentist", "clinic", "medical", "therapy",
    "massage", "chiropractic", "pharmacy", "urgent care", "physical therapy",
    "doctor", "physician", "hospital", "orthopedic",
    # services
    "real estate", "realtor", "mortgage", "bank", "financial", "insurance",
    "attorney", "law firm", "legal", "school", "university", "college",
    "church", "nonprofit", "charity", "government", "post office",
    "staffing", "recruiter", "recruitment", "now hiring",
]

# Words that signal this IS the kind of store Godspeed wants
STREETWEAR_SIGNALS = [
    # brands
    "hellstar", "rhude", "vale forever", "supreme", "denim tears", "sp5der",
    "gallery dept", "off-white", "off white", "fear of god", "bape", "amiri",
    "chrome hearts", "yeezy", "travis scott", "essentials", "fog", "vlone",
    "anti social social club", "assc", "stussy", "huf", "thrasher",
    "palace", "kith", "carhartt wip",
    # categories
    "streetwear", "sneaker", "sneakers", "hypebeast", "skate", "skateboard",
    "hype", "kicks", "consignment", "vintage", "thrift", "resale",
    "boutique", "multi-brand", "multi brand", "multibrand",
    # store-type signals
    "designer", "luxury streetwear", "urban wear", "urbanwear",
]

# Domains that should NEVER be in a "Website" column
SOCIAL_DOMAINS = {
    "instagram.com", "www.instagram.com", "m.instagram.com",
    "facebook.com", "www.facebook.com", "m.facebook.com", "fb.com",
    "tiktok.com", "www.tiktok.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "youtube.com", "www.youtube.com", "youtu.be",
    "linkedin.com", "www.linkedin.com",
    "pinterest.com", "www.pinterest.com",
    "linktr.ee", "linktree.com",
}

INSTAGRAM_HANDLE_RE = re.compile(r"^@?([A-Za-z0-9._]{1,30})$")
PHONE_DIGITS_RE = re.compile(r"\D+")

# ─────────────────────────────────────────
#  AUTH (same shape as the other scripts)
# ─────────────────────────────────────────

def get_creds():
    token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

    if token_json and creds_json:
        token_data = json.loads(token_json)
        creds_data = json.loads(creds_json)
    else:
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
            "https://www.googleapis.com/auth/drive.file",
        ],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def open_master():
    gc = gspread.authorize(get_creds())
    ss = gc.open_by_key(SPREADSHEET_ID)
    return ss, ss.worksheet("MASTER DATABASE")


# ─────────────────────────────────────────
#  ROW MODEL
# ─────────────────────────────────────────

@dataclass
class RowAudit:
    row_idx: int                # 1-based row number on the sheet (incl. header)
    store_name: str
    city: str
    state: str
    instagram_raw: str
    website_raw: str
    phone_raw: str
    cleanup_flag: str = "OK"
    cleanup_reasons: list = field(default_factory=list)
    ig_status: str = "empty"
    web_status: str = "empty"
    phone_status: str = "empty"

    def cleanup_summary(self) -> str:
        return self.cleanup_flag if not self.cleanup_reasons else f"{self.cleanup_flag}: {'; '.join(self.cleanup_reasons)}"


# ─────────────────────────────────────────
#  CLASSIFIERS
# ─────────────────────────────────────────

def _full_text(row: dict) -> str:
    parts = [str(row.get(k, "") or "").lower() for k in (
        "Store Name", "City", "State", "Address", "Store Description",
        "Category", "Notes", "Brands", "Last Order Date",
    )]
    return " ".join(parts)


def classify_business(row: dict) -> tuple[str, list[str]]:
    """
    Returns (top-level flag, list of reasons).
    Top-level flag is one of: OK, broken-data, chain, mono-brand, junk, low-fit.
    Multiple flags are joined with '+' (e.g. 'chain+low-fit').
    """
    name = str(row.get("Store Name", "") or "").strip()
    if not name or name.upper() in ("N/A", "NA", "UNDEFINED") or len(name) < 2:
        return "broken-data", ["missing or invalid Store Name"]

    text = _full_text(row)
    flags: list[str] = []
    reasons: list[str] = []

    for chain in CHAIN_STORES:
        if chain in text:
            flags.append("chain")
            reasons.append(f"chain match '{chain}'")
            break

    for mono in MONO_BRAND_STORES:
        if mono in text:
            if "mono-brand" not in flags:
                flags.append("mono-brand")
            reasons.append(f"mono-brand match '{mono}'")
            break

    for junk in JUNK_KEYWORDS:
        if junk in text:
            if "junk" not in flags:
                flags.append("junk")
            reasons.append(f"non-retail keyword '{junk.strip()}'")
            break

    if not any(sig in text for sig in STREETWEAR_SIGNALS):
        flags.append("low-fit")
        reasons.append("no streetwear signal in any text field")

    if not flags:
        return "OK", []
    return "+".join(flags), reasons


# ─────────────────────────────────────────
#  FIELD VALIDATORS  (format only)
# ─────────────────────────────────────────

def normalize_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = PHONE_DIGITS_RE.sub("", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def normalize_instagram(raw: str) -> Optional[str]:
    if not raw:
        return None
    cleaned = raw.strip()
    # Strip a full instagram URL down to the handle
    if "instagram.com/" in cleaned:
        cleaned = cleaned.split("instagram.com/", 1)[1].strip("/").split("?")[0]
    cleaned = cleaned.lstrip("@")
    m = INSTAGRAM_HANDLE_RE.match(cleaned)
    if not m:
        return None
    return m.group(1).lower()


def normalize_website(raw: str) -> Optional[str]:
    if not raw:
        return None
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        return None
    return url


def is_social_only(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in SOCIAL_DOMAINS


# ─────────────────────────────────────────
#  LIVE HTTP CHECKS
# ─────────────────────────────────────────

_ig_lock = threading.Lock()
_ig_last_call = [0.0]


def _ig_throttle():
    with _ig_lock:
        wait = IG_MIN_INTERVAL - (time.monotonic() - _ig_last_call[0])
        if wait > 0:
            time.sleep(wait)
        _ig_last_call[0] = time.monotonic()


def check_instagram(handle: str, session: requests.Session) -> str:
    """Returns 'ok' | 'unreachable'. Caller already verified format."""
    _ig_throttle()
    url = f"https://www.instagram.com/{handle}/"
    try:
        r = session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return "unreachable"
    if r.status_code == 404:
        return "unreachable"
    if r.status_code == 429:
        # Rate-limited — back off and don't penalize the row
        time.sleep(5)
        return "ok"
    if r.status_code >= 500:
        return "unreachable"
    body = r.text.lower() if r.text else ""
    if "page not found" in body or "sorry, this page" in body:
        return "unreachable"
    return "ok"


def check_website(url: str, session: requests.Session) -> str:
    """Returns 'ok' | 'unreachable'."""
    try:
        r = session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True,
                        headers={"User-Agent": USER_AGENT})
    except requests.RequestException:
        return "unreachable"
    # 4xx other than 404 / 410 we tolerate (lots of sites block bots with 403)
    if r.status_code in (404, 410):
        return "unreachable"
    if r.status_code >= 500:
        return "unreachable"
    return "ok"


# ─────────────────────────────────────────
#  PROCESSING
# ─────────────────────────────────────────

def audit_row(row_idx: int, row: dict) -> RowAudit:
    audit = RowAudit(
        row_idx=row_idx,
        store_name=str(row.get("Store Name", "") or "").strip(),
        city=str(row.get("City", "") or "").strip(),
        state=str(row.get("State", "") or "").strip(),
        instagram_raw=str(row.get("Instagram", "") or "").strip(),
        website_raw=str(row.get("Website", "") or "").strip(),
        phone_raw=str(row.get("Phone", "") or "").strip(),
    )

    flag, reasons = classify_business(row)
    audit.cleanup_flag = flag
    audit.cleanup_reasons = reasons

    # Phone: format only
    if not audit.phone_raw:
        audit.phone_status = "empty"
    elif normalize_phone(audit.phone_raw):
        audit.phone_status = "ok"
    else:
        audit.phone_status = "invalid-format"

    # Instagram: format check now, live check later
    if not audit.instagram_raw:
        audit.ig_status = "empty"
    elif not normalize_instagram(audit.instagram_raw):
        audit.ig_status = "invalid-format"
    else:
        audit.ig_status = "pending"

    # Website: format check now, live check later
    if not audit.website_raw:
        audit.web_status = "empty"
    else:
        norm = normalize_website(audit.website_raw)
        if not norm:
            audit.web_status = "invalid-format"
        elif is_social_only(norm):
            audit.web_status = "social-link"
        else:
            audit.web_status = "pending"

    return audit


def run_live_checks(audits: list[RowAudit], skip_live: bool):
    if skip_live:
        for a in audits:
            if a.ig_status == "pending":
                a.ig_status = "ok-format"
            if a.web_status == "pending":
                a.web_status = "ok-format"
        return

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    web_targets = [(a, normalize_website(a.website_raw)) for a in audits if a.web_status == "pending"]
    ig_targets = [(a, normalize_instagram(a.instagram_raw)) for a in audits if a.ig_status == "pending"]

    print(f"[live] websites to verify: {len(web_targets)}  |  instagram: {len(ig_targets)}")

    done = [0]
    total = len(web_targets) + len(ig_targets)

    def _bump():
        done[0] += 1
        if done[0] % 50 == 0 or done[0] == total:
            print(f"[live] {done[0]}/{total} checks complete")

    with ThreadPoolExecutor(max_workers=WEB_WORKERS) as pool:
        futures = {pool.submit(check_website, url, session): a for a, url in web_targets}
        for fut in as_completed(futures):
            a = futures[fut]
            try:
                a.web_status = fut.result()
            except Exception as e:
                a.web_status = "unreachable"
                a.cleanup_reasons.append(f"web check error: {e}")
            _bump()

    with ThreadPoolExecutor(max_workers=IG_WORKERS) as pool:
        futures = {pool.submit(check_instagram, h, session): a for a, h in ig_targets}
        for fut in as_completed(futures):
            a = futures[fut]
            try:
                a.ig_status = fut.result()
            except Exception as e:
                a.ig_status = "unreachable"
                a.cleanup_reasons.append(f"ig check error: {e}")
            _bump()


# ─────────────────────────────────────────
#  SHEET WRITE-BACK
# ─────────────────────────────────────────

FLAG_HEADERS = ["Cleanup Flag", "IG Status", "Web Status", "Phone Status"]


def ensure_flag_columns(ws, headers: list[str]) -> dict[str, int]:
    """Add the four flag headers if missing. Returns {header: 1-based col index}."""
    col_map: dict[str, int] = {}
    next_col = len(headers) + 1
    for h in FLAG_HEADERS:
        existing = next((i + 1 for i, v in enumerate(headers) if v.strip().lower() == h.lower()), None)
        if existing:
            col_map[h] = existing
        else:
            ws.update_cell(1, next_col, h)
            col_map[h] = next_col
            next_col += 1
            time.sleep(0.5)
    return col_map


def write_back(ws, audits: list[RowAudit], col_map: dict[str, int]):
    """Batch-update each flag column with one column-write per header."""
    n = len(audits)
    cols = {
        "Cleanup Flag":  [[a.cleanup_summary()] for a in audits],
        "IG Status":     [[a.ig_status] for a in audits],
        "Web Status":    [[a.web_status] for a in audits],
        "Phone Status":  [[a.phone_status] for a in audits],
    }
    for header, values in cols.items():
        col_idx = col_map[header]
        start = gspread.utils.rowcol_to_a1(2, col_idx)
        end = gspread.utils.rowcol_to_a1(n + 1, col_idx)
        rng = f"{start}:{end}"
        print(f"[write] {header} -> {rng}")
        ws.update(rng, values)
        time.sleep(2)  # polite delay between column writes


# ─────────────────────────────────────────
#  REPORT
# ─────────────────────────────────────────

def write_report(audits: list[RowAudit]):
    os.makedirs(REPORT_DIR, exist_ok=True)
    fieldnames = [
        "row_idx", "store_name", "city", "state",
        "instagram_raw", "website_raw", "phone_raw",
        "cleanup_flag", "cleanup_reasons",
        "ig_status", "web_status", "phone_status",
    ]
    with open(REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for a in audits:
            d = asdict(a)
            d["cleanup_reasons"] = " | ".join(a.cleanup_reasons)
            writer.writerow(d)
    print(f"[report] CSV saved: {REPORT_PATH}")


def print_summary(audits: list[RowAudit]):
    n = len(audits)
    counts: dict[str, int] = {}
    for a in audits:
        counts[a.cleanup_flag] = counts.get(a.cleanup_flag, 0) + 1
    ig = {k: 0 for k in ("ok", "ok-format", "pending", "invalid-format", "unreachable", "empty")}
    web = {k: 0 for k in ("ok", "ok-format", "pending", "invalid-format", "unreachable", "social-link", "empty")}
    phone = {k: 0 for k in ("ok", "invalid-format", "empty")}
    for a in audits:
        ig[a.ig_status] = ig.get(a.ig_status, 0) + 1
        web[a.web_status] = web.get(a.web_status, 0) + 1
        phone[a.phone_status] = phone.get(a.phone_status, 0) + 1

    print("\n" + "=" * 70)
    print(f"SUPER CLEAN AUDIT — {n} rows")
    print("=" * 70)
    print("\nCleanup Flag breakdown:")
    for flag, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {flag:<30} {count:>5}  ({count / n * 100:.1f}%)")

    print("\nInstagram status:")
    for k, v in ig.items():
        if v:
            print(f"  {k:<20} {v:>5}")
    print("\nWebsite status:")
    for k, v in web.items():
        if v:
            print(f"  {k:<20} {v:>5}")
    print("\nPhone status:")
    for k, v in phone.items():
        if v:
            print(f"  {k:<20} {v:>5}")
    print("=" * 70 + "\n")


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write flag columns back to MASTER DATABASE. Default is dry-run (CSV only).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N data rows (for testing).")
    parser.add_argument("--skip-live", action="store_true",
                        help="Skip HTTP verification of IG/website. Format checks only.")
    args = parser.parse_args()

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] super_clean.py starting")
    print(f"  mode      : {'APPLY (writes to sheet)' if args.apply else 'DRY-RUN (CSV only)'}")
    print(f"  live HTTP : {'OFF' if args.skip_live else 'ON'}")
    print(f"  row limit : {args.limit if args.limit else 'all'}\n")

    ss, ws = open_master()
    headers = ws.row_values(1)
    records = ws.get_all_records()
    if args.limit:
        records = records[: args.limit]
    print(f"[load] {len(records)} rows from MASTER DATABASE")

    audits = [audit_row(i + 2, row) for i, row in enumerate(records)]
    run_live_checks(audits, skip_live=args.skip_live)

    write_report(audits)
    print_summary(audits)

    if args.apply:
        col_map = ensure_flag_columns(ws, headers)
        write_back(ws, audits, col_map)
        print("[done] sheet updated with flag columns.")
    else:
        print("[done] dry-run complete. Re-run with --apply to write columns to the sheet.")


if __name__ == "__main__":
    main()
