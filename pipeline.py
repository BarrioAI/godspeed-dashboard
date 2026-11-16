"""
Build the clean MASTER DATABASE from every store tab in the spreadsheet.

Pure data-in / data-out (no Google, no network):

    tabs = {"ACQUISITION LEADS": [[header...], [row...], ...], ...}
    records, stats = build_master(tabs)

Every source tab is read by header name, each row is cleaned (fake phones,
CSS tokens posing as Instagram handles, tracker emails, Instagram links in the
Website column ...), the same store appearing on several tabs is merged into one
row, and every row is classified with quality.classify().

Nothing is ever deleted: rejected rows stay in the output with a Cleanup Flag
explaining why, and the source tabs are never written to.
"""

from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from datetime import date, datetime

import quality as q

MASTER_TAB = "MASTER DATABASE"

MASTER_HEADERS = [
    "Store Name", "City", "State", "Country", "Website", "Instagram", "Email",
    "Phone", "Carries Godspeed", "Outreach Status", "Outreach Channel",
    "Last Order Date", "Notes", "Date Added", "Lead Score", "Priority Tier",
    "Cleanup Flag", "Flag Reasons", "Review", "IG Status", "Web Status", "Phone Status",
    "Suggested Fixes", "Locations", "Cleaning Notes", "Sources",
]

# Fields a person (or the dashboard) edits by hand. A rebuild keeps them.
MANUAL_FIELDS = ("Outreach Status", "Outreach Channel", "Last Order Date", "Review")
# Live-verification results. A rebuild keeps them while the value they describe
# is unchanged.
VERIFY_FIELDS = {"IG Status": "Instagram", "Web Status": "Website", "Phone Status": "Phone"}

# Tabs that are not lists of stores.
NON_STORE_TABS = {
    "outreach log", "outreach_log", "scraper log", "orders", "orders (pre-v2 backup)",
    "rejected", "candidates", "invoices",
}

# Which tab to believe when two disagree (higher wins).
def tab_priority(tab: str) -> int:
    t = tab.strip().lower()
    if t == MASTER_TAB.lower():
        return 100          # edits made in the clean database always win
    if t == "existing retailers":
        return 90
    if t == "acquisition leads":
        return 80
    if t == "stores":
        return 40
    if t.startswith("master database"):
        return 30
    return 60               # hand-built city / market tabs

HEADER_ALIASES = {
    "name": ("store name", "store_name", "name", "store"),
    "city": ("city",),
    "state": ("state", "market", "state/province", "province"),
    "country": ("country",),
    "website": ("website", "https://website", "url", "site"),
    "instagram": ("instagram", "ig", "instagram handle"),
    "email": ("email", "e-mail"),
    "phone": ("phone", "phone number"),
    "status": ("outreach status", "pipeline_stage", "reorder status", "status"),
    "channel": ("outreach channel",),
    "notes": ("notes", "note"),
    "brands": ("brands carried", "brands"),
    "date_added": ("date added", "added date"),
    "last_order": ("last order date", "last_order_date"),
    "carries_godspeed": ("carries godspeed",),
    "carries_supreme": ("carries supreme",),
    "carries_hellstar": ("carries hellstar",),
    "cleanup_flag": ("cleanup flag",),
    "ig_status": ("ig status",),
    "web_status": ("web status",),
    "phone_status": ("phone status",),
    "suggested": ("suggested fixes",),
    "locations": ("locations",),
    "review": ("review",),
}

STATUS_WORDS = {
    "not contacted": "Not Contacted", "new lead": "New Lead", "pitched": "Pitched",
    "contacted": "Pitched", "replied": "Replied", "interested": "Replied",
    "converted": "Converted", "declined": "Declined", "not interested": "Declined",
    "active customer": "Converted", "active": "Converted", "warm": "Replied",
    "check in": "Converted", "reorder sent": "Converted",
    "research needed": "Not Contacted",
}
CUSTOMER_STATUSES = {"active customer", "active", "check in", "converted", "reorder sent"}

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
YES = {"yes", "y", "true", "1"}

_IG_TITLE_RE = re.compile(r"\s*\(@[\w.]+\).*$")
_IG_SUFFIX_RE = re.compile(r"\s*[•·|-]\s*instagram.*$", re.I)
_TRACKING_RE = re.compile(r"(?i)^(?:srsltid|utm_[a-z]+|fbclid|gclid|ref|hl|igshid|igsh)=")
_IG_PROFILE_URL_RE = re.compile(r"(?i)^(?:https?://)?(?:www\.|m\.)?instagram\.com/([A-Za-z0-9._]+)/?(?:\?.*)?$")


# ─────────────────────────────────────────
#  CELL CLEANERS
# ─────────────────────────────────────────

def _cell(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return q.s(value)


def _fix_mojibake(text: str) -> str:
    """'BogotÃ¡' -> 'Bogotá' (UTF-8 that was read as Latin-1 somewhere upstream)."""
    text = re.sub(r"_x00([0-9A-Fa-f]{2})_", lambda m: chr(int(m.group(1), 16)), text)
    if "Ã" in text or "â\x80" in text or "Â" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
    return text


_SEGMENT_RE = re.compile(r"\s+[|–—:·•]\s+|\s+-\s+|\s*\|\s*|:\s+")


def clean_name(raw: str, site_row: dict | None = None) -> str:
    """
    Scraped names are page titles ("Shop Hellstar | The Attic Streetwear").
    Keep the segment that matches the row's own website / Instagram.
    """
    name = _fix_mojibake(html.unescape(html.unescape(raw)))
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


def clean_date(raw: str) -> str:
    """'2026-04-21 00:00:00' or '4/21/2026' (how Sheets displays dates) -> '2026-04-21'."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return m.group(0)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})\b", raw)
    if m and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def clean_website(raw: str) -> str:
    url = q.normalize_website(raw)
    if not url:
        return ""
    base, _, query = url.partition("?")
    keep = [p for p in query.split("&") if p and not _TRACKING_RE.match(p)]
    return base + ("?" + "&".join(keep) if keep else "")


def clean_instagram(raw: str) -> str:
    handle = q.normalize_instagram(q.s(raw).rstrip(". "))
    if not handle or handle in IG_JUNK or handle.isdigit():
        return ""
    return "@" + handle


# ─────────────────────────────────────────
#  READING A TAB
# ─────────────────────────────────────────

def _header_map(header: list) -> dict[str, int]:
    names = [q.s(h).lower() for h in header]
    out = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in names:
                out[field] = names.index(alias)
                break
    return out


def is_store_tab(name: str, rows: list[list]) -> bool:
    if name.strip().lower() in NON_STORE_TABS or not rows:
        return False
    cols = _header_map(rows[0])
    return "name" in cols and "city" in cols


def read_tab(tab: str, rows: list[list]) -> list[dict]:
    """Rows of one tab -> raw records keyed by our field names."""
    cols = _header_map(rows[0])
    legacy_master = tab.strip().lower().startswith("master database") and tab.strip() != MASTER_TAB
    out = []
    for raw in rows[1:]:
        get = lambda f: _cell(raw[cols[f]]) if f in cols and cols[f] < len(raw) else ""
        rec = {f: get(f) for f in HEADER_ALIASES}
        if not rec["name"] or rec["name"].lower() in ("store name", "store_name"):
            continue                                   # blank line or a stray header row

        if legacy_master:
            _unshift_legacy_master(rec)

        rec["tab"] = tab
        rec["curated"] = _is_curated(tab, rec)
        out.append(rec)
    return out


def _is_curated(tab: str, rec: dict) -> bool:
    """
    False for raw scraper output: one row per search result, where the 'city'
    is the city that was searched rather than where the store is.
    """
    t = tab.strip().lower()
    if t == "stores":
        return bool(rec["notes"]) or rec["country"].upper() not in ("USA", "US", "")
    if t.startswith("master database") and tab.strip() != MASTER_TAB:
        return bool(rec["status"])
    return True


def _unshift_legacy_master(rec: dict):
    """
    The old master tab holds two older layouts under its current headers:
      * hand-curated rows: Email/Phone/Carries Supreme actually hold the
        Supreme / Hellstar / Godspeed yes-no answers, 'Carries Godspeed' holds
        the outreach status and 'Last Order Date' holds the description;
      * scraped rows: 'Carries Godspeed' holds the date the row was added.
    """
    cg = rec["carries_godspeed"]
    if cg.lower() in STATUS_WORDS:
        answers = (rec["email"], rec["phone"], rec["carries_supreme"])
        rec["status"] = cg
        rec["notes"] = rec["notes"] or rec["last_order"]
        rec["last_order"] = ""
        rec["carries_godspeed"] = answers[2] if answers[2].lower() in YES else ""
        rec["carries_hellstar"] = answers[1] if answers[1].lower() in YES else ""
        rec["carries_supreme"] = answers[0] if answers[0].lower() in YES else ""
        rec["email"] = answers[0] if "@" in answers[0] else ""
        rec["phone"] = ""
    elif clean_date(cg):
        rec["date_added"] = rec["date_added"] or cg
        rec["carries_godspeed"] = ""
    if not clean_date(rec["last_order"]):
        if rec["last_order"] and not rec["notes"]:
            rec["notes"] = rec["last_order"]
        rec["last_order"] = ""


# ─────────────────────────────────────────
#  CLEANING ONE RECORD
# ─────────────────────────────────────────

def clean_record(rec: dict, phone_counts: Counter) -> dict:
    notes: list[str] = []
    city = _fix_mojibake(rec["city"])
    state = q.normalize_state(_fix_mojibake(rec["state"]))
    country = _fix_mojibake(rec["country"])
    if not country or country.upper() in ("US", "U.S.", "UNITED STATES", "U.S.A."):
        country = "USA" if (q.is_us_state(state) or not country) else country
    if country == "USA" and state and not q.is_us_state(state):
        country = state if not rec["country"] else country   # e.g. market tab 'Colombia'

    # Website / Instagram
    website_raw = rec["website"]
    instagram = clean_instagram(rec["instagram"])
    if rec["instagram"] and not instagram:
        notes.append(f"dropped invalid Instagram '{rec['instagram'][:30]}'")
    website = ""
    m = _IG_PROFILE_URL_RE.match(website_raw)
    if m and m.group(1).lower() not in ("p", "reel", "reels", "explore", "tv", "stories"):
        from_url = clean_instagram(m.group(1))
        if from_url and from_url != instagram:
            notes.append(f"Instagram taken from the profile link in the Website column"
                         + (f" (was {instagram})" if instagram else ""))
            instagram = from_url
        else:
            notes.append("Website was only an Instagram link — moved to Instagram")
    elif website_raw:
        website = clean_website(website_raw)
        if not website:
            notes.append(f"dropped invalid website '{website_raw[:40]}'")
        elif q._IG_POST_RE.search(website):
            pass                                      # kept so the row is flagged not-a-store
        elif q.is_social_link(website):
            notes.append("Website is a social / directory link, not the store's own site")

    name = clean_name(rec["name"], {"Website": website, "Instagram": instagram, "City": city})
    full_title = re.sub(r"\s+", " ", _fix_mojibake(html.unescape(html.unescape(rec["name"])))).strip()
    title_note = f"Site title: {full_title[:160]}" if _key(full_title) != _key(name) and not rec["notes"] else ""

    # Email
    email = q.normalize_email(rec["email"]) or ""
    if rec["email"] and not email and rec["email"].lower() not in ("no", "none", "unknown", "n/a"):
        notes.append(f"dropped junk email '{rec['email'][:40]}'")

    # Phone
    phone = ""
    digits = q.normalize_phone(rec["phone"])
    raw_digits = re.sub(r"\D", "", rec["phone"])
    if digits and digits not in PHONE_JUNK and phone_counts[digits] < 4:
        phone = q.format_phone(digits)
    elif raw_digits and country not in ("USA", "") and 7 <= len(raw_digits) <= 15 \
            and phone_counts[raw_digits] < 4 and re.search(r"[\s()+-]", rec["phone"]):
        phone = rec["phone"]                          # plausible international number
    elif raw_digits:
        why = "repeated on many rows" if phone_counts[digits or raw_digits] >= 4 else "not a real number"
        notes.append(f"dropped fake phone {rec['phone'][:20]} ({why})")

    status_raw = rec["status"].lower()
    status = STATUS_WORDS.get(status_raw, rec["status"] if rec["status"] else "Not Contacted")
    carries = "Yes" if (rec["carries_godspeed"].lower() in YES or status_raw in CUSTOMER_STATUSES) else ""

    extra = []
    if rec["brands"]:
        extra.append(f"Brands: {rec['brands']}")
    if rec["carries_hellstar"].lower() in YES:
        extra.append("Carries Hellstar")
    if rec["carries_supreme"].lower() in YES:
        extra.append("Carries Supreme")
    note_text = " · ".join([_fix_mojibake(rec["notes"])] * bool(rec["notes"]) + extra
                           + [title_note] * bool(title_note))

    return {
        "Store Name": name, "City": city, "State": state, "Country": country,
        "Website": website, "Instagram": instagram, "Email": email, "Phone": phone,
        "Carries Godspeed": carries, "Outreach Status": status,
        "Outreach Channel": rec["channel"], "Last Order Date": clean_date(rec["last_order"]),
        "Notes": note_text, "Date Added": clean_date(rec["date_added"]),
        "IG Status": rec["ig_status"], "Web Status": rec["web_status"],
        "Phone Status": rec["phone_status"], "Suggested Fixes": rec["suggested"],
        "Locations": rec["locations"], "Review": rec["review"],
        "_notes": notes, "_tab": rec["tab"], "_prio": tab_priority(rec["tab"]),
        "_curated": rec["curated"],
    }


# ─────────────────────────────────────────
#  MERGING DUPLICATES
# ─────────────────────────────────────────

def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _similar(a: str, b: str) -> bool:
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return False
    if ka in kb or kb in ka:
        return True
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, len(ta | tb)) >= 0.6


def merge_duplicates(records: list[dict]) -> list[dict]:
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    by_name = defaultdict(list)
    by_site = defaultdict(list)
    for i, r in enumerate(records):
        city = _key(r["City"])
        by_name[(_key(r["Store Name"]), city)].append(i)
        domain = q.website_domain(r["Website"])
        if domain and not q.is_social_link(r["Website"]):
            by_site[("d", domain, city)].append(i)
        handle = q.normalize_instagram(r["Instagram"])
        if handle:
            by_site[("i", handle, city)].append(i)

    for ids in by_name.values():
        for i in ids[1:]:
            union(ids[0], i)
    # Same website or Instagram in the same city: one store if the names agree
    # ("LUXE MIAMI" / "Luxe Miami Boutique"), two doors if they don't
    # ("Undefeated - La Brea" / "Undefeated - Silver Lake").
    for ids in by_site.values():
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                if _similar(records[ids[a]]["Store Name"], records[ids[b]]["Store Name"]):
                    union(ids[a], ids[b])

    # Scraper output lists the same site once per city it searched. Fold every
    # scraped row for a site into one store (or into the curated row for that
    # site when there is one) instead of inventing a door per search.
    has_curated = defaultdict(bool)
    for i, r in enumerate(records):
        if r["_curated"]:
            has_curated[find(i)] = True
    by_presence = defaultdict(list)
    for i, r in enumerate(records):
        domain = q.website_domain(r["Website"])
        handle = q.normalize_instagram(r["Instagram"])
        if domain and not q.is_social_link(r["Website"]):
            by_presence[("d", domain)].append(i)
        elif handle:
            by_presence[("i", handle)].append(i)
    for ids in by_presence.values():
        orphans = [i for i in ids if not records[i]["_curated"] and not has_curated[find(i)]]
        curated = [i for i in ids if records[i]["_curated"]]
        for i in orphans[1:]:
            union(orphans[0], i)
        if orphans and curated:
            cities = Counter(_key(records[i]["City"]) for i in orphans)
            home = next((c for c in curated if _key(records[c]["City"]) in cities), curated[0])
            union(orphans[0], home)

    # Even on the hand-built tabs, one store was often listed once per city
    # searched. Same site + same name = one store; differently named doors
    # ("SoleFly Doral" / "SoleFly South Miami") stay separate.
    for ids in by_presence.values():
        seen: dict[str, int] = {}
        for i in ids:
            k = _key(records[i]["Store Name"])
            if k in seen:
                union(seen[k], i)
            else:
                seen[k] = i

    groups = defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(records[i])

    merged = []
    for group in groups.values():
        cities = Counter(r["City"] for r in group if not r["_curated"] and r["City"])
        any_curated = any(r["_curated"] for r in group)
        # a curated row wins; among scraped rows prefer a name that matches the
        # site and the city the site was found in most often
        group.sort(key=lambda r: (
            not r["_curated"], -r["_prio"],
            q.name_matches_site(r) is False,
            -cities.get(r["City"], 0), len(r["Store Name"]),
        ))
        best = dict(group[0])
        best["_search_cities"] = 0 if any_curated else len(cities)
        if not any_curated and len(cities) > 1:
            group[0]["_notes"].append(
                f"city unconfirmed — site came up in searches for {len(cities)} cities")
        tabs = [group[0]["_tab"]]
        notes = list(group[0]["_notes"])
        for other in group[1:]:
            for field, value in other.items():
                if field.startswith("_"):
                    continue
                if not best.get(field) and value:
                    best[field] = value
            if best["Outreach Status"] in ("Not Contacted", "") and \
                    other["Outreach Status"] not in ("Not Contacted", ""):
                best["Outreach Status"] = other["Outreach Status"]
            if other["Carries Godspeed"]:
                best["Carries Godspeed"] = "Yes"
            if other["Notes"] and other["Notes"] not in best["Notes"] and len(best["Notes"]) < 400:
                best["Notes"] = (best["Notes"] + " · " + other["Notes"]).strip(" ·")
            if other["_tab"] not in tabs:
                tabs.append(other["_tab"])
            notes.extend(n for n in other["_notes"] if n not in notes)
        best["_notes"] = notes
        best["_tabs"] = tabs
        best["_merged"] = len(group)
        merged.append(best)
    return merged


# ─────────────────────────────────────────
#  BUILD
# ─────────────────────────────────────────

def annotate(records: list[dict]):
    """Classify + score every record in place (also used by the dashboard)."""
    locations = q.count_locations(records)
    for rec, n in zip(records, locations):
        stored = q.s(rec.get("Locations"))
        n = max(n, rec.pop("_search_cities", 0) or 0, int(stored) if stored.isdigit() else 0)
        flag, reasons = q.classify(rec, locations=n)
        points, tier, _ = q.score(rec)
        rec["Locations"] = n if n > 1 else ""
        rec["Cleanup Flag"] = flag
        rec["Flag Reasons"] = "; ".join(reasons)
        rec["Lead Score"] = points if flag == "OK" else ""
        rec["Priority Tier"] = tier if flag == "OK" else ""
        for status_field, value_field in VERIFY_FIELDS.items():
            fmt = {"Instagram": q.instagram_status, "Website": q.website_status,
                   "Phone": q.phone_status}[value_field](rec.get(value_field))
            current = q.s(rec.get(status_field))
            # keep a live-verified result; otherwise fall back to the format check
            if not current or fmt in ("empty", "invalid-format", "social-link") \
                    or current in ("empty", "format-ok", "invalid-format", "social-link"):
                rec[status_field] = fmt
    return records


def build_master(tabs: dict[str, list[list]]) -> tuple[list[dict], dict]:
    raw: list[dict] = []
    per_tab = {}
    for tab, rows in tabs.items():
        if not is_store_tab(tab, rows):
            continue
        recs = read_tab(tab, rows)
        per_tab[tab] = len(recs)
        raw.extend(recs)

    # A phone number that shows up on many different rows is a scraper artefact
    # (page IDs, timestamps), not a store's number.
    phone_counts: Counter = Counter()
    for rec in raw:
        if rec["tab"].strip() == MASTER_TAB:
            continue
        digits = q.normalize_phone(rec["phone"]) or re.sub(r"\D", "", rec["phone"])
        if digits:
            phone_counts[digits] += 1

    cleaned = [clean_record(r, phone_counts) for r in raw]
    cleaned = [r for r in cleaned if r["Store Name"]]
    merged = merge_duplicates(cleaned)
    annotate(merged)

    for rec in merged:
        rec["Cleaning Notes"] = "; ".join(rec.pop("_notes"))
        rec["Sources"] = ", ".join(rec.pop("_tabs"))
        for k in ("_tab", "_prio", "_merged", "_curated"):
            rec.pop(k, None)

    order = {"qualified": 0, "review": 1, "rejected": 2}
    merged.sort(key=lambda r: (
        order[q.bucket(r["Cleanup Flag"], r.get("Review", ""))],
        r["Carries Godspeed"] != "Yes",
        -(r["Lead Score"] or 0),
        r["State"], r["City"], r["Store Name"].lower(),
    ))

    flags = Counter()
    for rec in merged:
        for part in rec["Cleanup Flag"].split("+"):
            flags[part] += 1
    buckets = Counter(q.bucket(r["Cleanup Flag"], r.get("Review", "")) for r in merged)
    qualified = [r for r in merged if q.bucket(r["Cleanup Flag"], r.get("Review", "")) == "qualified"]
    stats = {
        "source_tabs": len(per_tab),
        "source_rows": len(raw),
        "unique_stores": len(merged),
        "duplicates_merged": len(cleaned) - len(merged),
        "qualified": len(qualified),
        "needs_review": buckets["review"],
        "rejected": buckets["rejected"],
        "flags": dict(flags.most_common()),
        "qualified_with_instagram": sum(1 for r in qualified if r["Instagram"]),
        "qualified_with_website": sum(1 for r in qualified if r["Web Status"] == "format-ok"
                                      or r["Web Status"].startswith("ok")),
        "qualified_with_phone": sum(1 for r in qualified if r["Phone"]),
        "qualified_with_email": sum(1 for r in qualified if r["Email"]),
        "current_accounts": sum(1 for r in merged if r["Carries Godspeed"] == "Yes"),
        "per_tab": per_tab,
    }
    return merged, stats


def to_rows(records: list[dict]) -> list[list]:
    """Records -> sheet rows (header first)."""
    return [MASTER_HEADERS] + [[rec.get(h, "") for h in MASTER_HEADERS] for rec in records]
