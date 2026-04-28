"""Regression tests for Litestar migration edge cases."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from controller import config as config_controller
from controller import frontend as frontend_controller
from controller import monitoring as monitoring_controller
from controller import orders as orders_controller
from controller import statistics as statistics_controller
from controller import trades as trades_controller
from litestar import Litestar
from litestar.testing import TestClient
from service.log_viewer import LogReadResult


class _DummyConfigService:
    """Minimal config service stub for controller tests."""

    def __init__(self) -> None:
        self.last_batch: dict[str, Any] | None = None
        self.last_single: tuple[str, Any] | None = None
        self._cache: dict[str, Any] = {"signal": "asap"}

    async def batch_set(self, payload: dict[str, Any]) -> bool:
        self.last_batch = payload
        for key, value in payload.items():
            self._cache[key] = value.get("value") if isinstance(value, dict) else value
        return True

    async def set(self, key: str, value: Any) -> bool:
        self.last_single = (key, value)
        self._cache[key] = value.get("value") if isinstance(value, dict) else value
        return True

    def get(self, key: str, default: Any | None = None) -> Any | None:
        return self._cache.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._cache)


class _DummyOpenTradesCount:
    """OpenTrades stub exposing count() through all()."""

    count_value = 0

    @classmethod
    def all(cls) -> "_DummyOpenTradesCount":
        return cls()

    async def count(self) -> int:
        return self.count_value


class _DummyAppConfigQuery:
    """AppConfig query stub for freshness endpoint coverage."""

    def __init__(self, latest_row: Any) -> None:
        self._latest_row = latest_row

    def order_by(self, *_args: Any, **_kwargs: Any) -> "_DummyAppConfigQuery":
        return self

    async def first(self) -> Any:
        return self._latest_row


class _DummyAppConfigModel:
    """AppConfig stub exposing latest updated_at metadata."""

    latest_row: Any = None

    @classmethod
    def all(cls) -> _DummyAppConfigQuery:
        return _DummyAppConfigQuery(cls.latest_row)


def test_frontend_routes_serve_index_and_assets(tmp_path: Path, monkeypatch) -> None:
    """Ensure SPA routes serve compiled assets rather than index fallback."""
    static_dir = tmp_path / "static"
    template_dir = tmp_path / "templates"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    (template_dir / "index.html").write_text(
        (
            "<!doctype html><html><body>"
            "<script src='/assets/app-abc12345.js'></script>"
            "</body></html>"
        ),
        encoding="utf-8",
    )
    (assets_dir / "app-abc12345.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    app = Litestar(
        route_handlers=[
            frontend_controller.serve_static,
            frontend_controller.serve_vue,
            frontend_controller.serve_root,
        ]
    )
    with TestClient(app=app) as client:
        index_response = client.get("/")
        assert index_response.status_code == 200
        assert "/assets/app-abc12345.js" in index_response.text
        assert "text/html" in index_response.headers.get("content-type", "")
        assert index_response.headers.get("cache-control") == "no-cache"

        asset_response = client.get("/assets/app-abc12345.js")
        assert asset_response.status_code == 200
        assert "console.log('ok');" in asset_response.text
        assert "html" not in asset_response.text.lower()
        assert "javascript" in asset_response.headers.get("content-type", "")
        assert (
            asset_response.headers.get("cache-control")
            == "public, max-age=31536000, immutable"
        )


def test_statistics_http_endpoints_return_native_json(monkeypatch) -> None:
    """HTTP statistics endpoints should return native JSON values."""

    async def _fake_profits_overall(*args: Any, **kwargs: Any) -> dict[str, float]:
        return {"2026-03-01": 1.23}

    async def _fake_profit_timeline(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"timestamp": "2026-03-01 12:00:00", "profit_overall": 1.23}]

    monkeypatch.setattr(
        statistics_controller.statistic, "get_profits_overall", _fake_profits_overall
    )
    monkeypatch.setattr(
        statistics_controller.statistic,
        "get_profit_overall_timeline",
        _fake_profit_timeline,
    )

    app = Litestar(
        route_handlers=[
            statistics_controller.profit_statistics,
            statistics_controller.profit_overall_timeline,
        ]
    )
    with TestClient(app=app) as client:
        profits_response = client.get("/statistic/profit/1700000000/daily")
        assert profits_response.status_code == 200
        assert profits_response.json() == {"2026-03-01": 1.23}

        timeline_response = client.get("/statistic/profit-overall/timeline")
        assert timeline_response.status_code == 200
        assert timeline_response.json() == [
            {"timestamp": "2026-03-01 12:00:00", "profit_overall": 1.23}
        ]


def test_monitoring_logs_endpoint_returns_source_metadata(monkeypatch) -> None:
    """Monitoring log metadata endpoint should return native JSON."""

    monkeypatch.setattr(
        monitoring_controller.log_viewer_service,
        "list_sources",
        lambda: [
            {"source": "watcher", "label": "Watcher", "available": True},
            {"source": "signal", "label": "Signal", "available": False},
        ],
    )

    app = Litestar(route_handlers=[monitoring_controller.get_monitoring_log_sources])
    with TestClient(app=app) as client:
        response = client.get("/monitoring/logs")

    assert response.status_code == 200
    assert response.json() == {
        "sources": [
            {"source": "watcher", "label": "Watcher", "available": True},
            {"source": "signal", "label": "Signal", "available": False},
        ]
    }


def test_monitoring_logs_endpoint_returns_log_batches(monkeypatch) -> None:
    """Monitoring log batch endpoint should pass through the log payload."""

    monkeypatch.setattr(
        monitoring_controller.log_viewer_service,
        "read_source",
        lambda source, cursor, before, limit: LogReadResult(
            source=source,
            label="Watcher",
            available=True,
            lines=["2026-03-19 - INFO - watcher : started"],
            cursor=128,
            oldest_cursor=64,
            has_more_before=True,
            rotated=False,
        ),
    )

    app = Litestar(route_handlers=[monitoring_controller.get_monitoring_log_source])
    with TestClient(app=app) as client:
        response = client.get("/monitoring/logs/watcher?cursor=64&limit=100")

    assert response.status_code == 200
    assert response.json() == {
        "source": "watcher",
        "label": "Watcher",
        "available": True,
        "lines": ["2026-03-19 - INFO - watcher : started"],
        "cursor": 128,
        "oldest_cursor": 64,
        "has_more_before": True,
        "rotated": False,
    }


def test_monitoring_logs_endpoint_rejects_unknown_source(monkeypatch) -> None:
    """Unknown log sources should return 404."""

    def _raise_unknown(*_args: Any, **_kwargs: Any) -> LogReadResult:
        raise ValueError("Unknown log source: missing")

    monkeypatch.setattr(
        monitoring_controller.log_viewer_service,
        "read_source",
        _raise_unknown,
    )

    app = Litestar(route_handlers=[monitoring_controller.get_monitoring_log_source])
    with TestClient(app=app) as client:
        response = client.get("/monitoring/logs/missing")

    assert response.status_code == 404
    assert response.json() == {"error": "Unknown log source: missing"}


def test_monitoring_logs_download_endpoint_returns_attachment(
    monkeypatch, tmp_path: Path
) -> None:
    """Monitoring log downloads should use an attachment response."""

    download_path = tmp_path / "watcher.log"
    download_path.write_text(
        "2026-03-19 - INFO - watcher : started\n",
        encoding="utf-8",
    )

    class _Source:
        source = "watcher"

    monkeypatch.setattr(
        monitoring_controller.log_viewer_service,
        "get_download_path",
        lambda source: (_Source(), download_path),
    )

    app = Litestar(
        route_handlers=[monitoring_controller.download_monitoring_log_source]
    )
    with TestClient(app=app) as client:
        response = client.get("/monitoring/logs/watcher/download")

    assert response.status_code == 200
    assert response.text == "2026-03-19 - INFO - watcher : started\n"
    assert response.headers["content-type"].startswith("text/plain")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="moonwalker-watcher.log"'
    )


def test_monitoring_logs_download_endpoint_returns_404_for_missing_file(
    monkeypatch,
) -> None:
    """Missing current log files should return 404 on download."""

    def _raise_missing(*_args: Any, **_kwargs: Any) -> tuple[Any, Any]:
        raise FileNotFoundError("Log source file does not exist: watcher")

    monkeypatch.setattr(
        monitoring_controller.log_viewer_service,
        "get_download_path",
        _raise_missing,
    )

    app = Litestar(
        route_handlers=[monitoring_controller.download_monitoring_log_source]
    )
    with TestClient(app=app) as client:
        response = client.get("/monitoring/logs/watcher/download")

    assert response.status_code == 404
    assert response.json() == {"error": "Log source file does not exist: watcher"}


def test_config_multiple_accepts_2xx_contract(monkeypatch) -> None:
    """Ensure config batch endpoint uses a successful 2xx response."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    payload = {"debug": {"value": False, "type": "bool"}}
    with TestClient(app=app) as client:
        response = client.post("/config/multiple", json=payload)

    assert 200 <= response.status_code < 300
    assert response.status_code == 201
    assert response.json() == {"message": "Config updated"}
    assert service.last_batch == payload


def test_config_single_accepts_success_contract(monkeypatch) -> None:
    """Ensure single-key config updates keep the established success contract."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_config_key])
    payload = {"value": {"value": "binance", "type": "str"}}
    with TestClient(app=app) as client:
        response = client.put("/config/single/exchange", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "message": "Config 'exchange' updated",
        "value": payload["value"],
    }
    assert service.last_single == ("exchange", payload["value"])


def test_config_multiple_rejects_generic_live_activation(monkeypatch) -> None:
    """Generic config batch saves must not switch the instance live."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    payload = {"dry_run": {"value": False, "type": "bool"}}
    with TestClient(app=app) as client:
        response = client.post("/config/multiple", json=payload)

    assert response.status_code == 409
    assert "live activation" in response.json().get("error", "").lower()
    assert service.last_batch is None


def test_config_multiple_blocks_switch_to_csv_signal_when_open_trades_exist(
    monkeypatch,
) -> None:
    """Switching to csv_signal must be blocked while open trades exist."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )
    _DummyOpenTradesCount.count_value = 2
    monkeypatch.setattr(config_controller, "OpenTrades", _DummyOpenTradesCount)

    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    payload = {"signal": {"value": "csv_signal", "type": "str"}}
    with TestClient(app=app) as client:
        response = client.post("/config/multiple", json=payload)

    assert response.status_code == 409
    assert "csv_signal" in response.json().get("error", "")
    assert service.last_batch is None


def test_config_single_blocks_switch_to_csv_signal_when_open_trades_exist(
    monkeypatch,
) -> None:
    """Single-key signal update must also block csv_signal switch."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )
    _DummyOpenTradesCount.count_value = 1
    monkeypatch.setattr(config_controller, "OpenTrades", _DummyOpenTradesCount)

    app = Litestar(route_handlers=[config_controller.update_config_key])
    payload = {"value": {"value": "csv_signal", "type": "str"}}
    with TestClient(app=app) as client:
        response = client.put("/config/single/signal", json=payload)

    assert response.status_code == 409
    assert "open trades" in response.json().get("error", "").lower()
    assert service.last_batch is None


def test_config_single_rejects_generic_live_activation(monkeypatch) -> None:
    """Single-key config saves must not switch the instance live."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_config_key])
    payload = {"value": {"value": False, "type": "bool"}}
    with TestClient(app=app) as client:
        response = client.put("/config/single/dry_run", json=payload)

    assert response.status_code == 409
    assert "live activation" in response.json().get("error", "").lower()
    assert service.last_single is None


@pytest.mark.parametrize(
    (
        "route_handler",
        "method_name",
        "path",
        "payload",
        "open_trade_count",
        "expected_message",
    ),
    [
        (
            config_controller.update_config_key,
            "put",
            "/config/single/dry_run",
            {"value": {"value": False, "type": "bool"}},
            None,
            config_controller.LIVE_ACTIVATION_DENIED_MESSAGE,
        ),
        (
            config_controller.update_multiple_config_keys,
            "post",
            "/config/multiple",
            {"dry_run": {"value": False, "type": "bool"}},
            None,
            config_controller.LIVE_ACTIVATION_DENIED_MESSAGE,
        ),
        (
            config_controller.update_config_key,
            "put",
            "/config/single/signal",
            {"value": {"value": "csv_signal", "type": "str"}},
            1,
            (
                "Cannot switch signal plugin to 'csv_signal' while open trades exist. "
                "Close all open trades first."
            ),
        ),
        (
            config_controller.update_multiple_config_keys,
            "post",
            "/config/multiple",
            {"signal": {"value": "csv_signal", "type": "str"}},
            2,
            (
                "Cannot switch signal plugin to 'csv_signal' while open trades exist. "
                "Close all open trades first."
            ),
        ),
    ],
)
def test_config_update_routes_share_conflict_response_shape(
    monkeypatch,
    route_handler,
    method_name: str,
    path: str,
    payload: dict[str, Any],
    open_trade_count: int | None,
    expected_message: str,
) -> None:
    """Single and batch config updates should share the same conflict contract."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )
    if open_trade_count is not None:
        _DummyOpenTradesCount.count_value = open_trade_count
        monkeypatch.setattr(config_controller, "OpenTrades", _DummyOpenTradesCount)

    app = Litestar(route_handlers=[route_handler])
    with TestClient(app=app) as client:
        response = getattr(client, method_name)(path, json=payload)

    assert response.status_code == 409
    assert response.json() == {
        "error": expected_message,
        "message": expected_message,
    }


def test_live_activation_endpoint_blocks_when_setup_is_incomplete(monkeypatch) -> None:
    """Dedicated live activation must enforce readiness checks."""
    service = _DummyConfigService()
    service._cache.update(
        {
            "dry_run": True,
            "signal": "asap",
            "exchange": "binance",
            "timeframe": "1h",
            "currency": "USDT",
        }
    )

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.activate_live_trading])
    with TestClient(app=app) as client:
        response = client.post("/config/live/activate", json={"confirm": True})

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"] == "Live activation blocked until setup is complete."
    assert any(blocker["key"] == "key" for blocker in payload["blockers"])
    assert service.last_single is None


def test_live_activation_endpoint_blocks_missing_global_max_fund(monkeypatch) -> None:
    """Dedicated live activation must require a positive global max fund."""
    service = _DummyConfigService()
    service._cache.update(
        {
            "dry_run": True,
            "timezone": "Europe/Vienna",
            "signal": "asap",
            "exchange": "binance",
            "timeframe": "1h",
            "key": "api-key",
            "secret": "api-secret",
            "currency": "USDT",
            "max_bots": 2,
            "bo": 20,
            "tp": 1.5,
            "capital_max_fund": 0,
            "history_lookback_time": "180d",
            "symbol_list": "BTC/USDT",
        }
    )

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.activate_live_trading])
    with TestClient(app=app) as client:
        response = client.post("/config/live/activate", json={"confirm": True})

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"] == "Live activation blocked until setup is complete."
    assert {
        "key": "capital_max_fund",
        "message": "Set a positive global max fund.",
    } in payload["blockers"]
    assert service.last_single is None


def test_live_activation_endpoint_switches_dry_run_off(monkeypatch) -> None:
    """Dedicated live activation should persist dry_run=false when ready."""
    service = _DummyConfigService()
    service._cache.update(
        {
            "dry_run": True,
            "timezone": "Europe/Vienna",
            "signal": "asap",
            "exchange": "binance",
            "timeframe": "1h",
            "key": "api-key",
            "secret": "api-secret",
            "currency": "USDT",
            "max_bots": 2,
            "bo": 20,
            "tp": 1.5,
            "capital_max_fund": 250,
            "history_lookback_time": "180d",
            "symbol_list": "BTC/USDT",
        }
    )

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.activate_live_trading])
    with TestClient(app=app) as client:
        response = client.post("/config/live/activate", json={"confirm": True})

    assert response.status_code == 201
    assert response.json() == {
        "message": "Live trading activated.",
        "already_live": False,
    }
    assert service.last_single == (
        "dry_run",
        {"value": False, "type": "bool"},
    )


def test_config_route_handlers_expose_freshness_and_live_activation(
    monkeypatch,
) -> None:
    """The real config route list should expose freshness and live activation."""
    service = _DummyConfigService()
    service._cache.update(
        {
            "dry_run": True,
            "timezone": "Europe/Vienna",
            "signal": "asap",
            "exchange": "binance",
            "timeframe": "1h",
            "key": "api-key",
            "secret": "api-secret",
            "currency": "USDT",
            "max_bots": 2,
            "bo": 20,
            "tp": 1.5,
            "capital_max_fund": 250,
            "history_lookback_time": "180d",
            "symbol_list": "BTC/USDT",
        }
    )

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    freshness_timestamp = datetime(2026, 3, 20, 17, 38, tzinfo=timezone.utc)
    _DummyAppConfigModel.latest_row = type(
        "_DummyAppConfigRow",
        (),
        {"updated_at": freshness_timestamp},
    )()

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )
    monkeypatch.setattr(config_controller, "AppConfig", _DummyAppConfigModel)
    expected_config_snapshot = {
        **service.snapshot(),
        "config_updated_at": freshness_timestamp.isoformat(),
    }

    app = Litestar(route_handlers=config_controller.route_handlers)
    with TestClient(app=app) as client:
        config_response = client.get("/config/all")
        freshness_response = client.get("/config/freshness")
        activation_response = client.post(
            "/config/live/activate", json={"confirm": True}
        )

    assert config_response.status_code == 200
    assert config_response.json() == expected_config_snapshot
    assert freshness_response.status_code == 200
    assert freshness_response.json() == {"updated_at": freshness_timestamp.isoformat()}
    assert activation_response.status_code == 201
    assert activation_response.json() == {
        "message": "Live trading activated.",
        "already_live": False,
    }
    assert service.last_single == (
        "dry_run",
        {"value": False, "type": "bool"},
    )


def test_config_single_invalid_json_returns_validation_error() -> None:
    """Invalid JSON for single-key config update should return the legacy error."""
    app = Litestar(route_handlers=[config_controller.update_config_key])
    with TestClient(app=app) as client:
        response = client.put(
            "/config/single/signal",
            content="{invalid",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {"error": "Payload must be a JSON object"}


def test_config_multiple_invalid_json_returns_validation_error() -> None:
    """Invalid JSON for batch config update should return the legacy error."""
    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    with TestClient(app=app) as client:
        response = client.post(
            "/config/multiple",
            content="{invalid",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {"error": "'data' must be a JSON object"}


def test_config_single_rejects_legacy_stringified_update_payload() -> None:
    """Single-key config updates should reject legacy string payloads."""
    app = Litestar(route_handlers=[config_controller.update_config_key])
    with TestClient(app=app) as client:
        response = client.put(
            "/config/single/signal",
            json={"value": '{"value":"csv_signal","type":"str"}'},
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": "Config value must be an object with 'value' and 'type'."
    }


def test_config_multiple_rejects_legacy_stringified_update_payloads() -> None:
    """Batch config updates should reject legacy string payloads."""
    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    with TestClient(app=app) as client:
        response = client.post(
            "/config/multiple",
            json={"dry_run": '{"value": false, "type": "bool"}'},
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": (
            "Config updates must be objects with 'value' and 'type'. "
            "Invalid keys: dry_run"
        )
    }


def test_config_single_rejects_removed_legacy_autopilot_max_fund_key(
    monkeypatch,
) -> None:
    """Single-key config updates should reject removed legacy max-fund writes."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_config_key])
    with TestClient(app=app) as client:
        response = client.put(
            "/config/single/autopilot_max_fund",
            json={"value": {"value": 250, "type": "int"}},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": (
            "Config key 'autopilot_max_fund' was removed in v1.4.0.0. "
            "Use 'capital_max_fund' instead."
        ),
        "message": (
            "Config key 'autopilot_max_fund' was removed in v1.4.0.0. "
            "Use 'capital_max_fund' instead."
        ),
    }
    assert service.last_single is None


def test_config_multiple_rejects_removed_legacy_autopilot_max_fund_key(
    monkeypatch,
) -> None:
    """Batch config updates should reject removed legacy max-fund writes."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    with TestClient(app=app) as client:
        response = client.post(
            "/config/multiple",
            json={
                "capital_max_fund": {"value": 250, "type": "int"},
                "autopilot_max_fund": {"value": 250, "type": "int"},
            },
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": (
            "Config key 'autopilot_max_fund' was removed in v1.4.0.0. "
            "Use 'capital_max_fund' instead."
        ),
        "message": (
            "Config key 'autopilot_max_fund' was removed in v1.4.0.0. "
            "Use 'capital_max_fund' instead."
        ),
    }
    assert service.last_batch is None


def test_trades_websocket_disconnect_is_not_logged_as_error(monkeypatch) -> None:
    """Expected WebSocket disconnect should not trigger error logging."""
    errors: list[tuple[Any, ...]] = []

    async def _fake_open_trades() -> list[dict[str, Any]]:
        return [{"id": 1}]

    monkeypatch.setattr(trades_controller, "_get_open_trades_cached", _fake_open_trades)
    monkeypatch.setattr(
        trades_controller.logging, "error", lambda *args, **kwargs: errors.append(args)
    )

    app = Litestar(route_handlers=[trades_controller.open_trades])
    with TestClient(app=app) as client:
        with client.websocket_connect("/trades/open") as socket:
            payload = json.loads(socket.receive_text())
            assert payload == [{"id": 1}]

    # Give server side a short window to process close callback paths.
    time.sleep(0.05)

    assert errors == []


def test_closed_trades_websocket_disconnect_is_not_logged_as_error(
    monkeypatch,
) -> None:
    """Expected closed-trades WebSocket disconnect should not log errors."""
    errors: list[tuple[Any, ...]] = []

    async def _fake_closed_trades() -> list[dict[str, Any]]:
        return [{"id": 2}]

    monkeypatch.setattr(
        trades_controller, "_get_closed_trades_cached", _fake_closed_trades
    )
    monkeypatch.setattr(
        trades_controller.logging, "error", lambda *args, **kwargs: errors.append(args)
    )

    app = Litestar(route_handlers=[trades_controller.closed_trades])
    with TestClient(app=app) as client:
        with client.websocket_connect("/trades/closed") as socket:
            payload = json.loads(socket.receive_text())
            assert payload == [{"id": 2}]

    time.sleep(0.05)

    assert errors == []


def test_statistics_websocket_disconnect_is_not_logged_as_error(monkeypatch) -> None:
    """Expected WebSocket disconnect should not trigger error logging."""
    errors: list[tuple[Any, ...]] = []

    async def _fake_profit() -> dict[str, Any]:
        return {"upnl": 1.0}

    monkeypatch.setattr(statistics_controller, "_get_profit_cached", _fake_profit)
    monkeypatch.setattr(
        statistics_controller.logging,
        "error",
        lambda *args, **kwargs: errors.append(args),
    )

    app = Litestar(route_handlers=[statistics_controller.profit])
    with TestClient(app=app) as client:
        with client.websocket_connect("/statistic/profit") as socket:
            payload = json.loads(socket.receive_text())
            assert payload == {"upnl": 1.0}

    # Give server side a short window to process close callback paths.
    time.sleep(0.05)

    assert errors == []


def test_manual_buy_invalid_json_returns_validation_error() -> None:
    """Invalid JSON for manual buy should return the legacy validation payload."""
    app = Litestar(route_handlers=[orders_controller.add_manual_buy])
    with TestClient(app=app) as client:
        response = client.post(
            "/orders/buy/manual",
            content="{invalid",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "result": "",
        "error": "Payload must be a JSON object",
    }


def test_order_mutations_require_post(monkeypatch) -> None:
    """Sell, buy, and stop endpoints must reject GET and accept POST."""
    service = _DummyConfigService()
    captured_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    async def _fake_sell(symbol: str, _config: Any) -> bool:
        captured_calls.append(("sell", (symbol,)))
        return True

    async def _fake_buy(symbol: str, ordersize: str, _config: Any) -> bool:
        captured_calls.append(("buy", (symbol, ordersize)))
        return True

    async def _fake_stop(symbol: str, _config: Any) -> bool:
        captured_calls.append(("stop", (symbol,)))
        return True

    monkeypatch.setattr(
        orders_controller.Config, "instance", classmethod(_fake_instance)
    )
    monkeypatch.setattr(orders_controller.orders, "receive_sell_signal", _fake_sell)
    monkeypatch.setattr(orders_controller.orders, "receive_buy_signal", _fake_buy)
    monkeypatch.setattr(orders_controller.orders, "receive_stop_signal", _fake_stop)

    app = Litestar(
        route_handlers=[
            orders_controller.sell_order,
            orders_controller.buy_order,
            orders_controller.stop_order,
        ]
    )

    with TestClient(app=app) as client:
        assert client.get("/orders/sell/btc-usdt").status_code == 405
        assert client.get("/orders/buy/btc-usdt/10").status_code == 405
        assert client.get("/orders/stop/btc-usdt").status_code == 405

        sell_response = client.post("/orders/sell/btc-usdt")
        buy_response = client.post("/orders/buy/btc-usdt/10")
        stop_response = client.post("/orders/stop/btc-usdt")

    assert sell_response.status_code == 200
    assert sell_response.json() == {"result": "sell"}
    assert buy_response.status_code == 200
    assert buy_response.json() == {"result": "new_so"}
    assert stop_response.status_code == 200
    assert stop_response.json() == {"result": "stop"}
    assert captured_calls == [
        ("sell", ("btc-usdt",)),
        ("buy", ("btc-usdt", "10")),
        ("stop", ("btc-usdt",)),
    ]
