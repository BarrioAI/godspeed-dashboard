# Godspeed Wholesale Operating Loop

**Purpose:** Turn the dormant dashboard into a self-feeding machine that sources qualified stores, works them top-down, closes accounts, invoices automatically, and drives reorders.

**North-star KPI:** Reorder rate. First orders that never repeat are noise. Accounts that reorder *are* the business.

**Owners:** Wilmar (read-only scraping) · Vito (scoring/analytics) · Jordan Belfort (outreach) · Raj (sole writer/dev — all schema + automation) · Warren Buffet (credit terms) · Brian Steele (legal/tax) · Adolfo (router — delegates, never implements)

---

## The Loop — 8 stages

Every stage has an **entry trigger**, an **owner**, an **action**, an **exit trigger**, and **what it writes**. A dormant loop is one where exit triggers don't fire. This is what wakes it up.

| # | Stage | Owner | Entry trigger | Action | Exit trigger → next |
|---|-------|-------|---------------|--------|---------------------|
| 0 | **SOURCE** (standing job, weekly) | Wilmar | Scheduled run | Scrape anchor-brand stockist pages + IG follow-graph / tagged-brands of the 4 live accounts → raw candidate rows | Batch lands in `CANDIDATES` |
| 1 | **SCORE** | Vito | New `CANDIDATES` batch | Apply scoring rubric, dedupe against `STORES` | Score ≥60 → write to `STORES` (validate-on-write); 40–59 → `nurture`; <40 → `rejected` |
| 2 | **OUTREACH** | Jordan | New `STORES` row, `stage=queued` | Work queue top-down by `lead_score`; market-calibrated, proof-led, sequenced (touch 1/2/3) | First touch sent → `stage=contacted` |
| 3 | **ENGAGE** | Jordan | Reply received | Log reply, send Brandboom line sheet, qualify intent | Positive intent → `stage=line_sheet_sent`; ghost after seq → `stage=dormant_lead` |
| 4 | **CLOSE** | Jordan + Warren + Brian | `line_sheet_sent` | Terms (Warren: deposit vs Net 30), sample if needed, agreement (Brian) | First order placed → `stage=won`, write to `ORDERS` |
| 5 | **FULFILL** | Raj (system) | `ORDERS` row created | Confirm stock, mark order `confirmed` | `order.status=confirmed` |
| 6 | **INVOICE** | Raj (system) + Warren | `order.status=confirmed` | Auto-generate invoice → Stripe (US/EU) or wire flag (LatAm); send | Webhook → `INVOICES.status=paid/overdue` |
| 7 | **REORDER** | Jordan + Vito | Days since last order > cadence | Vito flags accounts due; Jordan re-engages with new drop/restock | New order → reorder counter++; this is the KPI that matters |

---

## Stage 1 — The Scoring Rubric (Vito)

Score 0–100. This is the gate that protects you from re-flooding the list into another 3,476-row mess. Only ≥60 enters the working pipeline.

| Signal | Weight | How to score |
|--------|--------|--------------|
| **Anchor/peer brands carried** | 0–40 | Strongest signal. Count matching brands they already stock. 1 match = 15, 2 = 28, 3+ = 40. A store carrying Denim Tears / Aimé Leon Dore / Rhude-tier is pre-qualified — they buy wholesale, buy this aesthetic, have the buyer. |
| **Genuine multi-brand boutique** | 0–15 | Real curated boutique = 15. Reseller / mall / dropshipper = 0. |
| **Identifiable buying contact** | 0–15 | Named buyer + email/DM path = 15. Generic info@ only = 6. None = 0. |
| **Activity / engagement** | 0–10 | Active IG, recent posts, healthy engagement band = 10. Stale account = 0. |
| **Price-tier match** | 0–10 | Carries goods at Godspeed's price point = 10. Far below = 0. |
| **Priority-market fit** | 0–10 | LatAm / West Coast US / Spain / France / UK = 10. Off-priority = 4. |

**Thresholds:** ≥60 → `STORES` (queued) · 40–59 → `nurture` (re-score next batch) · <40 → `rejected`.

### Anchor brands to scrape, by market (Wilmar's source list)

- **LatAm (warm):** start with what Broken Chains + Hype already stock. Layer in Carrots, Pleasures, Market, Born x Raised — imported US streetwear LatAm boutiques actually carry. Blessd / Westcol / Bizzy relationships open the door once a store is on the list.
- **West Coast US:** Brain Dead, Awake NY, Born x Raised, Honor the Gift, Sky High Farm.
- **Spain / France / UK (cold-proof):** reverse-engineer the stockist pages of END., Goodhood, Black Sheep, Citadium, Starcow, The Broken Arm — and the European stockist lists of the peer brands above.

**Lookalike seeds:** mine the IG follow-graphs, tagged brands, and city clusters of your 4 live accounts — Broken Chains (Medellín), Hype (Bogotá), Treats 787 (San Juan), Future Visions (Lima). Each seed surfaces 20–40 stores just like it.

---

## Data Model

Raj owns all writes. Validate-on-write at every intake — reject bad data at the door, never clean afterward.

### `CANDIDATES` (new — raw scrape output, pre-gate)
`candidate_id` · `name` · `source` (which anchor/seed produced it) · `instagram` · `website` · `brands_detected[]` · `city` · `market` · `raw_payload` · `scraped_at`

### `STORES` (existing — add fields)
Add: `lead_score` (int) · `source` · `stage` (queued→contacted→line_sheet_sent→won→dormant_lead) · `owner` · `buying_contact` · `last_contact_at` · `nurture_flag`

### `OUTREACH_LOG` (existing — keep as event log)
Every touch as an event: `store_id` · `touch_number` · `channel` · `template_used` · `sent_at` · `reply_at` · `outcome`. Stage lives on `STORES`; this stays the immutable history.

### `ORDERS` (existing)
`order_id` · `store_id` · `brandboom_ref` · `line_items` · `subtotal` · `status` (draft→confirmed→fulfilled) · `is_reorder` (bool) · `ordered_at`

### `INVOICES` (new)
`invoice_id` · `order_id` · `store_id` · `subtotal` · `terms` (deposit / Net 30) · `due_date` · `status` (draft→sent→paid→overdue) · `payment_method` (stripe / wire) · `stripe_invoice_id` · `paid_at`

### `SALES` view (rollup, not a table)
Live read over `ORDERS` + `INVOICES`: total booked, total collected, outstanding, overdue, reorder rate, revenue by market/account. This is your sales tracker.

---

## Invoicing — recommended architecture

**Front end:** Brandboom stays as catalog + line sheet + order capture.

**Automation engine:** Stripe Invoicing, triggered off `ORDERS`.
1. Order flips to `confirmed` → Raj's system creates a Stripe invoice from the line items (terms + due date from Warren's credit rule).
2. Stripe sends the hosted PDF + payment page, runs its own dunning/reminders.
3. Webhook updates `INVOICES.status` → paid / overdue, syncs to the `SALES` view.

**Coverage reality:**
- **US (incl. Puerto Rico → Treats 787) + EU** → Stripe cards / ACH / SEPA. Fully automatic.
- **Colombia (Broken Chains) + Peru (Future Visions)** → cross-border; Stripe coverage thin. Collect via wire / Wise, set `payment_method=wire`, mark paid manually. No fully-automated path exists for LatAm cross-border — plan for the manual rail.

**Credit policy (Warren):** new accounts → deposit or pay-upfront until trust is established; proven reorder accounts → Net 30. **Tax (Brian):** confirm US sales-tax nexus and EU VAT handling before going live — flag, don't assume.

**Build in Stripe test mode first**, validate the full ORDERS→INVOICES→webhook round trip, then switch to live.

> Lower-effort alternative: Brandboom native invoicing. Less to build, but weaker automation and no clean status feed into your dashboard. Recommendation is Stripe.

---

## Activation Sequence — dormant → live

Run in order. Each step has a single owner so nothing stalls waiting on "everyone."

1. **Raj — schema migration.** Add `CANDIDATES` + `INVOICES` tables and the new `STORES` fields. Deploy via Render. Confirm validate-on-write rejects dupes/garbage at intake.
2. **Wilmar — first scrape.** Run against a starter list: 5 anchor brands × your 3 priority markets, plus the 4 lookalike seeds. Target ~150 raw candidates into `CANDIDATES`.
3. **Vito — score the batch.** Apply the rubric. Expect ~30–50 to clear ≥60 and seed `STORES` as `queued`.
4. **Jordan — work the top 20.** This week, top 20 by `lead_score`, sequenced (touch 1 → wait → touch 2 → wait → touch 3). Market-calibrated, proof-led. Log every touch.
5. **Raj — wire Stripe (test mode).** Stand up the ORDERS→INVOICES→webhook path end to end on test data.
6. **Adolfo — set the weekly cadence.** Wilmar scrapes weekly → Vito scores → Jordan's queue refills automatically. One standing KPI tile on the dashboard: **reorder rate**, plus outstanding/overdue from `SALES`.

---

## Weekly Loop Cadence (once live)

- **Mon** — Wilmar scrape + Vito score → queue refilled.
- **Tue–Thu** — Jordan works queue top-down; replies advance stages; line sheets out.
- **Fri** — Vito reports: new qualified, reply rate, stage conversion, reorder rate, outstanding invoices. Warren flags overdue.
- **Continuous** — confirmed orders auto-invoice; reorder-due accounts surface for re-engagement.

The loop is healthy when the queue never empties and reorder rate trends up. If the queue dries, the problem is upstream (scrape/score); if replies stall, it's outreach; if first orders don't repeat, it's product/relationship — and the dashboard now tells you which.
