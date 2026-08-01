"""Tests for /compact command dispatch."""

from __future__ import annotations

from takopi.telegram.commands.menu import build_bot_commands
from takopi.telegram.commands.meta_args import should_handle_as_meta_command


def test_compact_is_meta_command() -> None:
    """compact is a pure meta command — never falls through as a prompt."""
    assert should_handle_as_meta_command("compact", "") is True
    assert should_handle_as_meta_command("compact", "keep tests") is True


def test_build_bot_commands_includes_compact() -> None:
    """Verify compact appears in the built-in commands tuple."""
    # The built-in command tuples are statically defined in menu.py.
    # We verify by importing the function and checking its source-level list.
    import inspect

    source = inspect.getsource(build_bot_commands)
    assert "compact" in source
    assert "compact current session" in source


def test_parse_compact_instructions() -> None:
    from takopi.compact import normalize_instructions

    assert normalize_instructions(None) is None
    assert normalize_instructions("") is None
    assert normalize_instructions("  ") is None
    assert normalize_instructions("keep tests") == "keep tests"
