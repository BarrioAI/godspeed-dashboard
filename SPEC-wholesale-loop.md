# Godspeed Wholesale Loop Spec

*Filed: 2026-06-29 — Do not implement until explicitly instructed.*

## Overview
Automated wholesale outreach loop for Godspeed brand targeting independent streetwear boutiques across the US and Colombia.

## Data Source
- Primary: `data/godspeed_leads_final.csv` (1,775 stores, A/B/C tiered)
- Priority order: A-Tier (70) → B-Tier (703) → C-Tier (1,002, post-classification)

## Loop Phases

### Phase 1 — A-Tier Outreach (immediate)
- Channel priority: Instagram DM → Email → Phone
- Message: personalized intro referencing store identity + Godspeed brand fit
- Goal: get a buyer contact or wholesale inquiry response
- Volume: all 70 A-Tier stores
- Cadence: 1 touch per store, wait 7 days before follow-up

### Phase 2 — B-Tier Outreach
- Same channel priority as Phase 1
- Slightly templated (less custom per store)
- Volume: 703 stores
- Cadence: batch of 50/day

### Phase 3 — C-Tier Classification + Outreach
- Run classification pass first (store vs. scraped content)
- Outreach only to confirmed stores
- Bulk template, lowest personalization

## Outreach Templates (to be written)
- [ ] Instagram DM template (short, hype-aware, brand voice)
- [ ] Email subject lines (3 variants for A/B test)
- [ ] Email body (2 variants: cold intro + Hellstar carrier angle)
- [ ] Follow-up template (day 7)

## Tracking
- Log all outreach attempts to OUTREACH_LOG tab in Google Sheet
- Fields: Store Name, Channel, Sent At, Status, Response
- Update pipeline_stage in STORES tab on response

## Success Metrics
- Response rate target: >10% on A-Tier
- Conversion to wholesale account: >2% overall
- Timeline: Phase 1 complete within 2 weeks of go-ahead

## Dependencies
- [ ] Outreach templates approved by Goldie
- [ ] Instagram DM tool or manual flow confirmed
- [ ] Email sender domain warmed up (if using email blast)
- [ ] C-Tier classification pass complete before Phase 3

## Status
FILED — awaiting Goldie go-ahead to begin Phase 1.
