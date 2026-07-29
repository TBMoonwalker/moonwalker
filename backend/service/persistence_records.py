"""Typed records accepted by the transactional order persistence boundary."""

from typing import Any, NotRequired, TypedDict

from service.exchange_types import TradeExecutionPayload


class TradePersistenceRecord(TypedDict):
    """Filled buy row plus metadata used to create its execution ledger row."""

    timestamp: str | int
    ordersize: float
    fee: float
    precision: int | None
    amount: float
    amount_fee: float
    price: float
    symbol: str
    orderid: str
    bot: str
    ordertype: str
    baseorder: bool | None
    safetyorder: bool | None
    order_count: int | None
    so_percentage: float | None
    direction: str
    side: str
    deal_id: NotRequired[str | None]
    campaign_id: NotRequired[str | None]
    signal_name: NotRequired[str | None]
    strategy_name: NotRequired[str | None]
    timeframe: NotRequired[str | None]
    metadata_json: NotRequired[str | dict[str, Any] | None]
    total_amount: NotRequired[float]
    order_id: NotRequired[str | None]
    order_type: NotRequired[str | None]


class TradeExecutionRecord(TypedDict):
    """Canonical row written to the append-only execution ledger."""

    deal_id: str
    campaign_id: str | None
    symbol: str
    side: str
    role: str
    timestamp: str
    price: float
    amount: float
    ordersize: float
    fee: float
    order_id: str | None
    order_type: str | None
    order_count: int | None
    so_percentage: float | None
    signal_name: str | None
    strategy_name: str | None
    timeframe: str | None
    metadata_json: str | None


class OpenTradeDcaDefaults(TypedDict):
    """DCA policy fields required when an open trade is created."""

    dca_sizing_mode: str
    dca_policy_json: str | None
    dca_reference_price: float
    dca_reference_atr_percent: float
    dca_next_trigger_price: float
    dca_last_decision_json: str | None


class OpenTradeLifecycleDefaults(TypedDict):
    """Lifecycle fields required when an open trade is created."""

    deal_id: str | None
    campaign_id: str | None
    lifecycle_mode: str
    exposure_state: str
    reserved_reentry_quote: float
    waiting_reference_price: float
    waiting_reference_amount: float
    waiting_reference_quote: float
    virtual_waiting_profit: float
    virtual_waiting_profit_percent: float
    last_transition_at: str | None


class OpenTradeBuyDefaults(OpenTradeDcaDefaults):
    """Buy-derived summary fields required when an open trade is created."""

    so_count: int
    profit: float
    profit_percent: float
    amount: float
    cost: float
    current_price: float
    tp_price: float
    avg_price: float
    open_date: str | None


class OpenTradeCreateRecord(OpenTradeLifecycleDefaults, OpenTradeBuyDefaults):
    """Complete row required when creating a new active trade."""

    symbol: str
    execution_history_complete: bool


class OpenTradeUpdateRecord(TypedDict, total=False):
    """Intentionally partial fields for updating an existing active trade."""

    deal_id: str | None
    campaign_id: str | None
    lifecycle_mode: str
    exposure_state: str
    execution_history_complete: bool
    so_count: int
    profit: float
    profit_percent: float
    amount: float
    cost: float
    current_price: float
    tp_price: float
    avg_price: float
    open_date: str | None
    sold_amount: float
    sold_proceeds: float
    unsellable_amount: float
    unsellable_reason: str | None
    unsellable_min_notional: float | None
    unsellable_estimated_notional: float | None
    unsellable_since: str | None
    unsellable_notice_sent: bool
    tp_limit_order_id: str | None
    tp_limit_order_price: float | None
    tp_limit_order_amount: float | None
    tp_limit_order_armed_at: str | None
    dca_sizing_mode: str
    dca_policy_json: str | None
    dca_reference_price: float
    dca_reference_atr_percent: float
    dca_next_trigger_price: float
    dca_last_decision_json: str | None
    automation_paused: bool
    automation_paused_at: str | None
    reserved_reentry_quote: float
    waiting_reference_price: float
    waiting_reference_amount: float
    waiting_reference_quote: float
    virtual_waiting_profit: float
    virtual_waiting_profit_percent: float
    last_transition_at: str | None


class ClosedTradeSummaryRecord(TypedDict):
    """Required closed-trade summary fields written to persistence."""

    symbol: str
    so_count: int | None
    profit: float | None
    profit_percent: float | None
    amount: float | None
    cost: float | None
    tp_price: float | None
    avg_price: float | None
    open_date: str | None
    close_date: str | None
    duration: str | None
    deal_id: NotRequired[str | None]
    campaign_id: NotRequired[str | None]
    execution_history_complete: NotRequired[bool]
    close_reason: NotRequired[str | None]


class ClosedTradePersistenceRecord(ClosedTradeSummaryRecord):
    """Closed-deal summary plus the final execution rows."""

    sell_executions: list[TradeExecutionPayload]


class UnsellableTradePersistenceRecord(TypedDict):
    """Archived remainder removed from active bot management."""

    symbol: str
    deal_id: str | None
    execution_history_complete: bool
    so_count: int
    profit: float
    profit_percent: float
    amount: float
    cost: float
    current_price: float
    avg_price: float
    open_date: str | None
    unsellable_reason: str | None
    unsellable_min_notional: float | None
    unsellable_estimated_notional: float | None
    unsellable_since: str | None


class CampaignPersistenceContext(TypedDict, total=False):
    """Campaign transition values committed with an order mutation."""

    campaign_id: str | None
    lifecycle_mode: str
    state: str
    started_at: str
    last_transition_at: str
    current_deal_id: str | None
    tp_percent: float
    principal_quote: float
    reserved_quote: float
    cumulative_realized_quote: float
    cumulative_realized_percent: float
    metadata_json: str | None
    cooldown_until: str | None
    create_campaign: bool
    sidestep_count: int
    last_exit_reason: str | None
    close_reason: str | None
    summary_overrides: dict[str, Any]
    sidestep_increment: int


class ClosedTradePayloadBundle(TypedDict):
    """Persistence and notification projections for one completed sell."""

    payload: ClosedTradePersistenceRecord
    monitor_payload: dict[str, Any]
