# Strategy Builder

The Strategy Builder stores Moonwalker strategies as a versioned graph IR. The
frontend may use Rete.js for editing, but the backend consumes the Moonwalker IR,
not raw Rete JSON. Active versions are immutable: operators edit a draft, validate
it, and promote a new active version.

## Graph Model

A strategy graph has value nodes, logic nodes, state nodes, and one decision
node. Value nodes read market data or indicator values. Logic nodes compare or
combine inputs. State nodes remember enough information to avoid replaying an
already-consumed signal.

Comparison input ports are named `value1` and `value2`. For example,
`value1 greater_than value2` means the first connected value must be above the
second connected value.

## Indicator

Reads a configured TA-Lib indicator value. Indicators can be compared against
prices, constants, or other indicator samples.

Parameters:
- `indicator`: `ema`, `rsi`, `bollinger_upper`, `bollinger_middle`,
  `bollinger_lower`, `bollinger_bandwidth`, `macd_line`, `macd_signal`, or
  `macd_histogram`.
- `length`: optional period for EMA, RSI, and Bollinger Bands.
- `standard_deviations`: optional Bollinger Band deviation multiplier; defaults
  to `2`.
- `fast_period`, `slow_period`, `signal_period`: optional MACD periods;
  defaults to `12`, `26`, and `9`.
- `sample`: `current` for the latest closed value, `previous` for the prior
  closed value, or `two_back` for the candle before `previous`.

`bollinger_bandwidth` is expressed as a percent of the middle band:
`(upper - lower) / middle * 100`.

## Bollinger Buy

The built-in `bollinger_buy` graph triggers when all of the following are true:

- The candle low freshly crosses down through the lower Bollinger Band.
- A rising Bollinger middle band requires the signal candle low to be below
  EMA50; a flat or falling middle band requires it to be below EMA100.
  The EMA penetration may already have started on an earlier candle.
- RSI14 is below `50`.
- Bollinger bandwidth is at least `2%`, filtering narrow sideways conditions.

## Close Price

Reads a close price from recent candle history.

Parameters:
- `lookback`: number of candles to load.
- `sample`: `current` for the latest closed value, or `previous` for the prior
  closed value. Some built-ins also use `two_back` for the candle before
  `previous`.

## Low Price

Reads a candle low for wick-based conditions.

Parameters:
- `lookback`: number of candles to load.
- `sample`: `current` for the latest closed value, or `previous` for the prior
  closed value.

## High Price

Reads a candle high for wick-based conditions.

Parameters:
- `lookback`: number of candles to load.
- `sample`: `current` for the latest closed value, or `previous` for the prior
  closed value.

## Constant Value

Provides a fixed comparison value such as `up`, `upward`, or `none`.

## Comparison

Compares two connected value nodes.

Inputs:
- `value1`: first operand.
- `value2`: second operand.

Parameters:
- `comparison`: `greater_than`, `less_than`, `greater_or_equal`,
  `less_or_equal`, `equals`, or `not_equals`.

## Higher Swing Low State

Tracks the swing-low state used by the built-in EMA swing strategy. It receives
the previous close and two-back close from the graph, calculates the current
qualified swing low, and only returns true when that swing low is above the
previous remembered swing low. Place this node behind the graphical EMA trend
and close/EMA comparison nodes, so state changes only happen after the swing
setup is already qualified.

Parameters:
- `state_key`: persisted state namespace for this graph.

## Fresh Signal State

Prevents repeated orders from the same already-qualified signal. This node should
receive the value nodes that identify the qualified event, usually the current
close price and current EMA value. It should sit behind graphical comparison
nodes, so the comparisons decide whether the signal is qualified and the state
node decides whether it is fresh.

## All Conditions

Returns true only when every connected condition node returns true.

## Any Condition

Returns true when at least one connected condition node returns true.

## Shared strategies for DCA and accumulation

Both modes use the same Strategy Builder, indicator library, graph conditions,
and immutable saved versions. Enable **Use with accumulation** in a custom
strategy's inspector to include its accumulation execution settings. Duplicate a
built-in to edit it. Select the saved version in **Configuration → Trade modes**;
saving a strategy does not change existing holdings' pinned versions.

Accumulation-compatible graphs support indicator, price, numeric constant,
comparison, All, and Any nodes. Stateful DCA nodes remain available for existing
DCA strategies, but cannot be enabled for accumulation: accumulation owns its
persistent opportunity, spacing, and recovery state. Existing ATR presets appear
in the common library without rewriting their historical documents. Their graph
preview allows ATR execution unconditionally; adding graph conditions filters
subsequent buys. The ASAP signal still buys the initial base order immediately,
subject to normal exchange, ownership and capital checks.

Additional shared indicators are `atr`, `adx`, `plus_di`, `minus_di`,
`ema_slope`, and `ema_distance_atr`. Length is configurable. EMA slope is
`(EMA now − EMA N candles ago) / ATR`, using `slope_period` (default 6)
and `atr_length` (default 14). EMA discount is `(EMA − close) / ATR`;
positive values mean price is below the EMA. Zero ATR and insufficient history
produce no signal.

An indicator's **Timeframe** may use the base timeframe or an exact higher
multiple. Higher-timeframe conditions use completed, contiguous candles only;
a forming candle cannot change the current regime. Graphs using higher
timeframes must use pure condition nodes. Warmup is validated and bounded at
12,000 base candles. Required history is shown in the inspector. The same pure
evaluator runs against closed snapshots in DCA, accumulation and historical
replay; charts expose the added indicators in their normal indicator panes.

**Downtrend / sideways accumulation** (`regime_accumulation`) is an experimental
starting preset with a 1h base timeframe:

- Downtrend: 4h EMA50 slope over six bars is below −0.1 ATR and −DI14 exceeds +DI14.
- Sideways: that slope is between −0.1 and +0.1 ATR and ADX14 is below 20.
- Either regime also requires the 1h close to be at least one ATR14 below EMA20.

In accumulation, the existing declining-close, peak discount, opportunity spacing,
recovery and dynamic budget sizing rules still apply. In Dynamic DCA the graph
provides the signal while DCA owns sizing and exits. These thresholds describe a
market filter, not a guarantee that prices will fall or that the strategy is
profitable. Backtest a duplicate before choosing it for a holding.
