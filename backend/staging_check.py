"""Dependency-free verification of the staged frontend entrypoint.

The built SPA entrypoint (``backend/templates/index.html``) references the
Vite hashed bundles under ``/assets/``. This module decides, from the
entrypoint text alone, which of those references are missing from the staged
static root. It is stdlib-only by contract: both the Litestar controller and
the pre-venv ``run.sh`` verification script import it, and the latter runs
under the bootstrap python before the project virtualenv exists.
"""

from html.parser import HTMLParser
from pathlib import Path

_ASSET_URL_PREFIX = "/assets/"
_REFERENCE_ATTRIBUTES = ("src", "href")


class _AssetReferenceParser(HTMLParser):
    """Collect the staged-asset URLs an HTML document references."""

    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record every ``src``/``href`` attribute pointing at a staged asset."""
        for name, value in attrs:
            if name in _REFERENCE_ATTRIBUTES and value is not None:
                if value.startswith(_ASSET_URL_PREFIX):
                    self.references.append(value)


def extract_asset_references(index_html: str) -> list[str]:
    """Return the staged-asset references an entrypoint document makes.

    Args:
        index_html: Raw HTML text of the staged entrypoint.

    Returns:
        The deduplicated, order-preserving list of ``/assets/...`` URLs
        referenced via ``src``/``href`` attributes. Non-asset references
        (for example ``/favicon.ico``) are not bootstrap-critical and are
        ignored.
    """
    parser = _AssetReferenceParser()
    parser.feed(index_html)
    return list(dict.fromkeys(parser.references))


def missing_referenced_assets(index_file: Path, static_root: Path) -> list[str]:
    """Return the entrypoint's asset references absent from the static root.

    Args:
        index_file: The staged entrypoint file (``index.html``).
        static_root: Root directory the ``/assets/...`` references resolve
            under (``backend/static``).

    Returns:
        The references, in entrypoint order, whose files are missing. A
        reference that escapes the static root is reported missing; the
        entrypoint is trusted build output and the serving path keeps its own
        containment.
    """
    missing: list[str] = []
    references = extract_asset_references(index_file.read_text(encoding="utf-8"))
    for reference in references:
        target = static_root / reference.removeprefix("/")
        if not target.is_file():
            missing.append(reference)
    return missing
