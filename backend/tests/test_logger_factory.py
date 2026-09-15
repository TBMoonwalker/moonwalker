"""Tests for logger factory behavior."""

import os
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
