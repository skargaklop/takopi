from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptAttachment:
    """Project-relative media for agents (Layer A path + Layer B CLI flags)."""

    rel_path: str
    abs_path: str
    mime_type: str | None = None
    kind: str = "image"  # image | file


@dataclass(frozen=True, slots=True)
class EngineRunOptions:
    model: str | None = None
    reasoning: str | None = None
    attachments: tuple[PromptAttachment, ...] = ()


def merge_run_options(
    base: EngineRunOptions | None,
    *,
    attachments: Sequence[PromptAttachment] | None = None,
) -> EngineRunOptions | None:
    if base is None and not attachments:
        return None
    base_atts = base.attachments if base is not None else ()
    new_atts = tuple(attachments) if attachments is not None else base_atts
    if base is None:
        return EngineRunOptions(attachments=new_atts)
    return EngineRunOptions(
        model=base.model,
        reasoning=base.reasoning,
        attachments=new_atts,
    )


_RUN_OPTIONS: ContextVar[EngineRunOptions | None] = ContextVar(
    "takopi.engine_run_options", default=None
)


def get_run_options() -> EngineRunOptions | None:
    return _RUN_OPTIONS.get()


def set_run_options(options: EngineRunOptions | None) -> Token:
    return _RUN_OPTIONS.set(options)


def reset_run_options(token: Token) -> None:
    _RUN_OPTIONS.reset(token)


@contextmanager
def apply_run_options(options: EngineRunOptions | None) -> Iterator[None]:
    token = set_run_options(options)
    try:
        yield
    finally:
        reset_run_options(token)
