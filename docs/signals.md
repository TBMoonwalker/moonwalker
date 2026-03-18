# Signal Setup

## SymSignals Setup
Example value for `signal_settings`:
```json
{"api_url":"https://stream.3cqs.com","api_key":"your api key","api_version":"v1","allowed_signals":[66]}
```

## ASAP Setup
Select `asap` in the signal field and provide `symbol_list` as:
- A comma-separated list, or
- A URL returning `{"pairs":[...]}`

## CSV Signal Setup
Select `csv_signal` in the signal field and set `signal_settings` like:

```json
{"csv_source":"/absolute/path/to/trades.csv"}
```

You can also use an HTTP(S) URL:

```json
{"csv_source":"https://example.com/trades.csv"}
```

CSV format:

```csv
date;symbol;price;amount
18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153
24/08/2025 15:04:00;BTC/USDC;112170.19;0.03863000
```

Rules:
- Oldest row per symbol is imported as base order.
- Following rows are imported as safety orders.
- Import is blocked when open trades already exist.
