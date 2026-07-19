"""Explicit user resume must outrank reply/store/running sources."""

from __future__ import annotations

from pathlib import Path

from takopi.config import ProjectsConfig
from takopi.model import ResumeToken
from takopi.resume_parse import parse_bare_resume, strip_engine_resume_prefix
from takopi.router import AutoRouter, RunnerEntry
from takopi.runners.agy import AgyRunner
from takopi.runners.claude import ClaudeRunner
from takopi.runners.codex import CodexRunner
from takopi.runners.mock import Return, ScriptRunner
from takopi.transport_runtime import TransportRuntime


def _runtime(*engines: str) -> TransportRuntime:
    entries: list[RunnerEntry] = []
    for eng in engines:
        if eng == "codex":
            runner = CodexRunner(codex_cmd="codex", extra_args=[])
        elif eng == "claude":
            runner = ClaudeRunner(claude_cmd="claude")
        elif eng == "agy":
            runner = AgyRunner(agy_cmd="agy")
        else:
            runner = ScriptRunner([Return(answer="ok")], engine=eng)
        entries.append(RunnerEntry(engine=eng, runner=runner))
    router = AutoRouter(entries=entries, default_engine=engines[0])
    return TransportRuntime(
        router=router,
        projects=ProjectsConfig(projects={}, default_project=None),
    )


# --- bare resume helper ---


def test_parse_bare_resume_forms() -> None:
    assert parse_bare_resume("resume abc123 fix it") == ("abc123", "fix it")
    assert parse_bare_resume("--resume sid rest") == ("sid", "rest")
    assert parse_bare_resume("--session s1") == ("s1", "")
    assert parse_bare_resume("-r tok more") == ("tok", "more")
    assert parse_bare_resume("-s tok") == ("tok", "")
    assert parse_bare_resume("please resume later") is None
    assert parse_bare_resume("hello") is None


def test_strip_engine_resume_prefix() -> None:
    assert (
        strip_engine_resume_prefix("resume abc continue", engine="agy")
        == "continue"
    )
    assert strip_engine_resume_prefix("agy resume abc continue", engine="agy") == (
        "continue"
    )


# --- resolve_message: user vs reply ---


def test_user_resume_beats_reply_footer() -> None:
    runtime = _runtime("codex", "claude")
    resolved = runtime.resolve_message(
        text="codex resume user-sid continue work",
        reply_text="`claude --resume reply-sid`",
    )
    assert resolved.user_resume == ResumeToken(engine="codex", value="user-sid")
    assert resolved.reply_resume == ResumeToken(engine="claude", value="reply-sid")
    # Compat field: effective for simple callers prefers user
    assert resolved.resume_token == ResumeToken(engine="codex", value="user-sid")
    assert "continue work" in resolved.prompt
    assert "user-sid" not in resolved.prompt


def test_bare_resume_with_engine_directive() -> None:
    runtime = _runtime("codex", "claude", "agy")
    resolved = runtime.resolve_message(
        text="/claude resume my-session do the thing",
        reply_text="`codex resume other`",
    )
    assert resolved.user_resume == ResumeToken(engine="claude", value="my-session")
    assert resolved.engine_override == "claude"
    assert resolved.prompt == "do the thing"
    assert resolved.resume_token == resolved.user_resume


def test_bare_resume_without_engine_pending() -> None:
    runtime = _runtime("codex")
    resolved = runtime.resolve_message(
        text="resume bare-id please fix",
        reply_text="`codex resume from-reply`",
    )
    assert resolved.user_resume is None
    assert resolved.bare_resume_id == "bare-id"
    assert resolved.prompt == "please fix"
    assert resolved.reply_resume == ResumeToken(engine="codex", value="from-reply")
    # Effective token not bound yet without engine — bare id still signals user intent
    assert resolved.resume_token is None or resolved.bare_resume_id == "bare-id"


def test_agy_accepts_resume_alias() -> None:
    runtime = _runtime("agy", "codex")
    for text in (
        "agy resume conv-1 go",
        "agy --resume conv-1 go",
        "/agy resume conv-1 go",
        "`agy --conversation conv-1`",
    ):
        resolved = runtime.resolve_message(text=text, reply_text=None)
        assert resolved.user_resume is not None, text
        assert resolved.user_resume.engine == "agy"
        assert resolved.user_resume.value == "conv-1", text


def test_omp_resume_reconstruct_still_works() -> None:
    from takopi.runners.omp import OmpRunner

    omp = OmpRunner(extra_args=[], model=None, provider=None)
    codex = ScriptRunner([Return(answer="ok")], engine="codex")
    router = AutoRouter(
        entries=[
            RunnerEntry(engine="codex", runner=codex),
            RunnerEntry(engine="omp", runner=omp),
        ],
        default_engine="codex",
    )
    runtime = TransportRuntime(
        router=router,
        projects=ProjectsConfig(projects={}, default_project=None),
    )
    resolved = runtime.resolve_message(
        text="/omp resume abc123 continue",
        reply_text=None,
    )
    assert resolved.user_resume == ResumeToken(engine="omp", value="abc123")
    assert resolved.engine_override == "omp"


def test_reply_only_resume_when_no_user_resume() -> None:
    runtime = _runtime("codex", "claude")
    resolved = runtime.resolve_message(
        text="continue please",
        reply_text="`claude --resume only-reply`",
    )
    assert resolved.user_resume is None
    assert resolved.bare_resume_id is None
    assert resolved.reply_resume == ResumeToken(engine="claude", value="only-reply")
    assert resolved.resume_token == ResumeToken(engine="claude", value="only-reply")


def test_codex_resume_line_strips_from_prompt() -> None:
    runtime = _runtime("codex")
    resolved = runtime.resolve_message(
        text="codex resume sid-9\nfix flaky test",
        reply_text=None,
    )
    assert resolved.user_resume == ResumeToken(engine="codex", value="sid-9")
    assert "fix flaky test" in resolved.prompt
    assert "sid-9" not in resolved.prompt
