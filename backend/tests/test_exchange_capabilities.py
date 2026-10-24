"""Tests for explicit exchange placement and reconciliation capabilities."""

import pytest
from service.exchange_capabilities import (
    UnsupportedExchangeCapability,
    build_client_order_id,
    build_client_order_params,
    require_exchange_placement_capabilities,
    resolve_exchange_placement_capabilities,
)


def test_binance_spot_exposes_required_reconciliation_guarantees() -> None:
    capabilities = resolve_exchange_placement_capabilities(
        {"exchange": "binance", "market": "spot"}
    )

    assert capabilities is not None
    assert capabilities.supports_safe_placement is True
    assert capabilities.lookup_by_client_order_id is True
    assert capabilities.deterministic_cancellation is True
    assert capabilities.supported_order_types == {"market", "limit"}


@pytest.mark.parametrize("exchange_id", ["bybit", "bybiteu"])
def test_bybit_spot_exposes_verified_reconciliation_guarantees(
    exchange_id: str,
) -> None:
    capabilities = resolve_exchange_placement_capabilities(
        {"exchange": exchange_id, "market": "spot"}
    )

    assert capabilities is not None
    assert capabilities.supports_safe_placement is True
    assert capabilities.client_order_id_parameter == "clientOrderId"
    assert capabilities.client_order_lookup_parameter == "orderLinkId"
    assert capabilities.client_order_lookup_via_order_lists is True
    assert capabilities.supported_order_types == {"market", "limit"}


def test_unsupported_configured_exchange_fails_closed() -> None:
    with pytest.raises(
        UnsupportedExchangeCapability,
        match="does not have verified idempotency",
    ):
        require_exchange_placement_capabilities(
            {"exchange": "unknown-exchange", "market": "spot"},
            order_type="market",
        )


def test_missing_exchange_remains_a_no_client_configuration() -> None:
    assert require_exchange_placement_capabilities({}, order_type="market") is None


def test_client_order_id_is_stable_bounded_and_forwarded_to_ccxt() -> None:
    first = build_client_order_id("operation-123")
    second = build_client_order_id("operation-123")

    assert first == second
    assert first.startswith("mw-")
    assert len(first) == 31
    assert build_client_order_params(first) == {"clientOrderId": first}


@pytest.mark.parametrize("demo", [True, False])
def test_execution_scope_binds_environment_and_account_without_exposing_keys(demo):
    from service.exchange_capabilities import exchange_execution_scope

    config = {"exchange": "binance", "dry_run": demo, "key": "scope-secret"}
    scope = exchange_execution_scope(config)
    assert "scope-secret" not in scope
    assert scope == exchange_execution_scope(dict(config))
    assert scope != exchange_execution_scope({**config, "dry_run": not demo})
    assert scope != exchange_execution_scope({**config, "key": "other"})
    assert scope != exchange_execution_scope({**config, "exchange_hostname": "other"})
    assert (scope == exchange_execution_scope({**config, "sandbox": True})) == demo


def test_execution_scope_rejects_ambiguous_environment():
    from service.exchange_capabilities import exchange_execution_scope

    with pytest.raises(ValueError, match="boolean"):
        exchange_execution_scope({"exchange": "binance", "dry_run": "false"})
