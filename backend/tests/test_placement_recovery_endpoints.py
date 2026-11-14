"""HTTP contract tests for the placement-recovery operator endpoints.

Value: protects=the recovery API contract the dashboard's recovery card
    consumes: the list envelope {"intents": [...]}, the repair/dismiss
    pass-through of service results, the error mapping (NotFound -> 404
    "not_found", Conflict -> 409 "conflict", other PlacementRepairError ->
    400 "invalid_request"), and the rule that a dismissal note is required
    before the service is reached.
fails_when=an error type maps to the wrong status or code (the card would
    swallow or mislabel a rejected repair), the list envelope changes, the
    configured snapshot is not the config the repair service sees, or a
    malformed dismiss body reaches the service.
why_new=the repair service and the recovery middleware are both tested, but
    no test exercised these real handlers, whose mapping and body validation
    are what frontend/src/api/placementRecovery.ts depends on.
seam=none (the repair service is the controller's dependency and is faked;
    the handlers under test are the real ones).
no_claim=green does not prove the middleware allows these routes in
    recovery mode, nor that the runtime wiring activates the services.
"""

from typing import Any

import pytest
from controller import orders as orders_controller
from httpx import ASGITransport, AsyncClient
from litestar import Litestar
from service.placement_repair import (
    PlacementRepairConflict,
    PlacementRepairInvalid,
    PlacementRepairNotFound,
)


class _FakeConfigService:
    """Config stub whose snapshot the repair endpoint must hand over."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        self.snapshots.append({})
        return {"exchange": "binance", "market": "spot"}


class _FakeRepairService:
    """Recording stub for the injected placement repair service."""

    def __init__(self) -> None:
        self.repair_calls: list[tuple[str, dict[str, Any]]] = []
        self.dismiss_calls: list[tuple[str, str]] = []
        self.repair_result: dict[str, Any] | None = None
        self.repair_error: Exception | None = None
        self.intents: list[dict[str, Any]] = []

    async def list_quarantined(self) -> list[dict[str, Any]]:
        return self.intents

    async def repair(
        self,
        operation_id: str,
        config: dict[str, Any],
        *,
        config_provider: Any,
    ) -> dict[str, Any]:
        self.repair_calls.append((operation_id, config))
        assert callable(config_provider)
        if self.repair_error is not None:
            raise self.repair_error
        assert self.repair_result is not None
        return self.repair_result

    async def dismiss(self, operation_id: str, note: str) -> dict[str, Any]:
        self.dismiss_calls.append((operation_id, note))
        return {
            "operation_id": operation_id,
            "status": "dismissed",
            "state": "rejected",
            "message": "dismissed",
        }


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeRepairService,
) -> tuple[Litestar, _FakeConfigService]:
    config_service = _FakeConfigService()

    class _FakeConfig:
        @staticmethod
        async def instance() -> _FakeConfigService:
            return config_service

    monkeypatch.setattr(orders_controller, "Config", _FakeConfig)
    monkeypatch.setattr(orders_controller, "placement_repair", fake)
    app = Litestar(
        route_handlers=[
            orders_controller.list_placement_recovery,
            orders_controller.repair_placement_intent,
            orders_controller.dismiss_placement_intent,
        ],
        openapi_config=None,
    )
    return app, config_service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        pytest.param(
            PlacementRepairNotFound("No placement intent found for op-x."),
            404,
            "not_found",
            id="not_found",
        ),
        pytest.param(
            PlacementRepairConflict("not quarantined"),
            409,
            "conflict",
            id="conflict",
        ),
        pytest.param(
            PlacementRepairInvalid("A placement operation id is required."),
            400,
            "invalid_request",
            id="invalid",
        ),
    ],
)
async def test_repair_endpoint_maps_service_errors_to_http_contract(
    monkeypatch: pytest.MonkeyPatch,
    error: PlacementRepairInvalid,
    status: int,
    code: str,
) -> None:
    """Each service error becomes the operator-visible status and code."""
    fake = _FakeRepairService()
    fake.repair_error = error
    app, _ = _install_fakes(monkeypatch, fake)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post("/orders/placement-recovery/op-x/repair")

    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["error"] == str(error)


@pytest.mark.asyncio
async def test_list_and_repair_endpoints_pass_through_service_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list envelope and the repair snapshot hand-off reach the client."""
    fake = _FakeRepairService()
    fake.intents = [{"operation_id": "op-1"}]
    fake.repair_result = {
        "operation_id": "op-1",
        "status": "unchanged",
        "state": "quarantined",
        "message": "retry",
    }
    app, config_service = _install_fakes(monkeypatch, fake)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        listed = await http.get("/orders/placement-recovery")
        repaired = await http.post("/orders/placement-recovery/op-1/repair")

    assert listed.status_code == 200
    assert listed.json() == {"intents": [{"operation_id": "op-1"}]}
    assert repaired.status_code == 200
    assert repaired.json() == fake.repair_result
    assert fake.repair_calls == [("op-1", {"exchange": "binance", "market": "spot"})]
    assert len(config_service.snapshots) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "valid"),
    [
        pytest.param("not-json", False, id="invalid_json"),
        pytest.param("[1, 2]", False, id="non_object"),
        pytest.param("{}", False, id="missing_note"),
        pytest.param('{"note": "   "}', False, id="blank_note"),
        pytest.param('{"note": 42}', False, id="non_string_note"),
        pytest.param('{"note": "reviewed on exchange"}', True, id="valid_note"),
    ],
)
async def test_dismiss_endpoint_validates_the_note_and_passes_it_through(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    valid: bool,
) -> None:
    """Only a non-empty string note reaches the repair service."""
    fake = _FakeRepairService()
    app, _ = _install_fakes(monkeypatch, fake)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post(
            "/orders/placement-recovery/op-1/dismiss",
            content=content,
            headers={"Content-Type": "application/json"},
        )

    if valid:
        assert response.status_code == 200
        assert response.json()["status"] == "dismissed"
        assert fake.dismiss_calls == [("op-1", "reviewed on exchange")]
        return
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert fake.dismiss_calls == []
