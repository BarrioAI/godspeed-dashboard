"""
Godspeed Retail Intelligence System — Dashboard

Data flow
---------
  source tabs (ACQUISITION LEADS, STORES, city tabs, ...)      never modified
        │   pipeline.build_master()  — merge, clean, classify
        ▼
  MASTER DATABASE tab                    the one tab this dashboard reads
        │   verify.verify_all()      — live website / Instagram / phone checks
        ▼
  Leads / Retailers / Outreach / Data Quality pages

Pitches are *logged* to OUTREACH LOG and the store's Outreach Status is updated.
The dashboard does not send DMs or emails itself.
"""

from __future__ import annotations

import csv
import hmac
import io
import os
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS

import pipeline
import quality as q
import sheets
from pipeline import MASTER_HEADERS, MASTER_TAB

app = Flask(__name__)
CORS(app)

CACHE_TTL = 60          # seconds a sheet read is reused
PAGE_SIZE = 50
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

OPEN_STATUSES = {"", "not contacted", "new lead"}
RETAILER_STATUSES = {"converted", "active", "active customer"}


# ─────────────────────────────────────────
#  OPTIONAL PASSWORD  (set DASHBOARD_PASSWORD to enable)
# ─────────────────────────────────────────

@app.before_request
def require_password():
    if not DASHBOARD_PASSWORD or request.path.startswith("/static/") or request.path == "/healthz":
        return None
    auth = request.authorization
    if auth and auth.password and hmac.compare_digest(auth.password, DASHBOARD_PASSWORD):
        return None
    return Response("Password required.", 401, {"WWW-Authenticate": 'Basic realm="Godspeed"'})


@app.route("/healthz")
def healthz():
    return "ok"


# ─────────────────────────────────────────
#  DATA LAYER
# ─────────────────────────────────────────

_cache = {"at": 0.0, "headers": None, "records": None, "outreach_at": 0.0, "outreach": None}
_cache_lock = threading.Lock()


def invalidate():
    with _cache_lock:
        _cache["at"] = 0.0
        _cache["outreach_at"] = 0.0


def load_master(force: bool = False):
    """
    Returns (records, headers, error).
    records is None when the MASTER DATABASE tab has not been built yet.
    Each record is a dict of strings plus:
        _row     1-based row number on the sheet
        _bucket  qualified | review | rejected
    """
    with _cache_lock:
        if not force and _cache["records"] is not None and time.time() - _cache["at"] < CACHE_TTL:
            return _cache["records"], _cache["headers"], None
    try:
        ss = sheets.open_spreadsheet()
        if MASTER_TAB not in sheets.tab_titles(ss):
            return None, [], None
        rows = sheets.read_tab(ss, MASTER_TAB)
    except Exception as exc:                       # credentials, network, quota
        return [], [], f"{type(exc).__name__}: {exc}"
    if not rows:
        return None, [], None

    headers = [q.s(h) for h in rows[0]]
    records = []
    for n, raw in enumerate(rows[1:], start=2):
        rec = {h: q.s(raw[i]) if i < len(raw) else "" for i, h in enumerate(headers) if h}
        if not rec.get("Store Name"):
            continue
        rec["_row"] = n
        records.append(rec)

    # Rows typed straight into the sheet have no flag yet: classify them here.
    missing = [r for r in records if not r.get("Cleanup Flag")]
    if missing:
        pipeline.annotate(missing)
    for rec in records:
        rec["_bucket"] = q.bucket(rec.get("Cleanup Flag", ""), rec.get("Review", ""))
        try:
            rec["_score"] = int(float(rec.get("Lead Score") or 0))
        except ValueError:
            rec["_score"] = 0

    with _cache_lock:
        _cache.update(at=time.time(), headers=headers, records=records)
    return records, headers, None


def load_outreach():
    with _cache_lock:
        if _cache["outreach"] is not None and time.time() - _cache["outreach_at"] < CACHE_TTL:
            return _cache["outreach"], None
    try:
        ss = sheets.open_spreadsheet()
        if sheets.OUTREACH_TAB not in sheets.tab_titles(ss):
            return [], None
        rows = sheets.read_tab(ss, sheets.OUTREACH_TAB)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    log = []
    if rows:
        headers = [q.s(h) for h in rows[0]]
        for raw in rows[1:]:
            entry = {h: q.s(raw[i]) if i < len(raw) else "" for i, h in enumerate(headers) if h}
            if entry.get("Store Name"):
                log.append(entry)
    with _cache_lock:
        _cache.update(outreach_at=time.time(), outreach=log)
    return log, None


def is_retailer(rec: dict) -> bool:
    return rec.get("Carries Godspeed", "").lower() == "yes" \
        or rec.get("Outreach Status", "").lower() in RETAILER_STATUSES


def compute_stats(records: list[dict], outreach: list[dict]) -> dict:
    qualified = [r for r in records if r["_bucket"] == "qualified"]
    n = len(qualified) or 1

    def pct(count):
        return round(count * 100 / n)

    def verified(field):
        return sum(1 for r in qualified if r.get(field, "").startswith("ok"))

    with_ig = sum(1 for r in qualified if r.get("Instagram"))
    with_web = sum(1 for r in qualified if r.get("Website") and r.get("Web Status") != "social-link")
    with_phone = sum(1 for r in qualified if r.get("Phone"))
    with_email = sum(1 for r in qualified if r.get("Email"))
    return {
        "total": len(records),
        "qualified": len(qualified),
        "review": sum(1 for r in records if r["_bucket"] == "review"),
        "rejected": sum(1 for r in records if r["_bucket"] == "rejected"),
        "retailers": sum(1 for r in records if is_retailer(r)),
        "pitched": sum(1 for r in records if r.get("Outreach Status", "").lower() == "pitched"),
        "replied": sum(1 for r in records if r.get("Outreach Status", "").lower() == "replied"),
        "converted": sum(1 for r in records if r.get("Outreach Status", "").lower() == "converted"),
        "sent": len(outreach),
        "replies_logged": sum(1 for o in outreach if o.get("Response")),
        "hot": sum(1 for r in qualified if r.get("Priority Tier") == "Hot"),
        "with_ig": with_ig, "with_web": with_web, "with_phone": with_phone, "with_email": with_email,
        "pct_ig": pct(with_ig), "pct_web": pct(with_web), "pct_phone": pct(with_phone),
        "pct_email": pct(with_email),
        "verified_ig": verified("IG Status"), "verified_web": verified("Web Status"),
        "verified_phone": verified("Phone Status"),
        "no_contact": sum(1 for r in qualified
                          if not (r.get("Instagram") or r.get("Phone") or r.get("Email"))),
    }


def find_record(records: list[dict], row, name: str):
    """Locate a store by sheet row (checked against its name), falling back to the name."""
    try:
        row = int(row)
    except (TypeError, ValueError):
        row = None
    if row:
        for rec in records:
            if rec["_row"] == row and rec["Store Name"] == name:
                return rec
    matches = [r for r in records if r["Store Name"] == name]
    return matches[0] if len(matches) == 1 else None


# ─────────────────────────────────────────
#  BACKGROUND JOBS  (rebuild / verify)
# ─────────────────────────────────────────

job = {"name": None, "running": False, "done": 0, "total": 0, "message": "No job has run yet.",
       "error": None, "started_at": None, "finished_at": None, "stop": False, "result": None}
_job_lock = threading.Lock()


def rebuild_master(progress=None) -> dict:
    """Merge + clean every store tab into MASTER DATABASE. Source tabs are not modified."""
    ss = sheets.open_spreadsheet()
    if progress:
        progress("Reading every tab…")
    tabs = sheets.read_all_tabs(ss)
    if progress:
        progress(f"Cleaning {sum(max(len(v) - 1, 0) for v in tabs.values())} rows from {len(tabs)} tabs…")
    records, stats = pipeline.build_master(tabs)
    if progress:
        progress(f"Writing {len(records)} stores to {MASTER_TAB}…")
    sheets.write_master(ss, pipeline.to_rows(records))
    invalidate()
    stats.pop("per_tab", None)
    return stats


def verify_master(progress=None, should_stop=None, limit=None) -> dict:
    """Live-check websites / Instagram / phones for qualified + review stores."""
    import verify

    records, headers, error = load_master(force=True)
    if error:
        raise RuntimeError(error)
    if records is None:
        raise RuntimeError("Build the clean database first.")
    targets = [r for r in records if r["_bucket"] != "rejected"]
    targets.sort(key=lambda r: (r["_bucket"] != "qualified", -r["_score"]))
    if limit:
        targets = targets[:int(limit)]

    def tick(done, total):
        if progress:
            progress(f"Checked {done} of {total} stores…", done, total)

    results = verify.verify_all(targets, progress=tick, should_stop=should_stop)

    # If nearly every site "failed", the problem is this server's network, not
    # the stores. Saving that would mark good websites as dead.
    tried = [c for c in results.values() if c.get("Web Status") in ("ok", "unreachable")]
    dead = sum(1 for c in tried if c["Web Status"] == "unreachable")
    if len(tried) >= 5 and dead / len(tried) > 0.6:
        raise RuntimeError(
            f"{dead} of {len(tried)} websites failed to load, which points to a network problem "
            "on the server rather than dead sites. Nothing was saved — try again later.")

    changed = filled = 0
    for i, changes in results.items():
        if not changes:
            continue
        changed += 1
        filled += sum(1 for k in ("Instagram", "Phone", "Email") if k in changes)
        targets[i].update(changes)
        targets[i]["Cleanup Flag"] = ""            # re-classify with the new evidence
    pipeline.annotate([r for r in records if not r.get("Cleanup Flag")])

    if progress:
        progress("Saving results to the sheet…", len(targets), len(targets))
    ss = sheets.open_spreadsheet()
    out_headers = headers + [h for h in MASTER_HEADERS if h not in headers]
    rows = [out_headers] + [[rec.get(h, "") for h in out_headers] for rec in records]
    sheets.write_master(ss, rows)
    invalidate()
    checked = [targets[i] for i in results]
    return {
        "checked": len(results),
        "rows_updated": changed,
        "contact_fields_filled": filled,
        "websites_ok": sum(1 for r in checked if r.get("Web Status") == "ok"),
        "websites_unreachable": sum(1 for r in checked if r.get("Web Status") == "unreachable"),
        "instagram_confirmed": sum(1 for r in checked if r.get("IG Status", "").startswith("ok")),
        "instagram_mismatch": sum(1 for r in checked if r.get("IG Status") in ("mismatch", "not-found")),
        "instagram_unverified": sum(1 for r in checked if r.get("IG Status") == "unverified"),
        "phones_confirmed": sum(1 for r in checked if r.get("Phone Status", "").startswith("ok")),
    }


def _run_job(name: str, limit=None):
    def progress(message, done=None, total=None):
        job["message"] = message
        if done is not None:
            job["done"], job["total"] = done, total

    try:
        if name == "rebuild":
            job["result"] = rebuild_master(progress)
            job["message"] = (f"Done — {job['result']['qualified']} qualified leads, "
                              f"{job['result']['needs_review']} to review, "
                              f"{job['result']['rejected']} rejected.")
        else:
            job["result"] = verify_master(progress, lambda: job["stop"], limit)
            job["message"] = (f"Done — checked {job['result']['checked']} stores, "
                              f"filled {job['result']['contact_fields_filled']} missing contact fields.")
    except Exception as exc:
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["message"] = "Failed."
    finally:
        job["running"] = False
        job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def start_job(name: str, limit=None) -> bool:
    with _job_lock:
        if job["running"]:
            return False
        job.update(name=name, running=True, done=0, total=0, error=None, result=None, stop=False,
                   message="Starting…", started_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
                   finished_at=None)
    threading.Thread(target=_run_job, args=(name, limit), daemon=True).start()
    return True


# ─────────────────────────────────────────
#  PAGES
# ─────────────────────────────────────────

def _needs_setup(records, error):
    """Render the setup page when there is no clean database yet."""
    if records is None and not error:
        return render_template("setup.html", job=job)
    return None


@app.route("/")
def index():
    records, _, error = load_master()
    setup = _needs_setup(records, error)
    if setup:
        return setup
    outreach, _ = load_outreach()
    records = records or []
    stats = compute_stats(records, outreach)
    recent = sorted(outreach, key=lambda o: o.get("Sent At", ""), reverse=True)[:10]

    alerts = []
    today = datetime.today()
    for rec in records:
        if is_retailer(rec) and rec.get("Last Order Date"):
            try:
                if (today - datetime.strptime(rec["Last Order Date"][:10], "%Y-%m-%d")).days > 60:
                    alerts.append(rec)
            except ValueError:
                pass

    top = sorted((r for r in records if r["_bucket"] == "qualified"
                  and r.get("Outreach Status", "").lower() in OPEN_STATUSES and not is_retailer(r)),
                 key=lambda r: -r["_score"])[:8]
    return render_template("index.html", stats=stats, recent=recent, alerts=alerts, top=top, error=error)


def _filter_leads(records, args):
    view = args.get("view", "qualified")
    search = args.get("q", "").strip().lower()
    state = args.get("state", "").strip()
    status = args.get("status", "").strip().lower()
    tier = args.get("tier", "").strip()
    contact = args.get("contact", "").strip()

    out = records if view == "all" else [r for r in records if r["_bucket"] == view]
    if search:
        out = [r for r in out if search in " ".join(
            (r["Store Name"], r.get("City", ""), r.get("Instagram", ""), r.get("Website", ""),
             r.get("Notes", ""))).lower()]
    if state:
        out = [r for r in out if r.get("State") == state]
    if status:
        out = [r for r in out if (r.get("Outreach Status", "").lower() or "not contacted") == status]
    if tier:
        out = [r for r in out if r.get("Priority Tier") == tier]
    if contact == "instagram":
        out = [r for r in out if r.get("Instagram")]
    elif contact == "phone":
        out = [r for r in out if r.get("Phone")]
    elif contact == "email":
        out = [r for r in out if r.get("Email")]
    elif contact == "none":
        out = [r for r in out if not (r.get("Instagram") or r.get("Phone") or r.get("Email"))]
    elif contact == "problem":
        out = [r for r in out if r.get("Suggested Fixes")
               or r.get("IG Status") in ("mismatch", "not-found")
               or r.get("Web Status") == "unreachable"]
    return sorted(out, key=lambda r: (-r["_score"], r["Store Name"].lower()))


@app.route("/leads")
def leads():
    records, _, error = load_master()
    setup = _needs_setup(records, error)
    if setup:
        return setup
    records = records or []
    filtered = _filter_leads(records, request.args)

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    pages = max(1, -(-len(filtered) // PAGE_SIZE))
    page = min(page, pages)
    shown = filtered[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    def page_url(n):
        args = request.args.to_dict()
        args["page"] = n
        return url_for("leads", **args)

    def view_url(name):
        args = {k: v for k, v in request.args.to_dict().items() if k not in ("page", "added")}
        args["view"] = name
        return url_for("leads", **args)

    counts = {b: sum(1 for r in records if r["_bucket"] == b) for b in ("qualified", "review", "rejected")}
    counts["all"] = len(records)
    return render_template(
        "leads.html", leads=shown, total=len(filtered), counts=counts,
        view=request.args.get("view", "qualified"), page=page, pages=pages,
        page_url=page_url, view_url=view_url,
        states=sorted({r.get("State") for r in records if r.get("State")}),
        args=request.args, error=error)


@app.route("/export/leads.csv")
def export_leads():
    records, _, error = load_master()
    if error or records is None:
        return Response(error or "No database yet.", 503)
    filtered = _filter_leads(records, request.args)
    fields = ["Store Name", "City", "State", "Country", "Website", "Instagram", "Email", "Phone",
              "Outreach Status", "Lead Score", "Priority Tier", "Cleanup Flag", "Flag Reasons",
              "IG Status", "Web Status", "Phone Status", "Suggested Fixes", "Notes"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(filtered)
    name = f"godspeed-{request.args.get('view', 'qualified')}-leads.csv"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@app.route("/retailers")
def retailers():
    records, _, error = load_master()
    setup = _needs_setup(records, error)
    if setup:
        return setup
    today = datetime.today()
    out = []
    for rec in (records or []):
        if not is_retailer(rec):
            continue
        rec = dict(rec, _days_since=None, _alert=False)
        if rec.get("Last Order Date"):
            try:
                rec["_days_since"] = (today - datetime.strptime(rec["Last Order Date"][:10], "%Y-%m-%d")).days
                rec["_alert"] = rec["_days_since"] > 60
            except ValueError:
                pass
        out.append(rec)
    return render_template("retailers.html", retailers=out, error=error)


@app.route("/outreach")
def outreach():
    log, error = load_outreach()
    store_filter = request.args.get("store", "").strip().lower()
    channel_filter = request.args.get("channel", "").strip().lower()
    date_filter = request.args.get("date", "").strip()

    filtered = log
    if store_filter:
        filtered = [o for o in filtered if store_filter in o.get("Store Name", "").lower()]
    if channel_filter:
        filtered = [o for o in filtered if channel_filter in o.get("Channel", "").lower()]
    if date_filter:
        filtered = [o for o in filtered if date_filter in o.get("Sent At", "")]
    filtered = sorted(filtered, key=lambda o: o.get("Sent At", ""), reverse=True)

    return render_template(
        "outreach.html", log=filtered,
        store_names=sorted({o.get("Store Name", "") for o in log if o.get("Store Name")}),
        channels=["Email", "Instagram DM", "SMS", "Phone"],
        store_filter=store_filter, channel_filter=channel_filter, date_filter=date_filter, error=error)


FLAG_LABELS = {
    "chain": "Chain stores", "mono-brand": "Brand-owned / single-brand stores",
    "not-a-store": "Articles, directories and posts (not stores)",
    "junk": "Not clothing retailers", "mismatch": "Name doesn't match its website",
    "low-fit": "No streetwear signal", "broken-data": "Broken rows",
}


@app.route("/quality")
def quality_page():
    records, _, error = load_master()
    setup = _needs_setup(records, error)
    if setup:
        return setup
    records = records or []
    outreach, _ = load_outreach()
    stats = compute_stats(records, outreach)

    reasons = {}
    for rec in records:
        if rec["_bucket"] == "qualified":
            continue
        for part in rec.get("Cleanup Flag", "").split("+"):
            reasons[part] = reasons.get(part, 0) + 1
    breakdown = sorted(((FLAG_LABELS.get(k, k), v) for k, v in reasons.items() if k and k != "OK"),
                       key=lambda item: -item[1])

    problems = [r for r in records if r["_bucket"] == "qualified" and (
        r.get("Suggested Fixes") or r.get("IG Status") in ("mismatch", "not-found")
        or r.get("Web Status") == "unreachable")]
    review = sorted((r for r in records if r["_bucket"] == "review"), key=lambda r: r["Store Name"].lower())
    verified_any = any(r.get("Web Status") in ("ok", "unreachable") for r in records)
    return render_template("quality.html", stats=stats, breakdown=breakdown, problems=problems[:100],
                           problem_count=len(problems), review=review[:60], review_count=len(review),
                           job=job, verified_any=verified_any, error=error)


@app.route("/add-store", methods=["GET", "POST"])
def add_store():
    if request.method == "GET":
        return render_template("add_store.html", error=None)
    try:
        form = {k: request.form.get(k, "").strip() for k in
                ("name", "city", "state", "instagram", "website", "phone", "brands", "notes")}
        if not form["name"]:
            return render_template("add_store.html", error="Store name is required.")
        carries = "godspeed" in form["brands"].lower()
        digits = q.normalize_phone(form["phone"])
        handle = q.normalize_instagram(form["instagram"])
        rec = {
            "Store Name": form["name"], "City": form["city"],
            "State": q.normalize_state(form["state"]), "Country": "USA",
            "Website": q.normalize_website(form["website"]) or form["website"],
            "Instagram": "@" + handle if handle else form["instagram"],
            "Phone": q.format_phone(digits) if digits else form["phone"],
            "Carries Godspeed": "Yes" if carries else "",
            "Outreach Status": "Converted" if carries else "Not Contacted",
            "Notes": " · ".join(p for p in (form["notes"], f"Brands: {form['brands']}" if form["brands"] else "") if p),
            "Date Added": datetime.today().strftime("%Y-%m-%d"),
            "Sources": "Added in dashboard",
        }
        pipeline.annotate([rec])
        ss = sheets.open_spreadsheet()
        headers = sheets.ensure_tab(ss, MASTER_TAB, MASTER_HEADERS)
        sheets.append_rows(ss, MASTER_TAB, [[rec.get(h, "") for h in headers]])
        invalidate()
        return redirect(url_for("leads", added=1, view=q.bucket(rec["Cleanup Flag"])))
    except Exception as exc:
        return render_template("add_store.html", error=str(exc))


@app.route("/scraper")
def scraper():
    return redirect(url_for("quality_page"))


# ─────────────────────────────────────────
#  API
# ─────────────────────────────────────────

DEFAULT_PITCH = ("Hey! We're Godspeed — a streetwear brand that would be a perfect fit for your "
                 "store. Mind if we send over our lookbook?")
DEFAULT_REORDER = ("Hey! Just checking in — ready to restock Godspeed? Let us know what you need "
                   "and we'll get it shipped ASAP.")


def _log_outreach(targets: list[dict], channel: str, message: str, status: str, mark_pitched: bool):
    ss = sheets.open_spreadsheet()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sheets.append_outreach(ss, [{
        "Store Name": rec["Store Name"], "City": rec.get("City", ""), "State": rec.get("State", ""),
        "Channel": channel, "Message": message, "Sent At": now, "Status": status, "Agent": "Dashboard",
    } for rec in targets])
    if mark_pitched:
        _, headers, _ = load_master()
        for rec in targets:
            if rec.get("Outreach Status", "").lower() in OPEN_STATUSES:
                sheets.update_row_cells(ss, MASTER_TAB, rec["_row"], headers,
                                        {"Outreach Status": "Pitched", "Outreach Channel": channel})
    invalidate()


def _ready():
    """(records, headers, error_response) for API calls that need the database."""
    records, headers, error = load_master(force=True)
    if error or records is None:
        return None, None, (jsonify(success=False, error=error or "Build the clean database first."), 503)
    return records, headers, None


@app.route("/api/send-pitch", methods=["POST"])
def send_pitch():
    data = request.get_json(silent=True) or {}
    try:
        records, _, problem = _ready()
        if problem:
            return problem
        rec = find_record(records, data.get("row"), data.get("store_name", ""))
        if not rec:
            return jsonify(success=False, error="Store not found — refresh the page and try again."), 404
        _log_outreach([rec], data.get("channel", "Instagram DM"), data.get("message") or DEFAULT_PITCH,
                      "Sent", mark_pitched=True)
        return jsonify(success=True, message=f"Pitch logged for {rec['Store Name']}")
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/bulk-pitch", methods=["POST"])
def bulk_pitch():
    data = request.get_json(silent=True) or {}
    try:
        records, _, problem = _ready()
        if problem:
            return problem
        targets = []
        for item in data.get("stores", []):
            if isinstance(item, dict):
                rec = find_record(records, item.get("row"), item.get("name", ""))
            else:
                rec = find_record(records, None, item)
            if rec and rec not in targets:
                targets.append(rec)
        if not targets:
            return jsonify(success=False, error="No matching stores."), 404
        _log_outreach(targets, data.get("channel", "Instagram DM"), data.get("message") or DEFAULT_PITCH,
                      "Sent", mark_pitched=True)
        return jsonify(success=True, message=f"Pitch logged for {len(targets)} stores", count=len(targets))
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/send-reorder", methods=["POST"])
def send_reorder():
    data = request.get_json(silent=True) or {}
    try:
        records, _, problem = _ready()
        if problem:
            return problem
        rec = find_record(records, data.get("row"), data.get("store_name", ""))
        if not rec:
            return jsonify(success=False, error="Store not found."), 404
        _log_outreach([rec], data.get("channel", "Email"), data.get("message") or DEFAULT_REORDER,
                      "Reorder Sent", mark_pitched=False)
        return jsonify(success=True, message=f"Reorder request logged for {rec['Store Name']}")
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/review", methods=["POST"])
def review():
    """Approve / reject a store by hand. The decision overrides the automatic flag."""
    data = request.get_json(silent=True) or {}
    decision = {"approve": "Approved", "reject": "Rejected", "clear": ""}.get(data.get("decision"))
    if decision is None:
        return jsonify(success=False, error="decision must be approve, reject or clear"), 400
    try:
        records, headers, problem = _ready()
        if problem:
            return problem
        rec = find_record(records, data.get("row"), data.get("store_name", ""))
        if not rec:
            return jsonify(success=False, error="Store not found."), 404
        ss = sheets.open_spreadsheet()
        if "Review" not in headers:
            headers = headers + ["Review"]
            sheets.update_row_cells(ss, MASTER_TAB, 1, headers, {"Review": "Review"})
        sheets.update_row_cells(ss, MASTER_TAB, rec["_row"], headers, {"Review": decision})
        invalidate()
        return jsonify(success=True, bucket=q.bucket(rec.get("Cleanup Flag", ""), decision))
    except Exception as exc:
        return jsonify(success=False, error=str(exc)), 500


@app.route("/api/job/start", methods=["POST"])
def job_start():
    data = request.get_json(silent=True) or {}
    name = data.get("job")
    if name not in ("rebuild", "verify"):
        return jsonify(success=False, error="job must be rebuild or verify"), 400
    if not start_job(name, limit=data.get("limit")):
        return jsonify(success=False, error=f"A {job['name']} job is already running."), 409
    return jsonify(success=True)


@app.route("/api/job/stop", methods=["POST"])
def job_stop():
    job["stop"] = True
    return jsonify(success=True)


@app.route("/api/job/status")
def job_status():
    return jsonify({k: v for k, v in job.items() if k != "stop"})


@app.route("/api/stats")
def api_stats():
    records, _, error = load_master()
    if error:
        return jsonify(error=error), 503
    if records is None:
        return jsonify(setup_required=True)
    outreach, _ = load_outreach()
    return jsonify(compute_stats(records, outreach))


if __name__ == "__main__":
    print("Godspeed Retail Intelligence Dashboard — http://127.0.0.1:8080")
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", 8080)))
