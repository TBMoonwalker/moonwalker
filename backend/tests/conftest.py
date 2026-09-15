import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# The service loggers are created at module-import time, pointing at the
# anchored production log directory. Redirect that directory to a throwaway
# location before any service module is imported so the test suite never
# appends ERROR/Traceback records to the live logs.
_LOG_TMP = Path(tempfile.mkdtemp(prefix="moonwalker-test-logs-"))
os.environ["MOONWALKER_LOG_DIR"] = str(_LOG_TMP)

import helper.logger as _logger_module  # noqa: E402

_logger_module.LOG_DIR = _LOG_TMP


def _close_temp_log_handlers(log_dir: Path) -> None:
    """Close file handlers that write under ``log_dir``.

    Service loggers were created at import time with handlers anchored to the
    redirected log directory. Their ``FileHandler`` objects keep the files open,
    which blocks removal on Windows, so they must be closed before the directory
    is deleted.
    """
    for logger in logging.Logger.manager.loggerDict.values():
        if not isinstance(logger, logging.Logger):
            continue
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", None)
            if isinstance(base, str) and str(Path(base).resolve()).startswith(
                str(log_dir)
            ):
                handler.close()
                logger.removeHandler(handler)


@pytest.fixture(scope="session", autouse=True)
def _clean_up_temp_log_dir():
    """Discard the throwaway log directory after the test session.

    Every pytest run creates its own ``moonwalker-test-logs-*`` directory; remove
    it on teardown so a long-running workstation does not accumulate temp dirs.
    """
    yield
    _close_temp_log_handlers(_LOG_TMP)
    shutil.rmtree(_LOG_TMP, ignore_errors=True)
