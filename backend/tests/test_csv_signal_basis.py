"""CSV acquisition basis survives real aggregation and live DCA valuation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import model
import pytest
import pytest_asyncio
from helper.utils import Utils
from service.autopilot import ResolvedTradingPolicy
from service.backup_restore import BackupService
from service.config import Config
from service.csv_signal_import import CSVSignalImportService
from service.database import Database
from service.dca import Dca
from service.dca.math import calculate_average_entry_price
from service.dca.recovery_sizing import (
    RECOVERY_TARGET_MODE,
    RecoverySizingPolicy,
    calculate_projected_average_price,
    calculate_recovery_sizing,
)
from service.trades import Trades
from tortoise import Tortoise

HEADER = "date;symbol;price;amount;fee;fee_currency;amount_type;fee_quote_value\n"


@pytest_asyncio.fixture
async def basis_db(tmp_path):
    await Tortoise.init(
        db_url=f"sqlite://{tmp_path / 'basis.sqlite'}", modules={"models": ["model"]}
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


def policy():
    return ResolvedTradingPolicy(
        symbol="BTC/USDC",
        mode="low",
        effective_max_bots=2,
        take_profit=1,
        baseline_take_profit=1,
        stop_loss=5,
        stop_loss_timeout=0,
        adaptive_tp_applied=False,
        adaptive_reason_code=None,
        adaptive_trust_direction=None,
        adaptive_trust_score=None,
        adaptive_entry_size_applied=False,
        adaptive_entry_reason_code=None,
        memory_status="fresh",
        baseline_base_order=50,
        entry_order_size=50,
        suggested_base_order=50,
    )


async def assert_live_basis(monkeypatch, expected_cost, expected_amount):
    aggregate = await Trades().get_trades_for_orders_fresh("BTC/USDC")
    dca = Dca()
    dca.config = {"trailing_tp": 0, "mstc": 0, "tp_spike_confirm_enabled": False}
    statistic = AsyncMock()
    monkeypatch.setattr(dca.statistic, "update_statistic_data", statistic)
    average = expected_cost / expected_amount
    await dca._Dca__calculate_tp(average, aggregate, policy())
    result = statistic.await_args.args[0]
    assert result["avg_price"] == pytest.approx(average)
    assert result["tp_price"] == pytest.approx(average * 1.01)
    assert Utils().calculate_actual_pnl(aggregate, average) == pytest.approx(0)
    return aggregate


# Value: protects=CSV paid acquisition fees counted once by actual DCA evaluation;
# fails_when=fee-inclusive rows receive another legacy fee surcharge;
# why_new=parser tests omit aggregation and live TP/PNL consumers; seam=none;
# no_claim=exchange execution (only statistics output is mocked).
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row,cost,quantity",
    [
        ("1;1;USDC;net;", 101, 1),
        ("1;1;USDC;gross;1", 101, 1),
        ("0.99;0.01;BTC;net;", 100, 0.99),
        ("1;0.01;BTC;gross;", 100, 0.99),
        ("1;0.02;BNB;net;2", 102, 1),
        ("1;0;;net;", 100, 1),
    ],
)
async def test_declared_csv_basis_reaches_live_dca_once(
    basis_db, monkeypatch, row, cost, quantity
):
    await CSVSignalImportService().import_from_csv(
        HEADER + "2026-01-01;BTC/USDC;100;" + row, "USDC", 1
    )
    await assert_live_basis(monkeypatch, cost, quantity)


# Value: protects=paid CSV fees stay isolated from later legacy fee estimates;
# fails_when=a later native/manual buy reapplies its proxy to imported cost;
# why_new=single CSV rows cannot prove mixed-order accounting; seam=none;
# no_claim=provider acceptance or a change to legacy-only valuation policy.
@pytest.mark.asyncio
@pytest.mark.parametrize("native_fee", [0, 0.01])
async def test_csv_then_native_or_manual_buy_preserves_each_basis(
    basis_db, monkeypatch, native_fee
):
    await CSVSignalImportService().import_from_csv(
        HEADER + "2026-01-01;BTC/USDC;100;1;1;USDC;net;", "USDC", 1
    )
    row = (await model.Trades.all().values())[0]
    row.pop("id")
    row.update(
        timestamp="1800000000000",
        ordersize=80,
        amount=1,
        amount_fee=0,
        price=80,
        fee=native_fee,
        orderid="native-order",
        bot="asap",
        baseorder=False,
        safetyorder=True,
        order_count=1,
    )
    # The legacy row intentionally has no provenance field.
    row.pop("cost_includes_fees", None)
    await model.Trades.create(**row)
    aggregate = await assert_live_basis(monkeypatch, 101 + 80 * (1 + native_fee), 2)
    assert aggregate["fee"] == native_fee
    assert aggregate["total_cost"] == 181


# Value: protects=remaining holdings do not retain the full original CSV basis;
# fails_when=unsellable remainder is valued using all original purchase costs;
# why_new=full-position CSV tests omit partial-close summaries; seam=none;
# no_claim=exchange minimum checks or sale settlement.
@pytest.mark.asyncio
async def test_csv_remainder_scales_effective_basis(basis_db, monkeypatch):
    await CSVSignalImportService().import_from_csv(
        HEADER + "2026-01-01;BTC/USDC;100;1;1;USDC;net;", "USDC", 1
    )
    await model.OpenTrades.all().update(
        amount=0.5, cost=50.5, unsellable_amount=0.5, unsellable_reason="minimum"
    )
    await assert_live_basis(monkeypatch, 50.5, 0.5)


# Value: protects=old backups recover bounded CSV provenance, explicit flags win;
# fails_when=restore loses provenance or ID heuristics override an explicit False;
# why_new=current import tests omit old backup and native-row compatibility;
# seam=none; no_claim=history downloads or configuration cache refresh.
@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, True, False])
async def test_backup_restore_preserves_csv_cost_provenance(
    basis_db, monkeypatch, flag
):
    await CSVSignalImportService().import_from_csv(
        HEADER + "2026-01-01;BTC/USDC;100;1;1;USDC;net;", "USDC", 1
    )
    backup = BackupService()
    payload = await backup.export_backup(include_trade_data=True)
    row = payload["trade_data"]["trades"][0]
    assert row["cost_includes_fees"] is True
    if flag is None:
        row.pop("cost_includes_fees")
    else:
        row["cost_includes_fees"] = flag
    config = SimpleNamespace(reload=AsyncMock(), snapshot=lambda: {})
    monkeypatch.setattr(Config, "instance", AsyncMock(return_value=config))
    monkeypatch.setattr(
        backup, "_refresh_required_history", AsyncMock(return_value=([], []))
    )
    await backup.restore_backup(payload, restore_trade_data=True)
    restored = await model.Trades.get()
    assert restored.cost_includes_fees is flag
    aggregate = await Trades().get_trades_for_orders_fresh("BTC/USDC")
    assert aggregate["entry_cost"] == (None if flag is False else 101)
    if flag is not False:
        await assert_live_basis(monkeypatch, 101, 1)


# Value: protects=unmarked native buys retain the established legacy calculator;
# fails_when=CSV compatibility inference captures an exchange or manual row;
# why_new=CSV-positive cases cannot prove native behavior unchanged; seam=none;
# no_claim=a redesign of the legacy fee estimate or realized-return accounting.
@pytest.mark.asyncio
async def test_native_only_fee_estimate_is_unchanged(basis_db):
    await CSVSignalImportService().import_from_csv(
        HEADER + "2026-01-01;BTC/USDC;100;1;1;USDC;net;", "USDC", 1
    )
    await model.Trades.all().update(bot="asap", ordersize=100, cost_includes_fees=None)
    aggregate = await Trades().get_trades_for_orders_fresh("BTC/USDC")
    assert aggregate["entry_cost"] is None
    assert (
        calculate_average_entry_price(
            aggregate["total_cost"],
            aggregate["fee"],
            aggregate["total_amount"],
            entry_cost=aggregate["entry_cost"],
        )
        == 101
    )


# Value: protects=additive upgrade preserves old CSV quantities and stored costs;
# fails_when=an older trade table cannot be read or its financial values change;
# why_new=fresh ORM schemas do not exercise missing-column upgrades; seam=none;
# no_claim=non-SQLite schema migration support.
@pytest.mark.asyncio
async def test_cost_provenance_upgrade_is_additive_and_repeatable(basis_db):
    await CSVSignalImportService().import_from_csv(
        HEADER + "2026-01-01;BTC/USDC;100;1;1;USDC;net;", "USDC", 1
    )
    connection = Tortoise.get_connection("default")
    await connection.execute_script("ALTER TABLE trades DROP COLUMN cost_includes_fees")
    database = Database()
    database.db_url = "sqlite://:memory:"
    await database._ensure_trade_cost_provenance()
    await database._ensure_trade_cost_provenance()
    row = await model.Trades.get()
    assert row.cost_includes_fees is None
    assert row.ordersize == 101 and row.amount == 1 and row.fee == 0.01
    assert (await Trades().get_trades_for_orders_fresh("BTC/USDC"))["entry_cost"] == 101


# Value: protects=existing paid fees stay separate from future recovery-buy fees;
# fails_when=projection and sizing surcharge existing CSV cost a second time;
# why_new=live TP tests omit hypothetical recovery order math; seam=none;
# no_claim=exchange precision, available balance or actual fill execution.
def test_recovery_sizing_uses_effective_existing_cost_and_future_fee():
    policy = RecoverySizingPolicy(mode=RECOVERY_TARGET_MODE, maximum_deal_quote=250)
    result = calculate_recovery_sizing(
        total_cost=101,
        total_amount=1,
        fill_price=80,
        take_profit_percent=1,
        fee_ratio=0.01,
        atr_percent=1,
        policy=policy,
        entry_cost=101,
    )
    assert result.current_tp_price == pytest.approx(102.01)
    assert result.projected_tp_price == pytest.approx(89.6)
    assert result.should_place and not result.capped
    assert result.remaining_deal_quote == 149
    assert calculate_projected_average_price(
        101, 1, 80, 40, 0.01, entry_cost=101
    ) == pytest.approx(141.4 / 1.5)
