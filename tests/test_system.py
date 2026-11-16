"""End-to-end tests: cleaning rules, the build pipeline, the dashboard, live verification."""

import http.server
import threading

import pytest

import app as dashboard
import pipeline
import quality as q
import sheets
import verify
from fake_sheets import FakeSpreadsheet

ACQ = [
    ["Store Name", "City", "State", "Country", "Territory", "Instagram", "Email", "Phone", "Website",
     "Warm Lead", "Outreach Status", "Date Added"],
    ["Sole Supremacy", "San Jose", "CA", "USA", "West", "@solesupremacy", "", "(408) 800-4950",
     "https://solesupremacy.com", "No", "Not Contacted", "2026-04-21"],
    ["Hollister Co. at Woodland Hills Mall - Tulsa - Simon", "Tulsa", "OK", "USA", "Southwest",
     "@hollister", "", "", "", "No", "Not Contacted", "2026-04-21"],
    ["Home Supreme Marine Inc. Fort Lauderdale", "Fort Lauderdale", "FL", "USA", "Southeast",
     "@suprememarineinc", "jquery.maskedinput@1.4.1", "(954) 797-1818", "https://suprememarineinc.com",
     "No", "Not Contacted", "2026-04-21"],
    ["Best Sneaker Stores in Miami", "Miami", "FL", "USA", "Southeast", "@designscene", "", "",
     "https://designscene.net/2025/01/best-sneaker-stores-miami.html", "No", "Not Contacted", "2026-04-21"],
]
# Old master tab: curated layout (status sits under 'Carries Godspeed') + scraped layout.
BACKUP = [
    ["Store Name", "City", "State", "Country", "Website", "Instagram", "Email", "Phone", "Carries Supreme",
     "Carries Hellstar", "Carries Godspeed", "Last Order Date", "Outreach Status", "Outreach Channel",
     "Notes", "Date Added", "Lead Score", "Priority Tier", "", ""],
    ["HYP Miami", "Miami (Brickell)", "FL", "", "https://hypmiami.com", "@hypmiami", "No", "No", "No", "",
     "New Lead", "Premium streetwear Brickell - Chrome Hearts/Fear of God"],
    ["Duval Kickz", "Jacksonville", "FL", "", "https://duvalkickz.com", "@duvalkickz", "Yes", "Yes", "Yes",
     "", "Not Contacted", "CONFIRMED carries Godspeed + Hellstar."],
    ["Store Name", "City", "State", "Instagram", "https://Website", "Phone"],          # stray header row
    ["R H U D E", "Miami", "Florida", "USA", "https://rh-ude.com/?srsltid=abc", "@rhude", "", "1613580349",
     "", "", "2026-04-16"],
    ["Supreme Sets Up Shop in Miami", "Miami", "Florida", "USA",
     "https://hypebeast.com/2025/4/supreme-miami-store-opening-info", "@hypebeast", "app-store-en@2x.png",
     "3702846231", "", "", "2026-04-16"],
    ["LUXE MIAMI (@luxe.mia) · Coral Gables, FL", "Coral Gables", "Florida", "USA",
     "https://www.instagram.com/luxe.mia/?hl=en", "@font", "", "1037483433", "", "", "2026-04-16"],
    ["Shop Hellstar clothing", "Austin", "Texas", "USA", "https://www.theatticstreetwear.com/hellstar",
     "@theatticstreetwear", "", "1037486289", "", "", "2026-04-16"],
    ["Shop Hellstar clothing", "Dallas", "Texas", "USA", "https://www.theatticstreetwear.com/hellstar",
     "@theatticstreetwear", "", "1037486289", "", "", "2026-04-16"],
    ["Sole Supremacy | Sneaker Boutique San Jose", "San Jose", "California", "USA",
     "https://solesupremacy.com/?srsltid=x", "", "info@solesupremacy.com", "1037486289", "", "", "2026-04-16"],
]
CITY = [
    ["Store Name", "City", "State", "Website", "Instagram", "Email", "Phone", "Outreach Status", "Date Added"],
    ["La Esencia Boutique", "Santo Domingo", "Dominican Republic", "", "@la.esencia.boutique", "", "#ERROR!",
     "Active Customer", "2026-04-20"],
    ["Wasteland SF", "San Francisco", "CA", "https://shopwasteland.com", "@shopwasteland", "", "", "", ""],
]
OUTREACH = [sheets.OUTREACH_HEADERS]


def workbook():
    return FakeSpreadsheet({
        "MASTER DATABASE (backup)": BACKUP, "ACQUISITION LEADS": ACQ, "DR - Dominican Republic": CITY,
        "OUTREACH LOG": OUTREACH, "Scraper Log": [["Run Date", "Stores Found"]],
        "ORDERS": [["order_id", "store_name"], ["GS-001", "La Esencia Boutique"]],
    })


@pytest.fixture
def ss():
    book = workbook()
    sheets.use_spreadsheet(book)
    dashboard.invalidate()
    dashboard._cache.update(records=None, outreach=None)
    return book


@pytest.fixture
def client(ss):
    dashboard.app.config["TESTING"] = True
    return dashboard.app.test_client()


def built():
    records, stats = pipeline.build_master(workbook().tabs)
    return {r["Store Name"]: r for r in records}, stats


# ── quality rules ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,city,expected", [
    ("Foot Locker #233", "Burbank", "chain"),
    ("Nike Well Collective - Brickell", "Miami", "mono-brand"),
    ("Supreme Los Angeles", "Los Angeles", "mono-brand"),
    ("Lululemon", "Austin", "mono-brand"),
    ("Joe's Pizza", "Queens", "junk"),
    ("Westland Mall", "Hialeah", "not-a-store"),
    ("10 Dallas Streetwear Brands You Should Be Wearing", "Dallas", "not-a-store"),
])
def test_rejects(name, city, expected):
    flag, _ = q.classify({"Store Name": name, "City": city})
    assert expected in flag.split("+")
    assert q.bucket(flag) == "rejected"


@pytest.mark.parametrize("name,city", [
    ("Supreme Kicks Boutique", "Dallas"),       # 'supreme' in an independent's name
    ("Tacoma Sneaker Exchange", "Tacoma"),      # city contains 'taco'
    ("Retail Therapy Boutique", "Burbank"),     # 'therapy', city contains 'bank'
    ("Jordan's Closet", "Columbia"),            # brand word + chain-named city
    ("Lovely Kickz Boutique", "Orlando"),
])
def test_keeps_independents(name, city):
    assert q.classify({"Store Name": name, "City": city})[0] == "OK"


def test_brand_in_notes_is_not_a_brand_store():
    row = {"Store Name": "HYP Miami", "Website": "https://hypmiami.com", "Instagram": "@hypmiami",
           "Notes": "Carries Chrome Hearts, Fear of God, Supreme"}
    assert q.classify(row)[0] == "OK"


def test_no_signal_goes_to_review_not_rejected():
    flag, _ = q.classify({"Store Name": "Smith & Sons", "City": "Reno"})
    assert flag == "low-fit" and q.bucket(flag) == "review"
    assert q.bucket(flag, "Approved") == "qualified"
    assert q.bucket("OK", "Rejected") == "rejected"


@pytest.mark.parametrize("raw,ok", [
    ("(305) 482-1100", True), ("+1 305-482-1100", True), (3054821100, True),
    ("1037486289", False), ("1750677234", False), ("9999999999", False), ("305-482-110", False),
    ("(310) 555-1234", False), ("#ERROR!", False), ("No", False),
])
def test_phone(raw, ok):
    assert bool(q.normalize_phone(raw)) is ok


@pytest.mark.parametrize("raw,handle", [
    ("@HypMiami", "hypmiami"), ("https://www.instagram.com/luxe.mia/?hl=en", "luxe.mia"),
    ("instagram.com/p/Cabc123/", None), ("@rsrc.php", None), ("@bad handle", None), ("@34.716203", None),
])
def test_instagram(raw, handle):
    assert q.normalize_instagram(raw) == handle


def test_email_junk():
    assert q.normalize_email("info@survivalmiami.com") == "info@survivalmiami.com"
    for junk in ("icon-klarna@2x.static.png", "bootstrap@4.0.0", "john.doe@email.com", "No"):
        assert q.normalize_email(junk) is None


# ── pipeline ─────────────────────────────────────────────────────────────────

def test_build_merges_and_cleans():
    stores, stats = built()
    assert stats["source_tabs"] == 3                       # logs / orders tabs are ignored

    sole = stores["Sole Supremacy"]                        # ACQ row + scraped page-title row merged
    assert sole["Phone"] == "(408) 800-4950"               # the fake 1037486289 never wins
    assert sole["Email"] == "info@solesupremacy.com"       # blank filled from the other tab
    assert sole["Cleanup Flag"] == "OK" and sole["State"] == "CA"
    assert "ACQUISITION LEADS" in sole["Sources"] and "MASTER DATABASE (backup)" in sole["Sources"]

    hyp = stores["HYP Miami"]                              # legacy curated layout is un-shifted
    assert hyp["Outreach Status"] == "New Lead" and hyp["Email"] == "" and hyp["Phone"] == ""
    assert "Chrome Hearts" in hyp["Notes"] and hyp["Cleanup Flag"] == "OK"

    assert stores["Duval Kickz"]["Carries Godspeed"] == "Yes"
    assert stores["La Esencia Boutique"]["Carries Godspeed"] == "Yes"
    assert stores["La Esencia Boutique"]["Phone"] == ""    # '#ERROR!' dropped

    luxe = stores["LUXE MIAMI"]                            # Instagram page title -> store + handle
    assert luxe["Instagram"] == "@luxe.mia" and luxe["Website"] == "" and luxe["Phone"] == ""

    assert "Store Name" not in stores                      # stray header row skipped
    attic = [r for n, r in stores.items() if "theatticstreetwear" in r["Website"]]
    assert len(attic) == 1                                 # one site searched in two cities = one store


def test_dates_as_sheets_displays_them():
    assert pipeline.clean_date("4/16/2026") == "2026-04-16"
    assert pipeline.clean_date("2026-04-16 00:00:00") == "2026-04-16"
    assert pipeline.clean_date("Sneaker boutique in Orlando") == ""
    rec = {f: "" for f in pipeline.HEADER_ALIASES}
    rec.update(name="R H U D E", carries_godspeed="4/16/2026")
    pipeline._unshift_legacy_master(rec)                   # scraped layout: date sits under 'Carries Godspeed'
    assert rec["date_added"] == "4/16/2026" and rec["carries_godspeed"] == ""


def test_build_flags_junk():
    stores, _ = built()
    assert "mono-brand" in stores["R H U D E"]["Cleanup Flag"]
    assert "not-a-store" in stores["Supreme Sets Up Shop in Miami"]["Cleanup Flag"]
    assert "not-a-store" in stores["Best Sneaker Stores in Miami"]["Cleanup Flag"]
    assert "chain" in next(r for n, r in stores.items() if n.startswith("Hollister"))["Cleanup Flag"]
    marine = next(r for n, r in stores.items() if "Marine" in n)
    assert marine["Email"] == "" and marine["Cleanup Flag"] == "low-fit"
    assert stores["R H U D E"]["Website"] == "https://rh-ude.com/"     # tracking parameter stripped


def test_source_tabs_untouched_and_rebuild_keeps_edits(client, ss):
    before = {k: [list(r) for r in v] for k, v in ss.tabs.items()}
    dashboard.rebuild_master()
    assert {k: v for k, v in ss.tabs.items() if k != "MASTER DATABASE"} == before

    rows = {r["Store Name"]: r for r in dashboard.load_master(force=True)[0]}
    sole, waste = rows["Sole Supremacy"], rows["Wasteland SF"]
    assert waste["_bucket"] == "review"
    assert client.post("/api/send-pitch", json={"row": sole["_row"], "store_name": "Sole Supremacy",
                                                "channel": "Email"}).json["success"]
    assert client.post("/api/review", json={"row": waste["_row"], "store_name": "Wasteland SF",
                                            "decision": "approve"}).json["bucket"] == "qualified"
    first = dashboard.rebuild_master()
    second = dashboard.rebuild_master()
    assert first["unique_stores"] == second["unique_stores"]
    rows = {r["Store Name"]: r for r in dashboard.load_master(force=True)[0]}
    assert rows["Sole Supremacy"]["Outreach Status"] == "Pitched"
    assert rows["Sole Supremacy"]["Outreach Channel"] == "Email"
    assert rows["Wasteland SF"]["_bucket"] == "qualified"


# ── dashboard ────────────────────────────────────────────────────────────────

def test_setup_page_before_build(client):
    page = client.get("/")
    assert page.status_code == 200 and b"Build clean database" in page.data
    assert client.get("/api/stats").json == {"setup_required": True}
    assert client.post("/api/send-pitch", json={"store_name": "x"}).status_code == 503


def test_pages_render(client):
    dashboard.rebuild_master()
    for path in ("/", "/leads", "/leads?view=review", "/leads?view=rejected&q=rhude", "/leads?view=all&page=9",
                 "/leads?contact=problem&tier=Hot&state=FL&status=pitched", "/retailers", "/outreach",
                 "/quality", "/add-store", "/export/leads.csv", "/healthz"):
        assert client.get(path).status_code == 200, path
    leads = client.get("/leads").data.decode()
    assert "Sole Supremacy" in leads and "R H U D E" not in leads and "Hollister" not in leads
    assert "Duval Kickz" in client.get("/retailers").data.decode()
    stats = client.get("/api/stats").json
    assert stats["retailers"] == 2 and stats["qualified"] + stats["review"] + stats["rejected"] == stats["total"]


def test_pitch_logs_without_touching_existing_log(client, ss):
    ss.tabs["OUTREACH LOG"].append(["Old Store", "X", "Y", "Email", "hi", "2026-01-01 10:00", "", "", "Sent", "Goldie"])
    ss.tabs["OUTREACH LOG"][0].append("My Extra Column")     # a hand-added column must not wipe the log
    dashboard.rebuild_master()
    sole = next(r for r in dashboard.load_master(force=True)[0] if r["Store Name"] == "Sole Supremacy")
    res = client.post("/api/bulk-pitch", json={"stores": [{"row": sole["_row"], "name": "Sole Supremacy"}]})
    assert res.json["count"] == 1
    log = ss.tabs["OUTREACH LOG"]
    assert log[1][0] == "Old Store" and log[-1][0] == "Sole Supremacy" and log[-1][8] == "Sent"
    assert client.post("/api/send-pitch", json={"row": 2, "store_name": "Wrong Name"}).status_code == 404


def test_add_store_lands_in_master(client, ss):
    dashboard.rebuild_master()
    res = client.post("/add-store", data={"name": "Test Kicks", "city": "Newark", "state": "New Jersey",
                                          "instagram": "https://instagram.com/TestKicks/",
                                          "phone": "973 482 1100", "website": "testkicks.com", "brands": "Hellstar"})
    assert res.status_code == 302
    row = dict(zip(ss.tabs["MASTER DATABASE"][0], ss.tabs["MASTER DATABASE"][-1]))
    assert (row["Instagram"], row["Phone"], row["Website"], row["State"]) == \
        ("@testkicks", "(973) 482-1100", "https://testkicks.com", "NJ")
    assert row["Cleanup Flag"] == "OK"


def test_password_gate(client, monkeypatch):
    monkeypatch.setattr(dashboard, "DASHBOARD_PASSWORD", "s3cret")
    assert client.get("/leads").status_code == 401
    assert client.get("/healthz").status_code == 200
    import base64
    token = base64.b64encode(b"goldie:s3cret").decode()
    assert client.get("/healthz", headers={"Authorization": "Basic " + token}).status_code == 200
    assert client.get("/", headers={"Authorization": "Basic " + token}).status_code == 200


# ── live verification (against a local web server) ───────────────────────────

PAGES = {
    "/good": '<a href="https://www.instagram.com/solesupremacy/">IG</a> <a href="tel:+14088004950">call</a>'
             '<a href="mailto:hello@solesupremacy.com">mail</a> We stock Hellstar and Supreme sneakers.',
    "/other": '<a href="https://instagram.com/realhandle">IG</a> Call us at (212) 334-9000 today',
    "/blank": "<html><body>Welcome</body></html>",
    "/waste": '<a href="https://www.instagram.com/shopwasteland/">IG</a> <a href="mailto:hi@shopwasteland.com">'
              'mail</a> Vintage and streetwear: Supreme, Stussy, Hellstar.',
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path)
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write((body or "gone").encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def site(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(verify, "check_instagram", lambda handle, session: "unverified")
    monkeypatch.setattr(q, "normalize_website", lambda raw: q.s(raw) or None)
    monkeypatch.setattr(q, "website_status", lambda raw: "format-ok" if q.s(raw) else "empty")
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _verify(rec):
    import requests
    return verify.verify_record(rec, requests.Session())


def test_verify_confirms_matching_contact_info(site):
    changes = _verify({"Website": site + "/good", "Instagram": "@solesupremacy", "Phone": "(408) 800-4950",
                       "Email": "", "Notes": ""})
    assert changes["Web Status"] == "ok"
    assert changes["IG Status"] == "ok (on website)" and changes["Phone Status"] == "ok (on website)"
    assert changes["Email"] == "hello@solesupremacy.com"
    assert "Hellstar" in changes["Notes"] and "Suggested Fixes" not in changes


def test_verify_suggests_instead_of_overwriting(site):
    changes = _verify({"Website": site + "/other", "Instagram": "@wronghandle", "Phone": "(408) 800-4950"})
    assert changes["IG Status"] == "mismatch"
    assert "Instagram" not in changes and "Phone" not in changes
    assert "@realhandle" in changes["Suggested Fixes"] and "(212) 334-9000" in changes["Suggested Fixes"]


def test_verify_fills_blanks_and_flags_dead_sites(site):
    filled = _verify({"Website": site + "/other", "Instagram": "", "Phone": ""})
    assert filled["Instagram"] == "@realhandle" and filled["Phone"] == "(212) 334-9000"
    dead = _verify({"Website": site + "/missing", "Instagram": "@x_store", "Phone": ""})
    assert dead["Web Status"] == "unreachable" and dead["IG Status"] == "unverified"
    assert "did not load" in dead["Suggested Fixes"]
    blank = _verify({"Website": site + "/blank", "Instagram": "@x_store", "Phone": "(408) 800-4950"})
    assert blank["Web Status"] == "ok" and blank["IG Status"] == "unverified"


def test_verify_job_saves_to_sheet_and_requalifies(client, ss, site):
    dashboard.rebuild_master()
    head = ss.tabs["MASTER DATABASE"][0]
    waste = next(r for r in ss.tabs["MASTER DATABASE"][1:] if r[0] == "Wasteland SF")
    waste[head.index("Website")] = site + "/waste"           # its site mentions Hellstar + streetwear
    for row in ss.tabs["MASTER DATABASE"][1:]:               # every other site would be a real request
        if row is not waste:
            row[head.index("Website")] = site + "/blank" if row[head.index("Website")] else ""
    dashboard.invalidate()

    result = dashboard.verify_master()
    assert result["checked"] >= 3 and result["websites_ok"] >= 1

    rows = {r["Store Name"]: r for r in dashboard.load_master(force=True)[0]}
    assert rows["Wasteland SF"]["IG Status"] == "ok (on website)"
    assert rows["Wasteland SF"]["Email"] == "hi@shopwasteland.com"
    assert "Hellstar" in rows["Wasteland SF"]["Notes"]
    assert rows["Wasteland SF"]["_bucket"] == "qualified"    # evidence from the site confirmed the fit
    assert rows["R H U D E"]["Web Status"] != "ok"           # rejected rows are not checked
    assert len(ss.tabs["MASTER DATABASE"][0]) == len(set(ss.tabs["MASTER DATABASE"][0]))
    assert client.get("/quality").status_code == 200


def test_verify_job_refuses_to_save_a_network_outage(client, ss, site):
    dashboard.rebuild_master()
    head = ss.tabs["MASTER DATABASE"][0]
    for row in ss.tabs["MASTER DATABASE"][1:]:
        row[head.index("Website")] = site + "/missing"       # every site "down"
    dashboard.invalidate()
    snapshot = [list(r) for r in ss.tabs["MASTER DATABASE"]]
    with pytest.raises(RuntimeError, match="network problem"):
        dashboard.verify_master()
    assert ss.tabs["MASTER DATABASE"] == snapshot


def test_backdoor_miami_is_held_out_and_not_a_retailer():
    tabs = {"EXISTING RETAILERS": [
        ["Store Name", "City", "State", "Website", "Instagram", "Email", "Phone", "First Order Date",
         "Last Order Date", "Reorder Status", "Notes"],
        ["HELLSTAR - Backdoor Miami", "Miami", "Florida", "https://backdoormia.com/collections/vendors?q=HELLSTAR",
         "@100", "", "1750677234", "", "", "Check In", ""]]}
    (rec,), _ = pipeline.build_master(tabs)
    assert rec["Carries Godspeed"] == "" and rec["Outreach Status"] == "Not Contacted"
    assert "excluded" in rec["Cleanup Flag"] and q.bucket(rec["Cleanup Flag"]) == "rejected"
