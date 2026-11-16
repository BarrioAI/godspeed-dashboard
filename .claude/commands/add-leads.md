---
description: Find new independent stores for a market and add the ones that qualify
argument-hint: <market, e.g. "Los Angeles" or "Medellín">
---
Source new stores for: $ARGUMENTS

Target: independent, multi-brand streetwear / sneaker / contemporary boutiques that buy wholesale.
Not chains (10+ doors), not a brand's own store, not resale-only marketplaces. The scoring rubric
and the anchor brands to look for are in `SPEC-wholesale-loop.md`.

1. Research with web search: stockist pages of the anchor brands for that market, and local
   "streetwear boutique" results. Open each candidate's own website.
2. For each candidate record only what its own site or Instagram shows: name, city, state/market,
   country, website, Instagram handle, email, phone, and which anchor brands it stocks (in Notes,
   e.g. "Carries Brain Dead, Awake NY — from stockist page"). Leave unknown fields blank.
3. Skip anything already in `data/godspeed_leads_final.csv` (same name + city, or same website).
4. Check each new row with `quality.classify`; anything not `OK` does not go in. Say why.
5. Append the rows to the leads file with `Outreach Status` = `Not Contacted` and today's
   `Date Added`, score them with `score_leads.score_row`, then validate and test.
6. Show Goldie the list with the evidence for each store before committing.
