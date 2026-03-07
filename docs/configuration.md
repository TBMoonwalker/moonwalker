# Configuration

1. Start the app with `./run.sh start`.
2. Open the UI at `http://<host>:<port>`
3. Save your settings (they are persisted in the DB).

## Configuration Reference
All supported configuration keys are listed below. Keys marked "(advanced)"
are not exposed in the UI and must be set via the API.

| Key | Type | Meaning | Example |
| --- | --- | --- | --- |
| `timezone` | `string` | Timezone used for logging. | `Europe/London` |
| `debug` | `bool` | Enable debug logging. | `true` |
| `signal` | `string` | Signal plugin to use (e.g. `sym_signals`, `asap`, `csv_signal`). | `sym_signals` |
| `signal_settings` | `string (json)` | Plugin settings per selected signal plugin. | `{"api_url":"https://stream.3cqs.com","api_key":"xxx","api_version":"v1","allowed_signals":[66]}` |
| `symbol_list` | `string` | CSV list or URL for ASAP symbol list. | `BTC/USDT,ETH/USDT` |
| `signal_strategy` | `string` | Strategy name for signal entry filter. | `ema_cross` |
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
| `tp_strategy` | `string` | Strategy for take-profit checks (advanced). | `ema_cross` |
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
| `dynamic_so_loss_max_scale_threshold` | `float` | Absolute loss percentage at which dynamic SO uses `dynamic_so_max_scale` directly. | `30.0` |
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
| `signal_plugins` | `array[string]` | Available signal plugins (read-only). | `["asap","csv_signal","sym_signals"]` |
