import re
from collections.abc import AsyncIterator
from typing import Any

import anyio
import pytest

import takopi.runner as runner_module
from takopi.model import (
    ActionEvent,
    CompletedEvent,
    ResumeToken,
    StartedEvent,
    TakopiEvent,
)
from takopi.runner import (
    BaseRunner,
    JsonlRunState,
    JsonlSubprocessRunner,
    ResumeTokenMixin,
)


class _DummyRunner(ResumeTokenMixin, BaseRunner):
    engine = "dummy"
    resume_re = re.compile(r"(?im)^`?dummy resume (?P<token>[^`\s]+)`?$")

    async def run_impl(
        self, prompt: str, resume: ResumeToken | None
    ) -> AsyncIterator[StartedEvent | CompletedEvent]:
        token = resume or ResumeToken(engine=self.engine, value="token")
        yield StartedEvent(engine=self.engine, resume=token, title="dummy")
        yield CompletedEvent(
            engine=self.engine,
            ok=True,
            answer=prompt,
            resume=token,
        )


class _DummyJsonlRunner(JsonlSubprocessRunner):
    engine = "dummy-jsonl"

    def command(self) -> str:
        return "dummy"

    def build_args(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: object,
    ) -> list[str]:
        _ = prompt, resume, state
        return []

    def translate(
        self,
        data: Any,
        *,
        state: Any,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        _ = data, state, resume, found_session
        return []


class _BareJsonlRunner(JsonlSubprocessRunner):
    engine = "bare-jsonl"


class _RunJsonlRunner(_DummyJsonlRunner):
    def stdin_payload(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> bytes | None:
        _ = prompt, resume, state
        return None

    async def iter_json_lines(self, stream: Any) -> AsyncIterator[bytes]:
        _ = stream
        yield b'{"type": "started", "resume": "sid"}'
        yield b'{"type": "completed", "resume": "sid"}'

    def translate(
        self,
        data: Any,
        *,
        state: Any,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        _ = state, resume, found_session
        token_value = "sid"
        if isinstance(data, dict) and isinstance(data.get("resume"), str):
            token_value = data["resume"]
        token = ResumeToken(engine=self.engine, value=token_value)
        if isinstance(data, dict) and data.get("type") == "started":
            return [StartedEvent(engine=self.engine, resume=token, title="t")]
        if isinstance(data, dict) and data.get("type") == "completed":
            return [
                CompletedEvent(engine=self.engine, ok=True, answer="done", resume=token)
            ]
        return []


class _BranchingJsonlRunner(_DummyJsonlRunner):
    def stdin_payload(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> bytes | None:
        _ = prompt, resume, state
        return None

    async def iter_json_lines(self, stream: Any) -> AsyncIterator[bytes]:
        _ = stream
        yield b"raise"
        yield b""
        yield b"invalid"
        yield b'{"type": "translate_error"}'
        yield b'{"type": "started", "resume": "sid"}'
        yield b'{"type": "started", "resume": "sid"}'
        yield b'{"type": "completed", "resume": "sid"}'
        yield b'{"type": "after"}'

    def decode_jsonl(self, *, line: bytes) -> Any | None:
        if line == b"raise":
            raise ValueError("boom")
        if line == b"invalid":
            return None
        return super().decode_jsonl(line=line)

    def translate(
        self,
        data: Any,
        *,
        state: Any,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        _ = state, resume, found_session
        if isinstance(data, dict) and data.get("type") == "translate_error":
            raise RuntimeError("nope")
        token_value = "sid"
        if isinstance(data, dict) and isinstance(data.get("resume"), str):
            token_value = data["resume"]
        token = ResumeToken(engine=self.engine, value=token_value)
        if isinstance(data, dict) and data.get("type") == "started":
            return [StartedEvent(engine=self.engine, resume=token, title="t")]
        if isinstance(data, dict) and data.get("type") == "completed":
            return [
                CompletedEvent(engine=self.engine, ok=True, answer="done", resume=token)
            ]
        return []


@pytest.mark.anyio
async def test_base_runner_run_locked_handles_resume() -> None:
    runner = _DummyRunner()
    events = [evt async for evt in runner.run("hello", None)]
    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)

    resume = ResumeToken(engine=runner.engine, value="resume")
    resumed = [evt async for evt in runner.run("again", resume)]
    assert isinstance(resumed[0], StartedEvent)
    assert resumed[0].resume == resume


@pytest.mark.anyio
async def test_base_runner_rejects_wrong_resume_engine() -> None:
    runner = _DummyRunner()
    bad_resume = ResumeToken(engine="other", value="oops")
    with pytest.raises(RuntimeError):
        _ = [evt async for evt in runner.run("hello", bad_resume)]


@pytest.mark.anyio
async def test_base_runner_run_impl_not_implemented() -> None:
    class _BareRunner(BaseRunner):
        engine = "bare"

    runner = _BareRunner()
    with pytest.raises(NotImplementedError):
        _ = [evt async for evt in runner.run_impl("hello", None)]


def test_resume_token_format_and_extract() -> None:
    runner = _DummyRunner()
    token = ResumeToken(engine=runner.engine, value="abc")
    assert runner.format_resume(token) == "`dummy resume abc`"
    assert runner.is_resume_line("`dummy resume abc`") is True
    text = "`dummy resume first`\n`dummy resume second`"
    assert runner.extract_resume(text) == ResumeToken(
        engine=runner.engine, value="second"
    )
    assert runner.extract_resume(None) is None

    with pytest.raises(RuntimeError):
        runner.format_resume(ResumeToken(engine="other", value="bad"))


def test_session_lock_reuse() -> None:
    runner = _DummyRunner()
    token = ResumeToken(engine=runner.engine, value="one")
    lock1 = runner.lock_for(token)
    lock2 = runner.lock_for(token)
    other = runner.lock_for(ResumeToken(engine=runner.engine, value="two"))
    assert lock1 is lock2
    assert other is not lock1


@pytest.mark.anyio
async def test_run_with_resume_lock_passthrough() -> None:
    runner = _DummyRunner()
    events = [
        evt async for evt in runner.run_with_resume_lock("hello", None, runner.run_impl)
    ]
    assert events


def test_jsonl_helpers() -> None:
    runner = _DummyJsonlRunner()
    state = JsonlRunState()

    note1 = runner.next_note_id(state)
    note2 = runner.next_note_id(state)
    assert note1.endswith(".1")
    assert note2.endswith(".2")

    event = runner.note_event("warn", state=state)
    assert isinstance(event, ActionEvent)
    assert event.action.detail == {}

    invalid = runner.invalid_json_events(raw="x", line="{}", state=state)
    invalid_event = invalid[0]
    assert isinstance(invalid_event, ActionEvent)
    assert invalid_event.action.detail["line"] == "{}"

    assert runner.decode_jsonl(line=b'{"a": 1}') == {"a": 1}
    assert runner.decode_jsonl(line=b"{") is None

    err_events = runner.decode_error_events(
        raw="oops", line="{}", error=ValueError("nope"), state=state
    )
    err_event = err_events[0]
    assert isinstance(err_event, ActionEvent)
    assert err_event.action.detail["error"] == "nope"

    translated = runner.translate_error_events(
        data={"type": "foo", "item": {"type": "bar"}},
        error=ValueError("boom"),
        state=state,
    )
    translated_event = translated[0]
    assert isinstance(translated_event, ActionEvent)
    detail = translated_event.action.detail
    assert detail["type"] == "foo"
    assert detail["item_type"] == "bar"

    resume = ResumeToken(engine=runner.engine, value="sid")
    processed = runner.process_error_events(
        2, resume=resume, found_session=None, state=state
    )
    processed_event = processed[-1]
    assert isinstance(processed_event, CompletedEvent)
    assert processed_event.ok is False
    assert processed_event.resume == resume

    stream_end = runner.stream_end_events(
        resume=None, found_session=resume, state=state
    )
    stream_event = stream_end[-1]
    assert isinstance(stream_event, CompletedEvent)
    assert stream_event.resume == resume

    started = StartedEvent(engine=runner.engine, resume=resume, title="t")
    found, emit = runner.handle_started_event(
        started, expected_session=None, found_session=None
    )
    assert found == resume
    assert emit is True

    found, emit = runner.handle_started_event(
        started, expected_session=None, found_session=resume
    )
    assert found == resume
    assert emit is False

    mismatch = StartedEvent(engine="other", resume=resume, title="t")
    with pytest.raises(RuntimeError):
        runner.handle_started_event(mismatch, expected_session=None, found_session=None)

    other_resume = ResumeToken(engine=runner.engine, value="other")
    with pytest.raises(RuntimeError):
        runner.handle_started_event(
            StartedEvent(engine=runner.engine, resume=other_resume, title="t"),
            expected_session=resume,
            found_session=None,
        )

    with pytest.raises(RuntimeError):
        runner.handle_started_event(
            StartedEvent(engine=runner.engine, resume=other_resume, title="t"),
            expected_session=None,
            found_session=resume,
        )


def test_next_note_id_requires_state_field() -> None:
    runner = _DummyJsonlRunner()
    with pytest.raises(RuntimeError):
        runner.next_note_id(object())


def test_jsonl_base_methods_raise_and_defaults() -> None:
    runner = _BareJsonlRunner()
    with pytest.raises(NotImplementedError):
        runner.command()
    with pytest.raises(NotImplementedError):
        runner.build_args("hi", None, state=None)
    with pytest.raises(NotImplementedError):
        runner.translate(data={}, state=None, resume=None, found_session=None)
    assert runner.pipes_error_message().startswith("bare-jsonl")
    state = runner.new_state("hi", None)
    assert isinstance(state, JsonlRunState)
    assert runner.start_run("hi", None, state=state) is None
    assert runner.env(state=state) is None
    assert runner.stdin_payload("hi", None, state=state) == b"hi"


@pytest.mark.anyio
async def test_jsonl_run_impl_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = object()
            self.stderr = object()
            self.stdin = None
            self.pid = 123

        async def wait(self) -> int:
            return 0

    class _FakeManager:
        def __init__(self, proc: _FakeProc) -> None:
            self._proc = proc

        async def __aenter__(self) -> _FakeProc:
            return self._proc

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    proc = _FakeProc()

    def fake_manage_subprocess(*args: Any, **kwargs: Any) -> _FakeManager:
        _ = args, kwargs
        return _FakeManager(proc)

    async def fake_drain_stderr(*args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        return None

    monkeypatch.setattr(runner_module, "manage_subprocess", fake_manage_subprocess)
    monkeypatch.setattr(runner_module, "drain_stderr", fake_drain_stderr)

    runner = _RunJsonlRunner()
    events = [evt async for evt in runner.run_impl("hello", None)]
    assert any(isinstance(evt, CompletedEvent) for evt in events)


@pytest.mark.anyio
async def test_jsonl_run_impl_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = object()
            self.stderr = object()
            self.stdin = None
            self.pid = 456

        async def wait(self) -> int:
            return 0

    class _FakeManager:
        def __init__(self, proc: _FakeProc) -> None:
            self._proc = proc

        async def __aenter__(self) -> _FakeProc:
            return self._proc

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    proc = _FakeProc()

    def fake_manage_subprocess(*args: Any, **kwargs: Any) -> _FakeManager:
        _ = args, kwargs
        return _FakeManager(proc)

    async def fake_drain_stderr(*args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        return None

    monkeypatch.setattr(runner_module, "manage_subprocess", fake_manage_subprocess)
    monkeypatch.setattr(runner_module, "drain_stderr", fake_drain_stderr)

    runner = _BranchingJsonlRunner()
    events = [evt async for evt in runner.run_impl("hello", None)]
    assert any(isinstance(evt, CompletedEvent) for evt in events)


def test_prompt_fingerprint_length() -> None:
    fp = runner_module._prompt_fingerprint("hello world")
    assert len(fp) == 12
    assert all(c in "0123456789abcdef" for c in fp)


def test_prompt_fingerprint_deterministic() -> None:
    assert runner_module._prompt_fingerprint(
        "test"
    ) == runner_module._prompt_fingerprint("test")
    assert runner_module._prompt_fingerprint("a") != runner_module._prompt_fingerprint(
        "b"
    )


def test_safe_preview_short() -> None:
    assert runner_module._safe_preview("hello") == "hello"


def test_safe_preview_truncates() -> None:
    long = "x" * 100
    result = runner_module._safe_preview(long, max_len=10)
    assert result == "xxxxxxxxxx…"


def test_safe_preview_collapses_newlines() -> None:
    assert runner_module._safe_preview("line1\nline2\nline3") == "line1 line2 line3"


@pytest.mark.anyio
async def test_iter_jsonl_startup_timeout_no_output() -> None:
    """If no JSONL arrives within startup_timeout_s, emit a failure event."""
    from collections.abc import AsyncIterator  # noqa: F401

    class _SlowRunner(_DummyJsonlRunner):
        async def iter_json_lines(self, stream: Any) -> AsyncIterator[bytes]:
            # Never produces output
            await anyio.sleep(300)
            return  # type: ignore[unreachable]
            yield b""  # type: ignore[unreachable]

    runner = _SlowRunner()
    runner.startup_timeout_s = 0.1
    runner.idle_timeout_s = 0.1
    stream = runner_module.JsonlStreamState(expected_session=None)
    state = runner_module.JsonlRunState()
    events = [
        evt
        async for evt in runner._iter_jsonl_events(
            stdout=None,
            stream=stream,
            state=state,
            resume=None,
            logger=None,
            pid=0,
            startup_timeout_s=0.1,
            idle_timeout_s=0.1,
        )
    ]
    assert any(isinstance(evt, CompletedEvent) and not evt.ok for evt in events), (
        f"expected failed completion, got {events}"
    )


@pytest.mark.anyio
async def test_iter_jsonl_normal_stream_ignores_timeouts() -> None:
    """A normal stream with events should complete regardless of timeouts."""
    from collections.abc import AsyncIterator  # noqa: F401

    class _FastRunner(_DummyJsonlRunner):
        async def iter_json_lines(self, stream: Any) -> AsyncIterator[bytes]:
            for line in [b'{"type": "test"}', b'{"type": "done"}']:
                yield line

    runner = _FastRunner()
    runner.startup_timeout_s = 10.0
    runner.idle_timeout_s = 10.0
    stream = runner_module.JsonlStreamState(expected_session=None)
    state = runner_module.JsonlRunState()
    events = [
        evt
        async for evt in runner._iter_jsonl_events(
            stdout=None,
            stream=stream,
            state=state,
            resume=None,
            logger=None,
            pid=0,
            startup_timeout_s=10.0,
            idle_timeout_s=10.0,
        )
    ]
    # Should process lines without timing out — events may be empty if
    # the dummy runner ignores unknown JSON, but it must not hang.
    # The key assertion: no timeout error event is emitted.
    assert not any(isinstance(evt, CompletedEvent) and not evt.ok for evt in events), (
        f"unexpected timeout on normal stream: {events}"
    )


@pytest.mark.anyio
async def test_lock_released_after_cancel() -> None:
    """The resume lock must release after cancellation, not stay held."""
    runner = _DummyRunner()
    token = ResumeToken(engine="dummy", value="ses_test")

    async def slow_run(prompt, resume):
        yield StartedEvent(engine="dummy", resume=resume, title="test", meta={})
        await anyio.sleep(300)
        yield CompletedEvent(engine="dummy", resume=resume, ok=True, answer="ok")

    runner.run_impl = slow_run  # type: ignore[assignment]

    async def drain(prompt, resume):
        async for _ in runner.run(prompt, resume):
            pass

    # Start and cancel
    with anyio.move_on_after(0.2):
        async with anyio.create_task_group() as tg:
            tg.start_soon(drain, "first", token)
            await anyio.sleep(0.05)
            tg.cancel_scope.cancel()

    # Lock should be released — second run starts immediately
    started = anyio.Event()

    async def quick_run(prompt, resume):
        started.set()
        yield CompletedEvent(engine="dummy", resume=resume, ok=True, answer="ok")

    runner.run_impl = quick_run  # type: ignore[assignment]
    with anyio.fail_after(2):
        async for _ in runner.run("second", token):
            pass
    assert started.is_set()


def _make_attempt_runner(
    attempts: list[tuple[list[bytes], int, list[str]]],
) -> _DummyJsonlRunner:
    """Build a JSONL runner that scripts each spawn's stdout, rc, and stderr.

    ``attempts`` is indexed by spawn count (0-based). Each entry is
    ``(stdout_lines, exit_code, stderr_lines)``. Each fake process captures its
    attempt index at construction so stdout/rc/stderr stay consistent even
    though the background ``drain_stderr`` task may run interleaved.
    """

    class _FakeProc:
        def __init__(self, idx: int) -> None:
            self._idx = idx
            self.stdout = object()
            self.stderr = object()
            self.stdin = None
            self.pid = 100 + idx

        async def wait(self) -> int:
            return attempts[self._idx][1]

    class _FakeManager:
        def __init__(self, idx: int) -> None:
            self._proc = _FakeProc(idx)

        async def __aenter__(self):
            return self._proc

        async def __aexit__(self, exc_type, exc, tb):
            return None

    spawn_counter = {"n": 0}

    class _AttemptRunner(_DummyJsonlRunner):
        engine = "attempt-jsonl"
        retry_max_attempts = 3
        retry_base_delay_s = 0.0  # keep tests fast

        def stdin_payload(self, prompt, resume, *, state):  # type: ignore[override]
            return None

        async def iter_json_lines(self, stream):  # type: ignore[override]
            idx = min(spawn_counter["n"] - 1, len(attempts) - 1)
            for line in attempts[max(0, idx)][0]:
                yield line

        def translate(self, data, *, state, resume, found_session):  # type: ignore[override]
            if isinstance(data, dict) and data.get("type") == "started":
                token = ResumeToken(engine=self.engine, value="sid")
                return [StartedEvent(engine=self.engine, resume=token, title="t")]
            if isinstance(data, dict) and data.get("type") == "completed":
                token = ResumeToken(engine=self.engine, value="sid")
                error = data.get("error")
                answer = data.get("answer", "")
                return [
                    CompletedEvent(
                        engine=self.engine,
                        ok=bool(data.get("ok", False)),
                        answer=answer,
                        resume=token,
                        error=error if isinstance(error, str) else None,
                    )
                ]
            return []

    runner = _AttemptRunner()

    async def fake_drain_stderr(stream, logger, tag, capture=None):
        # drain_stderr runs as a background task; read the pid from the fake
        # process to determine which attempt's stderr to emit.
        idx = min(spawn_counter["n"] - 1, len(attempts) - 1)
        idx = max(0, idx)
        if capture is not None:
            for line in attempts[idx][2]:
                capture.append(line)

    def fake_manage_subprocess(*args, **kwargs):
        idx = spawn_counter["n"]
        spawn_counter["n"] += 1
        return _FakeManager(idx)

    runner_module.manage_subprocess = fake_manage_subprocess  # type: ignore[assignment]
    runner_module.drain_stderr = fake_drain_stderr  # type: ignore[assignment]
    return runner


@pytest.mark.anyio
async def test_retry_two_failures_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    original_manage = runner_module.manage_subprocess
    original_drain = runner_module.drain_stderr
    try:
        blob = (
            'Internal error: {"message": "API error (status 503): '
            'capacity temporarily unavailable. Retry shortly.", '
            '"http_status": 503}'
        )
        runner = _make_attempt_runner(
            [
                ([], 1, [blob]),  # attempt 1: stderr-only 503
                ([], 1, [blob]),  # attempt 2: stderr-only 503
                (
                    [b'{"type": "completed", "ok": true, "answer": "ok"}'],
                    0,
                    [],
                ),
            ]
        )
        events = [evt async for evt in runner.run_impl("hello", None)]
    finally:
        runner_module.manage_subprocess = original_manage  # type: ignore[assignment]
        runner_module.drain_stderr = original_drain  # type: ignore[assignment]

    notes = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and evt.action.kind == "warning"
    ]
    completions = [evt for evt in events if isinstance(evt, CompletedEvent)]
    assert len(notes) == 2
    assert all("retrying in 0s" in n.action.title for n in notes)
    assert notes[0].action.title.endswith("(attempt 2/3)")
    assert notes[1].action.title.endswith("(attempt 3/3)")
    assert len(completions) == 1
    assert completions[0].ok is True
    assert completions[0].answer == "ok"


@pytest.mark.anyio
async def test_retry_exhausted_emits_clean_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_manage = runner_module.manage_subprocess
    original_drain = runner_module.drain_stderr
    try:
        blob = (
            'Internal error: {"message": "API error (status 503): '
            'capacity temporarily unavailable. Retry shortly.", '
            '"http_status": 503}'
        )
        runner = _make_attempt_runner(
            [
                ([], 1, [blob]),
                ([], 1, [blob]),
                ([], 1, [blob]),
            ]
        )
        events = [evt async for evt in runner.run_impl("hello", None)]
    finally:
        runner_module.manage_subprocess = original_manage  # type: ignore[assignment]
        runner_module.drain_stderr = original_drain  # type: ignore[assignment]

    completions = [evt for evt in events if isinstance(evt, CompletedEvent)]
    notes = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and evt.action.kind == "warning"
    ]
    assert len(notes) == 2  # two retry notes before exhaustion
    assert len(completions) == 1
    error = completions[0].error
    assert error is not None
    assert "temporarily unavailable" in error
    assert "{" not in error
    assert "Internal error" not in error
    assert "rc=" not in error


@pytest.mark.anyio
async def test_no_retry_after_started_event(monkeypatch: pytest.MonkeyPatch) -> None:
    original_manage = runner_module.manage_subprocess
    original_drain = runner_module.drain_stderr
    try:
        runner = _make_attempt_runner(
            [
                (
                    [
                        b'{"type": "started", "resume": "sid"}',
                        b'{"type": "completed", "ok": false, "error": "HTTP 503 overloaded"}',
                    ],
                    0,
                    [],
                ),
            ]
        )
        events = [evt async for evt in runner.run_impl("hello", None)]
    finally:
        runner_module.manage_subprocess = original_manage  # type: ignore[assignment]
        runner_module.drain_stderr = original_drain  # type: ignore[assignment]

    notes = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and "retrying in" in (evt.action.title or "")
    ]
    completions = [evt for evt in events if isinstance(evt, CompletedEvent)]
    started = [evt for evt in events if isinstance(evt, StartedEvent)]
    assert len(started) == 1  # only one spawn
    assert len(notes) == 0  # no retry note
    assert len(completions) == 1
    assert completions[0].error is not None
    assert "temporarily unavailable" in completions[0].error


@pytest.mark.anyio
async def test_non_transient_failure_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_manage = runner_module.manage_subprocess
    original_drain = runner_module.drain_stderr
    try:
        runner = _make_attempt_runner(
            [
                ([], 1, ["auth failed: unauthorized"]),
            ]
        )
        events = [evt async for evt in runner.run_impl("hello", None)]
    finally:
        runner_module.manage_subprocess = original_manage  # type: ignore[assignment]
        runner_module.drain_stderr = original_drain  # type: ignore[assignment]

    notes = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and evt.action.kind == "warning"
    ]
    completions = [evt for evt in events if isinstance(evt, CompletedEvent)]
    # One retry-note comes from process_error_events (the "failed rc=1" note),
    # but zero retry-backoff notes.
    assert not any("retrying in" in n.action.title for n in notes)
    assert len(completions) == 1
    assert completions[0].ok is False


@pytest.mark.anyio
async def test_cancellation_during_backoff_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_manage = runner_module.manage_subprocess
    original_drain = runner_module.drain_stderr
    try:
        blob = (
            'Internal error: {"message": "status 503 temporarily unavailable", '
            '"http_status": 503}'
        )
        runner = _make_attempt_runner(
            [
                ([], 1, [blob]),
                (
                    [b'{"type": "completed", "ok": true, "answer": "ok"}'],
                    0,
                    [],
                ),
            ]
        )
        runner.retry_base_delay_s = 10.0  # long backoff to cancel into

        with anyio.move_on_after(0.3):
            events = [evt async for evt in runner.run_impl("hello", None)]
            # If it completed without cancellation, there should be no second spawn.
            completions = [e for e in events if isinstance(e, CompletedEvent)]
            assert len(completions) <= 1
    finally:
        runner_module.manage_subprocess = original_manage  # type: ignore[assignment]
        runner_module.drain_stderr = original_drain  # type: ignore[assignment]


@pytest.mark.anyio
async def test_retry_pre_start_rc0_stream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient failed completion before any visible output with rc=0 retries.

    Existing tests cover nonzero-stderr retries and post-start rc=0 failures.
    This covers the gap: a failed CompletedEvent emitted from the stream itself
    (not stderr), process exits 0, no StartedEvent/ActionEvent/answer emitted.
    The shared retry path should retry once, then succeed.
    """
    original_manage = runner_module.manage_subprocess
    original_drain = runner_module.drain_stderr
    try:
        runner = _make_attempt_runner(
            [
                (
                    [
                        b'{"type": "completed", "ok": false, '
                        b'"error": "503 Chat admission capacity '
                        b'is temporarily unavailable. Retry shortly."}',
                    ],
                    0,  # rc=0: transport success despite stream failure
                    [],
                ),
                (
                    [b'{"type": "completed", "ok": true, "answer": "ok"}'],
                    0,
                    [],
                ),
            ]
        )
        events = [evt async for evt in runner.run_impl("hello", None)]
    finally:
        runner_module.manage_subprocess = original_manage  # type: ignore[assignment]
        runner_module.drain_stderr = original_drain  # type: ignore[assignment]

    notes = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and "retrying in" in (evt.action.title or "")
    ]
    completions = [evt for evt in events if isinstance(evt, CompletedEvent)]
    assert len(notes) == 1  # one shared retry note
    assert len(completions) == 1
    assert completions[0].ok is True
    assert completions[0].answer == "ok"
