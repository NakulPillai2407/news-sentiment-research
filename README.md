# News Sentiment Research

**Does it pay to trade on the headline?** Two pre-registered tests of one idea: buy stocks after clearly positive news and short them after clearly negative news. Both come out negative.

The idea is the one behind my live [Sentiment Signal app](https://github.com/NakulPillai2407/sentiment-signal). That app is a demo tool with an illustrative backtest. This repo is the careful version: parameters written down before the data was seen, an in-sample period, a final year held out and used once, costs included, and the result reported whatever it turned out to be. It is part of [Holdout Research](https://nakulpillai2407.github.io).

## Results

| | Study 1: daily | Study 2: intraday |
|---|---|---|
| News | FNSPID (dated to the day) | Alpaca / Benzinga (exact release time) |
| Prices | Daily closes (Yahoo Finance) | 1-minute bars (Alpaca, IEX feed) |
| Period | 2021 to 2023, last 12 months held out | Jan 2024 to Sep 2026, last 12 months held out |
| Stocks | 50, drawn at random across industries | 50, drawn at random from the most heavily covered US stocks |
| Trade | Enter at the close of the article's date, hold 1 day | Enter 1 minute after release, hold 60 minutes |
| Signal strength after the entry | +9.7 bps per unit of sentiment (p = 0.30) | +3.95 bps per unit of sentiment (p = 0.56) |
| Cost of a round trip | 10 bps | 10 bps |
| Held-out net Sharpe | -0.34 (equal-weight 0.94) | -3.74 (equal-weight 1.18) |
| Hypothesis | Not supported | Not supported |

In the daily data, sentiment is strongly linked to the abnormal return on the article's own day (+110 bps per unit in sample), but the next day, which is the first day a trade can honestly be placed, the effect is about the size of the trading cost. With exact release times, the effect left after the release is a few basis points at every horizon from 5 minutes to 5 hours, far below the cost. For heavily covered US stocks, the market appears to price a headline before a trade placed after it can act.

The full write-ups are in [`reports/`](reports/):
- [Study 1: daily news](reports/Study1_Daily_Report.pdf)
- [Study 2: intraday news](reports/Study2_Intraday_Report.pdf)

## How the work is organised

```
research/             Study 1 (daily). Scripts, notebook, PARAMETERS.md, outputs
research_intraday/    Study 2 (intraday). Numbered scripts, notebook, PARAMETERS.md, outputs
reports/              Written reports (PDF)
```

Each study has a `PARAMETERS.md` that records the hypothesis, the data, every parameter and the decision rule. Changes after that point are logged as dated deviations at the bottom of the file, each saying whether it was made before or after any returns were seen. This repo has no commit history from before the data was pulled, so those dates are my own record and are not independently timestamped.

Each notebook is tested on simulated data before it is allowed to touch real returns: a planted effect has to be recovered and a world with no effect has to produce nothing.

## Running it

```bash
pip install -r requirements.txt
```

**Study 1** needs the FNSPID Nasdaq news file (Dong et al., 2024, on Hugging Face as `Zihan1004/FNSPID`), saved as `research/data/nasdaq_exteral_data.csv`. It is far too large to include. See [`research/README.md`](research/README.md) for the run order.

**Study 2** needs a free Alpaca account for the news and bar data. Set the keys in your terminal, never in a file. See [`research_intraday/README.md`](research_intraday/README.md) for the run order.

## What is not in the repo

The raw news (FNSPID and Benzinga text), the downloaded 1-minute bars, and the scored headline files are left out. The news text belongs to its providers, and everything can be recreated with the scripts. The small derived files that record the universe, the coverage checks and the results are included.

## Limits

- Both universes are today's heavily covered US stocks, so survivorship bias is likely and the results say little about small or thinly covered stocks.
- Study 2 uses the free IEX price feed, which carries only part of market volume, so prices are approximate and thin stocks have gaps.
- Costs are a flat 10 bps round trip (20 and 30 bps as checks). Borrowing costs on shorts are ignored.
- Study 1 changed from a delayed entry to an immediate one after the first results were seen. That change is logged as a post-hoc deviation, so its held-out result is exploratory.
- Anything beyond the 60-minute (or one-day) strategy in either study is labelled exploratory in the reports.

This is research, not investment advice.

## Author

Nakul Pillai, MSc Financial Technology, Imperial College London. [GitHub](https://github.com/NakulPillai2407) · [LinkedIn](https://www.linkedin.com/in/nakul-pillai)
