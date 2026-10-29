"""
Shrink the 23 GB FNSPID Nasdaq file and pick the study universe.

Run from the project's .venv (works in the Terminal; the file is far too big for a small VM):

  python research/select_universe.py extract   # ONE pass over the 23 GB file -> data/news_slim.csv.gz (2020+, 4 columns)
  python research/select_universe.py select    # slim file -> random universe -> data/news_universe_raw.csv.gz

After `select` you can delete nasdaq_exteral_data.csv.

The universe rule is locked in PARAMETERS.md (Deviation 4) and uses only news counts and a fixed seed:
no price or return is looked at. Nothing here reads prices.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "nasdaq_exteral_data.csv"
SLIM = DATA / "news_slim.csv.gz"
OUT = DATA / "news_universe_raw.csv.gz"
INFO = DATA / "universe.json"

# --- locked in PARAMETERS.md, Deviation 4 ---
SEED = 2026
N_UNIVERSE = 50          # final size
N_DRAW = 80              # drawn in random order; extras replace tickers with no usable prices (in order)
WINDOW_MONTHS = 36
MIN_MONTHS_WITH_NEWS = 30   # of the 36 window months
MIN_ARTICLES_IN_WINDOW = 300
ROUNDUP_MIN_TICKERS = 3     # same headline on >= 3 different tickers on one day (across ALL tickers in the file)
KEEP_FROM_YEAR = "2020"
COLS = ["Date", "Stock_symbol", "Article_title", "Lsa_summary"]


def extract(budget_s=150):
    """One resumable pass over the big file. Stops after ~budget_s seconds and saves the byte offset of the next
    record in data/_extract_state.json; run it again to continue (it says DONE at the end of the file)."""
    import csv, gzip, io, time
    csv.field_size_limit(50_000_000)
    state_f = DATA / "_extract_state.json"
    state = json.load(open(state_f)) if state_f.exists() else {"offset": 0, "valid": 0, "kept": 0, "done": False}
    if state["done"]:
        print("Already DONE:", state); return
    if state["offset"] == 0 and SLIM.exists():
        SLIM.unlink()
    t0 = time.time()
    f = open(RAW, "rb")
    header = f.readline().decode("utf-8", "replace")
    idx = {n: i for i, n in enumerate(next(csv.reader([header])))}
    ii = [idx[c] for c in COLS]
    f.seek(max(state["offset"], len(header.encode())))
    pos = [f.tell()]

    def lines():
        for raw in f:
            pos[0] += len(raw)
            yield raw.decode("utf-8", "replace")

    out = gzip.open(SLIM, "ab")
    txt = io.TextIOWrapper(out, encoding="utf-8", newline="")
    w = csv.writer(txt)
    if state["offset"] == 0:
        w.writerow(COLS)
    rd = csv.reader(lines())
    finished = True
    while True:
        try:
            row = next(rd)
        except StopIteration:
            break
        except csv.Error:
            state["offset"] = pos[0]; continue
        state["offset"] = pos[0]
        if len(row) <= max(ii) or not row[ii[0]] or not row[ii[1]] or not row[ii[2]]:
            continue
        state["valid"] += 1
        if row[ii[0]][:4] >= KEEP_FROM_YEAR:
            w.writerow([row[i] for i in ii]); state["kept"] += 1
        if state["valid"] % 20000 == 0 and time.time() - t0 > budget_s:
            finished = False; break
    txt.flush(); txt.close()
    state["done"] = finished
    json.dump(state, open(state_f, "w"))
    pct = 100 * state["offset"] / RAW.stat().st_size
    print(("DONE" if finished else "PAUSED") + f": {pct:.1f}% of file, {state['valid']:,} valid rows, {state['kept']:,} kept")


def select():
    df = pd.read_csv(SLIM, dtype=str)
    df["Stock_symbol"] = df["Stock_symbol"].str.upper().str.strip()
    df["ts"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"]).drop_duplicates(["Stock_symbol", "ts", "Article_title"])
    n_before = len(df)

    # Multi-stock roundups: same headline on >= 3 different tickers on one calendar day (all tickers in the file).
    day = df["ts"].dt.strftime("%Y-%m-%d")
    title = df["Article_title"].str.strip().str.lower()
    shared = df.groupby([day, title])["Stock_symbol"].transform("nunique")
    n_roundup = int((shared >= ROUNDUP_MIN_TICKERS).sum())
    df = df[shared < ROUNDUP_MIN_TICKERS]

    # Window: last 36 full calendar months (a half-finished final month is excluded)
    month = df["ts"].dt.tz_localize(None).dt.to_period("M")
    final = month.max()
    if df["ts"].max().tz_localize(None) < final.end_time.normalize() - pd.Timedelta(days=3):
        end_m = final - 1
    else:
        end_m = final
    start_m = end_m - (WINDOW_MONTHS - 1)
    inwin = (month >= start_m) & (month <= end_m)
    w = df[inwin]
    wm = month[inwin]

    months_with_news = w.assign(m=wm).groupby("Stock_symbol")["m"].nunique()
    n_articles = w.groupby("Stock_symbol").size()
    stats = pd.DataFrame({"months_with_news": months_with_news, "articles": n_articles}).fillna(0)
    eligible = stats[(stats.months_with_news >= MIN_MONTHS_WITH_NEWS) & (stats.articles >= MIN_ARTICLES_IN_WINDOW)]
    eligible_list = sorted(eligible.index)
    rng = np.random.default_rng(SEED)
    order = list(rng.permutation(eligible_list))[:N_DRAW]

    keep = df[df["Stock_symbol"].isin(order)][COLS]
    keep.to_csv(OUT, index=False, compression="gzip")
    stats.sort_values("articles", ascending=False).to_csv(DATA / "_universe_candidate_stats.csv")
    info = {
        "seed": SEED, "n_universe": N_UNIVERSE, "window_start": str(start_m), "window_end": str(end_m),
        "n_tickers_in_file": int(stats.shape[0]), "n_eligible": len(eligible_list),
        "draw_order": [str(t) for t in order],
        "rows_before_roundup_removal": n_before, "roundup_rows_removed": n_roundup,
        "rows_kept_in_universe_file": int(len(keep)),
    }
    json.dump(info, open(INFO, "w"), indent=2)
    print(json.dumps({k: v for k, v in info.items() if k != "draw_order"}, indent=2))
    print("First 50 of the draw order:", ", ".join(order[:N_UNIVERSE]))
    print(f"\nWrote {OUT} and {INFO}. You can now delete {RAW.name} and {SLIM.name}.")


if __name__ == "__main__":
    {"extract": extract, "select": select}[sys.argv[1] if len(sys.argv) > 1 else "extract"]()
