# Safety-order sizing and Expert safeguards

A safety order (SO) is an additional buy in an existing deal. It adds exposure
and lowers the average entry price when it fills below that average. Take
profit (TP) is then calculated from the updated position.

In the Control Center, open **Expert safeguards → Recovery safety orders →
Sizing mode**. These controls appear when DCA is enabled in dynamic DCA mode.
The setting is `dynamic_so_sizing_mode`.

## Choose a sizing mode

| Mode | What determines the order amount? | What actually trades? |
|---|---|---|
| **Legacy factors** (`legacy_factors`, default) | Base order amount multiplied by loss, threshold, ATH-distance, volatility, and order-progression factors. | The existing dynamic DCA trigger and factor-based amount. |
| **Recovery shadow** (`recovery_shadow`) | Calculates a recovery-target amount for comparison when a legacy order is evaluated. | The same legacy orders; the recovery calculation is diagnostic only. |
| **Recovery target** (`recovery_target`) | Calculates the buy needed to bring projected TP within a configured rebound distance, bounded by budget. | Recovery spacing and sizing control actual safety orders. |

Use Legacy factors to retain the existing behavior. Use Recovery shadow to
observe the alternative sizing without letting it control orders. Shadow mode
is **not paper trading**: legacy orders still execute according to the instance's
exchange configuration. It also does not simulate every order that Recovery
target would place, because its comparisons run on legacy-triggered candidates.

Use Recovery target when you intend the rebound target and deal budget to
determine safety orders. A target describes a calculation, not a forecast or
guarantee of recovery.

## Existing deals keep their policy

The sizing mode and recovery policy are captured when a deal opens. Saving a
different mode, budget, spacing, or recovery target affects **new deals only**;
it does not migrate existing deals. A shadow deal therefore stays a shadow
deal after you switch the configuration to Recovery target.

This snapshot applies to the recovery policy, not every trading setting.
Account-wide capital controls and the runtime take-profit setting still apply.

## Legacy factors

The current dynamic DCA calculation starts from **Base order amount**
(`bo`), then multiplies it by:

- Current loss: larger losses increase the factor, up to its built-in cap.
- Distance beyond the safety-order loss threshold.
- Distance below the recent all-time high (ATH), obtained from exchange candles.
- The ATR volatility-regime multiplier.
- Safety-order progression: later orders increase the factor, up to its cap.

The resulting amount is limited by the configured fraction of free quote
balance. If it falls below the base order amount, the order is skipped.
Other buy-admission and exchange checks still apply.

This mode does not solve for a desired post-buy TP distance. The historical
weighted-loss/drawdown formula and its `dynamic_so_loss_weight`,
`dynamic_so_drawdown_weight`, exponent, and min/max-scale controls are not used
by the current dynamic DCA sizing path.

## Recovery target: spacing and amount

ATR (Average True Range) measures recent candle ranges. ATR% expresses that
range relative to price. The recovery policy uses it in two separate ways.

**Spacing** determines how far price must fall below the preceding filled buy:

```text
gap (%) = max(first-order deviation, reference ATR% × spacing multiplier)
          × step scale ^ number of filled safety orders
```

The reference is the preceding filled buy and its stored ATR reference; if that
ATR reference is missing, the current ATR is used. Later gaps expand with the
step scale. Reaching the price threshold is not sufficient on its own: the
configured DCA strategy must also provide a qualifying fresh signal.

**Sizing** determines how much to buy:

```text
target rebound (%) = clamp(current ATR% × recovery multiplier,
                           minimum recovery move, maximum recovery move)
```

Moonwalker solves for the quote amount that brings the projected TP price to
that rebound distance above the candidate fill price. The projection includes
the deal's recorded fee ratio and the configured TP percentage.

For example, suppose a position contains 1 coin bought for 100 quote units,
the next buy price is 80, TP is 1%, and the target rebound is 12%. Ignoring fees
and exchange rounding, TP needs to become 89.60. Buying approximately 103.64
quote units at 80 brings the average to approximately 88.71 and TP to 89.60.
This is a sizing illustration; actual orders remain subject to all limits.

## Recovery controls

| Control | Meaning |
|---|---|
| **ATR timeframe source / length** | Candle timeframe and lookback for volatility. `trading` uses the deal's trading timeframe; an explicit higher timeframe is also available. |
| **Spacing ATR multiplier** | Multiplies reference ATR% to set the gap, with `sos` as the minimum. |
| **Spacing step scale** | Expands the gap for each subsequent safety order (`ss`). |
| **Recovery ATR multiplier** | Multiplies current ATR% to determine the desired rebound to projected TP. |
| **Minimum / maximum recovery move (%)** | Bound the desired rebound. A smaller target generally needs a larger buy to pull the average down further. |
| **Maximum quote per deal** | Caps total deal cost, including the base order and filled safety orders. This is not a per-order allowance. Recovery target requires a positive cap. |
| **Minimum TP improvement** | When budget limits prevent the full target, the smaller buy must reduce the TP distance by at least this many percentage points. |
| **Execution guard** | When enabled, checks the exchange ask before execution and uses an immediate-or-cancel limit buy with a calculated price ceiling. |

The free-balance fraction (`trade_safety_order_budget_ratio`), global capital
limit, maximum safety-order count, exchange minimum order size, and other
trading guards still apply.
Recovery shadow computes diagnostics with the recovery settings but does not
apply their deal cap or execution guard to the legacy order.

The execution-price allowance is ATR% multiplied by the drift fraction,
clamped between its configured minimum and maximum. It limits how far the
executable price may rise above the trigger; it does not guarantee a fill.

## Why an order may be skipped

- Price has not reached the required gap, or there is no qualifying fresh
  strategy signal.
- Existing projected TP is already within the target rebound distance.
- The deal budget is exhausted or the target cannot be solved.
- The affordable amount is below the exchange minimum.
- A budget-limited order would improve the TP distance too little.
- The executable price exceeds the enabled execution guard, or another
  capital, exchange, or trading guard rejects the buy.

An improvement from a 25% rebound requirement to 19% is **6 percentage points**.
It satisfies a 5-point minimum. A change from 25% to 22% is only 3 points and
would not satisfy that minimum for a capped order.

## Change the mode

1. Open the Control Center and enable DCA if needed.
2. Open **Expert safeguards → Recovery safety orders** and choose the mode.
3. For Recovery shadow or Recovery target, review ATR, spacing, recovery,
   and budget settings. Recovery target requires a positive deal cap.
4. Save the configuration.
5. Inspect newly opened deals to evaluate the selected policy; existing deals
   retain their snapshots.

See the [configuration reference](configuration.md#configuration-reference)
for exact keys and defaults, and [developer documentation](development.md)
for implementation ownership.
