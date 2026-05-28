"""Tests for logging infrastructure (F4)."""

from __future__ import annotations

import io
import json
import logging
import sys
from unittest.mock import patch

import pytest

from atbm6441_cli.utils.logging import JsonFormatter, StructuredLogger, setup_logging


class TestJsonFormatter:
    """Tests for JsonFormatter."""

    def test_format_basic(self):
        """Test basic JSON formatting."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert data["message"] == "Hello world"
        assert "timestamp" in data

    def test_format_with_exception(self):
        """Test JSON formatting with exception info."""
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_format_with_extra_data(self):
        """Test JSON formatting with extra data."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Request",
            args=(),
            exc_info=None,
        )
        record.extra_data = {"url": "http://example.com", "method": "GET"}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["data"]["url"] == "http://example.com"
        assert data["data"]["method"] == "GET"


class TestStructuredLogger:
    """Tests for StructuredLogger."""

    def test_init_default(self):
        """Test initialization with defaults."""
        logger = StructuredLogger()
        assert logger._logger.name == "atbm6441-cli"
        assert logger._logger.level == logging.INFO

    def test_init_custom_level(self):
        """Test initialization with custom log level."""
        logger = StructuredLogger(level="debug")
        assert logger._logger.level == logging.DEBUG

    def test_init_json_output(self):
        """Test initialization with JSON output."""
        logger = StructuredLogger(json_output=True)
        assert logger._json_output is True
        for handler in logger._logger.handlers:
            assert isinstance(handler.formatter, JsonFormatter)

    def test_debug(self, capsys):
        """Test debug logging."""
        logger = StructuredLogger(level="debug")
        logger.debug("Debug message")
        captured = capsys.readouterr()
        assert "Debug message" in captured.err

    def test_info(self, capsys):
        """Test info logging."""
        logger = StructuredLogger(level="info")
        logger.info("Info message")
        captured = capsys.readouterr()
        assert "Info message" in captured.err

    def test_warning(self, capsys):
        """Test warning logging."""
        logger = StructuredLogger(level="info")
        logger.warning("Warning message")
        captured = capsys.readouterr()
        assert "Warning message" in captured.err

    def test_error(self, capsys):
        """Test error logging."""
        logger = StructuredLogger(level="info")
        logger.error("Error message")
        captured = capsys.readouterr()
        assert "Error message" in captured.err

    def test_debug_filtered_at_info_level(self, capsys):
        """Test debug messages are filtered at info level."""
        logger = StructuredLogger(level="info")
        logger.debug("Debug message")
        captured = capsys.readouterr()
        assert "Debug message" not in captured.err

    def test_set_level(self, capsys):
        """Test changing log level dynamically."""
        logger = StructuredLogger(level="info")
        logger.debug("Should not appear")
        captured = capsys.readouterr()
        assert "Should not appear" not in captured.err

        logger.set_level("debug")
        logger.debug("Should appear")
        captured = capsys.readouterr()
        assert "Should appear" in captured.err

    def test_enable_json(self, capsys):
        """Test enabling JSON output."""
        logger = StructuredLogger(level="info", json_output=False)
        logger.enable_json()
        logger.info("JSON message")
        captured = capsys.readouterr()
        data = json.loads(captured.err.strip())
        assert data["message"] == "JSON message"

    def test_disable_json(self, capsys):
        """Test disabling JSON output."""
        logger = StructuredLogger(level="info", json_output=True)
        logger.disable_json()
        logger.info("Text message")
        captured = capsys.readouterr()
        assert "Text message" in captured.err
        # Should not be valid JSON (or if it is, shouldn't have the message in data["message"])
        try:
            data = json.loads(captured.err.strip())
            assert data.get("message") != "Text message"
        except json.JSONDecodeError:
            pass  # Expected — plain text is not valid JSON

    def test_logger_property(self):
        """Test accessing underlying Logger."""
        logger = StructuredLogger()
        assert isinstance(logger.logger, logging.Logger)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_default(self):
        """Test setup_logging with defaults."""
        logger = setup_logging()
        assert isinstance(logger, StructuredLogger)
        assert logger._logger.name == "atbm6441-cli"

    def test_setup_logging_custom(self):
        """Test setup_logging with custom parameters."""
        logger = setup_logging(level="debug", json_output=True, logger_name="custom")
        assert logger._logger.name == "custom"
        assert logger._logger.level == logging.DEBUG
        assert logger._json_output is True
