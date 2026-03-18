"""Regression tests for Litestar migration edge cases."""

import json
import time
from pathlib import Path
from typing import Any

from controller import config as config_controller
from controller import frontend as frontend_controller
from controller import orders as orders_controller
from controller import statistics as statistics_controller
from controller import trades as trades_controller
from litestar import Litestar
from litestar.testing import TestClient


class _DummyConfigService:
    """Minimal config service stub for controller tests."""

    def __init__(self) -> None:
        self.last_batch: dict[str, Any] | None = None
        self._cache: dict[str, Any] = {"signal": "asap"}

    async def batch_set(self, payload: dict[str, Any]) -> bool:
        self.last_batch = payload
        return True

    async def set(self, key: str, value: Any) -> bool:
        self._cache[key] = value
        return True

    def get(self, key: str, default: Any | None = None) -> Any | None:
        return self._cache.get(key, default)


class _DummyOpenTradesCount:
    """OpenTrades stub exposing count() through all()."""

    count_value = 0

    @classmethod
    def all(cls) -> "_DummyOpenTradesCount":
        return cls()

    async def count(self) -> int:
        return self.count_value


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


def test_config_multiple_accepts_2xx_contract(monkeypatch) -> None:
    """Ensure config batch endpoint uses a successful 2xx response."""
    service = _DummyConfigService()

    async def _fake_instance(cls: type[Any]) -> _DummyConfigService:  # noqa: ANN001
        return service

    monkeypatch.setattr(
        config_controller.Config, "instance", classmethod(_fake_instance)
    )

    app = Litestar(route_handlers=[config_controller.update_multiple_config_keys])
    payload = {"dry_run": '{"value": false, "type": "bool"}'}
    with TestClient(app=app) as client:
        response = client.post("/config/multiple", json=payload)

    assert 200 <= response.status_code < 300
    assert response.status_code == 201
    assert response.json() == {"message": "Config updated"}
    assert service.last_batch == payload


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
    payload = {"signal": '{"value":"csv_signal","type":"str"}'}
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
    payload = {"value": '{"value":"csv_signal","type":"str"}'}
    with TestClient(app=app) as client:
        response = client.put("/config/single/signal", json=payload)

    assert response.status_code == 409
    assert "open trades" in response.json().get("error", "").lower()
    assert service.last_batch is None


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
