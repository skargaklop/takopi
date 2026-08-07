"""Shared assertion helper and invariant tests for all compact modes."""

from __future__ import annotations

import anyio
import pytest

from takopi.model import CompletedEvent, StartedEvent, TakopiEvent


def assert_compact_event_invariants(events: list[TakopiEvent]) -> None:
    started = [e for e in events if isinstance(e, StartedEvent)]
    completed = [e for e in events if isinstance(e, CompletedEvent)]
    assert len(started) == 1, f"expected exactly 1 StartedEvent, got {len(started)}"
    assert len(completed) == 1, (
        f"expected exactly 1 CompletedEvent, got {len(completed)}"
    )
    assert events[-1] is completed[0]
    assert completed[0].resume == started[0].resume


@pytest.mark.anyio
async def test_slash_compact_event_invariants() -> None:
    """Slash-prompt compact (claude/pi/codex) preserves event order."""
    from takopi.model import ResumeToken
    from takopi.runners._compact_mixin import SlashCompactMixin
    from takopi.runners.mock import Return, ScriptRunner

    class SlashRunner(SlashCompactMixin, ScriptRunner):
        compact_accepts_instructions = True

    runner = SlashRunner([Return(answer="done")], engine="claude")
    resume = ResumeToken(engine="claude", value="sid")
    events = [evt async for evt in runner.compact(resume, "keep tests")]
    assert_compact_event_invariants(events)


@pytest.mark.anyio
async def test_opencode_compact_event_invariants() -> None:
    """OpenCode native API compact preserves event order."""
    from takopi.model import ResumeToken
    from takopi.runners.opencode import OpenCodeRunner

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        async def post(self, url: str, json: dict | None = None) -> FakeResponse:
            return FakeResponse()

        async def close(self) -> None:
            pass

    runner = OpenCodeRunner(
        compact_http_client=FakeClient(),
        compact_wait=False,
    )
    resume = ResumeToken(engine="opencode", value="ses_abc")
    events = [evt async for evt in runner.compact(resume, None)]
    assert_compact_event_invariants(events)


@pytest.mark.anyio
async def test_acp_compact_event_invariants() -> None:
    """ACP compact (grok/omp) preserves event order when compact is advertised."""
    from takopi.model import ResumeToken
    from takopi.runners._acp import AcpClient, AcpCompactMixin, FakeAcpTransport
    from takopi.runners.mock import ScriptRunner

    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize",
        {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}},
    )
    transport.queue_response("session/load", {})
    transport.queue_response("session/prompt", {"stopReason": "stop"})
    transport.emit_notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "compact"}],
            }
        },
    )

    class AcpRunner(AcpCompactMixin, ScriptRunner):
        engine = "grok"
        compact_accepts_instructions = True
        close_timeout_s = 5.0
        startup_timeout_s: float | None = 60.0

        def __init__(self, transport: FakeAcpTransport) -> None:
            super().__init__([], engine="grok")
            self._acp_transport = transport

        def command(self) -> str:
            return "grok"

        def create_acp_client(self) -> AcpClient:
            return AcpClient(
                command="grok",
                args=["agent", "stdio"],
                transport=self._acp_transport,
            )

    runner = AcpRunner(transport)
    resume = ResumeToken(engine="grok", value="sid")
    events = [evt async for evt in runner.compact(resume, "keep tests")]
    assert_compact_event_invariants(events)


@pytest.mark.anyio
async def test_acp_compact_not_advertised_emits_failed_event() -> None:
    """ACP compact emits a failed CompletedEvent when compact is not advertised."""
    from takopi.model import ResumeToken
    from takopi.runners._acp import AcpClient, AcpCompactMixin, FakeAcpTransport
    from takopi.runners.mock import ScriptRunner

    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize",
        {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}},
    )
    transport.queue_response("session/load", {})
    transport.emit_notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "edit"}],
            }
        },
    )

    class AcpRunner(AcpCompactMixin, ScriptRunner):
        engine = "grok"
        compact_accepts_instructions = True
        close_timeout_s = 5.0
        startup_timeout_s: float | None = 60.0

        def __init__(self, transport: FakeAcpTransport) -> None:
            super().__init__([], engine="grok")
            self._acp_transport = transport

        def command(self) -> str:
            return "grok"

        def create_acp_client(self) -> AcpClient:
            return AcpClient(
                command="grok",
                args=["agent", "stdio"],
                transport=self._acp_transport,
            )

    runner = AcpRunner(transport)
    resume = ResumeToken(engine="grok", value="sid")
    events = [evt async for evt in runner.compact(resume, None)]
    assert_compact_event_invariants(events)
    final = events[-1]
    assert isinstance(final, CompletedEvent)
    assert final.ok is False


@pytest.mark.anyio
async def test_compact_serializes_with_active_run_same_resume() -> None:
    """Compact on the same resume token as an active run queues behind it."""
    from takopi.model import ResumeToken
    from takopi.runners._compact_mixin import SlashCompactMixin
    from takopi.runners.mock import Return, ScriptRunner
    from takopi.scheduler import ThreadJob, ThreadScheduler

    started_first = anyio.Event()
    allow_first_to_finish = anyio.Event()
    execution_order: list[str] = []

    class TrackingRunner(SlashCompactMixin, ScriptRunner):
        compact_accepts_instructions = True

        async def run(self, prompt, resume):
            execution_order.append(f"run:{prompt}")
            if prompt == "first prompt":
                started_first.set()
                await allow_first_to_finish.wait()
            async for event in super().run(prompt, resume):
                yield event

        async def compact(self, resume, instructions=None):
            execution_order.append("compact")
            async for event in super().compact(resume, instructions):
                yield event

    runner = TrackingRunner([Return(answer="done")], engine="claude")
    resume = ResumeToken(engine="claude", value="sid")

    async def run_job(job: ThreadJob) -> None:
        if job.kind == "compact":
            async for _event in runner.compact(
                job.resume_token, job.compact_instructions
            ):
                pass
        else:
            async for _event in runner.run(job.text, job.resume_token):
                pass

    async with anyio.create_task_group() as tg:
        scheduler = ThreadScheduler(task_group=tg, run_job=run_job)

        # Enqueue the first prompt — this will block on allow_first_to_finish.
        await scheduler.enqueue(
            ThreadJob(
                chat_id=1,
                user_msg_id=1,
                text="first prompt",
                resume_token=resume,
            )
        )
        # Wait until the first run has actually started.
        await started_first.wait()

        # Enqueue compact for the same resume token (same thread key).
        await scheduler.enqueue(
            ThreadJob(
                chat_id=1,
                user_msg_id=2,
                text="[compact]",
                resume_token=resume,
                kind="compact",
            )
        )
        # Give the scheduler a chance to potentially start compact — it must not.
        await anyio.wait_all_tasks_blocked()
        assert "compact" not in execution_order, (
            "compact started before the active run completed; "
            f"execution_order={execution_order}"
        )

        # Allow the first run to finish; compact should then execute.
        allow_first_to_finish.set()
        # Wait for compact to appear in execution_order.
        with anyio.fail_after(5):
            while "compact" not in execution_order:
                await anyio.wait_all_tasks_blocked()

    assert execution_order.index("run:first prompt") < execution_order.index("compact")
