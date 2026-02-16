import pytest
from service.dca import Dca


@pytest.mark.asyncio
async def test_dynamic_dca_skips_so_when_pnl_is_above_last_so_percentage(monkeypatch):
    dca = Dca()
    buy_calls = []

    async def fake_dynamic_strategy(_symbol):
        return True

    async def fake_resolve_size(**_kwargs):
        return 100.0, {"scale": 1.0, "window": "off"}

    async def fake_receive_buy_order(order, _config):
        buy_calls.append(order)
        return True

    async def fake_update_statistic_data(_payload):
        return None

    monkeypatch.setattr(
        dca,
        "_Dca__dynamic_dca_strategy",
        fake_dynamic_strategy,
    )
    monkeypatch.setattr(
        dca,
        "_Dca__resolve_safety_order_size",
        fake_resolve_size,
    )
    monkeypatch.setattr(dca.orders, "receive_buy_order", fake_receive_buy_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(
        dca.utils,
        "calculate_actual_pnl",
        lambda _trades, _current_price: -2.5,
    )

    dca.config = {
        "dynamic_dca": True,
        "os": 1.0,
        "ss": 0.5,
        "mstc": 5,
        "sos": 1.0,
        "so": 100.0,
    }

    trades = {
        "symbol": "TEST/USDT",
        "direction": "long",
        "bot": "asap_TEST/USDT",
        "ordertype": "market",
        "bo_price": 100.0,
        "safetyorders_count": 1,
        "safetyorders": [
            {"price": 97.0, "so_percentage": -3.0, "ordersize": 50.0},
        ],
    }

    await dca._Dca__calculate_dca(97.5, trades)

    assert buy_calls == []


@pytest.mark.asyncio
async def test_dynamic_dca_allows_so_when_pnl_is_deeper_than_last_so_percentage(
    monkeypatch,
):
    dca = Dca()
    buy_calls = []

    async def fake_dynamic_strategy(_symbol):
        return True

    async def fake_resolve_size(**_kwargs):
        return 100.0, {"scale": 1.0, "window": "off"}

    async def fake_receive_buy_order(order, _config):
        buy_calls.append(order)
        return True

    async def fake_update_statistic_data(_payload):
        return None

    monkeypatch.setattr(
        dca,
        "_Dca__dynamic_dca_strategy",
        fake_dynamic_strategy,
    )
    monkeypatch.setattr(
        dca,
        "_Dca__resolve_safety_order_size",
        fake_resolve_size,
    )
    monkeypatch.setattr(dca.orders, "receive_buy_order", fake_receive_buy_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(
        dca.utils,
        "calculate_actual_pnl",
        lambda _trades, _current_price: -3.6,
    )

    dca.config = {
        "dynamic_dca": True,
        "os": 1.0,
        "ss": 0.5,
        "mstc": 5,
        "sos": 1.0,
        "so": 100.0,
    }

    trades = {
        "symbol": "TEST/USDT",
        "direction": "long",
        "bot": "asap_TEST/USDT",
        "ordertype": "market",
        "bo_price": 100.0,
        "safetyorders_count": 1,
        "safetyorders": [
            {"price": 97.0, "so_percentage": -3.0, "ordersize": 50.0},
        ],
    }

    await dca._Dca__calculate_dca(96.4, trades)

    assert len(buy_calls) == 1
    assert buy_calls[0]["so_percentage"] == -3.6


@pytest.mark.asyncio
async def test_dynamic_dca_skips_so_when_normalized_pnl_matches_last_so_percentage(
    monkeypatch,
):
    dca = Dca()
    buy_calls = []

    async def fake_dynamic_strategy(_symbol):
        return True

    async def fake_resolve_size(**_kwargs):
        return 100.0, {"scale": 1.0, "window": "off"}

    async def fake_receive_buy_order(order, _config):
        buy_calls.append(order)
        return True

    async def fake_update_statistic_data(_payload):
        return None

    monkeypatch.setattr(
        dca,
        "_Dca__dynamic_dca_strategy",
        fake_dynamic_strategy,
    )
    monkeypatch.setattr(
        dca,
        "_Dca__resolve_safety_order_size",
        fake_resolve_size,
    )
    monkeypatch.setattr(dca.orders, "receive_buy_order", fake_receive_buy_order)
    monkeypatch.setattr(
        dca.statistic, "update_statistic_data", fake_update_statistic_data
    )
    monkeypatch.setattr(
        dca.utils,
        "calculate_actual_pnl",
        lambda _trades, _current_price: -2.01,
    )

    dca.config = {
        "dynamic_dca": True,
        "os": 1.0,
        "ss": 0.5,
        "mstc": 5,
        "sos": 1.0,
        "so": 100.0,
    }

    trades = {
        "symbol": "TEST/USDT",
        "direction": "long",
        "bot": "asap_TEST/USDT",
        "ordertype": "market",
        "bo_price": 100.0,
        "safetyorders_count": 1,
        "safetyorders": [
            {"price": 97.0, "so_percentage": -2.0, "ordersize": 50.0},
        ],
    }

    await dca._Dca__calculate_dca(97.99, trades)

    assert buy_calls == []
