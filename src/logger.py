import logging
import os

_configured = False


def setup_logging(name: str = "TelegramBot") -> logging.Logger:
    """
    Setup the logging configuration.
    """
    global _configured
    debug = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
    target_level = logging.DEBUG if debug else logging.INFO

    if not _configured:
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            level=target_level,
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        logging.getLogger().setLevel(target_level)
        for noisy_logger in (
            "matplotlib",
            "matplotlib.font_manager",
            "urllib3",
            "scrapling",
            "httpx",
            "httpcore",
        ):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)
        _configured = True

    logger = logging.getLogger(name)
    logger.setLevel(target_level)
    return logger