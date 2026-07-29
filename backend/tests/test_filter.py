import asyncio
import hashlib
import hmac

import httpx
import pytest
import service.coin_market_cap as coin_market_cap_module
from service.coin_market_cap import (
    SNAPSHOT_MAX_STALE_SECONDS,
    SNAPSHOT_REFRESH_SECONDS,
    CoinMarketCapRankService,
)
from service.filter import Filter


def test_cmc_api_key_fingerprint_uses_a_process_local_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint_key = b"k" * 32
    api_key = "sensitive-api-key"
    monkeypatch.setattr(
        coin_market_cap_module,
        "_FINGERPRINT_KEY",
        fingerprint_key,
    )

    fingerprint = CoinMarketCapRankService._fingerprint(api_key)

    assert (
        fingerprint
        == hmac.new(
            fingerprint_key,
            api_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )
    assert api_key not in fingerprint


def test_has_enough_volume_accepts_higher_range() -> None:
    filt = Filter()
    volume = {"size": 5, "range": "M"}
    assert filt.has_enough_volume("B", 1, volume) is True


def test_has_enough_volume_rejects_lower_size_same_range() -> None:
    filt = Filter()
    volume = {"size": 10, "range": "M"}
    assert filt.has_enough_volume("M", 5, volume) is False


def test_allow_and_deny_lists() -> None:
    filt = Filter()
    assert filt.is_on_allowed_list("BTC", ["BTC", "ETH"]) is True
    assert filt.is_on_allowed_list("XRP", ["BTC", "ETH"]) is False
    assert filt.is_on_deny_list("SCAM", ["SCAM"]) is True
    assert filt.is_on_deny_list("BTC", ["SCAM"]) is False


@pytest.mark.asyncio
async def test_get_cmc_marketcap_rank_returns_none_for_malformed_payload() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = CoinMarketCapRankService(client_factory=lambda **_kwargs: client)
    await service.start()
    try:
        filt = Filter(service)
        assert await filt.get_cmc_marketcap_rank("api-key", "BTC") is None
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_cmc_snapshot_refresh_is_single_flight_for_multiple_symbols() -> None:
    request_count = 0
    release_response = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        await release_response.wait()
        return httpx.Response(
            200,
            json={
                "status": {"error_code": 0},
                "data": [
                    {"symbol": "BTC", "rank": 1},
                    {"symbol": "ETH", "rank": 2},
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = CoinMarketCapRankService(client_factory=lambda **_kwargs: client)
    await service.start()
    try:
        lookups = asyncio.gather(
            service.lookup("api-key", "BTC"),
            service.lookup("api-key", "ETH"),
        )
        await asyncio.sleep(0)
        release_response.set()
        btc, eth = await lookups

        assert request_count == 1
        assert btc.rank == 1
        assert eth.rank == 2
        assert btc.available is True
        assert eth.available is True
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_cmc_snapshot_uses_stale_data_while_refreshing() -> None:
    now = 1_000.0
    request_count = 0
    refresh_finished = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        rank = 1 if request_count == 1 else 3
        if request_count == 2:
            refresh_finished.set()
        return httpx.Response(
            200,
            json={
                "status": {"error_code": 0},
                "data": [{"symbol": "BTC", "rank": rank}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = CoinMarketCapRankService(
        client_factory=lambda **_kwargs: client,
        clock=lambda: now,
    )
    await service.start()
    try:
        assert (await service.lookup("api-key", "BTC")).rank == 1
        now += SNAPSHOT_REFRESH_SECONDS + 1

        stale = await service.lookup("api-key", "BTC")
        assert stale.rank == 1
        assert stale.stale is True
        assert stale.reason_code == "cmc_snapshot_stale"

        await asyncio.wait_for(refresh_finished.wait(), timeout=1)
        await asyncio.sleep(0)
        refreshed = await service.lookup("api-key", "BTC")
        assert refreshed.rank == 3
        assert refreshed.stale is False
        assert request_count == 2
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_cmc_snapshot_fails_closed_after_maximum_staleness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                200,
                json={
                    "status": {"error_code": 0},
                    "data": [{"symbol": "BTC", "rank": 1}],
                },
            )
        return httpx.Response(503)

    monkeypatch.setattr("service.coin_market_cap.RETRY_DELAY_SECONDS", 0)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = CoinMarketCapRankService(
        client_factory=lambda **_kwargs: client,
        clock=lambda: now,
    )
    await service.start()
    try:
        assert (await service.lookup("api-key", "BTC")).available is True
        now += SNAPSHOT_MAX_STALE_SECONDS + 1

        expired = await service.lookup("api-key", "BTC")
        assert expired.available is False
        assert expired.rank is None
        assert expired.reason_code == "cmc_snapshot_unavailable"
        assert request_count == 4
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_cmc_service_requires_lifespan_start_and_closes_client() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
    service = CoinMarketCapRankService(client_factory=lambda **_kwargs: client)

    unavailable = await service.lookup("api-key", "BTC")
    assert unavailable.reason_code == "cmc_service_not_started"

    await service.start()
    await service.start()
    await service.shutdown()
    assert client.is_closed is True
