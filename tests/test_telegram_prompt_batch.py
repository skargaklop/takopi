from __future__ import annotations

import anyio
import pytest

from takopi.telegram.loop import _PendingPrompt, PromptInputBatcher
from takopi.telegram.prompt_batch import (
    PromptBatchPart,
    PromptBatchSettings,
    join_prompt_parts,
    should_batch_text,
)
from takopi.telegram.types import TelegramIncomingMessage


def _pending(message_id: int, text: str, **kwargs) -> _PendingPrompt:
    msg = TelegramIncomingMessage(
        transport="telegram",
        chat_id=123,
        message_id=message_id,
        text=text,
        reply_to_message_id=kwargs.pop("reply_to_message_id", None),
        reply_to_text=None,
        sender_id=kwargs.pop("sender_id", 321),
        thread_id=kwargs.pop("thread_id", None),
    )
    return _PendingPrompt(
        msg=msg,
        text=text,
        ambient_context=None,
        chat_project=None,
        topic_key=None,
        chat_session_key=None,
        reply_ref=None,
        reply_id=msg.reply_to_message_id,
        is_voice_transcribed=False,
        forwards=[],
    )


def test_batch_plain_text_when_enabled() -> None:
    settings = PromptBatchSettings(enabled=True)
    assert should_batch_text("fix this bug", settings=settings) is True


def test_disabled_batcher_never_batches() -> None:
    settings = PromptBatchSettings(enabled=False)
    assert should_batch_text("fix this bug", settings=settings) is False
    assert should_batch_text("/codex fix this", settings=settings) is False


def test_control_commands_do_not_batch() -> None:
    settings = PromptBatchSettings(enabled=True)
    for text in (
        "/cancel",
        "/new",
        "/ctx",
        "/agent claude",
        "/model set x",
        "/reasoning high",
        "/trigger mentions",
        "/queue",
        "/file put a.txt",
        "/compact",
        "/topic proj",
    ):
        assert should_batch_text(text, settings=settings) is False


def test_prompt_directives_can_batch() -> None:
    settings = PromptBatchSettings(enabled=True)
    for text in (
        "/codex summarize",
        "/plan refactor",
        "/goal tests pass",
        "/project-alias do work",
        "@branch do work",
    ):
        assert should_batch_text(text, settings=settings) is True


def test_bare_plan_goal_do_not_batch() -> None:
    settings = PromptBatchSettings(enabled=True)
    assert should_batch_text("/plan", settings=settings) is False
    assert should_batch_text("/goal", settings=settings) is False


def test_join_parts_in_message_id_order() -> None:
    parts = [
        PromptBatchPart(message_id=3, text="third"),
        PromptBatchPart(message_id=1, text="first"),
        PromptBatchPart(message_id=2, text="second"),
    ]
    assert join_prompt_parts(parts, separator="newline") == "first\nsecond\nthird"
    assert (
        join_prompt_parts(parts, separator="blank_line") == "first\n\nsecond\n\nthird"
    )


def test_join_parts_empty_list() -> None:
    assert join_prompt_parts([], separator="blank_line") == ""


@pytest.mark.anyio
async def test_batcher_flushes_one_pending_prompt_after_quiet_window() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.01,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=120_000,
            separator="blank_line",
        )

        assert batcher.schedule(_pending(1, "one")) is True
        assert batcher.schedule(_pending(2, "two")) is True
        await anyio.sleep(0.03)

        assert len(sent) == 1
        assert sent[0].text == "one\n\ntwo"
        assert sent[0].msg.message_id == 1


@pytest.mark.anyio
async def test_batcher_flushes_at_max_messages() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.05,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=2,
            max_chars=120_000,
            separator="newline",
        )

        assert batcher.schedule(_pending(1, "one")) is True
        assert batcher.schedule(_pending(2, "two")) is True
        await anyio.sleep(0.02)

        # Flushed because the message limit was hit, not because the debounce
        # window elapsed.
        assert len(sent) == 1
        assert sent[0].text == "one\ntwo"


@pytest.mark.anyio
async def test_batcher_flushes_at_max_chars() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.05,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=8,
            separator="blank_line",
        )

        assert batcher.schedule(_pending(1, "aaaa")) is True
        # Joining would exceed max_chars=8: flush the first batch, then start a
        # new batch with the current chunk.
        assert batcher.schedule(_pending(2, "bbbb")) is True
        await anyio.sleep(0.08)

        assert [item.text for item in sent] == ["aaaa", "bbbb"]


@pytest.mark.anyio
async def test_batcher_split_by_sender_and_chat() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.01,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=120_000,
            separator="blank_line",
        )

        assert batcher.schedule(_pending(1, "one", sender_id=1)) is True
        assert batcher.schedule(_pending(2, "two", sender_id=2)) is True
        await anyio.sleep(0.03)

        assert len(sent) == 2
        assert [item.text for item in sent] == ["one", "two"]


@pytest.mark.anyio
async def test_batcher_control_command_not_scheduled() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.01,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=120_000,
            separator="blank_line",
        )

        assert batcher.schedule(_pending(1, "/cancel")) is False
        assert batcher.schedule(_pending(2, "/new")) is False
        assert batcher.schedule(_pending(3, "")) is False
        await anyio.sleep(0.03)

        assert sent == []


@pytest.mark.anyio
async def test_batcher_disabled_never_schedules() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.0,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=120_000,
            separator="blank_line",
        )

        assert batcher.schedule(_pending(1, "hello")) is False
        await anyio.sleep(0.01)
        assert sent == []


@pytest.mark.anyio
async def test_batcher_cancel_drops_pending_batch() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.01,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=120_000,
            separator="blank_line",
        )

        key = batcher.key_for(_pending(1, "one"))
        assert key is not None
        assert batcher.schedule(_pending(1, "one")) is True
        assert batcher.schedule(_pending(2, "two")) is True
        batcher.cancel(key)
        await anyio.sleep(0.03)

        assert sent == []


@pytest.mark.anyio
async def test_batcher_voice_and_document_never_scheduled() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    async with anyio.create_task_group() as tg:
        batcher = PromptInputBatcher(
            task_group=tg,
            debounce_s=0.01,
            sleep=anyio.sleep,
            dispatch=dispatch,
            pending={},
            max_messages=8,
            max_chars=120_000,
            separator="blank_line",
        )

        voice_pending = _pending(1, "caption")
        voice_pending.msg = TelegramIncomingMessage(
            transport="telegram",
            chat_id=123,
            message_id=1,
            text="caption",
            reply_to_message_id=None,
            reply_to_text=None,
            sender_id=321,
            voice=object(),  # type: ignore[assignment]
        )
        assert batcher.schedule(voice_pending) is False

        doc_pending = _pending(2, "caption")
        doc_pending.msg = TelegramIncomingMessage(
            transport="telegram",
            chat_id=123,
            message_id=2,
            text="caption",
            reply_to_message_id=None,
            reply_to_text=None,
            sender_id=321,
            document=object(),  # type: ignore[assignment]
        )
        assert batcher.schedule(doc_pending) is False

        await anyio.sleep(0.03)
        assert sent == []
