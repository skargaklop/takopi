from __future__ import annotations

from takopi.compact import (
    COMPACT_NONE,
    CompactSupport,
    compact_prompt,
    get_compact_support,
    handoff_prompt,
    normalize_instructions,
    warn_if_dropping_instructions,
)


def test_normalize_instructions_strips_and_nones() -> None:
    assert normalize_instructions(None) is None
    assert normalize_instructions("") is None
    assert normalize_instructions("  ") is None
    assert normalize_instructions("  keep tests  ") == "keep tests"


def test_compact_prompt_formats_optional_instructions() -> None:
    assert compact_prompt(None) == "/compact"
    assert compact_prompt("") == "/compact"
    assert compact_prompt("keep failing tests") == "/compact keep failing tests"


def test_default_none_support() -> None:
    assert (
        CompactSupport(
            mode="none",
            accepts_instructions=False,
            true_compaction=False,
            note="compaction is not supported by this runner",
        )
        == COMPACT_NONE
    )


def test_handoff_prompt_is_not_labelled_compaction() -> None:
    text = handoff_prompt("preserve blockers")
    assert "handoff summary" in text.lower()
    assert "User focus:\npreserve blockers" in text
    assert "real compaction" not in text.lower()


def test_handoff_prompt_without_instructions() -> None:
    text = handoff_prompt(None)
    assert "handoff summary" in text.lower()
    assert "User focus:" not in text


def test_warning_when_instructions_are_dropped() -> None:
    msg = warn_if_dropping_instructions("codex", "keep API contracts")
    assert msg is not None
    assert "codex" in msg
    assert "instructions are not supported" in msg


def test_warning_none_when_no_instructions() -> None:
    assert warn_if_dropping_instructions("codex", None) is None
    assert warn_if_dropping_instructions("codex", "") is None


def test_get_compact_support_returns_none_for_plain_object() -> None:
    class NoCompact:
        pass

    assert get_compact_support(NoCompact()) == COMPACT_NONE


def test_get_compact_support_returns_value() -> None:
    class HasCompact:
        def compact_support(self) -> CompactSupport:
            return CompactSupport(
                mode="slash_prompt", accepts_instructions=True, true_compaction=True
            )

    support = get_compact_support(HasCompact())
    assert support.mode == "slash_prompt"
    assert support.accepts_instructions is True
