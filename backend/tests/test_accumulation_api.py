"""HTTP gating and exact read-only projections against a real temporary database."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import model
import pytest
import pytest_asyncio
from controller import accumulation as controller
from httpx import ASGITransport, AsyncClient
from litestar import Litestar
from litestar.middleware import DefineMiddleware
from service.accumulation_commands import AccumulationCommandResult
from service.accumulation_import import parse_accumulation_csv
from service.accumulation_state import AccumulationConflictError
from service.accumulation_strategy import build_accumulation_strategy_document
from service.origin_policy import TrustedLanHttpMiddleware
from tortoise import Tortoise


@pytest_asyncio.fixture
async def api_client():
    app = Litestar(
        route_handlers=controller.route_handlers,
        middleware=[DefineMiddleware(TrustedLanHttpMiddleware)],
        openapi_config=None,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def status_db(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(
        "service.strategy_persistence._STRATEGY_SEED_LOCK", asyncio.Lock()
    )
    promotion_lock = asyncio.Lock()
    monkeypatch.setattr(
        "service.strategy_persistence._STRATEGY_PROMOTION_LOCK", promotion_lock
    )
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'status.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture
def runtime(monkeypatch):
    owner = SimpleNamespace(
        ready=True,
        adapter=SimpleNamespace(config_provider=lambda: {}),
        notify=Mock(),
        status_events=SimpleNamespace(publish=Mock()),
        performance=AsyncMock(),
        status={},
        submit_command=AsyncMock(),
        entry=SimpleNamespace(submit_staged=AsyncMock()),
        repairs=SimpleNamespace(submit=AsyncMock()),
    )
    monkeypatch.setattr(
        controller.accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", True
    )
    monkeypatch.setattr(controller, "get_active_accumulation_runtime", lambda: owner)
    return owner


@pytest.mark.asyncio
async def test_release_gate_rejects_all_routes_without_resolving_services(
    api_client, monkeypatch
):
    monkeypatch.setattr(
        controller.accumulation_runtime, "ACCUMULATION_RUNTIME_AVAILABLE", False
    )
    monkeypatch.setattr(
        controller,
        "get_active_accumulation_runtime",
        lambda: pytest.fail("must not resolve credentials or clients"),
    )
    for method, path in [
        ("GET", "/accumulation/activations"),
        ("GET", "/accumulation/activation?symbol=BTC/USDC"),
        ("POST", "/accumulation/commands"),
        ("POST", "/accumulation/entry/commands"),
        ("POST", "/accumulation/repair"),
        ("GET", "/accumulation/strategies"),
        ("POST", "/accumulation/strategies"),
    ]:
        response = await api_client.request(method, path, content="not-json")
        assert response.status_code == 503
        assert response.json()["code"] == "unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_stopping_lifespan_rejects_requests(
    api_client, runtime, monkeypatch, missing
):
    runtime.ready = False
    if missing:
        monkeypatch.setattr(controller, "get_active_accumulation_runtime", lambda: None)
    assert (await api_client.get("/accumulation/activations")).status_code == 503
    assert (await api_client.post("/accumulation/commands", json={})).status_code == 503
    runtime.submit_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["commands", "entry/commands", "repair"])
@pytest.mark.parametrize("body", ["{", "[]", "null", '"text"'])
async def test_nonobject_commands_are_rejected_before_service(
    api_client, runtime, path, body
):
    response = await api_client.post(
        f"/accumulation/{path}",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    runtime.submit_command.assert_not_awaited()
    runtime.entry.submit_staged.assert_not_awaited()
    runtime.repairs.submit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["commands", "entry/commands"])
async def test_command_http_distinguishes_pending_historical_and_conflict(
    api_client, runtime, path
):
    service = (
        runtime.submit_command if path == "commands" else runtime.entry.submit_staged
    )
    payload = {"operation_id": "same-request", "expected_revision": 3}
    service.return_value = AccumulationCommandResult(
        "same-request", "activation", "pending", "closing", 4, "settlement_required"
    )
    response = await api_client.post(f"/accumulation/{path}", json=payload)
    assert response.status_code == 202
    assert response.json()["operation"]["revision"] == 4
    service.assert_awaited_once_with(payload)
    service.return_value = AccumulationCommandResult(
        "same-request", "activation", "applied", "stopped", 5, None
    )
    assert (
        await api_client.post(f"/accumulation/{path}", json=payload)
    ).status_code == 200
    service.side_effect = AccumulationConflictError("Stale lifecycle revision")
    response = await api_client.post(f"/accumulation/{path}", json=payload)
    assert response.status_code == 409 and response.json()["code"] == "conflict"
    service.side_effect = ValueError("Invalid symbol")
    assert (
        await api_client.post(f"/accumulation/{path}", json=payload)
    ).status_code == 400
    assert runtime.notify.call_count == 2  # Only acknowledged commands wake the owner.


@pytest.mark.asyncio
async def test_new_mutations_obey_existing_browser_origin_policy(api_client, runtime):
    for path in ("commands", "entry/commands"):
        response = await api_client.post(
            f"/accumulation/{path}",
            json={},
            headers={
                "origin": "https://evil.example",
                "x-moonwalker-client": "dashboard",
            },
        )
        assert response.status_code == 403
    runtime.submit_command.assert_not_awaited()
    runtime.entry.submit_staged.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_pages_preserve_exact_unknown_and_stopped_inventory(
    api_client, runtime, status_db
):
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=7,
        ir_json="{}",
        validation_json="{}",
        explanation="test",
    )
    holding = await model.OpenTrades.create(
        symbol="BTC/USDC",
        lifecycle_mode="accumulation",
        amount=12345,
        accumulation_net_quantity="0.000000000000000001",
        accumulation_remaining_cost=None,
        accumulation_contributed_quote="12.000000000000000001",
        accumulation_disposal_proceeds="10",
        accumulation_basis_provenance="unknown",
        execution_history_complete=False,
    )
    for symbol, state in [
        ("ADA/USDC", "validating"),
        ("BTC/USDC", "closing"),
        ("ETH/USDC", "stopped"),
    ]:
        await model.AccumulationActivation.create(
            symbol=symbol,
            account_scope="secret-scope",
            state=state,
            strategy_version=version,
            holding=holding if symbol == holding.symbol else None,
            revision=11,
        )
    runtime.status["BTC/USDC"] = "WAIT_MINIMUM"
    first = (await api_client.get("/accumulation/activations?limit=2")).json()
    assert [row["symbol"] for row in first["activations"]] == ["ADA/USDC", "BTC/USDC"]
    assert first["next_after"] == "BTC/USDC"
    btc = first["activations"][1]
    assert btc["revision"] == 11 and btc["state"] == "closing"
    assert btc["strategy_version"] == 7 and btc["runtime_wait_reason"] == "WAIT_MINIMUM"
    assert btc["holding"]["net_quantity"] == "0.000000000000000001"
    assert btc["holding"]["remaining_cost"] is None
    assert btc["holding"]["contributed_quote"] == "12.000000000000000001"
    assert not btc["holding"]["execution_history_complete"]
    second = (
        await api_client.get(
            "/accumulation/activations",
            params={"limit": 2, "after": first["next_after"]},
        )
    ).json()
    assert second["next_after"] is None
    assert second["activations"][0]["state"] == "stopped"
    assert second["activations"][0]["holding"] is None
    assert "secret-scope" not in json.dumps(first)
    assert await model.PlacementIntent.all().count() == 0
    assert (await model.AccumulationActivation.get(symbol="BTC/USDC")).revision == 11


@pytest.mark.asyncio
async def test_entry_detail_redacts_raw_requests_and_bounds_history(
    api_client, runtime, status_db
):
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="private-scope", revision=25
    )
    imported = parse_accumulation_csv(
        "1970-01-02;BTC/USDC;60.000000000000000001;0.1", "USDC", now_ms=100000000
    )[0]
    for index in range(25):
        await model.AccumulationLifecycleOperation.create(
            activation=activation,
            operation_id=f"request-{index}",
            action="correct_import",
            request_json=json.dumps(
                {
                    "source": "csv",
                    "imported_inventory": imported.to_dict(),
                    "secret": "must-not-leak",
                }
            ),
            previous_state="validating",
            previous_paused=True,
            result_state="validating",
            result_revision=index + 1,
            status="continued" if index < 24 else "pending",
        )
    response = await api_client.get(
        "/accumulation/activation", params={"symbol": "btc_usdc"}
    )
    assert response.status_code == 200
    result = response.json()
    assert len(result["operations"]) == 20 and result["older_operations_available"]
    assert result["entry"]["operation_id"] == "request-24"
    assert result["entry"]["declaration"]["acquisition_cost"] == "6.0000000000000000001"
    assert not result["entry"]["declaration"]["historical_fees_known"]
    assert "must-not-leak" not in response.text and "private-scope" not in response.text
    await model.AccumulationLifecycleOperation.filter(operation_id="request-24").update(
        request_json="{invalid"
    )
    malformed = (
        await api_client.get("/accumulation/activation?symbol=BTC/USDC")
    ).json()
    assert (
        malformed["entry"]["declaration_invalid"]
        and malformed["entry"]["declaration"] is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["limit=0", "limit=101", "after=invalid"])
async def test_status_rejects_unbounded_or_invalid_queries(
    api_client, runtime, status_db, query
):
    assert (
        await api_client.get(f"/accumulation/activations?{query}")
    ).status_code == 400
    assert (
        await api_client.get("/accumulation/activation?symbol=invalid")
    ).status_code == 400
    assert (
        await api_client.get("/accumulation/activation?symbol=BTC/USDC")
    ).status_code == 404


@pytest.mark.asyncio
async def test_retired_dip_writer_cannot_recreate_deleted_presets(
    api_client, runtime, status_db
):
    payload = {
        "operation_id": "old-dip-save",
        "name": "Accumulation dip",
        "parameters": build_accumulation_strategy_document()["parameters"],
    }
    for _ in range(2):
        response = await api_client.post("/accumulation/strategies", json=payload)
        assert response.status_code == 410
        assert response.json()["code"] == "retired_strategy_writer"
    assert not await model.StrategyVersion.exists()
    assert not await model.StrategyDefinition.exists()
    assert not await model.AccumulationActivation.exists()


@pytest.mark.asyncio
async def test_strategy_catalog_scan_pages_only_compatible_documents(
    api_client, runtime, status_db
):
    for index, document in enumerate(
        [
            {},
            build_accumulation_strategy_document(),
            {"capability": "accumulation/v2"},
            build_accumulation_strategy_document(),
        ]
    ):
        await model.StrategyVersion.create(
            strategy_slug=f"strategy-{index}",
            version=1,
            ir_json=json.dumps(document),
            validation_json="{}",
            explanation="test",
        )
    first = (await api_client.get("/accumulation/strategies?limit=1")).json()
    assert not first["versions"] and first["next_after_id"] is not None
    seen = []
    page = first
    while page["next_after_id"] is not None:
        page = (
            await api_client.get(
                "/accumulation/strategies",
                params={"limit": 1, "after_id": page["next_after_id"]},
            )
        ).json()
        seen.extend(page["versions"])
    assert [row["slug"] for row in seen] == [
        "strategy-1",
        "strategy-3",
        "regime_accumulation",
    ]
    assert seen[0]["required_history_candles"] == 253
    assert page["defaults"]["max_fraction"] == "0.20"
    from service.strategy_catalog import BUILTIN_STRATEGIES

    assert await model.StrategyDefinition.all().count() == len(BUILTIN_STRATEGIES)


@pytest.mark.asyncio
async def test_portfolio_totals_are_exact_complete_across_pages_and_quote_scoped(
    api_client, runtime, status_db
):
    for symbol, cost in [
        ("ADA/USDC", "0.100000000000000001"),
        ("BTC/USDC", "0.200000000000000002"),
        ("ETH/USDC", None),
        ("SOL/USDT", "9"),
    ]:
        holding = await model.OpenTrades.create(
            symbol=symbol,
            lifecycle_mode="accumulation",
            accumulation_remaining_cost=cost,
            cost=999999,  # The legacy float must never supply an exact projection.
        )
        if symbol != "SOL/USDT":
            await model.AccumulationActivation.create(
                symbol=symbol, account_scope="private", holding=holding
            )
    await model.OpenTrades.create(symbol="XRP/USDC", cost=100)
    first = (await api_client.get("/accumulation/activations?limit=1")).json()
    second = (
        await api_client.get(
            "/accumulation/activations",
            params={"after": first["next_after"], "limit": 1},
        )
    ).json()
    portfolio = first["portfolio"]
    assert portfolio == second["portfolio"]
    assert portfolio["holding_count"] == 4
    assert portfolio["unverified_holding_count"] == 1
    assert not portfolio["valuation_available"]
    assert portfolio["by_quote"] == [
        {
            "quote": "USDC",
            "holding_count": 3,
            "known_remaining_cost": "0.300000000000000003",
            "remaining_cost": None,
            "unknown_cost_count": 1,
        },
        {
            "quote": "USDT",
            "holding_count": 1,
            "known_remaining_cost": "9",
            "remaining_cost": "9",
            "unknown_cost_count": 0,
        },
    ]


@pytest.mark.asyncio
async def test_stopped_order_history_retains_exact_cumulative_evidence_without_secrets(
    api_client, runtime, status_db
):
    from service.accumulation_fill import AccumulationInventory

    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC", state="stopped", account_scope="private-scope"
    )
    inventory = AccumulationInventory(
        "0",
        None,
        None,
        "123.000000000000000001",
        {"BNB": "0.000000000000000001"},
        basis_provenance="unknown",
    )
    for index in range(22):
        placement = await model.PlacementIntent.create(
            operation_id=f"order-{index}",
            symbol=activation.symbol,
            exchange_name="binance",
            side="sell",
            action="sell",
            order_type="market",
            state="completed",
            request_json='{"secret":"do-not-expose"}',
        )
        await model.AccumulationFillCheckpoint.create(
            activation=activation,
            placement=placement,
            deal_id="closed-deal",
            filled="0.100000000000000001",
            quote_cost="12.000000000000000001",
            fees_json='{"BNB":"0.000000000000000001"}',
            fees_complete=True,
            terminal=True,
            evidence_json='{"account":"do-not-expose"}',
            inventory_json=inventory.serialize(),
        )
    response = await api_client.get("/accumulation/activation?symbol=BTC/USDC")
    data = response.json()
    assert data["holding"] is None and data["state"] == "stopped"
    assert data["portfolio"]["holding_count"] == 0
    assert len(data["orders"]) == 20 and data["older_orders_available"]
    assert data["orders"][0]["checkpoint_id"] > data["orders"][-1]["checkpoint_id"]
    latest = data["orders"][0]
    assert latest["placement_operation_id"] == "order-21"
    assert latest["filled_quantity"] == "0.100000000000000001"
    assert latest["quote_cost"] == "12.000000000000000001"
    assert latest["inventory_at_update"]["remaining_cost"] is None
    assert latest["inventory_at_update"]["net_quantity"] == "0"
    assert latest["fees"] == {"BNB": "0.000000000000000001"}
    assert "do-not-expose" not in response.text and "private-scope" not in response.text
    checkpoint = await model.AccumulationFillCheckpoint.all().order_by("-id").first()
    checkpoint.fees_json = "null"
    checkpoint.inventory_json = "corrupt"
    await checkpoint.save()
    data = (await api_client.get("/accumulation/activation?symbol=BTC/USDC")).json()
    assert len(data["orders"]) == 20  # Corrections do not append duplicate orders.
    assert data["orders"][0]["fees"] is None
    assert not data["orders"][0]["fees_complete"]
    assert data["orders"][0]["inventory_at_update"] is None


@pytest.mark.asyncio
async def test_accumulation_suppresses_unverified_legacy_performance_and_chart_samples(
    status_db,
):
    from service.statistic import Statistic

    statistic = Statistic()
    await model.OpenTrades.create(symbol="ETH/USDC", profit=2, cost=10)
    await model.OpenTrades.create(
        symbol="BTC/USDC",
        lifecycle_mode="accumulation",
        profit=9999,
        cost=9999,
        accumulation_remaining_cost="12.000000000000000001",
    )
    result = await statistic._get_profit_base_cached()
    assert result["upnl"] == 2
    assert result["funds_locked"] == 22
    assert result["performance_complete"] is False
    assert result["performance_scope"] == "dynamic_dca_only"
    assert await model.UpnlHistory.all().count() == 0
    await model.OpenTrades.filter(lifecycle_mode="accumulation").delete()
    await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="private", state="stopped"
    )
    assert await statistic._performance_complete() is False


@pytest.mark.asyncio
async def test_repair_http_requires_explicit_body_and_reports_remaining_quarantine(
    api_client, runtime
):
    request = {
        "symbol": "BTC/USDC",
        "action": "repair_order",
        "operation_id": "repair-request",
        "expected_revision": 5,
        "placement_operation_id": "restored-placement",
    }
    runtime.repairs.submit.return_value = AccumulationCommandResult(
        "repair-request",
        "activation",
        "quarantined",
        "paused",
        6,
        "terminal_evidence_required",
    )
    response = await api_client.post("/accumulation/repair", json=request)
    assert response.status_code == 202
    runtime.repairs.submit.assert_awaited_once_with(request)
    runtime.repairs.submit.return_value = AccumulationCommandResult(
        "repair-request",
        "activation",
        "applied",
        "paused",
        7,
        "terminal_evidence_accounted",
    )
    assert (
        await api_client.post("/accumulation/repair", json=request)
    ).status_code == 200
    runtime.repairs.submit.side_effect = AccumulationConflictError("Stale repair")
    assert (
        await api_client.post("/accumulation/repair", json=request)
    ).status_code == 409


@pytest.mark.parametrize(
    "value", [None, "NaN", "-1", "1e500", True, {}, "", "0.000000000000000001"]
)
def test_reporting_amount_never_invents_unknown_cost(value):
    from service.accumulation_reporting import _amount

    assert _amount(value) == (value if value == "0.000000000000000001" else None)


@pytest.mark.asyncio
async def test_account_status_compares_configured_scope_without_exposing_credentials(
    api_client, runtime, status_db
):
    runtime.current_account_scope = "new-private-scope"
    await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="old-private-scope"
    )
    response = await api_client.get("/accumulation/activation?symbol=BTC/USDC")
    assert response.json()["account_matches"] is False
    assert (
        "old-private-scope" not in response.text
        and "new-private-scope" not in response.text
    )
    runtime.current_account_scope = "old-private-scope"
    assert (await api_client.get("/accumulation/activations")).json()["activations"][0][
        "account_matches"
    ] is True


@pytest.mark.asyncio
async def test_replay_endpoint_uses_exact_pinned_strategy_without_account_actions(
    api_client, status_db, runtime
):
    from test_accumulation_replay import replay_fixture

    _, payload = replay_fixture()
    version = await model.StrategyVersion.create(
        strategy_slug="replay-fixture",
        version=1,
        ir_json=json.dumps(build_accumulation_strategy_document()),
        validation_json="{}",
        explanation="fixture",
    )
    response = await api_client.post(
        "/accumulation/replay",
        json={**payload, "strategy_version_id": version.id},
        headers={"X-Moonwalker-Client": "dashboard"},
    )
    assert response.status_code == 200
    report = response.json()
    assert report["simulation_only"] and report["strategy_version_id"] == version.id
    assert len(report["results"]) == 3
    runtime.repairs.submit.assert_not_awaited()
    runtime.submit_command.assert_not_awaited()
    assert not await model.PlacementIntent.exists()


@pytest.mark.asyncio
async def test_fresh_setup_has_builtin_accumulation_without_configuration_or_builder(
    api_client, runtime, status_db
):
    from service.strategy_persistence import (
        list_strategy_options,
        seed_builtin_strategies,
    )

    response = await api_client.get("/accumulation/strategies")
    assert response.status_code == 200
    starter = response.json()["versions"][0]
    assert starter["name"] == "Downtrend / sideways accumulation"
    assert starter["version"] == 1
    version = await model.StrategyVersion.get(id=starter["id"])
    original = version.ir_json
    definition = await model.StrategyDefinition.get(slug=starter["slug"])
    assert definition.is_builtin
    await seed_builtin_strategies()
    assert starter["slug"] in await list_strategy_options()
    second = (await api_client.get("/accumulation/strategies")).json()
    assert starter["id"] in [row["id"] for row in second["versions"]]
    assert (await model.StrategyVersion.get(id=starter["id"])).ir_json == original
    assert (
        await model.StrategyVersion.filter(strategy_slug=starter["slug"]).count() == 1
    )
    assert not await model.AppConfig.exists()
    assert not await model.AccumulationActivation.exists()
    assert not await model.PlacementIntent.exists()


@pytest.mark.asyncio
async def test_global_builtin_seed_exposes_starter_before_accumulation_setup(
    api_client, runtime, status_db
):
    from service.accumulation_strategy import BUILTIN_ACCUMULATION_SLUG
    from service.strategy_persistence import seed_builtin_strategies

    await seed_builtin_strategies()
    assert not await model.StrategyDefinition.filter(
        slug=BUILTIN_ACCUMULATION_SLUG
    ).exists()
    response = await api_client.get("/accumulation/strategies")
    assert response.status_code == 200
    assert [row["slug"] for row in response.json()["versions"]] == [
        "regime_accumulation",
    ]
    assert not await model.AppConfig.exists()


@pytest.mark.asyncio
async def test_concurrent_setup_clients_seed_one_immutable_starter(
    status_db, monkeypatch
):
    import asyncio

    from service import accumulation_catalog

    monkeypatch.setattr(
        "service.strategy_persistence._STRATEGY_SEED_LOCK", asyncio.Lock()
    )
    await asyncio.gather(
        *(accumulation_catalog.list_accumulation_strategies() for _ in range(8))
    )
    assert (
        await model.StrategyDefinition.filter(slug="regime_accumulation").count() == 1
    )
    assert (
        await model.StrategyVersion.filter(strategy_slug="regime_accumulation").count()
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "revision",
        "strategy_version_id",
        "activation_id",
        "reason",
        "expired",
        "account",
    ],
)
async def test_wait_levels_are_only_projected_for_current_matching_evidence(
    api_client, runtime, status_db, monkeypatch, invalid
):
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="test",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC",
        account_scope="account",
        strategy_version=version,
        state="enabled",
        explicitly_paused=False,
        revision=4,
        observations_initialized=True,
    )
    runtime.current_account_scope = "account"
    runtime.status = {"BTC/USDC": "WAIT_DEPTH"}
    evidence = {
        "activation_id": str(activation.id),
        "revision": 4,
        "strategy_version_id": version.id,
        "reason": "WAIT_DEPTH",
        "observed_close_ms": 3600000,
        "next_close_ms": 7200000,
        "observed_price": "100",
        "timeframe": "1h",
        "levels": [
            {
                "kind": "depth",
                "direction": "at_or_below",
                "target_price": "98",
                "change_percent": "-2",
            }
        ],
    }
    monkeypatch.setattr(
        "service.accumulation_status.time.time_ns", lambda: 3600001000000
    )
    if invalid in {"revision", "strategy_version_id"}:
        evidence[invalid] += 1
    elif invalid in {"activation_id", "reason"}:
        evidence[invalid] = "different"
    elif invalid == "expired":
        evidence["next_close_ms"] = 3600000
    elif invalid == "account":
        runtime.current_account_scope = "another"
    runtime.wait_conditions = {"BTC/USDC": evidence}
    response = await api_client.get(
        "/accumulation/activation", params={"symbol": "BTC/USDC"}
    )
    assert response.status_code == 200
    assert response.json()["wait_condition"] == (evidence if invalid is None else None)


@pytest.mark.asyncio
async def test_runtime_status_notifications_are_deduplicated_and_include_lifecycle_changes(
    status_db, monkeypatch
):
    import asyncio

    from service.accumulation_runtime import AccumulationRuntime

    owner = AccumulationRuntime(
        SimpleNamespace(
            exchange=SimpleNamespace(), readiness=AsyncMock(), account_scope=AsyncMock()
        )
    )
    monkeypatch.setattr(
        AccumulationRuntime, "current_account_scope", property(lambda _: "account")
    )
    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="test",
    )
    activation = await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="account", strategy_version=version
    )
    updates = owner.status_events.subscribe()
    await anext(updates)
    await owner.publish_status()
    await anext(updates)
    pending = asyncio.create_task(anext(updates))
    await owner.publish_status()
    await asyncio.sleep(0)
    assert not pending.done()
    owner.status["BTC/USDC"] = "WAIT_DEPTH"
    await owner.publish_status()
    await asyncio.wait_for(pending, 0.2)
    pending = asyncio.create_task(anext(updates))
    activation.revision += 1
    await activation.save()
    await owner.publish_status()
    await asyncio.wait_for(pending, 0.2)
    await updates.aclose()
    assert not owner.status_events.connected


@pytest.mark.asyncio
@pytest.mark.parametrize("begin_number", [1, 2])
async def test_disconnecting_stream_snapshot_does_not_strand_sqlite(
    status_db, monkeypatch, begin_number
):
    import asyncio

    from service.accumulation_status import accumulation_stream_snapshot
    from tortoise.backends.sqlite.client import SqliteTransactionWrapper
    from tortoise.connection import connections

    version = await model.StrategyVersion.create(
        strategy_slug="accumulation_dip_v1",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="test",
    )
    await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="account", strategy_version=version
    )
    entered, release = asyncio.Event(), asyncio.Event()
    original = SqliteTransactionWrapper.begin
    count = 0

    async def begin(self):
        nonlocal count
        count += 1
        if count == begin_number:
            entered.set()
            await release.wait()
        await original(self)

    monkeypatch.setattr(SqliteTransactionWrapper, "begin", begin)
    task = asyncio.create_task(
        accumulation_stream_snapshot(
            "BTC/USDC",
            wait_reasons={},
            wait_conditions={},
            configured_account_scope="account",
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert (
            await asyncio.wait_for(model.AccumulationActivation.all().count(), 0.2) == 1
        )
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        connection = connections.get("default")
        if connection._lock.locked():
            connection._lock.release()


@pytest.mark.asyncio
async def test_retired_dip_presets_leave_catalogs_without_losing_pinned_history(
    api_client, runtime, status_db
):
    from service.accumulation_strategy import BUILTIN_ACCUMULATION_SLUG, CATALOG_PREFIX
    from service.strategy_persistence import (
        get_strategy_detail,
        list_strategy_summaries,
    )
    from service.strategy_runtime import load_accumulation_strategy_version

    original = json.dumps(build_accumulation_strategy_document())
    retained = []
    for slug, builtin, symbol in [
        (BUILTIN_ACCUMULATION_SLUG, True, "BTC/USDC"),
        (CATALOG_PREFIX + "old_custom_dip", False, "ETH/USDC"),
    ]:
        await model.StrategyDefinition.create(
            slug=slug,
            name="Accumulation dip",
            is_builtin=builtin,
            active_version=1,
            draft_version=1,
            validation_status="valid",
        )
        version = await model.StrategyVersion.create(
            strategy_slug=slug,
            version=1,
            ir_json=original,
            validation_json=json.dumps({"status": "valid"}),
            explanation="legacy",
        )
        await model.AccumulationActivation.create(
            symbol=symbol,
            account_scope="fixture",
            state="stopped",
            strategy_version_id=version.id,
        )
        retained.append(version)

    page = (await api_client.get("/accumulation/strategies?limit=100")).json()
    assert [row["slug"] for row in page["versions"]] == ["regime_accumulation"]
    for include_hidden in (False, True):
        summaries = await list_strategy_summaries(include_hidden=include_hidden)
        assert not any(row["slug"].startswith(CATALOG_PREFIX) for row in summaries)
    for version in retained:
        assert (
            await load_accumulation_strategy_version(version.id)
        ).parameters.timeframe == "1h"
        assert (await model.StrategyVersion.get(id=version.id)).ir_json == original
        assert await get_strategy_detail(version.strategy_slug) is not None
    assert await model.AccumulationActivation.filter(state="stopped").count() == 2


@pytest.mark.asyncio
async def test_matching_dashboard_clients_share_database_projection(
    status_db, monkeypatch
):
    import asyncio

    from service.accumulation_runtime import AccumulationRuntime

    runtime = AccumulationRuntime(
        SimpleNamespace(
            exchange=SimpleNamespace(), readiness=AsyncMock(), account_scope=AsyncMock()
        )
    )
    monkeypatch.setattr(
        AccumulationRuntime, "current_account_scope", property(lambda _: "account")
    )
    events = runtime.status_events
    monkeypatch.setattr(controller, "_runtime", lambda: runtime)
    snapshot = controller.accumulation_stream_snapshot
    builds = 0

    async def count(*args, **kwargs):
        nonlocal builds
        builds += 1
        return await snapshot(*args, **kwargs)

    monkeypatch.setattr(controller, "accumulation_stream_snapshot", count)
    first = controller.stream_status.fn(symbol=None)
    second = controller.stream_status.fn(symbol=None)
    initial = await asyncio.gather(anext(first), anext(second))
    assert initial[0] == initial[1]
    assert builds == 1
    # A real DB projection changes, while the runtime owns the notification.
    version = await model.StrategyVersion.create(
        strategy_slug="test",
        version=1,
        ir_json="{}",
        validation_json="{}",
        explanation="test",
    )
    await model.AccumulationActivation.create(
        symbol="BTC/USDC", account_scope="account", strategy_version=version
    )
    events.publish()
    updated = await asyncio.gather(anext(first), anext(second))
    assert updated[0] == updated[1] and updated[0] != initial[0]
    assert builds == 2
    # A journal mutation invalidates reads before the worker's next tick.
    await model.AccumulationActivation.filter(symbol="BTC/USDC").update(revision=3)
    runtime.notify("BTC/USDC")
    third = controller.stream_status.fn(symbol=None)
    latest = await anext(third)
    assert latest != updated[0]
    assert builds == 3
    await first.aclose()
    await second.aclose()
    await third.aclose()
    assert not events.connected
    # The next session must read DB state rather than a disconnected cache.
    await model.AccumulationActivation.filter(symbol="BTC/USDC").update(revision=4)
    fourth = controller.stream_status.fn(symbol=None)
    assert await anext(fourth) != latest
    assert builds == 4
    await fourth.aclose()
    events.close()
    late = controller.stream_status.fn(symbol=None)
    with pytest.raises(StopAsyncIteration):
        await anext(late)
    assert builds == 4
