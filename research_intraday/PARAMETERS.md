# Intraday study: trade on news the moment it is released (locked 2026-10-27, before any Alpaca data was pulled)

Changes after this point are dated deviations at the bottom, never silent edits.

## Hypothesis
When a stock gets clearly positive (negative) news, its abnormal return in the minutes and hours after the headline is released keeps moving in the direction of the news, by more than the cost of trading it.

## Data
- News: Alpaca news API (Benzinga), every article with its exact release time (UTC), 2024-01-01 to 2026-09-30.
- Prices: Alpaca 1-minute bars (IEX feed, free tier), regular hours 09:30-16:00 New York; daily bars for beta; SPY as the market.
- Window: 2024-01-01 to 2026-09-30 (33 months). In sample: 2024-01 to 2025-09 (21 months). Holdout: 2025-10 to 2026-09 (12 months), used once.
  This period was chosen because no result from it has ever been seen (the first study used 2021-2023).

## Universe
- Every US ticker tagged in the window, excluding tickers containing "/" or longer than 5 letters, and a fixed list of major ETFs.
- Eligible: at least 25 of the 33 window months with a kept article, and at least 300 kept articles in the window (kept = regular-hours, see Deviation 1).
- Draw 80 eligible tickers in random order with numpy default_rng(20261027). The first 50 with complete minute-bar coverage are the universe.
  The draw uses only article counts and the seed, never prices or returns.

## Cleaning
- An article is kept for a ticker only if the article tags at most 2 tickers (multi-stock roundups say nothing about one stock).
- Duplicate article ids dropped. Headline only is scored (FinBERT, P(pos) - P(neg)); VADER is the comparison.

## Signal and trade
- Long if the article's FinBERT score is >= +0.5, short if <= -0.5.
- Entry: the open of the first 1-minute bar that starts at least 1 minute after the release time.
  Only articles released in regular hours are traded (see Deviation 1): after-hours, pre-market and weekend articles are ignored.
- One open position per stock: a new signal on a stock already held is ignored.
- Exit: the open of the bar that starts H minutes after entry, or the 16:00 close if that is earlier.
- PRIMARY strategy: H = 60 minutes. Comparison strategies: H = 5, 15, 30, 120, 180, 240, 300 minutes.
  All eight are reported in a comparison table. Only the 60-minute result decides the verdict; the others are exploratory (eight strategies means some will look good by chance).
- Abnormal return = stock return - beta x SPY return over the same interval; beta from the 120 trading days of daily closes before the event day.
- Cost: 10 bps round trip (primary); 20 and 30 bps as sensitivity checks.
- Portfolio: equal weight across the trades entered that day; no leverage; days with no trade earn 0; Sharpe uses rf = 0, annualised with sqrt(252).
- Benchmarks: equal-weight buy-and-hold of the universe (daily close to close), and SPY.

## Primary test
OLS of the 60-minute abnormal return (in bps) on the article's FinBERT score, standard errors clustered by ticker, in sample. Also reported: the same regression at every horizon, and a "profile" of average direction-adjusted abnormal return at each horizon after entry.

## Decision rule
Supported only if (1) the in-sample 60-minute coefficient is positive and significant at 5% AND (2) the holdout net-of-cost (10 bps) Sharpe of the 60-minute strategy beats the equal-weight benchmark. Anything else: not supported. Report whatever comes out.

## Known limits, stated in advance
- Free IEX bars cover only part of market volume, so prices are approximate and some minutes have no bar (the last available price is used).
- A fixed 10 bps cost understates spread and slippage at minute-level timing (hence the 20 and 30 bps checks). Borrowing cost on shorts is ignored.
- Benzinga's release time is when the article appeared there, which may be after the first appearance elsewhere.
- All prices come from the IEX feed only. They are split-adjusted but not dividend-adjusted, so both benchmarks (equal-weight buy-and-hold and SPY) exclude dividends equally.
- Half-days (early 13:00 closes) have fewer than 390 minute bars; the 16:00 close rule is applied to the last bar of such a session.

## Deviations (dated; each says whether it was made before any returns were seen)

### Deviation 1 (2026-10-27, before any news or price data was pulled or any return seen)
Reason: after-hours articles (before 09:30 or after 16:00, or on weekends) can only be traded at the next open, hours or days later, which brings back the delay this study is meant to remove and adds unpredictability from overnight moves.
Change: only articles released Monday to Friday between 09:30:00 and 15:58:59 New York time are kept (so an entry bar exists before the close). All other articles are dropped before eligibility is counted, so the eligibility counts (25 of 33 months, 300 articles) now refer to regular-hours articles. Days with no bars (exchange holidays) are dropped when bars are matched. Everything else is unchanged.

### Deviation 2 (2026-10-27, after seeing only the article counts and the draw; no bars, scores or returns exist yet)
Reason: the draw returned 84 eligible tickers (of 8,257 seen), 80 of them drawn, and its first 50 contain two items that do not fit the intent of the universe rule.
- FXI is an ETF (iShares China Large-Cap) that was missing from the fixed ETF exclusion list.
- GOOG and GOOGL are two share classes of the same company; their news and returns are near-duplicates and would double count one company.
Change: remove FXI and GOOGL from the draw order (keep GOOG, which was drawn first), without redrawing, so every other ticker keeps its place and the next tickers in the draw order fill the two gaps. The universe is then the first 50 remaining tickers with complete minute-bar coverage, as in the original rule.
Context to report: only 84 of 8,257 tickers meet the news-coverage rule, so the universe is essentially the most heavily covered large US stocks (the 50 are a random draw from those 84). Results apply to that kind of stock, not to US stocks in general.
- Also remove VGK (Vanguard FTSE Europe ETF), which sits in the reserve list and is an ETF like FXI. It matters only if 25 or more of the first 50 are skipped for missing bars.

### Deviation 3 (2026-10-27, set before any bars were downloaded; availability only, never returns)
Reason: "complete minute-bar coverage" (Universe section) was not defined, and free IEX bars have gaps, so a missing or very late bar would otherwise be silently replaced by a stale price at entry or exit. Both rules below are fixed now, before any price data exists.

A. Coverage rule (implemented in 03_pull_bars.py). A drawn ticker, taken in draw order after Deviation 2, is accepted only if ALL of these hold; otherwise it is skipped, the reason is recorded, and the next ticker in the draw order is tried, until 50 are accepted. The rule looks at bar counts and dates only, never at prices or returns.
1. At least one regular-hours (09:30-16:00 New York) bar on at least 95% of trading days. A trading day is a date on which SPY has at least 50 regular-hours bars (this drops exchange holidays).
2. The median over trading days of (bars that day / 390) is at least 25%.
3. At least one bar in each of the first 5 and the last 5 trading days of the window.
4. At least 120 daily bars before 2024-01-01, so the beta exists for the earliest events.

B. Staleness rule (applied in the notebook). A trade is skipped, and counted, if
1. the entry bar starts more than 5 minutes after the release time, or
2. the exit bar starts more than 5 minutes after the target exit time.
Skipped trades are reported overall, by ticker and by horizon. A skipped trade never opens a position, so it does not block a later signal on the same stock.
Clarifications made when writing this rule (also before any bars or returns exist): (i) "entry bar" and "exit bar" are the first actual bars that meet the locked timing rule (entry: first bar starting at least 1 minute after release; exit: first bar starting at or after the target exit time = entry bar start + H minutes). A minute with no bar is not filled with a stale price for entry or exit; the last-available-price fill from the Known limits is used only for the profile chart and intermediate marks. (ii) When entry + H would pass 16:00, the exit is the close of the last bar of the day, and the trade is skipped if that last bar starts before 15:55.

### Deviation 4 (2026-10-29, clarifications made before any real return was seen)
Status: the simulated-data validation in Intraday_Notebook.ipynb section 12 had passed, and no real bar, price or return had been loaded, when these six interpretations were fixed. They resolve points the earlier text left open; none changes a locked parameter. Each was applied in the validation code and is applied unchanged in the real run.
1. Event-study sample. The event study (primary test and every other horizon) uses every article-ticker event with a valid trade (entry bar and exit bar both pass the staleness rule), with no score threshold and no one-position rule. Holds cut short by the 16:00 close are included, because that is how the strategy realises the return; the same regression on holds not cut short by the close is reported as a robustness column. Date-clustered standard errors are a labelled robustness check and do not enter the decision rule.
2. Strategy profit and loss. A trade earns the raw stock return in the direction of the signal (long +1, short -1) minus the round-trip cost. It is not hedged against SPY. The abnormal return (stock return minus beta x SPY return) is used for the event study and the profile, and the average market beta of a trade is reported under risk.
3. Beta. Beta is the slope of the stock's daily returns on SPY's daily returns over the 120 daily closes before the event day, which is 119 daily returns, with the window ending the day before the event day. At least 100 usable returns are needed; otherwise the trade is skipped and counted.
4. Entry timing to the second. "Starts at least 1 minute after the release" is applied to the second: the entry bar is the first bar with start >= release + 60 seconds. An article released between 15:58:01 and 15:58:59 therefore has no entry bar before the close; it is skipped as a stale entry and counted.
5. One open position per stock. Signals are taken in release-time order. A signal is ignored if its release time is earlier than the exit time of the stock's open position (a release exactly at the exit time may trade). A signal whose trade is skipped for a stale bar never opens a position and blocks nothing. Ignored signals are counted separately from skipped trades.
6. Non-trading weekdays and early closes. A weekday release on a date with no trading session (exchange holiday) is skipped and counted. A session whose last SPY bar starts before 15:30 is treated as an early close at 13:00, and the 16:00-close exit rule (including the 15:55 last-bar check) is applied to the last bar of that session.
