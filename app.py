"""
Godspeed Retail Intelligence System — Dashboard (v2)
Clean 3-tab schema: STORES / OUTREACH_LOG / ORDERS.

Quality layer (read-side)
-------------------------
STORES is shown through stores.py / quality.py: junk contact values are hidden,
every store gets a fit flag, and Leads is split into Qualified / Needs review /
Rejected. Nothing in STORES is rewritten by this layer. Two small tabs hold what
people and the verifier add, keyed by store name + city so they survive STORES
being re-synced from the CSV:

    REVIEW         a person's Approve / Reject decision (overrides the flag)
    VERIFICATION   live website / Instagram / phone check results

The dashboard writes STORES in two cases only: pipeline_stage when a pitch is
sent, and the Sync job, which brings STORES in line with the leads file in this
deploy (data/godspeed_leads_final.csv) without deleting rows or touching the
columns the dashboard owns.

Local dev: GODSPEED_LOCAL_DIR=/path/to/csvs (STORES.csv, OUTREACH_LOG.csv, ...)
reads those files instead of Sheets; writes stay in memory.
"""

from __future__ import annotations

import csv
import hmac
import io
import os
import re
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS

import quality as q
import sheets
import stores as store_rules
from sheets import ORDERS_TAB, OUTREACH_TAB, REVIEW_TAB, STORES_TAB, VERIFY_TAB

app = Flask(__name__)
CORS(app)

CACHE_TTL = 60          # seconds a sheet read is reused
PAGE_SIZE = 50
DEFAULT_COMMISSION = 0.10  # Goldie's 10%
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

# clean pipeline_stage  ->  badge word the templates style
STAGE_TO_BADGE = {
    "won": "Converted", "in talks": "Replied", "replied": "Replied",
    "line_sheet_sent": "Replied", "contacted": "Pitched", "pitched": "Pitched",
    "lost": "Declined", "disqualified": "Declined", "dormant_lead": "Declined",
    "new": "Not Contacted", "qualified": "Not Contacted", "queued": "Not Contacted",
    "new lead": "New Lead",
}
OPEN_BADGES = {"Not Contacted", "New Lead"}

OUTREACH_HEADERS = [
    "outreach_id", "store_id", "store_name", "channel", "direction", "template_used",
    "message", "status", "sent_at", "sent_by", "reply_text", "reply_at", "sentiment", "notes",
]


def stage_badge(stage):
    return STAGE_TO_BADGE.get((stage or "").strip().lower(), "Not Contacted")


# ─────────────────────────────────────────  OPTIONAL PASSWORD
@app.before_request
def require_password():
    """Set DASHBOARD_PASSWORD to put the site behind HTTP basic auth (any username)."""
    if not DASHBOARD_PASSWORD or request.path.startswith("/static/") or request.path == "/healthz":
        return None
    auth = request.authorization
    if auth and auth.password and hmac.compare_digest(auth.password, DASHBOARD_PASSWORD):
        return None
    return Response("Password required.", 401, {"WWW-Authenticate": 'Basic realm="Godspeed"'})


@app.route("/healthz")
def healthz():
    return "ok"


# ─────────────────────────────────────────  DATA LAYER
_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()


def invalidate():
    with _cache_lock:
        _cache["at"] = 0.0


def _records(rows: list[list]) -> tuple[list[str], list[dict]]:
    """Sheet values -> (headers, dicts). Every cell is a string; '_row' is the sheet row."""
    if not rows:
        return [], []
    headers = [q.s(h) for h in rows[0]]
    out = []
    for n, raw in enumerate(rows[1:], start=2):
        rec = {h: q.s(raw[i]) if i < len(raw) else "" for i, h in enumerate(headers) if h}
        rec["_row"] = n
        out.append(rec)
    return headers, out


_XLSX_ESCAPE_RE = re.compile(r"_x[0-9A-Fa-f]{4}_")


def _ascii_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _XLSX_ESCAPE_RE.sub("", q.s(text)).lower())


def store_key(name: str, city: str) -> tuple[str, str]:
    """
    Identity of a store across tabs and the leads file: ASCII letters and digits
    of its name and city. Everything else is ignored on purpose, so a name that
    was mangled on its way into the sheet ("MedellÃ\xadn" for "Medellín") still
    matches the correct spelling.
    """
    return _ascii_key(name), _ascii_key(city)


def is_customer(s):
    """A store is a customer (Accounts engine) once Won / has an account_status."""
    acc = (s.get("account_status", "") or "").strip().lower()
    stage = (s.get("pipeline_stage", "") or "").strip().lower()
    return acc in ("active", "dormant", "churned") or stage == "won"


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_stores(rows, review_rows, verify_rows) -> tuple[list[str], list[dict]]:
    headers, raw = _records(rows)
    raw = [r for r in raw if r.get("store_name")]

    decisions = {}
    for d in _records(review_rows)[1]:                 # append-only log: the last decision wins
        decisions[store_key(d.get("store_name", ""), d.get("city", ""))] = d.get("decision", "")
    checks = {store_key(v.get("store_name", ""), v.get("city", "")): v for v in _records(verify_rows)[1]}

    counts = store_rules.phone_counts(raw)
    records = []
    for row in raw:
        rec = store_rules.clean_store(row, counts)
        rec["_score"] = int(_num(row.get("lead_score")))
        rec["Priority Tier"] = q.s(row.get("priority_tier"))
        rec["Outreach Status"] = stage_badge(row.get("pipeline_stage"))
        rec["_customer"] = is_customer(row)
        rec["Carries Godspeed"] = "Yes" if rec["_customer"] else ""
        rec["_filled"] = []
        key = store_key(row["store_name"], row.get("city", ""))
        rec["Review"] = decisions.get(key, "")

        # Verification results apply only while the values they checked are unchanged.
        check = checks.get(key)
        if check and (check.get("website"), check.get("instagram"), check.get("phone")) == \
                (rec["Website"], rec["Instagram"], rec["Phone"]):
            rec["IG Status"] = check.get("ig_status", "")
            rec["Web Status"] = check.get("web_status", "")
            rec["Phone Status"] = check.get("phone_status", "")
            rec["Suggested Fixes"] = check.get("suggested_fixes", "")
            rec["_checked_at"] = check.get("checked_at", "")
            for field, found in (("Instagram", "found_instagram"), ("Phone", "found_phone"),
                                 ("Email", "found_email")):
                if not rec[field] and check.get(found):
                    rec[field] = check[found]          # shown, marked as "from website"
                    rec["_filled"].append(field)
            if check.get("site_mentions"):
                rec["Notes"] = (rec["Notes"] + " · " if rec["Notes"] else "") + \
                    "Site mentions: " + check["site_mentions"]
        records.append(rec)

    store_rules.annotate(records)
    for rec in records:
        rec["_bucket"] = q.bucket(rec["Cleanup Flag"], rec["Review"])
    return headers, records


def load_data(force: bool = False) -> dict:
    """
    One cached batch read of every tab the dashboard uses.
    Returns {"stores", "store_headers", "outreach", "orders", "error"}.
    """
    with _cache_lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_TTL:
            return _cache["data"]
    try:
        ss = sheets.open_spreadsheet()
        tabs = sheets.read_tabs(ss, [STORES_TAB, OUTREACH_TAB, ORDERS_TAB, REVIEW_TAB, VERIFY_TAB])
    except Exception as exc:                           # credentials, network, quota
        return {"stores": [], "store_headers": [], "outreach": [], "orders": [],
                "error": f"{type(exc).__name__}: {exc}"}

    headers, records = _build_stores(tabs[STORES_TAB], tabs[REVIEW_TAB], tabs[VERIFY_TAB])
    outreach = []
    for o in _records(tabs[OUTREACH_TAB])[1]:
        if not o.get("store_name"):
            continue
        o.update({"Store Name": o.get("store_name", ""), "Channel": o.get("channel", ""),
                  "Message": o.get("message", ""), "Sent At": o.get("sent_at", ""),
                  "Status": o.get("status", ""), "Response": o.get("reply_text", "")})
        outreach.append(o)
    orders = [o for o in _records(tabs[ORDERS_TAB])[1] if any(v for k, v in o.items() if k != "_row")]
    data = {"stores": records, "store_headers": headers, "outreach": outreach, "orders": orders,
            "error": None if tabs[STORES_TAB] else f"The {STORES_TAB} tab is empty or missing."}
    with _cache_lock:
        _cache.update(at=time.time(), data=data)
    return data


def get_stores():
    data = load_data()
    return data["stores"], data["error"]


def compute_stats(stores: list[dict], outreach: list[dict]) -> dict:
    customers = [s for s in stores if s["_customer"]]
    prospects = [s for s in stores if not s["_customer"]]
    qualified = [s for s in prospects if s["_bucket"] == "qualified"]
    n = len(qualified) or 1

    def have(field):
        return sum(1 for s in qualified if s.get(field))

    def verified(field):
        return sum(1 for s in qualified if s.get(field, "").startswith("ok"))

    with_web = sum(1 for s in qualified if s["Website"] and s["Web Status"] != "social-link")
    return {
        # v2 keys (kept for /api/stats consumers)
        "total": len(stores), "leads": len(prospects), "retailers": len(customers),
        "sent": sum(1 for o in outreach if o.get("direction", "Outbound") != "Inbound"),
        "replied": sum(1 for o in outreach if o.get("Response", "").strip()),
        "converted": sum(1 for s in stores if s.get("pipeline_stage", "").strip().lower() == "won"),
        # quality layer
        "qualified": len(qualified),
        "review": sum(1 for s in prospects if s["_bucket"] == "review"),
        "rejected": sum(1 for s in prospects if s["_bucket"] == "rejected"),
        "top_tier": sum(1 for s in qualified if s["Priority Tier"] == "A-Tier"),
        "pitched": sum(1 for s in qualified if s["Outreach Status"] == "Pitched"),
        "in_talks": sum(1 for s in qualified if s["Outreach Status"] == "Replied"),
        "with_ig": have("Instagram"), "with_web": with_web, "with_phone": have("Phone"),
        "with_email": have("Email"),
        "pct_ig": round(have("Instagram") * 100 / n), "pct_web": round(with_web * 100 / n),
        "pct_phone": round(have("Phone") * 100 / n), "pct_email": round(have("Email") * 100 / n),
        "verified_ig": verified("IG Status"), "verified_web": verified("Web Status"),
        "verified_phone": verified("Phone Status"),
        "no_contact": sum(1 for s in qualified if not (s["Instagram"] or s["Phone"] or s["Email"])),
        "hidden_phones": sum(1 for s in stores if any("fake phone" in c for c in s["_cleaning"])),
    }


def find_store(stores: list[dict], row, name: str):
    """Locate a store by sheet row (checked against its name), falling back to a unique name."""
    try:
        row = int(row)
    except (TypeError, ValueError):
        row = None
    if row:
        for s in stores:
            if s["_row"] == row and name in (s["Store Name"], s["_name"]):
                return s
    matches = [s for s in stores if name in (s["Store Name"], s["_name"])]
    return matches[0] if len(matches) == 1 else None


# ─────────────────────────────────────────  WRITE HELPERS
def _next_id(records, id_field, prefix, width=4):
    mx = 0
    for r in records:
        m = re.search(r"(\d+)$", str(r.get(id_field, "")))
        if m:
            mx = max(mx, int(m.group(1)))
    return f"{prefix}-{mx + 1:0{width}d}"


def log_outreach(targets: list[dict], channel, message, status="Sent", template_used="",
                 sent_by="Goldie"):
    """Append one OUTREACH_LOG event per store; move pipeline_stage to Contacted when sent."""
    data = load_data(force=True)
    ss = sheets.open_spreadsheet()
    existing = list(data["outreach"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries = []
    for store in targets:
        entry = {
            "outreach_id": _next_id(existing + entries, "outreach_id", "OUT", 5),
            "store_id": store.get("store_id", ""), "store_name": store["_name"], "channel": channel,
            "direction": "Outbound", "template_used": template_used, "message": message,
            "status": status, "sent_at": now, "sent_by": sent_by,
        }
        entries.append(entry)
    sheets.append_by_header(ss, OUTREACH_TAB, OUTREACH_HEADERS, entries)
    if status == "Sent":
        for store in targets:
            if store["Outreach Status"] in OPEN_BADGES:
                sheets.update_row_cells(ss, STORES_TAB, store["_row"], data["store_headers"],
                                        {"pipeline_stage": "Contacted"})
    invalidate()


# ─────────────────────────────────────────  SYNC JOB  (repo CSV -> STORES)
REPO_LEADS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "godspeed_leads_final.csv")
STORES_DEFAULT_HEADERS = [
    "store_name", "city", "market", "country", "website", "instagram", "email", "phone",
    "pipeline_stage", "account_status", "last_order_date", "notes", "lead_score",
    "priority_tier", "score_breakdown",
]
# Columns the leads file owns: refreshed from it on every sync.
REPO_OWNED = {
    "State": "market", "Country": "country", "Website": "website", "Instagram": "instagram",
    "Email": "email", "Phone": "phone", "Notes": "notes", "Lead Score": "lead_score",
    "Priority Tier": "priority_tier", "Score Breakdown": "score_breakdown",
}
# Columns the dashboard owns once a store exists (pipeline_stage, account_status,
# last_order_date, ...). The file only seeds them for a store that is new.
SEED_ONLY = {"Store Name": "store_name", "City": "city", "Outreach Status": "pipeline_stage",
             "Last Order Date": "last_order_date"}


def sync_stores_from_repo(dry_run: bool = False, progress=None) -> dict:
    """
    Bring STORES in line with data/godspeed_leads_final.csv from this deploy.

    Never deletes a row and never touches the columns the dashboard owns, so
    pipeline stages, account statuses and stores added in the dashboard survive.
    """
    with open(REPO_LEADS_CSV, newline="", encoding="utf-8") as f:
        leads = list(csv.DictReader(f))
    ss = sheets.open_spreadsheet()
    rows = sheets.read_tabs(ss, [STORES_TAB])[STORES_TAB]
    headers = [q.s(h) for h in rows[0]] if rows else list(STORES_DEFAULT_HEADERS)
    col = {h: i for i, h in enumerate(headers) if h}
    if "store_name" not in col or "city" not in col:
        raise RuntimeError(f"{STORES_TAB} has no store_name / city columns — not syncing.")
    body = [[q.s(c) for c in r] + [""] * (len(headers) - len(r)) for r in rows[1:]]
    # Rows are matched in order within a key, so two rows that share a name and
    # city pair up one-to-one instead of fighting over the same sheet row.
    waiting: dict = {}
    for r in body:
        waiting.setdefault(store_key(r[col["store_name"]], r[col["city"]]), []).append(r)
    in_sheet = sum(len(v) for v in waiting.values())

    updated = added = cells = matched = 0
    for lead in leads:
        if not q.s(lead.get("Store Name")):
            continue
        queue = waiting.get(store_key(lead["Store Name"], lead.get("City", "")))
        if not queue:
            row = [""] * len(headers)
            for src, dst in {**SEED_ONLY, **REPO_OWNED}.items():
                if dst in col:
                    row[col[dst]] = q.s(lead.get(src))
            body.append(row)
            added += 1
            continue
        row = queue.pop(0)
        matched += 1
        changed = 0
        # name and city only differ by encoding or punctuation here; take the file's spelling
        for src, dst in {**REPO_OWNED, "Store Name": "store_name", "City": "city"}.items():
            if dst in col and row[col[dst]] != q.s(lead.get(src)):
                row[col[dst]] = q.s(lead.get(src))
                changed += 1
        if changed:
            updated += 1
            cells += changed

    result = {"leads_in_file": matched + added, "stores_in_sheet_before": in_sheet,
              "added": added, "updated": updated, "cells_changed": cells,
              "only_in_sheet_kept": in_sheet - matched, "dry_run": dry_run}
    if not dry_run and (added or updated):
        if progress:
            progress(f"Writing {len(body)} stores to {STORES_TAB}…")
        sheets.replace_tab(ss, STORES_TAB, [headers] + body)
        invalidate()
    return result


# ─────────────────────────────────────────  VERIFY JOB
job = {"name": None, "running": False, "done": 0, "total": 0, "message": "Not run yet.",
       "error": None, "started_at": None, "finished_at": None, "stop": False, "result": None}
_job_lock = threading.Lock()


def verify_stores(progress=None, should_stop=None, limit=None) -> dict:
    """Live-check websites / Instagram / phones for qualified + review stores -> VERIFICATION tab."""
    import verify

    data = load_data(force=True)
    if data["error"]:
        raise RuntimeError(data["error"])
    targets = [s for s in data["stores"] if s["_bucket"] != "rejected" or s["_customer"]]
    targets.sort(key=lambda s: (s["_bucket"] != "qualified", -s["_score"]))
    if limit:
        targets = targets[:int(limit)]
    # Check what the sheet says, not values an earlier run filled in.
    asked = [dict(s, **{f: "" for f in s["_filled"]}) for s in targets]

    def tick(done, total):
        if progress:
            progress(f"Checked {done} of {total} stores…", done, total)

    results = verify.verify_all(asked, progress=tick, should_stop=should_stop)

    # If nearly every site "failed", the problem is this server's network, not
    # the stores. Saving that would mark good websites as dead.
    tried = [r for r in results.values() if r.get("web_status") in ("ok", "unreachable")]
    dead = sum(1 for r in tried if r["web_status"] == "unreachable")
    if len(tried) >= 5 and dead / len(tried) > 0.6:
        raise RuntimeError(
            f"{dead} of {len(tried)} websites failed to load, which points to a network problem "
            "on the server rather than dead sites. Nothing was saved — try again later.")

    if progress:
        progress("Saving results…", len(targets), len(targets))
    ss = sheets.open_spreadsheet()
    kept = {}
    for old in _records(sheets.read_tabs(ss, [VERIFY_TAB])[VERIFY_TAB])[1]:
        kept[store_key(old.get("store_name", ""), old.get("city", ""))] = old
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for i, found in results.items():
        store = asked[i]
        kept[store_key(store["_name"], store.get("city", ""))] = dict(
            found, store_name=store["_name"], city=store.get("city", ""), website=store["Website"],
            instagram=store["Instagram"], phone=store["Phone"], checked_at=now)
    sheets.replace_tab(ss, VERIFY_TAB, [sheets.VERIFY_HEADERS] + [
        [row.get(h, "") for h in sheets.VERIFY_HEADERS] for row in kept.values()])
    invalidate()

    found = list(results.values())
    return {
        "checked": len(found),
        "websites_ok": sum(1 for r in found if r["web_status"] == "ok"),
        "websites_unreachable": dead,
        "instagram_confirmed": sum(1 for r in found if r["ig_status"].startswith("ok")),
        "instagram_problems": sum(1 for r in found if r["ig_status"] in ("mismatch", "not-found")),
        "instagram_unverified": sum(1 for r in found if r["ig_status"] == "unverified"),
        "phones_confirmed": sum(1 for r in found if r["phone_status"].startswith("ok")),
        "blanks_found": sum(1 for r in found for f in ("found_instagram", "found_phone", "found_email") if r[f]),
    }


def _run_job(name, limit=None, dry_run=False):
    def progress(message, done=None, total=None):
        job["message"] = message
        if done is not None:
            job["done"], job["total"] = done, total

    try:
        if name == "sync":
            r = job["result"] = sync_stores_from_repo(dry_run, progress)
            job["message"] = (f"{'Would add' if dry_run else 'Added'} {r['added']} stores, "
                              f"{'would update' if dry_run else 'updated'} {r['updated']}; "
                              f"{r['only_in_sheet_kept']} sheet-only stores kept.")
        else:
            job["result"] = verify_stores(progress, lambda: job["stop"], limit)
            job["message"] = (f"Done — checked {job['result']['checked']} stores, "
                              f"found {job['result']['blanks_found']} missing contact details.")
    except Exception as exc:
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["message"] = "Failed."
    finally:
        job["running"] = False
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def start_job(name="verify", limit=None, dry_run=False) -> bool:
    with _job_lock:
        if job["running"]:
            return False
        job.update(name=name, running=True, done=0, total=0, error=None, result=None, stop=False,
                   message="Starting…", started_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                   finished_at=None)
    threading.Thread(target=_run_job, args=(name, limit, dry_run), daemon=True).start()
    return True


# ─────────────────────────────────────────  ROUTES
@app.route("/")
def index():
    data = load_data()
    stores, outreach = data["stores"], data["outreach"]
    stats = compute_stats(stores, outreach)
    recent = sorted(outreach, key=lambda x: x.get("Sent At", ""), reverse=True)[:10]

    # Reorder alerts: customers with no order in 60+ days
    today = datetime.today()
    alerts = []
    for s in stores:
        if not s["_customer"]:
            continue
        lod = s.get("Last Order Date", "")
        if lod:
            try:
                if (today - datetime.strptime(lod[:10], "%Y-%m-%d")).days > 60:
                    alerts.append(s)
            except ValueError:
                pass
        elif s.get("account_status", "").strip().lower() == "dormant":
            alerts.append(s)

    top = sorted((s for s in stores if s["_bucket"] == "qualified" and not s["_customer"]
                  and s["Outreach Status"] in OPEN_BADGES), key=lambda s: -s["_score"])[:8]
    return render_template("index.html", stats=stats, recent=recent, alerts=alerts, top=top,
                           error=data["error"])


def _filter_leads(stores, args):
    """Acquisition view = prospects (not yet customers), narrowed by the query string."""
    view = args.get("view", "qualified")
    search = args.get("q", "").strip().lower()
    state = args.get("state", "").strip()              # really "market"
    status = args.get("status", "").strip().lower()
    tier = args.get("tier", "").strip()
    contact = args.get("contact", "").strip()

    out = [s for s in stores if not s["_customer"]]
    if view != "all":
        out = [s for s in out if s["_bucket"] == view]
    if search:
        out = [s for s in out if search in " ".join(
            (s["Store Name"], s["_name"], s["City"], s["Instagram"], s["Website"], s["Notes"])).lower()]
    if state:
        out = [s for s in out if s["State"] == state]
    if status:
        out = [s for s in out if s["Outreach Status"].lower() == status]
    if tier:
        out = [s for s in out if s["Priority Tier"] == tier]
    if contact in ("instagram", "phone", "email"):
        out = [s for s in out if s[contact.capitalize()]]
    elif contact == "none":
        out = [s for s in out if not (s["Instagram"] or s["Phone"] or s["Email"])]
    elif contact == "problem":
        out = [s for s in out if has_contact_problem(s)]
    return sorted(out, key=lambda s: (-s["_score"], s["Store Name"].lower()))


def has_contact_problem(s) -> bool:
    return bool(s["Suggested Fixes"]) or s["IG Status"] in ("mismatch", "not-found") \
        or s["Web Status"] == "unreachable"


@app.route("/leads")
def leads():
    data = load_data()
    stores = data["stores"]
    filtered = _filter_leads(stores, request.args)

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    pages = max(1, -(-len(filtered) // PAGE_SIZE))
    page = min(page, pages)

    def page_url(n):
        args = request.args.to_dict()
        args["page"] = n
        return url_for("leads", **args)

    def view_url(name):
        args = {k: v for k, v in request.args.to_dict().items() if k not in ("page", "added")}
        args["view"] = name
        return url_for("leads", **args)

    prospects = [s for s in stores if not s["_customer"]]
    counts = {b: sum(1 for s in prospects if s["_bucket"] == b) for b in ("qualified", "review", "rejected")}
    counts["all"] = len(prospects)
    return render_template(
        "leads.html", leads=filtered[(page - 1) * PAGE_SIZE: page * PAGE_SIZE], total=len(filtered),
        counts=counts, view=request.args.get("view", "qualified"), page=page, pages=pages,
        page_url=page_url, view_url=view_url,
        states=sorted({s["State"] for s in prospects if s["State"]}),
        args=request.args, error=data["error"])


@app.route("/export/leads.csv")
def export_leads():
    data = load_data()
    if data["error"]:
        return Response(data["error"], 503)
    fields = ["Store Name", "City", "State", "Country", "Website", "Instagram", "Email", "Phone",
              "Outreach Status", "lead_score", "Priority Tier", "Cleanup Flag", "Flag Reasons",
              "IG Status", "Web Status", "Phone Status", "Suggested Fixes", "Notes"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(_filter_leads(data["stores"], request.args))
    name = f"godspeed-{request.args.get('view', 'qualified')}-leads.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


EXPORTABLE_TABS = {"stores": STORES_TAB, "outreach": OUTREACH_TAB, "orders": ORDERS_TAB,
                   "review": REVIEW_TAB, "verification": VERIFY_TAB}


@app.route("/api/export/<name>.csv")
def export_tab(name):
    """A tab exactly as it is in the sheet (stores, outreach, orders, review, verification)."""
    tab = EXPORTABLE_TABS.get(name)
    if not tab:
        return Response("unknown tab", 404)
    try:
        rows = sheets.read_tabs(sheets.open_spreadsheet(), [tab])[tab]
    except Exception as exc:
        return Response(f"{type(exc).__name__}: {exc}", 503)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv")


@app.route("/retailers")
def retailers():
    data = load_data()
    today = datetime.today()
    rl = []
    for s in data["stores"]:
        if not s["_customer"]:
            continue
        lod = s.get("Last Order Date", "")
        try:
            d = (today - datetime.strptime(lod[:10], "%Y-%m-%d")).days if lod else None
        except ValueError:
            d = None
        rl.append(dict(s, _days_since=d, _alert=(d is not None and d > 60)))
    return render_template("retailers.html", retailers=rl, error=data["error"])


@app.route("/outreach")
def outreach():
    data = load_data()
    log = data["outreach"]
    sf = request.args.get("store", "").strip().lower()
    cf = request.args.get("channel", "").strip().lower()
    dfilt = request.args.get("date", "").strip()
    store_names = sorted({o["Store Name"] for o in log})
    if sf:
        log = [o for o in log if sf in o["Store Name"].lower()]
    if cf:
        log = [o for o in log if cf in o["Channel"].lower()]
    if dfilt:
        log = [o for o in log if dfilt in o["Sent At"]]
    log = sorted(log, key=lambda x: x["Sent At"], reverse=True)
    channels = ["Email", "Instagram DM", "WhatsApp", "Phone"]
    return render_template("outreach.html", log=log, store_names=store_names, channels=channels,
                           store_filter=sf, channel_filter=cf, date_filter=dfilt, error=data["error"])


@app.route("/orders")
def orders():
    data = load_data()
    rows = data["orders"]
    summary = {
        "orders": len(rows),
        "revenue": sum(_num(r.get("order_total")) for r in rows),
        "comm_pending": sum(_num(r.get("commission_amount")) for r in rows
                            if r.get("commission_status", "").lower() == "pending"),
        "comm_invoiced": sum(_num(r.get("commission_amount")) for r in rows
                             if r.get("commission_status", "").lower() == "invoiced"),
        "comm_paid": sum(_num(r.get("commission_amount")) for r in rows
                         if r.get("commission_status", "").lower() == "paid"),
    }
    rows = sorted(rows, key=lambda x: x.get("order_date", ""), reverse=True)
    return render_template("orders.html", orders=rows, summary=summary, error=data["error"])


FLAG_LABELS = {
    "chain": "Chain stores", "mono-brand": "Brand-owned / single-brand stores",
    "not-a-store": "Articles, directories and posts (not stores)",
    "junk": "Not clothing retailers", "mismatch": "Name doesn't match its website",
    "low-fit": "No streetwear signal", "broken-data": "Broken rows",
    "duplicate": "Same store listed more than once", "excluded": "Held out by you",
}


@app.route("/quality")
def quality_page():
    data = load_data()
    stores = data["stores"]
    stats = compute_stats(stores, data["outreach"])
    prospects = [s for s in stores if not s["_customer"]]

    reasons = {}
    for s in prospects:
        if s["_bucket"] == "qualified":
            continue
        for part in s["Cleanup Flag"].split("+"):
            reasons[part] = reasons.get(part, 0) + 1
    breakdown = sorted(((FLAG_LABELS.get(k, k), v) for k, v in reasons.items() if k and k != "OK"),
                       key=lambda item: -item[1])
    problems = [s for s in prospects if s["_bucket"] == "qualified" and has_contact_problem(s)]
    review = sorted((s for s in prospects if s["_bucket"] == "review"),
                    key=lambda s: (-s["_score"], s["Store Name"].lower()))
    verified_any = any(s.get("_checked_at") for s in stores)
    return render_template("quality.html", stats=stats, breakdown=breakdown, problems=problems[:100],
                           problem_count=len(problems), review=review[:60], review_count=len(review),
                           job=job, verified_any=verified_any, error=data["error"])


@app.route("/add-store", methods=["GET", "POST"])
def add_store():
    if request.method == "GET":
        return render_template("add_store.html", error=None)
    try:
        f = request.form
        name = f.get("name", "").strip()
        if not name:
            return render_template("add_store.html", error="Store name is required.")
        data = load_data(force=True)
        email = q.normalize_email(f.get("email", "")) or f.get("email", "").strip()
        handle = q.normalize_instagram(f.get("instagram", ""))
        ig = "@" + handle if handle else f.get("instagram", "").strip()
        digits = q.normalize_phone(f.get("phone", ""))
        phone = q.format_phone(digits) if digits else f.get("phone", "").strip()
        store = {
            "store_id": _next_id(data["stores"], "store_id", "GS", 4),
            "store_name": name,
            "country": f.get("country", "USA").strip() or "USA",
            "city": f.get("city", "").strip(),
            "market": q.normalize_state(f.get("market", "") or f.get("state", "")),
            "contact_name": f.get("contact_name", "").strip(),
            "instagram": ig, "ig_followers": "",
            "website": q.normalize_website(f.get("website", "")) or f.get("website", "").strip(),
            "email": email, "email_status": "unverified",
            "phone": phone, "whatsapp": "",
            "brands_carried": f.get("brands", "").strip(),
            "source": "Manual",
            "pipeline_stage": "Qualified" if (email or ig or phone) else "New",
            "account_status": "", "owner": "Goldie",
            "notes": " · ".join(p for p in (f.get("notes", "").strip(),
                                           f"Brands: {f.get('brands', '').strip()}" if f.get("brands", "").strip() else "") if p),
            "date_added": datetime.today().strftime("%Y-%m-%d"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        ss = sheets.open_spreadsheet()
        sheets.append_by_header(ss, STORES_TAB, list(store), [store])
        invalidate()
        return redirect(url_for("leads", added=1, view="all", q=name))
    except Exception as exc:
        return render_template("add_store.html", error=str(exc))


@app.route("/scraper")
def scraper():
    state = {"running": False, "status": "queued",
             "message": "Sourcing runs in Claude Code: ask it to find new stores (/add-leads). "
                        "Only rows that pass the validation gate are stored."}
    return render_template("scraper.html", state=state, error=None)


# ─────────────────────────────────────────  API
def _targets(data, items):
    """Resolve [{row, name}] or [name] to store records."""
    out = []
    for item in items:
        store = find_store(data["stores"], item.get("row"), item.get("name", "")) \
            if isinstance(item, dict) else find_store(data["stores"], None, item)
        if store and store not in out:
            out.append(store)
    return out


@app.route("/api/send-pitch", methods=["POST"])
def send_pitch():
    body = request.get_json(silent=True) or {}
    status = body.get("status", "Sent")                # supports Drafted / Queued / Sent
    try:
        data = load_data(force=True)
        if data["error"]:
            return jsonify(success=False, error=data["error"]), 503
        store = find_store(data["stores"], body.get("row"), body.get("store_name", ""))
        if not store:
            return jsonify(success=False, error="Store not found — refresh the page and try again."), 404
        log_outreach([store], body.get("channel", "Instagram DM"), body.get("message", ""),
                     status=status, template_used=body.get("template_used", ""))
        return jsonify(success=True, message=f"{status} logged for {store['Store Name']}")
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/bulk-pitch", methods=["POST"])
def bulk_pitch():
    body = request.get_json(silent=True) or {}
    status = body.get("status", "Sent")
    try:
        data = load_data(force=True)
        if data["error"]:
            return jsonify(success=False, error=data["error"]), 503
        targets = _targets(data, body.get("stores", []))
        if not targets:
            return jsonify(success=False, error="No matching stores."), 404
        log_outreach(targets, body.get("channel", "Instagram DM"), body.get("message", ""), status=status)
        return jsonify(success=True, count=len(targets),
                       message=f"{status} logged for {len(targets)} stores")
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/send-reorder", methods=["POST"])
def send_reorder():
    body = request.get_json(silent=True) or {}
    try:
        data = load_data(force=True)
        if data["error"]:
            return jsonify(success=False, error=data["error"]), 503
        store = find_store(data["stores"], body.get("row"), body.get("store_name", ""))
        if not store:
            return jsonify(success=False, error="Store not found."), 404
        log_outreach([store], body.get("channel", "Email"), body.get("message", ""),
                     status="Sent", template_used="reorder")
        return jsonify(success=True, message=f"Reorder logged for {store['Store Name']}")
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/review", methods=["POST"])
def review():
    """Approve / reject a store by hand. Stored in the REVIEW tab; overrides the automatic flag."""
    body = request.get_json(silent=True) or {}
    decision = {"approve": "Approved", "reject": "Rejected", "clear": ""}.get(body.get("decision"))
    if decision is None:
        return jsonify(success=False, error="decision must be approve, reject or clear"), 400
    try:
        data = load_data(force=True)
        if data["error"]:
            return jsonify(success=False, error=data["error"]), 503
        store = find_store(data["stores"], body.get("row"), body.get("store_name", ""))
        if not store:
            return jsonify(success=False, error="Store not found."), 404
        sheets.append_by_header(sheets.open_spreadsheet(), REVIEW_TAB, sheets.REVIEW_HEADERS, [{
            "store_name": store["_name"], "city": store.get("city", ""), "decision": decision,
            "decided_at": datetime.now().strftime("%Y-%m-%d %H:%M")}])
        invalidate()
        return jsonify(success=True, bucket=q.bucket(store["Cleanup Flag"], decision))
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/job/start", methods=["POST"])
def job_start():
    body = request.get_json(silent=True) or {}
    name = body.get("job", "verify")
    if name not in ("verify", "sync"):
        return jsonify(success=False, error="job must be verify or sync"), 400
    if not start_job(name, limit=body.get("limit"), dry_run=bool(body.get("dry_run"))):
        return jsonify(success=False, error=f"A {job['name']} job is already running."), 409
    return jsonify(success=True)


@app.route("/api/job/stop", methods=["POST"])
def job_stop():
    job["stop"] = True
    return jsonify(success=True)


@app.route("/api/job/status")
def job_status():
    return jsonify({k: v for k, v in job.items() if k != "stop"})


@app.route("/api/scraper/start", methods=["POST"])
def scraper_start():
    return jsonify({"success": True, "queued": True,
                    "message": "Sourcing runs in Claude Code — ask it to find new stores (/add-leads)."})


@app.route("/api/stats")
def api_stats():
    data = load_data()
    stats = compute_stats(data["stores"], data["outreach"])
    if data["error"]:
        stats["error"] = data["error"]
    return jsonify(stats)


if __name__ == "__main__":
    print("🚀 Godspeed Dashboard v2 — STORES / OUTREACH_LOG / ORDERS — http://127.0.0.1:8080")
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", 8080)))
