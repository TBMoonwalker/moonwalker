import json

import pandas as pd
import pytest
import service.data as data_module
from service.data import Data
from service.data_ohlcv import (
    build_live_candle_payload,
    resample_ohlcv_data,
    serialize_ohlcv_dataframe,
)


@pytest.mark.parametrize(
    "timestamp_dtype",
    ["datetime64[ns, UTC]", "datetime64[ms, UTC]", "datetime64[s, UTC]"],
)
def test_serialize_ohlcv_dataframe_uses_epoch_seconds_for_all_resolutions(
    timestamp_dtype: str,
) -> None:
    base_timestamps = pd.to_datetime(
        [1_700_000_000_000, 1_700_000_060_000], unit="ms", utc=True
    ).astype(timestamp_dtype)

    frame = pd.DataFrame(
        {
            "timestamp": base_timestamps,
            "open": [1.0, 2.0],
            "high": [1.2, 2.2],
            "low": [0.8, 1.8],
            "close": [1.1, 2.1],
            "volume": [10.0, 20.0],
        }
    )

    payload = serialize_ohlcv_dataframe(frame, offset=0)
    records = json.loads(payload)

    assert [record["time"] for record in records] == [
        pytest.approx(1_700_000_000.0),
        pytest.approx(1_700_000_060.0),
    ]


def test_serialize_ohlcv_dataframe_applies_offset_in_minutes() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([1_700_000_000_000], unit="ms", utc=True),
            "open": [1.0],
            "high": [1.2],
            "low": [0.8],
            "close": [1.1],
            "volume": [10.0],
        }
    )

    payload = serialize_ohlcv_dataframe(frame, offset=60)
    records = json.loads(payload)

    assert records[0]["time"] == pytest.approx(1_700_003_600.0)


def test_get_live_candle_for_symbol_uses_watcher_snapshot_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Data()
    captured: list[str] = []

    def fake_get_live_candle_snapshot(symbol: str):
        captured.append(symbol)
        return [1_700_000_120_000, 1.0, 1.2, 0.8, 1.1, 10.0]

    monkeypatch.setattr(
        data_module, "get_live_candle_snapshot", fake_get_live_candle_snapshot
    )

    live = data._Data__get_live_candle_for_symbol("BTC/USDT", 1_700_000_000_000)

    assert captured == ["BTC/USDT"]
    assert live == {
        "timestamp": 1_700_000_120_000.0,
        "symbol": "BTC/USDT",
        "open": 1.0,
        "high": 1.2,
        "low": 0.8,
        "close": 1.1,
        "volume": 10.0,
    }


def test_build_live_candle_payload_filters_outdated_snapshot() -> None:
    payload = build_live_candle_payload(
        [1_700_000_000_000, 1.0, 1.2, 0.8, 1.1, 10.0],
        "BTC/USDT",
        1_700_000_000_000,
    )

    assert payload is None


def test_resample_ohlcv_data_returns_expected_closed_candle_frame() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [
                1_699_999_980_000,
                1_700_000_040_000,
                1_700_000_100_000,
            ],
            "open": [1.0, 2.0, 3.0],
            "high": [1.2, 2.2, 3.2],
            "low": [0.8, 1.8, 2.8],
            "close": [1.1, 2.1, 3.1],
            "volume": [10.0, 20.0, 30.0],
        }
    )

    resampled = resample_ohlcv_data(frame, "2m")

    assert resampled is not None
    assert len(resampled.index) == 2
    assert list(resampled["open"]) == [1.0, 2.0]
    assert list(resampled["close"]) == [1.1, 3.1]
    assert list(resampled["volume"]) == [10.0, 50.0]


@pytest.mark.asyncio
async def test_get_ohlcv_for_pair_merges_stored_rows_with_live_candle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Data()

    async def fake_get_dataframe_for_symbol_since(
        _symbol: str,
        _start_timestamp: float,
        *,
        end_timestamp: float | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        assert end_timestamp is None
        assert fields == ("timestamp", "open", "high", "low", "close", "volume")
        return pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000, 1_700_000_060_000],
                "open": [1.0, 2.0],
                "high": [1.2, 2.2],
                "low": [0.8, 1.8],
                "close": [1.1, 2.1],
                "volume": [10.0, 20.0],
            }
        )

    monkeypatch.setattr(
        data,
        "_Data__get_dataframe_for_symbol_since",
        fake_get_dataframe_for_symbol_since,
    )
    monkeypatch.setattr(
        data_module,
        "get_live_candle_snapshot",
        lambda _symbol: [1_700_000_120_000, 3.0, 3.2, 2.8, 3.1, 30.0],
    )

    payload = await data.get_ohlcv_for_pair("BTC/USDT", "1m", 1_700_000_000_000, 0)
    records = json.loads(payload)

    assert [record["time"] for record in records] == [
        pytest.approx(1_700_000_000.0),
        pytest.approx(1_700_000_060.0),
        pytest.approx(1_700_000_120.0),
    ]
    assert records[-1]["open"] == pytest.approx(3.0)
    assert records[-1]["close"] == pytest.approx(3.1)


@pytest.mark.asyncio
async def test_get_ohlcv_for_pair_skips_live_candle_for_bounded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = Data()

    async def fake_get_dataframe_for_symbol_since(
        _symbol: str,
        _start_timestamp: float,
        *,
        end_timestamp: float | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        assert end_timestamp == 1_700_000_060_000
        assert fields == ("timestamp", "open", "high", "low", "close", "volume")
        return pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000, 1_700_000_060_000],
                "open": [1.0, 2.0],
                "high": [1.2, 2.2],
                "low": [0.8, 1.8],
                "close": [1.1, 2.1],
                "volume": [10.0, 20.0],
            }
        )

    monkeypatch.setattr(
        data,
        "_Data__get_dataframe_for_symbol_since",
        fake_get_dataframe_for_symbol_since,
    )
    monkeypatch.setattr(
        data_module,
        "get_live_candle_snapshot",
        lambda _symbol: [1_700_000_120_000, 3.0, 3.2, 2.8, 3.1, 30.0],
    )

    payload = await data.get_ohlcv_for_pair(
        "BTC/USDT",
        "1m",
        1_700_000_000_000,
        0,
        timestamp_end=1_700_000_060_000,
    )
    records = json.loads(payload)

    assert [record["time"] for record in records] == [
        pytest.approx(1_700_000_000.0),
        pytest.approx(1_700_000_060.0),
    ]
