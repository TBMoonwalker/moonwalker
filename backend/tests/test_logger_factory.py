"""Tests for logger factory behavior."""

from pathlib import Path

from helper.logger import LoggerFactory


def test_get_logger_creates_parent_log_directory(tmp_path: Path) -> None:
    log_file = tmp_path / "nested" / "logs" / "config.log"
    logger = LoggerFactory.get_logger(str(log_file), "test_logger_factory_create_dir")

    logger.info("hello")

    assert log_file.parent.is_dir()
    assert log_file.is_file()

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
