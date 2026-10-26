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
- In Dynamic DCA, `ASAP` can optionally use `signal_strategy` as an extra entry filter.
- In accumulation mode, ASAP requires fixed symbols and opens with `bo` immediately,
  without a strategy signal or history warmup. The accumulation strategy controls
  subsequent buys. Account, budget and exchange execution checks still apply.
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

Fee-aware format (also accepted without a header):

```csv
date;symbol;price;amount;fee;fee_currency;amount_type;fee_quote_value
18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153;0.000001;BTC;net;
24/08/2025 15:04:00;BTC/USDC;112170.19;0.03863000;0.5;USDC;gross;
```

The first four columns remain required. Append `fee;fee_currency` for six columns;
`amount_type` and `fee_quote_value` are optional seventh and eighth columns.
`amount_type` defaults to `net`: already-owned coins after base-coin fees. For
`gross`, base-coin fees are deducted once. Quote fees increase acquisition cost;
base fees reconstruct the gross purchase cost when the amount is net. `price`
is the execution price before fees. An explicit zero fee is supported; blank fee
fields mean unknown fees, not zero. Negative fees and rebates are not supported.
Third-currency fees, such as BNB on BTC/USDC, require their actual total value in
USDC in `fee_quote_value` to calculate returns. Accumulation retains unvalued
third-currency fees with returns unavailable; Dynamic DCA rejects them until the
quote value is supplied. No historical exchange rate is guessed.

Dynamic DCA rules:
- Declared acquisition fees are counted once in the entry basis used for P&L,
  TP/SL and recovery sizing. A 100 USDC purchase with a 1 USDC fee has a
  101 USDC basis. Later exchange buys retain their own legacy fee estimate;
  that estimate is not reapplied to imported acquisition costs.
- Backups preserve whether a purchase cost already includes fees. Older CSV
  rows from the standard plugin's generated identifiers retain the same basis
  after an upgrade or restore; quantities and recorded costs are not rewritten.
- Oldest row per symbol is imported as base order.
- Following rows are imported as safety orders.
- Import is blocked when open trades already exist.
- Switching an already-running instance from another signal plugin to
  `csv_signal` is also blocked while open trades still exist.
- The plugin prefills missing history for imported symbols before it creates the
  restored trade rows.

In accumulation mode, CSV declares already-owned net inventory instead of
reconstructing Dynamic DCA base/safety orders. Fresh wallet ownership must cover
the complete net declaration. Four-column purchases retain unknown fees.
Fee-complete, quote-valued declarations enable returns based on those declared
purchases and fees, labelled separately from exchange-confirmed fills. Failed adoption needs
an explicit entry retry. See [accumulation setup](howto-operate-accumulation.md#adopt-coins-already-owned-with-csv)
and [recovery](howto-recover-accumulation.md).

Changing the source does not rewrite an already-adopted holding. Correct a staged
CSV before adoption; existing historical fees are never inferred or silently
applied again to a running position.

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
