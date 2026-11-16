---
description: The weekly sourcing run — find 30 to 40 new independent stores in the next market and add the ones that hold up
argument-hint: [market — optional; default is the next one in the rotation]
---
Add new prospects every week. Target 30 to 40 good stores; never pad the number. Ten real
boutiques beat forty guesses, and the report says how many were found and why.

**Who counts.** An independent, multi-brand streetwear / sneaker / contemporary boutique that buys
wholesale. Not a chain (10+ doors), not a brand's own store, not resale-only marketplaces, not a
mall or directory page. Best of all: stores that stock Hellstar, Sp5der, Rhude, Denim Tears,
Gallery Dept, Vale Forever, Fear of God, Off-White, BAPE, Amiri, Chrome Hearts, Stussy or Kith.

1. **Pick the market.** $ARGUMENTS if given. Otherwise read `data/sourcing_log.csv` and take the
   first market in this rotation that has not been run in the last 12 weeks:
   Charlotte, Philadelphia, Washington DC, Boston, Nashville, New Orleans, Phoenix, Denver,
   Portland, Minneapolis, Columbus, Cleveland, St. Louis, Kansas City, Baltimore, Raleigh, Memphis,
   Indianapolis, Salt Lake City, Sacramento, San Jose, Oakland, Honolulu, San Juan PR, Brooklyn,
   Queens, The Bronx, Harlem, Los Angeles, Miami, Houston, Chicago, Atlanta, Dallas, Detroit,
   San Diego, Las Vegas, Seattle, Orlando, Tampa, Bogotá, Medellín, Mexico City, Lima.
   If one market yields fewer than 30, continue with the next one in the same run.
2. **Search.** Use web search (several queries per market): "<city> streetwear boutique",
   "<city> sneaker store independent", "<brand> stockist <city>" for the brands above, local
   "best streetwear stores in <city>" guides. A guide or directory is a source of names, never a
   row: find each store's own website and Instagram handle.
3. **Record only what a source shows.** Name, city, state, country, website (the store's own
   domain), Instagram handle, email, phone. Leave unknown fields blank; never guess a handle, an
   email or a phone. Put the evidence in Notes, e.g. "Sourced 2026-11-22 — Axios Charlotte guide;
   carries Denim Tears, Gallery Dept". Brands go in Notes with their source, not in Brands Carried
   (verification fills that from the store's own site).
4. **Filter.** Skip anything already in `data/godspeed_leads_final.csv` (same website domain, same
   Instagram handle, or same name and city). Run `quality.classify` on each candidate: only `OK`
   goes in. A store needs a name, a city and at least one way to reach it.
5. **Add.** Append the rows with `Outreach Status` = `Not Contacted` and today's `Date Added`,
   score with `score_leads.score_row`, add a line to `data/sourcing_log.csv`
   (`date,market,found,added,notes`), then validate and test.
6. **Prove.** After the change is merged and synced (see `/refresh-leads`), `python ops.py verify`
   reads each new store's own website. A new store whose site does not load, or shows nothing that
   looks like a clothing store, is not deleted: say so in the report so Goldie can reject it.
7. **Report** the new stores as a list: name, city, how to reach it, the evidence, and which of
   them verification confirmed.

This session cannot open store websites itself (the network only allows the dashboard); web search
results and the dashboard's verification are the evidence. Say so if that limited a run.
