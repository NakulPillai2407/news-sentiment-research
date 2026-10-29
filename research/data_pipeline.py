"""Data pipeline: raw FNSPID news CSV -> filtered, windowed, FinBERT/VADER-scored news.

Run this ONCE on your Mac, in the Sentiment Signal project's virtual environment (it needs torch,
transformers and the FinBERT weights the live app already downloaded). Then open the notebook.

    cd news-sentiment-research
    source .venv/bin/activate
    python research/data_pipeline.py --raw research/data/news_universe_raw.csv.gz
    python research/data_pipeline.py --raw path/to.csv    # or any other FNSPID news file

Stage 1  stream the big CSV in chunks, keep only the 50-stock universe, dedupe.
Stage 2  choose the study window: the last 36 months ending at the last month where >= 40 of the
         50 tickers have news; the final 12 months are the out-of-sample holdout.
Stage 3  score each unique headline (and summary, if the file has one) with FinBERT
         (P(positive) - P(negative)) and VADER (compound). Resumable: scores are cached in blocks.

Outputs (in research/data/):
    news_scored.csv.gz   ticker, ts_utc, title, finbert, vader
    window.json          start / end / in_sample_end / holdout_start
    pipeline_log.json    row counts, coverage, scoring speed (used by the notebook's efficiency section)
    coverage.txt         human-readable coverage report
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# locked in PARAMETERS.md
WINDOW_MONTHS, HOLDOUT_MONTHS, MIN_TICKERS_FOR_MONTH = 36, 12, 40
FINBERT_MODEL = "ProsusAI/finbert"
MAX_TOKENS_HEADLINE, MAX_TOKENS_SUMMARY, BLOCK = 64, 128, 20_000

# Ticker symbols that changed or are the same company (PARAMETERS.md, Deviation 2)
ALIASES = {"FB": "META", "GOOG": "GOOGL"}
ROUNDUP_MIN_TICKERS = 3      # same headline on >= 3 universe stocks on one day = generic roundup (Deviation 3)

CANDIDATES = {
    "ts": ["date", "datetime", "published", "published_at", "timestamp", "time"],
    "title": ["article_title", "title", "headline"],
    "ticker": ["stock_symbol", "ticker", "symbol", "stock"],
    "summary": ["lsa_summary", "lsa_summarization", "summary", "textrank_summary"],   # optional
}


# ------------------------------------------------------------------ stage 1: filter
def detect_columns(cols):
    lower = {c.lower().strip(): c for c in cols}
    found = {}
    for key, names in CANDIDATES.items():
        for n in names:
            if n in lower:
                found[key] = lower[n]
                break
    missing = [k for k in ("ts", "title", "ticker") if k not in found]
    if missing:
        raise SystemExit(f"Could not find columns for {missing}. File columns: {list(cols)}")
    return found


def filter_news(raw_path, universe):
    uni = set(universe)
    cols = detect_columns(pd.read_csv(raw_path, nrows=0).columns)
    print("Columns used:", cols)
    kept, n_rows, n_kept = [], 0, 0
    for chunk in pd.read_csv(raw_path, usecols=list(dict.fromkeys(cols.values())), dtype=str,
                             chunksize=100_000, on_bad_lines="skip"):
        chunk = chunk.rename(columns={v: k for k, v in cols.items()})
        chunk = chunk.dropna(subset=["ticker", "ts", "title"])   # stray quote marks in article text can split lines
        n_rows += len(chunk)
        chunk["ticker"] = chunk["ticker"].str.upper().str.strip().replace(ALIASES)
        chunk = chunk[chunk["ticker"].isin(uni)]
        n_kept += len(chunk)
        kept.append(chunk)
        print(f"  read {n_rows:,} rows, kept {n_kept:,}", end="\r")
    print()
    df = pd.concat(kept, ignore_index=True)
    if "summary" not in df:
        df["summary"] = ""
    df["ts_utc"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_utc", "title"]).drop_duplicates(["ticker", "ts_utc", "title"])

    # Multi-stock roundups ("46 Stocks Moving In Friday's Mid-Day Session") are attached to every stock
    # they list and say nothing specific about any one of them. Drop a headline if the same title is on
    # >= ROUNDUP_MIN_TICKERS different universe stocks on the same calendar day (PARAMETERS.md, Deviation 3).
    day = df["ts_utc"].dt.strftime("%Y-%m-%d")
    shared = df.groupby([day, df["title"].str.strip().str.lower()])["ticker"].transform("nunique")
    n_roundup = int((shared >= ROUNDUP_MIN_TICKERS).sum())
    df = df[shared < ROUNDUP_MIN_TICKERS]
    return df[["ticker", "ts_utc", "title", "summary"]].sort_values("ts_utc"), n_rows, cols, n_roundup


# ------------------------------------------------------------------ stage 2: window
def choose_window(df):
    month = df["ts_utc"].dt.tz_localize(None).dt.to_period("M")
    cover = df.groupby(month)["ticker"].nunique()
    final = month.max()                                  # a half-finished last month is not a "full calendar month"
    if df["ts_utc"].max().tz_localize(None) < final.end_time.normalize() - pd.Timedelta(days=3):
        cover = cover.drop(final)
    ok = cover[cover >= MIN_TICKERS_FOR_MONTH]
    if ok.empty:
        raise SystemExit("No month has >= 40 tickers of news; see coverage.txt and report back.")
    end_m = ok.index.max()
    start_m = end_m - (WINDOW_MONTHS - 1)
    hold_m = end_m - (HOLDOUT_MONTHS - 1)
    window = {"start": str(start_m.start_time.date()), "end": str(end_m.end_time.date()),
              "holdout_start": str(hold_m.start_time.date()),
              "in_sample_end": str((hold_m.start_time - pd.Timedelta(days=1)).date())}
    return window, month.between(start_m, end_m), cover


# ------------------------------------------------------------------ stage 3: score
def finbert_scores(texts, tag, max_len, batch_size):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    cache = DATA / "_score_cache"
    cache.mkdir(parents=True, exist_ok=True)
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(FINBERT_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(FINBERT_MODEL).to(device).eval()
    id2label = {int(k): v.lower() for k, v in model.config.id2label.items()}
    pos_i = next(k for k, v in id2label.items() if v == "positive")
    neg_i = next(k for k, v in id2label.items() if v == "negative")
    print(f"[{tag}] {len(texts):,} unique texts on {device}; labels {id2label}")

    order = np.argsort([len(t) for t in texts], kind="stable")     # similar lengths batch together
    out = np.zeros(len(texts), dtype=np.float32)
    t0, done, scored_now = time.time(), 0, 0
    for b, start in enumerate(range(0, len(texts), BLOCK)):
        f = cache / f"{tag}_{b:05d}.npy"
        idx = order[start:start + BLOCK]
        if f.exists():
            out[idx] = np.load(f)
            done += len(idx)
            continue
        block = np.zeros(len(idx), dtype=np.float32)
        for s in range(0, len(idx), batch_size):
            batch = [texts[i] for i in idx[s:s + batch_size]]
            enc = tok(batch, padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(device)
            with torch.inference_mode():
                p = torch.softmax(model(**enc).logits, dim=-1).cpu().numpy()
            block[s:s + len(batch)] = p[:, pos_i] - p[:, neg_i]
        np.save(f, block)
        out[idx] = block
        done += len(idx)
        scored_now += len(idx)
        print(f"[{tag}] {done:,}/{len(texts):,}  ({scored_now / max(time.time() - t0, 1e-9):,.0f} texts/s)", flush=True)
    return out, {"device": device, "texts": len(texts), "seconds": round(time.time() - t0, 1),
                 "texts_per_second": round(scored_now / max(time.time() - t0, 1e-9), 1)}


def vader_scores(texts):
    import nltk
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    try:
        sia = SentimentIntensityAnalyzer()
    except LookupError:
        nltk.download("vader_lexicon", quiet=True)
        sia = SentimentIntensityAnalyzer()
    return np.array([sia.polarity_scores(t)["compound"] for t in texts], dtype=np.float32)


def score(df, headline_only, batch_size):
    df = df.copy()
    df["title"] = df["title"].fillna("").astype(str).str.strip()
    df["summary"] = df["summary"].fillna("").astype(str).str.strip().str.slice(0, 700)
    log = {}
    titles = sorted(df["title"].unique())
    fb, log["finbert_headlines"] = finbert_scores(titles, "title", MAX_TOKENS_HEADLINE, batch_size)
    vd = vader_scores(titles)
    pos = df["title"].map({t: i for i, t in enumerate(titles)}).to_numpy()
    df["finbert"], df["vader"] = fb[pos], vd[pos]

    has_sum = (df["summary"].str.len() > 0) & (not headline_only)
    if has_sum.any():
        sums = sorted(df.loc[has_sum, "summary"].unique())
        fb_s, log["finbert_summaries"] = finbert_scores(sums, "summary", MAX_TOKENS_SUMMARY, batch_size)
        vd_s = vader_scores(sums)
        p = df.loc[has_sum, "summary"].map({t: i for i, t in enumerate(sums)}).to_numpy()
        df.loc[has_sum, "finbert"] = (df.loc[has_sum, "finbert"].to_numpy() + fb_s[p]) / 2
        df.loc[has_sum, "vader"] = (df.loc[has_sum, "vader"].to_numpy() + vd_s[p]) / 2
    log["articles_with_summary_averaged"] = int(has_sum.sum())
    log["headline_only_mode"] = bool(headline_only)
    return df, log


# ------------------------------------------------------------------ main
def main(raw, headline_only, batch_size, prepare_only=False):
    t_all = time.time()
    universe = [c for c in pd.read_csv(DATA / "adj_close_clean.csv", nrows=0).columns if c not in ("Date",) and not c.startswith("Unnamed")]

    # Stage 1 is slow on the 5+ GB file, so its result is cached and reused on re-runs.
    cache = DATA / "_news_universe.csv.gz"
    meta = DATA / "_news_universe_meta.json"
    raw_id = {"name": Path(raw).name, "bytes": Path(raw).stat().st_size}
    if cache.exists() and meta.exists() and json.load(open(meta)).get("raw_id") == raw_id:
        df = pd.read_csv(cache, dtype={"summary": str})
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
        m_ = json.load(open(meta))
        n_rows, cols, n_roundup = m_["raw_rows"], m_["columns"], m_.get("roundups_removed", 0)
        print(f"Reusing cached stage 1 ({len(df):,} universe articles)")
    else:
        df, n_rows, cols, n_roundup = filter_news(raw, universe)
        df.to_csv(cache, index=False)
        json.dump({"raw_rows": n_rows, "columns": cols, "raw_id": raw_id, "roundups_removed": n_roundup}, open(meta, "w"))
    window, in_window, cover = choose_window(df)
    win = df[in_window.to_numpy()].copy()
    per_ticker = win.groupby("ticker").size().reindex(universe).fillna(0).astype(int)
    json.dump(window, open(DATA / "window.json", "w"), indent=2)

    lines = [f"Raw rows read: {n_rows:,}", f"Rows for the {len(universe)}-stock universe (deduped): {len(df):,}",
             f"Multi-stock roundup articles removed: {n_roundup:,}",
             f"Date range for universe: {df['ts_utc'].min()} .. {df['ts_utc'].max()}", f"Window: {window}",
             f"Articles in window: {len(win):,}; with a summary field: {(win['summary'].fillna('').str.len() > 0).mean():.0%}",
             f"Tickers with zero articles in window: {list(per_ticker[per_ticker == 0].index)}", "",
             "Articles per ticker in window:", per_ticker.sort_values().to_string(), "",
             "Tickers covered per month (whole file):", cover.to_string()]
    (DATA / "coverage.txt").write_text("\n".join(lines))
    print("\n".join(lines[:6]))
    if prepare_only:
        print("--prepare-only: stopped before scoring. Re-run without it on a machine with torch/FinBERT.")
        return

    scored, slog = score(win, headline_only, batch_size)
    scored[["ticker", "ts_utc", "title", "finbert", "vader"]].to_csv(DATA / "news_scored.csv.gz", index=False)
    log = {"raw_rows": n_rows, "columns_used": cols, "universe_rows_deduped": len(df), "roundups_removed": n_roundup,
           "articles_in_window": len(win),
           "tickers_with_news": int((per_ticker > 0).sum()), "tickers_total": len(universe),
           "unique_headlines": int(win["title"].nunique()), "scoring": slog,
           "total_seconds": round(time.time() - t_all, 1)}
    json.dump(log, open(DATA / "pipeline_log.json", "w"), indent=2)
    print("Done. Wrote news_scored.csv.gz, window.json, pipeline_log.json, coverage.txt")
    print(scored[["finbert", "vader"]].describe().round(3).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(DATA / "All_external.csv"))
    ap.add_argument("--headline-only", action="store_true", help="skip summaries (a deviation: disclose it)")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--prepare-only", action="store_true", help="stages 1-2 only (no torch needed)")
    a = ap.parse_args()
    main(a.raw, a.headline_only, a.batch_size, a.prepare_only)
