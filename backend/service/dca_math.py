"""Pure DCA math functions for both live DCA engine and backtest simulation.

All functions here are pure: no DB, no exchange, no async I/O.
"""

from dataclasses import dataclass, field


@dataclass
class BacktestTradeState:
    """Mutable state for a single backtest trade."""

    symbol: str
    entry_price: float
    entry_amount: float
    entry_cost: float
    entry_timestamp: int
    fee: float = 0.0
    safety_orders: list[dict] = field(default_factory=list)
    safety_orders_count: int = 0
    total_amount: float = 0.0
    total_cost: float = 0.0
    closed: bool = False
    exit_price: float = 0.0
    exit_timestamp: int = 0
    sell_reason: str | None = None
    tp_limit_order_price: float | None = None
    sl_limit_order_price: float | None = None


def calculate_take_profit_price(
    entry_price: float,
    take_profit_pct: float,
    fee: float = 0.0,
) -> float:
    """Calculate take-profit price from average buy price.

    Args:
        entry_price: The average buy price (cost + fee) / total_amount.
        take_profit_pct: Take profit target as a percentage (e.g. 2.5 means 2.5%).
        fee: Optional fee ratio to account for.

    Returns:
        The price at which to sell for the target profit.
    """
    adjusted_price = entry_price * (1 + fee)
    return adjusted_price * (1 + (take_profit_pct / 100))


def calculate_stop_loss_price(
    entry_price: float,
    stop_loss_pct: float,
    fee: float = 0.0,
) -> float:
    """Calculate stop-loss price from average buy price.

    Args:
        entry_price: The average buy price (cost + fee) / total_amount.
        stop_loss_pct: Stop loss threshold as a percentage (e.g. 5.0 means -5%).
        fee: Optional fee ratio to account for.

    Returns:
        The price at which to cut losses.
    """
    adjusted_price = entry_price * (1 + fee)
    return adjusted_price * (1 - (stop_loss_pct / 100))


def calculate_actual_pnl_percent(
    total_cost: float,
    fee: float,
    total_amount: float,
    current_price: float,
) -> float:
    """Calculate actual PNL percentage for a trade.

    Args:
        total_cost: Total money spent on buys (excluding fees).
        fee: Fee ratio (e.g. 0.001 for 0.1%).
        total_amount: Total amount of base asset held.
        current_price: Current market price.

    Returns:
        PNL percentage (positive = profit, negative = loss).
    """
    cost_with_fees = total_cost + total_cost * fee
    avg_price = cost_with_fees / total_amount
    return ((current_price - avg_price) / avg_price) * 100


def check_take_profit_hit(
    current_price: float,
    tp_price: float,
    candle_high: float | None = None,
) -> bool:
    """Check if take-profit target has been hit.

    Uses candle.high when available (intra-candle precision),
    falls back to current_price alone.

    Args:
        current_price: Current or candle close price.
        tp_price: Take-profit price level.
        candle_high: Optional candle high for intra-candle precision.

    Returns:
        True if price reached or exceeded TP level.
    """
    check_price = candle_high if candle_high is not None else current_price
    return check_price >= tp_price


def check_stop_loss_hit(
    current_price: float,
    sl_price: float,
    max_safety_orders_reached: bool,
    candle_low: float | None = None,
) -> bool:
    """Check if stop-loss has been hit.

    Stop loss only triggers after all safety orders are placed to give
    the position a chance to recover.

    Args:
        current_price: Current or candle close price.
        sl_price: Stop-loss price level.
        max_safety_orders_reached: True when no more safety orders can be placed.
        candle_low: Optional candle low for intra-candle precision.

    Returns:
        True if price dropped below SL and no more safety orders remain.
    """
    if not max_safety_orders_reached:
        return False
    check_price = candle_low if candle_low is not None else current_price
    return check_price <= sl_price


def calculate_average_entry_price(
    total_cost: float,
    fee: float,
    total_amount: float,
) -> float:
    """Calculate weighted average entry price including fees.

    Args:
        total_cost: Total cost in quote currency.
        fee: Fee ratio.
        total_amount: Total base asset amount.

    Returns:
        Average entry price per unit of base asset.
    """
    if total_amount <= 0:
        return 0.0
    return (total_cost + total_cost * fee) / total_amount


def calculate_trade_profit_pct(
    entry_price: float,
    exit_price: float,
    fee: float = 0.0,
) -> float:
    """Calculate the profit percentage for a completed trade.

    Args:
        entry_price: Average entry price.
        exit_price: Exit (sell) price.
        fee: Fee ratio for the sell side.

    Returns:
        Profit percentage (negative = loss).
    """
    if entry_price <= 0:
        return 0.0
    return ((exit_price - entry_price) / entry_price) * 100


def tp_limit_prearm_price(
    take_profit_price: float,
    margin_percent: float,
) -> float:
    """Calculate the price at which to pre-arm a TP limit order.

    Args:
        take_profit_price: The TP target price.
        margin_percent: Buffer percentage below TP (e.g. 0.5 means pre-arm at 0.5% below TP).

    Returns:
        The pre-arm trigger price.
    """
    if take_profit_price <= 0:
        return 0.0
    return take_profit_price * (1 - (max(0.0, margin_percent) / 100.0))


def calculate_intra_candle_exit(
    tp_price: float,
    sl_price: float,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    max_safety_orders_reached: bool,
) -> tuple[str, float]:
    """Determine which exit (if any) triggers during a candle and at what price.

    Checks high for TP hit first, then low for SL hit. Returns no exit
    if neither triggers.

    Args:
        tp_price: Take-profit target price.
        sl_price: Stop-loss trigger price.
        candle_high: Candle's high price.
        candle_low: Candle's low price.
        candle_close: Candle's close price.
        max_safety_orders_reached: True when no more safety orders remain.

    Returns:
        (reason, exit_price) or ("", 0.0) if no exit.
    """
    if candle_high >= tp_price:
        return ("take_profit", tp_price)
    if max_safety_orders_reached and candle_low <= sl_price:
        return ("stop_loss", sl_price)
    return ("", 0.0)


def should_place_safety_order(
    actual_pnl: float,
    trigger_threshold: float,
    max_safety_orders: int,
    current_safety_orders: int,
) -> bool:
    """Determine whether a new safety order should be placed.

    Args:
        actual_pnl: Current PNL percentage (negative = underwater).
        trigger_threshold: PNL threshold that triggers safety order (negative).
        max_safety_orders: Maximum allowed safety orders before stop-out.
        current_safety_orders: Number of safety orders already placed.

    Returns:
        True if a new safety order should be placed.
    """
    if current_safety_orders >= max_safety_orders:
        return False
    return actual_pnl <= trigger_threshold


def calculate_safety_order_trigger_threshold(
    base_pct: float,
    step_scale: float,
    safety_orders_count: int,
) -> float:
    """Calculate the cumulative static safety-order PNL trigger threshold."""
    return -abs(
        calculate_cumulative_safety_order_deviation(
            base_pct,
            step_scale,
            safety_orders_count,
        )
    )


def calculate_cumulative_safety_order_deviation(
    base_pct: float,
    step_scale: float,
    safety_orders_count: int,
) -> float:
    """Calculate total price deviation after the next safety-order slot."""
    order_index = safety_orders_count + 1
    if step_scale == 1:
        return base_pct * order_index
    deviation = (base_pct * (1 - step_scale**order_index)) / (1 - step_scale)
    return round(deviation, 2)
