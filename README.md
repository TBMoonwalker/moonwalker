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
2. Start everything with `./run.sh start -p "port"`.
   - Debug logs: `./run.sh start --debug`
   - Trace logs: `./run.sh start --trace`
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
| `exchange_hostname` | `string` | Optional ccxt hostname override for exchange domains (advanced). | `bybit.eu` |
| `market` | `string` | Market type. | `spot` |
| `timeframe` | `string` | Ticker timeframe for watcher. | `1m` |
| `currency` | `string` | Quote currency for pairs. | `USDT` |
| `dry_run` | `bool` | Enable CCXT demo trading mode (if supported by exchange). | `true` |
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
| `dynamic_so_volume_enabled` | `bool` | Enable dynamic scaling for safety order amount. Trigger logic stays unchanged; only SO size is scaled. | `false` |
| `dynamic_so_ath_lookback_value` | `int` | ATH lookback amount used by dynamic SO scaling. | `1` |
| `dynamic_so_ath_lookback_unit` | `string` | Lookback unit for ATH: `day`, `week`, `month`, or `year`. | `month` |
| `dynamic_so_ath_timeframe` | `string` | Candle timeframe used for ATH fetch via ccxt: `4h`, `1d`, or `1w`. | `4h` |
| `dynamic_so_ath_cache_ttl` | `int` | Cache TTL in seconds for ATH lookup (in-memory + DB cache freshness). | `60` |
| `dynamic_so_loss_weight` | `float` | Weight for current trade loss contribution in dynamic scale formula. | `0.5` |
| `dynamic_so_drawdown_weight` | `float` | Weight for ATH drawdown contribution in dynamic scale formula. | `0.8` |
| `dynamic_so_exponent` | `float` | Curve exponent applied to drawdown term. Higher values emphasize deeper drawdowns. | `1.1` |
| `dynamic_so_min_scale` | `float` | Lower bound for dynamic SO multiplier. | `0.5` |
| `dynamic_so_max_scale` | `float` | Upper bound for dynamic SO multiplier. | `3.0` |
| `dynamic_so_ath_window` | `string` | Legacy compatibility key (`1d`/`1w`/`1m`) used only when lookback value/unit are not set. | `1m` |
| `tp` | `float` | Take profit (percent). | `1.0` |
| `sl` | `float` | Stop loss (percent). | `2.0` |
| `ordersize` | `float` | ASAP base order size (advanced). | `12` |
| `housekeeping_interval` | `int` | Ticker cache cleanup interval (days). | `2` |
| `history_from_data` | `int` | History lookback for indicator seed (days). | `30` |
| `upnl_housekeeping_interval` | `int` | uPNL history retention in days; `0` keeps all history forever. | `0` |
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
| `monitoring_enabled` | `bool` | Enable outbound monitoring notifications for executed buys/sells. | `false` |
| `monitoring_telegram_api_id` | `int` | Telegram API ID used by Telethon client. | `1234567` |
| `monitoring_telegram_api_hash` | `string` | Telegram API hash used by Telethon client. | `0123456789abcdef...` |
| `monitoring_telegram_bot_token` | `string` | Telegram bot token used by Telethon client start. | `123456:ABC-DEF...` |
| `monitoring_telegram_chat_id` | `string` | Telegram chat ID (user/group/channel) receiving notifications. | `-1001234567890` |
| `monitoring_timeout_sec` | `int` | Telegram send timeout in seconds. | `5` |
| `monitoring_retry_count` | `int` | Number of retries after a failed Telegram send. | `1` |
| `strategies` | `array[string]` | Available strategies (read-only). | `["ema_cross","bbands_cross"]` |
| `signal_plugins` | `array[string]` | Available signal plugins (read-only). | `["sym_signals","asap"]` |

## Dynamic SO ATH Parameters
Dynamic safety-order sizing uses recent ATH from exchange OHLCV data (ccxt), not local ticker history.

- Formula inputs:
  - Current loss (`actual_pnl`)
  - Drawdown from configurable ATH window
- Formula controls:
  - `dynamic_so_loss_weight`
  - `dynamic_so_drawdown_weight`
  - `dynamic_so_exponent`
  - `dynamic_so_min_scale` / `dynamic_so_max_scale`
- Caching:
  - ATH values are cached in the `ath_cache` table and in memory.
  - Freshness is controlled by `dynamic_so_ath_cache_ttl`.

### Dynamic SO Scale Controls
- `dynamic_so_loss_weight` (Loss weight):
  - Multiplies the current loss term (`abs(actual_pnl) / 100`) in the dynamic scale formula.
  - Higher value increases SO size faster as deal loss grows.
  - Typical range: `0.2` to `1.0`.

- `dynamic_so_drawdown_weight` (ATH drawdown weight):
  - Multiplies the ATH drawdown term (`(ath - price) / ath`) in the dynamic scale formula.
  - Higher value increases SO size faster when price is further below ATH.
  - Typical range: `0.3` to `1.5`.

- `dynamic_so_exponent` (Curve exponent):
  - Applied to drawdown term as `drawdown ** exponent`.
  - `> 1.0`: emphasizes deeper drawdowns; `0 < x < 1.0`: reacts more to smaller drawdowns.
  - Typical range: `1.0` to `1.5`.

- `dynamic_so_min_scale` (Dynamic min scale):
  - Lower clamp for final dynamic multiplier.
  - Prevents SO size from being reduced below this multiplier.
  - Example: `0.8` means SO size cannot drop below `80%` of base computed size.

- `dynamic_so_max_scale` (Dynamic max scale):
  - Upper clamp for final dynamic multiplier.
  - Prevents overly large SO size increases in extreme conditions.
  - Example: `1.8` means SO size cannot exceed `180%` of base computed size.

- `dynamic_so_ath_cache_ttl` (ATH cache TTL (sec)):
  - Cache freshness in seconds for ATH values (in-memory + DB cache read freshness).
  - Lower value updates ATH more often but makes more exchange requests.
  - Higher value reduces exchange load but uses older ATH values longer.
  - Typical range: `30` to `300`.

### Formula Summary
Dynamic SO multiplier is computed as:
```text
scale = clamp(
  1 + (loss_weight * loss_ratio) + (drawdown_weight * drawdown_ratio^exponent),
  min_scale,
  max_scale
)
```

Where:
- `loss_ratio = abs(actual_pnl) / 100`
- `drawdown_ratio = (ath - current_price) / ath`

Example: 1 year lookback using daily candles
```json
{
  "dynamic_so_volume_enabled": {"value": true, "type": "bool"},
  "dynamic_so_ath_lookback_value": {"value": 1, "type": "int"},
  "dynamic_so_ath_lookback_unit": {"value": "year", "type": "str"},
  "dynamic_so_ath_timeframe": {"value": "1d", "type": "str"}
}
```

Example: 1 year lookback using 4h candles
```json
{
  "dynamic_so_ath_lookback_value": {"value": 1, "type": "int"},
  "dynamic_so_ath_lookback_unit": {"value": "year", "type": "str"},
  "dynamic_so_ath_timeframe": {"value": "4h", "type": "str"}
}
```

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

### Trace
Start Moonwalker with `./run.sh start -t` (or `--trace`) to enable TRACE logs.

### Log Level Environment Variable
You can override log level directly with `MOONWALKER_LOG_LEVEL`:
- `TRACE`
- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Examples:
```bash
MOONWALKER_LOG_LEVEL=INFO ./run.sh start
MOONWALKER_LOG_LEVEL=TRACE ./run.sh start
```

Priority order:
1. `MOONWALKER_LOG_LEVEL` (if set)
2. `MOONWALKER_DEBUG=True` (set by `./run.sh start --debug`)
3. Default `INFO`
