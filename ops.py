#!/usr/bin/env python3
"""
Remote control for the live dashboard — how a Claude Code session operates it.

The deployed dashboard holds the Google credentials and has open network
access; a Claude Code session has the repo. This script is the bridge: it calls
the dashboard's own API over HTTPS, so nothing has to run on anyone's laptop.

  python ops.py status                  # is it up, which build, headline numbers
  python ops.py export stores           # print a live tab as CSV (stores, outreach, orders, review, verification)
  python ops.py export review -o x.csv
  python ops.py leads --view qualified  # the cleaned, flagged leads view as CSV
  python ops.py sync --dry-run          # what syncing the leads file to STORES would change
  python ops.py sync                    # do it (never deletes rows)
  python ops.py verify [--limit N]      # run the live website / Instagram check and wait

Environment:
  GODSPEED_URL        default https://godspeed-dashboard.onrender.com
  GODSPEED_PASSWORD   only if DASHBOARD_PASSWORD is set on the server
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

BASE = os.environ.get("GODSPEED_URL", "https://godspeed-dashboard.onrender.com").rstrip("/")
AUTH = ("claude", os.environ["GODSPEED_PASSWORD"]) if os.environ.get("GODSPEED_PASSWORD") else None


def call(method: str, path: str, **kwargs):
    try:
        resp = requests.request(method, BASE + path, auth=AUTH, timeout=120, **kwargs)
    except requests.RequestException as exc:
        sys.exit(f"Could not reach {BASE}: {type(exc).__name__}: {exc}\n"
                 "In Claude Code on the web, the session's environment must allow this host.")
    if resp.status_code == 401:
        sys.exit("The dashboard wants a password: set GODSPEED_PASSWORD.")
    return resp


def run_job(name: str, **params) -> dict:
    resp = call("POST", "/api/job/start", json={"job": name, **params})
    if resp.status_code == 404:
        sys.exit("This build of the dashboard has no job API — the quality-layer code is not deployed yet.")
    body = resp.json()
    if not body.get("success"):
        sys.exit(f"Could not start {name}: {body.get('error')}")
    last = ""
    while True:
        time.sleep(3)
        status = call("GET", "/api/job/status").json()
        if status["message"] != last:
            last = status["message"]
            print(last, flush=True)
        if not status["running"]:
            if status.get("error"):
                sys.exit(f"{name} failed: {status['error']}")
            return status.get("result") or {}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    export = sub.add_parser("export")
    export.add_argument("tab", choices=["stores", "outreach", "orders", "review", "verification"])
    export.add_argument("-o", "--out")
    leads = sub.add_parser("leads")
    leads.add_argument("--view", default="qualified", choices=["qualified", "review", "rejected", "all"])
    leads.add_argument("-o", "--out")
    sync = sub.add_parser("sync")
    sync.add_argument("--dry-run", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--limit", type=int)
    args = parser.parse_args()

    if args.command == "status":
        health = call("GET", "/healthz")
        stats = call("GET", "/api/stats").json()
        print(json.dumps({"url": BASE,
                          "quality_layer_deployed": health.status_code == 200,
                          "sheets_error": stats.get("error"),
                          **{k: stats.get(k) for k in ("total", "qualified", "review", "rejected",
                                                       "retailers", "sent", "replied",
                                                       "verified_web", "verified_ig", "hidden_phones")}},
                         indent=2))
    elif args.command in ("export", "leads"):
        path = f"/api/export/{args.tab}.csv" if args.command == "export" else f"/export/leads.csv?view={args.view}"
        resp = call("GET", path)
        if resp.status_code != 200:
            sys.exit(f"{resp.status_code}: {resp.text[:300]}")
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="") as f:
                f.write(resp.text)
            print(f"{args.out}: {max(resp.text.count(chr(10)) - 1, 0)} rows")
        else:
            sys.stdout.write(resp.text)
    elif args.command == "sync":
        print(json.dumps(run_job("sync", dry_run=args.dry_run), indent=2))
    elif args.command == "verify":
        print(json.dumps(run_job("verify", limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
