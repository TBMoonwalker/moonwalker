"""Shared response helpers for controller handlers."""

import json
from typing import Any

from litestar.response import Response


def json_response(payload: Any, status_code: int = 200) -> Response[str]:
    """Build a JSON response with an explicit status code."""
    return Response(
        content=json.dumps(payload, default=str),
        media_type="application/json",
        status_code=status_code,
    )
