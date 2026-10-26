# Why accumulation has its own lifecycle

Dynamic DCA builds and exits a deal. Accumulation keeps selected coins until an
operator authorizes a sale. Sharing indicators is useful; sharing automatic exit
rules would sell the inventory accumulation is intended to retain.

## The problem

Treating accumulation as an ordinary DCA deal would apply take-profit, stop-loss
or other automatic exits. Treating every signal as an independent buy would lose
the relationship between inventory, available capital and outstanding orders.
A lost exchange response could then create a duplicate purchase after restart.

Moonwalker shares the Strategy Builder, exchange buy/sell managers, exact
`ExchangeOrderReport` parser, private-fill fee hydration and `PlacementWorkflow`
submission journal. Strategy decisions and mode-specific accounting remain
separate: DCA manages deals and exits; accumulation manages owned inventory and
operator-authorized sales.

Both live and exchange demo orders are real exchange effects and use the durable
journal. A server-owned account/environment fingerprint is recorded before
submission and checked before recovery, including replay of saved results.
Changing credentials, hostname, sandbox or demo/live environment cannot replay an
order into another account. Historical unscoped DCA records remain unresolved
until ownership can be established; recovery does not invent a scope or rewrite
the original request.

## The approach

```text
ASAP fixed symbols                   CSV inventory declaration
        |                                      |
account and capital checks           ownership and inventory checks
        |                                      |
one base-order purchase              adopt existing coins (no purchase)
        +-------------------+------------------+
                            |
                 managed accumulation holding
                            |
              completed candles + pinned graph
                            |
             dip, spacing and dynamic sizing rules
                            |
               fresh shared capital admission
                            |
              journal -> exchange -> fill evidence
                            |
               exact inventory and fee accounting
                            |
                  next strategy opportunity

operator close -> block buys -> settle -> sell / archive verified dust
                                                 |
                                              stopped
                                                 |
                                       explicit reactivation
                                                 |
                                           new generation
```

The runtime is owned by one application lifespan. Watcher quotes, changed shared
balance observations, fills and operator actions wake it. Timers handle candle
boundaries, portfolio collection rounds and unresolved execution recovery. A wait
does not continuously enqueue itself. The dashboard receives snapshots and
changes through its accumulation WebSocket; it does not poll status on an interval.
The ASAP registration plugin retains its separate five-second scheduler.

### Why the first ASAP buy is different

ASAP is authorization to attempt the configured base order as soon as normal
execution checks pass. It does not require a dip, graph match, strategy warmup
or portfolio ranking round. Its fill has no invented ATR anchor.

After that fill, completed history initializes strategy observations. Before a
later purchase, the runtime freezes a spacing anchor from the base order's actual
gross execution price and the first fresh, validated completed-candle ATR. A
further decline or recovery followed by a fresh correction must satisfy the
configured ATR distances from that anchor, as well as the strategy conditions.
The anchor survives restart and prevents an older pending first-dip candidate
from bypassing spacing. Missing or unresolved fill evidence blocks further buys.
CSV starts from declared existing inventory instead, so it does not submit an
initial purchase or manufacture a base-order anchor.

### Why conditions and execution settings are separate

The shared graph answers whether market conditions match. Accumulation then
requires a declining completed close, peak discount and spacing/recovery rules,
and sizes the purchase from usable quote funds. Dynamic DCA can use the same
pure graph while retaining its own safety-order sizing and exit behavior.

The base candle interval follows Exchange configuration in live evaluation and
Backtest. A timeframe change rebuilds observations and invalidates unsubmitted
old-policy buys; it never backfills purchases. Explicit higher-timeframe graph
conditions remain pinned and must be compatible with the base interval.

Sizing grows with fresh downside from the preceding purchase anchor, rather than
the continuing discount from an old peak. Small additional declines retain a
small allocation even when the market remains far below that peak.

The **Downtrend / sideways accumulation** preset uses a completed 4h regime
filter and an EMA discount on the exchange base timeframe. The old standalone ATR presets are retired; existing
pinned versions remain readable for history. No indicator predicts the next move. Thresholds and indicator definitions are
in the [strategy reference](strategies.md#shared-strategies-for-dca-and-accumulation).

### Why a later buy can cost more

A decline is measured against the preceding completed close and strategy anchors,
not against every earlier execution. For example, a consumed strategy signal at
97 with an ATR of 2 can rearm after sufficient recovery. A later correction from
106 to 102 can qualify if the depth and other conditions also match. It is a
falling candle even though 102 exceeds the earlier 97 signal.

The strategy can also buy after a further decline without a recovery. An actual
purchase still needs a fresh ask no higher than the frozen signal price and all
execution checks. A displayed recovery rise is readiness for a later correction,
not a rising-price buy trigger. The first ASAP buy is independent of these rules.

### Why restarts do not reset purchase history

Observations and consumption are different records. Observations track completed
candles and recovery highs; consumption records that a confirmed positive fill
used an opportunity. Restart, resume and strategy changes rebuild observations
without buying old signals or clearing an existing consumption guard. A new
strategy version cannot bypass an unsettled order.

A full close followed by explicit reactivation is different: it starts a new
generation and deal. The old audit history remains, while the new ASAP cycle
receives its own base order. Old dust remains unmanaged rather than silently
joining the new inventory.

### Why unknown orders and dust remain visible

An unacknowledged submission can still have executed. Moonwalker keeps its
identity and commitment until exchange evidence settles it, rather than assuming
failure and placing another order. Commands use stable operation IDs plus
reviewed revisions so multiple dashboard clients cannot silently act on old state.

Dust is inventory too. After a full close, only fresh evidence of unsellability
permits archival. The archive transfers the exact remainder out of managed
inventory at its basis, without inventing a sale or realized loss. Uncertainty
keeps the holding in Closing.

## Trade-offs

- Completed candles and higher-timeframe warmup make decisions reproducible but
  delay reaction compared with intrabar price signals.
- Dynamic sizing spends more usable capital at deeper ATR discounts, but a long
  decline can consume available funds. There is no strategy cash reserve or
  fixed purchase-count limit.
- Shared-budget ranking prioritizes peak/ATR severity on the exchange base
  timeframe; lower-ranked symbols can wait indefinitely. This is not equal allocation.
- Evidence-based recovery prevents duplicate orders and invented profit, but
  requires operator attention when an exchange cannot supply complete evidence.
- Immutable strategy pins preserve a holding's reviewed behavior, but saving a
  new strategy does not update existing registrations automatically.

## Implementation map

| Boundary | Main implementation |
| --- | --- |
| ASAP/CSV registration | [accumulation/entry.py](../backend/service/accumulation/entry.py) |
| Single-owner orchestration | [accumulation/runtime.py](../backend/service/accumulation/runtime.py) |
| Pure dip calculations | [accumulation/strategy.py](../backend/service/accumulation/strategy.py) |
| Shared regime graph | [shared_accumulation.py](../backend/service/shared_accumulation.py) |
| Revision-checked proposals | [accumulation/evaluation.py](../backend/service/accumulation/evaluation.py) |
| Observation integrity | [accumulation/state.py](../backend/service/accumulation/state.py) |
| Dashboard notifications | [accumulation/status_events.py](../backend/service/accumulation/status_events.py) |

Use [the operating guide](howto-operate-accumulation.md) for actions,
[the recovery guide](howto-recover-accumulation.md) for blocked states, and
[the accumulation reference](accumulation.md) for exact contracts.


## Execution evidence and operator history

The shared workflow records acknowledgement before mode-specific accounting.
Acknowledgement is not proof of a fill: requested quantity, actual filled
quantity, cumulative quote cost, per-currency fees and terminal status remain
separate facts. Missing fees remain unknown; explicit zero fees are valid
complete evidence. Uncertain or cancelled submission is recovered by lookup,
never by blindly resending the operation.

Both modes report submissions and acknowledgements in the normal exchange/order
logs. Fill messages follow committed accounting; replaying unchanged accumulation
evidence does not emit another committed-fill message. Logs use allowlisted
identities and quantities rather than raw exchange payloads or exception bodies.

CSV imports adopt existing inventory without an exchange order. Their validated
purchase rows appear as CSV entries in the existing base/accumulation order
history, before subsequent native buys. The chart includes those purchase dates
and markers. Each receipt belongs to one deal, so closing and starting a new
holding cannot carry earlier purchase rows into the new cycle.
