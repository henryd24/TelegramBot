import logging
import os
def setup_logging() -> logging.Logger:
    """
    Setup the logging configuration.
    """
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
    if DEBUG:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    return logger