from __future__ import annotations

import pytest

from takopi.compact import CompactSupport
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
from takopi.runners._compact_mixin import SlashCompactMixin
from takopi.runners.mock import Return, ScriptRunner


class SlashScriptRunner(SlashCompactMixin, ScriptRunner):
    compact_accepts_instructions = True


class NoInstructionSlashRunner(SlashCompactMixin, ScriptRunner):
    compact_accepts_instructions = False


def test_slash_compact_support() -> None:
    runner = SlashScriptRunner([], engine="claude")
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "slash_prompt"
    assert support.accepts_instructions is True
    assert support.true_compaction is True


@pytest.mark.anyio
async def test_slash_compact_delegates_to_run_with_instructions() -> None:
    runner = SlashScriptRunner([Return(answer="done")], engine="claude")
    resume = ResumeToken(engine="claude", value="sid")
    events = [evt async for evt in runner.compact(resume, "keep tests")]

    assert runner.calls[-1] == ("/compact keep tests", resume)
    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].resume == events[0].resume


@pytest.mark.anyio
async def test_slash_compact_without_instructions() -> None:
    runner = SlashScriptRunner([Return(answer="done")], engine="claude")
    resume = ResumeToken(engine="claude", value="sid")
    _ = [evt async for evt in runner.compact(resume, None)]
    assert runner.calls[-1][0] == "/compact"


@pytest.mark.anyio
async def test_slash_compact_drops_instructions_when_unsupported() -> None:
    runner = NoInstructionSlashRunner([Return(answer="done")], engine="codex")
    resume = ResumeToken(engine="codex", value="sid")
    _ = [evt async for evt in runner.compact(resume, "drop this")]
    assert runner.calls[-1] == ("/compact", resume)


def test_no_instruction_support_mode() -> None:
    runner = NoInstructionSlashRunner([], engine="codex")
    support = runner.compact_support()
    assert support.mode == "slash_prompt"
    assert support.accepts_instructions is False
