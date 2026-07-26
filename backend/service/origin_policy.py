"""Browser-origin policy for HTTP CORS and WebSocket connections."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable
from urllib.parse import urlsplit

from litestar.types import ASGIApp, Receive, Scope, Send

WEBSOCKET_POLICY_VIOLATION = 1008
MOONWALKER_CLIENT_HEADER = b"x-moonwalker-client"
MOONWALKER_CLIENT_HEADER_VALUE = "dashboard"
UNSAFE_HTTP_METHODS = frozenset({"DELETE", "PATCH", "POST", "PUT"})


def normalize_origin(value: str) -> str:
    """Validate and normalize one explicit browser origin.

    Args:
        value: Origin containing only an HTTP(S) scheme and authority.

    Returns:
        The canonical origin without a trailing slash or default port.

    Raises:
        ValueError: If the value is not a concrete HTTP(S) origin.
    """
    candidate = value.strip()
    if not candidate or "*" in candidate:
        raise ValueError("Origins must be explicit; wildcards are not allowed.")

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Origins must use http:// or https://.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Origins must contain a host and no credentials.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Origins cannot contain a path, query, or fragment.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Origin contains an invalid port.") from exc

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    return f"{scheme}://{hostname}"


def parse_allowed_origins(raw_value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated explicit origin allowlist."""
    if raw_value is None or not raw_value.strip():
        return ()

    origins: list[str] = []
    for raw_origin in raw_value.split(","):
        origin = normalize_origin(raw_origin)
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


def normalize_host(value: str) -> str:
    """Validate and normalize one HTTP Host authority."""
    candidate = value.strip()
    if not candidate or any(character in candidate for character in "/*?#@"):
        raise ValueError("Hosts must contain only a hostname and optional port.")

    parsed = urlsplit(f"//{candidate}")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Hosts must contain a hostname and no credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Host contains an invalid port.") from exc

    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"{hostname}:{port}" if port is not None else hostname


def parse_allowed_hosts(raw_value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated explicit Host allowlist."""
    if raw_value is None or not raw_value.strip():
        return ()

    hosts: list[str] = []
    for raw_host in raw_value.split(","):
        host = normalize_host(raw_host)
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _header_value(scope: Scope, name: bytes) -> str | None:
    """Return a decoded ASGI header value."""
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _origin_matches_host(origin: str, host: str) -> bool:
    """Return whether a normalized origin has the request Host authority."""
    parsed = urlsplit(origin)
    try:
        return normalize_host(parsed.netloc) == normalize_host(host)
    except ValueError:
        return False


def _hostname_from_authority(authority: str) -> str:
    """Return the normalized hostname portion of an authority."""
    parsed = urlsplit(f"//{authority}")
    return str(parsed.hostname or "").lower()


def _is_trusted_lan_host(host: str, allowed_hosts: frozenset[str]) -> bool:
    """Return whether Host targets loopback, a private IP, or an allowlist."""
    try:
        normalized_host = normalize_host(host)
    except ValueError:
        return False
    hostname = _hostname_from_authority(normalized_host)
    allowed_hostnames = {
        _hostname_from_authority(authority) for authority in allowed_hosts
    }
    if normalized_host in allowed_hosts or hostname in allowed_hostnames:
        return True
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


async def _send_http_forbidden(send: Send, message: str) -> None:
    """Send a compact JSON rejection without entering application routing."""
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class TrustedLanHttpMiddleware:
    """Protect HTTP requests while preserving trusted LAN clients."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Iterable[str] = (),
        allowed_hosts: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        origin_hosts = {
            normalize_host(urlsplit(origin).netloc) for origin in self.allowed_origins
        }
        self.allowed_hosts = frozenset(allowed_hosts) | origin_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host = _header_value(scope, b"host")
        if host is None or not _is_trusted_lan_host(host, self.allowed_hosts):
            await _send_http_forbidden(send, "Request Host is not allowed.")
            return

        if str(scope.get("method", "")).upper() not in UNSAFE_HTTP_METHODS:
            await self.app(scope, receive, send)
            return

        raw_origin = _header_value(scope, b"origin")
        if raw_origin is None:
            await self.app(scope, receive, send)
            return

        try:
            origin = normalize_origin(raw_origin)
        except ValueError:
            origin = ""
        if not (
            origin
            and (_origin_matches_host(origin, host) or origin in self.allowed_origins)
        ):
            await _send_http_forbidden(send, "Request Origin is not allowed.")
            return

        client_header = _header_value(scope, MOONWALKER_CLIENT_HEADER)
        if client_header != MOONWALKER_CLIENT_HEADER_VALUE:
            await _send_http_forbidden(
                send,
                "Browser mutation is missing the Moonwalker client header.",
            )
            return

        await self.app(scope, receive, send)


class WebSocketOriginMiddleware:
    """Reject cross-origin browser WebSockets unless explicitly allowed."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Iterable[str] = (),
        allowed_hosts: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        origin_hosts = {
            normalize_host(urlsplit(origin).netloc) for origin in self.allowed_origins
        }
        self.allowed_hosts = frozenset(allowed_hosts) | origin_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return

        host = _header_value(scope, b"host")
        if host is None or not _is_trusted_lan_host(host, self.allowed_hosts):
            await send(
                {
                    "type": "websocket.close",
                    "code": WEBSOCKET_POLICY_VIOLATION,
                    "reason": "WebSocket Host is not allowed.",
                }
            )
            return

        raw_origin = _header_value(scope, b"origin")
        if raw_origin is None:
            await self.app(scope, receive, send)
            return

        try:
            origin = normalize_origin(raw_origin)
        except ValueError:
            origin = ""
        same_origin = bool(origin and _origin_matches_host(origin, host))
        if same_origin or origin in self.allowed_origins:
            await self.app(scope, receive, send)
            return

        await send(
            {
                "type": "websocket.close",
                "code": WEBSOCKET_POLICY_VIOLATION,
                "reason": "WebSocket origin is not allowed.",
            }
        )
