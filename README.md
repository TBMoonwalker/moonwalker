# Moonwalker
## Summary
Moonwalker can be used to trade on your exchange directly using various signal plugins. It is also capable to create (dynamic) DCA deals.

## Disclaimer
**Moonwalker is meant to be used for educational purposes only. Use with real funds at your own risk**

## Prerequisites
- A Linux server with a static ip address
- Configured API access on your exchange
- Python >= 3.11
- Node.js (for the frontend build)

## Installation (run script)
1. Copy `config.ts.example` to `config.ts` and set `MOONWALKER_API_HOST` and `MOONWALKER_API_PORT`.
2. Start everything with `./run.sh start`.
3. Stop with `./run.sh stop`.

The script builds the Vue frontend, copies assets into the backend, creates a Python venv, installs backend deps, and starts the Quart app. Logs go to `run.log`.

### TA-Lib dependency
You also need to install the ta-lib library for your OS. Please see: https://ta-lib.org/install/#linux-debian-packages

## Configuration (database-backed)
Moonwalker no longer reads `config.ini`. Configuration is stored in the SQLite database (`backend/db/trades.sqlite`) and managed via the web UI or the REST API.

1. Start the app with `./run.sh start`.
2. Open the UI at `http://<host>:<port>` and go to the **Config** page.
3. Save your settings (they are persisted in the DB).

## Configuration Reference
All supported configuration keys are listed below. Keys marked "(advanced)" are not exposed in the UI and must be set via the API.

| Key | Type | Meaning | Example |
| --- | --- | --- | --- |
| `timezone` | `string` | Timezone used for logging. | `Europe/London` |
| `debug` | `bool` | Enable debug logging. | `true` |
| `signal` | `string` | Signal plugin to use (e.g. `sym_signals`, `asap`). | `sym_signals` |
| `signal_settings` | `string (json)` | Plugin settings for SymSignals. | `{"api_url":"https://stream.3cqs.com","api_key":"xxx","api_version":"v1","allowed_signals":[66]}` |
| `symbol_list` | `string` | CSV list or URL for ASAP symbol list. | `BTC/USDT,ETH/USDT` |
| `signal_strategy` | `string` | Strategy name for signal entry filter. | `ema_cross` |
| `signal_strategy_timeframe` | `string` | Timeframe for `signal_strategy`. | `1m` |
| `pair_allowlist` | `string` | Comma-separated allowed symbols. | `BTC,ETH` |
| `pair_denylist` | `string` | Comma-separated denied symbols. | `SCAM,XYZ` |
| `filter` | `string (json)` | UI filter payload (compat). | `{"rsi_max":70,"marketcap_cmc_api_key":"cmc_..."}` |
| `volume` | `string (json)` | Minimum 24h volume filter. | `{"size":5,"range":"M"}` |
| `topcoin_limit` | `int` | Max CoinMarketCap rank allowed. | `200` |
| `marketcap_cmc_api_key` | `string` | CoinMarketCap API key for market cap filtering. | `cmc_...` |
| `rsi_max` | `float` | Max RSI allowed for entry. | `70` |
| `btc_pulse` | `bool` | Enable BTC pulse filter. | `true` |
| `exchange` | `string` | Exchange name (ccxt id). | `binance` |
| `key` | `string` | Exchange API key. | `your-key` |
| `secret` | `string` | Exchange API secret. | `your-secret` |
| `market` | `string` | Market type. | `spot` |
| `timeframe` | `string` | Ticker timeframe for watcher. | `1m` |
| `currency` | `string` | Quote currency for pairs. | `USDT` |
| `dry_run` | `bool` | Simulate trades instead of placing orders. | `true` |
| `watcher_ohlcv` | `bool` | Use OHLCV watcher mode. | `false` |
| `fee_deduction` | `bool` | Use exchange fee token (e.g., BNB). | `false` |
| `sandbox` | `bool` | Enable exchange sandbox mode (advanced). | `false` |
| `order_check_range` | `int` | Seconds for post-order trade lookup (advanced). | `5` |
| `dca` | `bool` | Enable DCA. | `true` |
| `dynamic_dca` | `bool` | Enable dynamic DCA. | `false` |
| `dca_strategy` | `string` | Strategy for dynamic DCA. | `bbands_cross` |
| `dca_strategy_timeframe` | `string` | UI timeframe for dynamic DCA (compat). | `1m` |
| `strategy_timeframe` | `string` | Timeframe for `dca_strategy` (advanced). | `1m` |
| `tp_strategy` | `string` | Strategy for take-profit checks (advanced). | `ema_cross` |
| `tp_strategy_timeframe` | `string` | Timeframe for `tp_strategy` (advanced). | `1m` |
| `trailing_tp` | `float` | Trailing TP deviation (percent). | `0.5` |
| `max_bots` | `int` | Max concurrent bots. | `3` |
| `bo` | `float` | Base order size. | `10` |
| `so` | `float` | Safety order size. | `20` |
| `sos` | `float` | Price deviation for first safety order (percent). | `1.5` |
| `ss` | `float` | Safety order step scale. | `1.05` |
| `os` | `float` | Safety order volume scale. | `1.2` |
| `mstc` | `int` | Max safety order count. | `5` |
| `tp` | `float` | Take profit (percent). | `1.0` |
| `sl` | `float` | Stop loss (percent). | `2.0` |
| `ordersize` | `float` | ASAP base order size (advanced). | `12` |
| `housekeeping_interval` | `int` | Ticker cache cleanup interval (hours). | `48` |
| `history_from_data` | `int` | History lookback for indicator seed (days). | `30` |
| `pair_age` | `int` | Minimum pair age in days (advanced). | `30` |
| `autopilot` | `bool` | Enable autopilot mode. | `false` |
| `autopilot_max_fund` | `int` | Max funds for autopilot calculations. | `1000` |
| `autopilot_high_mad` | `int` | Max active deals (high setting). | `5` |
| `autopilot_high_tp` | `float` | TP percent (high setting). | `1.2` |
| `autopilot_high_sl` | `float` | SL percent (high setting). | `2.5` |
| `autopilot_high_sl_timeout` | `int` | SL timeout in days (high setting). | `7` |
| `autopilot_high_threshold` | `int` | Max fund threshold percent (high setting). | `80` |
| `autopilot_medium_mad` | `int` | Max active deals (medium setting). | `3` |
| `autopilot_medium_tp` | `float` | TP percent (medium setting). | `1.0` |
| `autopilot_medium_sl` | `float` | SL percent (medium setting). | `2.0` |
| `autopilot_medium_sl_timeout` | `int` | SL timeout in days (medium setting). | `10` |
| `autopilot_medium_threshold` | `int` | Max fund threshold percent (medium setting). | `60` |
| `strategies` | `array[string]` | Available strategies (read-only). | `["ema_cross","bbands_cross"]` |
| `signal_plugins` | `array[string]` | Available signal plugins (read-only). | `["sym_signals","asap"]` |

## SymSignals signal setup
Example value for `signal_settings`:
```json
{"api_url":"https://stream.3cqs.com","api_key":"your api key","api_version":"v1","allowed_signals":[66]}
```

## ASAP signal setup
For ASAP, select `asap` in the signal field and provide `symbol_list` as a comma-separated list or a URL returning `{"pairs":[...]}`.

## CI / Tests
Run all backend linting, type checks, and tests:
```bash
./scripts/ci.sh
```

## Logging
You can see information about the DCA and the TakeProfit (TP) status in the statistics.log. Other logs are available too (for exchange ...).

### Debug
Start Moonwalker with ./run.sh start -d and you see the debug messages in the logs.
