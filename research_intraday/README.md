# Study 2: trading on news at the moment of release

Does a stock keep moving in the direction of a headline in the minutes after it is released, by more than it costs to trade? Alpaca (Benzinga) news with exact release times, Alpaca 1-minute bars, 50 stocks, January 2024 to September 2026, last 12 months held out. Everything was fixed in [`PARAMETERS.md`](PARAMETERS.md) before any data was pulled, with four dated deviations logged at the bottom.

## Run order

From the repo root, with the keys set in your terminal only:

```bash
pip install -r requirements.txt
export ALPACA_KEY="..." ALPACA_SECRET="..."
python research_intraday/01_pull_news.py          # all news in the window (resumable)
python research_intraday/02_select_universe.py    # filters, eligibility, seeded draw
python research_intraday/03_pull_bars.py --test   # one-ticker check
python research_intraday/03_pull_bars.py          # minute and daily bars for the 50 stocks (resumable)
python research_intraday/04_score.py              # FinBERT and VADER on the headlines
```

Then open `Intraday_Notebook.ipynb`. The first run only does the simulated-data validation and writes `outputs/validation_passed.json`. The real-data cells stay locked until that file exists and you set `INTRADAY_RUN_REAL=1`. Run it once, with no changes, to reproduce `outputs/`.

| File | What it is |
|---|---|
| `01` to `04` | The data pipeline, in order |
| `Intraday_Notebook.ipynb` | Validation, event study at 8 horizons, backtests, costs, benchmarks, decision rule |
| `PARAMETERS.md` | Locked parameters, decision rule, known limits and dated deviations |
| `data/` | Small derived files: draw order, final universe, bar-coverage manifest, trading calendar, scoring report |
| `outputs/` | Tables, figures and `results.json` |

The Alpaca free tier serves the IEX feed only. News text, bars and scored headlines are not included in the repo.
