"""/goal help (per-message goal uses the /goal directive on prompts)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...context import RunContext
from ..chat_prefs import ChatPrefsStore
from ..topic_state import TopicStateStore
from ..types import TelegramIncomingMessage
from .reply import make_reply

if TYPE_CHECKING:
    from ..bridge import TelegramBridgeConfig

GOAL_HELP = (
    "goal mode starts an autonomous loop until a condition is met "
    "(supported natively by Claude; best-effort on Grok).\n\n"
    "usage (message directive):\n"
    "`/goal all tests pass and lint is clean`\n"
    "`/claude /goal CHANGELOG has this week's PRs`\n\n"
    "tip: pair with unattended permissions (yolo / skip-permissions) so the "
    "loop is not blocked on tool approval."
)


async def _handle_goal_command(
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
    del ambient_context, topic_store, chat_prefs, resolved_scope, scope_chat_ids
    reply = make_reply(cfg, msg)
    condition = (args_text or "").strip()
    if not condition:
        await reply(text=GOAL_HELP)
        return
    # Bot slash command with args: treat as a directed prompt via error pointing
    # user to send as a normal message (directives need full resolve path).
    await reply(
        text=(
            "to start a goal run, send a normal message (not only the bot command):\n"
            f"`/goal {condition}`\n\n"
            "optionally prefix an engine: `/claude /goal {condition}`"
        )
    )
