"""Tests for /handoff command parsing and registration."""

from __future__ import annotations

from takopi.telegram.commands.menu import build_bot_commands
from takopi.telegram.commands.meta_args import should_handle_as_meta_command
from takopi.telegram.prompt_batch import (
    CONTROL_COMMANDS,
    PromptBatchSettings,
    should_batch_text,
)


def test_handoff_is_meta_command() -> None:
    """handoff is a pure meta command — never falls through as a prompt."""
    assert should_handle_as_meta_command("handoff", "") is True
    assert should_handle_as_meta_command("handoff", "keep tests") is True


def test_build_bot_commands_includes_handoff() -> None:
    import inspect

    source = inspect.getsource(build_bot_commands)
    assert "handoff" in source
    assert "new session with handoff summary" in source


def test_handoff_in_control_commands() -> None:
    assert "handoff" in CONTROL_COMMANDS


def test_handoff_not_batched() -> None:
    settings = PromptBatchSettings(enabled=True)
    assert should_batch_text("/handoff", settings=settings) is False
    assert should_batch_text("/handoff keep tests", settings=settings) is False


# ---------------------------------------------------------------------------
# Parser matrix
# ---------------------------------------------------------------------------

_EIDS: tuple[str, ...] = ("codex", "claude")


def test_handoff_bare() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions is None

    inv2 = parse_handoff_invocation("/handoff@mybot", engine_ids=_EIDS)
    assert inv2 is not None
    assert inv2.engine is None
    assert inv2.instructions is None


def test_handoff_with_instructions() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff keep tests", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "keep tests"


def test_handoff_engine_then_handoff() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/codex /handoff", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine == "codex"
    assert inv.instructions is None

    inv2 = parse_handoff_invocation("/codex /handoff keep tests", engine_ids=_EIDS)
    assert inv2 is not None
    assert inv2.engine == "codex"
    assert inv2.instructions == "keep tests"


def test_handoff_then_engine() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff /codex", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine == "codex"
    assert inv.instructions is None

    inv2 = parse_handoff_invocation("/handoff /codex keep tests", engine_ids=_EIDS)
    assert inv2 is not None
    assert inv2.engine == "codex"
    assert inv2.instructions == "keep tests"


def test_handoff_engine_with_bot_suffix() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff /codex@mybot", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine == "codex"
    assert inv.instructions is None


def test_handoff_unknown_slash_stops_scanning() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff /plan", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "/plan"


def test_handoff_none_cases() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    for text in ("", "hello", "/codex fix bug", "/new", "keep /handoff"):
        assert parse_handoff_invocation(text, engine_ids=_EIDS) is None


def test_handoff_multiline() -> None:
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff keep\nline1\nline2", engine_ids=_EIDS)
    assert inv is not None
    # First-line token "keep" space-joined with tail "line1\nline2".
    assert inv.instructions == "keep line1\nline2"

    inv2 = parse_handoff_invocation("/handoff\nline1\nline2", engine_ids=_EIDS)
    assert inv2 is not None
    assert inv2.instructions == "line1\nline2"


def test_handoff_multiple_engines_raises() -> None:
    import pytest

    from takopi.telegram.commands.parse import parse_handoff_invocation

    with pytest.raises(ValueError):
        parse_handoff_invocation("/handoff /codex /claude", engine_ids=_EIDS)


def test_handoff_then_compact_becomes_instructions() -> None:
    """Pathological combo: /handoff /compact -> handoff with instructions '/compact'."""
    from takopi.telegram.commands.parse import parse_handoff_invocation

    inv = parse_handoff_invocation("/handoff /compact", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "/compact"


def test_compact_then_handoff_becomes_instructions() -> None:
    """Pathological combo: /compact /handoff -> compact with instructions '/handoff'."""
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact /handoff", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions == "/handoff"


# ---------------------------------------------------------------------------
# Regression: compact parser matrix unchanged through shared implementation
# ---------------------------------------------------------------------------


def test_compact_matrix_regression_bare() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/compact@mybot", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine is None
    assert inv.instructions is None


def test_compact_matrix_regression_engine_first() -> None:
    from takopi.telegram.commands.parse import parse_compact_invocation

    inv = parse_compact_invocation("/claude /compact keep tests", engine_ids=_EIDS)
    assert inv is not None
    assert inv.engine == "claude"
    assert inv.instructions == "keep tests"
