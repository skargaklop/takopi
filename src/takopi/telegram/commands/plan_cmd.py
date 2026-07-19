"""Sticky /plan on|off scope command (agent plan mode preference)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...context import RunContext
from ..chat_prefs import ChatPrefsStore
from ..files import split_command_args
from ..topic_state import TopicStateStore
from ..topics import _topic_key
from ..types import TelegramIncomingMessage
from .overrides import require_admin_or_private
from .reply import make_reply

if TYPE_CHECKING:
    from ..bridge import TelegramBridgeConfig

PLAN_USAGE = "usage: `/plan`, `/plan on`, `/plan off`, or `/plan clear`"


async def _resolve_sticky_plan(
    *,
    chat_id: int,
    tkey: tuple[int, int] | None,
    topic_store: TopicStateStore | None,
    chat_prefs: ChatPrefsStore | None,
) -> tuple[bool | None, str]:
    if tkey is not None and topic_store is not None:
        topic_val = await topic_store.get_plan_mode(tkey[0], tkey[1])
        if topic_val is not None:
            return topic_val, "topic"
    if chat_prefs is not None:
        chat_val = await chat_prefs.get_plan_mode(chat_id)
        if chat_val is not None:
            return chat_val, "chat"
    return None, "default"


async def _handle_plan_command(
    cfg: TelegramBridgeConfig,
    msg: TelegramIncomingMessage,
    args_text: str,
    ambient_context: RunContext | None,
    topic_store: TopicStateStore | None,
    chat_prefs: ChatPrefsStore | None,
    *,
    resolved_scope: str | None = None,
    scope_chat_ids: frozenset[int] | None = None,
) -> None:
    del ambient_context, resolved_scope  # unused; signature matches other commands
    reply = make_reply(cfg, msg)
    tkey = (
        _topic_key(msg, cfg, scope_chat_ids=scope_chat_ids)
        if topic_store is not None
        else None
    )
    tokens = split_command_args(args_text)
    action = tokens[0].lower() if tokens else "show"

    if action in {"show", ""}:
        value, source = await _resolve_sticky_plan(
            chat_id=msg.chat_id,
            tkey=tkey,
            topic_store=topic_store,
            chat_prefs=chat_prefs,
        )
        if value is None:
            await reply(text=f"plan mode: off (default)\nsource: {source}")
        else:
            state = "on" if value else "off"
            await reply(text=f"plan mode: {state}\nsource: {source}")
        return

    if action in {"on", "off", "clear"}:
        if not await require_admin_or_private(
            cfg,
            msg,
            missing_sender="cannot verify sender for plan mode.",
            failed_member="failed to verify plan mode permissions.",
            denied="changing plan mode is restricted to group admins.",
        ):
            return
        if action == "clear":
            enabled: bool | None = None
        else:
            enabled = action == "on"
        if tkey is not None and topic_store is not None:
            await topic_store.set_plan_mode(tkey[0], tkey[1], enabled)
            if enabled is None:
                await reply(text="topic plan mode cleared (using chat/default).")
            else:
                await reply(text=f"topic plan mode set to `{'on' if enabled else 'off'}`.")
            return
        if chat_prefs is None:
            await reply(text="chat plan mode is unavailable (no config path).")
            return
        await chat_prefs.set_plan_mode(msg.chat_id, enabled)
        if enabled is None:
            await reply(text="chat plan mode cleared.")
        else:
            await reply(text=f"chat plan mode set to `{'on' if enabled else 'off'}`.")
        return

    await reply(text=PLAN_USAGE)
