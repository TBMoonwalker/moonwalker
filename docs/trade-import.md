# Trade Import (CSV)

Moonwalker supports importing externally opened spot positions as **open trades** via CSV.

This is useful when positions were created outside Moonwalker and should be managed by Moonwalker DCA/TP logic afterward.

## Where in UI

Open `Trades` view and use the card:

- `Import Open Trades (CSV)`

This section is shown below the open/closed trades card.

## CSV Format

Delimiter is `;`.

Supported columns:

- `date;symbol;price;amount`

Header row is optional.

Examples:

```csv
date;symbol;price;amount
18/08/2025 19:32:00;BTC;117644.41;0.00099153
24/08/2025 15:04:00;BTC;112170.19;0.03863000
```

or (without header):

```csv
18/08/2025 19:32:00;BTC;117644.41;0.00099153
24/08/2025 15:04:00;BTC;112170.19;0.03863000
```

## Field Rules

- `date`: converted internally to unix milliseconds.
  - accepted: unix seconds/ms, ISO datetime, and common date formats (e.g. `DD/MM/YYYY HH:MM:SS`)
- `symbol`:
  - accepts `BASE/QUOTE`, `BASE-QUOTE`, or base-only (`BTC`)
  - base-only symbols are mapped to `BASE/<configured currency>` (example: `BTC` -> `BTC/USDC`)
- `price`: numeric, must be `> 0`
- `amount`: numeric, must be `> 0`

## Import Mapping

For each symbol:

- oldest row becomes `baseorder`
- all following rows become `safetyorder`
- `open_date` is the oldest row date
- imported rows are tagged with:
  - `bot = manual-import`
  - `side = buy`
  - `direction = long`
  - `ordertype = market`
- fees are set to:
  - `fee = 0`
  - `fee currency = configured quote currency`

Historical closed trades are not imported by this flow.

## Overwrite Behavior

The UI offers **Overwrite existing symbols**.

- disabled: import fails if any symbol already exists in open/trade records
- enabled: existing `Trades` and `OpenTrades` rows for imported symbols are replaced

Use with care. This action is intended for cleanup/reconciliation workflows.

## DCA/Strategy Notes

- Imported deals are eligible for normal DCA/TP processing.
- Safety order progression values are derived from configured DCA keys (`sos`, `ss`) to stay compatible with DCA logic.
- If no new safety order is created, check:
  - `dca` enabled
  - `mstc` (max safety order count) not reached
  - strategy gate outcome when `dynamic_dca` is enabled

## API Endpoint

The frontend uploads CSV as multipart form data to:

- `POST /trades/import/csv`

Form fields:

- `file`: CSV file
- `overwrite`: `true|false`

