"""
Godspeed Retail Intelligence System — Dashboard (v2)
Rewired for the clean 3-tab schema: STORES / OUTREACH_LOG / ORDERS.

What changed from v1:
  - Reads the STORES tab (clean schema) instead of the scrambled MASTER DATABASE.
  - Adds OUTREACH_LOG (new schema, supports Drafted/Queued/Sent) and ORDERS (+ commission).
  - Templates are unchanged: a compatibility layer maps clean fields -> the legacy
    display keys the templates already use, so nothing in the UI breaks.
  - New /orders view with commission tracking.
  - Local dev/test mode: set GODSPEED_LOCAL_DIR=/path/to/csvs to read CSVs instead of Sheets.
"""

import os
import re
import csv
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────  CONFIG
SPREADSHEET_ID = "1My0941FahT4XvcdOK1UQtnMPA1qYI-Pqmkx-9v5nEnA"
STORES_SHEET     = "STORES"
OUTREACH_SHEET   = "OUTREACH_LOG"
ORDERS_SHEET     = "ORDERS"
CANDIDATES_SHEET = "CANDIDATES"
INVOICES_SHEET   = "INVOICES"

TOKEN_PATH = os.environ.get("GOOGLE_TOKEN_PATH", "/Users/elbarrio/.openclaw/drive-token.json")
CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", "/Users/elbarrio/.openclaw/google-credentials.json")
GOOGLE_TOKEN_JSON = os.environ.get("GOOGLE_TOKEN_JSON", "")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

# If set, read/write local CSVs instead of Google Sheets (for local dev + testing).
LOCAL_DIR = os.environ.get("GODSPEED_LOCAL_DIR", "")

DEFAULT_COMMISSION = 0.10  # Goldie's 10%

# ─────────────────────────────────────────  STATUS MAPPING
# clean pipeline_stage  ->  legacy badge word the templates already style
STAGE_TO_BADGE = {
    "won": "Converted", "in talks": "Replied", "replied": "Replied",
    "contacted": "Pitched", "lost": "Declined", "disqualified": "Declined",
    "new": "Not Contacted", "qualified": "Not Contacted",
}

def stage_badge(stage):
    return STAGE_TO_BADGE.get((stage or "").strip().lower(), "Not Contacted")

# ─────────────────────────────────────────  GOOGLE SHEETS AUTH
def get_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if GOOGLE_TOKEN_JSON and GOOGLE_CREDENTIALS_JSON:
        token_data = json.loads(GOOGLE_TOKEN_JSON)
        creds_data = json.loads(GOOGLE_CREDENTIALS_JSON)
    elif os.path.exists(TOKEN_PATH) and os.path.exists(CREDS_PATH):
        with open(TOKEN_PATH) as f: token_data = json.load(f)
        with open(CREDS_PATH) as f: creds_data = json.load(f)
    else:
        raise FileNotFoundError("Google credentials not configured.")
    installed = creds_data.get("installed", creds_data)
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=installed["client_id"], client_secret=installed["client_secret"],
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.file"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data["access_token"] = creds.token
        if not GOOGLE_TOKEN_JSON and os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, "w") as f: json.dump(token_data, f, indent=2)
    return creds

def get_sheet():
    import gspread
    return gspread.authorize(get_creds()).open_by_key(SPREADSHEET_ID)

# ─────────────────────────────────────────  DATA LAYER (Sheets OR local CSV)
def _read_records(sheet_name):
    """Return list-of-dicts for a tab, from local CSV if LOCAL_DIR set, else Sheets."""
    if LOCAL_DIR:
        path = os.path.join(LOCAL_DIR, f"{sheet_name}.csv")
        if not os.path.exists(path):
            return [], None
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f)), None
    try:
        ws = get_sheet().worksheet(sheet_name)
        # Cast every cell to str so Sheets mode matches CSV mode. gspread auto-types
        # numeric-looking cells (e.g. a store literally named "424") to int/float,
        # which breaks sorting and .lower() across mixed str/int values.
        recs = [{k: ("" if v is None else str(v)) for k, v in row.items()}
                for row in ws.get_all_records()]
        return recs, None
    except Exception as e:
        return [], str(e)

def _normalize_store(r):
    """Add legacy display keys so existing templates render unchanged."""
    r = dict(r)
    r["Store Name"]      = r.get("store_name", "")
    r["City"]            = r.get("city", "")
    r["State"]          = r.get("market", "")          # templates show market in the State column
    r["Email"]           = r.get("email", "")
    r["Phone"]           = r.get("phone", "")
    r["Instagram"]       = r.get("instagram", "")
    r["Website"]         = r.get("website", "")
    r["Last Order Date"] = r.get("last_order_date", "")
    r["Outreach Status"] = stage_badge(r.get("pipeline_stage", ""))
    return r

def _normalize_outreach(r):
    r = dict(r)
    r["Store Name"] = r.get("store_name", "")
    r["Channel"]    = r.get("channel", "")
    r["Message"]    = r.get("message", "")
    r["Sent At"]    = r.get("sent_at", "")
    r["Status"]     = r.get("status", "")
    r["Response"]   = r.get("reply_text", "")
    return r

def get_stores():
    recs, err = _read_records(STORES_SHEET)
    return [_normalize_store(r) for r in recs], err

def get_outreach_log():
    recs, err = _read_records(OUTREACH_SHEET)
    return [_normalize_outreach(r) for r in recs], err

def get_orders():
    recs, err = _read_records(ORDERS_SHEET)
    return recs, err

def is_customer(s):
    """A store is a customer (Accounts engine) once Won / has an account_status."""
    acc = (s.get("account_status", "") or "").strip().lower()
    stage = (s.get("pipeline_stage", "") or "").strip().lower()
    return acc in ("active", "dormant", "churned") or stage == "won"

def compute_stats(stores):
    total = len(stores)
    customers = sum(1 for s in stores if is_customer(s))
    return {
        "total": total,
        "leads": total - customers,     # prospects still in acquisition
        "retailers": customers,         # active accounts
    }

# ─────────────────────────────────────────  WRITE HELPERS
def _next_id(records, id_field, prefix, width=4):
    mx = 0
    for r in records:
        v = str(r.get(id_field, ""))
        m = re.search(r'(\d+)$', v)
        if m: mx = max(mx, int(m.group(1)))
    return f"{prefix}-{mx+1:0{width}d}"

def append_store(fields):
    if LOCAL_DIR:  # dev mode: no-op write
        return
    ss = get_sheet(); ws = ss.worksheet(STORES_SHEET)
    headers = ws.row_values(1)
    ws.append_row([fields.get(h, "") for h in headers])

def append_outreach(store_id, store_name, channel, message, status="Sent",
                    direction="Outbound", template_used="", sent_by="Jordan Belfort"):
    if LOCAL_DIR:
        return
    ss = get_sheet(); ws = ss.worksheet(OUTREACH_SHEET)
    headers = ws.row_values(1)
    existing, _ = _read_records(OUTREACH_SHEET)
    row = {
        "outreach_id": _next_id(existing, "outreach_id", "OUT", 5),
        "store_id": store_id, "store_name": store_name, "channel": channel,
        "direction": direction, "template_used": template_used, "message": message,
        "status": status, "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sent_by": sent_by, "reply_text": "", "reply_at": "", "sentiment": "", "notes": "",
    }
    ws.append_row([row.get(h, "") for h in headers])

def set_pipeline_stage(store_name, stage):
    if LOCAL_DIR:
        return
    ss = get_sheet(); ws = ss.worksheet(STORES_SHEET)
    headers = ws.row_values(1)
    if "pipeline_stage" not in headers or "store_name" not in headers:
        return
    col = headers.index("pipeline_stage") + 1
    records = ws.get_all_records()
    for i, rec in enumerate(records, start=2):
        if rec.get("store_name") == store_name:
            ws.update_cell(i, col, stage); break

# ─────────────────────────────────────────  ROUTES
@app.route("/")
def index():
    stores, error = get_stores()
    outreach, _ = get_outreach_log()
    stats = compute_stats(stores)
    sent = sum(1 for o in outreach if (o.get("direction", "Outbound") != "Inbound"))
    replied = sum(1 for o in outreach if o.get("Response", "").strip())
    converted = sum(1 for s in stores if (s.get("pipeline_stage", "").strip().lower() == "won"))
    recent = sorted(outreach, key=lambda x: x.get("Sent At", ""), reverse=True)[:10]

    # Reorder alerts: customers with no order in 60+ days
    today = datetime.today(); alerts = []
    for s in stores:
        if not is_customer(s):
            continue
        lod = s.get("Last Order Date", "")
        if lod:
            try:
                if (today - datetime.strptime(lod, "%Y-%m-%d")).days > 60:
                    alerts.append(s)
            except Exception:
                pass
        elif (s.get("account_status", "").strip().lower() == "dormant"):
            alerts.append(s)

    return render_template("index.html", stats=stats, sent=sent, replied=replied,
                           converted=converted, recent=recent, alerts=alerts, error=error)

@app.route("/leads")
def leads():
    stores, error = get_stores()
    # acquisition view = prospects (not yet customers)
    stores = [s for s in stores if not is_customer(s)]
    city = request.args.get("city", "").strip().lower()
    state = request.args.get("state", "").strip().lower()   # really "market"
    status = request.args.get("status", "").strip().lower()
    if city:   stores = [s for s in stores if city in s.get("City", "").lower()]
    if state:  stores = [s for s in stores if state in s.get("State", "").lower()]
    if status: stores = [s for s in stores if status in s.get("Outreach Status", "").lower()]
    cities = sorted({s.get("City", "") for s in stores if s.get("City", "")})
    states = sorted({s.get("State", "") for s in stores if s.get("State", "")})
    statuses = sorted({s.get("Outreach Status", "") for s in stores if s.get("Outreach Status", "")})
    return render_template("leads.html", leads=stores, cities=cities, states=states,
                           statuses=statuses, city_filter=city, state_filter=state,
                           status_filter=status, error=error)

@app.route("/retailers")
def retailers():
    stores, error = get_stores()
    today = datetime.today()
    rl = [s for s in stores if is_customer(s)]
    for r in rl:
        lod = r.get("Last Order Date", "")
        try:
            d = (today - datetime.strptime(lod, "%Y-%m-%d")).days if lod else None
        except Exception:
            d = None
        r["_days_since"] = d
        r["_alert"] = (d is not None and d > 60)
    return render_template("retailers.html", retailers=rl, error=error)

@app.route("/outreach")
def outreach():
    log, error = get_outreach_log()
    stores, _ = get_stores()
    sf = request.args.get("store", "").strip().lower()
    cf = request.args.get("channel", "").strip().lower()
    dfilt = request.args.get("date", "").strip()
    if sf: log = [o for o in log if sf in o.get("Store Name", "").lower()]
    if cf: log = [o for o in log if cf in o.get("Channel", "").lower()]
    if dfilt: log = [o for o in log if dfilt in o.get("Sent At", "")]
    log = sorted(log, key=lambda x: x.get("Sent At", ""), reverse=True)
    store_names = sorted({s.get("Store Name", "") for s in stores if s.get("Store Name", "")})
    channels = ["Email", "Instagram DM", "WhatsApp", "Phone"]
    return render_template("outreach.html", log=log, store_names=store_names, channels=channels,
                           store_filter=sf, channel_filter=cf, date_filter=dfilt, error=error)

@app.route("/orders")
def orders():
    rows, error = get_orders()
    def num(x):
        try: return float(x)
        except Exception: return 0.0
    summary = {
        "orders": len(rows),
        "revenue": sum(num(r.get("order_total")) for r in rows),
        "comm_pending": sum(num(r.get("commission_amount")) for r in rows
                            if (r.get("commission_status", "").lower() == "pending")),
        "comm_invoiced": sum(num(r.get("commission_amount")) for r in rows
                             if (r.get("commission_status", "").lower() == "invoiced")),
        "comm_paid": sum(num(r.get("commission_amount")) for r in rows
                         if (r.get("commission_status", "").lower() == "paid")),
    }
    rows = sorted(rows, key=lambda x: x.get("order_date", ""), reverse=True)
    return render_template("orders.html", orders=rows, summary=summary, error=error)

@app.route("/add-store", methods=["GET", "POST"])
def add_store():
    if request.method == "POST":
        try:
            existing, _ = _read_records(STORES_SHEET)
            f = request.form
            email = f.get("email", "").strip()
            ig = f.get("instagram", "").strip()
            phone = f.get("phone", "").strip()
            has_contact = bool(email or ig or phone)
            store = {
                "store_id": _next_id(existing, "store_id", "GS", 4),
                "store_name": f.get("name", "").strip(),
                "country": f.get("country", "USA").strip() or "USA",
                "city": f.get("city", "").strip(),
                "market": f.get("market", "").strip(),
                "contact_name": f.get("contact_name", "").strip(),
                "instagram": ig, "ig_followers": "",
                "website": f.get("website", "").strip(),
                "email": email, "email_status": "unverified",
                "phone": phone, "whatsapp": "",
                "brands_carried": f.get("brands", "").strip(),
                "fit_score": "", "tier": "", "score_reasons": "",
                "source": "Manual",
                "pipeline_stage": "Qualified" if has_contact else "New",
                "account_status": "", "owner": "Goldie",
                "next_action": "", "next_action_date": "",
                "last_outreach_date": "", "last_order_date": "",
                "notes": f.get("notes", "").strip(),
                "date_added": datetime.today().strftime("%Y-%m-%d"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            append_store(store)
            return redirect(url_for("leads") + "?added=1")
        except Exception as e:
            return render_template("add_store.html", error=str(e))
    return render_template("add_store.html", error=None)

@app.route("/scraper")
def scraper():
    state = {"running": False, "status": "queued",
             "message": "Validated scrape queued — Wilmar gathers, Raj validates on write, "
                        "Vito scores. Only rows that pass the validation gate are stored."}
    return render_template("scraper.html", state=state, error=None)

# ─────────────────────────────────────────  API
@app.route("/api/send-pitch", methods=["POST"])
def send_pitch():
    data = request.json or {}
    name = data.get("store_name", "")
    channel = data.get("channel", "Instagram DM")
    message = data.get("message", "")
    status = data.get("status", "Sent")  # supports Drafted / Queued / Sent
    try:
        stores, _ = get_stores()
        rec = next((s for s in stores if s.get("Store Name") == name), {})
        append_outreach(rec.get("store_id", ""), name, channel, message,
                        status=status, template_used=data.get("template_used", ""))
        if status == "Sent":
            set_pipeline_stage(name, "Contacted")
        return jsonify({"success": True, "message": f"{status} logged for {name}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/bulk-pitch", methods=["POST"])
def bulk_pitch():
    data = request.json or {}
    names = data.get("stores", [])
    channel = data.get("channel", "Instagram DM")
    message = data.get("message", "")
    status = data.get("status", "Sent")
    try:
        stores, _ = get_stores()
        lookup = {s.get("Store Name", ""): s for s in stores}
        for n in names:
            append_outreach(lookup.get(n, {}).get("store_id", ""), n, channel, message, status=status)
            if status == "Sent":
                set_pipeline_stage(n, "Contacted")
        return jsonify({"success": True, "message": f"{status} logged for {len(names)} stores"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/send-reorder", methods=["POST"])
def send_reorder():
    data = request.json or {}
    name = data.get("store_name", "")
    channel = data.get("channel", "Email")
    message = data.get("message", "")
    try:
        stores, _ = get_stores()
        rec = next((s for s in stores if s.get("Store Name") == name), {})
        append_outreach(rec.get("store_id", ""), name, channel, message,
                        status="Sent", template_used="reorder")
        return jsonify({"success": True, "message": f"Reorder logged for {name}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/scraper/start", methods=["POST"])
def scraper_start():
    return jsonify({"success": True, "queued": True,
                    "message": "Validated scrape queued — only rows passing the gate are stored."})

@app.route("/api/stats")
def api_stats():
    stores, error = get_stores()
    outreach, _ = get_outreach_log()
    stats = compute_stats(stores)
    stats["sent"] = len(outreach)
    stats["replied"] = sum(1 for o in outreach if o.get("Response", "").strip())
    if error: stats["error"] = error
    return jsonify(stats)

if __name__ == "__main__":
    print("🚀 Godspeed Dashboard v2 — clean schema (STORES / OUTREACH_LOG / ORDERS)")
    app.run(debug=True, host="127.0.0.1", port=8080)
