"""
Download adjusted closes for the drawn universe (and ^GSPC) from Yahoo Finance.

  pip install yfinance            # one-off, in the project's .venv
  python research/download_prices.py

Takes the draw order in data/universe.json and keeps the first 50 tickers with usable prices
(a ticker is skipped only if Yahoo has no/too little price history for the study window; this is
decided by data availability, not by returns). Writes data/adj_close_clean.csv and data/sp500.csv,
moving the old 56-stock files to data/_superseded_prices/.
"""
import json
import shutil
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA = Path(__file__).resolve().parent / "data"
info = json.load(open(DATA / "universe.json"))
order = info["draw_order"]
start = (pd.Period(info["window_start"]) - 8).start_time.strftime("%Y-%m-%d")    # ~8 months before: beta window
end = (pd.Period(info["window_end"]) + 2).end_time.strftime("%Y-%m-%d")           # buffer for the 3-day hold
print(f"Downloading {len(order)} tickers, {start} to {end}")

px = yf.download(order + ["^GSPC"], start=start, end=end, auto_adjust=True, progress=False)["Close"]
px.index = pd.to_datetime(px.index).tz_localize(None)
px.index.name = "Date"

w0, w1 = pd.Period(info["window_start"]).start_time, pd.Period(info["window_end"]).end_time
in_w = px.loc[w0:w1]
good, bad = [], []
for t in order:
    ok = t in px and in_w[t].notna().mean() >= 0.98 and px[t].loc[:w0].notna().sum() >= 100
    (good if ok else bad).append(t)
final = good[: info["n_universe"]]
print(f"Usable: {len(good)}; skipped (no/short Yahoo history): {bad}")
print(f"Final universe ({len(final)}): {', '.join(sorted(final))}")

old = DATA / "_superseded_prices"
old.mkdir(exist_ok=True)
for f in ("adj_close_clean.csv", "sp500.csv"):
    if (DATA / f).exists() and not (old / f).exists():
        shutil.move(DATA / f, old / f)

px[sorted(final)].ffill(limit=3).to_csv(DATA / "adj_close_clean.csv")
px[["^GSPC"]].ffill(limit=3).to_csv(DATA / "sp500.csv")
info["final_universe"] = sorted(final)
info["skipped_no_prices"] = bad
json.dump(info, open(DATA / "universe.json", "w"), indent=2)
print("Wrote adj_close_clean.csv, sp500.csv and updated universe.json")
