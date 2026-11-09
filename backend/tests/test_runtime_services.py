import pytest
from service.dca.order_lifecycle import DcaOrderLifecycle
from service.placement_recovery_entry import PlacementRecoveryEntry
from service.runtime_services import (
    RuntimeServiceProxy,
    RuntimeServiceShutdownError,
    activate_runtime_services,
    build_runtime_services,
    deactivate_runtime_services,
    get_active_accumulation_runtime,
    get_runtime_services,
    reset_runtime_services_for_testing,
)


def test_runtime_services_share_lifecycle_collaborators() -> None:
    reset_runtime_services_for_testing()
    lifecycle = DcaOrderLifecycle()
    entry = PlacementRecoveryEntry(lifecycle=lifecycle)
    services = build_runtime_services(placement_recovery=entry)

    assert services.order_lifecycle is lifecycle
    assert services.trades is lifecycle.trades
    assert services.statistic.trades is services.trades
    assert services.trading_controls._order_lifecycle is services.order_lifecycle
    assert services.trading_controls._trades is services.trades
    assert services.trade_replay_indicators.trades is services.trades
    assert services.accumulation is None


def test_accumulation_resolver_never_constructs_compatibility_graph(monkeypatch):
    reset_runtime_services_for_testing()
    monkeypatch.setattr(
        "service.runtime_services.build_runtime_services",
        lambda: pytest.fail("no lifespan"),
    )
    assert get_active_accumulation_runtime() is None


def test_runtime_service_proxy_prefers_active_lifespan_graph() -> None:
    reset_runtime_services_for_testing()
    compatibility = get_runtime_services()
    active = build_runtime_services()
    proxy = RuntimeServiceProxy[DcaOrderLifecycle]("order_lifecycle")

    assert proxy._resolve() is compatibility.order_lifecycle

    activate_runtime_services(active)
    try:
        assert proxy._resolve() is active.order_lifecycle
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

    async def close_order_lifecycle() -> None:
        closed.append("order_lifecycle")

    monkeypatch.setattr(services.data, "close", close_data)
    monkeypatch.setattr(
        services.statistics_exchange,
        "close",
        close_statistics_exchange,
    )
    monkeypatch.setattr(services.order_lifecycle, "close", close_order_lifecycle)

    await services.shutdown()

    assert closed == ["data", "statistics_exchange", "order_lifecycle"]


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

    async def close_order_lifecycle() -> None:
        closed.append("order_lifecycle")

    monkeypatch.setattr(services.data, "close", fail_data)
    monkeypatch.setattr(
        services.statistics_exchange,
        "close",
        close_statistics_exchange,
    )
    monkeypatch.setattr(services.order_lifecycle, "close", close_order_lifecycle)

    with pytest.raises(
        RuntimeServiceShutdownError,
        match="Controller service shutdown failed",
    ):
        await services.shutdown()

    assert closed == ["data", "statistics_exchange", "order_lifecycle"]


def test_proxy_monkeypatch_undo_restores_class_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch through the proxy; pytest 9.2.0 undoes with delattr on the proxy.

    The proxy forwards writes to the underlying service, so undo() must delete
    the shadowed instance attribute there and restore the class method without
    raising. Regression guard for the pytest 9.1.1 -> 9.2.0 toolchain bump:
    9.2.0 records NOTSET for forwarded setattr targets and undoes them via
    delattr, which the proxy must forward (RuntimeServiceProxy.__delattr__).
    """
    reset_runtime_services_for_testing()
    services = get_runtime_services()
    proxy = RuntimeServiceProxy("order_lifecycle")
    original = type(services.order_lifecycle).close

    monkeypatch.setattr(proxy, "close", lambda: None)
    assert proxy.close is not original
    # Fixture teardown after this body must restore the class method.
