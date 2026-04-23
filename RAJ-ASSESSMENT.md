# Raj Patel — Godspeed Dashboard Assessment
**Date:** April 21, 2026  
**Audited by:** Raj Patel | El Barrio  
**Status:** Pre-rebuild technical review

---

## TL;DR

The dashboard looks polished but is functionally broken in several critical ways. The Google Sheet has grown into something the app was never designed for. The good news: the data *is* there — it just needs to be cleaned and reconnected. My recommendation is a **targeted rebuild** (not a full rewrite from scratch), focused on making the data layer match reality.

---

## What I Found

### The Spreadsheet

There are **100+ sheets** in this workbook. Here's what matters:

| Sheet | Rows | State |
|---|---|---|
| MASTER DATABASE | 3,808 | The real dataset. Never read by the dashboard. |
| ACQUISITION LEADS | 841 | What the dashboard reads. Subset of master, but messy. |
| OUTREACH LOG | 42 rows | **Wrong schema** — columns don't match what the app writes. |
| EXISTING RETAILERS | 2 rows | Basically empty. |
| City sheets (FL - Miami, NY - Soho, etc.) | ~100 sheets | Raw scraped data per city. The scraper dumped here instead of master. |

---

## What's Actually Broken

### 1. OUTREACH LOG — Schema Mismatch (Critical)
The app writes: `[Store Name, Channel, Message, Sent At, Response, Response At, Status, Agent]`

The sheet actually has: `[Store Name, City, State, Instagram, Followers, Website, Email, Phone, Outreach Channel, Notes, Date Added]`

**Every pitch logged goes into the wrong columns.** The entire outreach history (42 rows) is contact data, not message logs. The "Send Pitch" button does nothing useful right now — it's writing garbage to a misaligned sheet.

### 2. MASTER DATABASE — Never Connected
3,808 stores with email, Instagram, phone, Supreme/Hellstar/Godspeed carrier flags — and the dashboard ignores all of it. The app reads only ACQUISITION LEADS (841 rows). The real intelligence is sitting idle.

### 3. ACQUISITION LEADS — Data Quality Issues
- **0 out of 841 entries** have "Brands Carried" filled in. The column is completely empty.
- **21 entries** have `#ERROR!` values (phone numbers stored as broken formulas).
- **Car dealerships** and other junk are in the list (GMC Buick Dealership Fayetteville AR, Nissan Dealership Fayetteville AR, Superior Automotive Group, etc.). The scraper wasn't filtered.
- **All 841 leads** have Outreach Status = "Not Contacted". Nothing has ever been updated.

### 4. Retailers Page — Shows Nothing
The `/retailers` page filters for stores where `Outreach Status == "converted"`. Zero stores qualify. The page is empty. Always.

Similarly, `compute_stats()` counts "retailers" by checking for `Outreach Status == "converted"` — so the dashboard homepage shows **0 active retailers**.

### 5. Add Store — Writes to Wrong Sheet
The `/add-store` form writes to `MASTER DATABASE`. The dashboard reads from `ACQUISITION LEADS`. Any store you add manually never appears in the leads list.

### 6. The Scraper Is 100% Fake
The scraper button runs a demo mode. It sleeps, prints fake progress steps, and logs `"Completed (Demo Run)"` with hardcoded numbers (`847 stores scanned`, `23 new leads`). No actual scraping happens. It doesn't write to ACQUISITION LEADS. It doesn't find anything.

### 7. The EXISTING RETAILERS Sheet Has 1 Entry
One entry: `HELLSTAR - Backdoor Miami`. The phone is `1750677234` — that's a Unix timestamp, not a phone number. The sheet schema is also different from ACQUISITION LEADS, so there's no unified store model.

---

## The Data You Actually Have

**This is the good news.** MASTER DATABASE has real, usable data:

- **3,808 stores** with Store Name, City, State, Country, Website, Instagram, Email, Phone
- **Carrier flags**: Carries Supreme, Carries Hellstar, Carries Godspeed (columns exist, sparsely filled — most stores need re-verification)
- **1,594 stores** have emails
- **3,254 stores** have Instagram handles
- **13 stores** tagged "Not Started" — everything else has no outreach status at all

The city-specific sheets (FL - Miami, CA - Los Angeles, etc.) contain the raw scraped store data broken out by market. That's the scraper's output — it just dumped to 100 individual sheets instead of consolidating to master.

---

## My Answers to Your Questions

### 1. Fix vs Rebuild?

**Targeted rebuild.** Don't patch the existing app piecemeal — too many things are disconnected. But don't start from zero either, because the UI is solid (dark navy/gold theme, modal pitching, bulk select, filters). What needs rebuilding is the data layer: fix the sheet references, align the schemas, and wire the OUTREACH LOG correctly.

Estimate: **1-2 days** to get a fully functional version using the existing UI as the shell.

### 2. Data First?

**Yes. Data cleanup is a prerequisite.**

Before we touch the code, the sheet needs:
1. **OUTREACH LOG schema reset** — clear the 42 existing rows and redefine the headers to match what the app expects: `[Store Name, Channel, Message, Sent At, Response, Response At, Status, Agent]`
2. **ACQUISITION LEADS junk removal** — filter out car dealerships and any non-retail/non-streetwear businesses
3. **Decide on single source of truth** — either MASTER DATABASE becomes the canonical store list (recommended), or ACQUISITION LEADS does. Right now both exist separately and neither is complete.

I can automate the cleanup script if you tell me the criteria for what counts as a valid lead.

### 3. What Would a Clean Version Look Like?

Three core screens:

**A. Leads Pipeline** — Read from MASTER DATABASE, filtered to stores that don't carry Godspeed. Show name, city, state, Instagram, email, outreach status. Pitch button logs to OUTREACH LOG correctly.

**B. Outreach Log** — Full history of all pitches sent. Filterable by store, channel, date. Response tracking.

**C. Overview** — Real numbers. How many leads, how many pitched, how many replied, how many converted. The funnel should show actual data, not zeros.

The scraper page can stay but needs to either connect to a real source or be removed. Right now it's theater.

### 4. How Long?

If the data is cleaned first (2-4 hours of sheet work):
- **Backend rewrite** (fix routes, align schema, use MASTER DATABASE as source): ~4 hours
- **Frontend cleanup** (minor fixes, make retailers page work, fix add-store form): ~2 hours  
- **Testing + QA**: ~2 hours

**Total: 1 solid day of focused work** to get a fully functional dashboard. Two days if we're also building the outreach response-tracking workflow.

### 5. What Does Goldie Need to Provide?

1. **Confirm which sheet is the master list** — MASTER DATABASE (3,808 rows) or ACQUISITION LEADS (841 rows)? Or do they need to be merged?
2. **Define "valid lead"** — What disqualifies a store? (We need this to write the cleanup filter: already confirmed car dealers are in there)
3. **Outreach history decision** — The 42 rows in OUTREACH LOG are store contacts, not pitch history. Keep as contacts, or delete and start fresh?
4. **The "Brands Carried" column** — Is this something Goldie wants to populate, or was it supposed to come from the scraper? All 841 rows are blank.
5. **Existing retailers** — Who are Godspeed's current stockists? That data isn't in the sheet yet (EXISTING RETAILERS has 1 fake entry).

---

## Immediate Next Steps (In Order)

1. **Goldie answers the 5 questions above**
2. **I run a data cleanup script** — removes junk, resets OUTREACH LOG schema, consolidates stores
3. **Rebuild the data layer** in app.py — point everything at MASTER DATABASE, fix add-store route, fix pitch logging
4. **QA pass** — verify leads page shows real data, pitch button logs correctly, retailers page works

---

*This is a solid foundation. The UI is good, the data exists, the auth works. We just need to reconnect the wires.*

— Raj
