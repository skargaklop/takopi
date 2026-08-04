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


def test_parse_compact_invocation_none_cases() -> None:
    """Non-compact or non-leading-slash texts return None."""
    from takopi.telegram.commands.parse import parse_compact_invocation

    engine_ids: tuple[str, ...] = ("codex", "claude")
    for text in ("", "hello", "/codex fix bug", "/new", "keep /compact"):
        assert parse_compact_invocation(text, engine_ids=engine_ids) is None


def test_parse_compact_invocation_bare() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions is None

    inv2 = parse_compact_invocation("/compact@mybot", engine_ids=("codex",))
    assert inv2 is not None
    assert inv2.engine is None
    assert inv2.instructions is None


def test_parse_compact_invocation_with_instructions() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact keep tests", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "keep tests"


def test_parse_compact_invocation_compact_then_engine() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact /codex", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine == "codex"
    assert inv.instructions is None

    inv2 = parse_compact_invocation("/compact /codex keep tests", engine_ids=("codex",))
    assert inv2 is not None
    assert inv2.engine == "codex"
    assert inv2.instructions == "keep tests"


def test_parse_compact_invocation_engine_then_compact() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/codex /compact", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine == "codex"
    assert inv.instructions is None

    inv2 = parse_compact_invocation("/codex /compact keep tests", engine_ids=("codex",))
    assert inv2 is not None
    assert inv2.engine == "codex"
    assert inv2.instructions == "keep tests"


def test_parse_compact_invocation_engine_with_bot_suffix() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/codex@mybot /compact", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine == "codex"
    assert inv.instructions is None


def test_parse_compact_invocation_unknown_slash_stops_scanning() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact /plan", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "/plan"


def test_parse_compact_invocation_multiple_engines_raises() -> None:
    import pytest

    from takopi.telegram.commands.parse import parse_compact_invocation

    with pytest.raises(ValueError, match="multiple engine"):
        parse_compact_invocation(
            "/codex /claude /compact", engine_ids=("codex", "claude")
        )


def test_parse_compact_invocation_multiline() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact\nkeep tests", engine_ids=("codex",))
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "keep tests"

    inv2 = parse_compact_invocation(
        "/codex /compact\nline1\nline2", engine_ids=("codex",)
    )
    assert inv2 is not None
    assert inv2.engine == "codex"
    assert inv2.instructions == "line1\nline2"
