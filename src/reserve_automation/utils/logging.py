"""Logging configuration for The Reserve Automation."""

import logging
import sys
from pathlib import Path
from typing import Optional


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
    level = getattr(logging, level_str.upper(), logging.INFO)

    # Create formatters
    log_format = logging_config.get(
        "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    formatter = logging.Formatter(log_format)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    if logging_config.get("console", True):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler
    if logging_config.get("file_logging", True):
        log_file = logging_config.get("file", "logs/automation.log")
        log_path = Path(log_file)

        # Create logs directory if it doesn't exist
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module."""
    return logging.getLogger(name)
