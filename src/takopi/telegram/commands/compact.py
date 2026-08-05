"""Compact command handler: session resolution, engine routing, and confirmation flow.

Extracted from loop.py (SRP). Handles:
- /compact dispatch from any reply context and any ordering with engine selectors.
- Engine precedence: explicit selector > reply-footer token > chat/topic default.
- Token precedence: running-task token (awaited) > reply footer > topic/chat store.
- None-support confirmation flow with inline keyboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..loop import ResumeResolver, TelegramLoopState
    from ...model import EngineId, ResumeToken
    from ...scheduler import ThreadScheduler
    from ...context import RunContext
    from ..bridge import TelegramBridgeConfig
    from ..types import TelegramIncomingMessage
    from collections.abc import Callable, Mapping
    from collections.abc import Awaitable


@dataclass(frozen=True, slots=True)
class PendingCompactConfirm:
    """Stored state for a pending compact-confirmation callback."""

    resume_token: ResumeToken
    instructions: str | None
    user_msg_id: int
    thread_id: int | None
    session_key: tuple[int, int | None] | None


async def handle_compact_command(
    instructions: str | None,
    engine_override: EngineId | None,
    *,
    cfg: TelegramBridgeConfig,
    msg: TelegramIncomingMessage,
    reply: Callable[..., Awaitable[None]],
    scheduler: ThreadScheduler,
    resume_resolver: ResumeResolver,
    topic_store: object | None,
    chat_session_store: object | None,
    topic_key: tuple[int, int] | None,
    chat_session_key: tuple[int, int | None] | None,
    reply_id: int | None,
    running_tasks: Mapping[object, object],
    state: TelegramLoopState,
    ambient_context: RunContext | None,
    force_handoff: bool = False,
) -> None:
    """Resolve an existing session and enqueue a compact job on the scheduler.

    Engine precedence: explicit selector > reply-footer token > chat/topic default.
    Token precedence: running-task token (awaited for compact) > reply footer >
    topic store > chat store.
    """
    from ..engine_defaults import resolve_engine_for_message
    from ...compact import (
        get_compact_support,
        warn_if_dropping_instructions,
    )
    from ..bridge import COMPACT_CONFIRM_MARKUP, send_plain
    from ..loop import _wait_for_resume
    from ...transport import MessageRef

    chat_id = msg.chat_id
    user_msg_id = msg.message_id

    # --- Engine resolution with precedence ---
    # Extract resume token from the replied-to message footer (if any).
    reply_resume: ResumeToken | None = None
    if msg.reply_to_text:
        reply_resume = cfg.runtime.extract_resume(msg.reply_to_text)

    # Determine engine: explicit selector > reply-footer engine > chat/topic default.
    if engine_override is not None:
        engine = engine_override
    elif reply_resume is not None:
        engine = reply_resume.engine
    else:
        engine_resolution = await resolve_engine_for_message(
            runtime=cfg.runtime,
            context=ambient_context,
            explicit_engine=None,
            chat_id=chat_id,
            topic_key=topic_key,
            topic_store=topic_store,  # type: ignore[arg-type]
            chat_prefs=state.chat_prefs,
        )
        engine = engine_resolution.engine

    # If selector present but footer engine mismatches, ignore footer token.
    footer_token: ResumeToken | None = None
    if reply_resume is not None and reply_resume.engine == engine:
        footer_token = reply_resume

    # --- Token resolution ---
    # Priority: running-task (awaited for compact) > reply footer > stores.
    resume_token: ResumeToken | None = None

    # Check running task first (await for compact mode).
    if reply_id is not None:
        ref = MessageRef(channel_id=chat_id, message_id=reply_id)
        running_task = running_tasks.get(ref)
        if running_task is not None:
            resume_token = await _wait_for_resume(running_task)

    if resume_token is None:
        resume_decision = await resume_resolver.resolve(
            resume_token=None,
            reply_id=reply_id,
            chat_id=chat_id,
            user_msg_id=user_msg_id,
            thread_id=msg.thread_id,
            chat_session_key=chat_session_key,
            topic_key=topic_key,
            engine_for_session=engine,
            prompt_text="",
            reply_resume=footer_token,
            for_compact=True,
        )
        resume_token = resume_decision.resume_token

    if resume_token is None:
        await reply(
            text=(
                "no active session to compact.\n"
                "reply to a Takopi progress/final message, "
                "or send a normal prompt first."
            )
        )
        return

    resolved = cfg.runtime.resolve_runner(
        resume_token=resume_token,
        engine_override=resume_token.engine,
    )
    runner = resolved.runner
    support = get_compact_support(runner)

    # --- Approval gate ---
    # Entered when: (a) /handoff (force_handoff=True, any engine), or
    # (b) /compact on an engine without true compaction (D1: handoff_only + none).
    # The flow: approve -> phase 1 (handoff summary in OLD session) ->
    # phase 2 (seed NEW session with summary) -> routing flips.
    if force_handoff or not support.true_compaction:
        if force_handoff and support.true_compaction:
            # /handoff on a compaction-capable engine: neutral wording
            # (do NOT claim the engine "cannot compact").
            prefix = (
                f"Start a NEW {resume_token.engine} session with a handoff "
                "summary instead of compacting in place?\n\n"
            )
        elif support.mode == "none":
            prefix = f"{resume_token.engine} does not support compaction at all.\n\n"
        else:
            prefix = f"{resume_token.engine} cannot compact natively.\n\n"
        text = (
            f"{prefix}"
            "Takopi will:\n"
            "1. Ask the agent for a handoff summary,\n"
            "2. Start a NEW session seeded with it,\n"
            "3. Route future messages to the new session.\n\n"
            "The old session stays available but is no longer default.\n\n"
            "Approve handoff?"
        )
        ref = await send_plain(
            cfg.exec_cfg.transport,
            chat_id=chat_id,
            user_msg_id=user_msg_id,
            text=text,
            notify=False,
            thread_id=msg.thread_id,
            reply_markup=COMPACT_CONFIRM_MARKUP,
        )
        if ref is not None:
            confirm_key = (chat_id, ref.message_id)
            _supersede_pending(state, chat_id, msg.thread_id)
            state.pending_compact_confirms[confirm_key] = PendingCompactConfirm(
                resume_token=resume_token,
                instructions=instructions,
                user_msg_id=user_msg_id,
                thread_id=msg.thread_id,
                session_key=chat_session_key,
            )
        return

    # --- True-compaction engines: immediate compact path ---
    final_instructions = instructions
    if final_instructions and not support.accepts_instructions:
        warning = warn_if_dropping_instructions(resume_token.engine, final_instructions)
        if warning:
            await reply(text=warning)
        final_instructions = None

    from ...scheduler import ThreadJob

    job = ThreadJob(
        chat_id=chat_id,
        user_msg_id=user_msg_id,
        text="[compact]",
        resume_token=resume_token,
        context=None,
        thread_id=msg.thread_id,
        session_key=chat_session_key,
        progress_ref=None,
        plan=False,
        goal=None,
        kind="compact",
        compact_instructions=final_instructions,
    )
    await scheduler.enqueue(job)

    ack = f"compacting {resume_token.engine} session…"
    await send_plain(
        cfg.exec_cfg.transport,
        chat_id=chat_id,
        user_msg_id=user_msg_id,
        text=ack,
        notify=False,
        thread_id=msg.thread_id,
    )


def _supersede_pending(
    state: TelegramLoopState, chat_id: int, thread_id: int | None
) -> None:
    """Remove prior pending compact confirms for the same chat/thread."""
    to_remove = [
        key
        for key, pending in state.pending_compact_confirms.items()
        if key[0] == chat_id and pending.thread_id == thread_id
    ]
    for key in to_remove:
        state.pending_compact_confirms.pop(key, None)


async def handle_compact_confirm_callback(
    cfg: TelegramBridgeConfig,
    query: object,
    state: TelegramLoopState,
    scheduler: ThreadScheduler,
    *,
    confirmed: bool,
) -> None:
    """Handle the compact confirm/decline inline-button callback."""
    from ...markdown import MarkdownParts
    from ...scheduler import ThreadJob
    from ...transport import MessageRef, RenderedMessage
    from ..render import prepare_telegram
    from ..types import TelegramCallbackQuery

    q: TelegramCallbackQuery = query  # type: ignore[assignment]
    chat_id = q.chat_id
    message_id = q.message_id
    confirm_key = (chat_id, message_id)

    pending = state.pending_compact_confirms.pop(confirm_key, None)

    if pending is None:
        await cfg.bot.answer_callback_query(q.callback_query_id, text="request expired")
        return

    # Edit the confirmation message to clear buttons.
    label = "approved — creating handoff summary…" if confirmed else "cancelled"
    rendered_text, entities = prepare_telegram(MarkdownParts(header=label))
    await cfg.exec_cfg.transport.edit(
        ref=MessageRef(channel_id=chat_id, message_id=message_id),
        message=RenderedMessage(text=rendered_text, extra={"entities": entities}),
    )
    if confirmed:
        job = ThreadJob(
            chat_id=chat_id,
            user_msg_id=pending.user_msg_id,
            text="[handoff]",
            resume_token=pending.resume_token,
            context=None,
            thread_id=pending.thread_id,
            session_key=pending.session_key,
            progress_ref=None,
            plan=False,
            goal=None,
            kind="handoff",
            compact_instructions=pending.instructions,
        )
        await cfg.bot.answer_callback_query(q.callback_query_id, text="sending…")
        await scheduler.enqueue(job)
    else:
        await cfg.bot.answer_callback_query(q.callback_query_id, text="cancelled")
