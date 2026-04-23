"""
Godspeed Retail Intelligence System - Dashboard
Built by Raj Patel | El Barrio
Fixed: 2026-04-22 — Raj overnight patch
  - OUTREACH LOG schema reset + correct columns
  - MASTER DATABASE wired as primary data source
  - /retailers fixed for active/warm/converted stores
  - /add-store writes to ACQUISITION LEADS (not MASTER DATABASE)
  - /clean route removes junk dealerships from ACQUISITION LEADS
  - Scraper replaced with honest queued message
"""

import json
import os
import sys
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS

# Google Sheets setup
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

app = Flask(__name__)
CORS(app)

SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")
# Optionally supply creds as JSON strings in env vars (for Render/cloud deployments)
GOOGLE_TOKEN_JSON = os.environ.get("GOOGLE_TOKEN_JSON", "")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

# Global scraper state — honest mode, no fake runs
scraper_state = {
    "running": False,
    "progress": [],
    "status": "queued",
    "last_run": None,
    "results": None,
    "message": "Scraper queued — Wilmar will run overnight. Check back tomorrow."
}

# ─────────────────────────────────────────
#  JUNK KEYWORDS — car dealers / auto shops
# ─────────────────────────────────────────
JUNK_KEYWORDS = [
    "dealership", "automotive", "nissan", "gmc", "buick",
    "ford", "honda", "toyota", "chevy", "chevrolet", "car", "auto"
]

# ─────────────────────────────────────────
#  OUTREACH LOG — correct schema
# ─────────────────────────────────────────
OUTREACH_LOG_HEADERS = [
    "Store Name", "City", "State", "Channel", "Message",
    "Sent At", "Response", "Response At", "Status", "Agent"
]

# ─────────────────────────────────────────
#  AUTH & SHEET HELPERS
# ─────────────────────────────────────────

def get_creds():
    """Load and refresh Google credentials. Returns None if credentials are unavailable."""
    # Prefer env var JSON strings (cloud/Render deployments)
    if GOOGLE_TOKEN_JSON and GOOGLE_CREDENTIALS_JSON:
        token_data = json.loads(GOOGLE_TOKEN_JSON)
        creds_data = json.loads(GOOGLE_CREDENTIALS_JSON)
    elif os.path.exists(TOKEN_PATH) and os.path.exists(CREDS_PATH):
        with open(TOKEN_PATH) as f:
            token_data = json.load(f)
        with open(CREDS_PATH) as f:
            creds_data = json.load(f)
    else:
        raise FileNotFoundError("Google credentials not configured. Set GOOGLE_TOKEN_JSON and GOOGLE_CREDENTIALS_JSON env vars.")

    installed = creds_data.get("installed", creds_data)

    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=installed["client_id"],
        client_secret=installed["client_secret"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file"
        ]
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data["access_token"] = creds.token
        # Only write back to file if using file-based creds (not env vars)
        if not GOOGLE_TOKEN_JSON and os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, "w") as f:
                json.dump(token_data, f, indent=2)

    return creds


def get_sheet():
    """Get gspread client and open spreadsheet."""
    creds = get_creds()
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def reset_outreach_log_schema(spreadsheet):
    """
    Clear bad data from OUTREACH LOG and set correct schema headers.
    Called once on startup and available via /api/reset-outreach-log.
    """
    try:
        ws = spreadsheet.worksheet("OUTREACH LOG")
        # Clear everything
        ws.clear()
        # Write correct headers
        ws.append_row(OUTREACH_LOG_HEADERS)
        print("✅ OUTREACH LOG schema reset to correct columns.")
        return True, "OUTREACH LOG reset successfully."
    except Exception as e:
        print(f"⚠️  Could not reset OUTREACH LOG: {e}")
        return False, str(e)


def ensure_worksheets(spreadsheet):
    """Ensure all required worksheets exist - skip if already present."""
    existing = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Existing sheets: {existing}")

    sheet_configs = [
        ("Scraper Log", ["Scraper Log", "SCRAPER LOG"]),
    ]

    for canonical, aliases in sheet_configs:
        found = any(a in existing for a in aliases)
        if not found:
            try:
                spreadsheet.add_worksheet(title=canonical, rows=1000, cols=20)
                ws = spreadsheet.worksheet(canonical)
                if canonical == "Scraper Log":
                    ws.append_row(["Run Date", "Stores Found", "New Leads", "Status", "Notes"])
            except Exception as e:
                print(f"Sheet note: {e}")

    return spreadsheet


# ─────────────────────────────────────────
#  DATA LAYER
# ─────────────────────────────────────────

def get_stores():
    """
    Fetch all stores from MASTER DATABASE (3,808 rows).
    This is the canonical source of truth.
    """
    try:
        ss = get_sheet()
        ws = ss.worksheet("MASTER DATABASE")
        records = ws.get_all_records()
        return records, None
    except Exception as e:
        return [], str(e)


def get_outreach_log():
    """Fetch outreach log from the sheet."""
    try:
        ss = get_sheet()
        ws = ss.worksheet("OUTREACH LOG")
        records = ws.get_all_records()
        return records, None
    except Exception as e:
        return [], str(e)


def write_outreach_log(store_name, city, state, channel, message, status="Sent", agent="Jordan Belfort"):
    """
    Write a single outreach entry to OUTREACH LOG with the correct schema:
    [Store Name, City, State, Channel, Message, Sent At, Response, Response At, Status, Agent]
    """
    ss = get_sheet()
    log_ws = ss.worksheet("OUTREACH LOG")

    # Validate headers — if first row is wrong, reset it
    try:
        existing_headers = log_ws.row_values(1)
        if existing_headers != OUTREACH_LOG_HEADERS:
            print("⚠️  OUTREACH LOG headers mismatch — resetting schema...")
            reset_outreach_log_schema(ss)
    except Exception:
        pass

    log_ws.append_row([
        store_name,
        city,
        state,
        channel,
        message,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",          # Response (empty at send time)
        "",          # Response At (empty at send time)
        status,
        agent
    ])


def compute_stats(stores):
    """
    Compute dashboard statistics from store list.
    Retailers = any store where Outreach Status is non-empty and not 'Not Contacted'.
    """
    total = len(stores)
    with_email = sum(1 for s in stores if s.get("Email", "").strip())

    # Count as active retailer if outreach status is anything meaningful
    def is_active_retailer(s):
        status = s.get("Outreach Status", "").strip().lower()
        return status not in ("", "not contacted") and status != ""

    retailers = sum(1 for s in stores if is_active_retailer(s))

    return {
        "total": total,
        "leads": total,
        "with_email": with_email,
        "retailers": retailers,
    }


def is_junk_store(name):
    """Return True if store name contains junk/auto keywords."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in JUNK_KEYWORDS)


# ─────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────

@app.route("/")
def index():
    stores, error = get_stores()
    outreach, _ = get_outreach_log()
    stats = compute_stats(stores)

    sent = len(outreach)
    replied = sum(1 for o in outreach if o.get("Response", "").strip())
    converted = sum(1 for s in stores if s.get("Outreach Status", "").strip().lower() == "converted")

    recent = sorted(outreach, key=lambda x: x.get("Sent At", ""), reverse=True)[:10]

    alerts = []
    today = datetime.today()
    for s in stores:
        status = s.get("Outreach Status", "").strip().lower()
        if status in ("converted", "active", "warm"):
            last_order = s.get("Last Order Date", "")
            if last_order:
                try:
                    dt = datetime.strptime(last_order, "%Y-%m-%d")
                    if (today - dt).days > 60:
                        alerts.append(s)
                except:
                    pass

    return render_template("index.html",
        stats=stats,
        sent=sent,
        replied=replied,
        converted=converted,
        recent=recent,
        alerts=alerts,
        error=error
    )


@app.route("/leads")
def leads():
    stores, error = get_stores()
    city_filter = request.args.get("city", "").strip().lower()
    state_filter = request.args.get("state", "").strip().lower()
    status_filter = request.args.get("status", "").strip().lower()

    leads_list = stores

    if city_filter:
        leads_list = [s for s in leads_list if city_filter in s.get("City", "").lower()]
    if state_filter:
        leads_list = [s for s in leads_list if state_filter in s.get("State", "").lower()]
    if status_filter:
        leads_list = [s for s in leads_list if status_filter in s.get("Outreach Status", "").lower()]

    cities = sorted(set(s.get("City", "") for s in stores if s.get("City", "")))
    states = sorted(set(s.get("State", "") for s in stores if s.get("State", "")))
    statuses = sorted(set(s.get("Outreach Status", "") for s in stores if s.get("Outreach Status", "")))

    return render_template("leads.html",
        leads=leads_list,
        cities=cities,
        states=states,
        statuses=statuses,
        city_filter=city_filter,
        state_filter=state_filter,
        status_filter=status_filter,
        error=error
    )


@app.route("/retailers")
def retailers():
    stores, error = get_stores()
    today = datetime.today()

    # Show stores that have any active outreach status (not blank, not "Not Contacted")
    def is_retailer(s):
        status = s.get("Outreach Status", "").strip().lower()
        return status not in ("", "not contacted")

    retailers_list = [s for s in stores if is_retailer(s)]

    for r in retailers_list:
        last_order = r.get("Last Order Date", "")
        if last_order:
            try:
                dt = datetime.strptime(last_order, "%Y-%m-%d")
                r["_days_since"] = (today - dt).days
                r["_alert"] = r["_days_since"] > 60
            except:
                r["_days_since"] = None
                r["_alert"] = False
        else:
            r["_days_since"] = None
            r["_alert"] = False

    return render_template("retailers.html",
        retailers=retailers_list,
        error=error
    )


@app.route("/outreach")
def outreach():
    log, error = get_outreach_log()
    stores, _ = get_stores()

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

    filtered = sorted(filtered, key=lambda x: x.get("Sent At", ""), reverse=True)

    store_names = sorted(set(s.get("Store Name", "") for s in stores if s.get("Store Name", "")))
    channels = ["Email", "Instagram DM", "SMS", "Phone"]

    return render_template("outreach.html",
        log=filtered,
        store_names=store_names,
        channels=channels,
        store_filter=store_filter,
        channel_filter=channel_filter,
        date_filter=date_filter,
        error=error
    )


@app.route("/add-store", methods=["GET", "POST"])
def add_store():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            city = request.form.get("city", "").strip()
            state = request.form.get("state", "").strip()
            instagram = request.form.get("instagram", "").strip()
            website = request.form.get("website", "").strip()
            phone = request.form.get("phone", "").strip()
            brands = request.form.get("brands", "").strip()
            notes = request.form.get("notes", "").strip()

            brands_lower = brands.lower()
            if "godspeed" in brands_lower:
                store_type = "Existing Retailer"
                outreach_status = "Converted"
            elif any(b in brands_lower for b in ["hellstar", "supreme", "sp5der", "rhude", "fear of god"]):
                store_type = "Acquisition Lead"
                outreach_status = "Not Contacted"
            else:
                store_type = "Lead"
                outreach_status = "Not Contacted"

            ss = get_sheet()
            # ✅ FIX: Write to ACQUISITION LEADS, not MASTER DATABASE
            ws = ss.worksheet("ACQUISITION LEADS")
            ws.append_row([
                name, city, state, instagram, website, phone,
                brands, outreach_status, store_type, "", notes,
                datetime.today().strftime("%Y-%m-%d")
            ])

            return redirect(url_for("leads") + "?added=1")
        except Exception as e:
            return render_template("add_store.html", error=str(e))

    return render_template("add_store.html", error=None)


@app.route("/clean", methods=["GET", "POST"])
def clean():
    """
    Remove car dealerships, auto shops, and non-streetwear junk from ACQUISITION LEADS.
    GET: show preview of what will be removed.
    POST: execute the cleanup.
    """
    try:
        ss = get_sheet()
        ws = ss.worksheet("ACQUISITION LEADS")
        records = ws.get_all_records()

        junk = [r for r in records if is_junk_store(r.get("Store Name", ""))]
        clean_records = [r for r in records if not is_junk_store(r.get("Store Name", ""))]

        if request.method == "POST":
            if not junk:
                return jsonify({"success": True, "removed": 0, "message": "No junk found — ACQUISITION LEADS is already clean."})

            # Get headers from first row
            headers = list(records[0].keys()) if records else []

            # Clear sheet and rewrite without junk rows
            ws.clear()
            ws.append_row(headers)
            if clean_records:
                rows = [[r.get(h, "") for h in headers] for r in clean_records]
                ws.append_rows(rows)

            return jsonify({
                "success": True,
                "removed": len(junk),
                "kept": len(clean_records),
                "message": f"Removed {len(junk)} junk entries. {len(clean_records)} clean leads remain."
            })

        # GET: preview
        return render_template("clean.html",
            junk=junk,
            junk_count=len(junk),
            clean_count=len(clean_records),
            keywords=JUNK_KEYWORDS
        ) if os.path.exists(os.path.join(app.root_path, "templates", "clean.html")) else jsonify({
            "preview": True,
            "junk_count": len(junk),
            "clean_count": len(clean_records),
            "junk_stores": [r.get("Store Name", "") for r in junk[:50]],
            "message": f"Found {len(junk)} junk entries. POST to /clean to remove them."
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/scraper")
def scraper():
    return render_template("scraper.html",
        state=scraper_state,
        error=None
    )


# ─────────────────────────────────────────
#  API ENDPOINTS
# ─────────────────────────────────────────

@app.route("/api/send-pitch", methods=["POST"])
def send_pitch():
    """Log a pitch outreach for a store."""
    data = request.json
    store_name = data.get("store_name", "")
    channel = data.get("channel", "Instagram DM")
    message = data.get("message", "Hey! We're Godspeed — a streetwear brand that would be a perfect fit for your store. Mind if we send over our lookbook?")

    try:
        # Look up city/state from MASTER DATABASE
        stores, _ = get_stores()
        store_record = next((s for s in stores if s.get("Store Name") == store_name), {})
        city = store_record.get("City", "")
        state = store_record.get("State", "")

        # Write with correct schema: [Store Name, City, State, Channel, Message, Sent At, Response, Response At, Status, Agent]
        write_outreach_log(store_name, city, state, channel, message, status="Sent", agent="Jordan Belfort")

        # Update store outreach status in MASTER DATABASE
        ss = get_sheet()
        stores_ws = ss.worksheet("MASTER DATABASE")
        records = stores_ws.get_all_records()
        headers = stores_ws.row_values(1)

        status_col = None
        for i, h in enumerate(headers):
            if h.strip().lower() in ("outreach status", "outreach_status"):
                status_col = i + 1
                break

        if status_col:
            for i, record in enumerate(records, start=2):
                if record.get("Store Name") == store_name:
                    stores_ws.update_cell(i, status_col, "Pitched")
                    break

        return jsonify({"success": True, "message": f"Pitch logged for {store_name}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/send-reorder", methods=["POST"])
def send_reorder():
    """Log a reorder outreach for an existing retailer."""
    data = request.json
    store_name = data.get("store_name", "")
    channel = data.get("channel", "Email")
    message = data.get("message", "Hey! Just checking in — ready to restock Godspeed? Let us know what you need and we'll get it shipped ASAP.")

    try:
        stores, _ = get_stores()
        store_record = next((s for s in stores if s.get("Store Name") == store_name), {})
        city = store_record.get("City", "")
        state = store_record.get("State", "")

        write_outreach_log(store_name, city, state, channel, message, status="Reorder Sent", agent="Jordan Belfort")

        return jsonify({"success": True, "message": f"Reorder request logged for {store_name}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/bulk-pitch", methods=["POST"])
def bulk_pitch():
    """Log bulk pitch for multiple stores."""
    data = request.json
    store_names = data.get("stores", [])
    channel = data.get("channel", "Instagram DM")
    message = data.get("message", "Hey! We're Godspeed — a streetwear brand that would be a perfect fit for your store. Mind if we send over our lookbook?")

    try:
        # Build a lookup for city/state
        stores, _ = get_stores()
        store_lookup = {s.get("Store Name", ""): s for s in stores}

        ss = get_sheet()
        log_ws = ss.worksheet("OUTREACH LOG")

        # Validate headers on log sheet
        existing_headers = log_ws.row_values(1)
        if existing_headers != OUTREACH_LOG_HEADERS:
            reset_outreach_log_schema(ss)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows = []
        for sname in store_names:
            rec = store_lookup.get(sname, {})
            rows.append([
                sname,
                rec.get("City", ""),
                rec.get("State", ""),
                channel,
                message,
                now,
                "",
                "",
                "Sent",
                "Jordan Belfort"
            ])

        if rows:
            log_ws.append_rows(rows)

        # Update outreach status in MASTER DATABASE
        stores_ws = ss.worksheet("MASTER DATABASE")
        records = stores_ws.get_all_records()
        headers = stores_ws.row_values(1)
        status_col = None
        for i, h in enumerate(headers):
            if h.strip().lower() in ("outreach status", "outreach_status"):
                status_col = i + 1
                break

        if status_col:
            for i, record in enumerate(records, start=2):
                if record.get("Store Name") in store_names:
                    stores_ws.update_cell(i, status_col, "Pitched")

        return jsonify({"success": True, "message": f"Bulk pitch sent to {len(store_names)} stores"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/scraper/start", methods=["POST"])
def scraper_start():
    """
    Scraper is queued — Wilmar runs it overnight.
    Do not fake progress or hardcode results.
    """
    return jsonify({
        "success": True,
        "queued": True,
        "message": "Scraper queued — Wilmar will run overnight. Check back tomorrow."
    })


@app.route("/api/scraper/status")
def scraper_status():
    return jsonify(scraper_state)


@app.route("/api/reset-outreach-log", methods=["POST"])
def api_reset_outreach_log():
    """Manually reset the OUTREACH LOG schema (admin use)."""
    try:
        ss = get_sheet()
        ok, msg = reset_outreach_log_schema(ss)
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    stores, error = get_stores()
    outreach, _ = get_outreach_log()
    stats = compute_stats(stores)
    stats["sent"] = len(outreach)
    stats["replied"] = sum(1 for o in outreach if o.get("Response", "").strip())
    if error:
        stats["error"] = error
    return jsonify(stats)


if __name__ == "__main__":
    print("🚀 Godspeed Retail Intelligence Dashboard")
    print("   Built by Raj Patel | El Barrio")
    print("   Running on http://127.0.0.1:8080")

    # On startup, verify and reset OUTREACH LOG schema if needed
    try:
        ss = get_sheet()
        ensure_worksheets(ss)
        ws = ss.worksheet("OUTREACH LOG")
        existing_headers = ws.row_values(1)
        if existing_headers != OUTREACH_LOG_HEADERS:
            print("⚠️  OUTREACH LOG schema mismatch on startup — resetting...")
            reset_outreach_log_schema(ss)
        else:
            print("✅ OUTREACH LOG schema OK.")
    except Exception as e:
        print(f"⚠️  Startup sheet check failed: {e}")

    app.run(debug=True, host="127.0.0.1", port=8080)
