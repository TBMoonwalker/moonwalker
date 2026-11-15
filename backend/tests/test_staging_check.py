"""Unit tests for the dependency-free staged-frontend verification helpers."""

from pathlib import Path

from staging_check import extract_asset_references, missing_referenced_assets

_ENTRYPOINT = (
    "<!doctype html><html><head>"
    '<script type="module" crossorigin src="/assets/app-abc12345.js"></script>'
    '<link rel="modulepreload" crossorigin href="/assets/vendor-def67890.js">'
    '<link rel="modulepreload" crossorigin href="/assets/app-abc12345.js">'
    '<link rel="stylesheet" crossorigin href="/assets/app-def67890.css">'
    '<link rel="icon" href="/favicon.ico">'
    '<meta property="og:image" content="https://example.com/banner.png">'
    "</head></html>"
)


def test_extract_asset_references_collects_script_and_link_targets() -> None:
    """Script, modulepreload, and stylesheet targets are captured, deduped."""
    assert extract_asset_references(_ENTRYPOINT) == [
        "/assets/app-abc12345.js",
        "/assets/vendor-def67890.js",
        "/assets/app-def67890.css",
    ]


def test_extract_asset_references_ignores_non_asset_references() -> None:
    references = extract_asset_references(
        '<link rel="icon" href="/favicon.ico">'
        '<img src="https://example.com/banner.png">'
    )

    assert references == []


def test_extract_asset_references_referenceless_document_is_empty() -> None:
    assert extract_asset_references("<!doctype html><html><body></body></html>") == []


def test_missing_referenced_assets_reports_only_absent_files(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    (static_root / "assets").mkdir(parents=True)
    (static_root / "assets" / "app-abc12345.js").write_text("js", encoding="utf-8")
    (static_root / "assets" / "app-def67890.css").write_text("css", encoding="utf-8")
    index_file = tmp_path / "index.html"
    index_file.write_text(
        '<script src="/assets/app-abc12345.js"></script>'
        '<link href="/assets/vendor-def67890.js">'
        '<link href="/assets/app-def67890.css">',
        encoding="utf-8",
    )

    assert missing_referenced_assets(index_file, static_root) == [
        "/assets/vendor-def67890.js"
    ]


def test_missing_referenced_assets_all_present_is_empty(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    (static_root / "assets").mkdir(parents=True)
    (static_root / "assets" / "app-abc12345.js").write_text("js", encoding="utf-8")
    index_file = tmp_path / "index.html"
    index_file.write_text(
        '<script src="/assets/app-abc12345.js"></script>', encoding="utf-8"
    )

    assert missing_referenced_assets(index_file, static_root) == []


def test_missing_referenced_assets_all_missing_are_listed_in_order(
    tmp_path: Path,
) -> None:
    static_root = tmp_path / "static"
    (static_root / "assets").mkdir(parents=True)
    index_file = tmp_path / "index.html"
    index_file.write_text(
        '<script src="/assets/app-abc12345.js"></script>'
        '<link href="/assets/app-def67890.css">',
        encoding="utf-8",
    )

    assert missing_referenced_assets(index_file, static_root) == [
        "/assets/app-abc12345.js",
        "/assets/app-def67890.css",
    ]


def test_missing_referenced_assets_escapes_root_without_raising(tmp_path: Path) -> None:
    """A reference escaping the static root is reported missing, not served."""
    static_root = tmp_path / "static"
    static_root.mkdir()
    index_file = tmp_path / "index.html"
    index_file.write_text(
        '<script src="/assets/../../outside.js"></script>', encoding="utf-8"
    )

    assert missing_referenced_assets(index_file, static_root) == [
        "/assets/../../outside.js"
    ]
