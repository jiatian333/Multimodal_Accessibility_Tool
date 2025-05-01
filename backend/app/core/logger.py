"""
Global Logging Configuration with Optional Point Context Support

This module configures consistent logging for the application, including:
- Console output (INFO+)
- Rotating file output (DEBUG+)
- Per-point contextual logging using `contextvars`

Responsibilities:
-----------------
- Configures unified logging with timestamps, levels and the name of the function
- Optionally includes `[POINT:x,y]` tags in logs during
  parallelized travel-time computations
- Ensures logs remain structured even when no point is set

Usage:
------
1. Call `setup_logging()` in your application entry point.

    from app.core.logger import setup_logging
    setup_logging()

2. In async point-processing functions, call `set_point_context(...)` to enable context:

    from app.core.logger import set_point_context
    set_point_context(point)

This will prefix all log messages with the current point during processing.

Example:
    2025-04-28 14:00:10 [INFO] [app.utils.request_processing] [POINT:8.5441,47.3763] Travel time = 12 min
"""

import logging
import logging.handlers
import contextvars
from shapely.geometry import Point
from app.core.config import LOG_FILE

_log_point = contextvars.ContextVar("log_point", default="-")


def set_point_context(point: Point) -> None:
    """
    Sets the logging context for the current point.

    This is used during parallel processing to attach point-specific
    identifiers (coordinates) to log messages.

    Args:
        point (Point): A shapely Point used as the identifier.
    """
    _log_point.set(f"{point.x:.4f},{point.y:.4f}")

def get_point_context() -> str:
    """
    Retrieves the currently set point identifier for logging.

    Returns:
        str: The currently active point context or "-" if not set.
    """
    return _log_point.get()


class ContextFilter(logging.Filter):
    """
    Logging filter that injects the current point context into each log record.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        point = get_point_context()
        record.point = f"[POINT:{point}]" if point != "-" else ""
        return True
    
class SafeFormatter(logging.Formatter):
    """
    Custom formatter that avoids crashing on missing fields.

    Fallbacks are provided for any optional log record attributes.
    """
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "point"):
            record.point = ""
        if not hasattr(record, "name"):
            record.name = "-"
        return super().format(record)


def setup_logging(
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5
) -> None:
    """
    Configures application-wide logging with console and rotating file output.

    Both loggers will include `[POINT:x,y]` if `set_point_context(...)`
    has been called in the current execution context.

    Args:
        console_level (int): Logging level for console (default: INFO).
        file_level (int): Logging level for file output (default: DEBUG).
        max_bytes (int): Max size in bytes before file rotation.
        backup_count (int): Number of backup files to keep.
    """
    formatter = SafeFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(point)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(ContextFilter())

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, mode="w", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(ContextFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers = [console_handler, file_handler]