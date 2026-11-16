"""
Live verification of a store's website, Instagram and phone.

The store's own website is the source of truth: the page is fetched once and
searched for the Instagram profile it links to, the phone numbers it shows and
the brands it mentions. That answers "is this the right Instagram / phone?"
far more reliably than asking Instagram, which blocks most automated requests.

Findings (stored in the VERIFICATION tab, never written into STORES):
    web_status    ok | unreachable | (format-only statuses when not checked)
    ig_status     ok (on website) | mismatch | ok | not-found | unverified
    phone_status  ok (on website) | format-ok | invalid-format | empty
    found_*       what the website shows where the sheet is blank
    suggested_fixes   where the website disagrees with the sheet
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import requests

import quality as q

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 10
MAX_BYTES = 250_000       # the header, nav and footer are what we need; keeps memory flat
WEB_WORKERS = 6
IG_MIN_INTERVAL = 1.5

_IG_LINK_RE = re.compile(r"instagram\.com/([A-Za-z0-9._]{2,30})(?=[/?\"'\s<&#]|$)", re.I)
_TEL_RE = re.compile(r"tel:([+\d()\s.\-]{10,20})", re.I)
_PHONE_TEXT_RE = re.compile(r"(?<![\d.])\(?\b[2-9]\d{2}\)?[\s.\-]{1,2}[2-9]\d{2}[\s.\-]\d{4}\b(?!\d)")
_MAILTO_RE = re.compile(r"mailto:([^\"'?\s<>]+)", re.I)
_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]{0,2000}>")

SITE_EVIDENCE = [label for _, label, _ in q.BRAND_POINTS] + [
    "Godspeed", "Fear of God", "Essentials", "Off-White", "BAPE", "Amiri",
    "Chrome Hearts", "Stussy", "Palace", "Kith", "Yeezy", "Jordan",
    "streetwear", "sneakers", "consignment",
]


def fetch_site(url: str, session: requests.Session) -> dict:
    """GET the page. Returns status + what it says about Instagram / phone / brands."""
    out = {"status": "unreachable", "handles": [], "phones": [], "emails": [], "evidence": [], "code": None}
    try:
        resp = session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True,
                           headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        out["code"] = resp.status_code
        body = resp.raw.read(MAX_BYTES, decode_content=True).decode(resp.encoding or "utf-8", "replace")
        resp.close()
    except requests.RequestException as exc:
        out["error"] = type(exc).__name__
        return out
    except Exception as exc:                      # decoding / stream errors
        out["error"] = type(exc).__name__
        return out

    if resp.status_code in (404, 410) or resp.status_code >= 500:
        return out
    # 401/403/429 = the site exists but refuses bots; reachable, nothing to read.
    out["status"] = "ok"
    if resp.status_code >= 400:
        return out

    handles = []
    for m in _IG_LINK_RE.finditer(body):
        handle = q.normalize_instagram(m.group(1))
        if handle and handle not in handles:
            handles.append(handle)
    phones = []
    text = _TAG_RE.sub(" ", _BLOCK_RE.sub(" ", body))
    for raw in _TEL_RE.findall(body) + _PHONE_TEXT_RE.findall(text):
        digits = q.normalize_phone(raw)
        if digits and digits not in phones:
            phones.append(digits)
    emails = []
    for raw in _MAILTO_RE.findall(body):
        email = q.normalize_email(raw)
        if email and email not in emails:
            emails.append(email)
    text = text.lower()
    out["handles"] = handles[:5]
    out["phones"] = phones[:5]
    out["emails"] = emails[:3]
    out["evidence"] = [e for e in SITE_EVIDENCE
                       if re.search(r"(?<![a-z])" + re.escape(e.lower()) + r"(?![a-z])", text)][:8]
    return out


_ig_lock = threading.Lock()
_ig_last = [0.0]
_ig_blocked = [0]


def check_instagram(handle: str, session: requests.Session) -> str:
    """'ok' | 'not-found' | 'unverified' (Instagram refused to answer)."""
    if _ig_blocked[0] >= 5:                       # Instagram is walling us: stop asking
        return "unverified"
    with _ig_lock:
        wait = IG_MIN_INTERVAL - (time.monotonic() - _ig_last[0])
        if wait > 0:
            time.sleep(wait)
        _ig_last[0] = time.monotonic()
    try:
        resp = session.get(f"https://www.instagram.com/{handle}/", timeout=TIMEOUT,
                           allow_redirects=True, headers={"User-Agent": USER_AGENT})
    except requests.RequestException:
        return "unverified"
    if resp.status_code == 404:
        return "not-found"
    body = resp.text or ""
    if resp.status_code != 200 or "/accounts/login" in resp.url:
        _ig_blocked[0] += 1
        return "unverified"
    # A real profile page names the handle in its metadata; the login wall and
    # the "page isn't available" shell do not.
    if re.search(r"@" + re.escape(handle) + r"\b|\"username\":\"" + re.escape(handle) + "\"", body, re.I):
        _ig_blocked[0] = 0
        return "ok"
    if "page isn't available" in body.lower() or "page not found" in body.lower():
        return "not-found"
    _ig_blocked[0] += 1
    return "unverified"


def verify_record(rec: dict, session: requests.Session, check_ig: bool = True) -> dict:
    """
    Check one store. Returns findings; the store's row is not modified.

        web_status / ig_status / phone_status
        found_instagram / found_phone / found_email   what the site shows for a blank field
        site_mentions      brands / keywords seen on the site (evidence of fit)
        suggested_fixes    where the site disagrees with the sheet
    """
    out = {"web_status": "", "ig_status": "", "phone_status": "", "found_instagram": "",
           "found_phone": "", "found_email": "", "site_mentions": "", "suggested_fixes": ""}
    suggestions: list[str] = []
    handle = q.normalize_instagram(rec.get("Instagram"))
    phone = q.normalize_phone(rec.get("Phone"))
    site = None

    web_fmt = q.website_status(rec.get("Website"))
    if web_fmt == "format-ok":
        site = fetch_site(q.normalize_website(rec["Website"]), session)
        out["web_status"] = site["status"]
    else:
        out["web_status"] = web_fmt
    live = bool(site and site["status"] == "ok")

    # Instagram
    if live and site["handles"]:
        if handle and handle in site["handles"]:
            out["ig_status"] = "ok (on website)"
        elif handle:
            out["ig_status"] = "mismatch"
            suggestions.append(f"Instagram: website links @{site['handles'][0]}, sheet has @{handle}")
        elif len(site["handles"]) == 1:
            out["found_instagram"] = "@" + site["handles"][0]
            out["ig_status"] = "ok (on website)"
    if not out["ig_status"]:
        if handle:
            out["ig_status"] = check_instagram(handle, session) if check_ig else "unverified"
        else:
            out["ig_status"] = q.instagram_status(rec.get("Instagram"))

    # Phone
    if live and site["phones"]:
        if phone and phone in site["phones"]:
            out["phone_status"] = "ok (on website)"
        elif phone:
            out["phone_status"] = "format-ok"
            suggestions.append(f"Phone: website shows {q.format_phone(site['phones'][0])}, "
                               f"sheet has {q.format_phone(phone)}")
        elif not q.s(rec.get("Phone")) and len(site["phones"]) == 1:
            out["found_phone"] = q.format_phone(site["phones"][0])
            out["phone_status"] = "ok (on website)"
    if not out["phone_status"]:
        out["phone_status"] = q.phone_status(rec.get("Phone"))

    if live:
        if not q.s(rec.get("Email")) and site["emails"]:
            out["found_email"] = site["emails"][0]
        out["site_mentions"] = ", ".join(site["evidence"])
    if site and site["status"] == "unreachable":
        suggestions.append("Website did not load — check the URL")
    out["suggested_fixes"] = "; ".join(suggestions)
    return out


def verify_all(records: list[dict],
               progress: Optional[Callable[[int, int], None]] = None,
               should_stop: Optional[Callable[[], bool]] = None,
               check_ig: bool = True) -> dict[int, dict]:
    """Verify many records in parallel. Returns {index: findings}."""
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=WEB_WORKERS, pool_maxsize=WEB_WORKERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _ig_blocked[0] = 0
    results: dict[int, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=WEB_WORKERS) as pool:
        futures = {pool.submit(verify_record, rec, session, check_ig): i
                   for i, rec in enumerate(records)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = {}
            done += 1
            if progress:
                progress(done, len(records))
            if should_stop and should_stop():
                for f in futures:
                    f.cancel()
                break
    return results
