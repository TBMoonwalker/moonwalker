"""Tests for logger factory behavior."""

import logging
import os
from pathlib import Path

import pytest
from helper.logger import LoggerFactory


def _file_handlers(logger: logging.Logger) -> list[logging.FileHandler]:
    """Return the file handlers attached to ``logger``."""
    return [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]


def _clear_logger(logger: logging.Logger) -> None:
    """Close and detach every handler from ``logger``."""
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_get_logger_creates_parent_log_directory(tmp_path: Path) -> None:
    log_file = tmp_path / "nested" / "logs" / "config.log"
    logger = LoggerFactory.get_logger(str(log_file), "test_logger_factory_create_dir")

    logger.info("hello")

    assert log_file.parent.is_dir()
    assert log_file.is_file()

    _clear_logger(logger)


def test_repeated_get_logger_attaches_single_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling get_logger repeatedly for one (name, file) must not double-attach."""
    monkeypatch.setattr("helper.logger.LOG_DIR", tmp_path)
    name = "test_logger_factory_repeated"
    logger = logging.getLogger(name)

    try:
        for _ in range(3):
            LoggerFactory.get_logger("svc.log", name)
        assert len(_file_handlers(logger)) == 1
    finally:
        _clear_logger(logger)


def test_get_logger_dedupes_when_log_dir_is_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """De-dup must recognize the same file when LOG_DIR is a symlink.

    macOS exposes /var as a symlink to /private/var and the suite's redirected
    LOG_DIR is not resolved; the factory must canonicalize so two callers
    sharing a logger do not each attach their own handler to the same file.
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    os.symlink(real_dir, link)

    monkeypatch.setattr("helper.logger.LOG_DIR", link)
    name = "test_logger_factory_symlink"
    logger = logging.getLogger(name)

    try:
        for _ in range(2):
            LoggerFactory.get_logger("svc.log", name)

        handlers = _file_handlers(logger)
        assert len(handlers) == 1
        # The handler must target the canonical (resolved) location, not the
        # symlink spelling that LOG_DIR carries.
        assert handlers[0].baseFilename == str((real_dir / "svc.log").resolve())
    finally:
        _clear_logger(logger)


def test_get_logger_dedupes_absolute_symlinked_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absolute log_file that traverses a symlink still de-duplicates."""
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    os.symlink(real_dir, link)

    name = "test_logger_factory_abs_symlink"
    logger = logging.getLogger(name)
    abs_path = link / "svc.log"

    try:
        for _ in range(2):
            LoggerFactory.get_logger(str(abs_path), name)
        assert len(_file_handlers(logger)) == 1
    finally:
        _clear_logger(logger)


def test_get_logger_keeps_distinct_files_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One logger asked for two different files must keep both handlers."""
    monkeypatch.setattr("helper.logger.LOG_DIR", tmp_path)
    name = "test_logger_factory_two_files"
    logger = logging.getLogger(name)

    try:
        LoggerFactory.get_logger("alpha.log", name)
        LoggerFactory.get_logger("beta.log", name)
        assert len(_file_handlers(logger)) == 2
    finally:
        _clear_logger(logger)


def test_get_logger_creates_handler_for_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A target that does not exist yet still yields exactly one handler."""
    monkeypatch.setattr("helper.logger.LOG_DIR", tmp_path)
    name = "test_logger_factory_missing"
    logger = logging.getLogger(name)

    try:
        LoggerFactory.get_logger("fresh.log", name)
        assert len(_file_handlers(logger)) == 1
    finally:
        _clear_logger(logger)


def test_service_loggers_do_not_write_to_production_log_dir() -> None:
    """Regression: the test suite must not append to the live log files.

    conftest redirects ``MOONWALKER_LOG_DIR`` to a throwaway directory before any
    service module is imported. If that redirect is ever removed, ``LOG_DIR`` falls
    back to the anchored production directory and the suite pollutes live logs.
    """
    import helper.logger

    prod_dir = Path(helper.logger.__file__).resolve().parents[2] / "backend" / "logs"
    assert helper.logger.LOG_DIR != prod_dir, (
        "test suite is writing to the production log directory"
    )
    assert os.environ.get("MOONWALKER_LOG_DIR", "").strip() == str(
        helper.logger.LOG_DIR
    )
