---
description: Read Goldie's Gmail for messages to and from stores, and log them in the dashboard
---
Keep the outreach log true without Goldie typing it in. Needs the Gmail connector. Read only:
never send, reply to, label, archive or delete an email, and never write to a store.

1. `python ops.py status`; stop and report if the dashboard is down or `sheets_error` is not null.
2. `python ops.py export stores -o /tmp/stores.csv` and `python ops.py threads > /tmp/threads.json`.
   Build a lookup of store email address and website domain -> store name and city (skip free-mail
   domains such as gmail.com when matching by domain; match those by full address only).
3. **Sent mail.** Search Gmail for mail Goldie sent in the last 8 days (`in:sent newer_than:8d`).
   For each message whose recipient matches a store: `python ops.py pitch --store … --city …
   --channel Email --message "<first 500 characters>" --at "<sent time, YYYY-MM-DD HH:MM>"
   --kind "First pitch"` (or `"Follow-up N"` when the store already has messages). The command
   answers `duplicate` for one already logged, so running twice is safe.
4. **Replies.** For every thread in `/tmp/threads.json`, and every store matched in step 3, search
   Gmail for mail from that store's address or domain since the last message to it. For each reply:
   read it, then `python ops.py reply --store … --city … --channel Email --text "<what they said,
   up to 500 characters>" --at "<received time>" --outcome <one of the below>`.
   - `interested` they want to know more, asked for pricing or the line sheet
   - `line_sheet` Goldie has already sent the line sheet in this thread
   - `in_talks` terms, minimums, samples or delivery are being discussed
   - `won` they placed an order
   - `declined` a clear no
   - `other` anything else, including auto-replies and out-of-office (say which in the text)
   When unsure, use `other`. Never mark `won` or `declined` on a guess.
5. Ignore everything that is not to or from a store in the dashboard. Do not read unrelated mail
   beyond the sender, recipient and subject needed to rule it out, and do not quote it anywhere.
6. Report in a few lines: messages logged, replies logged with store and outcome, who is now due a
   follow-up (`python ops.py threads`, `due: true`), and anything you could not match.

Instagram DMs cannot be read from here. Goldie logs those with the Log reply button.
