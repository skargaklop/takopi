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
    plan: bool = False
    goal: str | None = None


def merge_run_options(
    base: EngineRunOptions | None,
    *,
    attachments: Sequence[PromptAttachment] | None = None,
    plan: bool | None = None,
    goal: str | None = None,
    model: str | None = None,
    reasoning: str | None = None,
) -> EngineRunOptions | None:
    if (
        base is None
        and not attachments
        and plan is None
        and goal is None
        and model is None
        and reasoning is None
    ):
        return None
    base_atts = base.attachments if base is not None else ()
    new_atts = tuple(attachments) if attachments is not None else base_atts
    new_plan = bool(base.plan) if base is not None else False
    if plan is not None:
        new_plan = bool(plan)
    new_goal = base.goal if base is not None else None
    if goal is not None:
        cleaned = goal.strip()
        new_goal = cleaned or None
    new_model = base.model if base is not None else None
    if model is not None:
        new_model = model
    new_reasoning = base.reasoning if base is not None else None
    if reasoning is not None:
        new_reasoning = reasoning
    opts = EngineRunOptions(
        model=new_model,
        reasoning=new_reasoning,
        attachments=new_atts,
        plan=new_plan,
        goal=new_goal,
    )
    if (
        opts.model is None
        and opts.reasoning is None
        and not opts.attachments
        and not opts.plan
        and opts.goal is None
    ):
        return None
    return opts


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
