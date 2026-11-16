"""
Read-side quality layer for the STORES tab.

Nothing here writes anywhere. Given the rows of STORES it returns display
records in which

  * junk contact values are hidden (fake phone numbers repeated across
    hundreds of rows, CSS tokens in the Instagram column, tracker emails,
    Instagram links sitting in the Website column),
  * every store carries a fit flag from quality.classify(), and
  * the same store listed once per searched city is marked as a duplicate.

The sheet keeps its raw values; the dashboard shows the cleaned view.
"""

from __future__ import annotations

import html
import re
from collections import Counter, defaultdict

import quality as q

# Scraper leftovers that end up in the Instagram column.
IG_JUNK = {
    "font", "font-face", "media", "context", "keyframes", "supports", "theme",
    "import", "layer", "charset", "type", "id", "graph", "container", "page",
    "property", "namespace", "apply", "tailwind", "2x", "3x", "100", "gmail.com",
    "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "dd1",
    "hypebeast", "ebay", "linkedin", "fivestars", "yelp", "facebook", "google",
    "instagram", "tiktok", "nextdoor", "greyhoundlines", "shopify", "klarna",
    "afterpay", "sentry", "wix", "squarespace", "godaddy", "us", "usa", "n", "no",
}
PHONE_JUNK = {"2147483647", "1234567890", "0123456789", "9876543210"}
REPEATED_PHONE = 4          # a number on this many rows is a scraper artefact

_IG_TITLE_RE = re.compile(r"\s*\(@[\w.]+\).*$")
_IG_SUFFIX_RE = re.compile(r"\s*[•·|-]\s*instagram.*$", re.I)
_TRACKING_RE = re.compile(r"(?i)^(?:srsltid|utm_[a-z]+|fbclid|gclid|ref|hl|igshid|igsh)=")
_IG_PROFILE_URL_RE = re.compile(
    r"(?i)^(?:https?://)?(?:www\.|m\.)?instagram\.com/([A-Za-z0-9._]+)/?(?:\?.*)?$")
_SEGMENT_RE = re.compile(r"\s+[|–—:·•]\s+|\s+-\s+|\s*\|\s*|:\s+")


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", q._norm(text))


def fix_mojibake(text: str) -> str:
    """'BogotÃ¡' -> 'Bogotá' (UTF-8 that was read as Latin-1 somewhere upstream)."""
    text = re.sub(r"_x00([0-9A-Fa-f]{2})_", lambda m: chr(int(m.group(1), 16)), text)
    if "Ã" in text or "â\x80" in text or "Â" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
    return text


def clean_name(raw: str, site_row: dict | None = None) -> str:
    """
    Scraped names are page titles ("Shop Hellstar | The Attic Streetwear").
    Keep the segment that matches the row's own website / Instagram.
    """
    name = fix_mojibake(html.unescape(html.unescape(raw)))
    name = _IG_TITLE_RE.sub("", name)
    name = _IG_SUFFIX_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" \t-–—|·•:,")
    parts = [p.strip(" -–—|·•:,") for p in _SEGMENT_RE.split(name)]
    parts = [p for p in parts if len(p) >= 2]
    if len(parts) > 1:
        if len({_key(p) for p in parts}) == 1:
            return parts[0]                            # "SOLESTAGE – Solestage"
        matching = [p for p in parts if site_row and q.name_matches_site(site_row, p)]
        if matching:
            # "Undefeated - La Brea" stays whole (store first, then its door);
            # "Shop Hellstar | The Attic Streetwear" and long taglines are trimmed.
            if matching[0] == parts[0] and "|" not in name and len(name) <= 40:
                return name
            return matching[0]
        if "|" in name:
            keep = [p for p in parts if p.lower() not in q.GENERIC_PAGE_TITLES] or parts
            return keep[0]
    return name


def clean_website(raw: str) -> str:
    url = q.normalize_website(raw)
    if not url:
        return ""
    base, _, query = url.partition("?")
    keep = [p for p in query.split("&") if p and not _TRACKING_RE.match(p)]
    return base + ("?" + "&".join(keep) if keep else "")


def clean_instagram(raw) -> str:
    handle = q.normalize_instagram(q.s(raw).rstrip(". "))
    if not handle or handle in IG_JUNK or handle.isdigit():
        return ""
    return "@" + handle


def phone_counts(rows: list[dict]) -> Counter:
    counts: Counter = Counter()
    for row in rows:
        raw = q.s(row.get("phone"))
        digits = q.normalize_phone(raw) or re.sub(r"\D", "", raw)
        if digits:
            counts[digits] += 1
    return counts


def clean_store(row: dict, counts: Counter) -> dict:
    """One STORES row (snake_case keys) -> display record with cleaned contact fields."""
    notes: list[str] = []
    raw = {k: q.s(row.get(k)) for k in ("store_name", "website", "instagram", "email", "phone")}
    city = fix_mojibake(q.s(row.get("city")))
    market = q.normalize_state(fix_mojibake(q.s(row.get("market"))))
    country = fix_mojibake(q.s(row.get("country"))) or "USA"

    instagram = clean_instagram(raw["instagram"])
    if raw["instagram"] and not instagram:
        notes.append(f"hid invalid Instagram '{raw['instagram'][:30]}'")
    website = ""
    m = _IG_PROFILE_URL_RE.match(raw["website"])
    if m and m.group(1).lower() not in q._IG_NON_PROFILE:
        from_url = clean_instagram(m.group(1))
        if from_url and from_url != instagram:
            notes.append("Instagram taken from the profile link in the website column")
            instagram = from_url
    elif raw["website"]:
        website = clean_website(raw["website"])
        if not website:
            notes.append(f"hid invalid website '{raw['website'][:40]}'")

    email = q.normalize_email(raw["email"]) or ""
    if raw["email"] and not email:
        notes.append(f"hid junk email '{raw['email'][:40]}'")

    phone = ""
    digits = q.normalize_phone(raw["phone"])
    raw_digits = re.sub(r"\D", "", raw["phone"])
    if digits and digits not in PHONE_JUNK and counts[digits] < REPEATED_PHONE:
        phone = q.format_phone(digits)
    elif raw_digits and country != "USA" and 7 <= len(raw_digits) <= 15 \
            and counts[raw_digits] < REPEATED_PHONE and re.search(r"[\s()+-]", raw["phone"]):
        phone = raw["phone"]                           # plausible international number
    elif raw_digits:
        why = f"on {counts[digits or raw_digits]} rows" if counts[digits or raw_digits] >= REPEATED_PHONE \
            else "not a real number"
        notes.append(f"hid fake phone {raw['phone'][:20]} ({why})")

    name = clean_name(raw["store_name"], {"Website": website, "Instagram": instagram, "City": city})
    full_title = re.sub(r"\s+", " ", fix_mojibake(html.unescape(raw["store_name"]))).strip()
    sheet_notes = fix_mojibake(q.s(row.get("notes")))
    evidence = sheet_notes if sheet_notes else (
        f"Site title: {full_title[:160]}" if _key(full_title) != _key(name) else "")

    rec = dict(row)
    rec.update({
        "Store Name": name, "City": city, "State": market, "Country": country,
        "Website": website, "Instagram": instagram, "Email": email, "Phone": phone,
        "Notes": evidence, "Last Order Date": q.s(row.get("last_order_date")),
        "_name": raw["store_name"],                    # exact sheet value, for writes
        "_cleaning": notes,
    })
    return rec


def mark_duplicates(records: list[dict]):
    """
    The scraper listed one site once per city it searched. Rows sharing a
    website (or Instagram) *and* a name are one store: keep the best-scored row
    and mark the rest. Differently named doors ("SoleFly Doral" / "SoleFly
    South Miami") are left alone.
    """
    groups = defaultdict(list)
    for i, rec in enumerate(records):
        domain = None if q.is_social_link(rec["Website"]) else q.website_domain(rec["Website"])
        handle = q.normalize_instagram(rec["Instagram"])
        presence = domain or handle
        name = _key(rec["Store Name"])
        if presence and name:
            groups[(presence, name)].append(i)
        elif name:
            groups[("", name, _key(rec["City"]))].append(i)
    for ids in groups.values():
        if len(ids) < 2:
            continue
        ids.sort(key=lambda i: (-records[i].get("_score", 0), i))
        keeper = records[ids[0]]
        for i in ids[1:]:
            records[i]["_duplicate_of"] = f"{keeper['Store Name']} ({keeper['City']})"


def annotate(records: list[dict]):
    """Add Cleanup Flag / Flag Reasons / format-level contact statuses, in place."""
    mark_duplicates(records)
    for rec, n in zip(records, q.count_locations(records)):
        flag, reasons = q.classify(rec, locations=n)
        if rec.get("_duplicate_of"):
            parts = [] if flag == "OK" else flag.split("+")
            flag = "+".join(["duplicate"] + parts)
            reasons = [f"same store as {rec['_duplicate_of']}"] + reasons
        rec["Cleanup Flag"] = flag
        rec["Flag Reasons"] = "; ".join(reasons)
        rec["Locations"] = n if n > 1 else ""
        rec.setdefault("IG Status", q.instagram_status(rec["Instagram"]))
        rec.setdefault("Web Status", q.website_status(rec["Website"]))
        rec.setdefault("Phone Status", q.phone_status(rec["Phone"]))
        rec.setdefault("Suggested Fixes", "")
    return records


def summarize(records: list[dict]) -> dict:
    buckets = Counter(r["_bucket"] for r in records)
    flags = Counter(part for r in records if r["_bucket"] != "qualified"
                    for part in r["Cleanup Flag"].split("+") if part and part != "OK")
    qualified = [r for r in records if r["_bucket"] == "qualified"]
    return {
        "total": len(records),
        "qualified": buckets["qualified"], "review": buckets["review"], "rejected": buckets["rejected"],
        "held_back_by": dict(flags.most_common()),
        "qualified_with_instagram": sum(1 for r in qualified if r["Instagram"]),
        "qualified_with_website": sum(1 for r in qualified if r["Website"] and r["Web Status"] != "social-link"),
        "qualified_with_phone": sum(1 for r in qualified if r["Phone"]),
        "qualified_with_email": sum(1 for r in qualified if r["Email"]),
        "hidden_fake_phones": sum(1 for r in records if any("fake phone" in n for n in r["_cleaning"])),
        "hidden_junk_instagram": sum(1 for r in records if any("invalid Instagram" in n for n in r["_cleaning"])),
        "hidden_junk_emails": sum(1 for r in records if any("junk email" in n for n in r["_cleaning"])),
    }


# ─────────────────────────────────────────
#  PERMANENT FIX  (the leads file itself)
# ─────────────────────────────────────────

CSV_CONTACT_FIELDS = ("Website", "Instagram", "Email", "Phone")


def scrub_leads(rows: list[dict]) -> dict:
    """
    Clean the contact columns of data/godspeed_leads_final.csv rows in place:
    fake phones, junk Instagram handles and junk emails are blanked, Instagram
    profile links move from Website to Instagram, phones get one format.
    Store names and every other column are left exactly as they are, and no
    row is removed. Returns counts of what changed.
    """
    as_stores = [{"store_name": r.get("Store Name", ""), "city": r.get("City", ""),
                  "market": r.get("State", ""), "country": r.get("Country", ""),
                  "website": r.get("Website", ""), "instagram": r.get("Instagram", ""),
                  "email": r.get("Email", ""), "phone": r.get("Phone", "")} for r in rows]
    counts = phone_counts(as_stores)
    changed = Counter()
    for row, store in zip(rows, as_stores):
        clean = clean_store(store, counts)
        for field in CSV_CONTACT_FIELDS:
            before, after = q.s(row.get(field)), clean[field]
            if before != after:
                changed[field + (" cleared" if not after else " filled" if not before else " reformatted")] += 1
                row[field] = after
    return dict(sorted(changed.items()))
