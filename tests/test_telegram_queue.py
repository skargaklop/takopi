"""Telegram queue cancellation presentation and callback routing (Task 21).

Tests that Cancel callbacks for queued jobs produce exact, idempotent,
honest terminal states and that active-run cancellation remains isolated.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from takopi.model import ResumeToken
from takopi.runner_bridge import RunningTask
from takopi.scheduler import ThreadScheduler
from takopi.telegram.commands.cancel import handle_cancel, handle_callback_cancel
from takopi.telegram.types import TelegramCallbackQuery, TelegramIncomingMessage
from takopi.transport import MessageRef

from .telegram_fakes import FakeBot, FakeTransport, make_cfg

CODEX_ENGINE = "codex"


class _NoopTaskGroup:
    def start_soon(self, func: Any, *args: Any) -> None:
        _ = func, args


async def _noop_run_job(_job: Any) -> None:
    return None


def _make_scheduler() -> ThreadScheduler:
    return ThreadScheduler(task_group=_NoopTaskGroup(), run_job=_noop_run_job)


def _callback_query(
    progress_id: int, data: str = "takopi:cancel"
) -> TelegramCallbackQuery:
    return TelegramCallbackQuery(
        transport="telegram",
        chat_id=123,
        message_id=progress_id,
        callback_query_id=f"cbq-{progress_id}",
        data=data,
        sender_id=123,
    )


def _typed_cancel_msg(reply_to: int) -> TelegramIncomingMessage:
    return TelegramIncomingMessage(
        transport="telegram",
        chat_id=123,
        message_id=999,
        text="/cancel",
        reply_to_message_id=reply_to,
        reply_to_text=None,
        sender_id=123,
    )


def _assert_markup_cleared(edited_extra: dict[str, Any]) -> None:
    """Assert the terminal message has no inline keyboard."""
    markup = edited_extra.get("reply_markup", {})
    assert markup.get("inline_keyboard", []) == []


# ---------------------------------------------------------------------------
# Pending cancel: edits to terminal, clears markup, answers callback
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_callback_cancel_pending_edits_to_cancelled() -> None:
    """Pending Cancel edits the card to 'cancelled' and clears inline_keyboard."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    progress_id = 55
    progress_ref = MessageRef(channel_id=123, message_id=progress_id)
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
    await scheduler.enqueue_resume(
        chat_id=123,
        user_msg_id=10,
        text="queued prompt",
        resume_token=resume,
        progress_ref=progress_ref,
    )

    await handle_callback_cancel(cfg, _callback_query(progress_id), {}, scheduler)

    assert transport.edit_calls
    edited = transport.edit_calls[0]["message"]
    assert "cancelled" in edited.text.lower()
    _assert_markup_cleared(edited.extra)
    bot = cast(FakeBot, cfg.bot)
    assert bot.callback_calls[-1]["text"] == "dropped from queue."


@pytest.mark.anyio
async def test_callback_cancel_removes_only_selected_at_depth_two() -> None:
    """At queue depth > 1, Cancel removes only the selected job."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
    ref_a = MessageRef(channel_id=123, message_id=50)
    ref_b = MessageRef(channel_id=123, message_id=51)
    await scheduler.enqueue_resume(
        chat_id=123,
        user_msg_id=10,
        text="first",
        resume_token=resume,
        progress_ref=ref_a,
    )
    await scheduler.enqueue_resume(
        chat_id=123,
        user_msg_id=11,
        text="second",
        resume_token=resume,
        progress_ref=ref_b,
    )

    # Cancel the second (progress_id=51)
    await handle_callback_cancel(cfg, _callback_query(51), {}, scheduler)

    # Second is gone
    assert await scheduler.get_queued(123, 51) is None
    # First remains
    assert await scheduler.get_queued(123, 50) is not None


@pytest.mark.anyio
async def test_callback_cancel_stale_is_idempotent() -> None:
    """A repeated Cancel after success is NOT_FOUND and causes no second edit."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    progress_id = 55
    progress_ref = MessageRef(channel_id=123, message_id=progress_id)
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
    await scheduler.enqueue_resume(
        chat_id=123,
        user_msg_id=10,
        text="queued prompt",
        resume_token=resume,
        progress_ref=progress_ref,
    )

    # First cancel: success
    await handle_callback_cancel(cfg, _callback_query(progress_id), {}, scheduler)
    assert len(transport.edit_calls) == 1

    # Second cancel: stale, no extra edit
    await handle_callback_cancel(cfg, _callback_query(progress_id), {}, scheduler)
    assert len(transport.edit_calls) == 1  # no second edit

    bot = cast(FakeBot, cfg.bot)
    # Last callback answer should say "nothing is currently running"
    assert "nothing" in bot.callback_calls[-1]["text"].lower()


# ---------------------------------------------------------------------------
# ALREADY_CLAIMED: answer "already started", no predecessor cancellation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_callback_cancel_already_claimed_answers_started() -> None:
    """ALREADY_CLAIMED answers 'already started.' without touching any task."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    progress_id = 55
    progress_ref = MessageRef(channel_id=123, message_id=progress_id)
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")

    # Simulate claimed state.
    from collections import deque

    from takopi.scheduler import ThreadJob

    job = ThreadJob(
        chat_id=123,
        user_msg_id=10,
        text="queued prompt",
        resume_token=resume,
        progress_ref=progress_ref,
    )
    scheduler._claimed_by_progress[(123, 55)] = job
    _ = deque  # suppress unused

    # A predecessor running task exists but must NOT be cancelled.
    predecessor = RunningTask(resume=resume)
    predecessor_ref = MessageRef(channel_id=123, message_id=7)
    running_tasks = {predecessor_ref: predecessor}

    await handle_callback_cancel(
        cfg, _callback_query(progress_id), running_tasks, scheduler
    )

    assert predecessor.cancel_requested.is_set() is False
    bot = cast(FakeBot, cfg.bot)
    assert bot.callback_calls[-1]["text"] == "already started."


# ---------------------------------------------------------------------------
# Active-run cancel: the exact progress ref is now a RunningTask
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_callback_cancel_active_task_sets_cancel_event() -> None:
    """When the exact progress ref is a RunningTask, the active path cancels it."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    progress_id = 55
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
    task = RunningTask(resume=resume)
    running_tasks = {MessageRef(channel_id=123, message_id=progress_id): task}

    await handle_callback_cancel(
        cfg, _callback_query(progress_id), running_tasks, scheduler
    )

    assert task.cancel_requested.is_set() is True
    bot = cast(FakeBot, cfg.bot)
    assert bot.callback_calls[-1]["text"] == "cancelling..."


# ---------------------------------------------------------------------------
# Typed /cancel shares semantics with callback
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_typed_cancel_pending_edits_to_cancelled() -> None:
    """Typed /cancel on a pending job edits the card and answers via reply."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    progress_id = 55
    progress_ref = MessageRef(channel_id=123, message_id=progress_id)
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
    await scheduler.enqueue_resume(
        chat_id=123,
        user_msg_id=10,
        text="queued prompt",
        resume_token=resume,
        progress_ref=progress_ref,
    )

    await handle_cancel(cfg, _typed_cancel_msg(progress_id), {}, scheduler)

    assert transport.edit_calls
    edited = transport.edit_calls[0]["message"]
    assert "cancelled" in edited.text.lower()


@pytest.mark.anyio
async def test_typed_cancel_already_claimed_replies_started() -> None:
    """Typed /cancel on an already-claimed job replies 'already started.'"""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    progress_id = 55
    resume = ResumeToken(engine=CODEX_ENGINE, value="sid")

    from takopi.scheduler import ThreadJob

    job = ThreadJob(
        chat_id=123,
        user_msg_id=10,
        text="queued prompt",
        resume_token=resume,
        progress_ref=MessageRef(channel_id=123, message_id=55),
    )
    scheduler._claimed_by_progress[(123, 55)] = job

    await handle_cancel(cfg, _typed_cancel_msg(progress_id), {}, scheduler)

    assert transport.send_calls
    reply_text = transport.send_calls[-1]["message"].text.lower()
    assert "already started" in reply_text


# ---------------------------------------------------------------------------
# Scheduler observer presentation tests: claim edits to starting, failure edits to error
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_claim_observer_edits_card_to_starting() -> None:
    """on_job_claimed edits the queued card to 'starting' before run_job."""
    import anyio

    from takopi.scheduler import ThreadJob
    from takopi.telegram.loop import _make_scheduler_observers

    transport = FakeTransport()
    cfg = make_cfg(transport)

    claimed = anyio.Event()
    release = anyio.Event()

    async def _run_job(job: ThreadJob) -> None:
        claimed.set()
        await release.wait()

    on_claimed, _on_failed = _make_scheduler_observers(cfg, None)  # type: ignore[arg-type]

    async with anyio.create_task_group() as tg:
        from takopi.scheduler import ThreadScheduler

        scheduler = ThreadScheduler(
            task_group=tg,
            run_job=_run_job,
            on_job_claimed=on_claimed,
        )
        progress_ref = MessageRef(channel_id=123, message_id=55)
        resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
        await scheduler.enqueue_resume(
            chat_id=123,
            user_msg_id=10,
            text="queued prompt",
            resume_token=resume,
            progress_ref=progress_ref,
        )

        with anyio.fail_after(5):
            await claimed.wait()

        # The claim observer should have edited the card to "starting"
        assert transport.edit_calls
        edited = transport.edit_calls[0]["message"]
        assert "starting" in edited.text.lower()

        release.set()


@pytest.mark.anyio
async def test_failure_observer_edits_card_to_error() -> None:
    """on_job_failed edits the card to a terminal error and FIFO continues."""
    import anyio

    from takopi.scheduler import ThreadJob
    from takopi.telegram.loop import _make_scheduler_observers

    transport = FakeTransport()
    cfg = make_cfg(transport)

    ran: list[str] = []

    async def _run_job(job: ThreadJob) -> None:
        ran.append(job.text)
        if job.text == "boom":
            raise RuntimeError("something broke")

    _on_claimed, on_failed = _make_scheduler_observers(cfg, None)  # type: ignore[arg-type]

    async with anyio.create_task_group() as tg:
        from takopi.scheduler import ThreadScheduler

        scheduler = ThreadScheduler(
            task_group=tg,
            run_job=_run_job,
            on_job_failed=on_failed,
        )
        resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
        await scheduler.enqueue_resume(
            chat_id=123,
            user_msg_id=10,
            text="boom",
            resume_token=resume,
            progress_ref=MessageRef(channel_id=123, message_id=50),
        )
        await scheduler.enqueue_resume(
            chat_id=123,
            user_msg_id=11,
            text="ok",
            resume_token=resume,
            progress_ref=MessageRef(channel_id=123, message_id=51),
        )

        with anyio.fail_after(5):
            while len(ran) < 2:
                await anyio.wait_all_tasks_blocked()

    assert ran == ["boom", "ok"]
    # The failed job's card should have been edited to error
    error_edits = [
        e for e in transport.edit_calls if "error" in e["message"].text.lower()
    ]
    assert error_edits
    assert "something broke" in error_edits[0]["message"].text


@pytest.mark.anyio
async def test_edit_progress_label_without_progress_ref_is_noop() -> None:
    """_edit_progress_label is a no-op when job has no progress_ref."""
    from takopi.scheduler import ThreadJob
    from takopi.telegram.loop import _edit_progress_label

    transport = FakeTransport()
    cfg = make_cfg(transport)
    job = ThreadJob(
        chat_id=123,
        user_msg_id=10,
        text="queued",
        resume_token=ResumeToken(engine=CODEX_ENGINE, value="sid"),
        progress_ref=None,
    )
    await _edit_progress_label(cfg, job, label="starting")
    assert transport.edit_calls == []


@pytest.mark.anyio
async def test_failure_observer_without_progress_ref_is_noop() -> None:
    """on_job_failed is a no-op when job has no progress_ref."""
    from takopi.scheduler import ThreadJob
    from takopi.telegram.loop import _make_scheduler_observers

    transport = FakeTransport()
    cfg = make_cfg(transport)
    _on_claimed, on_failed = _make_scheduler_observers(cfg, None)  # type: ignore[arg-type]
    job = ThreadJob(
        chat_id=123,
        user_msg_id=10,
        text="queued",
        resume_token=ResumeToken(engine=CODEX_ENGINE, value="sid"),
        progress_ref=None,
    )
    await on_failed(job, RuntimeError("test"))
    assert transport.edit_calls == []


@pytest.mark.anyio
async def test_handle_enqueue_failure_edits_card() -> None:
    from takopi.logging import get_logger
    from takopi.telegram.loop import _handle_enqueue_failure

    transport = FakeTransport()
    progress_ref = MessageRef(channel_id=123, message_id=55)

    await _handle_enqueue_failure(
        get_logger(),
        transport=transport,
        engine=CODEX_ENGINE,
        chat_id=123,
        user_msg_id=10,
        prompt_text="do important work",
        progress_ref=progress_ref,
        exc=RuntimeError("queue is full"),
    )

    assert transport.edit_calls
    text = transport.edit_calls[0]["message"].text.lower()
    assert "error" in text
    assert "could not queue" in text
    assert "queue is full" in text
    assert "do important work" in text


@pytest.mark.anyio
async def test_handle_enqueue_failure_without_progress_ref_is_noop() -> None:
    """_handle_enqueue_failure with no progress_ref logs but does not edit."""
    from takopi.logging import get_logger
    from takopi.telegram.loop import _handle_enqueue_failure

    transport = FakeTransport()
    await _handle_enqueue_failure(
        get_logger(),
        transport=transport,
        engine=CODEX_ENGINE,
        chat_id=123,
        user_msg_id=10,
        prompt_text="do important work",
        progress_ref=None,
        exc=RuntimeError(""),
    )
    assert transport.edit_calls == []


# ---------------------------------------------------------------------------
# handle_cancel status branches
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_handle_cancel_already_claimed_says_started() -> None:
    """handle_cancel on an already-claimed job answers 'already started'."""
    from takopi.model import ResumeToken
    from takopi.scheduler import ThreadJob
    from takopi.transport import MessageRef

    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    # Manually move a job to claimed state
    job = ThreadJob(
        chat_id=123,
        user_msg_id=10,
        text="claimed-prompt",
        resume_token=ResumeToken(engine=CODEX_ENGINE, value="sid"),
        progress_ref=MessageRef(channel_id=123, message_id=55),
    )
    progress_key = (123, 55)
    async with scheduler._lock:
        scheduler._claimed_by_progress[progress_key] = job

    msg = _typed_cancel_msg(55)
    await handle_cancel(cfg, msg, {}, scheduler)

    sent = [c["message"].text for c in transport.send_calls]
    assert sent
    assert "already started" in sent[-1].lower()


@pytest.mark.anyio
async def test_handle_cancel_not_found_says_nothing_running() -> None:
    """handle_cancel on an unknown job answers 'nothing is currently running'."""
    transport = FakeTransport()
    cfg = make_cfg(transport)

    scheduler = _make_scheduler()
    msg = _typed_cancel_msg(999)
    await handle_cancel(cfg, msg, {}, scheduler)

    sent = [c["message"].text for c in transport.send_calls]
    assert sent
    assert "nothing is currently running" in sent[-1].lower()


# ---------------------------------------------------------------------------
# handle_callback_steer defensive branches
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_steer_without_scheduler_answers_no_queue() -> None:
    """handle_callback_steer with no scheduler answers 'no queue is available'."""
    from takopi.telegram.commands.cancel import handle_callback_steer

    transport = FakeTransport()
    cfg = make_cfg(transport)
    bot = cast(FakeBot, cfg.bot)
    query = _callback_query(55, data="takopi:steer")
    await handle_callback_steer(cfg, query, {})  # type: ignore[arg-type]

    assert bot.callback_calls
    assert "no queue" in bot.callback_calls[-1]["text"].lower()


@pytest.mark.anyio
async def test_steer_unknown_job_answers_not_queued() -> None:
    """handle_callback_steer for an unknown job answers 'not queued'."""
    from takopi.telegram.commands.cancel import handle_callback_steer

    transport = FakeTransport()
    cfg = make_cfg(transport)
    bot = cast(FakeBot, cfg.bot)
    scheduler = _make_scheduler()
    query = _callback_query(999, data="takopi:steer")
    await handle_callback_steer(cfg, query, {}, scheduler)  # type: ignore[arg-type]

    assert bot.callback_calls
    assert "not queued" in bot.callback_calls[-1]["text"].lower()


@pytest.mark.anyio
async def test_steer_no_matching_control_answers_not_steerable() -> None:
    """handle_callback_steer when no matching active turn answers 'not steerable'."""
    from takopi.telegram.commands.cancel import handle_callback_steer
    from takopi.transport import MessageRef as MsgRef

    transport = FakeTransport()
    cfg = make_cfg(transport)
    bot = cast(FakeBot, cfg.bot)
    scheduler = _make_scheduler()
    # Queue a job so get_queued finds it
    job_resume = ResumeToken(engine=CODEX_ENGINE, value="sid")
    await scheduler.enqueue_resume(
        chat_id=123,
        user_msg_id=10,
        text="queued",
        resume_token=job_resume,
        progress_ref=MsgRef(channel_id=123, message_id=55),
    )
    query = _callback_query(55, data="takopi:steer")
    # No matching running task with same resume token
    await handle_callback_steer(cfg, query, {}, scheduler)  # type: ignore[arg-type]
    assert bot.callback_calls
    assert "not steerable" in bot.callback_calls[-1]["text"].lower()


@pytest.mark.anyio
async def test_steer_already_claimed_answers_left_queue() -> None:
    """handle_callback_steer when job was claimed between get and claim."""

    from takopi.model import ResumeToken as RT
    from takopi.runner_bridge import RunningTask
    from takopi.scheduler import ThreadJob
    from takopi.telegram.commands.cancel import handle_callback_steer
    from takopi.transport import MessageRef as MsgRef

    transport = FakeTransport()
    cfg = make_cfg(transport)
    bot = cast(FakeBot, cfg.bot)

    # Use a mock scheduler where get_queued returns a job but claim_queued returns None
    job_resume = RT(engine=CODEX_ENGINE, value="sid")
    job = ThreadJob(
        chat_id=123,
        user_msg_id=10,
        text="claimed",
        resume_token=job_resume,
        progress_ref=MsgRef(channel_id=123, message_id=55),
    )

    class _RaceScheduler:
        async def get_queued(self, chat_id, msg_id):
            return job

        async def claim_queued(self, chat_id, msg_id):
            return None

    task = RunningTask()
    task.resume = job_resume
    task.control = object()  # type: ignore[assignment]
    running_tasks: dict = {MsgRef(channel_id=123, message_id=55): task}

    query = _callback_query(55, data="takopi:steer")
    await handle_callback_steer(cfg, query, running_tasks, _RaceScheduler())  # type: ignore[arg-type]

    assert bot.callback_calls
    assert "already left" in bot.callback_calls[-1]["text"].lower()
