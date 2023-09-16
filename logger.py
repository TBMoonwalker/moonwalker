import logging, logging.handlers
import os


class Logger(logging.Logger):
    def __init__(self, name, log_file="moonwalker.log", log_level=logging.DEBUG):
        super().__init__(name, log_level)
        self.log_file = log_file
        self._create_logger()

    def _create_logger(self):
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

        file_handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=200000,
            backupCount=5,
        )

        if os.name == "nt":
            file_handler = logging.FileHandler(self.log.file)

        file_handler.setLevel(self.level)
        file_handler.setFormatter(formatter)

        self.addHandler(file_handler)

    def log(self, level, msg, *args, **kwargs):
        if self.isEnabledFor(level):
            self._log(level, msg, args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.log(logging.CRITICAL, msg, *args, **kwargs)
