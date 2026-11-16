"""End-to-end tests: quality rules, the STORES quality layer, the dashboard, live verification."""

import base64
import http.server
import threading

import pytest

import app as dashboard
import quality as q
import sheets
import stores
import verify
from fake_sheets import FakeSpreadsheet

STORES_HEADERS = ["store_name", "city", "market", "country", "website", "instagram", "email", "phone",
                  "pipeline_stage", "account_status", "last_order_date", "notes", "lead_score",
                  "priority_tier", "score_breakdown"]


def _store(name, city, market, website="", instagram="", email="", phone="", stage="Not Contacted",
           account="", notes="", score="30", tier="C-Tier"):
    return [name, city, market, "USA", website, instagram, email, phone, stage, account, "", notes,
            score, tier, ""]


STORES = [
    STORES_HEADERS,
    _store("Sole Supremacy", "San Jose", "CA", "https://solesupremacy.com/?srsltid=x", "@solesupremacy",
           "", "(408) 800-4950", score="72", tier="A-Tier"),
    _store("HYP Miami", "Miami (Brickell)", "FL", "hypmiami.com", "@hypmiami", stage="New Lead",
           notes="Premium streetwear - Chrome Hearts/Fear of God", score="60", tier="B-Tier"),
    _store("Wasteland SF", "San Francisco", "California", "https://shopwasteland.com", "@shopwasteland"),
    _store("R H U D E", "Miami", "Florida", "https://rh-ude.com/", "@rhude", "", "1613580349"),
    _store("Supreme Sets Up Shop in Miami", "Miami", "Florida",
           "https://hypebeast.com/2025/4/supreme-miami-store-opening-info", "@hypebeast",
           "app-store-en@2x.png", "3702846231", score="80", tier="A-Tier"),
    _store("LUXE MIAMI (@luxe.mia) · Coral Gables, FL", "Coral Gables", "Florida",
           "https://www.instagram.com/luxe.mia/?hl=en", "@font", "", "1037486289"),
    _store("Shop Hellstar clothing | The Attic Streetwear", "Austin", "Texas",
           "https://www.theatticstreetwear.com/hellstar", "@theatticstreetwear", "", "1037486289", score="50"),
    _store("Shop Hellstar clothing | The Attic Streetwear", "Dallas", "Texas",
           "https://www.theatticstreetwear.com/hellstar", "@theatticstreetwear", "", "1037486289", score="40"),
    _store("Riverbend Marketplace - Ft Lauderdale", "Fort Lauderdale", "Florida",
           "https://locations.dtlr.com/fl/ftlauderdale/riverbend-marketplace.html", "@dtlrofficial",
           "custserv@dtlr.com", "1037486289"),
    _store("House of Drip", "Detroit", "Michigan", "https://houseofdripmi.com/", "@layer",
           "john.doe@email.com", "1037486289"),
    _store("Broken Chains", "Medellín", "Colombia", "", "@brokenchains", "", "", stage="Won",
           account="Active", notes="Live account"),
    _store("HELLSTAR - Backdoor Miami", "Miami", "Florida", "https://backdoormia.com/collections/vendors",
           "@100", "", "1750677234"),
]
STORES[11][3] = "Colombia"


def workbook():
    return FakeSpreadsheet({
        "STORES": STORES, "OUTREACH_LOG": [dashboard.OUTREACH_HEADERS],
        "ORDERS": [["order_id", "store_name", "order_date", "order_total", "commission_amount",
                    "commission_status"],
                   ["ORD-0001", "Broken Chains", "2026-05-01", "5210", "521", "Pending"]],
    })


@pytest.fixture
def ss():
    book = workbook()
    sheets.use_spreadsheet(book)
    dashboard._cache.update(at=0.0, data=None)
    return book


@pytest.fixture
def client(ss):
    dashboard.app.config["TESTING"] = True
    return dashboard.app.test_client()


def by_name():
    return {s["Store Name"]: s for s in dashboard.load_data(force=True)["stores"]}


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


# ── quality layer over STORES ────────────────────────────────────────────────

def test_junk_contact_values_are_hidden_not_deleted(client, ss):
    before = [list(r) for r in ss.tabs["STORES"]]
    rows = by_name()

    sole = rows["Sole Supremacy"]
    assert sole["Phone"] == "(408) 800-4950" and sole["_bucket"] == "qualified"
    assert sole["Website"] == "https://solesupremacy.com/" and sole["State"] == "CA"

    luxe = rows["LUXE MIAMI"]                              # Instagram page title -> store + handle
    assert luxe["Instagram"] == "@luxe.mia" and luxe["Website"] == "" and luxe["Phone"] == ""
    assert luxe["_name"].startswith("LUXE MIAMI (@luxe.mia)")

    drip = rows["House of Drip"]
    assert (drip["Instagram"], drip["Email"], drip["Phone"]) == ("", "", "")
    assert any("fake phone" in note for note in drip["_cleaning"])

    assert rows["HYP Miami"]["Website"] == "https://hypmiami.com"
    assert rows["Wasteland SF"]["State"] == "CA"
    assert ss.tabs["STORES"] == before                     # the sheet itself is untouched
    assert not any(c.startswith(("update", "append", "clear", "add")) for c in ss.calls)


def test_flags_and_buckets(client):
    rows = by_name()
    assert rows["HYP Miami"]["_bucket"] == "qualified"
    assert rows["Wasteland SF"]["_bucket"] == "review"
    assert "mono-brand" in rows["R H U D E"]["Cleanup Flag"]
    assert "not-a-store" in rows["Supreme Sets Up Shop in Miami"]["Cleanup Flag"]
    assert "chain" in rows["Riverbend Marketplace - Ft Lauderdale"]["Cleanup Flag"]
    assert "excluded" in rows["Backdoor Miami"]["Cleanup Flag"]
    attic = [s for s in dashboard.load_data()["stores"] if s["Store Name"] == "The Attic Streetwear"]
    assert sorted(s["_bucket"] for s in attic) == ["qualified", "rejected"]   # one store, listed twice
    dup = next(s for s in attic if s["_bucket"] == "rejected")
    assert dup["City"] == "Dallas" and "duplicate" in dup["Cleanup Flag"]     # the better-scored row stays


# ── dashboard ────────────────────────────────────────────────────────────────

def test_pages_render(client):
    for path in ("/", "/leads", "/leads?view=review", "/leads?view=rejected&q=rhude", "/leads?view=all&page=9",
                 "/leads?contact=problem&tier=A-Tier&state=FL&status=pitched", "/retailers", "/outreach",
                 "/orders", "/quality", "/add-store", "/scraper", "/export/leads.csv", "/healthz"):
        assert client.get(path).status_code == 200, path
    leads = client.get("/leads").data.decode()
    assert "Sole Supremacy" in leads and "R H U D E" not in leads and "Riverbend" not in leads
    assert "Broken Chains" not in leads                    # customers live on Retailers
    assert "Broken Chains" in client.get("/retailers").data.decode()
    assert "$5,210" in client.get("/orders").data.decode()
    stats = client.get("/api/stats").json
    assert stats["retailers"] == 1 and stats["total"] == 12 and stats["leads"] == 11
    assert stats["qualified"] + stats["review"] + stats["rejected"] == stats["leads"]


def test_sheets_error_is_shown_not_raised(client, monkeypatch):
    def boom():
        raise RuntimeError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(sheets, "open_spreadsheet", boom)
    page = client.get("/")
    assert page.status_code == 200 and b"invalid_grant" in page.data
    assert client.get("/leads").status_code == 200
    assert client.post("/api/send-pitch", json={"store_name": "Sole Supremacy"}).status_code == 503


def test_pitch_logs_event_and_moves_stage(client, ss):
    sole = by_name()["Sole Supremacy"]
    res = client.post("/api/send-pitch", json={"row": sole["_row"], "store_name": "Sole Supremacy",
                                               "channel": "Email", "message": "hi"})
    assert res.json["success"]
    log = ss.tabs["OUTREACH_LOG"]
    entry = dict(zip(log[0], log[-1]))
    assert (entry["outreach_id"], entry["store_name"], entry["status"], entry["direction"]) == \
        ("OUT-00001", "Sole Supremacy", "Sent", "Outbound")
    assert ss.tabs["STORES"][sole["_row"] - 1][STORES_HEADERS.index("pipeline_stage")] == "Contacted"
    assert by_name()["Sole Supremacy"]["Outreach Status"] == "Pitched"

    # a draft is logged but does not move the stage; the v2 name-only payload still works
    hyp = by_name()["HYP Miami"]
    assert client.post("/api/send-pitch", json={"store_name": "HYP Miami", "status": "Drafted"}).json["success"]
    assert ss.tabs["STORES"][hyp["_row"] - 1][STORES_HEADERS.index("pipeline_stage")] == "New Lead"
    assert ss.tabs["OUTREACH_LOG"][-1][0] == "OUT-00002"
    assert client.post("/api/send-pitch", json={"row": 2, "store_name": "Wrong Name"}).status_code == 404


def test_bulk_pitch_uses_sheet_names(client, ss):
    luxe = by_name()["LUXE MIAMI"]
    res = client.post("/api/bulk-pitch", json={"stores": [{"row": luxe["_row"], "name": "LUXE MIAMI"}]})
    assert res.json["count"] == 1
    assert ss.tabs["OUTREACH_LOG"][-1][2] == "LUXE MIAMI (@luxe.mia) · Coral Gables, FL"


def test_review_decisions_survive_a_stores_resync(client, ss):
    waste = by_name()["Wasteland SF"]
    assert client.post("/api/review", json={"row": waste["_row"], "store_name": "Wasteland SF",
                                            "decision": "approve"}).json["bucket"] == "qualified"
    sole = by_name()["Sole Supremacy"]
    client.post("/api/review", json={"row": sole["_row"], "store_name": "Sole Supremacy", "decision": "reject"})
    assert ss.tabs["REVIEW"][0] == sheets.REVIEW_HEADERS and len(ss.tabs["REVIEW"]) == 3

    ss.tabs["STORES"][1:] = reversed(ss.tabs["STORES"][1:])    # sync_to_sheets rewrites STORES
    rows = by_name()
    assert rows["Wasteland SF"]["_bucket"] == "qualified" and rows["Sole Supremacy"]["_bucket"] == "rejected"

    sole = rows["Sole Supremacy"]
    client.post("/api/review", json={"row": sole["_row"], "store_name": "Sole Supremacy", "decision": "clear"})
    assert by_name()["Sole Supremacy"]["_bucket"] == "qualified"


def test_add_store_appends_to_stores(client, ss):
    res = client.post("/add-store", data={"name": "Test Kicks", "city": "Newark", "state": "New Jersey",
                                          "instagram": "https://instagram.com/TestKicks/",
                                          "phone": "973 482 1100", "website": "testkicks.com", "brands": "Hellstar"})
    assert res.status_code == 302
    row = dict(zip(ss.tabs["STORES"][0], ss.tabs["STORES"][-1]))
    assert (row["instagram"], row["phone"], row["website"], row["market"], row["pipeline_stage"]) == \
        ("@testkicks", "(973) 482-1100", "https://testkicks.com", "NJ", "Qualified")
    assert by_name()["Test Kicks"]["_bucket"] == "qualified"


def test_password_gate(client, monkeypatch):
    monkeypatch.setattr(dashboard, "DASHBOARD_PASSWORD", "s3cret")
    assert client.get("/leads").status_code == 401
    assert client.get("/healthz").status_code == 200
    token = base64.b64encode(b"goldie:s3cret").decode()
    assert client.get("/", headers={"Authorization": "Basic " + token}).status_code == 200


def test_local_csv_dir_mode(tmp_path):
    import csv
    with open(tmp_path / "STORES.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(STORES)
    book = FakeSpreadsheet.from_csv_dir(str(tmp_path))
    assert book.tabs["STORES"][1][0] == "Sole Supremacy"


# ── live verification (against a local web server) ───────────────────────────

PAGES = {
    "/good": '<a href="https://www.instagram.com/solesupremacy/">IG</a> <a href="tel:+14088004950">call</a>'
             '<a href="mailto:hello@solesupremacy.com">mail</a> We stock Hellstar and Supreme sneakers.',
    "/other": '<a href="https://instagram.com/realhandle">IG</a> Call us at (212) 334-9000 today',
    "/blank": "<html><body>Welcome</body></html>",
    "/waste": '<a href="https://www.instagram.com/shopwasteland/">IG</a> <a href="mailto:hi@shopwasteland.com">'
              'mail</a> Call (415) 863-3150. Vintage and streetwear: Supreme, Stussy, Hellstar.',
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
    monkeypatch.setattr(q, "CHAIN_LOCATION_THRESHOLD", 999)   # every test store shares 127.0.0.1
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _verify(rec):
    import requests
    return verify.verify_record(rec, requests.Session())


def test_verify_confirms_matching_contact_info(site):
    found = _verify({"Website": site + "/good", "Instagram": "@solesupremacy", "Phone": "(408) 800-4950",
                     "Email": ""})
    assert found["web_status"] == "ok"
    assert found["ig_status"] == "ok (on website)" and found["phone_status"] == "ok (on website)"
    assert found["found_email"] == "hello@solesupremacy.com"
    assert "Hellstar" in found["site_mentions"] and found["suggested_fixes"] == ""


def test_verify_reports_disagreement(site):
    found = _verify({"Website": site + "/other", "Instagram": "@wronghandle", "Phone": "(408) 800-4950"})
    assert found["ig_status"] == "mismatch"
    assert found["found_instagram"] == "" and found["found_phone"] == ""
    assert "@realhandle" in found["suggested_fixes"] and "(212) 334-9000" in found["suggested_fixes"]


def test_verify_finds_blanks_and_dead_sites(site):
    found = _verify({"Website": site + "/other", "Instagram": "", "Phone": ""})
    assert found["found_instagram"] == "@realhandle" and found["found_phone"] == "(212) 334-9000"
    dead = _verify({"Website": site + "/missing", "Instagram": "@x_store", "Phone": ""})
    assert dead["web_status"] == "unreachable" and dead["ig_status"] == "unverified"
    assert "did not load" in dead["suggested_fixes"]
    blank = _verify({"Website": site + "/blank", "Instagram": "@x_store", "Phone": "(408) 800-4950"})
    assert blank["web_status"] == "ok" and blank["ig_status"] == "unverified"


def _point_sites(ss, site, mapping, default="/blank"):
    col = STORES_HEADERS.index("website")
    for row in ss.tabs["STORES"][1:]:
        if row[col] and "instagram.com" not in row[col]:
            row[col] = site + mapping.get(row[0], default)


def test_verify_job_writes_only_the_verification_tab(client, ss, site):
    _point_sites(ss, site, {"Wasteland SF": "/waste"})
    stores_before = [list(r) for r in ss.tabs["STORES"]]

    result = dashboard.verify_stores()
    assert result["checked"] >= 4 and result["websites_ok"] >= 3
    assert ss.tabs["STORES"] == stores_before
    assert ss.tabs["VERIFICATION"][0] == sheets.VERIFY_HEADERS

    waste = by_name()["Wasteland SF"]
    assert waste["IG Status"] == "ok (on website)"
    assert waste["Email"] == "hi@shopwasteland.com" and waste["Phone"] == "(415) 863-3150"
    assert sorted(waste["_filled"]) == ["Email", "Phone"]
    assert waste["_bucket"] == "qualified"                 # the site itself confirmed the fit
    assert "Backdoor" not in " ".join(r[0] for r in ss.tabs["VERIFICATION"])    # rejected rows are skipped

    # a second run keeps earlier results and does not treat found values as sheet values
    again = dashboard.verify_stores()
    assert again["checked"] == result["checked"]
    assert len(ss.tabs["VERIFICATION"]) == result["checked"] + 1
    assert sorted(by_name()["Wasteland SF"]["_filled"]) == ["Email", "Phone"]
    assert client.get("/quality").status_code == 200 and client.get("/leads").status_code == 200

    # once the sheet's value changes, the old check no longer applies
    row = next(r for r in ss.tabs["STORES"] if r[0] == "Wasteland SF")
    row[STORES_HEADERS.index("instagram")] = "@somethingelse"
    assert by_name()["Wasteland SF"]["IG Status"] == "format-ok"


def test_verify_job_refuses_to_save_a_network_outage(client, ss, site):
    _point_sites(ss, site, {}, default="/missing")         # every site "down"
    with pytest.raises(RuntimeError, match="network problem"):
        dashboard.verify_stores()
    assert "VERIFICATION" not in ss.tabs
