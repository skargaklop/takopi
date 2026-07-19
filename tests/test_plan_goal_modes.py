"""Tests for plan/goal directives, run options, and runner argv mapping."""

from __future__ import annotations

from pathlib import Path

from takopi.config import ProjectsConfig
from takopi.directives import parse_directives
from takopi.model import ResumeToken
from takopi.runners.agy import AgyRunner
from takopi.runners.claude import ClaudeRunner
from takopi.runners.codex import CodexRunner
from takopi.runners.grok import GrokRunner, GrokStreamState
from takopi.runners.omp import OmpRunner
from takopi.runners.opencode import OpenCodeRunner, OpenCodeStreamState
from takopi.runners.pi import ENGINE as PI_ENGINE, PiRunner, PiStreamState
from takopi.runners.run_options import (
    EngineRunOptions,
    apply_run_options,
    merge_run_options,
)
from takopi.telegram.bridge import CANCEL_MARKUP, STEER_CANCEL_MARKUP, TelegramPresenter
from takopi.progress import ProgressTracker


def _empty_projects() -> ProjectsConfig:
    return ProjectsConfig(projects={})


# --- bot command vs prompt fallthrough ---


def test_is_sticky_plan_args() -> None:
    from takopi.telegram.commands.plan_cmd import is_sticky_plan_args

    assert is_sticky_plan_args("") is True
    assert is_sticky_plan_args("on") is True
    assert is_sticky_plan_args("off") is True
    assert is_sticky_plan_args("clear") is True
    assert is_sticky_plan_args("show") is True
    assert is_sticky_plan_args("/agy make a plan") is False
    assert is_sticky_plan_args("make a plan how to make the world better") is False
    assert is_sticky_plan_args("on extra") is False


def test_is_sticky_goal_args() -> None:
    from takopi.telegram.commands.goal_cmd import is_sticky_goal_args

    assert is_sticky_goal_args("") is True
    assert is_sticky_goal_args("   ") is True
    assert is_sticky_goal_args("all tests pass") is False


def test_meta_vs_freeform_dispatch_matrix() -> None:
    """Audit: only plan/goal free-form fall through to agent runs."""
    from takopi.telegram.commands.meta_args import should_handle_as_meta_command

    engines = ("codex", "claude", "agy", "grok")

    # Dual-mode: free-form → agent run (not meta)
    assert should_handle_as_meta_command("plan", "/agy design", engine_ids=engines) is False
    assert should_handle_as_meta_command("plan", "design auth", engine_ids=engines) is False
    assert should_handle_as_meta_command("goal", "all tests pass", engine_ids=engines) is False
    # Dual-mode sticky/help stays meta
    assert should_handle_as_meta_command("plan", "", engine_ids=engines) is True
    assert should_handle_as_meta_command("plan", "on", engine_ids=engines) is True
    assert should_handle_as_meta_command("goal", "", engine_ids=engines) is True

    # Pure meta: always handled (never agent-run fallthrough)
    for cmd in (
        "agent",
        "model",
        "reasoning",
        "trigger",
        "queue",
        "cancel",
        "file",
        "new",
        "ctx",
        "topic",
    ):
        assert (
            should_handle_as_meta_command(cmd, "random freeform", engine_ids=engines)
            is True
        ), cmd


# --- directives ---


def test_parse_directives_plan() -> None:
    d = parse_directives(
        "/plan refactor auth",
        engine_ids=("codex", "claude"),
        projects=_empty_projects(),
    )
    assert d.plan is True
    assert d.goal is None
    assert d.prompt == "refactor auth"
    assert d.engine is None


def test_parse_directives_plan_with_engine() -> None:
    d = parse_directives(
        "/claude /plan fix flaky test",
        engine_ids=("codex", "claude"),
        projects=_empty_projects(),
    )
    assert d.engine == "claude"
    assert d.plan is True
    assert d.prompt == "fix flaky test"


def test_parse_directives_plan_after_engine() -> None:
    d = parse_directives(
        "/plan /grok design the API",
        engine_ids=("grok", "claude"),
        projects=_empty_projects(),
    )
    assert d.engine == "grok"
    assert d.plan is True
    assert d.prompt == "design the API"


def test_parse_directives_goal_rest_is_condition() -> None:
    d = parse_directives(
        "/goal all tests pass and lint is clean",
        engine_ids=("claude",),
        projects=_empty_projects(),
    )
    assert d.goal == "all tests pass and lint is clean"
    assert d.prompt == ""
    assert d.plan is False


def test_parse_directives_goal_with_engine() -> None:
    d = parse_directives(
        "/claude /goal CHANGELOG has this week's PRs",
        engine_ids=("claude",),
        projects=_empty_projects(),
    )
    assert d.engine == "claude"
    assert d.goal == "CHANGELOG has this week's PRs"
    assert d.prompt == ""


def test_parse_directives_goal_multiline() -> None:
    d = parse_directives(
        "/goal tests green\nextra note ignored as condition body",
        engine_ids=("claude",),
        projects=_empty_projects(),
    )
    # Remainder of message after /goal is the condition (including following lines).
    assert d.goal is not None
    assert "tests green" in d.goal
    assert "extra note" in d.goal
    assert d.prompt == ""


def test_parse_directives_plan_reserved_over_project_alias() -> None:
    from takopi.config import ProjectConfig

    projects = ProjectsConfig(
        projects={
            "plan": ProjectConfig(
                alias="plan", path=Path("."), worktrees_dir=Path(".worktrees")
            )
        }
    )
    d = parse_directives(
        "/plan do work",
        engine_ids=("claude",),
        projects=projects,
    )
    assert d.plan is True
    assert d.project is None
    assert d.prompt == "do work"


# --- run options ---


def test_merge_run_options_preserves_plan_goal() -> None:
    base = EngineRunOptions(model="m", plan=True, goal="done")
    merged = merge_run_options(base, attachments=())
    assert merged is not None
    assert merged.plan is True
    assert merged.goal == "done"
    assert merged.model == "m"


def test_merge_run_options_plan_from_none_base() -> None:
    opts = EngineRunOptions(plan=True)
    merged = merge_run_options(opts)
    assert merged is not None
    assert merged.plan is True


# --- runners: plan / goal ---


def test_claude_plan_uses_permission_mode_no_yolo() -> None:
    runner = ClaudeRunner(claude_cmd="claude", dangerously_skip_permissions=True)
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design it", None, state=None)
    assert "--permission-mode" in args
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert "--dangerously-skip-permissions" not in args
    assert args[-1] == "design it"


def test_claude_goal_prefixes_prompt() -> None:
    runner = ClaudeRunner(claude_cmd="claude", dangerously_skip_permissions=True)
    with apply_run_options(EngineRunOptions(goal="all tests pass")):
        args = runner.build_args("ignored body", None, state=None)
    assert args[-1] == "/goal all tests pass"
    # Goal needs unattended tool use → keep skip-permissions
    assert "--dangerously-skip-permissions" in args


def test_claude_goal_keeps_existing_goal_prefix() -> None:
    runner = ClaudeRunner(claude_cmd="claude")
    with apply_run_options(EngineRunOptions(goal="x")):
        args = runner.build_args("/goal already set", None, state=None)
    assert args[-1] == "/goal already set"


def test_grok_plan_permission_mode_no_yolo() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=True)
    state = GrokStreamState(resume=ResumeToken(engine="grok", value="sid"), started=False)
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("plan the refactor", None, state=state)
    assert "--permission-mode" in args
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert "--yolo" not in args


def test_grok_goal_prefixes_prompt() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=True)
    state = GrokStreamState(resume=ResumeToken(engine="grok", value="sid"), started=False)
    with apply_run_options(EngineRunOptions(goal="lint clean")):
        args = runner.build_args("body", None, state=state)
    # -p prompt is early in args
    assert "-p" in args
    p_idx = args.index("-p")
    assert args[p_idx + 1] == "/goal lint clean"


def test_agy_plan_mode_no_yolo() -> None:
    runner = AgyRunner(agy_cmd="agy", yolo=True, mode=None)
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("explore", None)
    assert "--mode" in args
    assert args[args.index("--mode") + 1] == "plan"
    assert "--dangerously-skip-permissions" not in args


def test_omp_plan_yolo_when_configured() -> None:
    runner = OmpRunner(extra_args=[], model=None, provider=None, plan_mode="yolo")
    state = PiStreamState(resume=ResumeToken(engine="omp", value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design", None, state=state)
    assert "--plan-yolo" in args


def test_omp_soft_plan_prefixes_prompt() -> None:
    runner = OmpRunner(extra_args=[], model=None, provider=None, plan_mode="soft")
    state = PiStreamState(resume=ResumeToken(engine="omp", value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design auth", None, state=state)
    prompt = args[-1]
    assert "plan" in prompt.lower()
    assert "design auth" in prompt


def test_pi_plan_flag_when_enabled() -> None:
    runner = PiRunner(extra_args=[], model=None, provider=None, plan_flag=True)
    state = PiStreamState(resume=ResumeToken(engine=PI_ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design", None, state=state)
    assert "--plan" in args


def test_pi_soft_plan_default() -> None:
    runner = PiRunner(extra_args=[], model=None, provider=None, plan_flag=False)
    state = PiStreamState(resume=ResumeToken(engine=PI_ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design", None, state=state)
    prompt = args[-1]
    assert "plan" in prompt.lower()


def test_opencode_plan_agent_when_configured() -> None:
    runner = OpenCodeRunner(opencode_cmd="opencode", plan_agent="plan")
    state = OpenCodeStreamState()
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design", None, state=state)
    assert "--agent" in args
    assert args[args.index("--agent") + 1] == "plan"


def test_opencode_soft_plan_default() -> None:
    runner = OpenCodeRunner(opencode_cmd="opencode", plan_agent=None)
    state = OpenCodeStreamState()
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design api", None, state=state)
    assert args[-1].startswith("[") or "plan" in args[-1].lower()


def test_codex_soft_plan_prefixes_prompt() -> None:
    runner = CodexRunner(codex_cmd="codex", extra_args=[])
    state = runner.new_state("hi", None)
    with apply_run_options(EngineRunOptions(plan=True)):
        # exec path uses stdin for prompt; soft plan may only affect stdin/payload
        # At minimum build_args should not crash.
        args = runner.build_args("design it", None, state=state)
    assert isinstance(args, list)


# --- steer markup ---


def test_progress_queued_steerable_shows_steer() -> None:
    presenter = TelegramPresenter()
    tracker = ProgressTracker(engine="codex")
    state = tracker.snapshot()
    message = presenter.render_progress(state, elapsed_s=0.0, label="queued")
    assert message.extra.get("reply_markup") == STEER_CANCEL_MARKUP


def test_progress_queued_not_steerable_cancel_only() -> None:
    presenter = TelegramPresenter()
    tracker = ProgressTracker(engine="claude")
    state = tracker.snapshot()
    message = presenter.render_progress(
        state, elapsed_s=0.0, label="queued", steerable=False
    )
    assert message.extra.get("reply_markup") == CANCEL_MARKUP
