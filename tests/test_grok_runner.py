from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID

import takopi.runners.grok as grok_runner
from takopi.model import ActionEvent, CompletedEvent, ResumeToken, StartedEvent
from takopi.runners.grok import (
    ENGINE,
    GrokRunner,
    GrokStreamState,
    translate_grok_event,
)
from takopi.runners.run_options import EngineRunOptions, apply_run_options
from takopi.schemas import grok as grok_schema


def _load_fixture(name: str) -> list[grok_schema.GrokEvent]:
    path = Path(__file__).parent / "fixtures" / name
    return [
        grok_schema.decode_event(line)
        for line in path.read_bytes().splitlines()
        if line.strip()
    ]


def test_grok_resume_format_and_extract() -> None:
    runner = GrokRunner(grok_cmd="grok")
    token = ResumeToken(engine=ENGINE, value="sid")

    assert runner.format_resume(token) == "`grok --resume sid`"
    assert runner.extract_resume("`grok --resume sid`") == token
    assert runner.extract_resume("grok -r other") == ResumeToken(
        engine=ENGINE, value="other"
    )
    assert runner.extract_resume("`claude --resume sid`") is None


def test_is_resume_line() -> None:
    runner = GrokRunner(grok_cmd="grok")
    assert runner.is_resume_line("`grok --resume sid`")
    assert runner.is_resume_line("grok -r sid")
    assert not runner.is_resume_line("`claude --resume sid`")
    assert not runner.is_resume_line("not a resume line")


def test_build_runner_uses_shutil_which(monkeypatch) -> None:
    expected = r"C:\Tools\grok.exe"
    called: dict[str, str] = {}

    def fake_which(name: str) -> str | None:
        called["name"] = name
        return expected

    monkeypatch.setattr(grok_runner.shutil, "which", fake_which)
    runner = cast(GrokRunner, grok_runner.build_runner({}, Path("takopi.toml")))

    assert called["name"] == "grok"
    assert runner.grok_cmd == expected
    assert runner.yolo is True


def test_build_runner_config_fields() -> None:
    runner = cast(
        GrokRunner,
        grok_runner.build_runner(
            {
                "model": "grok-build",
                "yolo": False,
                "tools": ["read_file", "grep"],
                "disallowed_tools": "web_search",
                "reasoning_effort": "high",
                "max_turns": 7,
                "extra_args": ["--no-auto-update"],
            },
            Path("takopi.toml"),
        ),
    )
    assert runner.model == "grok-build"
    assert runner.yolo is False
    assert runner.tools == ["read_file", "grep"]
    assert runner.disallowed_tools == "web_search"
    assert runner.reasoning_effort == "high"
    assert runner.max_turns == 7
    assert runner.extra_args == ["--no-auto-update"]


def test_build_args_new_session_includes_session_id_and_yolo() -> None:
    runner = GrokRunner(
        grok_cmd="grok",
        model="grok-build",
        yolo=True,
        extra_args=["--no-auto-update"],
    )
    session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    args = runner.build_args("hello world", None, state=state)

    assert args[:1] == ["--no-auto-update"]
    assert "-p" in args
    assert args[args.index("-p") + 1] == "hello world"
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "streaming-json"
    assert "--yolo" in args
    assert args[args.index("-m") + 1] == "grok-build"
    assert args[args.index("--session-id") + 1] == session_id
    assert "--resume" not in args


def test_build_args_resume_uses_resume_flag() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=False)
    resume = ResumeToken(engine=ENGINE, value="sid-resume")
    state = GrokStreamState(resume=resume, started=False)
    args = runner.build_args("continue", resume, state=state)

    assert args[args.index("--resume") + 1] == "sid-resume"
    assert "--session-id" not in args
    assert "--yolo" not in args


def test_build_args_honors_run_options_model_and_reasoning() -> None:
    runner = GrokRunner(grok_cmd="grok", model="default-model", yolo=True)
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        started=False,
    )
    with apply_run_options(EngineRunOptions(model="override-model", reasoning="low")):
        args = runner.build_args("prompt", None, state=state)

    assert args[args.index("-m") + 1] == "override-model"
    assert "--effort" in args or "--reasoning-effort" in args
    effort_flag = "--effort" if "--effort" in args else "--reasoning-effort"
    assert args[args.index(effort_flag) + 1] == "low"


def test_new_state_generates_uuid_for_new_session() -> None:
    runner = GrokRunner(grok_cmd="grok")
    state = runner.new_state("hi", None)
    assert state.resume.engine == ENGINE
    # Must be a valid UUID string for --session-id
    UUID(state.resume.value)
    assert state.started is False


def test_new_state_uses_resume_token() -> None:
    runner = GrokRunner(grok_cmd="grok")
    resume = ResumeToken(engine=ENGINE, value="existing-sid")
    state = runner.new_state("hi", resume)
    assert state.resume == resume


def test_translate_success_fixture() -> None:
    session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list = []
    for event in _load_fixture("grok_stream_success.jsonl"):
        events.extend(
            translate_grok_event(
                event,
                title="grok",
                state=state,
            )
        )

    assert isinstance(events[0], StartedEvent)
    started = events[0]
    assert started.resume.value == session_id

    thoughts = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and evt.action.kind == "note"
    ]
    assert thoughts
    assert "Scanning" in thoughts[0].action.title

    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert events[-1] == completed
    assert completed.ok is True
    assert completed.resume == started.resume
    assert completed.answer == "Hello from Grok."
    assert completed.usage is not None
    assert completed.usage.get("num_turns") == 1


def test_translate_error_fixture() -> None:
    session_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list = []
    for event in _load_fixture("grok_stream_error.jsonl"):
        events.extend(
            translate_grok_event(
                event,
                title="grok",
                state=state,
            )
        )

    started = next(evt for evt in events if isinstance(evt, StartedEvent))
    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert events[-1] == completed
    assert completed.ok is False
    assert completed.error is not None
    assert "auth failed" in completed.error
    assert completed.resume == started.resume
    assert "Partial answer" in completed.answer


def test_translate_emits_started_once() -> None:
    session_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list = []
    for payload in (
        b'{"type":"text","data":"a"}',
        b'{"type":"text","data":"b"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"cccccccc-cccc-cccc-cccc-cccccccccccc"}',
    ):
        events.extend(
            translate_grok_event(
                grok_schema.decode_event(payload),
                title="grok",
                state=state,
            )
        )

    started_events = [evt for evt in events if isinstance(evt, StartedEvent)]
    assert len(started_events) == 1
    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert completed.answer == "ab"


def test_backend_id() -> None:
    assert grok_runner.BACKEND.id == "grok"
    assert grok_runner.BACKEND.cli_cmd == "grok"
