import json
import warnings
from datetime import UTC, datetime

import pandas as pd
import pytest
import service.data as data_module
from dateutil import tz
from pandas.errors import Pandas4Warning
from service.data import Data
from service.data_ohlcv import (
    build_live_candle_payload,
    resample_ohlcv_data,
    rows_to_dataframe,
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


def test_resample_ohlcv_data_uses_fixed_duration_weekly_buckets() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [
                1_704_326_400_000,
                1_704_412_800_000,
                1_704_499_200_000,
                1_704_585_600_000,
                1_704_672_000_000,
                1_704_758_400_000,
                1_704_844_800_000,
                1_704_931_200_000,
            ],
            "open": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "high": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5],
            "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5],
            "close": [1.1, 2.1, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1],
            "volume": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
        }
    )

    resampled = resample_ohlcv_data(frame, "1W")

    assert resampled is not None
    assert list(resampled["timestamp"]) == list(
        pd.to_datetime(
            ["2024-01-01T00:00:00Z", "2024-01-08T00:00:00Z"],
            utc=True,
        )
    )
    assert list(resampled["open"]) == [1.0, 5.0]
    assert list(resampled["close"]) == [4.1, 8.1]
    assert list(resampled["volume"]) == [100.0, 260.0]


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


@pytest.mark.parametrize(
    ("local_times", "utc_times"),
    [
        (
            [(2026, 10, 25, 2, 30, 0), (2026, 10, 25, 2, 30, 1)],
            [(2026, 10, 25, 0, 30), (2026, 10, 25, 1, 30)],
        ),
        (
            [(2040, 7, 1, 12, 0, 0)],
            [(2040, 7, 1, 10, 0)],
        ),
    ],
    ids=["repeated-autumn-hour", "summer-after-2038"],
)
def test_candle_serialization_preserves_timezone_instants(
    local_times: list[tuple[int, int, int, int, int, int]],
    utc_times: list[tuple[int, int, int, int, int]],
) -> None:
    """Keep distinct exchange instants through dateutil's timezone conversion."""
    timezone = tz.gettz("Europe/Vienna")
    assert timezone is not None
    timestamps = [
        datetime(*parts[:5], fold=parts[5], tzinfo=timezone) for parts in local_times
    ]
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 1.0,
            "high": 1.2,
            "low": 0.8,
            "close": 1.1,
            "volume": 10.0,
        }
    )
    records = json.loads(serialize_ohlcv_dataframe(frame, offset=0))
    assert [row["time"] for row in records] == [
        datetime(*parts, tzinfo=UTC).timestamp() for parts in utc_times
    ]


def test_ohlcv_helpers_emit_no_pandas4_deprecations() -> None:
    """The OHLCV helpers must not call pandas APIs removed in pandas 4.x."""
    rows = [
        {
            "timestamp": 1_700_000_000_000,
            "open": 1.0,
            "high": 1.2,
            "low": 0.8,
            "close": 1.1,
            "volume": 10.0,
        },
        {
            "timestamp": 1_700_000_060_000,
            "open": 2.0,
            "high": 2.2,
            "low": 1.8,
            "close": 2.1,
            "volume": 20.0,
        },
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame = rows_to_dataframe(rows)
        resampled = resample_ohlcv_data(frame, "2m")
        serialize_ohlcv_dataframe(resampled, offset=0)

    deprecated = [
        warning for warning in caught if issubclass(warning.category, Pandas4Warning)
    ]
    assert deprecated == []


def test_serialize_ohlcv_dataframe_removes_duplicate_timestamps_first_wins() -> None:
    """Rows sharing a timestamp must collapse to the first occurrence."""
    timestamp = pd.to_datetime(1_700_000_000_000, unit="ms", utc=True)
    frame = pd.DataFrame(
        {
            "timestamp": [timestamp, timestamp],
            "open": [1.0, 9.0],
            "high": [1.2, 9.2],
            "low": [0.8, 9.4],
            "close": [1.1, 9.1],
            "volume": [10.0, 90.0],
        }
    )

    records = json.loads(serialize_ohlcv_dataframe(frame, offset=0))

    assert len(records) == 1
    assert records[0]["time"] == pytest.approx(1_700_000_000.0)
    assert records[0]["open"] == pytest.approx(1.0)
    assert records[0]["high"] == pytest.approx(1.2)
    assert records[0]["close"] == pytest.approx(1.1)


def test_resample_ohlcv_data_drops_partial_candles_before_aggregation() -> None:
    """Rows missing any field must not contaminate their resampled bucket."""
    rows = [
        {
            "timestamp": 1_699_999_990_000,
            "open": 1.0,
            "high": 6.0,
            "low": 0.8,
            "close": 6.0,
            "volume": 20.0,
        },
        {
            "timestamp": 1_700_000_020_000,
            "open": None,
            "high": 9.0,
            "low": 0.9,
            "close": 9.0,
            "volume": 50.0,
        },
    ]

    frame = rows_to_dataframe(rows)
    resampled = resample_ohlcv_data(frame, "1m")

    assert resampled is not None
    assert len(resampled.index) == 1
    assert resampled["open"].iloc[0] == pytest.approx(1.0)
    assert resampled["high"].iloc[0] == pytest.approx(6.0)
    assert resampled["close"].iloc[0] == pytest.approx(6.0)
    assert resampled["volume"].iloc[0] == pytest.approx(20.0)
