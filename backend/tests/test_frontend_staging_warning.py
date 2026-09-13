"""Regression tests for the frontend staging guard.

When the built SPA entrypoint is missing from ``backend/templates``, the controller
must surface an actionable ``HTTPException`` (not fail opaquely) and the
application must log the gap at startup.
"""

import asyncio
from pathlib import Path

from controller import frontend as frontend_controller
from litestar.exceptions import HTTPException


def _staged_layout(tmp_path: Path) -> Path:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text(
        "<!doctype html><html><body>index</body></html>", encoding="utf-8"
    )
    return template_dir


def test_staging_warning_absent_when_entrypoint_present(
    tmp_path: Path, monkeypatch
) -> None:
    template_dir = _staged_layout(tmp_path)
    monkeypatch.setattr(
        frontend_controller, "SPA_INDEX_FILE", template_dir / "index.html"
    )
    assert frontend_controller.frontend_staging_warning() is None


def test_staging_warning_names_missing_entrypoint(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "templates" / "index.html"
    monkeypatch.setattr(frontend_controller, "SPA_INDEX_FILE", missing)

    message = frontend_controller.frontend_staging_warning()

    assert message is not None
    assert "not staged" in message
    assert "./run.sh start" in message


def test_spa_fallback_raises_actionable_httperror_when_not_staged(
    tmp_path: Path, monkeypatch
) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)
    monkeypatch.setattr(
        frontend_controller, "SPA_INDEX_FILE", template_dir / "index.html"
    )

    # A missing entrypoint must raise an HTTPException carrying the actionable
    # warning rather than failing opaquely. Litestar's TestClient masks 5xx
    # detail in the response body, so assert the raised exception (the contract
    # the controller docstring promises), not the masked client body.
    raised = _capture_httperror_from_serve_vue(frontend_controller)

    assert raised is not None
    assert raised.status_code == 500
    assert "not staged" in raised.detail
    assert "./run.sh start" in raised.detail


def _capture_httperror_from_serve_vue(controller) -> HTTPException | None:
    async def _run() -> None:
        await controller._serve_vue_path("")

    try:
        asyncio.run(_run())
        return None
    except HTTPException as exc:
        return exc
