"""Regression coverage for required persistence record contracts."""

from service.persistence_records import (
    ClosedTradePersistenceRecord,
    ClosedTradeSummaryRecord,
    OpenTradeCreateRecord,
    OpenTradeUpdateRecord,
    TradePersistenceRecord,
    UnsellableTradePersistenceRecord,
)


def test_create_records_keep_core_persistence_fields_required() -> None:
    """Create-bound records must fail static checks when core fields are absent."""
    assert TradePersistenceRecord.__required_keys__ == {
        "timestamp",
        "ordersize",
        "fee",
        "precision",
        "amount",
        "amount_fee",
        "price",
        "symbol",
        "orderid",
        "bot",
        "ordertype",
        "baseorder",
        "safetyorder",
        "order_count",
        "so_percentage",
        "direction",
        "side",
    }
    assert {"symbol", "execution_history_complete"} <= (
        OpenTradeCreateRecord.__required_keys__
    )
    assert {
        "symbol",
        "so_count",
        "profit",
        "profit_percent",
        "amount",
        "cost",
        "tp_price",
        "avg_price",
        "open_date",
        "close_date",
        "duration",
    } == ClosedTradeSummaryRecord.__required_keys__
    assert (
        ClosedTradePersistenceRecord.__required_keys__
        == ClosedTradeSummaryRecord.__required_keys__ | {"sell_executions"}
    )
    assert UnsellableTradePersistenceRecord.__required_keys__ == {
        "symbol",
        "deal_id",
        "execution_history_complete",
        "so_count",
        "profit",
        "profit_percent",
        "amount",
        "cost",
        "current_price",
        "avg_price",
        "open_date",
        "unsellable_reason",
        "unsellable_min_notional",
        "unsellable_estimated_notional",
        "unsellable_since",
    }


def test_update_record_is_explicitly_partial() -> None:
    """Partial active-trade updates must remain distinct from create records."""
    assert OpenTradeUpdateRecord.__required_keys__ == set()
