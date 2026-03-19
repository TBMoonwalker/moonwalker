from pathlib import Path

from service.log_viewer import LogSource, LogViewerService


def _build_service(log_path: Path) -> LogViewerService:
    return LogViewerService(
        (
            LogSource("watcher", "Watcher", log_path),
            LogSource("missing", "Missing", log_path.parent / "missing.log"),
        )
    )


def test_log_viewer_lists_allowlisted_sources_with_availability(tmp_path: Path) -> None:
    log_path = tmp_path / "watcher.log"
    log_path.write_text("2026-03-19 - INFO - watcher : started\n", encoding="utf-8")

    service = _build_service(log_path)

    assert service.list_sources() == [
        {"source": "watcher", "label": "Watcher", "available": True},
        {"source": "missing", "label": "Missing", "available": False},
    ]


def test_log_viewer_reads_latest_complete_lines_only(tmp_path: Path) -> None:
    log_path = tmp_path / "watcher.log"
    log_path.write_text(
        "2026-03-19 - INFO - watcher : line 1\n"
        "2026-03-19 - INFO - watcher : line 2\n"
        "2026-03-19 - INFO - watcher : partial",
        encoding="utf-8",
    )

    result = _build_service(log_path).read_source("watcher", limit=10)

    assert result.lines == [
        "2026-03-19 - INFO - watcher : line 1",
        "2026-03-19 - INFO - watcher : line 2",
    ]
    assert result.cursor < log_path.stat().st_size
    assert result.oldest_cursor == 0
    assert result.has_more_before is False


def test_log_viewer_reads_incremental_updates_without_consuming_partial_lines(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "watcher.log"
    log_path.write_text(
        "2026-03-19 - INFO - watcher : first\n",
        encoding="utf-8",
    )
    service = _build_service(log_path)
    initial = service.read_source("watcher", limit=10)

    with log_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write("2026-03-19 - INFO - watcher : second\n")
        file_handle.write("2026-03-19 - INFO - watcher : third")

    update = service.read_source("watcher", cursor=initial.cursor, limit=10)
    assert update.lines == ["2026-03-19 - INFO - watcher : second"]

    with log_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write(" completed\n")

    update_after_completion = service.read_source(
        "watcher", cursor=update.cursor, limit=10
    )
    assert update_after_completion.lines == [
        "2026-03-19 - INFO - watcher : third completed"
    ]


def test_log_viewer_supports_backfill_and_more_before_state(tmp_path: Path) -> None:
    log_path = tmp_path / "watcher.log"
    log_path.write_text(
        "".join(
            f"2026-03-19 - INFO - watcher : line {index}\n" for index in range(1, 7)
        ),
        encoding="utf-8",
    )
    service = _build_service(log_path)

    latest = service.read_source("watcher", limit=2)
    older = service.read_source("watcher", before=latest.oldest_cursor, limit=2)

    assert latest.lines == [
        "2026-03-19 - INFO - watcher : line 5",
        "2026-03-19 - INFO - watcher : line 6",
    ]
    assert older.lines == [
        "2026-03-19 - INFO - watcher : line 3",
        "2026-03-19 - INFO - watcher : line 4",
    ]
    assert older.has_more_before is True


def test_log_viewer_marks_rotation_when_cursor_is_past_current_file_size(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "watcher.log"
    log_path.write_text(
        "2026-03-19 - INFO - watcher : before rotate\n",
        encoding="utf-8",
    )
    service = _build_service(log_path)
    initial = service.read_source("watcher", limit=10)

    log_path.write_text(
        "2026-03-19 - INFO - watcher : after rotate\n",
        encoding="utf-8",
    )

    rotated = service.read_source("watcher", cursor=initial.cursor + 100, limit=10)
    assert rotated.rotated is True
    assert rotated.lines == ["2026-03-19 - INFO - watcher : after rotate"]


def test_log_viewer_returns_empty_payload_for_known_missing_source(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path / "watcher.log")

    result = service.read_source("missing", limit=10)

    assert result.available is False
    assert result.lines == []
    assert result.cursor == 0
