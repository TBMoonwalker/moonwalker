# Signal Plugins

Moonwalker currently supports four signal plugins selected via the `signal`
config key:
- `sym_signals`
- `asap`
- `csv_signal`
- `websocket_signal`

Plugin-specific settings are passed through `signal_settings`.

## SymSignals Setup
Example value for `signal_settings`:
```json
{"api_url":"https://stream.3cqs.com","api_key":"your api key","api_version":"v1","allowed_signals":[66]}
```

## ASAP Setup
Select `asap` in the signal field and provide `symbol_list` as:
- A comma-separated list, or
- A URL returning `{"pairs":[...]}`

Notes:
- `ASAP` can optionally use `signal_strategy` as an extra entry filter.
- When the strategy or dynamic DCA needs history warmup, Moonwalker will prefill
  missing history before watching a symbol.
- The symbol-list URL is fetched through async HTTP and should return a plain
  JSON object with a `pairs` array.

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
- Switching an already-running instance from another signal plugin to
  `csv_signal` is also blocked while open trades still exist.
- The plugin prefills missing history for imported symbols before it creates the
  restored trade rows.

## WebSocket Signal Setup
Select `websocket_signal` in the signal field for a plain WebSocket feed that
publishes JSON trade decisions. Set `signal_settings` like:

```json
{
  "websocket_url": "wss://signals.example.com/stream",
  "accepted_market_states": ["healthy"],
  "min_confidence": 50
}
```

Optional settings:
- `headers`: JSON object with additional connection headers. Omit this when
  authentication is carried in the URL, for example
  `ws://localhost:8000/v1/signals/stream?token=dev-token`.
- `subscribe_message`: JSON object, array, or string sent once after connect.
- `required_decision`: decision value that opens a trade. Defaults to
  `take_trade`.
- `accepted_exchanges`: exchange ids accepted from payloads. Defaults to the
  configured `exchange`.
- `accepted_market_states`: allowed `market_state` values. Omit to accept all.
- `reconnect_delay_seconds` and `max_error_reconnect_delay_seconds`: reconnect
  tuning.

Incoming payloads must include a compact or slash-separated `symbol`, a matching
`exchange`, `decision: "take_trade"`, numeric `confidence`, and a non-expired
`expires_at` when that field is present. The plugin records the signal payload in
trade metadata, de-duplicates `signal_id` or `sequence`, and uses the same
Moonwalker admission, max-bot, BTC pulse, allowlist, denylist, history warmup,
and order-sizing flow as the other signal plugins.

Messages with `type: "keepalive"` are treated as connection control messages and
do not trigger trade validation.
