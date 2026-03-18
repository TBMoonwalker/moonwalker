import json

import pandas as pd
import pytest
from service.data import Data


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

    payload = Data._serialize_ohlcv_dataframe(frame, offset=0)
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

    payload = Data._serialize_ohlcv_dataframe(frame, offset=60)
    records = json.loads(payload)

    assert records[0]["time"] == pytest.approx(1_700_003_600.0)
