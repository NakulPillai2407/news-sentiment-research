"""
Step 3: download Alpaca price bars for the drawn tickers (plus SPY) and fix the final 50-ticker universe.

  export ALPACA_KEY="..."   ALPACA_SECRET="..."        # in your Terminal, never in a file or chat
  python research_intraday/03_pull_bars.py --test       # one ticker, one month, nothing kept; must pass first
  python research_intraday/03_pull_bars.py              # full run, resumable: just run it again if it stops

What it does
  - Reads the draw order from data/universe.json, removes the tickers named in PARAMETERS.md Deviation 2 (no redraw),
    and walks down the list in order. SPY goes first (it is the market and defines the trading calendar).
  - For each ticker: 1-minute bars (IEX feed, split-adjusted) for the window, kept only if they start in regular hours
    (09:30 <= start < 16:00 New York, Mon-Fri), and daily bars (IEX) from 8 months before the window, used for beta
    and for the equal-weight buy-and-hold benchmark.
  - A ticker is accepted if its bars are complete enough (rules below), otherwise skipped with the reason recorded.
    Coverage looks at bar counts and dates only, never at prices or returns.
  - Stops as soon as 50 tickers are accepted, so the universe is exactly the first 50 with complete coverage.

Writes (data/): bars/<SYM>.parquet (zstd), daily/<SYM>.parquet (zstd), trading_days.csv, bars_manifest.json
(every processed ticker, accepted or skipped, with its coverage numbers) and, at the end, universe_final.json.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.alpaca.markets/v2/stocks"
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
BARS_DIR, DAILY_DIR = DATA / "bars", DATA / "daily"
MANIFEST, TEST_MARK = DATA / "bars_manifest.json", DATA / "_bars_test_ok.json"
NY = "America/New_York"

WINDOW_START, WINDOW_END = "2024-01-01", "2026-09-30"
DAILY_START = "2023-05-01"                       # 8 months before the window, for the 120-day beta
N_UNIVERSE = 50
EXCLUDED = ["FXI", "GOOGL", "VGK"]               # PARAMETERS.md Deviation 2: removed from the draw order, no redraw
PAUSE = 0.35                                     # seconds between calls: stays under 200 calls a minute

# "Complete coverage" (availability only; fixed before the first bar was downloaded). A ticker needs ALL of:
MIN_DAY_SHARE = 0.95      # at least one regular-hours bar on 95% of trading days (days on which SPY traded)
MIN_MEDIAN_FILL = 0.25    # median over trading days of (bars that day / 390 minutes) at least 25%; below this the price is mostly stale
EDGE_DAYS = 5             # at least one bar in the first and in the last 5 trading days of the window (not listed late / delisted early)
MIN_PRE_DAILY = 120       # at least 120 daily bars before the window start, so beta exists for the first event
MIN_SPY_BARS = 50         # a date counts as a trading day if SPY has this many regular-hours bars (drops holidays)
BARS_PER_DAY = 390


def api_get(session, url, params):
    for attempt in range(10):
        try:
            r = session.get(url, params=params, timeout=60)
        except requests.RequestException:
            time.sleep(5 + 5 * attempt)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (401, 403):
            sys.exit(f"Alpaca refused the request ({r.status_code}): {r.text[:200]}\nCheck ALPACA_KEY / ALPACA_SECRET and market-data access.")
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After") or 0) or 20 + 10 * attempt)
        elif r.status_code >= 500:
            time.sleep(5 + 5 * attempt)
        else:
            return {"_error": r.status_code, "_text": r.text[:200]}
    sys.exit("Too many failures; run the script again to resume.")


def fetch(session, sym, timeframe, start, end):
    """All bars for one symbol and timeframe, following page tokens. Returns (DataFrame, n_calls, error or None)."""
    params = {"timeframe": timeframe, "start": start, "end": end, "limit": 10000, "feed": "iex", "adjustment": "split", "sort": "asc"}
    rows, calls = [], 0
    while True:
        js = api_get(session, f"{BASE}/{sym}/bars", params)
        calls += 1
        if "_error" in js:
            return pd.DataFrame(), calls, f"api_error_{js['_error']}"
        rows.extend(js.get("bars") or [])
        token = js.get("next_page_token")
        time.sleep(PAUSE)
        if not token:
            break
        params["page_token"] = token
    return pd.DataFrame(rows), calls, None


def regular_hours(raw, first_day=WINDOW_START, last_day=WINDOW_END):
    """Keep minute bars whose START is 09:30 <= t < 16:00 New York on Mon-Fri, inside the window. Columns: t (UTC), o h l c v n."""
    cols = ["t", "o", "h", "l", "c", "v", "n"]
    if raw.empty:
        return pd.DataFrame(columns=cols)
    t = pd.to_datetime(raw["t"], utc=True)
    ny = t.dt.tz_convert(NY)
    mins = ny.dt.hour * 60 + ny.dt.minute
    day = ny.dt.normalize().dt.tz_localize(None)
    keep = (mins >= 570) & (mins < 960) & (ny.dt.dayofweek < 5) & (day >= pd.Timestamp(first_day)) & (day <= pd.Timestamp(last_day))
    out = raw.loc[keep, ["o", "h", "l", "c", "v", "n"]].copy()
    out.insert(0, "t", t[keep])
    return out.reset_index(drop=True)


def clean_daily(raw):
    if raw.empty:
        return pd.DataFrame(columns=["date", "o", "h", "l", "c", "v"])
    d = raw[["o", "h", "l", "c", "v"]].copy()
    d.insert(0, "date", pd.to_datetime(raw["t"], utc=True).dt.tz_convert(NY).dt.strftime("%Y-%m-%d"))
    return d.drop_duplicates("date").reset_index(drop=True)


def bars_per_day(bars):
    day = bars["t"].dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)
    return day.value_counts()


def trading_days_from_spy(spy):
    n = bars_per_day(spy)
    return pd.DatetimeIndex(sorted(n[n >= MIN_SPY_BARS].index))


def evaluate(bars, daily, days):
    """Coverage numbers and the list of reasons a ticker fails (empty list = accepted)."""
    pre = int((pd.to_datetime(daily["date"]) < pd.Timestamp(WINDOW_START)).sum()) if len(daily) else 0
    m = {"n_bars": int(len(bars)), "daily_bars_before_window": pre}
    if bars.empty:
        m.update(day_share=0.0, median_fill=0.0, bars_first_days=0, bars_last_days=0)
        return m, ["no_minute_bars"]
    n = bars_per_day(bars).reindex(days).fillna(0)
    m.update(day_share=round(float((n > 0).mean()), 4), median_fill=round(float((n / BARS_PER_DAY).median()), 4),
             bars_first_days=int(n.iloc[:EDGE_DAYS].sum()), bars_last_days=int(n.iloc[-EDGE_DAYS:].sum()))
    why = []
    if m["day_share"] < MIN_DAY_SHARE:
        why.append(f"bars on only {m['day_share']:.1%} of trading days (< {MIN_DAY_SHARE:.0%})")
    if m["median_fill"] < MIN_MEDIAN_FILL:
        why.append(f"sparse bars: median {m['median_fill']:.1%} of minutes filled (< {MIN_MEDIAN_FILL:.0%})")
    if m["bars_first_days"] == 0:
        why.append(f"no bars in the first {EDGE_DAYS} trading days of the window (listed late or symbol changed)")
    if m["bars_last_days"] == 0:
        why.append(f"no bars in the last {EDGE_DAYS} trading days of the window (delisted or symbol changed)")
    if pre < MIN_PRE_DAILY:
        why.append(f"only {pre} daily bars before the window (< {MIN_PRE_DAILY}, no beta for early events)")
    return m, why


def save_parquet(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    os.replace(tmp, path)


def save_json(obj, path):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def make_session():
    key, sec = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
    if not key or not sec:
        sys.exit("Set ALPACA_KEY and ALPACA_SECRET in this Terminal first (see the top of this file).")
    s = requests.Session()
    s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    return s


def draw_order():
    info = json.load(open(DATA / "universe.json"))
    return [t for t in info["draw_order"] if t not in EXCLUDED]


def run_test(symbol):
    """One ticker, January 2024 only. Writes nothing except a marker that the format checks passed."""
    s = make_session()
    sym = symbol or draw_order()[0]
    print(f"Test: {sym}, 1-minute bars 2024-01-01 to 2024-01-31 and daily bars from {DAILY_START}")
    t0 = time.time()
    raw, c1, e1 = fetch(s, sym, "1Min", "2024-01-01T00:00:00Z", "2024-02-01T00:00:00Z")
    draw, c2, e2 = fetch(s, sym, "1Day", f"{DAILY_START}T00:00:00Z", "2026-10-01T00:00:00Z")
    if e1 or e2:
        sys.exit(f"Test failed: {e1 or e2}")
    bars, daily = regular_hours(raw, "2024-01-01", "2024-01-31"), clean_daily(draw)
    ny = bars["t"].dt.tz_convert(NY)
    per_day = bars_per_day(bars)
    print(f"  API calls: {c1} minute + {c2} daily, {time.time() - t0:.1f}s")
    print(f"  raw minute rows {len(raw):,} -> regular hours {len(bars):,} ({len(raw) - len(bars):,} pre/post-market rows dropped)")
    print(f"  trading days with bars: {len(per_day)}; bars per day min/median/max: {per_day.min()}/{int(per_day.median())}/{per_day.max()}")
    print(f"  earliest start-of-day bar (NY): {ny.dt.strftime('%H:%M').groupby(ny.dt.date).min().min()}, latest bar start (NY): {ny.dt.strftime('%H:%M').max()}")
    raw_first = pd.to_datetime(raw["t"].iloc[0], utc=True)
    print(f"  first RAW row (any session):  {raw_first} UTC  =  {raw_first.tz_convert(NY)} New York   (bar START time)")
    print(f"  first REGULAR-HOURS row kept: {bars['t'].iloc[0]} UTC  =  {ny.iloc[0]} New York   (bar START time)")
    print(f"  bar columns: {list(bars.columns)}; open of first bar {bars['o'].iloc[0]}, close of last bar {bars['c'].iloc[-1]}")
    print(f"  daily bars {len(daily)} ({daily['date'].iloc[0]} to {daily['date'].iloc[-1]}); before window: {(daily['date'] < WINDOW_START).sum()}")
    ok = bool(len(bars) > 0 and ny.dt.hour.min() >= 9 and (ny.dt.hour * 60 + ny.dt.minute).max() < 960 and len(daily) > 0)
    print("  CHECKS PASSED" if ok else "  CHECKS FAILED: do not run the full download")
    if ok:
        save_json({"symbol": sym, "minute_rows": int(len(bars)), "daily_rows": int(len(daily)), "ok": True}, TEST_MARK)
    return 0 if ok else 1


def run_full():
    DATA.mkdir(exist_ok=True)
    s = make_session()
    manifest = json.load(open(MANIFEST)) if MANIFEST.exists() else {"tickers": {}}
    manifest["rules"] = {"excluded": EXCLUDED, "window": [WINDOW_START, WINDOW_END], "daily_start": DAILY_START, "feed": "iex", "adjustment": "split",
                         "min_day_share": MIN_DAY_SHARE, "min_median_fill": MIN_MEDIAN_FILL, "edge_days": EDGE_DAYS, "min_pre_daily": MIN_PRE_DAILY}
    calls = 0

    def download(sym):
        nonlocal calls
        raw, c1, e1 = fetch(s, sym, "1Min", f"{WINDOW_START}T00:00:00Z", "2026-10-01T00:00:00Z")
        draw, c2, e2 = fetch(s, sym, "1Day", f"{DAILY_START}T00:00:00Z", "2026-10-01T00:00:00Z")
        calls += c1 + c2
        return regular_hours(raw), clean_daily(draw), e1 or e2

    # SPY: the market and the trading calendar. It must be complete or nothing downstream makes sense.
    if not (BARS_DIR / "SPY.parquet").exists() or not (DAILY_DIR / "SPY.parquet").exists():
        print("SPY ...", flush=True)
        spy, spy_d, err = download("SPY")
        if err or spy.empty or spy_d.empty:
            sys.exit(f"SPY download failed ({err or 'no bars'}); cannot continue.")
        save_parquet(spy, BARS_DIR / "SPY.parquet")
        save_parquet(spy_d, DAILY_DIR / "SPY.parquet")
    spy = pd.read_parquet(BARS_DIR / "SPY.parquet")
    days = trading_days_from_spy(spy)
    pd.Series(days.strftime("%Y-%m-%d"), name="date").to_csv(DATA / "trading_days.csv", index=False)
    print(f"SPY ok: {len(spy):,} bars, {len(days)} trading days ({days[0].date()} to {days[-1].date()}); days with no SPY bars (holidays) are dropped")

    order = draw_order()
    accepted = [t for t in order if manifest["tickers"].get(t, {}).get("status") == "accepted"]
    for sym in order:
        if len(accepted) >= N_UNIVERSE:
            break
        if sym in manifest["tickers"]:
            continue
        t0 = time.time()
        bars, daily, err = download(sym)
        m, why = evaluate(bars, daily, days)
        if err:
            why = [err] + why
        if why:
            manifest["tickers"][sym] = {"status": "skipped", "reasons": why, **m}
        else:
            save_parquet(bars, BARS_DIR / f"{sym}.parquet")
            save_parquet(daily, DAILY_DIR / f"{sym}.parquet")
            manifest["tickers"][sym] = {"status": "accepted", "reasons": [], **m}
            accepted.append(sym)
        save_json(manifest, MANIFEST)
        verdict = "accepted" if not why else "SKIPPED: " + "; ".join(why)
        print(f"[{len(accepted):2d}/{N_UNIVERSE}] {sym:6s} {m['n_bars']:>8,} bars, days {m['day_share']:.1%}, fill {m['median_fill']:.1%}  {verdict}  ({time.time() - t0:.0f}s)", flush=True)

    skipped = {t: manifest["tickers"][t]["reasons"] for t in order if manifest["tickers"].get(t, {}).get("status") == "skipped"}
    final = {"excluded_by_deviation_2": EXCLUDED, "n_accepted": len(accepted), "tickers": accepted[:N_UNIVERSE],
             "skipped": skipped, "reserve_used": [t for t in accepted[:N_UNIVERSE] if order.index(t) >= N_UNIVERSE],
             "rules": manifest["rules"], "n_trading_days": int(len(days))}
    if len(accepted) >= N_UNIVERSE:
        save_json(final, DATA / "universe_final.json")
    print(f"\nAPI calls this run: {calls}")
    print(f"Accepted {len(accepted)} of {N_UNIVERSE} needed.")
    print(f"Skipped ({len(skipped)}):" + ("" if skipped else " none"))
    for t, w in skipped.items():
        print(f"  {t}: {'; '.join(w)}")
    if len(accepted) < N_UNIVERSE:
        print(f"\nWARNING: draw order exhausted with only {len(accepted)} tickers. Do not relax a rule; report this.")
        return 1
    print("Final universe (draw order):", ", ".join(accepted[:N_UNIVERSE]))
    print("Reserve tickers used:", ", ".join(final["reserve_used"]) or "none")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", nargs="?", const="", metavar="SYMBOL", help="one-ticker, one-month test (default: first ticker in the draw order)")
    ap.add_argument("--skip-test", action="store_true", help="run the full download without the passed-test marker")
    a = ap.parse_args()
    if a.test is not None:
        sys.exit(run_test(a.test or None))
    if not TEST_MARK.exists() and not a.skip_test:
        sys.exit("Run the one-ticker test first:  python research_intraday/03_pull_bars.py --test")
    sys.exit(run_full())


if __name__ == "__main__":
    main()
