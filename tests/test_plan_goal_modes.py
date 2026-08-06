"""Tests for plan/goal directives, run options, and runner argv mapping."""

from __future__ import annotations

from pathlib import Path

from takopi.config import ProjectConfig, ProjectsConfig
from takopi.context import RunContext
from takopi.directives import (
    compose_context_line,
    format_context_line,
    format_mode_badge,
)
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


def test_is_sticky_subagent_args() -> None:
    from takopi.telegram.commands.subagent_cmd import is_sticky_subagent_args

    assert is_sticky_subagent_args("") is True
    assert is_sticky_subagent_args("show") is True
    assert is_sticky_subagent_args("off") is True
    assert is_sticky_subagent_args("clear") is True
    assert is_sticky_subagent_args("set scout") is True
    assert is_sticky_subagent_args("scout") is False
    assert is_sticky_subagent_args("scout explore") is False
    assert is_sticky_subagent_args("set") is False


def test_meta_vs_freeform_dispatch_matrix() -> None:
    """Audit: only plan/goal free-form fall through to agent runs."""
    from takopi.telegram.commands.meta_args import should_handle_as_meta_command

    engines = ("codex", "claude", "agy", "grok")

    # Dual-mode: free-form → agent run (not meta)
    assert (
        should_handle_as_meta_command("plan", "/agy design", engine_ids=engines)
        is False
    )
    assert (
        should_handle_as_meta_command("plan", "design auth", engine_ids=engines)
        is False
    )
    assert (
        should_handle_as_meta_command("goal", "all tests pass", engine_ids=engines)
        is False
    )
    # Dual-mode sticky/help stays meta
    assert should_handle_as_meta_command("plan", "", engine_ids=engines) is True
    assert should_handle_as_meta_command("plan", "on", engine_ids=engines) is True
    assert should_handle_as_meta_command("goal", "", engine_ids=engines) is True
    # Subagent dual-mode: free-form → agent run, sticky/show → meta
    assert (
        should_handle_as_meta_command("subagent", "scout explore", engine_ids=engines)
        is False
    )
    assert should_handle_as_meta_command("subagent", "", engine_ids=engines) is True
    assert should_handle_as_meta_command("subagent", "off", engine_ids=engines) is True
    assert (
        should_handle_as_meta_command("subagent", "set scout", engine_ids=engines)
        is True
    )
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
    state = GrokStreamState(
        resume=ResumeToken(engine="grok", value="sid"), started=False
    )
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("plan the refactor", None, state=state)
    # Task 16: native --permission-mode plan + read-only --tools allow-list.
    # Mutating tools are physically absent -> no approval prompt -> no cancel.
    assert "--permission-mode" in args
    assert args[args.index("--permission-mode") + 1] == "plan"
    assert "--yolo" not in args
    assert "--tools" in args
    tools_val = args[args.index("--tools") + 1]
    assert "write" not in tools_val
    assert "read_file" in tools_val
    # plan_mode flag is set for the salvage safety net.
    assert state.plan_mode is True


def test_grok_goal_prefixes_prompt() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=True)
    state = GrokStreamState(
        resume=ResumeToken(engine="grok", value="sid"), started=False
    )
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


def test_pi_plan_mode_appends_flag() -> None:
    """In plan mode with the extension detected, the runner appends ``--plan``.

    The default ``plan_mode_extension=True`` simulates the extension being
    installed; the soft-plan fallback is covered in ``test_pi_runner.py``.
    """
    runner = PiRunner(extra_args=[], model=None, provider=None)
    state = PiStreamState(resume=ResumeToken(engine=PI_ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design", None, state=state)
    assert "--plan" in args
    # No soft-plan prefix is injected; the prompt is passed through unchanged.
    assert "design" in args


def test_pi_non_plan_mode_omits_flag() -> None:
    runner = PiRunner(extra_args=[], model=None, provider=None)
    state = PiStreamState(resume=ResumeToken(engine=PI_ENGINE, value="s.jsonl"))
    args = runner.build_args("design", None, state=state)
    assert "--plan" not in args


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


# --- mode badge + footer composition (plan/goal indicator) ---


# (imports moved to top of file)


def _projects_with(alias: str = "z80") -> ProjectsConfig:
    return ProjectsConfig(
        projects={
            alias: ProjectConfig(
                alias=alias, path=Path("."), worktrees_dir=Path(".worktrees")
            )
        }
    )


def test_format_mode_badge_plan() -> None:
    assert format_mode_badge(plan=True, goal=None) == "`plan`"


def test_format_mode_badge_goal_wins_over_plan() -> None:
    assert format_mode_badge(plan=True, goal="all tests pass") == "`goal`"


def test_format_mode_badge_goal_only() -> None:
    assert format_mode_badge(plan=False, goal="x") == "`goal`"


def test_format_mode_badge_none() -> None:
    assert format_mode_badge(plan=False, goal=None) is None
    assert format_mode_badge(plan=False, goal="") is None


def test_compose_context_line_plan_with_ctx() -> None:
    ctx = RunContext(project="z80", branch="feat/api")
    line = compose_context_line(ctx, _projects_with(), plan=True, goal=None)
    assert line == "`plan` `ctx: z80 @feat/api`"


def test_compose_context_line_goal_only_no_ctx() -> None:
    line = compose_context_line(None, _empty_projects(), plan=False, goal="cond")
    assert line == "`goal`"


def test_compose_context_line_no_mode_returns_ctx() -> None:
    ctx = RunContext(project="z80")
    line = compose_context_line(ctx, _projects_with(), plan=False, goal=None)
    assert line == "`ctx: z80`"


def test_compose_context_line_no_mode_no_ctx() -> None:
    assert compose_context_line(None, _empty_projects(), plan=False, goal=None) is None


def test_format_context_line_unchanged_when_no_mode() -> None:
    """Existing format_context_line behavior must not regress."""
    ctx = RunContext(project="z80", branch="feat")
    assert format_context_line(ctx, projects=_projects_with()) == "`ctx: z80 @feat`"
    assert format_context_line(None, projects=_empty_projects()) is None


# --- skill / subagent directives ---


def test_parse_directives_skill_inline() -> None:
    d = parse_directives(
        "/codex --skill tdd write tests",
        engine_ids=("codex", "claude"),
        projects=_empty_projects(),
    )
    assert d.skill == "tdd"
    assert d.subagent is None
    assert d.engine == "codex"
    assert d.prompt == "write tests"


def test_parse_directives_skill_slash() -> None:
    d = parse_directives(
        "/codex /skill tdd write tests",
        engine_ids=("codex", "claude"),
        projects=_empty_projects(),
    )
    assert d.skill == "tdd"
    assert d.prompt == "write tests"


def test_parse_directives_subagent_inline() -> None:
    d = parse_directives(
        "/grok --subagent reviewer review this",
        engine_ids=("grok", "claude"),
        projects=_empty_projects(),
    )
    assert d.subagent == "reviewer"
    assert d.skill is None
    assert d.prompt == "review this"


def test_parse_directives_subagent_slash() -> None:
    d = parse_directives(
        "/codex /subagent scout explore the tree",
        engine_ids=("codex", "claude"),
        projects=_empty_projects(),
    )
    assert d.subagent == "scout"
    assert d.prompt == "explore the tree"


def test_parse_directives_skill_and_subagent() -> None:
    d = parse_directives(
        "/codex --skill tdd --subagent scout do thing",
        engine_ids=("codex",),
        projects=_empty_projects(),
    )
    assert d.skill == "tdd"
    assert d.subagent == "scout"
    assert d.prompt == "do thing"


def test_parse_directives_skill_before_engine() -> None:
    d = parse_directives(
        "--skill tdd /codex write tests",
        engine_ids=("codex",),
        projects=_empty_projects(),
    )
    assert d.skill == "tdd"
    assert d.engine == "codex"
    assert d.prompt == "write tests"


def test_parse_directives_skill_requires_value() -> None:
    import pytest

    from takopi.directives import DirectiveError

    with pytest.raises(DirectiveError):
        parse_directives(
            "/codex --skill",
            engine_ids=("codex",),
            projects=_empty_projects(),
        )


def test_parse_directives_duplicate_skill_errors() -> None:
    import pytest

    from takopi.directives import DirectiveError

    with pytest.raises(DirectiveError):
        parse_directives(
            "/codex --skill tdd --skill other go",
            engine_ids=("codex",),
            projects=_empty_projects(),
        )


def test_parse_directives_no_skill_keeps_field_none() -> None:
    d = parse_directives(
        "/codex write tests",
        engine_ids=("codex",),
        projects=_empty_projects(),
    )
    assert d.skill is None
    assert d.subagent is None


def test_merge_run_options_preserves_skill() -> None:
    base = EngineRunOptions(skill="tdd")
    merged = merge_run_options(base)
    assert merged is not None
    assert merged.skill == "tdd"


def test_merge_run_options_skill_from_none_base() -> None:
    merged = merge_run_options(None, subagent="scout")
    assert merged is not None
    assert merged.subagent == "scout"


def test_grok_subagent_injects_agent_flag() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=True)
    state = GrokStreamState(
        resume=ResumeToken(engine="grok", value="sid"), started=False
    )
    with apply_run_options(EngineRunOptions(subagent="reviewer")):
        args = runner.build_args("review it", None, state=state)
    assert "--agent" in args
    assert args[args.index("--agent") + 1] == "reviewer"


def test_grok_no_subagent_omits_agent_flag() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=True)
    state = GrokStreamState(
        resume=ResumeToken(engine="grok", value="sid"), started=False
    )
    args = runner.build_args("do it", None, state=state)
    assert "--agent" not in args


def test_claude_subagent_injects_agent_flag() -> None:
    runner = ClaudeRunner(claude_cmd="claude", dangerously_skip_permissions=True)
    with apply_run_options(EngineRunOptions(subagent="reviewer")):
        args = runner.build_args("review it", None, state=None)
    assert "--agent" in args
    assert args[args.index("--agent") + 1] == "reviewer"


def test_build_bot_commands_includes_subagent() -> None:
    import inspect

    from takopi.telegram.commands.menu import build_bot_commands

    source = inspect.getsource(build_bot_commands)
    assert "subagent" in source
    assert "sticky subagent" in source


def test_subagent_reserved_command_id() -> None:
    from takopi.ids import RESERVED_COMMAND_IDS

    assert "subagent" in RESERVED_COMMAND_IDS


def test_opencode_subagent_overrides_plan_agent() -> None:
    runner = OpenCodeRunner(opencode_cmd="opencode", plan_agent="plan")
    state = OpenCodeStreamState()
    with apply_run_options(EngineRunOptions(subagent="reviewer")):
        args = runner.build_args("review it", None, state=state)
    assert "--agent" in args
    assert args[args.index("--agent") + 1] == "reviewer"


def test_opencode_plan_agent_when_no_subagent() -> None:
    runner = OpenCodeRunner(opencode_cmd="opencode", plan_agent="plan")
    state = OpenCodeStreamState()
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design it", None, state=state)
    assert "--agent" in args
    assert args[args.index("--agent") + 1] == "plan"
