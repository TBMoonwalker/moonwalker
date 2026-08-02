"""Resolve the controller-facing service graph for one application lifespan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, cast, overload

from service.analytics import Analytics
from service.backup_restore import BackupService
from service.data import Data
from service.delisting_protection import DelistingProtectionService
from service.exchange import Exchange
from service.log_viewer import LogViewerService
from service.orders import Orders
from service.statistic import Statistic
from service.trade_replay_indicators import TradeReplayIndicatorService
from service.trades import Trades
from service.trading_controls import TradingControlsService

ServiceT = TypeVar("ServiceT")


class RuntimeServiceShutdownError(RuntimeError):
    """Aggregate controller-service close failures after best-effort cleanup."""

    def __init__(self, failures: list[Exception]) -> None:
        self.failures = tuple(failures)
        super().__init__(
            f"Controller service shutdown failed in {len(failures)} step(s)"
        )


@dataclass(frozen=True)
class RuntimeServices:
    """Controller-facing collaborators owned by one application lifespan."""

    orders: Orders
    trades: Trades
    data: Data
    analytics: Analytics
    backup: BackupService
    log_viewer: LogViewerService
    statistic: Statistic
    statistics_exchange: Exchange
    trading_controls: TradingControlsService
    trade_replay_indicators: TradeReplayIndicatorService
    delisting_protection: DelistingProtectionService

    async def shutdown(self) -> None:
        """Close clients held by controller-facing services."""
        failures: list[Exception] = []
        for close in (
            self.data.close,
            self.statistics_exchange.close,
            self.orders.close,
        ):
            try:
                await close()
            except Exception as exc:  # noqa: BLE001 - attempt every owned closer.
                failures.append(exc)
        if failures:
            raise RuntimeServiceShutdownError(failures)


_active_services: RuntimeServices | None = None
_compatibility_services: RuntimeServices | None = None


def build_runtime_services(
    *,
    orders: Orders | None = None,
    delisting_protection: DelistingProtectionService | None = None,
    statistics_balance_cache_ttl_seconds: float = 5.0,
) -> RuntimeServices:
    """Build one internally shared controller service graph."""
    orders_service = orders or Orders()
    trades_service = cast(
        Trades,
        getattr(orders_service, "trades", None) or Trades(),
    )
    statistic_service = Statistic(trades=trades_service)
    return RuntimeServices(
        orders=orders_service,
        trades=trades_service,
        data=Data(),
        analytics=Analytics(),
        backup=BackupService(),
        log_viewer=LogViewerService(),
        statistic=statistic_service,
        statistics_exchange=Exchange(
            balance_cache_ttl_seconds=statistics_balance_cache_ttl_seconds
        ),
        trading_controls=TradingControlsService(
            orders=orders_service,
            trades=trades_service,
        ),
        trade_replay_indicators=TradeReplayIndicatorService(trades_service),
        delisting_protection=(
            delisting_protection or DelistingProtectionService.shared()
        ),
    )


def activate_runtime_services(services: RuntimeServices) -> None:
    """Expose the ready lifespan graph to controllers."""
    global _active_services
    _active_services = services


def deactivate_runtime_services(services: RuntimeServices) -> None:
    """Clear the active graph without disturbing a newer lifespan."""
    global _active_services
    if _active_services is services:
        _active_services = None


def get_runtime_services() -> RuntimeServices:
    """Resolve the active graph or lazily build the import-compatibility graph."""
    global _compatibility_services

    # Controller import
    #     |
    #     +--> no construction
    #     |
    # request during lifespan --> active graph
    # direct test/script call  --> one lazy compatibility graph
    if _active_services is not None:
        return _active_services
    if _compatibility_services is None:
        _compatibility_services = build_runtime_services()
    return _compatibility_services


def reset_runtime_services_for_testing() -> None:
    """Clear resolver state between identity-focused unit tests."""
    global _active_services
    global _compatibility_services
    _active_services = None
    _compatibility_services = None


class RuntimeServiceProxy(Generic[ServiceT]):
    """Delegate attribute access to one named service in the resolved graph."""

    def __init__(self, service_name: str) -> None:
        object.__setattr__(self, "_service_name", service_name)

    def _resolve(self) -> ServiceT:
        services = get_runtime_services()
        return cast(ServiceT, getattr(services, self._service_name))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_service_name":
            object.__setattr__(self, name, value)
            return
        setattr(self._resolve(), name, value)


@overload
def runtime_service_proxy(service_name: Literal["orders"]) -> Orders: ...


@overload
def runtime_service_proxy(service_name: Literal["trades"]) -> Trades: ...


@overload
def runtime_service_proxy(service_name: Literal["data"]) -> Data: ...


@overload
def runtime_service_proxy(service_name: Literal["analytics"]) -> Analytics: ...


@overload
def runtime_service_proxy(service_name: Literal["backup"]) -> BackupService: ...


@overload
def runtime_service_proxy(service_name: Literal["log_viewer"]) -> LogViewerService: ...


@overload
def runtime_service_proxy(service_name: Literal["statistic"]) -> Statistic: ...


@overload
def runtime_service_proxy(
    service_name: Literal["statistics_exchange"],
) -> Exchange: ...


@overload
def runtime_service_proxy(
    service_name: Literal["trading_controls"],
) -> TradingControlsService: ...


@overload
def runtime_service_proxy(
    service_name: Literal["trade_replay_indicators"],
) -> TradeReplayIndicatorService: ...


@overload
def runtime_service_proxy(
    service_name: Literal["delisting_protection"],
) -> DelistingProtectionService: ...


def runtime_service_proxy(service_name: str) -> Any:
    """Return a lazy compatibility proxy for a controller module."""
    return RuntimeServiceProxy(service_name)
