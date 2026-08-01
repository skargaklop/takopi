"""Tests for takopi.logging path resolution and file sink setup."""

from __future__ import annotations

from pathlib import Path

import pytest

from takopi import logging as takopi_logging


def test_resolve_relative_log_file(tmp_path: Path) -> None:
    """A relative log file path resolves under the takopi home config dir."""
    monkey_home = tmp_path / ".takopi"
    monkey_home.mkdir()
    original = takopi_logging._TAKOPI_HOME_DIR
    takopi_logging._TAKOPI_HOME_DIR = monkey_home
    try:
        resolved = takopi_logging._resolve_log_file_path("takopi.log")
        assert resolved == monkey_home / "takopi.log"
    finally:
        takopi_logging._TAKOPI_HOME_DIR = original


def test_resolve_absolute_log_file(tmp_path: Path) -> None:
    """An absolute log file path is returned unchanged."""
    absolute = tmp_path / "custom.log"
    resolved = takopi_logging._resolve_log_file_path(str(absolute))
    assert resolved == absolute


def test_setup_logging_writes_to_takopi_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """setup_logging with a relative file creates the log under ~/.takopi/."""
    monkey_home = tmp_path / ".takopi"
    monkey_home.mkdir()
    monkeypatch.setattr(takopi_logging, "_TAKOPI_HOME_DIR", monkey_home)

    original_handle = takopi_logging._log_file_handle
    try:
        takopi_logging.setup_logging(file="test_relative.log", level="info")
        log_path = monkey_home / "test_relative.log"
        assert log_path.exists()

        logger = takopi_logging.get_logger("test_logger")
        logger.info("test.event", field="value")
        if takopi_logging._log_file_handle is not None:
            takopi_logging._log_file_handle.flush()
        content = log_path.read_text(encoding="utf-8")
        assert "test.event" in content
    finally:
        if takopi_logging._log_file_handle is not None:
            takopi_logging._log_file_handle.close()
            takopi_logging._log_file_handle = None
        takopi_logging._log_file_handle = original_handle
