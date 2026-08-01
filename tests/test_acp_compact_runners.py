"""Tests for ACP-based compact on grok and omp runners."""

from __future__ import annotations

import pytest

from takopi.compact import CompactSupport
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
from takopi.runners._acp import FakeAcpTransport
from takopi.runners.grok import GrokRunner
from takopi.runners.omp import OmpRunner


def _make_transport_with_compact() -> FakeAcpTransport:
    transport = FakeAcpTransport()
    transport.queue_response("initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}})
    transport.queue_response("session/load", {})
    transport.queue_response("session/prompt", {"stopReason": "stop"})
    transport.emit_notification(
        "available_commands_update",
        {"availableCommands": [{"name": "compact"}]},
    )
    return transport


def _make_transport_without_compact() -> FakeAcpTransport:
    transport = FakeAcpTransport()
    transport.queue_response("initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}})
    transport.queue_response("session/load", {})
    transport.queue_response("session/prompt", {"stopReason": "stop"})
    transport.emit_notification(
        "available_commands_update",
        {"availableCommands": [{"name": "edit"}]},
    )
    return transport



def test_grok_compact_support_is_acp() -> None:
    runner = GrokRunner()
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "acp"
    assert support.accepts_instructions is True


def test_omp_compact_support_is_acp() -> None:
    runner = OmpRunner.__new__(OmpRunner)
    runner.extra_args = []
    runner.model = None
    runner.provider = None
    runner.plan_mode = "soft"
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "acp"


@pytest.mark.anyio
async def test_grok_compact_when_advertised() -> None:
    transport = _make_transport_with_compact()
    runner = GrokRunner()
    runner._acp_transport = transport
    resume = ResumeToken(engine="grok", value="sid")

    events = [evt async for evt in runner.compact(resume, "keep tests")]

    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].resume == events[0].resume
    assert events[-1].ok is True

    prompt_reqs = [r for r in transport.requests if r["method"] == "session/prompt"]
    assert len(prompt_reqs) == 1
    assert prompt_reqs[0]["params"]["prompt"][0]["text"] == "/compact keep tests"


@pytest.mark.anyio
async def test_grok_compact_when_not_advertised() -> None:
    transport = _make_transport_without_compact()
    runner = GrokRunner()
    runner._acp_transport = transport
    resume = ResumeToken(engine="grok", value="sid")

    events = [evt async for evt in runner.compact(resume, None)]

    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].ok is False

    prompt_reqs = [r for r in transport.requests if r["method"] == "session/prompt"]
    assert len(prompt_reqs) == 0


@pytest.mark.anyio
async def test_omp_compact_when_advertised() -> None:
    transport = _make_transport_with_compact()
    runner = OmpRunner.__new__(OmpRunner)
    runner.extra_args = []
    runner.model = None
    runner.provider = None
    runner.plan_mode = "soft"
    runner._acp_transport = transport
    resume = ResumeToken(engine="omp", value="sid")

    events = [evt async for evt in runner.compact(resume, "preserve decisions")]

    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].ok is True

    prompt_reqs = [r for r in transport.requests if r["method"] == "session/prompt"]
    assert prompt_reqs[0]["params"]["prompt"][0]["text"] == "/compact preserve decisions"
