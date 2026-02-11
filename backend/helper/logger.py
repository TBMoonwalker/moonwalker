import logging
import logging.handlers
import os

TRACE_LEVEL_NUM = 5


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

    _LOG = None

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
        configured loggers with rotating file handlers.

        Args:
            log_file: Path to the log file
            name: Name for the logger instance

        Returns:
            Configured logging.Logger instance

        Raises:
            Exception: If logger creation fails
        """
        loglevel = LoggerFactory.__resolve_loglevel()

        # Set the logging format
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s : %(message)s"
        )

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5000000,
            backupCount=5,
        )

        # Windows has a problem with the RotatingFileHandler - so only one file
        if os.name == "nt":
            file_handler = logging.FileHandler(log_file)

        # Initialize the class variable with logger object
        LoggerFactory._LOG = logging.getLogger(name)
        file_handler.setFormatter(formatter)
        LoggerFactory._LOG.addHandler(file_handler)

        # Set the logging level based on the user selection
        if loglevel == "TRACE":
            LoggerFactory._LOG.setLevel(TRACE_LEVEL_NUM)
        elif loglevel == "DEBUG":
            LoggerFactory._LOG.setLevel(logging.DEBUG)
        elif loglevel == "INFO":
            LoggerFactory._LOG.setLevel(logging.INFO)
        elif loglevel == "WARNING":
            LoggerFactory._LOG.setLevel(logging.WARNING)
        elif loglevel == "ERROR":
            LoggerFactory._LOG.setLevel(logging.ERROR)
        elif loglevel == "CRITICAL":
            LoggerFactory._LOG.setLevel(logging.CRITICAL)
        return LoggerFactory._LOG

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
