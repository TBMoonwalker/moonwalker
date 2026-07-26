"""Tests for same-origin HTTP and WebSocket policy."""

from __future__ import annotations

from typing import Any

import pytest
from litestar.types import Receive, Scope, Send
from service.origin_policy import (
    WEBSOCKET_POLICY_VIOLATION,
    WebSocketOriginMiddleware,
    normalize_origin,
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


async def _call_websocket_middleware(
    *,
    origin: str | None,
    host: str = "moonwalker.local:8130",
    allowed_origins: tuple[str, ...] = (),
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
    )
    await middleware(scope, receive, send)
    return called, messages


@pytest.mark.asyncio
async def test_websocket_origin_policy_allows_same_origin() -> None:
    """A dashboard served by Moonwalker should connect by default."""
    called, messages = await _call_websocket_middleware(
        origin="http://moonwalker.local:8130",
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
