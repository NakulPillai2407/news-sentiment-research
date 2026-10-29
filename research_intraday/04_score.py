"""
Step 4: score every kept headline for the final 50 tickers with FinBERT (P(pos) - P(neg)) and VADER (compound).

  python research_intraday/04_score.py            # resumable: finished blocks are cached, just run it again if it stops

Needs no Alpaca keys and never touches prices or returns. Headline only (PARAMETERS.md, Cleaning).
Reads data/universe_final.json and data/news_universe.csv; keeps only article-ticker rows that
  - belong to one of the 50 final tickers,
  - tag at most 2 tickers (roundup filter), and
  - were released Mon-Fri 09:30:00-15:58:59 New York (regular-hours filter, Deviation 1).
(02_select_universe.py already applied the last two; they are re-checked here so a stale file cannot slip through.)

Scoring code is reused from research/data_pipeline.py (FinBERT block cache on mps/cuda/cpu, VADER). That module's cache
folder is pointed at THIS study's data/ folder so Study 1's cached scores can never be picked up, and cache file names
carry a hash of the headline list so a changed list can never reuse old blocks.

Writes data/scores.csv.gz (id, symbol, created_at, headline, n_symbols, finbert, vader), data/scoring_log.json and
data/scoring_report.txt.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PIPELINE = HERE.parent / "research" / "data_pipeline.py"
MAX_SYMBOLS = 2
NY = "America/New_York"


def load_pipeline():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("study1_data_pipeline", PIPELINE)
    dp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dp)
    dp.DATA = DATA                       # finbert_scores() reads its cache folder from this global
    return dp


def kept_rows():
    tickers = json.load(open(DATA / "universe_final.json"))["tickers"]
    assert len(tickers) == 50, f"expected 50 final tickers, found {len(tickers)}"
    df = pd.read_csv(DATA / "news_universe.csv", dtype={"id": str, "symbol": str, "headline": str})
    n0 = len(df)
    df = df[df["symbol"].isin(tickers)]
    n_final = len(df)
    df["n_symbols"] = df["n_symbols"].astype(int)
    df = df[df["n_symbols"] <= MAX_SYMBOLS]
    ts = pd.to_datetime(df["created_at"], utc=True)
    ny = ts.dt.tz_convert(NY)
    mins = ny.dt.hour * 60 + ny.dt.minute
    df = df[((mins >= 570) & (mins < 959) & (ny.dt.dayofweek < 5)).to_numpy()]
    df = df.dropna(subset=["headline"]).drop_duplicates(["id", "symbol"])
    df["headline"] = df["headline"].astype(str).str.strip()
    df = df[df["headline"].str.len() > 0]
    counts = {"rows_in_news_universe_csv": n0, "rows_for_final_50": n_final, "rows_after_filters": len(df)}
    return df[["id", "symbol", "created_at", "headline", "n_symbols"]].reset_index(drop=True), tickers, counts


def main(batch_size):
    t_all = time.time()
    dp = load_pipeline()
    df, tickers, counts = kept_rows()
    titles = sorted(df["headline"].unique())
    tag = "intraday_headline_" + hashlib.md5("\n".join(titles).encode()).hexdigest()[:8]
    print(f"{len(df):,} article-ticker rows, {len(titles):,} unique headlines, cache tag {tag}")

    fb, flog = dp.finbert_scores(titles, tag, dp.MAX_TOKENS_HEADLINE, batch_size)
    t0 = time.time()
    vd = dp.vader_scores(titles)
    vader_sec = round(time.time() - t0, 1)

    pos = df["headline"].map({t: i for i, t in enumerate(titles)}).to_numpy()
    df["finbert"], df["vader"] = fb[pos], vd[pos]
    df = df.sort_values(["created_at", "symbol"]).reset_index(drop=True)
    df.to_csv(DATA / "scores.csv.gz", index=False)

    log = {**counts, "unique_headlines": len(titles), "cache_tag": tag, "finbert": flog, "vader_seconds": vader_sec,
           "headline_only": True, "max_tokens": dp.MAX_TOKENS_HEADLINE, "total_seconds": round(time.time() - t_all, 1)}
    json.dump(log, open(DATA / "scoring_log.json", "w"), indent=2)
    report(df, tickers, log)


def report(df, tickers, log):
    ts = pd.to_datetime(df["created_at"], utc=True)
    holdout = (ts >= pd.Timestamp("2025-10-01", tz="UTC")).to_numpy()   # same split as PARAMETERS.md (in sample to 2025-09)

    def dist(x):
        return pd.Series({"n": len(x), "mean": x["finbert"].mean(), "share>=+0.5": (x["finbert"] >= 0.5).mean(),
                          "share<=-0.5": (x["finbert"] <= -0.5).mean(), "vader_mean": x["vader"].mean()})

    per = df.groupby("symbol").apply(dist, include_groups=False).reindex(tickers)
    per["n"] = per["n"].astype(int)
    out = []
    out.append(f"Row counts: {log['rows_in_news_universe_csv']:,} in news_universe.csv -> {log['rows_for_final_50']:,} for the final 50 -> "
               f"{log['rows_after_filters']:,} after roundup (<=2 tickers) and regular-hours filters; {log['unique_headlines']:,} unique headlines scored")
    out.append(f"FinBERT device {log['finbert']['device']}, {log['finbert']['texts']:,} texts; scored this run in {log['finbert']['seconds']}s "
               f"(0 means all blocks came from the cache); VADER {log['vader_seconds']}s")
    out.append("\nArticles scored per ticker, and FinBERT distribution by ticker (draw order):")
    out.append(per.round(3).to_string())
    out.append("\nFinBERT score distribution (all kept articles):")
    allrows = {"all": df, "in sample (to 2025-09)": df[~holdout], "holdout (2025-10 on)": df[holdout]}
    out.append(pd.DataFrame({k: dist(v) for k, v in allrows.items()}).T.round(3).to_string())
    q = df["finbert"].quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).round(3)
    out.append("\nFinBERT quantiles (1%,5%,25%,50%,75%,95%,99%): " + ", ".join(map(str, q.tolist())))
    out.append(f"VADER distribution: mean {df['vader'].mean():.3f}, share>=+0.5 {(df['vader'] >= 0.5).mean():.3f}, "
               f"share<=-0.5 {(df['vader'] <= -0.5).mean():.3f}, share exactly 0 {(df['vader'] == 0).mean():.3f}")
    sig = df["finbert"].abs() >= 0.5
    out.append(f"\nCorrelation FinBERT vs VADER: Pearson {df['finbert'].corr(df['vader']):.3f}, Spearman {df['finbert'].corr(df['vader'], method='spearman'):.3f} "
               f"(all rows); Pearson {df.loc[sig, 'finbert'].corr(df.loc[sig, 'vader']):.3f} on the {int(sig.sum()):,} rows with |FinBERT| >= 0.5")
    longs, shorts = df["finbert"] >= 0.5, df["finbert"] <= -0.5
    agree = (np.sign(df.loc[sig, "vader"]) == np.sign(df.loc[sig, "finbert"])).mean()
    out.append(f"Signals at the 0.5 threshold: {int(longs.sum()):,} long, {int(shorts.sum()):,} short; VADER has the same sign on {agree:.1%} of them")
    out.append(f"Headlines scored identically by FinBERT across different rows (same text, several tickers): "
               f"{int(df.duplicated('headline', keep=False).sum()):,} rows share a headline with another row")
    text = "\n".join(out)
    (DATA / "scoring_report.txt").write_text(text)
    print("\n" + text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=64)
    main(ap.parse_args().batch_size)
