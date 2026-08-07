"""Runner protocol and shared runner definitions."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from typing import Any, NamedTuple, Protocol, cast
from weakref import WeakValueDictionary

import anyio

from .logging import get_logger, log_pipeline
from .compact import COMPACT_NONE, CompactSupport, CompactUnsupportedError
from .model import (
    Action,
    ActionEvent,
    CompletedEvent,
    EngineId,
    ResumeToken,
    StartedEvent,
    TakopiEvent,
)
from .utils.paths import get_run_base_dir
from .utils.streams import drain_stderr, iter_bytes_lines
from .utils.transient_failures import (
    classify_transient_failure,
    format_transient_failure,
)
from .utils.subprocess import DEFAULT_SHUTDOWN_TIMEOUT_S, manage_subprocess


class ResumeTokenMixin:
    engine: EngineId
    resume_re: re.Pattern[str]

    def format_resume(self, token: ResumeToken) -> str:
        if token.engine != self.engine:
            raise RuntimeError(f"resume token is for engine {token.engine!r}")
        return f"`{self.engine} resume {token.value}`"

    def is_resume_line(self, line: str) -> bool:
        return bool(self.resume_re.match(line))

    def extract_resume(self, text: str | None) -> ResumeToken | None:
        if not text:
            return None
        found: str | None = None
        for match in self.resume_re.finditer(text):
            token = match.group("token")
            if token:
                found = token
        if not found:
            return None
        return ResumeToken(engine=self.engine, value=found)


class SessionLockMixin:
    engine: EngineId
    session_locks: WeakValueDictionary[str, anyio.Semaphore] | None = None

    def lock_for(self, token: ResumeToken) -> anyio.Semaphore:
        locks = self.session_locks
        if locks is None:
            locks = WeakValueDictionary()
            self.session_locks = locks
        key = f"{token.engine}:{token.value}"
        lock = locks.get(key)
        if lock is None:
            lock = anyio.Semaphore(1)
            locks[key] = lock
        return lock

    async def run_with_resume_lock(
        self,
        prompt: str,
        resume: ResumeToken | None,
        run_fn: Callable[[str, ResumeToken | None], AsyncIterator[TakopiEvent]],
    ) -> AsyncIterator[TakopiEvent]:
        resume_token = resume
        if resume_token is not None and resume_token.engine != self.engine:
            raise RuntimeError(
                f"resume token is for engine {resume_token.engine!r}, not {self.engine!r}"
            )
        if resume_token is None:
            async for evt in run_fn(prompt, resume_token):
                yield evt
            return
        lock = self.lock_for(resume_token)
        async with lock:
            async for evt in run_fn(prompt, resume_token):
                yield evt


class BaseRunner(SessionLockMixin):
    engine: EngineId

    def run(
        self, prompt: str, resume: ResumeToken | None
    ) -> AsyncIterator[TakopiEvent]:
        return self.run_locked(prompt, resume)

    def compact_support(self) -> CompactSupport:
        return COMPACT_NONE

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        if False:
            yield  # pragma: no cover
        raise CompactUnsupportedError(f"{self.engine} does not support compact")

    async def run_locked(
        self, prompt: str, resume: ResumeToken | None
    ) -> AsyncIterator[TakopiEvent]:
        if resume is not None:
            async for evt in self.run_with_resume_lock(prompt, resume, self.run_impl):
                yield evt
            return

        lock: anyio.Semaphore | None = None
        acquired = False
        try:
            async for evt in self.run_impl(prompt, None):
                if lock is None and isinstance(evt, StartedEvent):
                    lock = self.lock_for(evt.resume)
                    await lock.acquire()
                    acquired = True
                yield evt
        finally:
            if acquired and lock is not None:
                lock.release()

    async def run_impl(
        self, prompt: str, resume: ResumeToken | None
    ) -> AsyncIterator[TakopiEvent]:
        if False:
            yield  # pragma: no cover
        raise NotImplementedError


def _prompt_fingerprint(prompt: str) -> str:
    """Return a short SHA-256 fingerprint for diagnostic logging."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def _safe_preview(prompt: str, max_len: int = 60) -> str:
    """Return a single-line preview of *prompt*, truncated to *max_len* chars."""
    preview = prompt.replace("\n", " ").strip()
    return preview[:max_len] + ("…" if len(preview) > max_len else "")


def _format_delay(delay: float) -> str:
    """Format a backoff delay without a trailing ``.0`` for integral values."""
    if delay == int(delay):
        return str(int(delay))
    return str(delay)


@dataclass(slots=True)
class JsonlRunState:
    note_seq: int = 0


@dataclass(slots=True)
class JsonlStreamState:
    expected_session: ResumeToken | None
    found_session: ResumeToken | None = None
    did_emit_completed: bool = False
    ignored_after_completed: bool = False
    jsonl_seq: int = 0


class AttemptBatch(NamedTuple):
    """One batch of events from a single subprocess attempt.

    Stream events arrive as single-event batches with ``rc=None``. A terminal
    batch (no stream completion was emitted) carries empty events, the raw
    stderr text, the process exit code, and ``pid`` for log correlation. The
    retry loop classifies the terminal batch before calling
    ``process_error_events`` so generic failure notes do not pollute the
    side-effect safety counters.
    """

    events: tuple[TakopiEvent, ...]
    stderr: str
    pid: int
    rc: int | None = None


class JsonlSubprocessRunner(BaseRunner):
    startup_timeout_s: float | None = None
    idle_timeout_s: float | None = None
    shutdown_timeout_s: float = DEFAULT_SHUTDOWN_TIMEOUT_S
    retry_max_attempts: int = 3
    retry_base_delay_s: float = 5.0

    def get_logger(self) -> Any:
        return getattr(self, "logger", get_logger(__name__))

    def command(self) -> str:
        raise NotImplementedError

    def tag(self) -> str:
        return str(self.engine)

    def build_args(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> list[str]:
        raise NotImplementedError

    def stdin_payload(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> bytes | None:
        return prompt.encode()

    def env(self, *, state: Any) -> dict[str, str] | None:
        return None

    def new_state(self, prompt: str, resume: ResumeToken | None) -> Any:
        return JsonlRunState()

    def start_run(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
    ) -> None:
        return None

    def pipes_error_message(self) -> str:
        return f"{self.tag()} failed to open subprocess pipes"

    def next_note_id(self, state: Any) -> str:
        try:
            note_seq = state.note_seq
        except AttributeError as exc:
            raise RuntimeError(
                "state must define note_seq or override next_note_id"
            ) from exc
        state.note_seq = note_seq + 1
        return f"{self.tag()}.note.{state.note_seq}"

    def note_event(
        self,
        message: str,
        *,
        state: Any,
        ok: bool = False,
        detail: dict[str, Any] | None = None,
    ) -> TakopiEvent:
        note_id = self.next_note_id(state)
        action = Action(
            id=note_id,
            kind="warning",
            title=message,
            detail=detail or {},
        )
        return ActionEvent(
            engine=self.engine,
            action=action,
            phase="completed",
            ok=ok,
            message=message,
            level="info" if ok else "warning",
        )

    def invalid_json_events(
        self,
        *,
        raw: str,
        line: str,
        state: Any,
    ) -> list[TakopiEvent]:
        message = f"invalid JSON from {self.tag()}; ignoring line"
        return [self.note_event(message, state=state, detail={"line": line})]

    def decode_jsonl(self, *, line: bytes) -> Any | None:
        text = line.decode("utf-8", errors="replace")
        try:
            return cast(dict[str, Any], json.loads(text))
        except json.JSONDecodeError:
            return None

    async def iter_json_lines(
        self,
        stream: Any,
    ) -> AsyncIterator[bytes]:
        async for raw_line in iter_bytes_lines(stream):
            yield raw_line.rstrip(b"\n")

    async def _iter_jsonl_with_timeouts(
        self,
        stdout: Any,
        *,
        startup_timeout_s: float,
        idle_timeout_s: float,
    ) -> AsyncIterator[bytes]:
        """Yield JSONL lines, enforcing startup and idle timeouts per read.

        The first read uses ``startup_timeout_s``; subsequent reads use
        ``idle_timeout_s``. If a read times out, iteration stops silently
        — the caller decides what to emit based on how many lines were
        produced.
        """
        gen = self.iter_json_lines(stdout)
        first = True
        while True:
            timeout = startup_timeout_s if first else idle_timeout_s
            exhausted = False
            with anyio.move_on_after(timeout) as scope:
                try:
                    raw = await gen.__anext__()
                except StopAsyncIteration:
                    exhausted = True
                    raw = b""
                first = False
                if not exhausted:
                    yield raw
                    continue
            if scope.cancel_called or exhausted:
                return

    def decode_error_events(
        self,
        *,
        raw: str,
        line: str,
        error: Exception,
        state: Any,
    ) -> list[TakopiEvent]:
        message = f"invalid event from {self.tag()}; ignoring line"
        detail = {"line": line, "error": str(error)}
        return [self.note_event(message, state=state, detail=detail)]

    def translate_error_events(
        self,
        *,
        data: Any,
        error: Exception,
        state: Any,
    ) -> list[TakopiEvent]:
        message = f"{self.tag()} translation error; ignoring event"
        detail: dict[str, Any] = {"error": str(error)}
        if isinstance(data, dict):
            detail["type"] = data.get("type")
            item = data.get("item")
            if isinstance(item, dict):
                detail["item_type"] = item.get("type") or item.get("item_type")
        return [self.note_event(message, state=state, detail=detail)]

    def process_error_events(
        self,
        rc: int,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: Any,
    ) -> list[TakopiEvent]:
        message = f"{self.tag()} failed (rc={rc})."
        resume_for_completed = found_session or resume
        return [
            self.note_event(message, state=state),
            CompletedEvent(
                engine=self.engine,
                ok=False,
                answer="",
                resume=resume_for_completed,
                error=message,
            ),
        ]

    def stream_end_events(
        self,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: Any,
    ) -> list[TakopiEvent]:
        message = f"{self.tag()} finished without a result event"
        resume_for_completed = found_session or resume
        return [
            CompletedEvent(
                engine=self.engine,
                ok=False,
                answer="",
                resume=resume_for_completed,
                error=message,
            )
        ]

    def translate(
        self,
        data: Any,
        *,
        state: Any,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        raise NotImplementedError

    def handle_started_event(
        self,
        event: StartedEvent,
        *,
        expected_session: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> tuple[ResumeToken | None, bool]:
        if event.engine != self.engine:
            raise RuntimeError(
                f"{self.tag()} emitted session token for engine {event.engine!r}"
            )
        if expected_session is not None and event.resume != expected_session:
            message = (
                f"{self.tag()} emitted session id {event.resume.value} "
                f"but expected {expected_session.value}"
            )
            raise RuntimeError(message)
        if found_session is None:
            return event.resume, True
        if event.resume != found_session:
            message = (
                f"{self.tag()} emitted session id {event.resume.value} "
                f"but expected {found_session.value}"
            )
            raise RuntimeError(message)
        return found_session, False

    async def _send_payload(
        self,
        proc: Any,
        payload: bytes | None,
        *,
        logger: Any,
        resume: ResumeToken | None,
    ) -> None:
        if payload is not None:
            assert proc.stdin is not None
            await proc.stdin.send(payload)
            await proc.stdin.aclose()
            logger.info(
                "subprocess.stdin.send",
                pid=proc.pid,
                resume=resume.value if resume else None,
                bytes=len(payload),
            )
        elif proc.stdin is not None:
            await proc.stdin.aclose()

    def _decode_jsonl_events(
        self,
        *,
        raw_line: bytes,
        line: bytes,
        jsonl_seq: int,
        state: Any,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        logger: Any,
        pid: int,
    ) -> list[TakopiEvent]:
        raw_text = raw_line.decode("utf-8", errors="replace")
        line_text = line.decode("utf-8", errors="replace")
        try:
            decoded = self.decode_jsonl(line=line)
        except Exception as exc:  # noqa: BLE001
            log_pipeline(
                logger,
                "jsonl.parse.error",
                pid=pid,
                jsonl_seq=jsonl_seq,
                line=line_text,
                error=str(exc),
            )
            return self.decode_error_events(
                raw=raw_text,
                line=line_text,
                error=exc,
                state=state,
            )
        if decoded is None:
            log_pipeline(
                logger,
                "jsonl.parse.invalid",
                pid=pid,
                jsonl_seq=jsonl_seq,
                line=line_text,
            )
            logger.info(
                "runner.jsonl.invalid",
                pid=pid,
                jsonl_seq=jsonl_seq,
                line=line_text,
            )
            return self.invalid_json_events(
                raw=raw_text,
                line=line_text,
                state=state,
            )
        try:
            return self.translate(
                decoded,
                state=state,
                resume=resume,
                found_session=found_session,
            )
        except Exception as exc:  # noqa: BLE001
            log_pipeline(
                logger,
                "runner.translate.error",
                pid=pid,
                jsonl_seq=jsonl_seq,
                error=str(exc),
            )
            return self.translate_error_events(
                data=decoded,
                error=exc,
                state=state,
            )

    def _process_started_event(
        self,
        event: StartedEvent,
        *,
        expected_session: ResumeToken | None,
        found_session: ResumeToken | None,
        logger: Any,
        pid: int,
        jsonl_seq: int,
    ) -> tuple[ResumeToken | None, bool]:
        prior_found = found_session
        try:
            found_session, emit = self.handle_started_event(
                event,
                expected_session=expected_session,
                found_session=found_session,
            )
        except Exception as exc:
            log_pipeline(
                logger,
                "runner.started.error",
                pid=pid,
                jsonl_seq=jsonl_seq,
                resume=event.resume.value,
                expected_session=expected_session.value if expected_session else None,
                found_session=prior_found.value if prior_found else None,
                error=str(exc),
            )
            raise
        if prior_found is None and emit:
            reason = (
                "matched_expected" if expected_session is not None else "first_seen"
            )
        elif prior_found is not None and not emit:
            reason = "duplicate"
        else:
            reason = "unknown"
        log_pipeline(
            logger,
            "runner.started.seen",
            pid=pid,
            jsonl_seq=jsonl_seq,
            resume=event.resume.value,
            expected_session=expected_session.value if expected_session else None,
            found_session=found_session.value if found_session else None,
            emit=emit,
            reason=reason,
        )
        return found_session, emit

    def _log_completed_event(
        self,
        *,
        logger: Any,
        pid: int,
        event: CompletedEvent,
        jsonl_seq: int | None = None,
        source: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "pid": pid,
            "ok": event.ok,
            "has_answer": bool(event.answer.strip()),
            "emit": True,
        }
        if jsonl_seq is not None:
            payload["jsonl_seq"] = jsonl_seq
        if source is not None:
            payload["source"] = source
        log_pipeline(logger, "runner.completed.seen", **payload)

    def _handle_jsonl_line(
        self,
        *,
        raw_line: bytes,
        stream: JsonlStreamState,
        state: Any,
        resume: ResumeToken | None,
        logger: Any,
        pid: int,
    ) -> list[TakopiEvent]:
        if stream.did_emit_completed:
            if not stream.ignored_after_completed:
                log_pipeline(
                    logger,
                    "runner.drop.jsonl_after_completed",
                    pid=pid,
                )
                stream.ignored_after_completed = True
            return []
        line = raw_line.strip()
        if not line:
            return []
        stream.jsonl_seq += 1
        seq = stream.jsonl_seq
        events = self._decode_jsonl_events(
            raw_line=raw_line,
            line=line,
            jsonl_seq=seq,
            state=state,
            resume=resume,
            found_session=stream.found_session,
            logger=logger,
            pid=pid,
        )
        output: list[TakopiEvent] = []
        for evt in events:
            if isinstance(evt, StartedEvent):
                stream.found_session, emit = self._process_started_event(
                    evt,
                    expected_session=stream.expected_session,
                    found_session=stream.found_session,
                    logger=logger,
                    pid=pid,
                    jsonl_seq=seq,
                )
                if not emit:
                    continue
            if isinstance(evt, CompletedEvent):
                stream.did_emit_completed = True
                self._log_completed_event(
                    logger=logger,
                    pid=pid,
                    event=evt,
                    jsonl_seq=seq,
                )
                output.append(evt)
                break
            output.append(evt)
        return output

    async def _iter_jsonl_events(
        self,
        *,
        stdout: Any,
        stream: JsonlStreamState,
        state: Any,
        resume: ResumeToken | None,
        logger: Any,
        pid: int,
        startup_timeout_s: float | None = None,
        idle_timeout_s: float | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        if startup_timeout_s is not None and idle_timeout_s is not None:
            line_iter: AsyncIterator[bytes] = self._iter_jsonl_with_timeouts(
                stdout,
                startup_timeout_s=startup_timeout_s,
                idle_timeout_s=idle_timeout_s,
            )
        else:
            line_iter = self.iter_json_lines(stdout)
        got_any = False
        async for raw_line in line_iter:
            got_any = True
            for evt in self._handle_jsonl_line(
                raw_line=raw_line,
                stream=stream,
                state=state,
                resume=resume,
                logger=logger,
                pid=pid,
            ):
                yield evt
        if (
            not got_any
            and not stream.did_emit_completed
            and startup_timeout_s is not None
        ):
            tag = self.tag()
            yield self.note_event(
                f"{tag} produced no JSON events within "
                f"{startup_timeout_s:.0f}s; prompt was spawned but no "
                "session started",
                state=state,
            )
            yield CompletedEvent(
                engine=self.engine,
                resume=resume,
                ok=False,
                answer="",
                error="startup timeout",
            )

    async def _run_single_attempt(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: Any,
        logger: Any,
    ) -> AsyncIterator[AttemptBatch]:
        """Run one subprocess attempt, yielding event batches.

        Stream events arrive as single-event batches with ``rc=None``. When the
        subprocess exits without a terminal stream completion, one final batch
        is yielded with empty ``events``, the raw ``stderr``, the exit code,
        and ``pid``; the caller classifies it before deciding retry vs emit.
        """
        cmd = [self.command(), *self.build_args(prompt, resume, state=state)]
        payload = self.stdin_payload(prompt, resume, state=state)
        env = self.env(state=state)
        tag = self.tag()
        cwd = get_run_base_dir()

        async with manage_subprocess(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            close_timeout=self.shutdown_timeout_s,
        ) as proc:
            if proc.stdout is None or proc.stderr is None:
                raise RuntimeError(self.pipes_error_message())
            if payload is not None and proc.stdin is None:
                raise RuntimeError(self.pipes_error_message())

            logger.info(
                "subprocess.spawn",
                cmd=cmd[0] if cmd else None,
                args=cmd[1:],
                pid=proc.pid,
            )

            await self._send_payload(proc, payload, logger=logger, resume=resume)

            rc: int | None = None
            stream = JsonlStreamState(expected_session=resume)
            stderr_capture: list[str] = []

            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    drain_stderr,
                    proc.stderr,
                    logger,
                    tag,
                    stderr_capture,
                )
                async for evt in self._iter_jsonl_events(
                    stdout=proc.stdout,
                    stream=stream,
                    state=state,
                    resume=resume,
                    logger=logger,
                    pid=proc.pid,
                    startup_timeout_s=self.startup_timeout_s,
                    idle_timeout_s=self.idle_timeout_s,
                ):
                    yield AttemptBatch(events=(evt,), stderr="", pid=proc.pid)

                rc = await proc.wait()

            logger.info("subprocess.exit", pid=proc.pid, rc=rc)
            if stream.did_emit_completed:
                return
            yield AttemptBatch(
                events=(),
                stderr="\n".join(stderr_capture),
                pid=proc.pid,
                rc=rc,
            )

    async def run_impl(
        self, prompt: str, resume: ResumeToken | None
    ) -> AsyncIterator[TakopiEvent]:
        logger = self.get_logger()
        logger.info(
            "runner.start",
            engine=self.engine,
            resume=resume.value if resume else None,
            prompt=prompt,
            prompt_len=len(prompt),
            prompt_sha256=_prompt_fingerprint(prompt),
            prompt_preview=_safe_preview(prompt),
        )

        max_attempts = max(1, int(self.retry_max_attempts))
        base_delay = float(self.retry_base_delay_s)
        engine = self.engine
        found_session: ResumeToken | None = None

        for attempt in range(1, max_attempts + 1):
            state = self.new_state(prompt, resume)
            self.start_run(prompt, resume, state=state)

            started_emitted = False
            action_emitted = False
            answer_emitted = False
            held_failure: CompletedEvent | None = None
            held_pid = 0
            terminal_rc: int | None = None
            terminal_stderr = ""
            settled = False

            async for batch in self._run_single_attempt(
                prompt, resume, state=state, logger=logger
            ):
                pid = batch.pid
                if batch.events:
                    for evt in batch.events:
                        if isinstance(evt, StartedEvent):
                            started_emitted = True
                            found_session = evt.resume
                            yield evt
                        elif isinstance(evt, ActionEvent):
                            action_emitted = True
                            yield evt
                        elif isinstance(evt, CompletedEvent):
                            if evt.ok:
                                self._log_completed_event(
                                    logger=logger,
                                    pid=pid,
                                    event=evt,
                                )
                                yield evt
                                settled = True
                                continue
                            # Failed stream completion: classify for clean error.
                            failure = classify_transient_failure(
                                evt.error or batch.stderr
                            )
                            if failure is not None:
                                evt = replace(
                                    evt,
                                    error=format_transient_failure(engine, failure),
                                )
                            # Side effects make replay unsafe: emit immediately.
                            if (
                                failure is None
                                or started_emitted
                                or action_emitted
                                or evt.answer.strip()
                            ):
                                answer_emitted = (
                                    bool(evt.answer.strip()) or answer_emitted
                                )
                                self._log_completed_event(
                                    logger=logger,
                                    pid=pid,
                                    event=evt,
                                )
                                yield evt
                                settled = True
                            else:
                                held_failure = evt
                                held_pid = pid
                        else:
                            yield evt
                else:
                    # Terminal batch: process exited without a stream completion.
                    terminal_rc = batch.rc
                    terminal_stderr = batch.stderr

            if settled:
                return

            # Build terminal failure events. A held stream failure
            # (CompletedEvent from the stream itself) takes precedence over
            # a raw-exit failure. The terminal events list may include
            # synthetic StartedEvents and notes from runner overrides
            # (e.g. GrokRunner.process_error_events).
            terminal_events: list[TakopiEvent] = []
            if held_failure is not None:
                terminal_events = [held_failure]
            elif terminal_rc is not None and terminal_rc != 0:
                terminal_events = self._terminal_failure_events(
                    rc=terminal_rc,
                    stderr=terminal_stderr,
                    resume=resume,
                    found_session=found_session,
                    state=state,
                    engine=engine,
                    logger=logger,
                    pid=held_pid,
                )
            else:
                terminal_events = self._stream_end_failure_events(
                    resume=resume,
                    found_session=found_session,
                    state=state,
                    logger=logger,
                    pid=held_pid,
                )

            # Extract the CompletedEvent for classification.
            combined = next(
                (e for e in terminal_events if isinstance(e, CompletedEvent)),
                None,
            )
            if combined is None:
                combined = CompletedEvent(
                    engine=engine,
                    ok=False,
                    answer="",
                    resume=found_session or resume,
                    error=f"{engine} failed without a result event",
                )
                terminal_events.append(combined)

            can_retry = (
                attempt < max_attempts
                and not started_emitted
                and not action_emitted
                and not answer_emitted
                and classify_transient_failure(combined.error or terminal_stderr)
                is not None
            )

            if can_retry:
                failure = classify_transient_failure(combined.error or terminal_stderr)
                assert failure is not None  # can_retry guarantees it
                delay = base_delay * attempt
                status = (
                    f" (HTTP {failure.http_status})"
                    if failure.http_status in (429, 503)
                    else ""
                )
                yield self.note_event(
                    f"{engine} upstream busy{status}; "
                    f"retrying in {_format_delay(delay)}s "
                    f"(attempt {attempt + 1}/{max_attempts})",
                    state=state,
                )
                await anyio.sleep(delay)
                continue

            # Exhausted or non-transient: emit all terminal events
            # (StartedEvent, notes, then the CompletedEvent).
            for evt in terminal_events:
                if isinstance(evt, CompletedEvent):
                    self._log_completed_event(
                        logger=logger,
                        pid=held_pid,
                        event=evt,
                    )
                yield evt
            return

    def _terminal_failure_events(
        self,
        *,
        rc: int,
        stderr: str,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: Any,
        engine: str,
        logger: Any,
        pid: int,
    ) -> list[TakopiEvent]:
        """Build terminal failure events for a nonzero raw-exit failure.

        Delegates to ``process_error_events`` (which runners like Grok override
        to emit a synthetic ``StartedEvent``), then replaces the
        ``CompletedEvent`` error with a clean message when the stderr is a
        transient upstream failure.
        """
        events = self.process_error_events(
            rc,
            resume=resume,
            found_session=found_session,
            state=state,
        )
        failure = classify_transient_failure(stderr)
        if failure is None:
            return events
        clean = format_transient_failure(engine, failure)
        # For transient failures, suppress the generic "failed (rc=N)" note
        # (the user already saw retry notes) but keep StartedEvent and the
        # CompletedEvent with a clean message.
        return [
            replace(evt, error=clean) if isinstance(evt, CompletedEvent) else evt
            for evt in events
            if not isinstance(evt, ActionEvent)
        ]

    def _stream_end_failure_events(
        self,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: Any,
        logger: Any,
        pid: int,
    ) -> list[TakopiEvent]:
        """Build terminal failure events for the stream-end (rc==0) path."""
        return self.stream_end_events(
            resume=resume,
            found_session=found_session,
            state=state,
        )


class Runner(Protocol):
    engine: str

    def is_resume_line(self, line: str) -> bool: ...

    def format_resume(self, token: ResumeToken) -> str: ...

    def extract_resume(self, text: str | None) -> ResumeToken | None: ...

    def run(
        self,
        prompt: str,
        resume: ResumeToken | None,
    ) -> AsyncIterator[TakopiEvent]: ...

    def compact_support(self) -> CompactSupport: ...

    def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]: ...


class RunnerTurnControl(Protocol):
    async def steer(self, text: str) -> None: ...

    async def interrupt(self) -> bool: ...
