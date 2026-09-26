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

Messages with `type: "keepalive"` are treated as connection control messages,
acknowledged with `{"type":"keepalive_ack","id":"<keepalive id>"}`, and do not
trigger trade validation.

### Pathfinder closed-trade feedback

With `websocket_signal` selected, enable **Send trade feedback** in Signal
settings, or set `"feedback_enabled": true` in `signal_settings`. It defaults to
false. Both live and CCXT demo trades are eligible. Feedback is sent only for
newly closed deals with persisted WebSocket signal provenance, while this
plugin is selected and the option is enabled. There is no historical backfill.

Moonwalker posts to `/v1/feedback/closed-trades` on the WebSocket URL's origin
(`wss` becomes `https`, `ws` becomes `http`). It uses the existing Authorization
header, or the WebSocket URL's `token` query parameter as a bearer credential.
Credentials are not stored in the outbox, and HTTP redirects are not followed.
The destination is recorded with the signal so changing providers cannot route
old deals to the new provider.

A final close and its immutable feedback payload are committed together. The
`tradefeedback` table retains delivery state across restarts: `pending`, `sent`,
`rejected`, or `blocked`. Network errors, HTTP 429, and server errors retry with
bounded exponential backoff. A matching accepted acknowledgement completes the
receipt, including Pathfinder's `created:false` duplicate response. Other HTTP
errors are retained as rejected with the status code in `last_error`; correct
the underlying authentication/scope/contract problem before explicitly resetting
such a receipt to `pending`. Payloads must not be edited after submission.

Disabling feedback or selecting another plugin pauses queued sends. Re-enabling
feedback for the same provider resumes pending deliveries. Deals closed while
feedback is disabled are not queued. Partial sells and unsellable remainders do
not independently generate a final outcome.

Net results use execution cash flows and recorded CCXT fees, including DCA buys
and partial sells. Base-asset buy fees already reflected in reduced inventory
are not deducted again. Missing fee data, unsupported third-asset fee valuation,
or invalid accounting blocks delivery rather than labelling a gross result as
net. Such deals remain in the local outbox with a diagnostic in
`backend/logs/feedback.log`. Existing deals without the new provider provenance
are skipped. Incomplete execution history, when fee accounting is available,
is reported as incomplete so Pathfinder can exclude it from quality statistics.

Pathfinder currently has no demo/live discriminator in this request contract;
its quality totals therefore include both modes when submitted with the same
client credential.
