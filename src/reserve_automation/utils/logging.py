"""Logging configuration for The Reserve Automation using loguru."""

import sys
from pathlib import Path

from loguru import logger


def setup_logging(config: dict, verbose: bool = False) -> None:
    """
    Configure logging based on config settings.

    Args:
        config: Configuration dictionary with logging settings
        verbose: If True, override level to DEBUG
    """
    logging_config = config.get("logging", {})

    # Determine log level
    level_str = "DEBUG" if verbose else logging_config.get("level", "INFO")

    # Remove default handler
    logger.remove()

    # Console handler
    if logging_config.get("console", True):
        logger.add(
            sys.stdout,
            level=level_str,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            colorize=True,
        )

    # File handler
    if logging_config.get("file_logging", True):
        log_file = logging_config.get("file", "logs/automation.log")
        log_path = Path(log_file)

        # Create logs directory if it doesn't exist
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_path,
            level=level_str,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="10 MB",  # Rotate when file reaches 10MB
            retention="1 week",  # Keep logs for 1 week
            compression="zip",  # Compress rotated logs
        )

    # Reduce noise from third-party libraries by patching their loggers
    # Loguru doesn't intercept standard logging by default, but we can if needed
    intercept_standard_logging()


def intercept_standard_logging():
    """
    Intercept standard library logging and redirect to loguru.

    This catches logs from third-party libraries using standard logging.
    """
    import logging

    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # Get corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where originated the logged message
            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    # Intercept standard logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Reduce noise from specific libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


# Export logger for easy import
__all__ = ["logger", "setup_logging"]
