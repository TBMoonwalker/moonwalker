"""Regression tests for the frontend staging guard.

When the built SPA entrypoint is missing from the template directory, or a
bundle the entrypoint references is missing from the static directory, the
controller must answer dashboard routes with an actionable error body (not
fail opaquely or serve a blank page) and the application must log the gap at
startup. The guard resolves its paths against the live ``TEMPLATE_DIR`` and
``STATIC_DIR`` so these tests patch the same sources of truth the fallback
uses.
"""

import json
from pathlib import Path

from controller import frontend as frontend_controller
from litestar import Litestar
from litestar.testing import TestClient


def test_staging_warning_absent_when_entrypoint_present(
    tmp_path: Path, monkeypatch
) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    assert frontend_controller.frontend_staging_warning() is None


def test_staging_warning_names_missing_entrypoint(tmp_path: Path, monkeypatch) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    message = frontend_controller.frontend_staging_warning()

    assert message is not None
    assert "not staged" in message
    assert "./run.sh start" in message


def test_staging_warning_absent_when_all_referenced_assets_present(
    tmp_path: Path, monkeypatch
) -> None:
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text(
        (
            "<!doctype html><html><head>"
            '<script type="module" crossorigin src="/assets/app-abc12345.js"></script>'
            '<link rel="stylesheet" crossorigin href="/assets/app-def67890.css">'
            "</head></html>"
        ),
        encoding="utf-8",
    )
    (static_dir / "assets" / "app-abc12345.js").write_text(
        "console.log('ok');", encoding="utf-8"
    )
    (static_dir / "assets" / "app-def67890.css").write_text("body {}", encoding="utf-8")

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    assert frontend_controller.frontend_staging_warning() is None


def test_staging_warning_names_missing_referenced_assets(
    tmp_path: Path, monkeypatch
) -> None:
    """A partial stage (entrypoint present, bundle missing) must be flagged.

    Regression for finding F1 of the 2026-09-13 pre-landing review: such a
    stage previously passed both the startup guard and the request path, so a
    dead dashboard answered HTTP 200 with a blank page.
    """
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text(
        (
            "<!doctype html><html><head>"
            '<script type="module" crossorigin src="/assets/app-abc12345.js"></script>'
            '<link rel="modulepreload" crossorigin href="/assets/vendor-def67890.js">'
            "</head></html>"
        ),
        encoding="utf-8",
    )
    (static_dir / "assets" / "app-abc12345.js").write_text(
        "console.log('ok');", encoding="utf-8"
    )
    # vendor-def67890.js deliberately missing: partial stage.

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    message = frontend_controller.frontend_staging_warning()

    assert message is not None
    assert "partially staged" in message
    assert "/assets/vendor-def67890.js" in message
    assert "./run.sh start" in message


def _build_staging_app() -> Litestar:
    """Build the minimal app whose handlers serve the SPA routes."""
    return Litestar(route_handlers=frontend_controller.route_handlers)


def test_spa_fallback_answers_actionable_body_when_not_staged(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing entrypoint must reach the browser as an actionable 500 body.

    Litestar masks ``HTTPException.detail`` on 500 responses, so the guard
    answers with a controlled body; assert at the HTTP level that the
    actionable message survives (finding F2).
    """
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    with TestClient(app=_build_staging_app()) as client:
        response = client.get("/")

    assert response.status_code == 500
    body = json.loads(response.text)
    assert "not staged" in body["detail"]
    assert "./run.sh start" in body["detail"]


def test_spa_fallback_answers_actionable_body_when_partially_staged(
    tmp_path: Path, monkeypatch
) -> None:
    """A partial stage must answer an actionable 500 body, not a blank 200."""
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text(
        (
            "<!doctype html><html><head>"
            '<script type="module" crossorigin src="/assets/app-abc12345.js"></script>'
            "</head></html>"
        ),
        encoding="utf-8",
    )
    # No staged assets: partial stage.

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    with TestClient(app=_build_staging_app()) as client:
        response = client.get("/")

    assert response.status_code == 500
    body = json.loads(response.text)
    assert "partially staged" in body["detail"]
    assert "/assets/app-abc12345.js" in body["detail"]
    assert "./run.sh start" in body["detail"]


def test_spa_fallback_serves_entrypoint_when_fully_staged(
    tmp_path: Path, monkeypatch
) -> None:
    """A complete stage keeps serving the entrypoint (the normal contract)."""
    static_dir = tmp_path / "static"
    (static_dir / "assets").mkdir(parents=True)
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "index.html").write_text(
        (
            "<!doctype html><html><head>"
            '<script type="module" crossorigin src="/assets/app-abc12345.js"></script>'
            "</head></html>"
        ),
        encoding="utf-8",
    )
    (static_dir / "assets" / "app-abc12345.js").write_text(
        "console.log('ok');", encoding="utf-8"
    )

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    with TestClient(app=_build_staging_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "/assets/app-abc12345.js" in response.text
