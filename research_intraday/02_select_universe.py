"""
Step 2: count articles per ticker, apply the locked eligibility rule and draw the universe.

  python research_intraday/02_select_universe.py

Reads data/news_raw.csv. Writes data/universe.json (the draw order), data/news_universe.csv (articles for the drawn
tickers, one row per article-ticker) and data/_candidate_stats.csv. Uses only article counts and the seed, never prices.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
SEED = 20261027
N_UNIVERSE, N_DRAW = 50, 80
MIN_MONTHS, MIN_ARTICLES, MAX_SYMBOLS_PER_ARTICLE = 25, 300, 2
WINDOW = ("2024-01-01", "2026-09-30")
ETFS = set("SPY QQQ IWM DIA VOO VTI IVV XLF XLE XLK XLV XLY XLP XLU XLI XLB XLRE XLC SMH SOXX ARKK ARKG ARKW ARKF GLD SLV USO UNG TLT HYG LQD EEM EFA VXX UVXY SQQQ TQQQ SPXU SPXL SOXL SOXS TNA TZA LABU LABD FAS FAZ XBI IBB KRE KBE XOP OIH GDX GDXJ XME XHB ITB JETS BITO IBIT FBTC ETHA".split())


def main():
    df = pd.read_csv(DATA / "news_raw.csv", dtype=str)
    df["ts"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts", "symbols", "headline"]).drop_duplicates("id")
    df = df[(df.ts >= WINDOW[0]) & (df.ts <= pd.Timestamp(WINDOW[1], tz="UTC") + pd.Timedelta(days=1))]
    df["sym_list"] = df["symbols"].str.split("|")
    df["n_symbols"] = df["sym_list"].str.len()
    n_all = len(df)
    ex = df.explode("sym_list").rename(columns={"sym_list": "symbol"})
    ok = ~ex.symbol.str.contains("/") & (ex.symbol.str.len() <= 5) & ex.symbol.str.isalpha() & ~ex.symbol.isin(ETFS)
    ex = ex[ok & (ex.n_symbols <= MAX_SYMBOLS_PER_ARTICLE)].copy()
    # Locked rule (PARAMETERS.md, Deviation 1): keep only articles released in regular hours, Mon-Fri, 09:30:00 to 15:58:59 New York,
    # so that an entry bar (release + 1 minute) exists before the close. After-hours/weekend articles are not traded.
    ny = ex.ts.dt.tz_convert("America/New_York")
    mins = ny.dt.hour * 60 + ny.dt.minute
    in_hours_mask = (mins >= 570) & (mins < 959) & (ny.dt.dayofweek < 5)
    share_in_hours = float(in_hours_mask.mean())
    ex = ex[in_hours_mask].copy()
    ex["month"] = ex.ts.dt.tz_localize(None).dt.to_period("M")
    n_months = ex.month.nunique()
    stats = ex.groupby("symbol").agg(articles=("id", "size"), months=("month", "nunique"))
    elig = stats[(stats.months >= MIN_MONTHS) & (stats.articles >= MIN_ARTICLES)]
    order = [str(t) for t in np.random.default_rng(SEED).permutation(sorted(elig.index))[:N_DRAW]]
    keep = ex[ex.symbol.isin(order)][["id", "created_at", "symbol", "headline", "summary", "n_symbols"]]
    keep.to_csv(DATA / "news_universe.csv", index=False)
    stats.sort_values("articles", ascending=False).to_csv(DATA / "_candidate_stats.csv")
    info = {"seed": SEED, "window": WINDOW, "articles_in_window": n_all, "articles_kept_article_ticker_rows": int(len(ex)),
            "months_seen": int(n_months), "tickers_seen": int(stats.shape[0]), "n_eligible": int(len(elig)),
            "share_released_in_regular_hours_before_filter": share_in_hours, "draw_order": order, "n_universe": N_UNIVERSE}
    json.dump(info, open(DATA / "universe.json", "w"), indent=2)
    print(json.dumps({k: v for k, v in info.items() if k != "draw_order"}, indent=2))
    print("First 50 of the draw:", ", ".join(order[:N_UNIVERSE]))
    if len(elig) < N_UNIVERSE:
        print(f"\nWARNING: only {len(elig)} eligible tickers (< {N_UNIVERSE}). Paste this output back before going on.")
    print("\nArticles per drawn ticker (min / median / max):",
          int(stats.loc[order[:N_UNIVERSE], 'articles'].min()), int(stats.loc[order[:N_UNIVERSE], 'articles'].median()), int(stats.loc[order[:N_UNIVERSE], 'articles'].max()))


if __name__ == "__main__":
    main()
