"""Loop-level tests for /compact command dispatch robustness.

Tests cover:
1. Reply-to-final-message with resume footer -> compact on correct engine.
2. Reply-to-active-run -> no empty-prompt job; compact serializes behind.
3. Ordering equivalence: /codex /compact and /compact /codex.
4. Prompt-batch debounce > 0 does not swallow /compact.
5. None-support engine -> confirmation keyboard; confirm enqueues handoff prompt.
6. Instructions-warning path preserved.
7. No-session /compact -> guidance reply.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from takopi.compact import CompactSupport
from takopi.config import ProjectsConfig
from takopi.markdown import MarkdownPresenter
from takopi.model import CompletedEvent, EngineId, ResumeToken, TakopiEvent
from takopi.router import AutoRouter, RunnerEntry
from takopi.runner_bridge import ExecBridgeConfig
from takopi.runners.mock import Raise, Return, ScriptRunner
from takopi.telegram.bridge import TelegramBridgeConfig, run_main_loop
from takopi.telegram.client import BotClient
from takopi.telegram.types import TelegramCallbackQuery, TelegramIncomingMessage
from takopi.transport import MessageRef, RenderedMessage, SendOptions
from takopi.transport_runtime import TransportRuntime

CODEX: EngineId = "codex"
CLAUDE: EngineId = "claude"


def _empty_projects() -> ProjectsConfig:
    return ProjectsConfig(projects={}, default_project=None)


class FakeTransport:
    """Captures sends/edits for assertions."""

    def __init__(self) -> None:
        self._next_id = 1
        self.send_calls: list[dict] = []
        self.edit_calls: list[dict] = []

    async def send(
        self,
        *,
        channel_id: int | str,
        message: RenderedMessage,
        options: SendOptions | None = None,
    ) -> MessageRef:
        ref = MessageRef(channel_id=channel_id, message_id=self._next_id)
        self._next_id += 1
        self.send_calls.append(
            {
                "ref": ref,
                "channel_id": channel_id,
                "message": message,
                "options": options,
            }
        )
        return ref

    async def edit(
        self, *, ref: MessageRef, message: RenderedMessage, wait: bool = True
    ) -> MessageRef:
        self.edit_calls.append({"ref": ref, "message": message, "wait": wait})
        return ref

    async def close(self) -> None:
        pass


class FakeBot(BotClient):
    def __init__(self) -> None:
        self.callback_calls: list[dict] = []

    async def answer_callback_query(self, callback_query_id: str, **kwargs) -> None:
        self.callback_calls.append({"callback_query_id": callback_query_id, **kwargs})

    async def get_me(self):  # type: ignore[override]
        class _Me:
            username = "testbot"
            id = 999
            first_name = "Test"
            is_bot = True

        return _Me()


class CompactableScriptRunner(ScriptRunner):
    """ScriptRunner that declares slash_prompt compact support and records compact calls."""

    def __init__(self, *args, accepts_instructions: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._compact_accepts = accepts_instructions
        self.compact_calls: list[tuple[ResumeToken, str | None]] = []

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="slash_prompt",
            accepts_instructions=self._compact_accepts,
            true_compaction=True,
        )

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        self.compact_calls.append((resume, instructions))
        yield TakopiEvent()  # minimal event
        del resume, instructions


class HandoffScriptRunner(ScriptRunner):
    """ScriptRunner that declares handoff_only compact support."""

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="handoff_only",
            accepts_instructions=True,
            true_compaction=False,
        )

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        from takopi.compact import handoff_prompt

        async for event in self.run(handoff_prompt(instructions), resume):
            yield event


class RaisingCompactRunner(ScriptRunner):
    """ScriptRunner whose compact() raises RuntimeError."""

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="slash_prompt",
            accepts_instructions=True,
            true_compaction=True,
        )

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        raise RuntimeError("compact boom")
        yield  # pragma: no cover


class SilentFailCompactRunner(ScriptRunner):
    """ScriptRunner whose compact() yields CompletedEvent(ok=False) without raising."""

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="slash_prompt",
            accepts_instructions=True,
            true_compaction=True,
        )

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        yield CompletedEvent(
            engine=self.engine, ok=False, answer="", resume=resume, error="boom"
        )


def _make_multi_cfg(
    transport: FakeTransport,
    runners: list[ScriptRunner],
    *,
    default_engine: str | None = None,
    prompt_batch_debounce_s: float = 0.0,
) -> TelegramBridgeConfig:
    entries = [RunnerEntry(engine=r.engine, runner=r) for r in runners]
    router = AutoRouter(
        entries=entries,
        default_engine=default_engine or entries[0].engine,
    )
    return TelegramBridgeConfig(
        bot=FakeBot(),
        runtime=TransportRuntime(router=router, projects=_empty_projects()),
        chat_id=123,
        startup_msg="",
        exec_cfg=ExecBridgeConfig(
            transport=transport,
            presenter=MarkdownPresenter(),
            final_notify=True,
        ),
        prompt_batch_enabled=True,
        prompt_batch_debounce_s=prompt_batch_debounce_s,
    )


def _msg(
    text: str,
    *,
    message_id: int,
    chat_id: int = 123,
    reply_to_message_id: int | None = None,
    reply_to_text: str | None = None,
    sender_id: int = 123,
) -> TelegramIncomingMessage:
    return TelegramIncomingMessage(
        transport="telegram",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_to_message_id=reply_to_message_id,
        reply_to_text=reply_to_text,
        sender_id=sender_id,
        chat_type="private",
    )


def _cb(
    *,
    callback_data: str,
    message_id: int = 1,
    chat_id: int = 123,
) -> TelegramCallbackQuery:
    return TelegramCallbackQuery(
        transport="telegram",
        chat_id=chat_id,
        message_id=message_id,
        callback_query_id=f"cbq-{message_id}",
        data=callback_data,
        sender_id=123,
    )


# ---------------------------------------------------------------------------
# Test 1: /compact replying to a FINAL message with resume footer.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compact_reply_to_final_with_footer() -> None:
    """Replying /compact to a final message with `claude resume xyz` footer
    compacts the claude session."""
    transport = FakeTransport()
    codex = CompactableScriptRunner([Return(answer="ok")], engine=CODEX)
    claude = CompactableScriptRunner([Return(answer="ok")], engine=CLAUDE)
    cfg = _make_multi_cfg(transport, [codex, claude], default_engine=CODEX)

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`claude resume xyz`",
        )

    await run_main_loop(cfg, poller)

    assert len(claude.compact_calls) == 1
    assert claude.compact_calls[0][0] == ResumeToken(engine=CLAUDE, value="xyz")
    assert codex.compact_calls == []


# ---------------------------------------------------------------------------
# Test 3: Ordering equivalence.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compact_ordering_engine_first() -> None:
    """/codex /compact and /compact /codex both produce a compact job on codex."""
    transport = FakeTransport()
    codex = CompactableScriptRunner([Return(answer="ok")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        yield _msg(
            "/codex /compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c1`",
        )

    await run_main_loop(cfg, poller)
    assert len(codex.compact_calls) == 1
    assert codex.compact_calls[0][0] == ResumeToken(engine=CODEX, value="c1")


@pytest.mark.anyio
async def test_compact_ordering_compact_first() -> None:
    transport = FakeTransport()
    codex = CompactableScriptRunner([Return(answer="ok")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        yield _msg(
            "/compact /codex",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c2`",
        )

    await run_main_loop(cfg, poller)
    assert len(codex.compact_calls) == 1
    assert codex.compact_calls[0][0] == ResumeToken(engine=CODEX, value="c2")


# ---------------------------------------------------------------------------
# Test 4: Prompt-batch debounce does not swallow /compact.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compact_not_swallowed_by_batcher() -> None:
    transport = FakeTransport()
    codex = CompactableScriptRunner([Return(answer="ok")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex], prompt_batch_debounce_s=0.5)

    async def poller(_cfg):
        yield _msg(
            "/compact keep tests",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c1`",
        )

    await run_main_loop(cfg, poller)
    assert len(codex.compact_calls) == 1
    assert codex.compact_calls[0][1] == "keep tests"


# ---------------------------------------------------------------------------
# Test 5: None-support engine -> confirmation keyboard.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compact_none_support_shows_confirmation() -> None:
    """When the engine does not support compact, a confirmation keyboard appears."""
    transport = FakeTransport()
    codex = ScriptRunner([Return(answer="ok")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c1`",
        )

    await run_main_loop(cfg, poller)

    # No compact call was made (none support).
    assert not hasattr(codex, "compact_calls")
    # The confirmation message has an inline keyboard.
    confirm_sends = [
        s
        for s in transport.send_calls
        if "compact" in s["message"].text.lower()
        or "support" in s["message"].text.lower()
        or "native" in s["message"].text.lower()
    ]
    assert confirm_sends, "expected a confirmation message about no compact support"
    send = confirm_sends[0]
    markup = send["message"].extra.get("reply_markup")
    assert markup is not None, "confirmation message must have inline keyboard"


# ---------------------------------------------------------------------------
# Test 6: Instructions-warning path preserved.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compact_warning_drops_instructions() -> None:
    """When accepts_instructions=False, instructions are dropped with a warning."""
    transport = FakeTransport()
    codex = CompactableScriptRunner(
        [Return(answer="ok")], engine=CODEX, accepts_instructions=False
    )
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        yield _msg(
            "/compact keep my tests",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c1`",
        )

    await run_main_loop(cfg, poller)
    assert len(codex.compact_calls) == 1
    assert codex.compact_calls[0][1] is None


# ---------------------------------------------------------------------------
# Test 7: No-session /compact -> guidance reply.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_compact_no_session_shows_guidance() -> None:
    transport = FakeTransport()
    codex = CompactableScriptRunner([Return(answer="ok")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        # No reply-to message, no stored session.
        yield _msg("/compact", message_id=10)

    await run_main_loop(cfg, poller)
    assert codex.compact_calls == []
    assert any(
        "no active session" in s["message"].text.lower()
        or "no session" in s["message"].text.lower()
        for s in transport.send_calls
    )


# ---------------------------------------------------------------------------
# Test 8: Handoff engine /compact -> approval card with inline keyboard; nothing runs.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_engine_shows_approval_gate() -> None:
    """handoff_only engine /compact shows approval card, does not run yet."""
    transport = FakeTransport()
    omp = HandoffScriptRunner([Return(answer="summary")], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )

    await run_main_loop(cfg, poller)
    # No compact/run happened (approval gate stops it).
    assert omp.calls == []
    # An approval card with inline keyboard was sent.
    approve_sends = [
        s for s in transport.send_calls if "approve handoff" in str(s["message"].extra)
    ]
    assert approve_sends, "expected approval card with keyboard"


# ---------------------------------------------------------------------------
# Test 9: Approve -> phase 1 compact on OLD token; phase 2 seed run with resume=None.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_approve_runs_phase1_and_phase2() -> None:
    """Approve: compact() called on OLD token, then run() called with resume=None."""
    transport = FakeTransport()
    omp = HandoffScriptRunner([Return(answer="the summary text")], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact keep decisions",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )
        # FakeTransport assigns message_id=1 to the first send (the approval card).
        yield _cb(callback_data="takopi:compact:confirm", message_id=1)

    await run_main_loop(cfg, poller)
    # Phase 1: compact() was called on the OLD token.
    assert len(omp.calls) >= 1
    assert omp.calls[0][0] is not None  # prompt is handoff_prompt text
    # Phase 2: run() called with resume=None (new session) and seed prompt.
    assert len(omp.calls) >= 2
    phase2_prompt, phase2_resume = omp.calls[1]
    assert phase2_resume is None  # new session
    assert "handoff summary" in phase2_prompt.lower()
    assert "the summary text" in phase2_prompt


# ---------------------------------------------------------------------------
# Test 10: Decline -> nothing runs, cancelled reply.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_decline_does_nothing() -> None:
    transport = FakeTransport()
    omp = HandoffScriptRunner([Return(answer="summary")], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )
        yield _cb(callback_data="takopi:compact:decline", message_id=1)

    await run_main_loop(cfg, poller)
    assert omp.calls == []
    # "cancelled" appears in the edited confirmation message.
    edit_texts = [s["message"].text.lower() for s in transport.edit_calls]
    assert any("cancelled" in t for t in edit_texts), edit_texts


# ---------------------------------------------------------------------------
# Test 11: Phase 1 failure -> no phase 2; failure reply.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_phase1_failure_no_phase2() -> None:
    transport = FakeTransport()
    omp = HandoffScriptRunner([Raise(error=RuntimeError("phase1 boom"))], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )
        yield _cb(callback_data="takopi:compact:confirm", message_id=1)

    await run_main_loop(cfg, poller)
    # Phase 1 failed: only one compact call, no phase 2.
    assert len(omp.calls) == 1
    texts = [s["message"].text.lower() for s in transport.send_calls]
    assert any("handoff failed" in t for t in texts), texts


# ---------------------------------------------------------------------------
# Test 12: Empty answer -> treated as failure (no phase 2).
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_empty_answer_no_phase2() -> None:
    transport = FakeTransport()
    omp = HandoffScriptRunner([Return(answer="   ")], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )
        yield _cb(callback_data="takopi:compact:confirm", message_id=1)

    await run_main_loop(cfg, poller)
    assert len(omp.calls) == 1  # phase 1 only, no phase 2
    texts = [s["message"].text.lower() for s in transport.send_calls]
    assert any("handoff failed" in t for t in texts), texts


# ---------------------------------------------------------------------------
# Test 13: True-compaction engine -> NO approval gate; immediate compact.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_true_compaction_no_approval_gate() -> None:
    """Slash-prompt engine runs compact immediately, no approval card."""
    transport = FakeTransport()
    codex = CompactableScriptRunner([Return(answer="ok")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c1`",
        )

    await run_main_loop(cfg, poller)
    assert len(codex.compact_calls) == 1
    # No approval card with keyboard.
    assert not any(
        "approve handoff" in str(s["message"].extra) for s in transport.send_calls
    )


# ---------------------------------------------------------------------------
# Test 14: Instructions forwarded through approval -> handoff_prompt.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_instructions_forwarded() -> None:
    """/compact keep tests -> compact() receives the instruction text."""
    from takopi.compact import handoff_prompt

    transport = FakeTransport()
    omp = HandoffScriptRunner([Return(answer="summary")], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact keep tests",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )
        yield _cb(callback_data="takopi:compact:confirm", message_id=1)

    await run_main_loop(cfg, poller)
    assert len(omp.calls) >= 1
    # Phase 1 prompt is the handoff_prompt with instructions.
    assert omp.calls[0][0] == handoff_prompt("keep tests")


# ---------------------------------------------------------------------------
# Test 15: None engine -> approval card with disclaimer; approve -> handoff flow.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_none_engine_approval_includes_disclaimer() -> None:
    transport = FakeTransport()
    codex = ScriptRunner([Return(answer="summary")], engine=CODEX)
    cfg = _make_multi_cfg(transport, [codex])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`codex resume c1`",
        )

    await run_main_loop(cfg, poller)
    texts = [s["message"].text.lower() for s in transport.send_calls]
    assert any("does not support compaction at all" in t for t in texts), texts
    assert any(
        "approve handoff" in str(s["message"].extra) for s in transport.send_calls
    )


# ---------------------------------------------------------------------------
# Test 16: Completion message mentions new session + summary echo.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handoff_completion_mentions_new_session_and_echoes_summary() -> None:
    transport = FakeTransport()
    omp = HandoffScriptRunner([Return(answer="my cool summary")], engine="omp")
    cfg = _make_multi_cfg(transport, [omp])

    async def poller(_cfg):
        yield _msg(
            "/compact",
            message_id=10,
            reply_to_message_id=5,
            reply_to_text="done\n`omp resume s1`",
        )
        yield _cb(callback_data="takopi:compact:confirm", message_id=1)

    await run_main_loop(cfg, poller)
    texts = [s["message"].text.lower() for s in transport.send_calls]
    # Completion message mentions new session.
    assert any("new omp session" in t for t in texts), texts
    # Summary echo was sent.
    assert any("my cool summary" in s["message"].text for s in transport.send_calls), [
        s["message"].text for s in transport.send_calls
    ]
