import logging, logging.handlers
import os


class LoggerFactory(object):
    _LOG = None

    @staticmethod
    def __create_logger(log_file, name, log_level):
        """
        A private method that interacts with the python
        logging module
        """
        # set the logging format
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

        # set the logging level based on the user selection
        if log_level == "INFO":
            LoggerFactory._LOG.setLevel(logging.INFO)
        elif log_level == "ERROR":
            LoggerFactory._LOG.setLevel(logging.ERROR)
        elif log_level == "DEBUG":
            LoggerFactory._LOG.setLevel(logging.DEBUG)
        return LoggerFactory._LOG

    @staticmethod
    def get_logger(log_file, name, log_level):
        """
        A static method called by other modules to initialize logger in
        their own module
        """
        logger = LoggerFactory.__create_logger(log_file, name, log_level)

        # return the logger object
        return logger
