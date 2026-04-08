"""Regression tests for top-level SPA route fallback behavior."""

from pathlib import Path

from controller import frontend as frontend_controller
from litestar import Litestar
from litestar.testing import TestClient


def test_supported_top_level_spa_routes_bypass_api_prefix_404s(
    tmp_path: Path, monkeypatch
) -> None:
    """Top-level SPA routes should serve index even when API prefixes overlap."""
    # Regression: ISSUE-001 — /monitoring deep links returned API 404s
    # Found by /qa on 2026-03-20
    # Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-03-20.md
    static_dir = tmp_path / "static"
    template_dir = tmp_path / "templates"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    (template_dir / "index.html").write_text(
        (
            "<!doctype html><html><body>"
            "<script src='/assets/app-abc12345.js'></script>"
            "</body></html>"
        ),
        encoding="utf-8",
    )
    (assets_dir / "app-abc12345.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    app = Litestar(route_handlers=frontend_controller.route_handlers)
    with TestClient(app=app) as client:
        for route in ("/control-center", "/monitoring"):
            response = client.get(route)
            assert response.status_code == 200
            assert "/assets/app-abc12345.js" in response.text
            assert "text/html" in response.headers.get("content-type", "")
            assert response.headers.get("cache-control") == "no-cache"

        asset_response = client.get("/assets/app-abc12345.js")
        assert asset_response.status_code == 200
        assert "console.log('ok');" in asset_response.text
        assert "html" not in asset_response.text.lower()
        assert "javascript" in asset_response.headers.get("content-type", "")
        assert (
            asset_response.headers.get("cache-control")
            == "public, max-age=31536000, immutable"
        )


def test_removed_legacy_spa_routes_return_not_found(
    tmp_path: Path, monkeypatch
) -> None:
    """Removed legacy config entry routes should no longer fall back to the SPA."""
    static_dir = tmp_path / "static"
    template_dir = tmp_path / "templates"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    (template_dir / "index.html").write_text(
        "<!doctype html><html><body>index</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(frontend_controller, "STATIC_DIR", static_dir)
    monkeypatch.setattr(frontend_controller, "TEMPLATE_DIR", template_dir)

    app = Litestar(route_handlers=frontend_controller.route_handlers)
    with TestClient(app=app) as client:
        for route in ("/settings", "/config"):
            response = client.get(route)
            assert response.status_code == 404
