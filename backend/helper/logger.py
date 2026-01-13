import logging, logging.handlers
import os


class LoggerFactory(object):
    _LOG = None

    @staticmethod
    def __create_logger(log_file, name):
        """
        A private method that interacts with the python
        logging module
        """
        debug = None
        try:
            debug = os.environ["MOONWALKER_DEBUG"]
        except:
            pass

        if debug:
            loglevel="DEBUG"
        else:
            loglevel="INFO"
        
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
        if loglevel == "INFO":
            LoggerFactory._LOG.setLevel(logging.INFO)
        elif loglevel == "ERROR":
            LoggerFactory._LOG.setLevel(logging.ERROR)
        elif loglevel == "DEBUG":
            LoggerFactory._LOG.setLevel(logging.DEBUG)
        return LoggerFactory._LOG

    @staticmethod
    def get_logger(log_file, name):
        """
        A static method called by other modules to initialize logger in
        their own module
        """
        logger = LoggerFactory.__create_logger(log_file, name)

        # return the logger object
        return logger
