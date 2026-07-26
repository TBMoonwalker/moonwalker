"""Tests for same-origin HTTP and WebSocket policy."""

from __future__ import annotations

from typing import Any

import pytest
from litestar.types import Receive, Scope, Send
from service.origin_policy import (
    MOONWALKER_CLIENT_HEADER,
    MOONWALKER_CLIENT_HEADER_VALUE,
    WEBSOCKET_POLICY_VIOLATION,
    TrustedLanHttpMiddleware,
    WebSocketOriginMiddleware,
    normalize_host,
    normalize_origin,
    parse_allowed_hosts,
    parse_allowed_origins,
)


@pytest.mark.parametrize(
    ("raw_origin", "expected"),
    [
        ("HTTPS://Dashboard.Example.com/", "https://dashboard.example.com"),
        ("http://localhost:8130", "http://localhost:8130"),
        ("http://localhost:80", "http://localhost"),
        ("https://localhost:443", "https://localhost"),
        ("http://[::1]:8130", "http://[::1]:8130"),
    ],
)
def test_normalize_origin_returns_canonical_origin(
    raw_origin: str,
    expected: str,
) -> None:
    """Valid explicit origins should have one stable representation."""
    assert normalize_origin(raw_origin) == expected


@pytest.mark.parametrize(
    "raw_origin",
    [
        "*",
        "https://*.example.com",
        "dashboard.example.com",
        "ftp://dashboard.example.com",
        "https://user:secret@dashboard.example.com",
        "https://dashboard.example.com/path",
        "https://dashboard.example.com?mode=live",
        "https://dashboard.example.com#status",
        "https://dashboard.example.com:invalid",
    ],
)
def test_normalize_origin_rejects_unsafe_values(raw_origin: str) -> None:
    """Malformed and wildcard origins must fail startup validation."""
    with pytest.raises(ValueError):
        normalize_origin(raw_origin)


def test_parse_allowed_origins_deduplicates_and_preserves_order() -> None:
    """The environment allowlist should be deterministic."""
    assert parse_allowed_origins(
        "https://dashboard.example.com/, http://localhost:3000, "
        "https://dashboard.example.com"
    ) == (
        "https://dashboard.example.com",
        "http://localhost:3000",
    )


def test_parse_allowed_origins_defaults_to_same_origin_only() -> None:
    """An unset or empty allowlist must not enable cross-origin access."""
    assert parse_allowed_origins(None) == ()
    assert parse_allowed_origins("  ") == ()


@pytest.mark.parametrize(
    ("raw_host", "expected"),
    [
        ("192.168.6.5:8150", "192.168.6.5:8150"),
        ("LOCALHOST", "localhost"),
        ("[::1]:8130", "[::1]:8130"),
        ("moonwalker.local:8130", "moonwalker.local:8130"),
    ],
)
def test_normalize_host_returns_canonical_authority(
    raw_host: str,
    expected: str,
) -> None:
    """Valid Host authorities should have one stable representation."""
    assert normalize_host(raw_host) == expected


@pytest.mark.parametrize(
    "raw_host",
    ["", "*", "https://moonwalker.local", "user@moonwalker.local", "host/path"],
)
def test_normalize_host_rejects_unsafe_values(raw_host: str) -> None:
    """Host allowlists must reject ambiguous or URL-shaped values."""
    with pytest.raises(ValueError):
        normalize_host(raw_host)


def test_parse_allowed_hosts_deduplicates_values() -> None:
    """Explicit local DNS names should be normalized once."""
    assert parse_allowed_hosts("moonwalker.local:8130, MOONWALKER.local:8130") == (
        "moonwalker.local:8130",
    )


async def _call_http_middleware(
    *,
    method: str = "POST",
    host: str = "192.168.6.5:8150",
    origin: str | None = "http://192.168.6.5:8150",
    client_header: str | None = MOONWALKER_CLIENT_HEADER_VALUE,
    allowed_origins: tuple[str, ...] = (),
    allowed_hosts: tuple[str, ...] = (),
) -> tuple[bool, list[dict[str, Any]]]:
    called = False
    messages: list[dict[str, Any]] = []

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if client_header is not None:
        headers.append((MOONWALKER_CLIENT_HEADER, client_header.encode()))
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/orders/sell/BTCUSDT",
        "raw_path": b"/orders/sell/BTCUSDT",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 10000),
        "server": ("0.0.0.0", 8150),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    middleware = TrustedLanHttpMiddleware(
        inner_app,
        allowed_origins=allowed_origins,
        allowed_hosts=allowed_hosts,
    )
    await middleware(scope, receive, send)
    return called, messages


@pytest.mark.asyncio
async def test_http_policy_allows_same_origin_dashboard_mutation() -> None:
    """The served dashboard should mutate through the trusted client header."""
    called, messages = await _call_http_middleware()
    assert called is True
    assert messages == []


@pytest.mark.asyncio
async def test_http_policy_rejects_cross_origin_mutation() -> None:
    """A cross-site form or script must not reach an unsafe handler."""
    called, messages = await _call_http_middleware(
        origin="https://attacker.example",
    )
    assert called is False
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_http_policy_requires_dashboard_header_for_browser_mutation() -> None:
    """Same-origin browser mutations still need the anti-CSRF header."""
    called, messages = await _call_http_middleware(client_header=None)
    assert called is False
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_http_policy_allows_private_lan_client_without_origin() -> None:
    """CLI and automation clients on the trusted LAN remain supported."""
    called, messages = await _call_http_middleware(
        origin=None,
        client_header=None,
    )
    assert called is True
    assert messages == []


@pytest.mark.asyncio
async def test_http_policy_rejects_untrusted_host_for_direct_client() -> None:
    """DNS-rebinding hostnames must not reach unsafe handlers by default."""
    called, messages = await _call_http_middleware(
        host="attacker.example",
        origin=None,
        client_header=None,
    )
    assert called is False
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_http_policy_allows_explicit_local_hostname() -> None:
    """Operators can allow a stable local DNS name explicitly."""
    called, messages = await _call_http_middleware(
        host="moonwalker.local:8150",
        origin=None,
        client_header=None,
        allowed_hosts=("moonwalker.local",),
    )
    assert called is True
    assert messages == []


@pytest.mark.asyncio
async def test_http_policy_rejects_untrusted_host_for_read_only_requests() -> None:
    """DNS rebinding must not expose read-only APIs or backup exports."""
    called, messages = await _call_http_middleware(
        method="GET",
        host="attacker.example",
        origin="https://attacker.example",
        client_header=None,
    )
    assert called is False
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_http_policy_allows_trusted_read_only_requests() -> None:
    """Normal dashboard reads should pass after Host validation."""
    called, messages = await _call_http_middleware(
        method="GET",
        client_header=None,
    )
    assert called is True
    assert messages == []


async def _call_websocket_middleware(
    *,
    origin: str | None,
    host: str = "192.168.6.5:8130",
    allowed_origins: tuple[str, ...] = (),
    allowed_hosts: tuple[str, ...] = (),
) -> tuple[bool, list[dict[str, Any]]]:
    called = False
    messages: list[dict[str, Any]] = []

    async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    scope: Scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "scheme": "ws",
        "path": "/trades/open",
        "raw_path": b"/trades/open",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 10000),
        "server": ("moonwalker.local", 8130),
        "subprotocols": [],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    middleware = WebSocketOriginMiddleware(
        inner_app,
        allowed_origins=allowed_origins,
        allowed_hosts=allowed_hosts,
    )
    await middleware(scope, receive, send)
    return called, messages


@pytest.mark.asyncio
async def test_websocket_origin_policy_allows_same_origin() -> None:
    """A dashboard served by Moonwalker should connect by default."""
    called, messages = await _call_websocket_middleware(
        origin="http://192.168.6.5:8130",
    )
    assert called is True
    assert messages == []


@pytest.mark.asyncio
async def test_websocket_origin_policy_allows_explicit_proxy_origin() -> None:
    """An explicitly configured reverse-proxy origin should connect."""
    called, messages = await _call_websocket_middleware(
        origin="https://dashboard.example.com",
        allowed_origins=("https://dashboard.example.com",),
    )
    assert called is True
    assert messages == []


@pytest.mark.asyncio
async def test_websocket_origin_policy_rejects_cross_origin() -> None:
    """Unlisted cross-origin browser WebSockets should fail closed."""
    called, messages = await _call_websocket_middleware(
        origin="https://attacker.example",
    )
    assert called is False
    assert messages == [
        {
            "type": "websocket.close",
            "code": WEBSOCKET_POLICY_VIOLATION,
            "reason": "WebSocket origin is not allowed.",
        }
    ]


@pytest.mark.asyncio
async def test_websocket_origin_policy_allows_non_browser_clients() -> None:
    """Clients without an Origin header remain supported."""
    called, messages = await _call_websocket_middleware(origin=None)
    assert called is True
    assert messages == []


@pytest.mark.asyncio
async def test_websocket_origin_policy_rejects_dns_rebinding_host() -> None:
    """A same-origin attacker hostname must not become a trusted WS authority."""
    called, messages = await _call_websocket_middleware(
        host="attacker.example",
        origin="http://attacker.example",
    )
    assert called is False
    assert messages == [
        {
            "type": "websocket.close",
            "code": WEBSOCKET_POLICY_VIOLATION,
            "reason": "WebSocket Host is not allowed.",
        }
    ]


@pytest.mark.asyncio
async def test_websocket_origin_policy_allows_explicit_local_hostname() -> None:
    """Operators can explicitly trust a stable local WebSocket hostname."""
    called, messages = await _call_websocket_middleware(
        host="moonwalker.local:8130",
        origin="http://moonwalker.local:8130",
        allowed_hosts=("moonwalker.local",),
    )
    assert called is True
    assert messages == []
