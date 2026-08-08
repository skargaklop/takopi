"""End-to-end prompt batching tests through the Telegram main loop.

Covers docs/plans/2026-08-01-telegram-multi-message-input.md Task 5 (all
regimes and workflows) and Task 6 (queue safety audit).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import anyio
import pytest

from takopi import commands, plugins
import takopi.telegram.loop as telegram_loop
from takopi.config import ProjectConfig, ProjectsConfig
from takopi.context import RunContext
from takopi.markdown import MarkdownPresenter
from takopi.model import ResumeToken
from takopi.runner_bridge import ExecBridgeConfig
from takopi.runners.mock import Return, ScriptRunner, Wait
from takopi.settings import TelegramTopicsSettings
from takopi.telegram.bridge import TelegramBridgeConfig, run_main_loop
from takopi.telegram.chat_prefs import ChatPrefsStore, resolve_prefs_path
from takopi.telegram.chat_sessions import ChatSessionStore, resolve_sessions_path
from takopi.telegram.topic_state import TopicStateStore, resolve_state_path
from takopi.telegram.types import (
    TelegramIncomingMessage,
    TelegramVoice,
)
from takopi.transport_runtime import TransportRuntime
from tests.plugin_fixtures import FakeEntryPoint, install_entrypoints
from tests.telegram_fakes import (
    FakeBot,
    FakeTransport,
    _empty_projects,
    make_cfg,
    make_multi_runner_cfg,
    _make_router,
)

CODEX_ENGINE = "codex"
FAST_PROMPT_BATCH_S = 0.02


def _topic_projects() -> ProjectsConfig:
    return ProjectsConfig(
        projects={
            "takopi": ProjectConfig(
                alias="takopi",
                path=Path("."),
                worktrees_dir=Path(".worktrees"),
            )
        },
        default_project=None,
    )


def _msg(message_id: int, text: str, **kwargs) -> TelegramIncomingMessage:
    return TelegramIncomingMessage(
        transport="telegram",
        chat_id=kwargs.pop("chat_id", 123),
        message_id=message_id,
        text=text,
        reply_to_message_id=kwargs.pop("reply_to_message_id", None),
        reply_to_text=kwargs.pop("reply_to_text", None),
        sender_id=kwargs.pop("sender_id", 123),
        thread_id=kwargs.pop("thread_id", None),
        chat_type=kwargs.pop("chat_type", "private"),
        **kwargs,
    )


def _chat_cfg(
    runner: ScriptRunner,
    transport: FakeTransport,
    config_path: Path,
    *,
    session_mode: Literal["stateless", "chat"] = "stateless",
    topics: TelegramTopicsSettings | None = None,
) -> TelegramBridgeConfig:
    runtime = TransportRuntime(
        router=_make_router(runner),
        projects=_topic_projects(),
        config_path=config_path,
    )
    return TelegramBridgeConfig(
        bot=FakeBot(),
        runtime=runtime,
        chat_id=123,
        startup_msg="",
        exec_cfg=ExecBridgeConfig(
            transport=transport,
            presenter=MarkdownPresenter(),
            final_notify=True,
        ),
        forward_coalesce_s=0.0,
        media_group_debounce_s=0.0,
        session_mode=session_mode,
        topics=topics or TelegramTopicsSettings(),
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )


@pytest.mark.anyio
async def test_prompt_batch_plain_text_runs_once() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_enabled=True,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
        forward_coalesce_s=0.0,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "first part")
        yield _msg(2, "second part")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "first part\n\nsecond part"


@pytest.mark.anyio
async def test_prompt_batch_engine_directive_resolves_after_joining() -> None:
    codex_runner = ScriptRunner([Return(answer="codex")], engine="codex")
    claude_runner = ScriptRunner([Return(answer="claude")], engine="claude")
    cfg = make_multi_runner_cfg(
        FakeTransport(),
        [codex_runner, claude_runner],
        default_engine="claude",
        prompt_batch_enabled=True,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/codex summarize")
        yield _msg(2, "the pasted content")

    await run_main_loop(cfg, poller)

    assert codex_runner.calls[0][0] == "summarize\n\nthe pasted content"
    assert not claude_runner.calls


@pytest.mark.anyio
async def test_prompt_batch_plan_prompt_joins() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/plan build API")
        yield _msg(2, "more details")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "build API\n\nmore details"


@pytest.mark.anyio
async def test_prompt_batch_bare_plan_not_batched() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/plan")
        yield _msg(2, "more")

    await run_main_loop(cfg, poller)

    # Bare /plan is a sticky command and never joins the follow-up message;
    # the follow-up still runs as its own prompt.
    assert [call[0] for call in runner.calls] == ["more"]


@pytest.mark.anyio
async def test_prompt_batch_goal_prompt_joins() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/goal all tests pass")
        yield _msg(2, "also lint")

    await run_main_loop(cfg, poller)

    # Both chunks joined into ONE goal-mode run; the goal condition consumed
    # the prompt body, so the runner sees the empty-prompt placeholder.
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "continue"


@pytest.mark.anyio
async def test_prompt_batch_bare_goal_not_batched() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/goal")
        yield _msg(2, "more")

    await run_main_loop(cfg, poller)

    # Bare /goal is help-only and never joins the follow-up message.
    assert [call[0] for call in runner.calls] == ["more"]


@pytest.mark.anyio
async def test_prompt_batch_plugin_command_arguments(monkeypatch) -> None:
    class EchoCommand:
        id = "echo"
        description = "echo"

        async def handle(self, ctx):
            return commands.CommandResult(text=f"echo:{ctx.args_text}")

    entrypoints = [
        FakeEntryPoint(
            "echo",
            "takopi.commands.echo:BACKEND",
            plugins.COMMAND_GROUP,
            loader=EchoCommand,
        )
    ]
    install_entrypoints(monkeypatch, entrypoints)

    transport = FakeTransport()
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/echo first")
        yield _msg(2, "second")

    await run_main_loop(cfg, poller)

    assert runner.calls == []
    assert transport.send_calls
    assert "echo:first\n\nsecond" in transport.send_calls[-1]["message"].text


@pytest.mark.anyio
async def test_prompt_batch_stateless_reply_joins_and_resumes() -> None:
    runner = ScriptRunner(
        [Return(answer="ok")],
        engine=CODEX_ENGINE,
        resume_value="sid",
    )
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )
    footer = "done\n`codex resume sid`"

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "continue with", reply_to_message_id=99, reply_to_text=footer)
        yield _msg(2, "these details", reply_to_message_id=99, reply_to_text=footer)

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "continue with\n\nthese details"
    assert runner.calls[0][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")


@pytest.mark.anyio
async def test_prompt_batch_chat_session_resumes_once(tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    config_path = tmp_path / "takopi.toml"
    store = ChatSessionStore(resolve_sessions_path(config_path))
    await store.set_session_resume(
        123, None, ResumeToken(engine=CODEX_ENGINE, value="sid")
    )
    cfg = _chat_cfg(runner, FakeTransport(), config_path, session_mode="chat")

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "first chunk", chat_type="private")
        yield _msg(2, "second chunk", chat_type="private")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "first chunk\n\nsecond chunk"
    assert runner.calls[0][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")


@pytest.mark.anyio
async def test_prompt_batch_topic_same_thread_batches(tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    config_path = tmp_path / "takopi.toml"
    topic_store = TopicStateStore(resolve_state_path(config_path))
    await topic_store.set_context(
        123,
        5,
        RunContext(project="takopi", branch=None),
        topic_title="takopi",
    )
    cfg = _chat_cfg(
        runner,
        FakeTransport(),
        config_path,
        topics=TelegramTopicsSettings(enabled=True, scope="main"),
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "first", thread_id=5, chat_type="supergroup")
        yield _msg(2, "second", thread_id=5, chat_type="supergroup")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "first\n\nsecond"


@pytest.mark.anyio
async def test_prompt_batch_different_thread_does_not_batch(tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    config_path = tmp_path / "takopi.toml"
    topic_store = TopicStateStore(resolve_state_path(config_path))
    for thread_id in (5, 6):
        await topic_store.set_context(
            123,
            thread_id,
            RunContext(project="takopi", branch=None),
            topic_title="takopi",
        )
    cfg = _chat_cfg(
        runner,
        FakeTransport(),
        config_path,
        topics=TelegramTopicsSettings(enabled=True, scope="main"),
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "first", thread_id=5, chat_type="supergroup")
        yield _msg(2, "second", thread_id=6, chat_type="supergroup")

    await run_main_loop(cfg, poller)

    assert [call[0] for call in runner.calls] == ["first", "second"]


@pytest.mark.anyio
async def test_prompt_batch_queues_as_one_job_for_busy_resume() -> None:
    hold = anyio.Event()
    progress_ready = anyio.Event()
    transport = FakeTransport(progress_ready=progress_ready)
    runner = ScriptRunner(
        [Wait(hold), Return(answer="active")],
        engine=CODEX_ENGINE,
        resume_value="sid",
    )
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "start active run")
        await progress_ready.wait()
        assert transport.progress_ref is not None
        assert isinstance(transport.progress_ref.message_id, int)
        reply_id = transport.progress_ref.message_id
        yield _msg(2, "first", reply_to_message_id=reply_id)
        yield _msg(3, "second", reply_to_message_id=reply_id)
        await anyio.sleep(0.06)
        assert len(runner.calls) == 1
        hold.set()

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 2
    assert runner.calls[0][0] == "start active run"
    assert runner.calls[1][0] == "first\n\nsecond"
    assert runner.calls[1][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")


@pytest.mark.anyio
async def test_prompt_batch_fifo_ordering_with_surrounding_jobs() -> None:
    hold = anyio.Event()
    progress_ready = anyio.Event()
    transport = FakeTransport(progress_ready=progress_ready)
    runner = ScriptRunner(
        [Wait(hold), Return(answer="ok")],
        engine=CODEX_ENGINE,
        resume_value="sid",
    )
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "start")
        await progress_ready.wait()
        assert transport.progress_ref is not None
        assert isinstance(transport.progress_ref.message_id, int)
        reply_id = transport.progress_ref.message_id
        yield _msg(2, "A1", reply_to_message_id=reply_id)
        yield _msg(3, "A2", reply_to_message_id=reply_id)
        await anyio.sleep(0.08)
        yield _msg(4, "B", reply_to_message_id=reply_id)
        await anyio.sleep(0.08)
        hold.set()

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 3
    assert runner.calls[0][0] == "start"
    assert runner.calls[1][0] == "A1\n\nA2"
    assert runner.calls[2][0] == "B"
    assert runner.calls[1][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")
    assert runner.calls[2][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")


@pytest.mark.anyio
async def test_prompt_batch_mentions_mode_trigger_on_assembled_text(
    tmp_path: Path,
) -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    config_path = tmp_path / "takopi.toml"
    prefs = ChatPrefsStore(resolve_prefs_path(config_path))
    await prefs.set_trigger_mode(123, "mentions")
    runtime = TransportRuntime(
        router=_make_router(runner),
        projects=_empty_projects(),
        config_path=config_path,
    )
    cfg = TelegramBridgeConfig(
        bot=FakeBot(),
        runtime=runtime,
        chat_id=123,
        startup_msg="",
        exec_cfg=ExecBridgeConfig(
            transport=FakeTransport(),
            presenter=MarkdownPresenter(),
            final_notify=True,
        ),
        forward_coalesce_s=0.0,
        media_group_debounce_s=0.0,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "please do the thing")
        yield _msg(2, "hello @bot now finish it")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "please do the thing\n\nhello @bot now finish it"


@pytest.mark.anyio
async def test_prompt_batch_mentions_mode_no_trigger_skips(tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    config_path = tmp_path / "takopi.toml"
    prefs = ChatPrefsStore(resolve_prefs_path(config_path))
    await prefs.set_trigger_mode(123, "mentions")
    runtime = TransportRuntime(
        router=_make_router(runner),
        projects=_empty_projects(),
        config_path=config_path,
    )
    cfg = TelegramBridgeConfig(
        bot=FakeBot(),
        runtime=runtime,
        chat_id=123,
        startup_msg="",
        exec_cfg=ExecBridgeConfig(
            transport=FakeTransport(),
            presenter=MarkdownPresenter(),
            final_notify=True,
        ),
        forward_coalesce_s=0.0,
        media_group_debounce_s=0.0,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "just text")
        yield _msg(2, "more text")

    await run_main_loop(cfg, poller)

    assert runner.calls == []


@pytest.mark.anyio
async def test_prompt_batch_different_sender_does_not_batch() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "one", sender_id=1)
        yield _msg(2, "two", sender_id=2)

    await run_main_loop(cfg, poller)

    assert [call[0] for call in runner.calls] == ["one", "two"]


@pytest.mark.anyio
async def test_prompt_batch_missing_sender_not_batched() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "one", sender_id=None)

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "one"


@pytest.mark.anyio
async def test_prompt_batch_different_reply_target_does_not_batch() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "one", reply_to_message_id=10, reply_to_text="a")
        yield _msg(2, "two", reply_to_message_id=11, reply_to_text="b")

    await run_main_loop(cfg, poller)

    assert [call[0] for call in runner.calls] == ["one", "two"]


@pytest.mark.anyio
async def test_prompt_batch_delay_beyond_debounce_creates_two_prompts() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "one")
        await anyio.sleep(0.08)
        yield _msg(2, "two")

    await run_main_loop(cfg, poller)

    assert [call[0] for call in runner.calls] == ["one", "two"]


@pytest.mark.anyio
async def test_prompt_batch_max_messages_flushes_immediately() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=0.05,
        prompt_batch_max_messages=2,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "one")
        yield _msg(2, "two")
        await anyio.sleep(0.02)

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "one\n\ntwo"


@pytest.mark.anyio
async def test_prompt_batch_max_chars_flushes_immediately() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=0.05,
        prompt_batch_max_chars=4096,
    )
    big = "x" * 3000

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, big)
        yield _msg(2, big)
        await anyio.sleep(0.02)

    await run_main_loop(cfg, poller)

    # The joined text would exceed max_chars=4096, so the first chunk is
    # flushed on its own and the second chunk starts a new batch.
    assert [call[0] for call in runner.calls] == [big, big]


@pytest.mark.anyio
async def test_prompt_batch_cancel_cancels_pending_batch() -> None:
    transport = FakeTransport()
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "pending prompt")
        yield _msg(2, "/cancel")

    await run_main_loop(cfg, poller)

    assert runner.calls == []


@pytest.mark.anyio
async def test_prompt_batch_new_cancels_pending_batch(tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    config_path = tmp_path / "takopi.toml"
    cfg = _chat_cfg(runner, FakeTransport(), config_path, session_mode="chat")

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "pending prompt", chat_type="private")
        yield _msg(2, "/new", chat_type="private")

    await run_main_loop(cfg, poller)

    assert runner.calls == []


@pytest.mark.anyio
async def test_prompt_batch_control_commands_bypass_batching() -> None:
    transport = FakeTransport()
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/model")
        yield _msg(2, "/ctx")
        yield _msg(3, "/queue")

    await run_main_loop(cfg, poller)

    assert runner.calls == []


@pytest.mark.anyio
async def test_prompt_batch_forwarded_messages_attach_to_batch() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
        forward_coalesce_s=0.0,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "explain this")
        yield _msg(2, "see", raw={"forward_origin": {"type": "user"}})
        yield _msg(3, "also", raw={"forward_origin": {"type": "user"}})

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "explain this\n\nsee\n\nalso"


@pytest.mark.anyio
async def test_prompt_batch_voice_not_joined(monkeypatch) -> None:
    async def fake_transcribe_voice(**kwargs):
        _ = kwargs
        return "transcribed text"

    monkeypatch.setattr(telegram_loop, "transcribe_voice", fake_transcribe_voice)

    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
        forward_coalesce_s=0.0,
    )
    voice = TelegramVoice(
        file_id="voice-id",
        mime_type="audio/ogg",
        file_size=5,
        duration=1,
        raw={},
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "hello")
        yield _msg(2, "", voice=voice)

    await run_main_loop(cfg, poller)

    texts = [call[0] for call in runner.calls]
    assert "(voice transcribed) transcribed text" in texts
    assert "hello" in texts
    assert len(runner.calls) == 2


@pytest.mark.anyio
async def test_prompt_batch_disabled_no_join() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_enabled=False,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "one")
        yield _msg(2, "two")

    await run_main_loop(cfg, poller)

    assert [call[0] for call in runner.calls] == ["one", "two"]

# ---------------------------------------------------------------------------
# Task 21: Cross-engine queue cancellation and isolation
# ---------------------------------------------------------------------------

_ENGINES = ["codex", "claude", "pi"]


@pytest.mark.anyio
@pytest.mark.parametrize("engine", _ENGINES)
async def test_queue_behind_busy_run_per_engine(engine: str) -> None:
    """For each engine, a prompt queued behind a busy run waits and runs FIFO."""
    hold = anyio.Event()
    progress_ready = anyio.Event()
    transport = FakeTransport(progress_ready=progress_ready)
    runner = ScriptRunner(
        [Wait(hold), Return(answer="active"), Return(answer="queued")],
        engine=engine,
        resume_value="sid",
    )
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_enabled=False,
    )
    expected_token = ResumeToken(engine=engine, value="sid")

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "start active run")
        await progress_ready.wait()
        assert transport.progress_ref is not None
        reply_id = transport.progress_ref.message_id

        yield _msg(2, "queued prompt", reply_to_message_id=reply_id)
        await anyio.sleep(0.06)

        # The queued prompt must NOT have started yet.
        assert len(runner.calls) == 1

        hold.set()
        await anyio.sleep(0.06)

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 2
    assert runner.calls[0][0] == "start active run"
    assert runner.calls[1][0] == "queued prompt"
    # The first call has resume=None (new run); the queued call carries the token.
    assert runner.calls[1][1] == expected_token


@pytest.mark.anyio
async def test_queue_isolation_between_engines_same_session() -> None:
    """Different engines with the same session value run concurrently."""
    hold_a = anyio.Event()
    hold_b = anyio.Event()
    progress_ready_a = anyio.Event()
    transport = FakeTransport(progress_ready=progress_ready_a)
    runner_a = ScriptRunner(
        [Wait(hold_a), Return(answer="a")], engine="codex", resume_value="shared"
    )
    runner_b = ScriptRunner(
        [Wait(hold_b), Return(answer="b")], engine="claude", resume_value="shared"
    )
    cfg = make_multi_runner_cfg(
        transport,
        [runner_a, runner_b],
        prompt_batch_enabled=False,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "/codex start")
        await progress_ready_a.wait()
        assert transport.progress_ref is not None

        yield _msg(2, "/claude start")
        await anyio.sleep(0.1)

        assert len(runner_a.calls) == 1
        assert len(runner_b.calls) == 1

        hold_a.set()
        hold_b.set()

    await run_main_loop(cfg, poller)

    assert runner_a.calls[0][0] == "start"
    assert runner_b.calls[0][0] == "start"
    # Both runners were invoked concurrently (isolation: different engines
    # with the same session value "shared" are separate thread keys).
    assert len(runner_a.calls) == 1
    assert len(runner_b.calls) == 1


@pytest.mark.anyio
async def test_queue_fifo_ordering_with_claim_transition() -> None:
    """After the active run finishes, queued prompts run FIFO with correct tokens."""
    hold = anyio.Event()
    progress_ready = anyio.Event()
    transport = FakeTransport(progress_ready=progress_ready)
    runner = ScriptRunner(
        [Wait(hold), Return(answer="first"), Return(answer="second")],
        engine=CODEX_ENGINE,
        resume_value="sid",
    )
    cfg = make_cfg(
        transport,
        runner=runner,
        prompt_batch_enabled=False,
    )

    async def poller(_cfg: TelegramBridgeConfig):
        yield _msg(1, "active")
        await progress_ready.wait()
        assert transport.progress_ref is not None
        reply_id = transport.progress_ref.message_id

        yield _msg(2, "first", reply_to_message_id=reply_id)
        yield _msg(3, "second", reply_to_message_id=reply_id)
        await anyio.sleep(0.06)

        assert len(runner.calls) == 1
        hold.set()
        await anyio.sleep(0.1)

    await run_main_loop(cfg, poller)
    assert len(runner.calls) == 3
    assert [c[0] for c in runner.calls] == ["active", "first", "second"]
    # First call has resume=None (new run); queued calls carry the token.
    assert runner.calls[1][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")
    assert runner.calls[2][1] == ResumeToken(engine=CODEX_ENGINE, value="sid")