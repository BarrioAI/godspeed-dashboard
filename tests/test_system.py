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

    # a second run has nothing left to do; --recheck does everything again and keeps one row per store
    again = dashboard.verify_stores()
    assert (again["checked"], again["already_verified"], again["remaining"]) == (0, result["checked"], 0)
    redo = dashboard.verify_stores(recheck=True)
    assert redo["checked"] == result["checked"]
    assert len(ss.tabs["VERIFICATION"]) == result["checked"] + 1
    assert sorted(by_name()["Wasteland SF"]["_filled"]) == ["Email", "Phone"]   # found values are not re-read as sheet values
    assert client.get("/quality").status_code == 200 and client.get("/leads").status_code == 200

    # once the sheet's value changes, the old check no longer applies
    row = next(r for r in ss.tabs["STORES"] if r[0] == "Wasteland SF")
    row[STORES_HEADERS.index("instagram")] = "@somethingelse"
    assert by_name()["Wasteland SF"]["IG Status"] == "format-ok"


def test_verify_job_refuses_to_save_a_network_outage(client, ss, site):
    _point_sites(ss, site, {}, default="/missing")         # every site "down"
    with pytest.raises(RuntimeError, match="network problem"):
        dashboard.verify_stores()
    assert "VERIFICATION" not in ss.tabs                   # the failed batch was not saved


# ── sync: leads file -> STORES ───────────────────────────────────────────────

LEADS_HEADER = ["Store Name", "City", "State", "Country", "Website", "Instagram", "Email", "Phone",
                "Carries Supreme", "Carries Hellstar", "Carries Godspeed", "Last Order Date",
                "Outreach Status", "Outreach Channel", "Notes", "Date Added", "Lead Score", "Priority Tier",
                "Brands Carried", "Score Reasons", "Score Breakdown"]


def _lead(name, city, state, website="", instagram="", phone="", score="40", tier="C-Tier"):
    row = dict.fromkeys(LEADS_HEADER, "")
    row.update({"Store Name": name, "City": city, "State": state, "Country": "USA", "Website": website,
                "Instagram": instagram, "Phone": phone, "Outreach Status": "Not Contacted",
                "Lead Score": score, "Priority Tier": tier})
    return row


@pytest.fixture
def leads_file(tmp_path, monkeypatch):
    import csv

    def write(rows):
        path = tmp_path / "leads.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEADS_HEADER)
            writer.writeheader()
            writer.writerows(rows)
        monkeypatch.setattr(dashboard, "REPO_LEADS_CSV", str(path))
    return write


def test_sync_updates_details_adds_stores_and_deletes_nothing(client, ss, leads_file):
    leads_file([
        _lead("Sole Supremacy", "San Jose", "CA", "https://solesupremacy.com/", "@solesupremacy",
              "(408) 800-4950", score="58", tier="B-Tier"),
        _lead("House of Drip", "Detroit", "Michigan", "https://houseofdripmi.com/"),     # junk scrubbed in the file
        _lead("New Kicks Boutique", "Oakland", "CA", "https://newkicks.com", "@newkicks"),
    ])
    client.post("/api/send-pitch", json={"store_name": "Sole Supremacy"})                # stage -> Contacted
    before = len(ss.tabs["STORES"])

    preview = dashboard.sync_stores_from_repo(dry_run=True)
    assert (preview["added"], preview["updated"]) == (1, 2) and len(ss.tabs["STORES"]) == before

    result = dashboard.sync_stores_from_repo()
    assert (result["added"], result["updated"], result["only_in_sheet_kept"]) == (1, 2, before - 3)
    assert len(ss.tabs["STORES"]) == before + 1                                          # nothing deleted

    head = ss.tabs["STORES"][0]
    sheet = {r[0]: dict(zip(head, r)) for r in ss.tabs["STORES"][1:]}
    assert sheet["Sole Supremacy"]["lead_score"] == "58"
    assert sheet["Sole Supremacy"]["pipeline_stage"] == "Contacted"                      # dashboard-owned column kept
    assert (sheet["House of Drip"]["instagram"], sheet["House of Drip"]["phone"]) == ("", "")
    assert sheet["New Kicks Boutique"]["pipeline_stage"] == "Not Contacted"
    assert sheet["Broken Chains"]["account_status"] == "Active"                          # not in the file: untouched

    assert dashboard.sync_stores_from_repo()["updated"] == 0                             # second run is a no-op
    assert by_name()["New Kicks Boutique"]["_bucket"] == "qualified"


def test_sync_matches_names_mangled_by_encoding(client, ss, leads_file):
    good = "Studios – HELLSTAR"
    ss.tabs["STORES"].append(_store(good.encode("utf-8").decode("latin-1"), "MedellÃ\xadn", "Colombia"))
    ss.tabs["STORES"].append(_store("Twin Kicks", "Reno", "NV", phone="1037486289"))
    ss.tabs["STORES"].append(_store("Twin Kicks", "Reno", "NV", phone="2147483647"))
    before = len(ss.tabs["STORES"])
    leads_file([_lead(good, "Medellín", "Colombia"), _lead("Twin Kicks", "Reno", "NV"),
                _lead("Twin Kicks", "Reno", "NV", instagram="@twinkicks")])
    result = dashboard.sync_stores_from_repo()
    assert result["added"] == 0 and len(ss.tabs["STORES"]) == before
    names = [r[0] for r in ss.tabs["STORES"]]
    assert good in names and ss.tabs["STORES"][names.index(good)][1] == "Medellín"       # spelling repaired
    twins = [r for r in ss.tabs["STORES"] if r[0] == "Twin Kicks"]
    assert [r[5] for r in twins] == ["", "@twinkicks"] and [r[7] for r in twins] == ["", ""]
    assert dashboard.sync_stores_from_repo()["updated"] == 0


def test_job_api_runs_sync_and_exports_tabs(client, ss, leads_file):
    import time
    leads_file([_lead("New Kicks Boutique", "Oakland", "CA", "https://newkicks.com", "@newkicks")])
    assert client.post("/api/job/start", json={"job": "nonsense"}).status_code == 400
    assert client.post("/api/job/start", json={"job": "sync", "dry_run": True}).json["success"]
    for _ in range(50):
        status = client.get("/api/job/status").json
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["name"] == "sync" and status["error"] is None and status["result"]["added"] == 1

    export = client.get("/api/export/stores.csv")
    assert export.status_code == 200 and export.data.decode().splitlines()[0].startswith("store_name,city,market")
    assert client.get("/api/export/review.csv").status_code == 200                       # empty tab is fine
    assert client.get("/api/export/secrets.csv").status_code == 404


def test_fix_leads_scrubs_contacts_and_keeps_rows(tmp_path):
    import csv
    import super_clean
    rows = [
        _lead("House of Drip", "Detroit", "Michigan", "https://houseofdripmi.com/?srsltid=x", "@layer", "9999999999"),
        _lead("LUXE MIAMI (@luxe.mia)", "Coral Gables", "Florida", "https://www.instagram.com/luxe.mia/?hl=en", "@font"),
        _lead("Sole Supremacy", "San Jose", "CA", "solesupremacy.com", "@SoleSupremacy", "408-800-4950"),
    ]
    for r in rows:
        r["Score Breakdown"] = "Contact:18/Brand:5/Market:5/Reach:10"
    path = tmp_path / "leads.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEADS_HEADER); w.writeheader(); w.writerows(rows)
    super_clean.fix_leads(str(path))
    out = {r["Store Name"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}
    assert len(out) == 3
    drip = out["House of Drip"]
    assert (drip["Website"], drip["Instagram"], drip["Phone"]) == ("https://houseofdripmi.com/", "", "")
    assert drip["Score Breakdown"] == "Contact:0/Brand:5/Market:5/Reach:0" and drip["Lead Score"] == "10"
    luxe = out["LUXE MIAMI (@luxe.mia)"]                                                  # name untouched
    assert (luxe["Website"], luxe["Instagram"]) == ("", "@luxe.mia")
    sole = out["Sole Supremacy"]
    assert (sole["Website"], sole["Instagram"], sole["Phone"]) == \
        ("https://solesupremacy.com", "@solesupremacy", "(408) 800-4950")


def test_verify_saves_as_it_goes_and_resumes(client, ss, site, monkeypatch):
    _point_sites(ss, site, {})
    monkeypatch.setattr(dashboard, "VERIFY_CHUNK", 3)
    # a run that is cut off after its first chunk keeps that chunk
    calls = {"n": 0}

    def stop_after_first_chunk():
        calls["n"] += 1
        return True

    first = dashboard.verify_stores(should_stop=stop_after_first_chunk)
    assert first["stopped"] and 1 <= first["checked"] <= 3
    saved = len(ss.tabs["VERIFICATION"]) - 1
    assert saved == first["checked"] and first["remaining"] > 0

    # batches (what `ops.py verify` does) pick up where it stopped, without repeats
    second = dashboard.verify_stores(limit=4)
    assert second["already_verified"] == saved and second["checked"] == 4
    rest = dashboard.verify_stores()
    assert rest["remaining"] == 0
    names = [r[0] for r in ss.tabs["VERIFICATION"][1:]]
    assert len(names) == len(set(names)) == saved + 4 + rest["checked"]
    assert dashboard.verify_stores()["checked"] == 0
    status = client.get("/api/job/status").json
    assert status["boot"]                                            # lets a caller detect a restart


def test_apply_verification_uses_only_the_stores_own_site(tmp_path, capsys):
    import csv
    import super_clean
    leads = [
        _lead("Hype24/7", "Atlanta", "GA", "https://hype2407.com/", "@hype2407", "(902) 999-9862"),      # wrong phone
        _lead("Coppra Miami", "Miami", "FL", "https://coppramiami.com/", "@coppra.us"),                  # wrong IG
        _lead("Sole Supremacy", "San Jose", "CA", "https://solesupremacy.com/"),                         # blanks
        _lead("Best Boutiques in Town", "Reno", "NV", "https://citymagazine.com/x"),                     # not its site
        _lead("Fresh Kicks", "Tulsa", "OK", "https://freshkicks.com/", "@freshkicks"),                   # platform IG
        _lead("Changed Since", "Boise", "ID", "https://changedsince.com/", "@changedsince", "(208) 344-1000"),
    ]
    for r in leads:
        r["Score Breakdown"] = "Contact:0/Brand:5/Market:5/Reach:0"
    path = tmp_path / "leads.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEADS_HEADER); w.writeheader(); w.writerows(leads)

    def check(name, city, website, instagram="", phone="", **found):
        row = dict.fromkeys(sheets.VERIFY_HEADERS, "")
        row.update(store_name=name, city=city, website=website, instagram=instagram, phone=phone, **found)
        return row

    checks = [
        check("Hype24/7", "Atlanta", "https://hype2407.com/", "@hype2407", "(902) 999-9862",
              suggested_fixes="Phone: website shows (470) 560-1388, sheet has (902) 999-9862"),
        check("Coppra Miami", "Miami", "https://coppramiami.com/", "@coppra.us",
              suggested_fixes="Instagram: website links @coppramiami, sheet has @coppra.us"),
        check("Sole Supremacy", "San Jose", "https://solesupremacy.com/", found_instagram="@solesupremacy",
              found_phone="(408) 800-4950", found_email="hello@solesupremacy.com"),
        check("Best Boutiques in Town", "Reno", "https://citymagazine.com/x", found_phone="(775) 322-1000"),
        check("Fresh Kicks", "Tulsa", "https://freshkicks.com/", "@freshkicks",
              suggested_fixes="Instagram: website links @shopify, sheet has @freshkicks"),
        check("Changed Since", "Boise", "https://changedsince.com/", "@changedsince", "(208) 999-0000",
              suggested_fixes="Phone: website shows (208) 555-0000, sheet has (208) 999-0000"),
    ]
    vpath = tmp_path / "verification.csv"
    with open(vpath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=sheets.VERIFY_HEADERS); w.writeheader(); w.writerows(checks)

    changes = tmp_path / "changes.csv"
    super_clean.apply_verification(str(vpath), str(path), str(changes))
    out = {r["Store Name"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}
    assert out["Hype24/7"]["Phone"] == "(470) 560-1388"
    assert out["Coppra Miami"]["Instagram"] == "@coppramiami"
    sole = out["Sole Supremacy"]
    assert (sole["Instagram"], sole["Phone"], sole["Email"]) == ("@solesupremacy", "(408) 800-4950", "hello@solesupremacy.com")
    assert sole["Score Breakdown"] == "Contact:30/Brand:5/Market:5/Reach:20" and sole["Lead Score"] == "60"
    assert out["Best Boutiques in Town"]["Phone"] == ""            # the page is not the store's own
    assert out["Fresh Kicks"]["Instagram"] == "@freshkicks"        # @shopify is not this store
    assert out["Changed Since"]["Phone"] == "(208) 344-1000"       # row edited after the check
    assert len(list(csv.DictReader(open(changes, encoding="utf-8")))) == 5
    assert len(out) == 6
