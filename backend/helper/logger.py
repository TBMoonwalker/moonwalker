"""Logging factory with support for TRACE level and rotating files.

All service log files live under a single, CWD-independent directory so the
writer and the monitoring log viewer always agree, regardless of where the
process was launched from. The directory is anchored to the repository root by
default and can be overridden with the ``MOONWALKER_LOG_DIR`` environment
variable.
"""

import logging
import logging.handlers
import os
from pathlib import Path

TRACE_LEVEL_NUM = 5


def _resolve_log_dir() -> Path:
    """Return the absolute directory that holds all service log files.

    Resolution order:

    1. ``MOONWALKER_LOG_DIR`` when set and non-empty.
    2. ``<repo_root>/logs`` (three levels up from this module:
       ``backend/helper/logger.py`` -> repo root).

    Args:
        None.

    Returns:
        An absolute ``Path`` for the log directory.
    """
    configured = os.getenv("MOONWALKER_LOG_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "backend" / "logs"


LOG_DIR = _resolve_log_dir()


def _canonical_log_file(path: str | Path) -> str:
    """Return the canonical (symlink-resolved, absolute) form of a log path.

    ``FileHandler.baseFilename`` is produced by ``os.path.abspath`` (lexical
    normalization, no symlink resolution), so two handlers that target the same
    file can carry different ``baseFilename`` strings whenever a path component
    is a symlink (e.g. macOS ``/var`` -> ``/private/var``) or an absolute path
    is not normalized. Canonicalizing both sides of a handler comparison with
    ``os.path.realpath`` makes de-duplication robust to such uncanonical
    spellings.

    Args:
        path: A log file path, as a string or ``Path``.

    Returns:
        The canonical absolute form of the path.
    """
    return os.path.realpath(os.fspath(path))


def _resolve_log_path(log_file: str | Path) -> Path:
    """Resolve a caller-supplied log file name to a canonical path.

    The returned path is absolute, normalized, and symlink-resolved so the
    handler's ``baseFilename`` and the de-duplication comparison agree even
    when ``LOG_DIR`` (or the supplied path) is not canonical - for example a
    directory behind a symlink.

    Historical call sites pass names like ``"logs/startup.log"``. Because the
    location is now anchored, only the file name is retained and joined onto the
    directory; absolute paths are used as given and then canonicalized.

    Args:
        log_file: A relative log file name or an absolute path.

    Returns:
        The fully resolved absolute ``Path`` for the log file.
    """
    path = Path(log_file)
    candidate = path if path.is_absolute() else LOG_DIR / path.name
    return candidate.resolve()


def _register_trace_level() -> None:
    """Register TRACE logging level and logger.trace() helper."""
    if hasattr(logging, "TRACE"):
        return

    logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
    logging.TRACE = TRACE_LEVEL_NUM  # type: ignore[attr-defined]

    def trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
        if self.isEnabledFor(TRACE_LEVEL_NUM):
            self._log(TRACE_LEVEL_NUM, message, args, **kwargs)

    logging.Logger.trace = trace  # type: ignore[attr-defined]


_register_trace_level()


class LoggerFactory:
    """Factory class for creating and managing logger instances.

    Provides a singleton pattern for logger creation with support for
    rotating log files and environment-based log level configuration.
    """

    @staticmethod
    def __resolve_loglevel() -> str:
        """Resolve active log level from environment variables."""
        configured = os.getenv("MOONWALKER_LOG_LEVEL", "").strip().upper()
        if configured in {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return configured

        debug = os.getenv("MOONWALKER_DEBUG")
        if debug:
            return "DEBUG"
        return "INFO"

    @staticmethod
    def __create_logger(log_file: str, name: str) -> logging.Logger:
        """Create a logger instance with file handler and appropriate formatting.

        A private method that interacts with the Python logging module to create
        configured loggers with rotating file handlers. A file handler is only
        attached when the logger does not already own one for the same canonical
        log file, so repeated ``get_logger`` calls never double-attach handlers
        even when the log directory is not a canonical path.

        Args:
            log_file: Path to the log file
            name: Name for the logger instance

        Returns:
            Configured logging.Logger instance

        Raises:
            Exception: If logger creation fails
        """
        loglevel = LoggerFactory.__resolve_loglevel()
        logger = logging.getLogger(name)
        resolved = _resolve_log_path(log_file)
        log_dir = resolved.parent
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)

        # De-duplicate by canonical form: FileHandler.baseFilename is
        # os.path.abspath (no symlink resolution), so compare both sides with
        # realpath to stay correct when the log dir sits behind a symlink.
        target = _canonical_log_file(resolved)
        existing_handler = next(
            (
                handler
                for handler in logger.handlers
                if isinstance(handler, logging.FileHandler)
                and _canonical_log_file(handler.baseFilename) == target
            ),
            None,
        )
        if existing_handler is None:
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s : %(message)s"
            )
            # Windows has a problem with the RotatingFileHandler - so only one file
            if os.name == "nt":
                file_handler = logging.FileHandler(str(resolved))
            else:
                file_handler = logging.handlers.RotatingFileHandler(
                    str(resolved),
                    maxBytes=5000000,
                    backupCount=5,
                )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        # Set the logging level based on the user selection
        if loglevel == "TRACE":
            logger.setLevel(TRACE_LEVEL_NUM)
        elif loglevel == "DEBUG":
            logger.setLevel(logging.DEBUG)
        elif loglevel == "INFO":
            logger.setLevel(logging.INFO)
        elif loglevel == "WARNING":
            logger.setLevel(logging.WARNING)
        elif loglevel == "ERROR":
            logger.setLevel(logging.ERROR)
        elif loglevel == "CRITICAL":
            logger.setLevel(logging.CRITICAL)

        # Keep service logs in their dedicated files instead of bubbling
        # into the root/uvicorn stderr handlers captured by run.log.
        logger.propagate = False
        return logger

    @staticmethod
    def get_logger(log_file: str, name: str) -> logging.Logger:
        """Get a logger instance for the specified module.

        A static method called by other modules to initialize logger in
        their own module. Uses singleton pattern to reuse logger instances.

        Args:
            log_file: Path to the log file
            name: Name for the logger instance

        Returns:
            Configured logging.Logger instance
        """
        logger = LoggerFactory.__create_logger(log_file, name)

        # Return the logger object
        return logger
