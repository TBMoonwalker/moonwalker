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
second connected value. Legacy graphs that still contain `left` and `right`
ports are normalized to `value1` and `value2`.

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

## Bollinger Sell

The built-in `bollinger_sell` graph triggers when the candle high freshly
crosses above the upper Bollinger Band, the candle closes back below that band,
and RSI14 is at least `60`. This models a rejected overextended top rather than
waiting for MACD momentum to fade.

## Close Price

Reads a close price from recent candle history.

Parameters:
- `lookback`: number of candles to load.
- `sample`: `current` for the latest closed value, or `previous` for the prior
  closed value. Some migrated built-ins also use `two_back` for the candle before
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

## EMA Swing State

Legacy compatibility node for old EMA swing graphs. New editable graphs should
prefer explicit indicator, close price, comparison, higher swing-low state, and
all-conditions nodes.

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
