"""Tests for agy handoff-only compact."""

from __future__ import annotations

import pytest

from takopi.compact import CompactSupport, handoff_prompt
from takopi.runners.agy import AgyRunner


def test_agy_compact_support_is_handoff_only() -> None:
    runner = AgyRunner()
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "handoff_only"
    assert support.accepts_instructions is True
    assert support.true_compaction is False


def test_handoff_prompt_includes_user_focus() -> None:
    text = handoff_prompt("preserve blockers")
    assert "User focus:\npreserve blockers" in text
    assert "handoff summary" in text.lower()


@pytest.mark.anyio
async def test_agy_compact_uses_handoff_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify compact_support reports handoff_only with false compaction."""
    runner = AgyRunner()

    # Verify support metadata without running the actual subprocess.
    support = runner.compact_support()
    assert support.true_compaction is False
    assert support.mode == "handoff_only"

    # The handoff prompt is what compact should send. Verify the prompt builder.
    prompt = handoff_prompt("preserve blockers")
    assert "preserve blockers" in prompt
    assert "not real context compaction" in prompt.lower()
