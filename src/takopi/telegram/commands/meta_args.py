"""Classify Telegram slash-command args: meta (handled) vs free-form (fall through).

Only dual-mode commands (also message directives that start agent runs) should
return False for free-form so the main loop treats the full message as a prompt.
"""

from __future__ import annotations

from collections.abc import Collection

from .goal_cmd import is_sticky_goal_args
from .plan_cmd import is_sticky_plan_args

# Pure meta commands: never fall through to an agent prompt.
_PURE_META = frozenset(
    {
        "cancel",
        "file",
        "new",
        "ctx",
        "topic",
        "queue",
        "trigger",
        "model",
        "reasoning",
    }
)

# Dual-mode: sticky/help when meta; free-form starts a plan/goal agent run.
_DUAL_MODE = frozenset({"plan", "goal"})


def is_agent_meta_args(args_text: str, *, engine_ids: Collection[str]) -> bool:
    """/agent is always a meta command (show/set/clear/shorthand set)."""
    del args_text, engine_ids
    return True


def should_handle_as_meta_command(
    command_id: str,
    args_text: str,
    *,
    engine_ids: Collection[str] = (),
) -> bool:
    """Return True if builtin dispatch should handle the command (not fall through).

    Dual-mode commands that are also message directives:
    - ``/plan <prompt>`` / ``/goal <condition>`` fall through so the agent runs.
    Pure meta commands always return True (handler shows status, sets prefs, or usage).
    """
    del engine_ids
    cmd = command_id.lower()
    if cmd in _PURE_META:
        return True
    if cmd == "agent":
        return True
    if cmd == "plan":
        return is_sticky_plan_args(args_text)
    if cmd == "goal":
        return is_sticky_goal_args(args_text)
    # Unknown builtin id: let other dispatch paths decide.
    return True
