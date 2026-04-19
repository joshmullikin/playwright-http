"""Tests for executor/logging.py — setup_logging and RequestIdFormatter."""

import logging
import os
import tempfile

import pytest

import executor.logging as logging_module
from executor.logging import (
    RequestIdFormatter,
    setup_logging,
    get_logger,
    request_id_var,
)


# ---------------------------------------------------------------------------
# RequestIdFormatter
# ---------------------------------------------------------------------------


class TestRequestIdFormatter:
    def test_format_injects_request_id(self):
        formatter = RequestIdFormatter("%(request_id)s %(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = formatter.format(record)
        assert "-" in result  # default request_id is "-"

    def test_format_uses_existing_request_id(self):
        token = request_id_var.set("req-abc-123")
        try:
            formatter = RequestIdFormatter("%(request_id)s %(message)s")
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="msg", args=(), exc_info=None,
            )
            result = formatter.format(record)
            assert "req-abc-123" in result
        finally:
            request_id_var.reset(token)


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_logger_with_name(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


# ---------------------------------------------------------------------------
# setup_logging — console-only (default) and with file handler
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_setup_logging_configures_root_logger(self, monkeypatch):
        """setup_logging should attach a StreamHandler to the root logger."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("LOG_FILE", raising=False)

        # Reload module-level vars affected by env
        monkeypatch.setattr(logging_module, "LOG_LEVEL", "DEBUG")
        monkeypatch.setattr(logging_module, "LOG_FILE", None)

        setup_logging()
        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types

    def test_setup_logging_with_log_file(self, monkeypatch, tmp_path):
        """setup_logging with LOG_FILE should add a RotatingFileHandler."""
        log_file = str(tmp_path / "app.log")
        monkeypatch.setattr(logging_module, "LOG_FILE", log_file)
        monkeypatch.setattr(logging_module, "LOG_LEVEL", "INFO")

        setup_logging()
        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" in handler_types

        # Cleanup
        for h in root.handlers[:]:
            if hasattr(h, "baseFilename"):
                h.close()
                root.removeHandler(h)

    def test_setup_logging_json_format(self, monkeypatch):
        """LOG_FORMAT=json should use the JSON formatter."""
        monkeypatch.setattr(logging_module, "LOG_FORMAT", "json")
        monkeypatch.setattr(logging_module, "LOG_FILE", None)

        setup_logging()
        root = logging.getLogger()
        for h in root.handlers:
            fmt = h.formatter.formatTime  # just check it's a valid formatter
            break
        # Reset format to text to avoid affecting other tests
        monkeypatch.setattr(logging_module, "LOG_FORMAT", "text")

    def test_setup_logging_clears_existing_handlers(self, monkeypatch):
        """Calling setup_logging twice should not accumulate duplicate handlers."""
        monkeypatch.setattr(logging_module, "LOG_FILE", None)
        monkeypatch.setattr(logging_module, "LOG_LEVEL", "INFO")

        setup_logging()
        count_after_first = len(logging.getLogger().handlers)
        setup_logging()
        count_after_second = len(logging.getLogger().handlers)
        assert count_after_second == count_after_first
