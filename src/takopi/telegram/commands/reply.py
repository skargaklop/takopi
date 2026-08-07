from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Protocol

from ..bridge import send_plain
from ...transport import MessageRef
from ..types import TelegramIncomingMessage

if TYPE_CHECKING:
    from ..bridge import TelegramBridgeConfig


class ReplyCallable(Protocol):
    """Callable returned by :func:`make_reply` for sending Telegram replies."""

    async def __call__(
        self,
        *,
        text: str,
        notify: bool = ...,
        thread_id: int | None = ...,
        reply_markup: dict | None = ...,
    ) -> MessageRef | None: ...


def make_reply(
    cfg: TelegramBridgeConfig, msg: TelegramIncomingMessage
) -> ReplyCallable:
    return partial(
        send_plain,
        cfg.exec_cfg.transport,
        chat_id=msg.chat_id,
        user_msg_id=msg.message_id,
        thread_id=msg.thread_id,
    )
