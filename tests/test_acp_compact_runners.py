"""Tests for compact on grok and omp runners.

omp and grok now use ``HandoffCompactMixin`` (handoff summary via ``run()``).
The ACP path (``FakeAcpTransport``, ``AcpCompactMixin``) remains test-only
for future subprocess-transport work (Task 6 of the compact production-failure
plan).
"""

from __future__ import annotations

import pytest

from takopi.compact import CompactSupport, handoff_prompt
from takopi.model import CompletedEvent, ResumeToken
from takopi.runners.grok import GrokRunner
from takopi.runners.omp import OmpRunner


def test_grok_compact_support_is_handoff_only() -> None:
    runner = GrokRunner()
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "handoff_only"
    assert support.true_compaction is False
    assert support.accepts_instructions is True


def test_omp_compact_support_is_handoff_only() -> None:
    runner = OmpRunner.__new__(OmpRunner)
    runner.extra_args = []
    runner.model = None
    runner.provider = None
    runner.plan_mode = "soft"
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "handoff_only"
    assert support.true_compaction is False


@pytest.mark.anyio
async def test_grok_compact_uses_handoff_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compact() delegates to run() with the handoff_prompt text."""
    runner = GrokRunner()
    captured: list[str] = []

    async def fake_run(self, prompt, resume):
        captured.append(prompt)
        yield CompletedEvent(engine="grok", ok=True, answer="", resume=resume)

    monkeypatch.setattr(GrokRunner, "run", fake_run)
    resume = ResumeToken(engine="grok", value="sid")

    events = [evt async for evt in runner.compact(resume, "preserve decisions")]

    assert len(events) == 1
    assert events[0].ok is True
    assert captured[0] == handoff_prompt("preserve decisions")


@pytest.mark.anyio
async def test_omp_compact_uses_handoff_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """compact() delegates to run() with the handoff_prompt text."""
    runner = OmpRunner.__new__(OmpRunner)
    runner.extra_args = []
    runner.model = None
    runner.provider = None
    runner.plan_mode = "soft"
    captured: list[str] = []

    async def fake_run(self, prompt, resume):
        captured.append(prompt)
        yield CompletedEvent(engine="omp", ok=True, answer="", resume=resume)

    monkeypatch.setattr(OmpRunner, "run", fake_run)
    resume = ResumeToken(engine="omp", value="sid")

    events = [evt async for evt in runner.compact(resume, "preserve decisions")]

    assert len(events) == 1
    assert events[0].ok is True
    assert captured[0] == handoff_prompt("preserve decisions")
