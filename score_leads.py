"""Score Godspeed outreach leads (US + Colombia) and emit a unified CSV.

Reads:
  data/master_backup_20260511_144030.csv  (US stores)
  data/colombia_stores_final.csv          (Colombia stores)

Writes:
  data/godspeed_leads_scored.csv          (all stores, fresh Lead Score / Tier / Breakdown)

Rubric (100 pts max):
  Contact Quality (30): IG +10, Email +12, Phone +8
  Brand Alignment (25): Supreme +10, Hellstar +10, Godspeed +5  (per non-blank/No/N/A value)
  Market Tier (25):     Tier 1 city +25, Tier 2 city +15, else +5
  Outreach Readiness (20): IG+Email +20, IG only +10, Email only +8, neither 0

Tiering: A 75-100, B 45-74, C 0-44.
"""

import csv
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
US_CSV = DATA_DIR / "master_backup_20260511_144030.csv"
CO_CSV = DATA_DIR / "colombia_stores_final.csv"
OUT_CSV = DATA_DIR / "godspeed_leads_scored.csv"

US_SCHEMA = [
    "Store Name", "City", "State", "Country", "Website", "Instagram", "Email",
    "Phone", "Carries Supreme", "Carries Hellstar", "Carries Godspeed",
    "Last Order Date", "Outreach Status", "Outreach Channel", "Notes",
    "Date Added", "Lead Score", "Priority Tier",
]

# Final output column order: US schema + Colombia-only extras + breakdown.
_seen = set()
OUTPUT_COLUMNS = [c for c in US_SCHEMA + ["Brands Carried", "Score Reasons", "Score Breakdown"]
                  if not (c in _seen or _seen.add(c))]

TIER1_CITIES = {"nyc", "new york", "new york city", "los angeles", "la",
                "miami", "chicago", "houston", "atlanta", "atl"}
TIER2_CITIES = {"dallas", "phoenix", "seattle", "denver", "portland", "boston",
                "las vegas", "nashville", "charlotte", "philadelphia"}

# Values that count as "missing" for the rubric's not-blank/No/N/A check.
BLANK_VALUES = {"", "no", "n/a", "na", "none", "null"}


def read_csv_resilient(path: Path):
    """Read a CSV with utf-8, fall back to latin-1 on decode error."""
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not decode {path}")


def has_value(v) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() not in BLANK_VALUES


def normalize_city(city: str) -> str:
    """Lowercase + strip parenthetical suffix: 'Miami (Brickell)' -> 'miami'."""
    if not city:
        return ""
    c = city.lower().strip()
    if "(" in c:
        c = c.split("(", 1)[0].strip()
    return c


def market_points(city: str) -> int:
    nc = normalize_city(city)
    if nc in TIER1_CITIES:
        return 25
    if nc in TIER2_CITIES:
        return 15
    return 5


def detect_brand(brands_field: str, brand_name: str) -> bool:
    if not brands_field:
        return False
    return brand_name.lower() in brands_field.lower()


def normalize_colombia_row(row: dict) -> dict:
    """Map Colombia CSV columns into the US schema so scoring is uniform."""
    brands = row.get("Brands Carried", "") or ""
    return {
        "Store Name": row.get("Store Name", ""),
        "City": row.get("City", ""),
        "State": row.get("State", ""),
        "Country": "Colombia",
        "Website": "",
        "Instagram": row.get("Instagram", ""),
        "Email": row.get("Email", ""),
        "Phone": row.get("Phone", ""),
        "Carries Supreme": "Yes" if detect_brand(brands, "Supreme") else "",
        "Carries Hellstar": "Yes" if detect_brand(brands, "Hellstar") else "",
        "Carries Godspeed": "Yes" if detect_brand(brands, "Godspeed") else "",
        "Last Order Date": "",
        "Outreach Status": "",
        "Outreach Channel": "",
        "Notes": row.get("Score Reasons", ""),
        "Date Added": "",
        "Lead Score": row.get("Lead Score", ""),
        "Priority Tier": row.get("Priority Tier", ""),
        "Brands Carried": brands,
        "Score Reasons": row.get("Score Reasons", ""),
    }


def normalize_us_row(row: dict) -> dict:
    out = {col: row.get(col, "") for col in US_SCHEMA}
    out["Brands Carried"] = ""
    out["Score Reasons"] = ""
    if not (out.get("Country") or "").strip():
        out["Country"] = "USA"
    return out


def score_row(row: dict) -> tuple[int, str, str]:
    has_ig = has_value(row.get("Instagram"))
    has_em = has_value(row.get("Email"))
    has_ph = has_value(row.get("Phone"))

    contact = (10 if has_ig else 0) + (12 if has_em else 0) + (8 if has_ph else 0)

    brand = 0
    if has_value(row.get("Carries Supreme")):
        brand += 10
    if has_value(row.get("Carries Hellstar")):
        brand += 10
    if has_value(row.get("Carries Godspeed")):
        brand += 5

    market = market_points(row.get("City", ""))

    if has_ig and has_em:
        reach = 20
    elif has_ig:
        reach = 10
    elif has_em:
        reach = 8
    else:
        reach = 0

    total = contact + brand + market + reach
    if total >= 75:
        tier = "A-Tier"
    elif total >= 45:
        tier = "B-Tier"
    else:
        tier = "C-Tier"
    breakdown = f"Contact:{contact}/Brand:{brand}/Market:{market}/Reach:{reach}"
    return total, tier, breakdown


def main():
    us_rows_raw = read_csv_resilient(US_CSV)
    co_rows_raw = read_csv_resilient(CO_CSV)

    rows = []
    for r in us_rows_raw:
        if not (r.get("Store Name") or "").strip():
            continue
        rows.append(normalize_us_row(r))
    for r in co_rows_raw:
        if not (r.get("Store Name") or "").strip():
            continue
        rows.append(normalize_colombia_row(r))

    tier_counts = Counter()
    ig_count = em_count = ph_count = 0
    for row in rows:
        score, tier, breakdown = score_row(row)
        row["Lead Score"] = score
        row["Priority Tier"] = tier
        row["Score Breakdown"] = breakdown
        tier_counts[tier] += 1
        if has_value(row.get("Instagram")):
            ig_count += 1
        if has_value(row.get("Email")):
            em_count += 1
        if has_value(row.get("Phone")):
            ph_count += 1

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in OUTPUT_COLUMNS})

    total = len(rows)
    us_n = sum(1 for r in rows if (r.get("Country") or "").upper() == "USA")
    co_n = sum(1 for r in rows if r.get("Country") == "Colombia")

    print("=" * 72)
    print("GODSPEED LEAD SCORING — SUMMARY")
    print("=" * 72)
    print(f"Total stores scored:   {total}")
    print(f"  US stores:           {us_n}")
    print(f"  Colombia stores:     {co_n}")
    print()
    print("Tier distribution:")
    for t in ("A-Tier", "B-Tier", "C-Tier"):
        n = tier_counts[t]
        pct = (n / total * 100) if total else 0
        print(f"  {t}: {n:>5}  ({pct:5.1f}%)")
    print()
    print("Contact coverage:")
    print(f"  Instagram:  {ig_count:>5} / {total}  ({ig_count / total * 100:5.1f}%)")
    print(f"  Email:      {em_count:>5} / {total}  ({em_count / total * 100:5.1f}%)")
    print(f"  Phone:      {ph_count:>5} / {total}  ({ph_count / total * 100:5.1f}%)")
    print()
    print("Top 20 leads by score:")
    print(f"  {'#':>3}  {'Score':>5}  {'Tier':<7}  {'Name':<38}  {'City':<22}  State")
    top = sorted(rows, key=lambda r: (-int(r["Lead Score"]), r.get("Store Name", "")))[:20]
    for i, r in enumerate(top, 1):
        name = (r.get("Store Name") or "")[:38]
        city = (r.get("City") or "")[:22]
        state = (r.get("State") or "")[:18]
        print(f"  {i:>3}  {r['Lead Score']:>5}  {r['Priority Tier']:<7}  {name:<38}  {city:<22}  {state}")
    print()
    print(f"Output written to: {OUT_CSV}")
    print("=" * 72)


if __name__ == "__main__":
    main()
