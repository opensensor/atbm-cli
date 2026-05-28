"""Logging infrastructure — structured logging with JSON output support."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """JSON log formatter for machine-readable output."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as JSON.

        Args:
            record: Log record to format.

        Returns:
            JSON-formatted log line.
        """
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data

        return json.dumps(log_entry)


class StructuredLogger:
    """Wrapper around Python logging with convenience methods."""

    def __init__(
        self,
        name: str = "atbm6441-cli",
        level: str = "info",
        json_output: bool = False,
    ) -> None:
        """Initialize the structured logger.

        Args:
            name: Logger name.
            level: Log level string (debug, info, warn, error).
            json_output: Whether to emit JSON-formatted logs.
        """
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

        # Remove existing handlers to avoid duplicates
        self._logger.handlers.clear()

        # Create handler
        handler = logging.StreamHandler(sys.stderr)

        if json_output:
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            ))

        self._logger.addHandler(handler)
        self._json_output = json_output

    @property
    def logger(self) -> logging.Logger:
        """Access the underlying logging.Logger."""
        return self._logger

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a debug message."""
        if kwargs:
            msg = f"{message} | {kwargs}"
        else:
            msg = message
        self._logger.debug(msg)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message."""
        if kwargs:
            msg = f"{message} | {kwargs}"
        else:
            msg = message
        self._logger.info(msg)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message."""
        if kwargs:
            msg = f"{message} | {kwargs}"
        else:
            msg = message
        self._logger.warning(msg)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message."""
        if kwargs:
            msg = f"{message} | {kwargs}"
        else:
            msg = message
        self._logger.error(msg)

    def exception(self, message: str, **kwargs: Any) -> None:
        """Log an exception with traceback."""
        if kwargs:
            msg = f"{message} | {kwargs}"
        else:
            msg = message
        self._logger.exception(msg)

    def set_level(self, level: str) -> None:
        """Change the log level.

        Args:
            level: Log level string (debug, info, warn, error).
        """
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    def enable_json(self) -> None:
        """Enable JSON output mode."""
        for handler in self._logger.handlers:
            handler.setFormatter(JsonFormatter())
        self._json_output = True

    def disable_json(self) -> None:
        """Disable JSON output mode."""
        for handler in self._logger.handlers:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            ))
        self._json_output = False


def setup_logging(
    level: str = "info",
    json_output: bool = False,
    logger_name: str = "atbm6441-cli",
) -> StructuredLogger:
    """Set up logging with the specified configuration.

    Args:
        level: Log level (debug, info, warn, error).
        json_output: Whether to emit JSON-formatted logs.
        logger_name: Logger name.

    Returns:
        Configured StructuredLogger instance.
    """
    return StructuredLogger(
        name=logger_name,
        level=level,
        json_output=json_output,
    )
