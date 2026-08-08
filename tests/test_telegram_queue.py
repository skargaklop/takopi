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


def _callback_query(progress_id: int, data: str = "takopi:cancel") -> TelegramCallbackQuery:
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
        chat_id=123, user_msg_id=10, text="first", resume_token=resume,
        progress_ref=ref_a,
    )
    await scheduler.enqueue_resume(
        chat_id=123, user_msg_id=11, text="second", resume_token=resume,
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
        chat_id=123, user_msg_id=10, text="queued prompt",
        resume_token=resume, progress_ref=progress_ref,
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
        chat_id=123, user_msg_id=10, text="queued prompt",
        resume_token=resume, progress_ref=progress_ref,
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
        chat_id=123, user_msg_id=10, text="queued prompt",
        resume_token=resume, progress_ref=progress_ref,
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
        chat_id=123, user_msg_id=10, text="queued prompt",
        resume_token=resume, progress_ref=MessageRef(channel_id=123, message_id=55),
    )
    scheduler._claimed_by_progress[(123, 55)] = job

    await handle_cancel(cfg, _typed_cancel_msg(progress_id), {}, scheduler)

    assert transport.send_calls
    reply_text = transport.send_calls[-1]["message"].text.lower()
    assert "already started" in reply_text
