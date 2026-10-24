# Compare accumulation strategies before starting a holding

Run an accumulation simulation in the existing Backtest view, then compare its
coins, cash and ending value with buy-and-hold and fixed-interval DCA. This teaches
you how the saved strategy behaves without submitting an exchange order.

## What you'll need

- A running Moonwalker installation. Follow the [README](../README.md#run-script-recommended).
- A configured exchange and quote currency, with accessible public spot history.
- A compatible saved strategy. **Downtrend / sideways accumulation** is available
  in the common catalog before setup is complete.

You do not need to switch the running bot's trade mode, adopt inventory or fund
an exchange account for this simulation. Historical data still comes from the
configured exchange.

## Step 1: Select an accumulation version

Open **Backtest**, set **Trade mode** to **Accumulation**, and select a saved
version under **Strategy**. Select a spot symbol in your configured quote.
The strategy's saved timeframe appears automatically.

Select **Downtrend / sideways accumulation** to test its market conditions and
dip execution rules together. It is an experimental preset, not optimized settings.
Duplicate it in Strategy Builder to compare a customized version.

## Step 2: Run a historical comparison

Select a past date range for which the exchange has sufficient earlier history.
For a first 1h comparison, use a month on a well-established spot market.
Set these simulation inputs:

| Field | Example | Meaning |
| --- | --- | --- |
| Initial funding | `1000` | Starting quote balance for each comparison. |
| Fee | `0.001` | Fee fraction: 0.1% per buy. |
| Adverse buy slippage · basis points | `20` | Buy execution 0.2% above the modeled opening price. |
| Fixed DCA comparison interval · candles | `24` | One comparison purchase per 24 strategy candles. |

Choose **Run**. The result workspace shows **Buys**, **Coins accumulated**,
**Spent incl. fees**, **Cash remaining**, **Ending value**, and **Max drawdown**.
Zero buys is a valid result when the strategy never qualifies.

If the exchange does not cover warmup, choose an older listed market or a more
recent start date with enough preceding history. Shorten an oversized range:
the 20,000-candle limit includes warmup. The shipped downtrend/sideways preset
needs 1,240 warmup candles on its 1h base.

## Step 3: Read the result

Open **Trades** to inspect buy executions and **Comparison** to compare the
three equally funded approaches. Ending value includes remaining cash and coins
marked at the ending price. It is not realized sale profit.

Signals execute at the next supplied candle open. Only the first 100 accumulation
executions appear as rows and markers; totals include every buy. Missing candles
can cancel a pending buy and force another continuous warmup window.

This comparison evaluates the strategy after warmup. It does not reproduce the
initial ASAP base order, live exchange minimums, precision or liquidity. Fixed
fees and slippage are modeling assumptions; future sale fees are excluded.

## What you built

You now have a historical comparison for an exact saved accumulation version.
Use [the operating guide](howto-operate-accumulation.md) to assign it to a new
registration. See [strategy reference](strategies.md#shared-strategies-for-dca-and-accumulation),
[accumulation reference](accumulation.md#historical-strategy-comparison), and
[the lifecycle explanation](explanation-accumulation-lifecycle.md) before
interpreting a result as evidence about live behavior.
