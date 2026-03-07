from typing import Any

import pytest
import service.csv_signal_import as csv_import_module
from service.csv_signal_import import CSVSignalImportService


class _DummyFilter:
    def __init__(self, values: list[Any]):
        self._values = values

    async def values_list(self, *args, **kwargs) -> list[Any]:
        return self._values


class _DummyTradesModel:
    created_bulk: list[Any] = []

    def __init__(self, **kwargs: Any):
        self.__dict__.update(kwargs)

    @classmethod
    def filter(cls, **kwargs):
        return _DummyFilter([])

    @classmethod
    async def bulk_create(cls, rows: list[Any], using_db: Any = None) -> None:
        cls.created_bulk.extend(rows)


class _DummyOpenTradesModel:
    created_rows: list[dict[str, Any]] = []

    @classmethod
    def filter(cls, **kwargs):
        return _DummyFilter([])

    @classmethod
    async def create(cls, using_db: Any = None, **kwargs: Any) -> None:
        cls.created_rows.append(kwargs)


class _DummyTx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_csv_signal_import_creates_base_and_safety_orders(monkeypatch) -> None:
    _DummyTradesModel.created_bulk = []
    _DummyOpenTradesModel.created_rows = []

    monkeypatch.setattr(csv_import_module.model, "Trades", _DummyTradesModel)
    monkeypatch.setattr(csv_import_module.model, "OpenTrades", _DummyOpenTradesModel)
    monkeypatch.setattr(
        csv_import_module,
        "run_sqlite_write_with_retry",
        lambda operation, _name: operation(),
    )
    monkeypatch.setattr(csv_import_module, "in_transaction", lambda: _DummyTx())

    importer = CSVSignalImportService()
    csv_content = (
        "date;symbol;price;amount\n"
        "18/08/2025 19:32:00;BTC/USDC;117644.41;0.00099153\n"
        "24/08/2025 15:04:00;BTC/USDC;112170.19;0.03863000\n"
        "01/09/2025 22:31:00;BTC/USDC;109000;0.00050000\n"
    )

    result = await importer.import_from_csv(
        csv_content=csv_content,
        quote_currency="USDC",
        take_profit=1.0,
    )

    assert result["symbol_count"] == 1
    assert result["row_count"] == 3
    assert result["symbols"] == ["BTC/USDC"]
    assert result["first_timestamp_by_symbol"]["BTC/USDC"] > 0

    assert len(_DummyTradesModel.created_bulk) == 3
    first = _DummyTradesModel.created_bulk[0]
    second = _DummyTradesModel.created_bulk[1]
    third = _DummyTradesModel.created_bulk[2]

    assert first.baseorder is True
    assert first.safetyorder is False
    assert first.order_count == 0
    assert second.baseorder is False
    assert second.safetyorder is True
    assert second.order_count == 1
    assert third.baseorder is False
    assert third.safetyorder is True
    assert third.order_count == 2

    expected_second_delta = round(((112170.19 - 117644.41) / 117644.41) * 100, 2)
    expected_third_delta = round(((109000.0 - 112170.19) / 112170.19) * 100, 2)
    assert float(second.so_percentage) == expected_second_delta
    assert float(third.so_percentage) == expected_third_delta

    assert first.ordersize == pytest.approx(117644.41 * 0.00099153)
    assert second.ordersize == pytest.approx(112170.19 * 0.03863)
    assert third.ordersize == pytest.approx(109000.0 * 0.0005)

    assert len(_DummyOpenTradesModel.created_rows) == 1
    open_trade = _DummyOpenTradesModel.created_rows[0]
    assert open_trade["symbol"] == "BTC/USDC"
    assert open_trade["so_count"] == 2
    assert open_trade["amount"] == pytest.approx(
        0.00099153 + 0.03863 + 0.0005,
        rel=1e-12,
    )
    assert open_trade["cost"] == pytest.approx(
        (117644.41 * 0.00099153) + (112170.19 * 0.03863) + (109000.0 * 0.0005),
        rel=1e-12,
    )


def test_parse_csv_rows_normalizes_symbol_and_date() -> None:
    importer = CSVSignalImportService()
    csv_content = (
        "date;symbol;price;amount\n"
        "18/08/2025 19:32:00;btc-usdc;117644.41;0.00099153\n"
    )
    grouped = importer._parse_csv_rows(csv_content, "USDC")
    assert list(grouped.keys()) == ["BTC/USDC"]
    assert grouped["BTC/USDC"][0]["timestamp"] > 0
