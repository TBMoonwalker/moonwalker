import helper
import service.watcher_runtime as watcher_runtime


def test_normalize_symbols_flattens_and_deduplicates() -> None:
    result = watcher_runtime.normalize_symbols(
        ["BTC/USDC", ["ETH/USDC", "BTC/USDC"], "invalid", 1, "SOL/USDC"]
    )

    assert result == ["BTC/USDC", "ETH/USDC", "SOL/USDC"]


def test_get_mandatory_symbols_uses_currency_only_when_enabled() -> None:
    assert watcher_runtime.get_mandatory_symbols({"btc_pulse": False}) == set()
    assert watcher_runtime.get_mandatory_symbols(
        {"btc_pulse": True, "currency": "usdt"}
    ) == {"BTC/USDT"}


def test_compose_ticker_symbols_merges_sources_and_converts_when_ohlcv() -> None:
    utils = helper.Utils()

    result = watcher_runtime.compose_ticker_symbols(
        utils,
        base_symbols=["ETH/USDC"],
        signal_symbols={"BTC/USDC"},
        mandatory_symbols={"BTC/USDC", "SOL/USDC"},
        exchange_watcher_ohlcv=True,
        timeframe="1m",
    )

    assert result == [
        ["ETH/USDC", "1m"],
        ["BTC/USDC", "1m"],
        ["SOL/USDC", "1m"],
    ]


def test_prepare_ohlcv_write_rolls_closed_candle_forward() -> None:
    candles: dict[str, list[float]] = {}
    symbol = "BTC/USDC"

    assert (
        watcher_runtime.prepare_ohlcv_write(
            candles, symbol, [[1_000, 10, 10, 10, 10, 1]]
        )
        is None
    )
    assert (
        watcher_runtime.prepare_ohlcv_write(
            candles, symbol, [[1_000, 10, 12, 9, 11, 0.5]]
        )
        is None
    )

    payload = watcher_runtime.prepare_ohlcv_write(
        candles, symbol, [[2_000, 11, 13, 10, 12, 2]]
    )

    assert payload == {
        "timestamp": 1000.0,
        "symbol": symbol,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 1.5,
    }
    assert candles[symbol] == [2_000, 11, 13, 10, 12, 2]
