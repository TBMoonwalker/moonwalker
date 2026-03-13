"""Pure helpers for watcher symbol and OHLCV state handling."""

from typing import Any


def get_mandatory_symbols(config: dict[str, Any]) -> set[str]:
    """Return symbols that must always be watched regardless of plugin queues."""
    if not config.get("btc_pulse", False):
        return set()
    currency = str(config.get("currency", "USDC")).upper().strip()
    if not currency:
        return set()
    return {f"BTC/{currency}"}


def normalize_symbols(symbols: list[Any] | None) -> list[str]:
    """Flatten nested symbol lists and return unique trading pairs."""
    if not symbols:
        return []

    flat: list[str] = []
    for symbol in symbols:
        if isinstance(symbol, list):
            flat.extend(entry for entry in symbol if isinstance(entry, str))
        elif isinstance(symbol, str):
            flat.append(symbol)

    valid = [symbol for symbol in flat if "/" in symbol]
    return list(dict.fromkeys(valid))


def compose_ticker_symbols(
    utils: Any,
    *,
    base_symbols: list[str],
    signal_symbols: set[str],
    mandatory_symbols: set[str],
    exchange_watcher_ohlcv: bool,
    timeframe: str,
) -> list[Any]:
    """Merge trades, signal symbols, and mandatory symbols into watch targets."""
    merged_symbols = list(
        dict.fromkeys(base_symbols + sorted(signal_symbols) + sorted(mandatory_symbols))
    )
    if exchange_watcher_ohlcv:
        return utils.convert_symbols(merged_symbols, timeframe)
    return merged_symbols


def merge_candle(last: list[Any], current: list[Any]) -> list[float]:
    """Merge two candles for the same timestamp into one OHLCV candle."""
    timestamp = float(last[0])
    open_price = float(last[1])
    high_price = max(float(last[2]), float(current[2]))
    low_price = min(float(last[3]), float(current[3]))
    close_price = float(current[4])

    last_volume = float(last[5])
    current_volume = float(current[5])
    volume = (
        current_volume
        if current_volume >= last_volume
        else last_volume + current_volume
    )

    return [timestamp, open_price, high_price, low_price, close_price, volume]


def prepare_ohlcv_write(
    candle_store: dict[str, list[Any]],
    symbol: str,
    ticker: Any,
) -> dict[str, Any] | None:
    """Prepare a closed candle payload while keeping the latest live candle in memory."""
    current_candle = ticker[-1]
    timestamp = current_candle[0]

    last = candle_store.get(symbol)
    if not last or last[0] < timestamp:
        if last:
            t, open_price, high_price, low_price, close_price, volume = last[:6]
            payload = {
                "timestamp": t,
                "symbol": symbol,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            }
        else:
            payload = None
        candle_store[symbol] = current_candle
        return payload

    if last[0] == timestamp:
        candle_store[symbol] = merge_candle(last, current_candle)
    return None
