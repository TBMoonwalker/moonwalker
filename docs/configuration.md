# Configuration

1. Start the app with `./run.sh start`.
2. Open the UI at `http://<host>:<port>`
3. Save your settings (they are persisted in the DB).

Runtime configuration is stored in the `AppConfig` table and served to the UI
through `/config/all`. The dashboard typically updates settings via
`PUT /config/single/{key}` or `POST /config/multiple`.

For signal-plugin-specific payloads and examples, see [signals.md](signals.md).
For backup/restore and related config endpoints, see [api.md](api.md).

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
| `sell_order_type` | `string` | Sell execution type for TP/exit orders. Supported values are `market` and `limit`. | `market` |
| `limit_sell_timeout_sec` | `int` | Timeout in seconds before an unfilled limit sell is treated as timed out. | `60` |
| `limit_sell_fallback_to_market` | `bool` | Allow a timed-out limit sell to fall back to a market sell when guards still permit it. | `true` |
| `tp_spike_confirm_enabled` | `bool` | Enable TP spike confirmation so a single wick above TP does not immediately trigger a sell. | `false` |
| `tp_spike_confirm_seconds` | `float` | Required time the price must continue to qualify above TP before the sell is confirmed. | `3` |
| `tp_spike_confirm_ticks` | `int` | Minimum number of qualifying ticker updates above TP required before the sell is confirmed. `0` disables the tick requirement. | `0` |
| `so` | `float` | Safety order size. | `20` |
| `sos` | `float` | Price deviation for first safety order (percent). | `1.5` |
| `ss` | `float` | Safety order step scale. | `1.05` |
| `os` | `float` | Safety order volume scale. | `1.2` |
| `mstc` | `int` | Max safety order count. | `5` |
| `trade_safety_order_budget_ratio` | `float` | Dynamic-DCA budget cap for a single safety order as a fraction of currently free quote balance. | `0.95` |
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
| `history_lookback_time` | `string` | Canonical indicator history lookback using `d/w/m/y` suffixes such as `30d`, `12w`, `6m`, or `1y`. | `90d` |
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
| `autopilot_green_phase_enabled` | `bool` | Enable Green Phase deal expansion. When active, Autopilot can temporarily raise effective max deals during strong profitable-close bursts. | `false` |
| `autopilot_green_phase_ramp_days` | `int` | Ramp-up history window in days used to build the profitable-close speed baseline from `ClosedTrades`. | `30` |
| `autopilot_green_phase_eval_interval_sec` | `int` | How often the Green Phase service re-runs its analysis. Each run counts as one evaluation cycle for `confirm_cycles` and `release_cycles`. | `60` |
| `autopilot_green_phase_window_minutes` | `int` | Rolling lookback window used on each evaluation to measure recent profitable-close speed. It does not define the cycle length. | `60` |
| `autopilot_green_phase_min_profitable_close_ratio` | `float` | Minimum ratio of profitable closes required inside the recent window before Green Phase may activate. | `0.8` |
| `autopilot_green_phase_speed_multiplier` | `float` | Minimum multiple of baseline profitable-close speed required to enter Green Phase. | `1.5` |
| `autopilot_green_phase_exit_multiplier` | `float` | Lower speed threshold used to leave Green Phase again, providing hysteresis and avoiding flapping. | `1.15` |
| `autopilot_green_phase_max_extra_deals` | `int` | Maximum number of additional deals Green Phase may add on top of the current effective `max_bots`. | `2` |
| `autopilot_green_phase_confirm_cycles` | `int` | Number of consecutive evaluation runs that must satisfy the enter condition before Green Phase activates. The timing of those runs is controlled by `autopilot_green_phase_eval_interval_sec`. | `2` |
| `autopilot_green_phase_release_cycles` | `int` | Number of consecutive evaluation runs below the exit condition before Green Phase deactivates. The timing of those runs is controlled by `autopilot_green_phase_eval_interval_sec`. | `4` |
| `autopilot_green_phase_max_locked_fund_percent` | `float` | Hard ceiling for locked funds, in percent of `autopilot_max_fund`, above which Green Phase may not add extra deals. | `85` |
| `monitoring_enabled` | `bool` | Enable outbound monitoring notifications for executed buys/sells. | `false` |
| `monitoring_telegram_api_id` | `int` | Telegram API ID used by Telethon client. | `1234567` |
| `monitoring_telegram_api_hash` | `string` | Telegram API hash used by Telethon client. | `0123456789abcdef...` |
| `monitoring_telegram_bot_token` | `string` | Telegram bot token used by Telethon client start. | `123456:ABC-DEF...` |
| `monitoring_telegram_chat_id` | `string` | Telegram chat ID (user/group/channel) receiving notifications. | `-1001234567890` |
| `monitoring_timeout_sec` | `int` | Telegram send timeout in seconds. | `5` |
| `monitoring_retry_count` | `int` | Number of retries after a failed Telegram send. | `1` |
| `strategies` | `array[string]` | Available strategies (read-only). | `["ema_cross","bbands_cross"]` |
| `signal_plugins` | `array[string]` | Available signal plugins (read-only). | `["asap","csv_signal","sym_signals"]` |

Read-only metadata keys such as `strategies` and `signal_plugins` are returned
in config snapshots for the dashboard and should not be treated as persisted
user-entered values.

## Autopilot Green Phase

Green Phase is an Autopilot extension that watches the speed of profitable closed
trades. If recent profitable closes rise clearly above the historical baseline,
the bot treats that as a broader "green market phase" and can temporarily raise
the effective maximum number of concurrent deals.

In simple terms:

- Moonwalker watches how quickly profitable trades are closing.
- If profitable trades are closing faster than usual, it treats that as a
  stronger market phase.
- During that phase, it can temporarily allow a few more deals than normal.
- It only does that when enough capital is still available for safety orders.

Simple example:

```json
{
  "autopilot": true,
  "autopilot_green_phase_enabled": true,
  "autopilot_green_phase_ramp_days": 30,
  "autopilot_green_phase_window_minutes": 60,
  "autopilot_green_phase_min_profitable_close_ratio": 0.8,
  "autopilot_green_phase_speed_multiplier": 1.5,
  "autopilot_green_phase_confirm_cycles": 2,
  "autopilot_green_phase_max_extra_deals": 2
}
```

What that means in practice:

- Moonwalker first looks at the last 30 days of closed trades and builds a
  baseline for how many profitable trades normally close per hour.
- Then it keeps looking at the last 60 minutes and compares recent profitable
  closes to that baseline.
- It repeats that analysis every configured evaluation interval. By default,
  this means every `60` seconds.
- To activate Green Phase, the recent profitable-close speed must be at least
  `1.5x` the baseline.
- At least `80%` of the closes in that recent window must be profitable.
- The condition must stay true for 2 consecutive evaluation runs before Green
  Phase actually activates.

How the timing works:

- `autopilot_green_phase_window_minutes` is the size of the lookback window.
  In this example, every check looks back over the last `60` minutes.
- `autopilot_green_phase_eval_interval_sec` is how often that check runs. In
  the default setup, it runs every `60` seconds.
- `autopilot_green_phase_confirm_cycles = 2` means the enter condition must be
  true on `2` checks in a row. With a `60` second evaluation interval, that is
  roughly `2` minutes of confirmation.
- `autopilot_green_phase_release_cycles` works the same way for switching Green
  Phase off again.

Illustrative activation example:

- Assume the 30-day baseline is `1` profitable closed trade per hour.
- With `autopilot_green_phase_speed_multiplier = 1.5`, the recent window must
  reach at least `1.5` profitable closes per hour.
- Because the window is 60 minutes in this example, that means Moonwalker needs
  about `2` profitable closed trades within the last hour.
- With `autopilot_green_phase_min_profitable_close_ratio = 0.8`, those recent
  closes must also be mostly positive. For example:
  `2` profitable and `0` losing closes works, and `4` profitable with `1`
  losing close also works.
- If those conditions remain true for 2 checks in a row, and the checks happen
  every `60` seconds, Green Phase can turn on after roughly `2` minutes and
  temporarily add up to 2 extra deals, as long as the capital guardrails still
  allow it.

This example is illustrative. The real trigger always depends on your own
historical baseline from `ClosedTrades`, so the exact number of profitable
closes needed can be higher or lower in your setup.

The baseline is built from `ClosedTrades`, not from raw incoming signals. This
keeps the feature tied to realized trade flow instead of noisy signal bursts.

Green Phase only adjusts entry capacity in the current implementation:

- It can increase effective `max_bots`.
- It does not change TP, SL, or SL timeout.
- It does not replace normal Autopilot `low` / `medium` / `high` mode logic.

Before any extra deals are allowed, the service applies capital guardrails:

- It blocks expansion when locked funds are already above
  `autopilot_green_phase_max_locked_fund_percent`.
- It estimates remaining safety-order reserve for existing open trades.
- It requires enough free quote balance to cover that reserve plus the proposed
  additional deals.

This means Green Phase is intentionally conservative: market momentum alone is
not enough to open more deals unless capital protection still looks safe.

## TP Spike Confirmation

TP spike confirmation adds a debounce layer to normal take-profit exits. When
enabled, a trade is not sold immediately on the first price print above TP.
Instead, Moonwalker waits until the move remains valid for the configured time
window and, optionally, for a minimum number of ticker updates.

- `tp_spike_confirm_seconds` is the primary time-based filter.
- `tp_spike_confirm_ticks` is an optional extra filter.
- Stop-loss exits are not delayed by this feature.

This helps avoid selling into wick spikes that revert before the actual sell
order is placed.

## Limit Sell Timeout And Fallback

When `sell_order_type` is set to `limit`, Moonwalker places a limit sell at the
target price and waits for up to `limit_sell_timeout_sec` seconds.

If the order is not filled in time and `limit_sell_fallback_to_market` is
enabled, the bot may fall back to a market sell. That fallback is guarded:

- if TP was the reason for the sell, Moonwalker checks that the live price is
  still above the allowed fallback floor before sending the market order
- if the price has already dropped back below that floor, the market fallback is
  skipped and the trade remains open

This protection is meant to reduce exits at a loss after short-lived spikes.
