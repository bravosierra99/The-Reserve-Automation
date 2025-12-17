"""Logging configuration for web server using loguru."""

import sys
from pathlib import Path

from loguru import logger


def setup_web_logging(
    log_dir: Path = None,
    log_level: str = "INFO",
    rotation: str = "10 MB",
    retention: int = 5,
    compression: str = "zip"
):
    """
    Set up logging for the web server using loguru.

    Args:
        log_dir: Directory for log files (defaults to logs/ in project root)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        rotation: When to rotate log file (e.g., "10 MB", "1 day", "1 week")
        retention: Number of rotated files to keep
        compression: Compression format for rotated files ("zip", "gz", etc.)

    Returns:
        Path to the log file
    """
    # Default log directory
    if log_dir is None:
        log_dir = Path(__file__).parent.parent.parent.parent / "logs"

    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "web_server.log"

    # Remove default handler
    logger.remove()

    # Add console handler with colored output
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # Add file handler with rotation
    logger.add(
        log_file,
        level="DEBUG",  # File gets everything
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        compression=compression,
        enqueue=True,  # Thread-safe
    )

    # Log startup message
    logger.info("=" * 80)
    logger.info("Web server logging initialized")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Log level: {log_level}")
    logger.info(f"Rotation: {rotation}, Retention: {retention} files")
    logger.info("=" * 80)

    return log_file


def get_log_file_path() -> Path:
    """Get the path to the current log file."""
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    return log_dir / "web_server.log"
