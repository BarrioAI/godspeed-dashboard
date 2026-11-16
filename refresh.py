#!/usr/bin/env python3
"""
Apply the live verification results to the leads file — the weekly refresh.

`python ops.py verify` has the dashboard read every store's own website.
This script takes that evidence (an export of the VERIFICATION tab) and makes
the corrections a careful sales rep would make by hand, and only those:

  * a phone / Instagram / email the store's own site shows, where the file is
    blank or disagrees
  * a phone from the wrong state that the site does not confirm is cleared
  * the peer brands the site stocks go into Brands Carried, which drives the
    Brand part of the lead score — so the stores most like Godspeed's existing
    accounts rise to the top of the queue

Anything it is not sure of is left alone and listed under "needs_a_look".
No row is added or removed and no store name is changed.

  python ops.py export verification -o /tmp/verification.csv
  python refresh.py /tmp/verification.csv --dry-run     # what would change
  python refresh.py /tmp/verification.csv               # change the leads file
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

import quality as q
import stores
import super_clean

LEADS_CSV = super_clean.LEADS_CSV

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com", "me.com"}
# Handles a site links to that belong to its web platform, not to the store.
PLATFORM_HANDLES = {"shopify", "wix", "squarespace", "bigcartel", "godaddy", "instagram", "facebook",
                    "lovable_dev", "square", "linktree", "shop"}

_PHONE_FIX_RE = re.compile(r"Phone: website shows (\(\d{3}\) \d{3}-\d{4}), sheet has (\(\d{3}\) \d{3}-\d{4})")
_IG_FIX_RE = re.compile(r"Instagram: website links @([\w.]+), sheet has @([\w.]+)")


def _key(name, city) -> tuple[str, str]:
    return q.s(name).strip().lower(), q.s(city).strip().lower()


def _compact(text) -> str:
    return re.sub(r"[^a-z0-9]", "", q.s(text).lower())


def _shares_run(a: str, b: str, n: int = 5) -> bool:
    """Do a and b share a run of n characters? ('fringe_lr' / 'shopfringeclothing')"""
    return any(a[i:i + n] in b for i in range(len(a) - n + 1)) if len(a) >= n and len(b) >= n else False


def own_site(row: dict) -> bool:
    """Is the Website cell the store's own site (not a directory, mall, chain or brand page)?"""
    if not q.normalize_website(row.get("Website")) or q.is_social_link(row.get("Website")):
        return False
    if q.website_flags(row):
        return False
    return q.name_matches_site({**row, "Instagram": ""}) is True


def resembles(handle: str, row: dict) -> bool:
    """Does an Instagram handle look like it belongs to this row's store?"""
    h = _compact(handle)
    keys = q.site_keys({**row, "Instagram": ""}) + [_compact(row.get("Store Name"))]
    return any(_shares_run(h, k) or (len(h) >= 4 and (h in k or k in h)) for k in keys if k)


def row_state(row: dict) -> str:
    """Two-letter state of a US row, '' for anything else."""
    if q.s(row.get("Country")).upper() not in ("USA", "US", ""):
        return ""
    state = q.normalize_state(row.get("State"))
    return state if q.is_us_state(state) else ""


def phone_state(phone) -> str:
    digits = q.normalize_phone(phone)
    return q.AREA_CODE_STATE.get(digits[:3], "") if digits else ""


def apply(leads: list[dict], checks: list[dict]) -> dict:
    """
    Apply verification findings to `leads` in place. Returns
    {"changed": {what: count}, "log": [...], "needs_a_look": [...], "godspeed_on_site": [...]}.
    Safe to run twice: a correction is only made while the file still holds the
    value the check looked at.
    """
    by_key = {_key(c.get("store_name"), c.get("city")): c for c in checks}
    domains = Counter(q.website_domain(r.get("Website")) for r in leads
                      if q.website_domain(r.get("Website")) and not q.is_social_link(r.get("Website")))
    flags = [q.classify(r, n)[0] for r, n in zip(leads, q.count_locations(leads))]

    # What each store website mentions, pooled over every row that points at it
    # (a product-page row proves what the store behind it stocks).
    mentions = defaultdict(set)
    for c in checks:
        d = q.website_domain(c.get("website"))
        if d and c.get("web_status") == "ok":
            mentions[d].update(m.strip() for m in q.s(c.get("site_mentions")).split(",") if m.strip())

    changed, log, look, godspeed = Counter(), [], [], []

    def put(row, col, value, why):
        log.append({"store": row["Store Name"], "city": row.get("City", ""), "column": col,
                    "before": row.get(col, ""), "after": value, "why": why})
        row[col] = value
        changed[why] += 1

    def ask(row, what):
        look.append({"store": row["Store Name"], "city": row.get("City", ""), "what": what})

    for row, flag in zip(leads, flags):
        check = by_key.get(_key(row.get("Store Name"), row.get("City")))
        domain = q.website_domain(row.get("Website"))
        mine = own_site(row)
        rejected = q.bucket(flag) == "rejected"
        state = row_state(row)
        path = urlparse(q.normalize_website(row.get("Website")) or "").path.strip("/")
        one_door = domains.get(domain, 0) <= 1 or bool(path)     # a location page speaks for one door

        # Brands the store's site stocks
        if mine and not rejected and domain in mentions:
            sep = " | " if "|" in q.s(row.get("Brands Carried")) else ", "
            have = [b.strip() for b in re.split(r"[|,]", q.s(row.get("Brands Carried"))) if b.strip()]
            have_keys = {_compact(b) for b in have}
            new = [b for b in q.peer_brands(mentions[domain]) if _compact(b) not in have_keys]
            if new:
                put(row, "Brands Carried", sep.join(have + new), "brands found on store website")
            carried = q.peer_brands(have + new)
            for brand, col in (("Hellstar", "Carries Hellstar"), ("Supreme", "Carries Supreme")):
                if brand in carried and not q.s(row.get(col)).lower().startswith("y"):
                    put(row, col, "Yes", "brands found on store website")
            if "Godspeed" in mentions[domain] and q.bucket(flag) == "qualified":
                godspeed.append({"store": row["Store Name"], "city": row.get("City", "")})

        if not check:
            continue
        live = check.get("web_status") == "ok"
        fixes = q.s(check.get("suggested_fixes"))
        phone = q.normalize_phone(row.get("Phone"))

        # Phone
        m = _PHONE_FIX_RE.search(fixes)
        site_phone = m.group(1) if m else q.s(check.get("found_phone"))
        applies = bool(site_phone) and (q.normalize_phone(m.group(2)) == phone if m else not q.s(row.get("Phone")))
        if applies and live and not rejected:
            ok_state = phone_state(site_phone) == state and state
            if mine and one_door and ok_state:
                put(row, "Phone", site_phone,
                    "phone corrected from store website" if m else "phone filled from store website")
                phone = q.normalize_phone(site_phone)
            elif mine:
                ask(row, f"website shows phone {site_phone}"
                         + ("" if ok_state else " (toll-free or another state)")
                         + ("" if one_door else " (site shared by several stores)"))
        if (phone and state and q.normalize_phone(check.get("phone")) == phone
                and check.get("phone_status") != "ok (on website)"
                and phone[:3] in q.AREA_CODE_STATE and q.AREA_CODE_STATE[phone[:3]] != state):
            put(row, "Phone", "", "out-of-state phone cleared")

        # Instagram
        handle = q.normalize_instagram(row.get("Instagram"))
        m = _IG_FIX_RE.search(fixes)
        if m and live and mine and not rejected and handle == m.group(2).lower():
            linked = m.group(1).lower()
            if linked in PLATFORM_HANDLES:
                pass
            elif domains.get(domain, 0) <= 1 and resembles(linked, row) and not resembles(handle, row):
                put(row, "Instagram", "@" + linked, "instagram corrected from store website")
            else:
                ask(row, f"website links @{linked}, file has @{handle}")
        found = q.normalize_instagram(check.get("found_instagram"))
        if found and not handle and live and mine and not rejected and found not in PLATFORM_HANDLES:
            site = (q.site_keys({**row, "Instagram": ""}) or [""])[0]
            if domains.get(domain, 0) <= 1 or (site and (site in _compact(found) or _compact(found) in site)):
                put(row, "Instagram", "@" + found, "instagram filled from store website")
            else:
                ask(row, f"website links @{found}")

        # Email
        email = q.normalize_email(check.get("found_email"))
        if email and not q.s(row.get("Email")) and live and mine and not rejected:
            host = email.split("@")[1]
            if host in FREE_MAIL or host == domain or host.endswith("." + q.s(domain)) or q.s(domain).endswith("." + host):
                put(row, "Email", email, "email filled from store website")
            else:
                ask(row, f"website shows email {email}")

        if check.get("web_status") == "unreachable" and not rejected \
                and q.normalize_website(check.get("website")) == q.normalize_website(row.get("Website")):
            ask(row, f"website did not load: {q.s(row.get('Website'))}")

    return {"changed": dict(sorted(changed.items())), "log": log, "needs_a_look": look,
            "godspeed_on_site": godspeed}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("verification", help="CSV export of the VERIFICATION tab (python ops.py export verification -o …)")
    parser.add_argument("--csv", default=LEADS_CSV, help="leads file (default: data/godspeed_leads_final.csv)")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    parser.add_argument("--log", help="write every changed cell to this CSV")
    args = parser.parse_args()

    header, rows = super_clean.read_leads(args.csv)
    with open(args.verification, newline="", encoding="utf-8-sig") as f:
        checks = list(csv.DictReader(f))
    result = apply(rows, checks)
    scrubbed = stores.scrub_leads(rows)
    tiers_before, tiers_after = super_clean.rescore(rows)
    buckets = Counter(q.bucket(q.classify(r, n)[0]) for r, n in zip(rows, q.count_locations(rows)))
    if not args.dry_run:
        super_clean.write_leads(args.csv, header, rows)
    if args.log:
        with open(args.log, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["store", "city", "column", "before", "after", "why"])
            writer.writeheader()
            writer.writerows(result["log"])
    print(json.dumps({
        "file": args.csv, "rows": len(rows), "stores_checked": len(checks), "dry_run": args.dry_run,
        "changed": result["changed"], "scrubbed": scrubbed,
        "tiers_before": tiers_before, "tiers_after": tiers_after, "buckets": dict(buckets),
        "needs_a_look": result["needs_a_look"], "godspeed_on_site": result["godspeed_on_site"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
