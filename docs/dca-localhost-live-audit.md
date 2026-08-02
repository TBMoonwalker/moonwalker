# DCA Localhost Live Audit

Date: 2026-07-28

## Scope

This audit validated the current branch against the local Moonwalker database
and a local application instance bound to `127.0.0.1:8150`. The existing
instance at `http://192.168.6.5:8150` runs the older code and was not modified,
restarted, or used as the verification target.

The audited local configuration had dry-run and DCA enabled, used dynamic DCA
mode on Binance USDC markets, and used a four-hour timeframe.

## Persistence and Ledger Results

SQLite reported `integrity_check: ok`. The audited database contained:

- 20 open trades and 462 closed trades;
- 21 active trade rows and 1,003 canonical execution rows;
- 482 base-order buys, 44 safety-order buys, 15 partial sells, and 462 final
  sells;
- 56,492 archived replay candles;
- seven applied schema migrations.

All open and closed trade summaries had deal IDs. The 19 open deals with
complete execution histories matched their ledgers for total amount, total
cost, and safety-order count. All 461 closed deals with complete execution
histories had a base order, exactly one final sell, and a matching safety-order
count.

The open SEI deal provided a concrete DCA check. Its base order plus one safety
order summed exactly to:

- quote cost: `56.804204`;
- asset amount: `1155.30142`;
- safety-order count: `1`.

The active trade summary reported the same values. This confirms that the
changed DCA mechanism persists and aggregates an actual safety-order fill
correctly.

The DASH deal had a partial sell and was explicitly marked
`execution_history_complete = false`; incomplete history was therefore not
silently treated as authoritative.

Three older closed deals (PENGU, GMT, and CGPT) sold marginally more asset than
their recorded buys. Their quote and profit arithmetic remained internally
consistent, and the differences match legacy precision, fee, or dust behavior
rather than the current DCA aggregation path.

## Historical Data Results

Every one of the 462 closed deals had a replay archive. Archives contained
between 15 and 3,125 candles, bracketed their deal interval, and had:

- no duplicate timestamps;
- no invalid OHLCV rows;
- consistent replay and indicator API responses.

The closed-trade length endpoint returned 462, the latest STX summary matched
the database, and the execution, replay-candle, and indicator endpoints matched
their stored records.

## Browser and Responsive Results

Desktop checks passed for open trades, closed-trade replay, and statistics
without browser errors. Mobile checks passed for statistics and closed trades
without global overflow.

Two responsive defects found during the audit were fixed:

1. the non-key expansion column was dropped when mobile columns were selected;
2. stale positional `colgroup` widths overrode the mobile widths and expanded
   a 325-pixel table to 442 pixels.

At a 375-pixel viewport, the SEI row now expands and displays both “Base order”
and “Safety order 1”. Its historical view loads 200 OHLCV/indicator records,
renders seven canvases, reports no console errors, and keeps the document width
at 375 pixels.

## Runtime Boundary and Shutdown

The local listener was verified on `127.0.0.1:8150` only. A managed
`./run.sh stop` sent `TERM`, completed Litestar shutdown normally, removed the
PID/lock state, and left no listener on port 8150. The local server remains
stopped after this audit.

## Conclusion

The current DCA mechanism behaves consistently across actual trade ledgers,
open/closed summaries, replay history, APIs, and the rendered dashboard. No
current-branch DCA accounting defect was found. Legacy incomplete or
precision-affected histories remain explicitly distinguishable from complete
canonical ledgers.
