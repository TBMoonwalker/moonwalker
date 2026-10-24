# How to start, manage and close an accumulation holding

Configure an initial holding, monitor subsequent purchases, and end the cycle
through the same Open trades workspace used for Dynamic DCA.

## Prerequisites

- A configured spot exchange and quote currency.
- Credentials and free funds for the selected environment. **Dry run uses the
  exchange's supported demo environment**, with demo credentials and funds.
  Unsupported demo venues cannot trade and do not fall back to live funds.
- A compatible saved accumulation version. Built-in versions are available
  before setup completes; you do not need to create one during configuration.
- No open holdings, non-stopped registrations or unresolved orders if changing
  trade mode. Pause an already-live instance before changing its mode.

For a local simulation with no wallet or orders, use the
[backtest tutorial](tutorial-accumulation-backtest.md).

## Start with ASAP

1. Open **Configuration → Trade modes**, enable management, and select
   **Accumulation**. Disable Autopilot and use a spot market.
2. Select the **ASAP** signal plugin and enter a fixed comma-separated symbol
   list such as `BTC/USDC,ETH/USDC` when the configured quote is USDC. URL lists
   are unsupported for accumulation.
3. Select **Initial accumulation strategy version**. The shared
   **Downtrend / sideways accumulation** preset is available without creating a
   strategy first. The [strategy reference](strategies.md#shared-strategies-for-dca-and-accumulation)
   describes its conditions. Select an exact version; names alone are not pins.
4. Set **Base order amount**, **Max managed symbols**, and your capital limit.
   Review the environment and save the configuration. If Moonwalker is globally
   paused, resume it when you intend to allow purchases.
5. Open **Trading Overview → Open trades**. ASAP registers each admitted symbol
   and the runtime attempts its configured base order. It does not wait for a
   dip, a completed candle, strategy warmup or the portfolio ranking round.
   Account, ownership, balance, capital, precision and exchange minimum checks
   still apply. Expand the row to see the base order once filled.

After the first fill, the runtime loads completed history and establishes a fresh
strategy baseline. Subsequent buys require qualifying new candles. Saving a
configuration or strategy is not a guarantee that an exchange order will pass.

## Adopt coins already owned with CSV

1. Select **CSV Signal** instead of ASAP and retain the other accumulation
   requirements above. Configure its input using the [signal plugin guide](signals.md).
2. Supply actual purchases in the existing format:

   ```csv
   date;symbol;price;amount
   2026-01-15 12:00:00;BTC/USDC;90000;0.001
   ```

   Use your own past date, acquisition price and net owned amount. Do not submit
   the example as invented inventory. Each row declares already-owned coins;
   the import does not purchase them. Historical fees remain unknown.
3. Save and inspect the entry in **Open trades**. Fresh free wallet inventory
   must cover the declaration, accounting for other managed holdings. If validation
   fails, correct the cause and use **Retry entry check**. A corrected declaration
   remains paused until explicitly validated.

The parser accepts at most 10,000 rows and 1,000,000 characters. All symbols must
use the configured spot quote. See [entry reference](accumulation.md#set-up-a-holding)
for adoption and retry behavior.

## Monitor and pause purchases

1. Read **Order status** in Open trades. Expand the trade for its chart, order
   history and next-buy condition. A displayed percentage is measured from the
   stated completed close, or the fresh ask for an execution-price wait.
2. Use the row's **More** actions to pause or resume the registration. Pause
   blocks new buys while retaining managed coins and settling outstanding work.
   Use the top-bar global pause to block new buys across Moonwalker.
3. Resume explicitly after a pause. Resume revalidates ownership and history;
   it does not purchase missed historical signals.

The dashboard receives status updates over WebSocket. A disconnected stream
makes actions stale; reconnect or use **Refresh status** before acting.
The ASAP plugin still checks for registrations periodically, and the runtime
uses timers for candle boundaries and order recovery. Neither is browser polling.

A declining candle need not be below the base-order price or previous fill.
A recovery followed by a fresh correction can qualify above an earlier purchase.
See [why prices can differ](explanation-accumulation-lifecycle.md#why-a-later-buy-can-cost-more).

## Change a strategy

1. Create or duplicate and validate a strategy in the common **Strategy Builder**.
   Custom graphs need **Use with accumulation** and valid execution settings.
2. Open **Configuration → Trade modes → Change strategy for an existing
   registration**. Select the symbol and exact replacement version, review,
   and confirm the change.
3. Verify the registration's version in Configuration and its new wait condition
   in Open trades. A paused registration stays paused.

The initial version selector only affects new registrations. Saving a strategy
never updates holding pins. Strategy assignment is not in Utilities or trade cards.

## Sell and start a new cycle

1. Use **Sell part** for an exact base-asset quantity that leaves positive managed
   inventory. Review and confirm it. After settlement, the previous explicit
   pause state is restored.
2. Use the trade's **Sell** action to close the holding, review, and confirm.
   Closing blocks new buys. Wait for terminal sale and fee evidence. A sellable
   remainder needs an explicit **Retry remaining sale**; verified unsellable
   dust is archived automatically in **Unsellable trades**.
3. Confirm the registration is **Stopped**. ASAP does not restart it automatically.
   Choose **Reactivate** explicitly to begin a new generation. For an ASAP
   registration, this starts a fresh base order under the same checks as its
   original entry. Old executions remain in the audit history, but do not appear
   as orders of the new deal. Archived dust remains unmanaged.

There are no accumulation take-profit, stop-loss, trailing or timeout sales.
The strategy can keep spending newly available budget without a fixed buy count.

## Verification

A filled **Base order** proves initial entry. A later strategy wait proves only
that the runtime is observing or waiting, not that another buy is guaranteed.
Check the selected version, current condition, and executed **Accumulation order**
rows separately. Read-only status is also available at
`/accumulation/activation?symbol=BTC%2FUSDC`; use your instance and symbol.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Symbol quote rejected | Match every pair's quote to the configured currency; use spot pairs. |
| Entry has no fill | Read the current blocker: pause, account, funds, capital, minimum or unresolved order. Do not repeatedly re-register. |
| Waiting for strategy history after a base order | Allow completed continuous history to load; no historical buys are backfilled. |
| Next buy can be above an earlier fill | This is compatible with a fresh correction after recovery; use the market filter if desired. It is not a lifetime descending-price rule. |
| Closing persists or profit is unavailable | Follow the [recovery guide](howto-recover-accumulation.md); do not clear database records to hide the blocker. |

See the [accumulation reference](accumulation.md) for parameter constraints,
capital allocation, lifecycle actions and accounting details.
