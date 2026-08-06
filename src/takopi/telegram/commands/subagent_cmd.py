"""Sticky /subagent command (chat-scoped subagent preference)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..chat_prefs import ChatPrefsStore
from ..files import split_command_args
from ..types import TelegramIncomingMessage
from .overrides import require_admin_or_private
from .reply import make_reply

if TYPE_CHECKING:
    from ..bridge import TelegramBridgeConfig

SUBAGENT_USAGE = (
    "usage: `/subagent`, `/subagent set <name>`, `/subagent off`, or `/subagent clear`\n"
    "one-shot: `/codex /subagent <name> <prompt>` or `/codex --subagent <name> <prompt>`"
)

_STICKY_ACTIONS = frozenset({"set", "off", "clear", "show"})


def is_sticky_subagent_args(args_text: str) -> bool:
    """True when /subagent is the sticky preference command, not a one-shot."""
    tokens = split_command_args(args_text)
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0].lower() in {"off", "clear", "show"}:
        return True
    return len(tokens) == 2 and tokens[0].lower() == "set"


async def _handle_subagent_command(
    cfg: TelegramBridgeConfig,
    msg: TelegramIncomingMessage,
    args_text: str,
    chat_prefs: ChatPrefsStore | None,
) -> None:
    reply = make_reply(cfg, msg)
    tokens = split_command_args(args_text)
    head = tokens[0].lower() if tokens else "show"

    if head in {"show", ""}:
        if chat_prefs is None:
            await reply(text="subagent: unavailable (no config path).")
            return
        current = await chat_prefs.get_subagent(msg.chat_id)
        if current is None:
            await reply(text="subagent: none (default)")
        else:
            await reply(text=f"subagent: `{current}`")
        return

    if head in {"set", "off", "clear"}:
        if not await require_admin_or_private(
            cfg,
            msg,
            missing_sender="cannot verify sender for subagent preference.",
            failed_member="failed to verify subagent permissions.",
            denied="changing subagent is restricted to group admins.",
        ):
            return
        if chat_prefs is None:
            await reply(text="subagent is unavailable (no config path).")
            return
        if head == "set":
            if len(tokens) < 2:
                await reply(text=SUBAGENT_USAGE)
                return
            name = tokens[1]
        else:  # off / clear
            name = None
        await chat_prefs.set_subagent(msg.chat_id, name)
        if name is None:
            await reply(text="subagent cleared.")
        else:
            await reply(text=f"subagent set to `{name}`.")
        return

    # Free-form args fall through to the loop as a one-shot directive.
    await reply(text=SUBAGENT_USAGE)
