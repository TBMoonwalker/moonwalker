"""Read-only helpers for exposing monitored log files to the frontend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_LOG_READ_LIMIT = 500
DEFAULT_LOG_READ_LIMIT = 200
LOG_READ_CHUNK_SIZE = 64 * 1024
ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LogSource:
    """Allowlisted frontend-visible log source."""

    source: str
    label: str
    path: Path


@dataclass(frozen=True)
class LogLineChunk:
    """One complete log line with byte offsets."""

    start_offset: int
    end_offset: int
    text: str


@dataclass(frozen=True)
class LogReadResult:
    """Normalized log read payload for API responses."""

    source: str
    label: str
    available: bool
    lines: list[str]
    cursor: int
    oldest_cursor: int
    has_more_before: bool
    rotated: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "source": self.source,
            "label": self.label,
            "available": self.available,
            "lines": self.lines,
            "cursor": self.cursor,
            "oldest_cursor": self.oldest_cursor,
            "has_more_before": self.has_more_before,
            "rotated": self.rotated,
        }


DEFAULT_LOG_SOURCES: tuple[LogSource, ...] = (
    LogSource("watcher", "Watcher", Path("logs/watcher.log")),
    LogSource("exchange", "Exchange", Path("logs/exchange.log")),
    LogSource("orders", "Orders", Path("logs/orders.log")),
    LogSource("signal", "Signal", Path("logs/signal.log")),
    LogSource("monitoring", "Monitoring", Path("logs/monitoring.log")),
    LogSource("statistics", "Statistics", Path("logs/statistics.log")),
    LogSource("dca", "DCA", Path("logs/dca.log")),
    LogSource("database", "Database", Path("logs/database.log")),
    LogSource("housekeeper", "Housekeeper", Path("logs/housekeeper.log")),
    LogSource("trades", "Trades", Path("logs/trades.log")),
    LogSource("data", "Data", Path("logs/data.log")),
    LogSource("green_phase", "Green Phase", Path("logs/green_phase.log")),
    LogSource("autopilot", "Autopilot", Path("logs/autopilot.log")),
    LogSource("ath", "ATH", Path("logs/ath.log")),
    LogSource("filter", "Filter", Path("logs/filter.log")),
    LogSource("strategies", "Strategies", Path("logs/strategies.log")),
    LogSource("config", "Config", Path("logs/config.log")),
    LogSource("controller", "Controller", Path("logs/controller.log")),
    LogSource("run", "Run Output", ROOT_DIR / "run.log"),
)


class LogViewerService:
    """Serve allowlisted log files in small polling-friendly batches."""

    def __init__(
        self, log_sources: tuple[LogSource, ...] = DEFAULT_LOG_SOURCES
    ) -> None:
        self._sources = {source.source: source for source in log_sources}

    def list_sources(self) -> list[dict[str, object]]:
        """Return metadata for all frontend-visible log sources."""
        return [
            {
                "source": source.source,
                "label": source.label,
                "available": source.path.exists(),
            }
            for source in self._sources.values()
        ]

    def read_source(
        self,
        source_name: str,
        cursor: int | None = None,
        before: int | None = None,
        limit: int = DEFAULT_LOG_READ_LIMIT,
    ) -> LogReadResult:
        """Read the requested log source with tailing or backfill semantics."""
        if cursor is not None and before is not None:
            raise ValueError("Use either 'cursor' or 'before', not both.")

        source = self._resolve_source(source_name)
        normalized_limit = self._normalize_limit(limit)
        path = source.path

        if not path.exists():
            return LogReadResult(
                source=source.source,
                label=source.label,
                available=False,
                lines=[],
                cursor=0,
                oldest_cursor=0,
                has_more_before=False,
                rotated=False,
            )

        if before is not None:
            return self._read_before(path, source, before, normalized_limit)
        if cursor is not None:
            return self._read_after_cursor(path, source, cursor, normalized_limit)
        return self._read_latest(path, source, normalized_limit)

    def _resolve_source(self, source_name: str) -> LogSource:
        source = self._sources.get(source_name)
        if source is None:
            raise ValueError(f"Unknown log source: {source_name}")
        return source

    def _read_latest(self, path: Path, source: LogSource, limit: int) -> LogReadResult:
        file_size = path.stat().st_size
        if file_size == 0:
            return LogReadResult(
                source=source.source,
                label=source.label,
                available=True,
                lines=[],
                cursor=0,
                oldest_cursor=0,
                has_more_before=False,
                rotated=False,
            )

        start = file_size
        line_chunks: list[LogLineChunk] = []
        complete_end_cursor = 0
        while True:
            start = max(0, start - LOG_READ_CHUNK_SIZE)
            line_chunks, complete_end_cursor = self._read_complete_lines(
                path, start, file_size
            )
            if len(line_chunks) >= limit or start == 0:
                break

        selected_chunks = line_chunks[-limit:]
        oldest_cursor = (
            selected_chunks[0].start_offset if selected_chunks else complete_end_cursor
        )
        return LogReadResult(
            source=source.source,
            label=source.label,
            available=True,
            lines=[chunk.text for chunk in selected_chunks],
            cursor=complete_end_cursor,
            oldest_cursor=oldest_cursor,
            has_more_before=oldest_cursor > 0,
            rotated=False,
        )

    def _read_after_cursor(
        self, path: Path, source: LogSource, cursor: int, limit: int
    ) -> LogReadResult:
        file_size = path.stat().st_size
        normalized_cursor = max(0, cursor)
        if normalized_cursor > file_size:
            latest = self._read_latest(path, source, limit)
            return LogReadResult(
                source=latest.source,
                label=latest.label,
                available=latest.available,
                lines=latest.lines,
                cursor=latest.cursor,
                oldest_cursor=latest.oldest_cursor,
                has_more_before=latest.has_more_before,
                rotated=True,
            )

        line_chunks, complete_end_cursor = self._read_complete_lines(
            path, normalized_cursor, file_size
        )
        if not line_chunks:
            return LogReadResult(
                source=source.source,
                label=source.label,
                available=True,
                lines=[],
                cursor=complete_end_cursor,
                oldest_cursor=normalized_cursor,
                has_more_before=normalized_cursor > 0,
                rotated=False,
            )

        selected_chunks = line_chunks[:limit]
        next_cursor = selected_chunks[-1].end_offset
        return LogReadResult(
            source=source.source,
            label=source.label,
            available=True,
            lines=[chunk.text for chunk in selected_chunks],
            cursor=next_cursor,
            oldest_cursor=selected_chunks[0].start_offset,
            has_more_before=selected_chunks[0].start_offset > 0,
            rotated=False,
        )

    def _read_before(
        self, path: Path, source: LogSource, before: int, limit: int
    ) -> LogReadResult:
        file_size = path.stat().st_size
        normalized_before = max(0, before)
        if normalized_before > file_size:
            latest = self._read_latest(path, source, limit)
            return LogReadResult(
                source=latest.source,
                label=latest.label,
                available=latest.available,
                lines=latest.lines,
                cursor=latest.cursor,
                oldest_cursor=latest.oldest_cursor,
                has_more_before=latest.has_more_before,
                rotated=True,
            )

        if normalized_before == 0:
            return LogReadResult(
                source=source.source,
                label=source.label,
                available=True,
                lines=[],
                cursor=0,
                oldest_cursor=0,
                has_more_before=False,
                rotated=False,
            )

        start = normalized_before
        line_chunks: list[LogLineChunk] = []
        complete_end_cursor = 0
        while True:
            start = max(0, start - LOG_READ_CHUNK_SIZE)
            line_chunks, complete_end_cursor = self._read_complete_lines(
                path, start, normalized_before
            )
            if len(line_chunks) >= limit or start == 0:
                break

        selected_chunks = line_chunks[-limit:]
        oldest_cursor = selected_chunks[0].start_offset if selected_chunks else 0
        cursor = selected_chunks[-1].end_offset if selected_chunks else 0
        return LogReadResult(
            source=source.source,
            label=source.label,
            available=True,
            lines=[chunk.text for chunk in selected_chunks],
            cursor=cursor,
            oldest_cursor=oldest_cursor,
            has_more_before=oldest_cursor > 0,
            rotated=False,
        )

    def _read_complete_lines(
        self, path: Path, start_offset: int, end_offset: int
    ) -> tuple[list[LogLineChunk], int]:
        if end_offset <= start_offset:
            return [], start_offset

        with path.open("rb") as file_handle:
            file_handle.seek(start_offset)
            data = file_handle.read(end_offset - start_offset)
            previous_byte = b""
            if start_offset > 0:
                file_handle.seek(start_offset - 1)
                previous_byte = file_handle.read(1)

        if not data:
            return [], start_offset

        drop_partial_prefix = start_offset > 0 and previous_byte not in {b"\n", b"\r"}
        complete_end_cursor = end_offset
        offset = start_offset
        line_chunks: list[LogLineChunk] = []
        parts = data.splitlines(keepends=True)
        for index, raw_part in enumerate(parts):
            line_start = offset
            line_end = offset + len(raw_part)
            offset = line_end

            is_complete = raw_part.endswith((b"\n", b"\r"))
            if not is_complete:
                complete_end_cursor = line_start
                break
            if drop_partial_prefix and index == 0:
                continue

            decoded = raw_part.rstrip(b"\r\n").decode("utf-8", errors="replace")
            line_chunks.append(
                LogLineChunk(
                    start_offset=line_start,
                    end_offset=line_end,
                    text=decoded,
                )
            )

        return line_chunks, complete_end_cursor

    def _normalize_limit(self, limit: int) -> int:
        return max(1, min(limit, MAX_LOG_READ_LIMIT))
