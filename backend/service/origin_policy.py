"""Browser-origin policy for HTTP CORS and WebSocket connections."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from litestar.types import ASGIApp, Receive, Scope, Send

WEBSOCKET_POLICY_VIOLATION = 1008


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


def _header_value(scope: Scope, name: bytes) -> str | None:
    """Return a decoded ASGI header value."""
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _origin_matches_host(origin: str, host: str) -> bool:
    """Return whether a normalized origin has the request Host authority."""
    parsed = urlsplit(origin)
    return parsed.netloc.lower() == host.strip().lower()


class WebSocketOriginMiddleware:
    """Reject cross-origin browser WebSockets unless explicitly allowed."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket":
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
        host = _header_value(scope, b"host")
        same_origin = bool(host and origin and _origin_matches_host(origin, host))
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
