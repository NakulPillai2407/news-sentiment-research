# Pre-registered parameters (locked 2026-10-26, before any FNSPID data was downloaded or inspected)

Nothing below may be changed after results are seen. If a choice turns out to be unworkable
(e.g. a data field is missing), the change is recorded in a dated "Deviations" section at the
bottom of this file and disclosed in the report. It is never silently edited.

## Hypothesis
News sentiment for a stock, scored by FinBERT, predicts that stock's abnormal return on the
following days, because prices adjust gradually to news. Competing view: any sentiment/return
link is same-day only (already priced), so nothing is tradeable.

## Universe and prices
- The 56 US tech/semiconductor stocks in `data/adj_close_clean.csv` (same universe as the
  lead-lag capstone). Adjusted closes. Market benchmark: S&P 500 (`^GSPC`).
- Tickers with no FNSPID articles in the window are kept in the price universe but cannot
  trigger signals; the count is reported.

## Window
- Source of news: FNSPID. Study window = the final 36 months of FNSPID coverage for this
  universe (end date = last full calendar month with news for at least 40 of the 56 tickers).
- In-sample (design/estimation period) = first 24 months. Out-of-sample holdout = final 12
  months, touched once, at the end.

## Sentiment
- Primary model: FinBERT (ProsusAI/finbert). Article score = P(positive) - P(negative), in [-1, 1].
- Text scored: headline; if a summary field exists it is scored too and the two are averaged.
- Baseline: VADER compound score, same text, used only for the model comparison.
- Stock-day score = mean article score over articles mapped to that stock-day.

## Alignment (look-ahead control)
- Convert timestamps to America/New_York. Published before 16:00 on a trading day -> event day
  is that day. Published at/after 16:00 or on a non-trading day -> next trading day.
- If FNSPID provides date only (no time), the article is treated as published at/after the
  close, i.e. event day = the next trading day (conservative).
- Event day = t. The signal is known at the close of t. Entry is at the close of t+1
  (one full day after, matching the capstone's entry rule).

## Abnormal returns
- Market model: AR = stock return - beta x S&P 500 return. Beta estimated by OLS on the 120
  trading days ending the day before the article's event day t (no overlap with t).
- Event study horizons: day 0 (t), +1, +2, +3, with cumulative +1..+3.

## Primary statistical test
- OLS of AR(+1) on stock-day sentiment score, standard errors clustered by ticker.
  Same regression for AR(0) as the mechanism check (is the move same-day only, as in the capstone?).

## Strategy
- Signal: stock-day with |mean score| >= 0.5. Long if score >= +0.5, short if <= -0.5.
  Minimum 1 article.
- Hold 3 trading days from entry. Equal weight across all positions open on a day. No leverage
  (capital split across open trades). Cost: 10 bps round trip on every trade.
- Benchmarks: equal-weight buy-and-hold of the 56 stocks; S&P 500.
- Metrics (same six as the capstone): cumulative return, annualised return, Sharpe, max
  drawdown, Sortino, win rate. Reported separately in-sample and out-of-sample.

## Pre-declared sensitivity checks (reported whatever they show)
- Threshold 0.3 and 0.7 (primary stays 0.5).
- FinBERT vs VADER (same rules).
- No-cost version of the strategy.

## Decision rule (set now so the verdict cannot move later)
The hypothesis is "supported" only if BOTH hold:
1. In-sample AR(+1) coefficient on sentiment is positive and significant at the 5% level, AND
2. Out-of-sample net-of-cost Sharpe of the strategy exceeds the equal-weight benchmark's.
Anything else is reported as "not supported". Positive Sharpe alone is not enough.

## Deviations
### Deviation 1 (2026-10-26, made BEFORE any news data was downloaded or inspected)
Reason: internal inconsistency found while mirroring the capstone code. The strategy enters at the
close of t+1 and holds 3 days, so it earns the returns of days t+2, t+3 and t+4 -- not day t+1.
The originally locked primary test (AR at +1) would have tested a day the strategy never trades.
Changes (these supersede the three places named):
- "Event study horizons": now day 0, +1, +2, +3 and +4 (profile shown as a bar chart, as in the capstone lag check),
  plus the cumulative tradeable window CAR(+2..+4).
- "Primary statistical test": OLS of CAR(+2..+4) on stock-day sentiment score, clustered by ticker.
  The same regression on AR(0) and AR(+1) is the mechanism check, reported alongside.
- "Decision rule", condition 1: in-sample CAR(+2..+4) coefficient positive and significant at 5%.
  Condition 2 (out-of-sample net-of-cost Sharpe above equal-weight) is unchanged.
Everything else is unchanged. Cost convention copied from the capstone: the 10 bps is deducted
from the first holding day of each trade, and open trades are averaged each day (days with no open
trade earn 0). Sharpe uses a zero risk-free rate, as in the capstone.

### Deviation 2 (2026-10-26, made after inspecting only the news file's ticker/date metadata -- no sentiment score or return had been computed)
Reason: the first FNSPID file downloaded (`All_external.csv`) turned out to cover 2009 to 11 June 2020, with
only 39 of the 56 tickers present (AAPL 473 articles, AMZN 278, MSFT none), so the locked window rule
("last month with >= 40 of 56 tickers") could not be met. That file is not used for the study.
Changes recorded before any results exist:
- Ticker aliases applied when filtering news: `FB` -> `META` and `GOOG` -> `GOOGL` (same companies; the
  price file uses the current symbols). Duplicate (ticker, time, headline) rows created by the mapping are dropped.
- The window rule's "last full calendar month" now explicitly excludes a half-finished final month in the file.
- The coverage rule (>= 40 of 56 tickers) is unchanged. If the replacement file also fails it, the shortfall will
  be reported and a new, dated decision made before any returns are looked at.

### Deviation 3 (2026-10-26, made before any sentiment score or return was computed)
Reason: in the first (rejected) FNSPID file, 38% of articles were multi-stock roundups (the same title attached to
5+ tickers, e.g. "46 Stocks Moving In Friday's Mid-Day Session"). They are attached to every stock they list and say
nothing specific about any one of them, so scoring them as stock news would pollute the signal.
Change: an article is dropped if the same headline (case-insensitive) appears on 3 or more different universe
stocks on the same calendar day. The number removed is reported in the Data Pipeline section. No other cleaning
of headlines is done.

### Deviation 4 (2026-10-26, made before any sentiment score or return was computed; no price for the new stocks has been downloaded)
Reason: the 56-stock tech/semiconductor universe is not required by the hypothesis (sentiment does not rely on
interconnectedness, unlike the lead-lag project), and the news files available do not cover that list well enough.
The replacement FNSPID file is `nasdaq_exteral_data.csv` (about 23 GB, to Dec 2023).
Changes:
- Universe: about 50 US stocks drawn at random across all industries, instead of the 56 tech/semiconductor stocks.
  Eligible stocks are those with news in at least 30 of the 36 window months and at least 300 articles in the window
  (after roundup removal). They are drawn in random order with `numpy.random.default_rng(2026)`; the first 50 with
  usable Yahoo prices are used (80 are drawn so that a stock with no price history is replaced by the next in order).
  The selection uses only news counts and the seed, never prices or returns. Script: `select_universe.py`.
- The report title and wording change from "US tech/semiconductor stocks" to "US stocks across industries".
- Roundup removal (Deviation 3) is now applied across ALL tickers in the file (same headline on >= 3 different
  tickers on one day), because within a random 50 most roundups would otherwise slip through. The count removed is reported.
- The MIN tickers rule becomes 40 of 50. Everything else (window length, holdout, sentiment, thresholds, costs,
  decision rule) is unchanged. Prices: `download_prices.py` (Yahoo, adjusted close; ^GSPC as market).

### Deviation 5 (2026-10-27, made AFTER Strategy A's results were seen: this is a post-hoc design change and is reported as such)
Reason: the hypothesis was always "trade immediately on positive/negative news", but Strategy A (as locked) entered at the
close of the day after the event day and earned days 2 to 4, which tests a delayed reaction, and the news file turned out
to carry dates only, which pushed A's trades two days later again. Strategy A found no edge (in-sample CAR(2..4)
coefficient -18.2 bps, p = 0.18; out-of-sample net Sharpe -0.30 vs 0.94 for equal-weight).
Strategy B (replaces A as the reported strategy; A's results are kept in the project folder `outputs_A_delayed/`):
- The event day is the article's own date (the next trading day if that date is a weekend or holiday).
- Entry at the close of the event day; hold one day (earn day +1); 10 bps cost on that day; same 0.5 threshold,
  equal weighting, no leverage, same stocks, window, in-sample and holdout periods.
- Primary test: OLS of AR(+1) on the FinBERT stock-day score, clustered by ticker. Day 0 is a diagnostic (the strategy cannot trade it).
- Decision rule condition 1 uses AR(+1) instead of CAR(+2..+4); condition 2 is unchanged.
Known bias, stated in advance: the file has no times of day, so some articles dated D were published after the close
of D, and entering at that close is then slightly ahead of the information. This favours Strategy B.
Because B was designed after the holdout was seen, its out-of-sample result is exploratory, not a clean confirmation.
