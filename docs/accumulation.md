# Accumulation mode

Accumulation builds a managed holding with strategy-driven purchases and explicit
operator sales. Select **Accumulation** in Configuration, then pin a compatible
saved strategy version. Dynamic DCA remains a separate lifecycle.

There is no purchase-count limit, mandatory strategy cash reserve, automatic take
profit, stop loss, trailing exit, timeout sale or Autopilot liquidation. Newly
available funds can be spent while accumulation is enabled. A prolonged decline
can consume most of the available budget. Pause Moonwalker or a registration to
block new buys; reconciliation and explicit sales remain available.

## Documentation paths

- Learn through the [backtest tutorial](tutorial-accumulation-backtest.md).
- Start, pause, switch and sell with the [operating guide](howto-operate-accumulation.md).
- Resolve blocked work with the [recovery guide](howto-recover-accumulation.md).
- Understand [lifecycle and price anchors](explanation-accumulation-lifecycle.md).
- Integrate using the [API reference](api.md#accumulation).

The sections below describe the current contracts and limits. A saved strategy
version is an immutable pin, not an automatically updated strategy name.

## Set up a holding

1. Use spot markets and enable trade mode management. Disable Autopilot.
2. Select ASAP with a fixed symbol list, or CSV Signal for coins already owned.
   Symbols must use the configured quote currency. URL-based ASAP lists and other
   signal plugins are not supported for accumulation.
3. Select **Downtrend / sideways accumulation** as the initial strategy in
   Configuration. This shared built-in exists before setup is complete; creating
   a custom variant is optional. Its starting parameters are experimental and
   not performance optimized. Duplicate it in Strategy Builder to customize it.
4. ASAP uses the existing **Base order amount** (`bo`) for the first purchase,
   just as in Dynamic DCA. Later purchases use dynamic accumulation strategy
   sizing. Save the configuration. An incomplete draft may omit the strategy pin.
   Demo and live execution require credentials, an exact compatible pin and
   successful ownership and market checks. The ASAP base order does not require
   strategy candle warmup; subsequent purchases do.
5. Manage the registration from **Open trades** in Trading Overview.

The dry-run switch routes accumulation to the exchange demo trading environment,
using CCXT demo support, demo credentials and demo wallet funds. Unsupported demo
venues fail closed; there is no fallback to a live account. A fully configured
ASAP registration opens with its configured base order in demo mode. An incomplete draft
without credentials or a strategy cannot trade. Demo and live ownership are
separate: changing modes cannot reuse or rebind the other environment's holdings
or orders. Use separate installations/databases when keeping demo history alongside live trading.
Use **Backtest → Accumulation** for an isolated simulation without
an exchange account. Creating a strategy does not itself submit a purchase.

ASAP immediately opens a managed holding with the configured base-order amount.
The first order does not wait for a dip, candle close, strategy history or portfolio
ranking window. Account ownership, available budget, global pause, exchange
minimums and order precision still apply. The durable order journal prevents
repeat submissions after restarts or uncertain exchange responses. Once the first
fill is recorded, the selected accumulation strategy initializes its observations
and controls subsequent purchases. Unrelated wallet coins remain unmanaged. CSV declarations use
`date;symbol;price;amount`, with each row representing already-owned inventory.
The entire declaration is staged before adoption and must fit fresh free wallet
balance. Optional fee columns support base, quote and explicitly quote-valued
third-currency fees. `amount` defaults to net owned coins; `amount_type=gross`
deducts base-coin fees once. Four-column purchases retain unknown historical fees.
See the [CSV format](signals.md#csv-signal-setup).
The runtime continues pending, unadopted ASAP entries when it starts or receives
updated inputs, using the same operation ID. A recovered entry then opens its BO;
it does not wait for a strategy signal. Explicitly stopped, quarantined or
account-mismatched entries do not resume automatically. CSV ownership validation
still requires an explicit retry after a failed check.

Changing the global entry mode requires no open holdings, non-stopped
registrations or unresolved orders. Pause an already-live instance first. The
server drains order work and rechecks these conditions when saving.
Pending accumulation commands and reserved opportunities also block the switch.
After a settled switch to Dynamic DCA, a stopped, empty registration no longer
blocks a new DCA trade for its symbol. Its accumulation history remains recorded;
switching back to accumulation retains the explicit-reactivation requirement.

Authenticated balance reads must complete within ten seconds. For Binance spot,
CCXT copies the last account update (`info.updateTime`) into the balance timestamp;
that timestamp is not the time the response was fetched. When those fields match,
Moonwalker measures freshness from the balance request instead. Slow requests,
future timestamps and unrecognized stale evidence still block trading.

## Monitor a holding

The **Order status** column shows the current buy wait and any available target
price/percentage. A recovery rise is shown separately as a readiness reset,
never as a buy target: a fresh correction must follow before another buy can
qualify. Use the usual **Sell** and **More** row actions, or expand the
trade. The order card beside the chart shows the detailed next-buy condition.
The expanded details show executed orders and any required action controls.
The row actions are the single home for pausing, resuming, partial sales and closing. **Sell part** reveals an exact base-asset
quantity field and a reviewed confirmation; it does not sell on the first click.
Entry registration and blocked entry messages
appear in Open trades until there is an owned holding.

The **Base order** and **Accumulation order** entries use the same compact
history layout as Dynamic DCA: order size, amount, price and execution time.
Manual sales appear as executed orders too. Holding summaries, inventory snapshots
and activation/retry requests are excluded from this history; their accounting
and audit records remain stored. Unknown execution values stay explicitly unknown.
Reviewed action controls sit outside the timeline in the same order card.
Strategy information belongs in Configuration, without a repeated label below
the order history.

The dashboard uses the existing **Portfolio exposure** card without separate
accumulation holdings or valuation sections. Registrations without an open
trade, including stopped records, remain expandable in Open trades with the same
order timeline. Utilities contains no accumulation management.
Strategy selection and changes live only in **Configuration → Trade modes**.
The initial version is the default for new registrations. Expand **Change strategy
for an existing registration** there to review and apply a different saved version
to one existing registration; the same control can retry a staged entry with a
replacement version. Utilities and trade cards do not change strategies.
Issue links open the affected symbol in Open trades. If that symbol cannot be
loaded, the screen reports the error instead of selecting a different holding.

## Operator actions and retries

Each action carries a stable operation ID, the displayed activation revision and
its full reviewed payload. An identical retry returns the recorded outcome.
Reusing an ID for different content or submitting a stale revision is rejected.
The dashboard retains an uncertain request across reloads and offers **Retry same
request**; it never automatically resubmits it under a new ID.

- **Pause** immediately blocks new purchases and settles outstanding purchases.
  Unknown acceptance remains an obligation until reconciliation proves its state.
- **Resume** revalidates the account, inventory, strategy and current candle
  baseline before allowing purchases.
- **Switch strategy** selects an exact immutable version. It settles outstanding
  buys, rebuilds observations from the current market and retains execution
  consumption and purchase guards. A paused registration stays paused.
- **Sell part** authorizes an exact base-asset quantity and must retain positive
  inventory. After settlement it restores the previous explicit pause state.
- **Close holding** blocks buys and sells managed inventory. Once orders and fees
  are settled, fresh exchange checks automatically move a remainder below precision
  or the sale minimum to **Unsellable trades**, preserving its exact accounting.
  The registration becomes **Stopped**. Uncertain orders or missing evidence keep
  it in **Closing**. No coins are bought to meet a sale minimum.
- **Retry remaining sale** is a new explicit authorization after the previous sale
  has complete terminal accounting. Sellable remainders require this explicit retry;
  unsellable dust is archived automatically. An adopted registration with no
  recorded inventory or unsettled execution can be closed without submitting an order.
- **Reactivate** explicitly starts a stopped, previously adopted registration's
  next generation and readiness check. Plugin polling does not reactivate it.

The first entry check runs automatically. Staged entries that have not completed
it have **Retry entry check**, **Correct CSV**, and **Abandon entry**. Retrying
checks exchange access, ownership, strategy and market history. The check itself
does not submit an order; the runtime executes eligible purchases afterward.
For ASAP, successful validation permits the immediate base order without a
strategy signal. For CSV, validation adopts the declared inventory before
strategy-driven buying. Correction stays paused until explicitly validated. Abandonment leaves the coins
unmanaged and the registration stopped, without selling. A never-adopted abandoned
entry can later be explicitly validated again or given a corrected CSV declaration.
A compatible replacement strategy can be reviewed in Trade modes configuration;
changing the global initial pin never changes existing registrations.

## Buying strategy and capital

Dynamic DCA backfill and accumulation use the same source-qualified completed
history window layer. Identical windows coalesce within the instance; complete
windows are retained for at most 60 seconds in a bounded cache. Venue, account
configuration, market, demo/live mode, timeframe and candle boundary qualify the
request. Incomplete evidence is retried rather than cached. Existing unqualified
ticker rows cannot substitute for accumulation's strict contiguous history.
Authenticated exchange clients keep their existing owners. This changes neither
the immediate ASAP base order nor the fresh startup baseline.

The existing capital service owns reservation locking and exposes immutable
reservation and usage snapshots. Accumulation uses its public guard with the
existing lifecycle → capital → database lock order; exchange calls stay outside
that guard. Mode-specific sizing and safety-order reserve policies remain with
their respective trading engines.


The initial implementation is `accumulation_dip_v1`, with configurable immutable
variants. The completed-candle base interval follows **Exchange → Timeframe**
for live trading, warmup, portfolio ranking and Backtest. The peak reference is
168 preceding candle highs, and volatility is Wilder ATR14. It requires an exact,
contiguous bounded history window with deterministic initialization. Forming,
missing, unordered or misaligned candles cannot produce a buy.

A qualifying decline must close below the previous close and reach at least
1.5 ATR below the rolling peak. After a consumed signal, another purchase needs a
further decline of one ATR, or a recovery followed by a fresh correction. The
spacing unit uses the larger of the preceding signal ATR and current ATR, so a
longer timeframe or higher volatility cannot reuse an old, smaller spacing unit. For ASAP, these distances also apply after the immediate
base order: its actual gross fill price becomes the first anchor, with ATR frozen
when fresh completed strategy data becomes available. The original ASAP request
retains its zero ATR; no candle history is needed to submit that base order.
Restarts preserve the anchor. CSV imports without an ASAP base order retain the
first qualifying dip behavior. There is no extra elapsed-time cooldown. Only a confirmed
positive fill consumes an opportunity; partial and duplicate reports cannot
consume it twice. Warmup, resume, restart and switching observe historical candles
without backfilling purchases.

Default sizing starts at 2% of usable funds. It adds three percentage points per
ATR of fresh decline beyond the spacing distance, capped at 20%. Follow-up size
uses downside since the preceding consumed purchase, not the total discount from
an older peak. The first CSV strategy buy uses its preceding completed close;
corrections above the preceding purchase retain the minimum fraction. Strategy settings
control these fractions; the engine does not impose a separate accumulation
reserve. Amount and price precision can reduce execution, but cannot top up a
small request to an exchange minimum or enlarge it to fit a budget.

Multiple symbols share the existing capital pool. A five-second collection round
ranks candidates by the same peak/ATR severity on the exchange base timeframe,
then creation time and symbol. Lower-ranked symbols can starve; this is not equal allocation.
Admission refreshes account, quote, exchange holds and shared capital before each
selection. Ordinary DCA leases and unresolved placements count against the same
pool. Accumulation receives no future DCA safety-order reserve.

The capital cap, execution buffer, spendable wallet funds, fee uncertainty and
unresolved commitments remain authoritative. Already-accounted partial-fill cost
is not counted twice as pending capital. Unknown imported basis blocks capital
calculation. Existing holdings in another quote also block capital admission;
the engine never implicitly converts their cost. Quotes and wallet evidence must be current, and admission rechecks
the ledger after network reads and lock waits. Global pause is checked at
candidate evaluation, admission and the final submission claim. When delisting
protection is enabled, accumulation buys use the same shared exchange schedule
and market checks as Dynamic DCA. Scheduled delistings and unavailable required
schedule evidence block new buys; the final claim rechecks the cached decision
without network I/O inside the database transaction. Explicit sales remain available.

## Strategy execution parameters

These defaults apply to the execution settings of the shipped
downtrend/sideways graph. Custom versions persist a complete parameter
set; missing or unknown fields are rejected. Decimal values are serialized as
strings in strategy documents. Graph conditions are additional requirements,
not replacements for these execution rules. Decimal strings must be finite,
at most 128 characters, and have an absolute decimal exponent no greater than 128.
All six decimal parameters must be strictly positive.

| Parameter | Type / constraint | Default | Effect |
| --- | --- | --- | --- |
| `timeframe` | Stored compatibility field | Exchange configuration | Live and Backtest use the exchange base interval; immutable saved rows retain their original value. Weekly candles use Monday alignment. |
| `peak_length` | Integer, 2–1000 | `168` | Preceding candle highs used for the peak, excluding the current high. |
| `atr_length` | Integer, 2–100 | `14` | Wilder average true range period. |
| `entry_atr` | Positive decimal string | `"1.5"` | Required peak-to-close discount in ATR units. |
| `spacing_atr` | Positive decimal string | `"1"` | Further-decline or fresh-correction distance. |
| `recovery_atr` | Positive decimal string | `"1"` | Recovery distance needed to rearm a correction path. |
| `min_fraction` | Positive decimal string | `"0.02"` | Fraction of usable funds for a small eligible fresh decline. |
| `slope` | Positive decimal string | `"0.03"` | Added fraction per fresh ATR beyond buy spacing. |
| `max_fraction` | Decimal string, `min_fraction <= max_fraction <= 1` | `"0.20"` | Maximum fraction requested per opportunity. |

Base history length is `max(252, peak_length, 18 * atr_length) + 1`, or 253
candles at the defaults. Shared graph requirements can increase it; the shipped
regime graph requires 1,240 base candles at 1h or 310 at 4h. The complete graph warmup is bounded
at 12,000 base candles.

Peak-to-close discount determines eligibility and portfolio priority. It does
not repeatedly force maximum allocation while price stays below an old high.
For each eligible purchase, sizing uses:

```text
anchor = preceding purchase signal price (preceding close for the first CSV dip)
ATR unit = max(current ATR, preceding purchase ATR), or current ATR before first buy
fresh depth = max(0, (anchor - signal close) / ATR unit)
fraction = min(max_fraction, min_fraction + slope * max(0, fresh depth - spacing_atr))
requested quote = fraction * usable quote
```

At the default settings with 1,000 usable quote units, fresh declines of 1, 3
and 7 ATR request 20, 80 and 200 units. A small new decline does not receive the
maximum merely because the rolling peak remains far above price. ASAP still uses
`bo` for its initial purchase.

Changing the exchange timeframe discards queued evaluations and rebuilds
observations before another strategy signal. It waits when the new completed-bar
boundary predates the previous baseline, rather than replaying missed purchases.
Already submitted orders are reconciled normally; unsubmitted requests using an
old timeframe or sizing policy cannot submit. Explicit indicator timeframes stay
part of the saved graph and must be compatible higher multiples of the new base.

The next buy is not required to be below the base order or all previous fills.
A recovery and new correction can qualify above an earlier signal. See
[price anchors](explanation-accumulation-lifecycle.md#why-a-later-buy-can-cost-more)
and the [shared condition graph reference](strategies.md#shared-strategies-for-dca-and-accumulation).

## Lifecycle state reference

| State | Meaning |
| --- | --- |
| `validating` | Entry or lifecycle readiness checks are not complete. |
| `enabled` | Eligible for evaluation, subject to pause, data, account and capital checks; it does not promise a buy. |
| `paused` | New buys are blocked until explicit validated resume. |
| `blocked` | A lifecycle/integrity condition prevents buying. |
| `switching` | Outstanding buys are settling before a new pinned strategy is initialized. |
| `selling_partial` | An explicit partial sale is settling; new buys wait. |
| `closing` | Full close is latched; buys remain blocked until settlement and sale or verified dust archival finish. |
| `stopped` | The cycle has ended or entry was abandoned. Plugin scheduling cannot reactivate it. |

Runtime reasons such as `WAIT_REBASE`, `WAIT_CONDITIONS`, `WAIT_DEPTH`,
`WAIT_PRICE`, `WAIT_BUDGET` and `WAIT_ORDER` refine the state; they do not replace
it. The [operating guide](howto-operate-accumulation.md) covers the normal actions;
the [recovery guide](howto-recover-accumulation.md) maps blockers to repairs.

## Recovery and inventory repair

Repairs always preserve exact monetary evidence, immutable strategy pins and
purchase guards. No repair silently enables buying or transfers coins.

**Reconcile restored order** looks up the existing exchange/client order identity.
Complete terminal quantity, cost and fee evidence is required. If the normalized
order omits fees, the server can retrieve at most 1000 authenticated executions
for that exact order. Unique execution IDs, symbol, side, order ID and complete
filled-quantity coverage must match before their fees become known. Missing,
partial or conflicting coverage stays unresolved; it is never zero fees. Recovery
never resubmits an order whose acceptance is uncertain.

Native UUID-based placement IDs can reconstruct their deterministic client ID
when stored lookup fields are missing. Under changed credentials, signed exchange
evidence must match that native client identity before account binding changes.
An exchange order number or similar wallet balance alone is not account proof.

**Retire interrupted command** cancels only an unplaced quarantined intent. It
retains the original declaration and inventory. Retiring a close retains Closing;
a separate new retry must authorize a sale. **Acknowledge recorded sale settlement**
handles a restored command whose completed placement and complete accounting
already exist. It checks the latest inventory checkpoint and changes only command
metadata, with no exchange lookup, submission or cancellation.

**Revalidate rotated API key** proves a settled native holding against its first
and latest order anchors and fresh free wallet inventory. It pauses before reads
and rechecks the account, revision and complete snapshot before committing. The
binding changes only when signed native identities, cumulative totals and fees
match. Shared-base ambiguity, conflicting ownership or unresolved original-account
work blocks the operation.

**Declare ownership under changed credentials** is a separate explicit operator
declaration for CSV or otherwise unverifiable settled inventory. Type the complete
symbol and a reason, then review the action. Fresh free wallet balance must cover
the recorded coins. The declaration does not prove original-account identity;
return history becomes unverified. It retains quantity, cost, fees, pins and
purchase guards, and leaves buying paused. Closing and Stopped remain latched.

**Restore recorded inventory link** reconstructs a missing holding or relinks an
intact row from the latest server-held fill checkpoint, audited correction receipt
or validated CSV declaration. The request cannot supply quantity or cost. Fresh
wallet coverage and consistent evidence are required. Conflicting managed coins,
unknown provenance or inconsistent audit records require restoration of a complete
backup rather than guessed inventory. Closing remains latched.

**Correct managed inventory** is an explicitly paused declaration of an addition
or partial removal, checked against fresh free wallet inventory. Added acquisition
cost can be known or explicitly unknown. Removals allocate proportional remaining
weighted cost and must retain positive quantity. Corrections never clear a holding
or Closing dust, trade coins, or masquerade as exchange fills. Before/after exact
amounts and the operator's reason remain in the journal; return history becomes
unverified. Historical CSV fee uncertainty can remain declared, but incomplete
native executions must first be reconciled.

If startup finds only paused, quarantined accumulation obligations, it can serve
**recovery only**: status/strategy reads and explicit reconciliation, settlement
acknowledgement or interrupted-command retirement. Trading workers, watcher,
signal plugins, configuration writes and websocket feeds remain stopped. Restart
after repairing the obligations. Mixed or unknown unresolved DCA work retains the
fatal startup gate; recovery access does not bypass it.

## Backup and restore

Full backup schema 3 preserves six accumulation audit tables, exact inventory,
placements, execution history and every referenced immutable strategy document,
including the initial configured pin. Original IDs and relationships survive.
Missing dependencies, inconsistent ownership, invalid execution links and strategy
ID/content conflicts reject restore atomically.

Restore forces paused dry-run configuration. Nonterminal exchange work and
interrupted commands are quarantined. Explicit account/inventory validation and
repair are required before resuming; an unresolved commitment is never cleared
just to make a symbol runnable. Config-only restore leaves the registry untouched
and clears the initial strategy pin because a numeric ID alone is not portable.
Schema 1/2 backups retain compatibility for their original data.

## Value, return history and scale

Routine valuation reads completeness flags and the latest checkpoint for all
registrations in one database query. SQLite returns at most one checkpoint
summary per registration, including stopped registrations; latest evidence is
ordered by update time and then checkpoint ID. Lifetime fill rows are not loaded
into Python for routine snapshots.


The reporting API groups exact remaining cost by quote currency. Unknown cost
stays null, with a separate known subtotal. Order reporting retains cumulative
per-order quantities, costs, fees and inventory checkpoints, including fully
closed holdings; it is not a list of assumed incremental fills.

In Statistics, the accumulation report shows managed coin quantities, remaining
basis and current bid values, followed by a paginated activity list. Activity
separately labels cumulative exchange-order summaries and CSV declarations. If
an order is corrected or other activity changes while paging, the list reloads
automatically. The report selector changes the view only; the live
trading mode remains unchanged.

The `/accumulation/performance` API uses bids at most ten seconds old, before
future sale fees. The dashboard has no separate valuation refresh control.
A shared cache lasts at most two seconds and expires before its marks. No legacy
float price or foreign-exchange conversion is guessed. Market value can be known
while historical return is unknown; a missing bid does not make inventory worthless.

Realized return is disposal proceeds plus remaining basis minus total acquisition
cost including recorded quote fees. Unrealized return is remaining bid value
minus remaining basis. Native coverage requires complete terminal fee evidence,
consistent ledger totals, intact ownership and verified history. Fee-complete CSV
purchases can also establish a declared acquisition basis, retained in their
cycle-bound adoption receipt without inventing exchange executions. These returns
are labelled as including CSV-declared costs and fees. Missing CSV fees, external
unvalued fees, ownership declarations and inventory corrections remain explicit
unknowns. Dated execution deltas must reconcile with cumulative returns before
entering charts. Verified single-quote native returns join Dynamic DCA totals;
incomplete evidence or mixed quotes keeps overall figures unavailable and labels
Dynamic DCA-only chart history.

Return totals and UTC daily rows are rebuildable caches updated in the fill
transaction. Portable backups exclude them. Missing caches rebuild from immutable
history under drained maintenance in batches of at most 1000 rows. Routine
valuation and admission do not materialize lifetime fills; they use compact
registration totals and indexed coverage/latest-checkpoint queries. Regression
fixtures exercise 10, 1000 and 100000 retained execution and zero-fill rows, with
bounded routine result sets. Registry/history pages are capped at 100 records.
The quote-currency summary includes lifetime contributed quote amounts before
fees and current remaining basis. Contributions include verified CSV declarations;
incomplete accounting evidence makes the affected total unavailable. Remaining
basis is unavailable when managed ownership or basis cannot be verified.

## Historical strategy comparison

Open **Backtest**, select **Accumulation** as the trade mode and choose an exact
saved strategy version. The existing symbol picker, date range, Run action,
market chart and result tabs are shared with Dynamic DCA. The timeframe comes
from Exchange configuration, matching live accumulation. Set initial funding, fee, adverse buy slippage in basis
points and the fixed DCA comparison interval. Market history, including warmup,
is fetched automatically from the exchange; no candle paste is needed.
The 20000-candle limit includes warmup. Only completed bars are evaluated.

The summary shows buys, coins accumulated, spending including fees, remaining
cash, ending value and drawdown. **Trades** shows buy executions without fabricated
exits or realized profits. **Comparison** shows accumulation, buy-and-hold and
fixed-interval DCA with equal funding. Run metadata and modeling caveats remain
in the same result workspace. Chart markers and execution rows show at most 100
buys; totals include every buy. This tests the strategy after warmup, independently
of an ASAP initial base-order signal. The isolated `/accumulation/replay` API
remains available for supplied candle data.

The isolated simulation uses the same pure market, observation, signal and sizing
functions as live accumulation. Signals execute at the next supplied candle open;
no future candle influences a prior signal. Accumulation, buy-and-hold and
fixed-interval DCA receive identical initial funding after warmup. Results include
units, spending including fees, fees, remaining cash, ending marked value, maximum
sampled drawdown and purchase count. Missing intervals cancel pending buys and
require contiguous warmup before new signals. Fixed DCA keeps its calendar
schedule and skips missing execution candles. The report discloses gaps and limits.

The simulation never reads a wallet or submits an order. It assumes constant
adverse slippage and quote-denominated fees, excludes future sale fees, exchange
precision/minimums and liquidity constraints, and can contain survivorship bias
from historical symbol selection. It is a comparison tool, not validation of
future profitability.

## Runtime and maintenance contracts

One lifespan-owned runtime coordinates accumulation in Moonwalker's single-node,
single-instance model. Multiple dashboard clients use the same durable command
journal. Dynamic DCA runs normally without initializing accumulation credentials
when no native registration exists. Legacy DCA order, pause, importer and automatic
exit paths reject accumulation ownership before executing their own logic.

Process-local hints carry no prices, balances or credentials. Changed watcher
quotes dirty registered symbols; successful changed shared balance observations,
committed fills and operator actions wake the owner. Quote/wallet bursts coalesce
to at most one extra wake per five seconds. Fresh admission is still mandatory.
There is no new private wallet stream: external deposits become visible when the
existing balance reader refreshes. Shutdown detaches the subscriber and preserves
uncertain placements for lookup-only recovery.

Tests use simulated exchange transports and isolated SQLite databases. No
actual-money acceptance transactions are required or performed. Repository-wide
security/dependency release gates remain separate from feature verification; see
[TODOS](../TODOS.md) for recorded release blockers.

### Live waiting status

The compact overview shows the current unmet entry or next-buy condition. When
market observations are available, it includes a target price and the required
percentage move from the latest completed strategy candle. A recovery target
still requires a subsequent fresh correction. Execution-price waits use the
fresh ask instead. Levels are snapshots of the current ATR/peak/guard calculation,
not guaranteed orders, and can change at the next candle. Invalid, expired or
revision-mismatched observations do not produce a price level.

The dashboard loads an initial REST snapshot and subscribes to
`/accumulation/stream?symbol=BTC%2FUSDC`. The stream sends an initial snapshot and
coalesced runtime/lifecycle changes to each connected client. There is no browser
status-polling interval; reconnecting obtains another snapshot. A disconnected
stream makes actions stale until a fresh snapshot or explicit refresh succeeds.
Runtime candle-boundary and execution-recovery timers are separate from dashboard
updates. Repair-only startup retains explicit HTTP refresh and recovery controls;
its `stream_available` flag is false because ordinary WebSockets remain disabled.

The current wait and executed orders belong to the expanded Open trades entry.
Row actions own pause, sales and reactivation; required recovery controls appear
in the same trade information. Strategy assignment is only in Configuration,
strategy editing is in Strategy Builder, and simulation is in Backtest. There is
no separate accumulation management area in Utilities.

### Shared Strategy Builder

Accumulation strategies now use the same [Strategy Builder](strategies.md#shared-strategies-for-dca-and-accumulation)
as Dynamic DCA. The inspector contains accumulation execution settings alongside
the shared graph. The retired standalone **Accumulation dip** presets no longer
appear in either strategy selector or the builder library and are no longer
seeded. Their saved versions and holding pins remain readable for historical
accounting and recovery. The downtrend/sideways preset filters subsequent buys;
it does not delay
the initial ASAP base order. Strategy assignment remains in Configuration.

### Archive an unsellable closing remainder

After a full close, Moonwalker automatically archives a remainder that fresh
wallet, order-book and market precision information proves unsellable. This also
runs when the worker resumes a previously stuck Closing trade, including a retry
that never placed an order because the remainder was already below the minimum.
Earlier sale accounting is verified through the recorded retry chain. A close
that could not place any sale can archive its verified unsellable inventory too.
Sellable remainders, unresolved orders, incomplete fees, changed accounts or stale
evidence prevent archival. Partial sales never trigger automatic archival.

**More trade actions → Archive remaining dust** remains available as an explicit
fallback using the same checks. Review the remaining quantity and cost, then confirm.

The archive atomically moves the remainder to the existing **Unsellable trades**
view and stops the registration. Its exact decimal quantity, remaining cost
(including unknown basis), contributed funds, actual disposal proceeds, fees and
execution history remain recorded. No order is placed and no sale proceeds or
realized loss are created. The archive and its audit snapshot survive full backup
and restore. Old installations add the archive column without replacing records.

Choose **Reactivate** separately to resume accumulation with the pinned strategy.
Archived coins remain unmanaged wallet surplus; a new trade does not adopt or sell
them. Clean them up on the exchange before using the existing **Resolve** action
in Unsellable trades. The immutable archive command retains its audit snapshot.
Managed-trade returns retain the actual realized profit from the sold quantity.
The archived remainder leaves managed inventory at its recorded cost basis: it is
neither a sale nor a realized loss. Its wallet value and subsequent manual disposal
are outside managed performance. Reporting verifies the retained archive against
its immutable command and native fill checkpoint before accepting this transfer.
Missing records, unknown basis or fees keep returns unavailable. A new accumulation
holding contributes its own unrealized return normally. Older caches disabled by
verified dust archival rebuild automatically once; history remains preserved.
