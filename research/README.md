# Study 1: daily news and abnormal returns

Does news sentiment predict the abnormal return the day after an article is dated? FNSPID news (Nasdaq file, 2021 to 2023) scored with FinBERT, 50 US stocks drawn at random across industries, last 12 months held out. The decision rule, the parameters and every dated deviation are in [`PARAMETERS.md`](PARAMETERS.md).

| File | What it is |
|---|---|
| `select_universe.py` | One resumable pass over the large news file, then the seeded random draw of the stock universe (uses article counts only, never prices) |
| `download_prices.py` | Yahoo Finance adjusted closes for the drawn stocks and ^GSPC |
| `data_pipeline.py` | Filters the news to the universe and window, scores headlines with FinBERT and VADER |
| `Sentiment_Signal_Notebook.ipynb` | All the analysis: alignment, abnormal returns, event study, backtest, benchmarks, risk, decision rule, validation on simulated data |
| `PARAMETERS.md` | Locked parameters and decision rule, with dated deviations |
| `data/` | Small derived files (universe, window, coverage, prices) |
| `outputs/` | Tables, figures and `results.json` from the notebook (the final immediate-entry design) |
| `outputs_A_delayed/` | Results of the first, delayed-entry design that was replaced (Deviation 5) |

## Run order

```bash
pip install -r ../requirements.txt
# put the FNSPID Nasdaq file at research/data/nasdaq_exteral_data.csv, then from the repo root:
python research/select_universe.py extract      # repeat until it prints DONE
python research/select_universe.py select
python research/download_prices.py
python research/data_pipeline.py                # resumable
jupyter nbconvert --to notebook --execute --inplace research/Sentiment_Signal_Notebook.ipynb
```

Data: FNSPID (Dong et al., 2024; Hugging Face `Zihan1004/FNSPID`). Prices: Yahoo Finance adjusted closes.
