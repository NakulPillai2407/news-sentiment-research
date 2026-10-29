"""
Step 1: download every Alpaca (Benzinga) news article in the study window, with its release time.

  export ALPACA_KEY="..."   ALPACA_SECRET="..."        # in your Terminal, never in a file or chat
  python research_intraday/01_pull_news.py              # resumable: just run it again if it stops

Writes data/news_raw.csv (id, created_at, headline, summary, symbols, source). Takes roughly 15-40 minutes.
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

URL = "https://data.alpaca.markets/v1beta1/news"
START = "2024-01-01T00:00:00Z"
END = "2026-09-30T23:59:59Z"
DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)
OUT = DATA / "news_raw.csv"
STATE = DATA / "_news_state.json"
COLS = ["id", "created_at", "headline", "summary", "symbols", "source"]


def get(session, params):
    for attempt in range(8):
        r = session.get(URL, params=params, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (401, 403):
            sys.exit(f"Alpaca refused the request ({r.status_code}): {r.text[:200]}\nCheck ALPACA_KEY / ALPACA_SECRET and that your account has market-data access.")
        if r.status_code == 429:
            time.sleep(20 + 10 * attempt)
        elif r.status_code >= 500:
            time.sleep(5 + 5 * attempt)
        else:
            return {"_error": r.status_code, "_text": r.text[:200]}
    sys.exit("Too many failures; run the script again to resume.")


def main():
    key, sec = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
    if not key or not sec:
        sys.exit("Set ALPACA_KEY and ALPACA_SECRET in this Terminal first (see the top of this file).")
    s = requests.Session()
    s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})

    state = json.load(open(STATE)) if STATE.exists() else {"last_created_at": START, "page_token": None, "n": 0}
    seen = set()
    if OUT.exists():
        with open(OUT, newline="", encoding="utf-8") as f:
            seen = {row["id"] for row in csv.DictReader(f)}
    new_file = not OUT.exists()
    out = open(OUT, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(out, fieldnames=COLS)
    if new_file:
        w.writeheader()

    token, start, pages = state["page_token"], state["last_created_at"], 0
    while True:
        params = {"start": start, "end": END, "limit": 50, "sort": "asc", "include_content": "false"}
        if token:
            params["page_token"] = token
        js = get(s, params)
        if "_error" in js:                       # a stale page token: restart from the last article time instead
            if token:
                token = None
                continue
            sys.exit(f"API error {js['_error']}: {js['_text']}")
        items = js.get("news", [])
        for a in items:
            if str(a["id"]) in seen:
                continue
            seen.add(str(a["id"]))
            w.writerow({"id": a["id"], "created_at": a["created_at"], "headline": a.get("headline", ""),
                        "summary": a.get("summary", ""), "symbols": "|".join(a.get("symbols", [])), "source": a.get("source", "")})
            state["n"] += 1
        if items:
            state["last_created_at"] = items[-1]["created_at"]
        token = js.get("next_page_token")
        state["page_token"] = token
        out.flush()
        json.dump(state, open(STATE, "w"))
        pages += 1
        if pages % 20 == 0:
            print(f"  {state['n']:,} articles, now at {state['last_created_at']}", flush=True)
        if not token:
            break
        time.sleep(0.35)                         # stay well under 200 calls a minute
    out.close()
    print(f"DONE: {state['n']:,} articles up to {state['last_created_at']} -> {OUT}")


if __name__ == "__main__":
    main()
