from service.watcher import Watcher


def test_prepare_ohlcv_write_merges_same_timestamp() -> None:
    watcher = Watcher()
    symbol = "BTC/USDC"
    Watcher.candles = {}

    first = [1_000, 10.0, 10.0, 10.0, 10.0, 1.0]
    assert watcher._Watcher__prepare_ohlcv_write(symbol, [first]) is None

    second = [1_000, 11.0, 12.0, 9.0, 11.0, 0.5]
    assert watcher._Watcher__prepare_ohlcv_write(symbol, [second]) is None

    assert Watcher.candles[symbol] == [1000.0, 10.0, 12.0, 9.0, 11.0, 1.5]


def test_prepare_ohlcv_write_returns_merged_payload_on_rollover() -> None:
    watcher = Watcher()
    symbol = "BTC/USDC"
    Watcher.candles = {}

    first = [1_000, 10.0, 10.0, 10.0, 10.0, 1.0]
    second = [1_000, 11.0, 12.0, 9.0, 11.0, 0.5]
    next_candle = [2_000, 11.0, 13.0, 10.0, 12.0, 2.0]

    watcher._Watcher__prepare_ohlcv_write(symbol, [first])
    watcher._Watcher__prepare_ohlcv_write(symbol, [second])
    payload = watcher._Watcher__prepare_ohlcv_write(symbol, [next_candle])

    assert payload == {
        "timestamp": 1000.0,
        "symbol": symbol,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 1.5,
    }
    assert Watcher.candles[symbol] == next_candle
