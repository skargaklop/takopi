import os
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import anyio
import pytest

from takopi.model import ActionEvent, CompletedEvent, ResumeToken, StartedEvent
from takopi.runners.pi import (
    ENGINE,
    PiRunner,
    PiStreamState,
    _default_session_dir,
    detect_plan_mode_extension,
    translate_pi_event,
)
from takopi.runners.omp import (
    BACKEND as OMP_BACKEND,
    ENGINE as OMP_ENGINE,
    OmpRunner,
)
from takopi.runners.run_options import (
    EngineRunOptions,
    apply_run_options,
)
from takopi.schemas import pi as pi_schema


def _load_fixture(name: str) -> list[pi_schema.PiEvent]:
    path = Path(__file__).parent / "fixtures" / name
    events: list[pi_schema.PiEvent] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            decoded = pi_schema.decode_event(line)
        except Exception as exc:
            raise AssertionError(f"{name} contained unparseable line: {line}") from exc
        events.append(decoded)
    return events


def test_pi_resume_format_and_extract(tmp_path: Path) -> None:
    runner = PiRunner(
        extra_args=[],
        model=None,
        provider=None,
    )
    session_path = tmp_path / "session.jsonl"
    session_str = str(session_path)
    token = ResumeToken(engine=ENGINE, value=session_str)

    expected_session = f'"{session_str}"' if " " in session_str else session_str
    assert runner.format_resume(token) == f"`pi --session {expected_session}`"
    assert runner.extract_resume(f"`pi --session {expected_session}`") == token
    assert runner.extract_resume(f'pi --session "{session_str}"') == token
    assert runner.extract_resume("`codex resume sid`") is None

    spaced_path = tmp_path / "pi session.jsonl"
    spaced = ResumeToken(engine=ENGINE, value=str(spaced_path))
    assert runner.format_resume(spaced) == f'`pi --session "{spaced_path}"`'
    assert runner.extract_resume(f'`pi --session "{spaced_path}"`') == spaced


def test_omp_resume_format_and_extract(tmp_path: Path) -> None:
    runner = OmpRunner(
        extra_args=[],
        model=None,
        provider=None,
    )
    token = ResumeToken(engine=OMP_ENGINE, value="abc123")

    assert runner.format_resume(token) == "`omp --resume abc123`"
    assert runner.extract_resume("`omp --resume abc123`") == token
    assert runner.extract_resume("/omp resume abc123") == token
    assert runner.is_resume_line("`omp --resume abc123`") is True
    assert runner.is_resume_line("`/omp resume abc123`") is True
    assert runner.extract_resume("`pi --session abc123`") is None

    spaced_path = tmp_path / "oh my pi session.jsonl"
    spaced = ResumeToken(engine=OMP_ENGINE, value=str(spaced_path))
    assert runner.format_resume(spaced) == f'`omp --resume "{spaced_path}"`'
    assert runner.extract_resume(f'`/omp resume "{spaced_path}"`') == spaced
    assert runner.is_resume_line("/omp resume abc123 continue") is False


def test_translate_success_fixture() -> None:
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="session.jsonl"))
    events: list = []
    for event in _load_fixture("pi_stream_success.jsonl"):
        events.extend(translate_pi_event(event, title="pi", meta=None, state=state))

    assert isinstance(events[0], StartedEvent)
    started = next(evt for evt in events if isinstance(evt, StartedEvent))
    assert started.meta is None

    action_events = [evt for evt in events if isinstance(evt, ActionEvent)]
    assert len(action_events) == 4

    started_actions = {
        (evt.action.id, evt.phase): evt
        for evt in action_events
        if evt.phase == "started"
    }
    assert started_actions[("tool_1", "started")].action.kind == "command"
    write_action = started_actions[("tool_2", "started")].action
    assert write_action.kind == "file_change"
    assert write_action.detail["changes"][0]["path"] == "notes.md"

    completed_actions = {
        (evt.action.id, evt.phase): evt
        for evt in action_events
        if evt.phase == "completed"
    }
    assert completed_actions[("tool_1", "completed")].ok is True
    assert completed_actions[("tool_2", "completed")].ok is True

    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert events[-1] == completed
    assert completed.ok is True
    assert completed.resume == started.resume
    assert completed.answer == "Done. Added notes.md."


def test_omp_translate_success_fixture() -> None:
    runner = OmpRunner(
        extra_args=[],
        model="takopi-model",
        provider="takopi-provider",
    )
    state = runner.new_state(
        "prompt",
        ResumeToken(engine=OMP_ENGINE, value="session.jsonl"),
    )
    events: list = []
    for event in _load_fixture("pi_stream_success.jsonl"):
        events.extend(
            runner.translate(
                event,
                state=state,
                resume=None,
                found_session=None,
            )
        )

    started = next(evt for evt in events if isinstance(evt, StartedEvent))
    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    action = next(evt for evt in events if isinstance(evt, ActionEvent))

    assert started.engine == OMP_ENGINE
    assert started.resume.engine == OMP_ENGINE
    assert started.title == "omp"
    assert started.meta == {
        "cwd": os.getcwd(),
        "model": "takopi-model",
        "provider": "takopi-provider",
    }
    assert action.engine == OMP_ENGINE
    assert completed.engine == OMP_ENGINE
    assert completed.resume is not None
    assert completed.resume.engine == OMP_ENGINE


def test_translate_error_fixture() -> None:
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="session.jsonl"))
    events: list = []
    for event in _load_fixture("pi_stream_error.jsonl"):
        events.extend(translate_pi_event(event, title="pi", meta=None, state=state))

    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert completed.ok is False
    assert completed.error == "Upstream error"
    assert completed.answer == "Request failed."


def test_session_id_promotion_from_stdout() -> None:
    state = PiStreamState(
        resume=ResumeToken(engine=ENGINE, value="session.jsonl"),
        allow_id_promotion=True,
    )
    events = translate_pi_event(
        pi_schema.SessionHeader(
            id="ccd569e0-4e1b-4c7d-a981-637ed4107310",
            version=3,
            timestamp="2026-01-13T00:33:34.702Z",
            cwd="/tmp",
        ),
        title="pi",
        meta=None,
        state=state,
    )
    started = next(evt for evt in events if isinstance(evt, StartedEvent))
    assert started.resume.value == "ccd569e0"


def test_extract_resume_keeps_session_path(tmp_path: Path) -> None:
    session_path = tmp_path / "session.jsonl"
    session_str = str(session_path)
    runner = PiRunner(
        extra_args=[],
        model=None,
        provider=None,
    )
    quoted = f'"{session_str}"' if " " in session_str else session_str
    token = runner.extract_resume(f"pi --session {quoted}")
    assert token is not None
    assert token.value == session_str


def test_omp_build_args_invokes_omp_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = OmpRunner(
        extra_args=["--extra"],
        model="cfg-model",
        provider="cfg-provider",
    )
    state = runner.new_state("prompt", None)
    monkeypatch.setattr("takopi.runners.omp.get_run_options", lambda: None)

    assert runner.command() == "omp"
    assert runner.build_args("hello", None, state=state) == [
        "--extra",
        "--print",
        "--mode",
        "json",
        "--provider",
        "cfg-provider",
        "--model",
        "cfg-model",
        "hello",
    ]

    resume = ResumeToken(engine=OMP_ENGINE, value="session-123")
    resumed_state = runner.new_state("hello", resume)
    assert runner.build_args("hello", resume, state=resumed_state) == [
        "--extra",
        "--print",
        "--mode",
        "json",
        "--provider",
        "cfg-provider",
        "--model",
        "cfg-model",
        "--resume",
        "session-123",
        "hello",
    ]


def test_omp_backend_metadata_documents_terminal_command() -> None:
    assert OMP_BACKEND.id == OMP_ENGINE
    assert OMP_BACKEND.cli_cmd == "omp"
    assert OMP_BACKEND.install_cmd == "bun install -g @oh-my-pi/pi-coding-agent"


@pytest.mark.anyio
async def test_run_keeps_resume_path(tmp_path: Path) -> None:
    session_path = tmp_path / "session.jsonl"
    runner = PiRunner(
        extra_args=[],
        model=None,
        provider=None,
    )
    seen_resume: ResumeToken | None = None

    async def run_stub(_prompt: str, resume: ResumeToken | None):
        nonlocal seen_resume
        seen_resume = resume
        yield CompletedEvent(
            engine=ENGINE,
            resume=resume,
            ok=True,
            answer="ok",
        )

    runner.run_impl = run_stub  # type: ignore[assignment]
    resume = ResumeToken(engine=ENGINE, value=str(session_path))
    async for _event in runner.run("test", resume):
        pass
    assert seen_resume is not None
    assert seen_resume.value == str(session_path)


@pytest.mark.anyio
async def test_run_serializes_same_session() -> None:
    runner = PiRunner(
        extra_args=[],
        model=None,
        provider=None,
    )
    gate = anyio.Event()
    in_flight = 0
    max_in_flight = 0

    async def run_stub(*_args, **_kwargs):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await gate.wait()
            yield CompletedEvent(
                engine=ENGINE,
                resume=ResumeToken(engine=ENGINE, value="session.jsonl"),
                ok=True,
                answer="ok",
            )
        finally:
            in_flight -= 1

    runner.run_impl = run_stub  # type: ignore[assignment]

    async def drain(prompt: str, resume: ResumeToken | None) -> None:
        async for _event in runner.run(prompt, resume):
            pass

    token = ResumeToken(engine=ENGINE, value="session.jsonl")
    async with anyio.create_task_group() as tg:
        tg.start_soon(drain, "a", token)
        tg.start_soon(drain, "b", token)
        await anyio.sleep(0)
        gate.set()
    assert max_in_flight == 1


def test_session_path_prefers_run_base_dir(tmp_path: Path) -> None:
    runner = PiRunner(
        extra_args=[],
        model=None,
        provider=None,
    )
    project_cwd = Path("/project")
    session_root = tmp_path / "sessions"

    with (
        patch("takopi.runners.pi.get_run_base_dir", return_value=project_cwd),
        patch(
            "takopi.runners.pi._default_session_dir",
            return_value=session_root,
        ) as default_session_dir,
    ):
        session_path = runner._new_session_path()

    default_session_dir.assert_called_once_with(project_cwd)
    assert str(session_root) in session_path


def test_session_path_sanitizes_windows_separators() -> None:
    cwd = PureWindowsPath("C:\\foo\\bar")
    session_dir = _default_session_dir(cwd)
    name = session_dir.name
    assert "\\" not in name
    assert ":" not in name


def test_pi_multiline_prompt_goes_via_stdin() -> None:
    """Multi-line prompts must be sent via stdin, not as a CLI arg.

    pi.cmd (the Windows batch wrapper) rejects argv elements containing
    newlines with "batch file arguments are invalid" (rc=126), which is the
    root cause of `/plan` failing for the pi engine: the soft-plan prefix
    injects newlines into the prompt.
    """
    runner = PiRunner(extra_args=[], model=None, provider=None)
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    prompt = "line one\nline two"
    args = runner.build_args(prompt, None, state=state)
    payload = runner.stdin_payload(prompt, None, state=state)
    assert prompt not in args
    assert payload is not None
    assert payload.decode() == prompt


def test_pi_single_line_prompt_stays_as_arg() -> None:
    """Single-line prompts keep using the argv path (existing contract)."""
    runner = PiRunner(extra_args=[], model=None, provider=None)
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    prompt = "single line"
    args = runner.build_args(prompt, None, state=state)
    payload = runner.stdin_payload(prompt, None, state=state)
    assert args[-1] == prompt
    assert payload is None


# --- plan-mode extension detection ---


def test_detect_plan_mode_extension_present(tmp_path: Path) -> None:
    """Detector returns True when the package dir exists."""
    root = tmp_path / "node_modules"
    (root / "@narumitw" / "pi-plan-mode").mkdir(parents=True)
    assert detect_plan_mode_extension(root) is True


def test_detect_plan_mode_extension_absent(tmp_path: Path) -> None:
    """Detector returns False when the package dir is missing."""
    root = tmp_path / "node_modules"
    root.mkdir(parents=True)
    assert detect_plan_mode_extension(root) is False


def test_detect_plan_mode_extension_default_root_exists() -> None:
    """Default root points at the conventional pi node_modules path."""
    # The extension is installed on this machine, so default detection is True.
    assert detect_plan_mode_extension() is True


def test_pi_plan_with_extension_appends_flag() -> None:
    """Plan + extension -> args contain --plan, prompt has NO soft-plan prefix."""
    runner = PiRunner(
        extra_args=[], model=None, provider=None, plan_mode_extension=True
    )
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design", None, state=state)
    assert "--plan" in args
    # No soft-plan prefix injected
    assert all(not a.startswith("[Takopi plan mode]") for a in args)


def test_pi_plan_without_extension_uses_soft_prompt() -> None:
    """Plan + no extension -> args have NO --plan, prompt HAS soft-plan prefix."""
    runner = PiRunner(
        extra_args=[], model=None, provider=None, plan_mode_extension=False
    )
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("design auth", None, state=state)
        # The soft-plan prefix goes through stdin (it contains newlines).
        payload = runner.stdin_payload("design auth", None, state=state)
    assert "--plan" not in args
    assert payload is not None
    decoded = payload.decode()
    assert "[Takopi plan mode]" in decoded
    assert "design auth" in decoded


def test_pi_plan_without_extension_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing extension logs a one-time warning."""
    from takopi.runners import pi as pi_module

    calls: list[str] = []
    original_warning = pi_module.logger.warning

    def capture_warning(event: str, *args: object, **kwargs: object) -> None:
        calls.append(event)
        original_warning(event, *args, **kwargs)

    monkeypatch.setattr(pi_module.logger, "warning", capture_warning)

    runner = PiRunner(
        extra_args=[], model=None, provider=None, plan_mode_extension=False
    )
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True)):
        runner.build_args("design", None, state=state)
        assert runner._plan_warning_logged is True
        # Second call should not warn again.
        state2 = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
        runner.build_args("design", None, state=state2)
    assert calls.count("pi.plan_mode_extension_missing") == 1


def test_pi_goal_mode_prefix_unchanged() -> None:
    """Goal mode injects the autonomous-goal prefix (regression)."""
    runner = PiRunner(
        extra_args=[], model=None, provider=None, plan_mode_extension=True
    )
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(goal="all tests pass")):
        payload = runner.stdin_payload("body text", None, state=state)
    assert payload is not None
    decoded = payload.decode()
    assert "(autonomous goal — work until: all tests pass)" in decoded
    assert "body text" in decoded


def test_pi_goal_plus_plan_missing_extension_composes() -> None:
    """Goal + plan (no extension) -> both fallbacks compose, no --plan.

    Goal wins over plan in run_modes(), so the goal prefix is applied and
    --plan is not appended.  The soft-plan prefix is NOT added because goal
    takes priority.
    """
    runner = PiRunner(
        extra_args=[], model=None, provider=None, plan_mode_extension=False
    )
    state = PiStreamState(resume=ResumeToken(engine=ENGINE, value="s.jsonl"))
    with apply_run_options(EngineRunOptions(plan=True, goal="done")):
        args = runner.build_args("body", None, state=state)
        payload = runner.stdin_payload("body", None, state=state)
    assert "--plan" not in args
    assert payload is not None
    decoded = payload.decode()
    assert "(autonomous goal — work until: done)" in decoded
    # Soft-plan prefix is NOT added when goal is active (goal wins).
    assert "[Takopi plan mode]" not in decoded


def test_build_runner_wires_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_runner stores the detection result on the runner instance."""
    from takopi.runners import pi as pi_module

    monkeypatch.setattr(pi_module, "detect_plan_mode_extension", lambda root=None: True)
    runner = pi_module.build_runner({}, Path("takopi.toml"))
    assert isinstance(runner, PiRunner)
    assert runner.plan_mode_extension is True

    monkeypatch.setattr(
        pi_module, "detect_plan_mode_extension", lambda root=None: False
    )
    runner = pi_module.build_runner({}, Path("takopi.toml"))
    assert isinstance(runner, PiRunner)
    assert runner.plan_mode_extension is False
