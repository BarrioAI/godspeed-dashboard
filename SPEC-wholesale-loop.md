# Godspeed Wholesale Operating Loop

**Purpose:** Turn the dormant dashboard into a self-feeding machine that sources qualified stores, works them top-down, closes accounts, invoices automatically, and drives reorders.

**North-star KPI:** Reorder rate. First orders that never repeat are noise. Accounts that reorder *are* the business.

**Who does what:** Claude Code runs the system (sourcing, scoring, cleaning, verification, sync, the dashboard and its schema). Goldie decides, sends outreach and closes. See `CLAUDE.md` for how each job is run.

---

## The Loop — 8 stages

Every stage has an **entry trigger**, an **owner**, an **action**, an **exit trigger**, and **what it writes**. A dormant loop is one where exit triggers don't fire. This is what wakes it up.

| # | Stage | Owner | Entry trigger | Action | Exit trigger → next |
|---|-------|-------|---------------|--------|---------------------|
| 0 | **SOURCE** (standing job, weekly) | Claude Code | Scheduled run | Scrape anchor-brand stockist pages + IG follow-graph / tagged-brands of the 4 live accounts → raw candidate rows | Batch lands in `CANDIDATES` |
| 1 | **SCORE** | Claude Code | New `CANDIDATES` batch | Apply scoring rubric, dedupe against `STORES` | Score ≥60 → write to `STORES` (validate-on-write); 40–59 → `nurture`; <40 → `rejected` |
| 2 | **OUTREACH** | Goldie | New `STORES` row, `stage=queued` | Work queue top-down by `lead_score`; market-calibrated, proof-led, sequenced (touch 1/2/3) | First touch sent → `stage=contacted` |
| 3 | **ENGAGE** | Goldie | Reply received | Log reply, send Brandboom line sheet, qualify intent | Positive intent → `stage=line_sheet_sent`; ghost after seq → `stage=dormant_lead` |
| 4 | **CLOSE** | Goldie | `line_sheet_sent` | Terms (deposit vs Net 30), sample if needed, agreement | First order placed → `stage=won`, write to `ORDERS` |
| 5 | **FULFILL** | Dashboard | `ORDERS` row created | Confirm stock, mark order `confirmed` | `order.status=confirmed` |
| 6 | **INVOICE** | Dashboard | `order.status=confirmed` | Auto-generate invoice → Stripe (US/EU) or wire flag (LatAm); send | Webhook → `INVOICES.status=paid/overdue` |
| 7 | **REORDER** | Claude Code + Goldie | Days since last order > cadence | Claude Code flags accounts due; Goldie re-engages with new drop/restock | New order → reorder counter++; this is the KPI that matters |

---

## Stage 1 — The Scoring Rubric

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

### Anchor brands to scrape, by market

- **LatAm (warm):** start with what Broken Chains + Hype already stock. Layer in Carrots, Pleasures, Market, Born x Raised — imported US streetwear LatAm boutiques actually carry. Blessd / Westcol / Bizzy relationships open the door once a store is on the list.
- **West Coast US:** Brain Dead, Awake NY, Born x Raised, Honor the Gift, Sky High Farm.
- **Spain / France / UK (cold-proof):** reverse-engineer the stockist pages of END., Goodhood, Black Sheep, Citadium, Starcow, The Broken Arm — and the European stockist lists of the peer brands above.

**Lookalike seeds:** mine the IG follow-graphs, tagged brands, and city clusters of your 4 live accounts — Broken Chains (Medellín), Hype (Bogotá), Treats 787 (San Juan), Future Visions (Lima). Each seed surfaces 20–40 stores just like it.

---

## Data Model

Store details are written only through the leads file and the dashboard's sync (see `CLAUDE.md`). Validate-on-write at every intake — reject bad data at the door, never clean afterward.

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
1. Order flips to `confirmed` → the dashboard creates a Stripe invoice from the line items (terms + due date from the credit rule).
2. Stripe sends the hosted PDF + payment page, runs its own dunning/reminders.
3. Webhook updates `INVOICES.status` → paid / overdue, syncs to the `SALES` view.

**Coverage reality:**
- **US (incl. Puerto Rico → Treats 787) + EU** → Stripe cards / ACH / SEPA. Fully automatic.
- **Colombia (Broken Chains) + Peru (Future Visions)** → cross-border; Stripe coverage thin. Collect via wire / Wise, set `payment_method=wire`, mark paid manually. No fully-automated path exists for LatAm cross-border — plan for the manual rail.

**Credit policy:** new accounts → deposit or pay-upfront until trust is established; proven reorder accounts → Net 30. **Tax:** confirm with your accountant US sales-tax nexus and EU VAT handling before going live — flag, don't assume.

**Build in Stripe test mode first**, validate the full ORDERS→INVOICES→webhook round trip, then switch to live.

> Lower-effort alternative: Brandboom native invoicing. Less to build, but weaker automation and no clean status feed into your dashboard. Recommendation is Stripe.

---

## Activation Sequence — dormant → live

Run in order.

1. **Schema.** `CANDIDATES` + `INVOICES` tabs and the new `STORES` fields exist. Validate-on-write rejects dupes/garbage at intake.
2. **Clean what is there.** `/clean-leads`, then `/sync-leads`, then `/verify-leads`. Work only from the Qualified view.
3. **First sourcing run.** `/add-leads` for each priority market: 5 anchor brands × 3 markets, plus the 4 lookalike seeds. Only stores that clear the rubric go in.
4. **Goldie works the top 20.** Top 20 by `lead_score`, sequenced (touch 1 → wait → touch 2 → wait → touch 3). Market-calibrated, proof-led. Log every touch in the dashboard.
5. **Wire Stripe (test mode).** Stand up the ORDERS→INVOICES→webhook path end to end on test data.
6. **Set the weekly cadence** below as a scheduled Claude Code task. One standing KPI tile on the dashboard: **reorder rate**, plus outstanding/overdue from `SALES`.

---

## Weekly Loop Cadence (once live)

- **Mon** — Claude Code: `/add-leads` for the week's market, `/verify-leads`, `/sync-leads` → queue refilled.
- **Tue–Thu** — Goldie works the queue top-down; replies advance stages; line sheets out.
- **Fri** — Claude Code reports: new qualified, reply rate, stage conversion, reorder rate, outstanding and overdue invoices.
- **Continuous** — confirmed orders auto-invoice; reorder-due accounts surface for re-engagement.

The loop is healthy when the queue never empties and reorder rate trends up. If the queue dries, the problem is upstream (scrape/score); if replies stall, it's outreach; if first orders don't repeat, it's product/relationship — and the dashboard now tells you which.
