import pytest
from service.orders import Orders
from service.runtime_services import (
    RuntimeServiceProxy,
    RuntimeServiceShutdownError,
    activate_runtime_services,
    build_runtime_services,
    deactivate_runtime_services,
    get_runtime_services,
    reset_runtime_services_for_testing,
)


def test_runtime_services_share_lifecycle_collaborators() -> None:
    reset_runtime_services_for_testing()
    orders = Orders()
    services = build_runtime_services(orders=orders)

    assert services.orders is orders
    assert services.trades is orders.trades
    assert services.statistic.trades is services.trades
    assert services.trading_controls._orders is services.orders
    assert services.trading_controls._trades is services.trades
    assert services.trade_replay_indicators.trades is services.trades


def test_runtime_service_proxy_prefers_active_lifespan_graph() -> None:
    reset_runtime_services_for_testing()
    compatibility = get_runtime_services()
    active = build_runtime_services()
    proxy = RuntimeServiceProxy[Orders]("orders")

    assert proxy._resolve() is compatibility.orders

    activate_runtime_services(active)
    try:
        assert proxy._resolve() is active.orders
        assert proxy._resolve() is proxy._resolve()
    finally:
        deactivate_runtime_services(active)
        reset_runtime_services_for_testing()


@pytest.mark.asyncio
async def test_runtime_services_close_controller_owned_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = build_runtime_services()
    closed: list[str] = []

    async def close_data() -> None:
        closed.append("data")

    async def close_statistics_exchange() -> None:
        closed.append("statistics_exchange")

    async def close_orders() -> None:
        closed.append("orders")

    monkeypatch.setattr(services.data, "close", close_data)
    monkeypatch.setattr(
        services.statistics_exchange,
        "close",
        close_statistics_exchange,
    )
    monkeypatch.setattr(services.orders, "close", close_orders)

    await services.shutdown()

    assert closed == ["data", "statistics_exchange", "orders"]


@pytest.mark.asyncio
async def test_runtime_services_attempt_every_close_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = build_runtime_services()
    closed: list[str] = []

    async def fail_data() -> None:
        closed.append("data")
        raise RuntimeError("data close failed")

    async def close_statistics_exchange() -> None:
        closed.append("statistics_exchange")

    async def close_orders() -> None:
        closed.append("orders")

    monkeypatch.setattr(services.data, "close", fail_data)
    monkeypatch.setattr(
        services.statistics_exchange,
        "close",
        close_statistics_exchange,
    )
    monkeypatch.setattr(services.orders, "close", close_orders)

    with pytest.raises(
        RuntimeServiceShutdownError,
        match="Controller service shutdown failed",
    ):
        await services.shutdown()

    assert closed == ["data", "statistics_exchange", "orders"]
