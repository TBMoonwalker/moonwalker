import asyncio
import json
import os

import model
import pytest
import pytest_asyncio
from service.strategy_builder import (
    create_blank_strategy,
    delete_custom_strategy,
    duplicate_strategy,
    get_strategy_detail,
    list_strategy_options,
    promote_strategy_version,
    seed_builtin_strategies,
    validate_strategy_ir,
)
from tortoise import Tortoise


@pytest_asyncio.fixture
async def strategy_db(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), ".."))
    db_path = tmp_path / "strategy_builder.sqlite"
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules={"models": ["model"]})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_builtin_strategies_seed_as_versioned_ir(strategy_db) -> None:
    await seed_builtin_strategies()

    detail = await get_strategy_detail("ema_down")
    assert detail is not None
    assert detail["is_builtin"] is True
    assert detail["active_version"] == 1
    assert detail["ir"]["schema_version"] == 1
    assert detail["validation"]["status"] == "valid"

    options = await list_strategy_options()
    assert "ema_down" in options
    assert "ema_swing_reverse" not in options


@pytest.mark.asyncio
async def test_unchanged_builtin_reseed_does_not_append_version(strategy_db) -> None:
    """Validation timestamps alone must not create immutable versions."""
    await seed_builtin_strategies()
    initial_versions = await model.StrategyVersion.filter(
        strategy_slug="ema_down"
    ).count()
    initial_definition = await model.StrategyDefinition.get(slug="ema_down")
    initial_lock_version = initial_definition.lock_version

    await asyncio.sleep(0)
    await seed_builtin_strategies()

    definition = await model.StrategyDefinition.get(slug="ema_down")
    versions = await model.StrategyVersion.filter(strategy_slug="ema_down").count()
    assert initial_versions == 1
    assert versions == 1
    assert definition.active_version == 1
    assert definition.draft_version == 1
    assert definition.lock_version == initial_lock_version


@pytest.mark.asyncio
async def test_builtin_reseed_appends_version_without_rewriting_history(
    strategy_db,
) -> None:
    """Changed built-in content creates a new immutable active version."""
    await seed_builtin_strategies()
    original = await model.StrategyVersion.get(
        strategy_slug="ema_down",
        version=1,
    )
    original.ir_json = json.dumps({"legacy": "preserve me"})
    await original.save()

    await seed_builtin_strategies()

    definition = await model.StrategyDefinition.get(slug="ema_down")
    historical = await model.StrategyVersion.get(
        strategy_slug="ema_down",
        version=1,
    )
    active = await model.StrategyVersion.get(
        strategy_slug="ema_down",
        version=2,
    )
    assert definition.active_version == 2
    assert json.loads(historical.ir_json) == {"legacy": "preserve me"}
    assert json.loads(active.ir_json)["slug"] == "ema_down"


@pytest.mark.asyncio
async def test_ema20_swing_builtin_is_decomposed_into_executable_graph(
    strategy_db,
) -> None:
    await seed_builtin_strategies()

    detail = await get_strategy_detail("ema20_swing")

    assert detail is not None
    assert detail["validation"]["status"] == "valid"
    assert detail["ir"]["root"] == "decision"
    assert {node["type"] for node in detail["ir"]["nodes"]} >= {
        "indicator",
        "close_price",
        "comparison",
        "fresh_signal_state",
        "all",
    }
    assert len(detail["ir"]["nodes"]) == 7
    decision = next(node for node in detail["ir"]["nodes"] if node["id"] == "decision")
    assert decision["label"] == "All conditions"
    assert all(
        not isinstance(value, (dict, list))
        for node in detail["ir"]["nodes"]
        for value in node.get("params", {}).values()
    )
    assert {
        "source": "ema20_current",
        "target": "ema_trend_compare",
        "target_input": "value1",
    } in detail["ir"]["connections"]
    assert {
        "source": "ema20_previous",
        "target": "ema_trend_compare",
        "target_input": "value2",
    } in detail["ir"]["connections"]
    palette_types = {item["type"] for item in detail["palette"]}
    assert "ema20_swing" not in palette_types
    assert "ema_low_rebound" not in palette_types
    assert "ema_indicator" not in palette_types
    assert "indicator_signal" not in palette_types
    assert "indicator" in palette_types
    assert "swing_low_state" in palette_types


@pytest.mark.asyncio
async def test_ema_swing_builtin_is_decomposed_into_executable_graph(
    strategy_db,
) -> None:
    await seed_builtin_strategies()

    detail = await get_strategy_detail("ema_swing")

    assert detail is not None
    assert detail["validation"]["status"] == "valid"
    assert detail["ir"]["root"] == "decision"
    assert {node["type"] for node in detail["ir"]["nodes"]} >= {
        "indicator",
        "close_price",
        "comparison",
        "swing_low_state",
        "all",
    }
    assert "ema_swing" not in {node["type"] for node in detail["ir"]["nodes"]}
    assert len(detail["ir"]["nodes"]) == 14
    assert {
        "source": "close_previous",
        "target": "higher_swing_low",
    } in detail[
        "ir"
    ]["connections"]
    assert {
        "source": "close_two_back",
        "target": "higher_swing_low",
    } in detail[
        "ir"
    ]["connections"]
    palette_item = next(
        item for item in detail["palette"] if item["type"] == "swing_low_state"
    )
    assert (
        palette_item["documentation_url"]
        == "/docs/strategies.md#higher-swing-low-state"
    )


@pytest.mark.asyncio
async def test_other_builtins_are_decomposed_into_graph_nodes(strategy_db) -> None:
    await seed_builtin_strategies()

    expected_types = {
        "ema_down": {"indicator", "comparison"},
        "ema_low": {"indicator", "close_price", "comparison", "all"},
        "ema_swing": {
            "indicator",
            "close_price",
            "comparison",
            "swing_low_state",
            "all",
        },
    }
    for slug, node_types in expected_types.items():
        detail = await get_strategy_detail(slug)

        assert detail is not None
        assert detail["validation"]["status"] == "valid"
        assert len(detail["ir"]["nodes"]) > 1
        assert {node["type"] for node in detail["ir"]["nodes"]} >= node_types
        assert "ema20_swing" not in {node["type"] for node in detail["ir"]["nodes"]}
        assert "ema_low_rebound" not in {node["type"] for node in detail["ir"]["nodes"]}
        assert "ema_indicator" not in {node["type"] for node in detail["ir"]["nodes"]}
        assert "indicator_signal" not in {
            node["type"] for node in detail["ir"]["nodes"]
        }


@pytest.mark.asyncio
async def test_bollinger_buy_seeds_as_executable_indicator_graph(
    strategy_db,
) -> None:
    await seed_builtin_strategies()

    buy = await get_strategy_detail("bollinger_buy")
    options = await list_strategy_options()

    assert buy is not None
    assert buy["validation"]["status"] == "valid"
    assert "bollinger_buy" in options
    assert "bollinger_sell" not in options
    assert await get_strategy_detail("bollinger_sell") is None

    buy_indicators = {
        node["params"]["indicator"]
        for node in buy["ir"]["nodes"]
        if node["type"] == "indicator"
    }
    assert buy_indicators >= {
        "bollinger_lower",
        "bollinger_middle",
        "bollinger_bandwidth",
        "ema",
        "rsi",
    }
    assert {
        node["params"]["length"]
        for node in buy["ir"]["nodes"]
        if node["type"] == "indicator" and node["params"]["indicator"] == "ema"
    } == {50, 100}
    assert {node["type"] for node in buy["ir"]["nodes"]} >= {"indicator", "low_price"}
    assert "close_price" not in {node["type"] for node in buy["ir"]["nodes"]}
    assert any(
        node["id"] == "trend_cross" and node["type"] == "any"
        for node in buy["ir"]["nodes"]
    )


@pytest.mark.asyncio
async def test_blank_custom_strategy_starts_empty_and_invalid(strategy_db) -> None:
    detail = await create_blank_strategy("Operator blank")

    assert detail["is_builtin"] is False
    assert detail["ir"]["nodes"] == []
    assert detail["ir"]["root"] == ""
    assert detail["validation"]["status"] == "invalid"
    assert detail["available"] is False


@pytest.mark.asyncio
async def test_seed_removes_retired_builtin_strategy_rows(strategy_db) -> None:
    definition = await model.StrategyDefinition.create(
        slug="retired_builtin",
        name="Retired built-in",
        description="",
        is_builtin=True,
        active_version=1,
        draft_version=1,
        validation_status="valid",
    )
    await model.StrategyVersion.create(
        strategy_slug=definition.slug,
        version=1,
        ir_json=json.dumps(
            {
                "schema_version": 1,
                "slug": definition.slug,
                "name": definition.name,
                "kind": "builtin",
                "root": "decision",
                "nodes": [
                    {
                        "id": "decision",
                        "type": "indicator_compare",
                        "params": {
                            "indicator": "unknown",
                            "operator": "equals",
                            "value": "up",
                        },
                    }
                ],
                "connections": [],
            }
        ),
        validation_json=json.dumps({"status": "valid"}),
        explanation="legacy",
    )

    await seed_builtin_strategies()

    assert await model.StrategyDefinition.get_or_none(slug=definition.slug) is None
    assert (
        await model.StrategyVersion.filter(strategy_slug=definition.slug).count()
    ) == 0


@pytest.mark.asyncio
async def test_seed_preserves_configured_retired_builtin_strategy(strategy_db) -> None:
    definition = await model.StrategyDefinition.create(
        slug="retired_configured_builtin",
        name="Retired configured built-in",
        description="",
        is_builtin=True,
        active_version=1,
        draft_version=1,
        validation_status="valid",
    )
    await model.StrategyVersion.create(
        strategy_slug=definition.slug,
        version=1,
        ir_json=json.dumps({"slug": definition.slug}),
        validation_json=json.dumps({"status": "valid"}),
        explanation="legacy",
    )
    await model.AppConfig.create(
        key="dca_strategy",
        value=definition.slug,
        value_type="str",
    )

    await seed_builtin_strategies()

    assert await model.StrategyDefinition.get_or_none(slug=definition.slug) is not None
    assert (
        await model.StrategyVersion.filter(strategy_slug=definition.slug).count() == 1
    )


@pytest.mark.asyncio
async def test_seed_leaves_legacy_custom_graphs_unmigrated(strategy_db) -> None:
    definition = await model.StrategyDefinition.create(
        slug="custom_legacy_graph",
        name="Legacy graph",
        description="",
        is_builtin=False,
        active_version=1,
        draft_version=1,
        validation_status="valid",
    )
    await model.StrategyVersion.create(
        strategy_slug=definition.slug,
        version=1,
        ir_json=json.dumps(
            {
                "schema_version": 1,
                "slug": definition.slug,
                "name": definition.name,
                "description": "",
                "kind": "custom",
                "root": "decision",
                "nodes": [
                    {
                        "id": "decision",
                        "type": "indicator_compare",
                        "label": "Legacy condition",
                        "params": {
                            "indicator": "legacy_signal",
                            "operator": "equals",
                            "value": "up",
                        },
                    },
                ],
                "connections": [],
                "metadata": {"source": "strategy_builder_blank"},
            }
        ),
        validation_json=json.dumps({"status": "valid"}),
        explanation="legacy",
    )

    await seed_builtin_strategies()
    detail = await get_strategy_detail(definition.slug)

    assert detail is not None
    assert detail["active_version"] == 1
    assert detail["ir"]["nodes"][0]["type"] == "indicator_compare"
    assert (
        await model.StrategyVersion.filter(strategy_slug=definition.slug).count() == 1
    )


@pytest.mark.asyncio
async def test_duplicate_then_promote_custom_strategy_uses_optimistic_lock(
    strategy_db,
) -> None:
    await seed_builtin_strategies()
    duplicate = await duplicate_strategy("ema_down", "Operator EMA copy")

    assert duplicate["is_builtin"] is False
    assert duplicate["duplicated_from"] == "ema_down"

    draft = duplicate["ir"]
    draft["name"] = "Operator EMA copy tuned"
    promoted, status_code = await promote_strategy_version(
        duplicate["slug"],
        draft,
        duplicate["lock_version"],
    )
    assert status_code == 200
    assert promoted["active_version"] == 2
    assert promoted["lock_version"] == duplicate["lock_version"] + 1

    stale_payload, stale_status = await promote_strategy_version(
        duplicate["slug"],
        draft,
        duplicate["lock_version"],
    )
    assert stale_status == 409
    assert stale_payload["active_version"] == 2


@pytest.mark.asyncio
async def test_concurrent_strategy_promotions_commit_one_version(strategy_db) -> None:
    """Concurrent clients with one lock version must produce one promotion."""
    await seed_builtin_strategies()
    duplicate = await duplicate_strategy("ema_down", "Concurrent copy")
    draft = duplicate["ir"]
    draft["name"] = "Concurrent copy tuned"

    results = await asyncio.gather(
        promote_strategy_version(
            duplicate["slug"],
            draft,
            duplicate["lock_version"],
        ),
        promote_strategy_version(
            duplicate["slug"],
            draft,
            duplicate["lock_version"],
        ),
    )

    assert sorted(status for _payload, status in results) == [200, 409]
    assert (
        await model.StrategyVersion.filter(strategy_slug=duplicate["slug"]).count() == 2
    )


@pytest.mark.asyncio
async def test_strategy_promotion_rolls_back_version_when_pointer_save_fails(
    strategy_db,
    monkeypatch,
) -> None:
    """A failed active-pointer update must not leave an orphan version."""
    await seed_builtin_strategies()
    duplicate = await duplicate_strategy("ema_down", "Rollback copy")
    draft = duplicate["ir"]
    draft["name"] = "Rollback copy tuned"
    original_save = model.StrategyDefinition.save

    async def fail_promoted_definition_save(self, *args, **kwargs):
        if self.slug == duplicate["slug"] and self.lock_version > 1:
            raise RuntimeError("pointer write failed")
        return await original_save(self, *args, **kwargs)

    monkeypatch.setattr(
        model.StrategyDefinition,
        "save",
        fail_promoted_definition_save,
    )

    with pytest.raises(RuntimeError, match="pointer write failed"):
        await promote_strategy_version(
            duplicate["slug"],
            draft,
            duplicate["lock_version"],
        )

    persisted = await get_strategy_detail(duplicate["slug"])
    assert persisted is not None
    assert persisted["active_version"] == 1
    assert persisted["lock_version"] == duplicate["lock_version"]
    assert (
        await model.StrategyVersion.filter(strategy_slug=duplicate["slug"]).count() == 1
    )


@pytest.mark.asyncio
async def test_delete_custom_strategy_removes_definition_versions_and_state(
    strategy_db,
) -> None:
    detail = await create_blank_strategy("Delete me")
    await model.StrategyGraphState.create(
        strategy_slug=detail["slug"],
        state_key="state",
        symbol="BTC/USDT",
        timeframe="1m",
        value_json="1",
    )

    await delete_custom_strategy(detail["slug"])

    assert await get_strategy_detail(detail["slug"]) is None
    assert (
        await model.StrategyVersion.filter(strategy_slug=detail["slug"]).count()
    ) == 0
    assert (
        await model.StrategyGraphState.filter(strategy_slug=detail["slug"]).count()
    ) == 0


@pytest.mark.asyncio
async def test_delete_builtin_strategy_is_rejected(strategy_db) -> None:
    await seed_builtin_strategies()

    with pytest.raises(PermissionError):
        await delete_custom_strategy("ema20_swing")


@pytest.mark.asyncio
async def test_delete_configured_custom_strategy_is_rejected(strategy_db) -> None:
    detail = await create_blank_strategy("Configured strategy")
    await model.AppConfig.create(
        key="dca_strategy",
        value=detail["slug"],
        value_type="str",
    )

    with pytest.raises(PermissionError, match="configured by dca_strategy"):
        await delete_custom_strategy(detail["slug"])


@pytest.mark.asyncio
async def test_delete_historically_referenced_strategy_is_rejected(
    strategy_db,
) -> None:
    detail = await create_blank_strategy("Historical strategy")
    await model.TradeExecutions.create(
        deal_id="11111111-1111-4111-8111-111111111111",
        symbol="BTC/USDC",
        side="buy",
        role="base_order",
        timestamp="1700000000000",
        price=100.0,
        amount=1.0,
        strategy_name=detail["slug"],
        strategy_slug=detail["slug"],
        strategy_version=1,
    )

    with pytest.raises(PermissionError, match="referenced by trade history"):
        await delete_custom_strategy(detail["slug"])


@pytest.mark.asyncio
async def test_runtime_loads_exact_historical_strategy_version(strategy_db) -> None:
    from service.strategy_runtime import (
        _load_strategy_snapshot,
        invalidate_strategy_runtime_cache,
    )

    await seed_builtin_strategies()
    version_one = await model.StrategyVersion.get(
        strategy_slug="ema_down",
        version=1,
    )
    historical_ir = json.loads(version_one.ir_json)
    historical_ir["name"] = "Historical EMA Down"
    version_one.ir_json = json.dumps(historical_ir)
    await version_one.save()
    await seed_builtin_strategies()
    invalidate_strategy_runtime_cache("ema_down")

    snapshot = await _load_strategy_snapshot("ema_down", version=1)

    assert snapshot.version == 1
    assert snapshot.ir["name"] == "Historical EMA Down"


def test_validation_groups_blocking_errors_for_invalid_graph() -> None:
    validation = validate_strategy_ir(
        {
            "schema_version": 1,
            "root": "missing",
            "nodes": [{"id": "decision", "type": "not_supported"}],
        }
    )

    assert validation["status"] == "invalid"
    assert any(error["group"] == "Graph" for error in validation["blocking_errors"])


def test_validation_rejects_data_only_decision_nodes() -> None:
    validation = validate_strategy_ir(
        {
            "schema_version": 1,
            "root": "ema20",
            "nodes": [
                {
                    "id": "ema20",
                    "type": "indicator",
                    "params": {"indicator": "ema", "length": 20},
                }
            ],
            "connections": [],
        }
    )

    assert validation["status"] == "invalid"
    assert any(
        "decision node must be logic" in error["message"]
        for error in validation["blocking_errors"]
    )


def test_validation_requires_explicit_comparison_value_ports() -> None:
    validation = validate_strategy_ir(
        {
            "schema_version": 1,
            "root": "decision",
            "nodes": [
                {
                    "id": "value_source_1",
                    "type": "indicator",
                    "params": {"indicator": "ema", "length": 20},
                },
                {
                    "id": "value_source_2",
                    "type": "close_price",
                    "params": {"lookback": 50},
                },
                {
                    "id": "decision",
                    "type": "comparison",
                    "params": {"comparison": "greater_than"},
                },
            ],
            "connections": [
                {"source": "value_source_1", "target": "decision"},
                {"source": "value_source_2", "target": "decision"},
            ],
        }
    )

    assert validation["status"] == "invalid"
    assert any(
        "explicit value1 and value2" in error["message"]
        for error in validation["blocking_errors"]
    )
