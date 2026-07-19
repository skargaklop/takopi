from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import msgspec

from ..backends import EngineBackend, EngineConfig
from ..config import ConfigError
from ..events import EventFactory
from ..logging import get_logger
from ..model import EngineId, ResumeToken, TakopiEvent
from ..runner import JsonlSubprocessRunner, ResumeTokenMixin, Runner
from ..schemas import grok as grok_schema
from .modes import effective_prompt, run_modes
from .run_options import get_run_options

logger = get_logger(__name__)

ENGINE: EngineId = "grok"

_RESUME_RE = re.compile(
    r"(?im)^\s*`?grok\s+(?:resume|--resume|-r)\s+(?P<token>[^`\s]+)`?(?:\s|$)"
)
_RESUME_LINE_RE = re.compile(
    r"(?im)^\s*`?grok\s+(?:resume|--resume|-r)\s+(?P<token>[^`\s]+)`?\s*$"
)


@dataclass(slots=True)
class GrokStreamState:
    resume: ResumeToken
    factory: EventFactory = field(default_factory=lambda: EventFactory(ENGINE))
    last_assistant_text: str = ""
    started: bool = False
    note_seq: int = 0


def _coerce_comma_list(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value if item is not None]
        joined = ",".join(part for part in parts if part)
        return joined or None
    text = str(value).strip()
    return text or None


def _usage_payload(event: grok_schema.StreamEndEvent | grok_schema.StreamErrorEvent) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    for key in (
        "num_turns",
        "requestId",
        "stopReason",
        "total_cost_usd",
        "total_cost_usd_ticks",
        "cost_is_partial",
        "usage_is_incomplete",
    ):
        value = getattr(event, key, None)
        if value is not None:
            usage[key] = value
    if event.usage is not None:
        usage["usage"] = event.usage
    model_usage = getattr(event, "modelUsage", None)
    if model_usage is not None:
        usage["modelUsage"] = model_usage
    return usage


def translate_grok_event(
    event: grok_schema.GrokEvent,
    *,
    title: str,
    state: GrokStreamState,
    meta: dict[str, Any] | None = None,
) -> list[TakopiEvent]:
    out: list[TakopiEvent] = []

    if not state.started:
        state.started = True
        out.append(
            state.factory.started(state.resume, title=title, meta=meta or None)
        )

    match event:
        case grok_schema.StreamTextEvent(data=data):
            if data:
                state.last_assistant_text += data
            return out

        case grok_schema.StreamThoughtEvent(data=data):
            if data:
                state.note_seq += 1
                out.append(
                    state.factory.action_completed(
                        action_id=f"grok.thought.{state.note_seq}",
                        kind="note",
                        title=data,
                        ok=True,
                        detail={},
                    )
                )
            return out

        case grok_schema.StreamEndEvent():
            session_id = event.sessionId or state.resume.value
            resume = ResumeToken(engine=ENGINE, value=session_id)
            # Keep factory resume aligned with the canonical token we started with
            # unless the CLI reports a different session id (should match --session-id).
            if session_id != state.resume.value:
                state.resume = resume
            usage = _usage_payload(event)
            stop = (event.stopReason or "").lower()
            ok = stop not in {"error", "aborted", "cancelled", "canceled"}
            error = None if ok else f"grok run stopped ({event.stopReason})"
            out.append(
                state.factory.completed(
                    ok=ok,
                    answer=state.last_assistant_text,
                    resume=resume,
                    error=error,
                    usage=usage or None,
                )
            )
            return out

        case grok_schema.StreamErrorEvent():
            session_id = event.sessionId or state.resume.value
            resume = ResumeToken(engine=ENGINE, value=session_id)
            usage = _usage_payload(event)
            message = event.message or "grok run failed"
            out.append(
                state.factory.completed(
                    ok=False,
                    answer=state.last_assistant_text,
                    resume=resume,
                    error=message,
                    usage=usage or None,
                )
            )
            return out

        case _:
            return out


@dataclass(slots=True)
class GrokRunner(ResumeTokenMixin, JsonlSubprocessRunner):
    engine: EngineId = ENGINE
    resume_re: re.Pattern[str] = _RESUME_RE

    grok_cmd: str = "grok"
    model: str | None = None
    yolo: bool = True
    tools: list[str] | str | None = None
    disallowed_tools: list[str] | str | None = None
    reasoning_effort: str | None = None
    max_turns: int | None = None
    extra_args: list[str] = field(default_factory=list)
    session_title: str = "grok"
    logger = logger

    def format_resume(self, token: ResumeToken) -> str:
        if token.engine != ENGINE:
            raise RuntimeError(f"resume token is for engine {token.engine!r}")
        return f"`grok --resume {token.value}`"

    def is_resume_line(self, line: str) -> bool:
        return bool(_RESUME_LINE_RE.match(line))

    def command(self) -> str:
        return self.grok_cmd

    def build_args(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: GrokStreamState,
    ) -> list[str]:
        run_options = get_run_options()
        plan, _goal = run_modes(run_options)
        prompt = effective_prompt(prompt, soft_plan=False, options=run_options)
        args: list[str] = [*self.extra_args]
        args.extend(["-p", prompt])
        args.extend(["--output-format", "streaming-json"])

        if plan:
            args.extend(["--permission-mode", "plan"])
        elif self.yolo is True:
            args.append("--yolo")

        model = self.model
        if run_options is not None and run_options.model:
            model = run_options.model
        if model is not None:
            args.extend(["-m", str(model)])

        reasoning = self.reasoning_effort
        if run_options is not None and run_options.reasoning:
            reasoning = run_options.reasoning
        if reasoning is not None:
            args.extend(["--effort", str(reasoning)])

        tools = _coerce_comma_list(self.tools)
        if tools is not None:
            args.extend(["--tools", tools])

        disallowed = _coerce_comma_list(self.disallowed_tools)
        if disallowed is not None:
            args.extend(["--disallowed-tools", disallowed])

        if self.max_turns is not None:
            args.extend(["--max-turns", str(self.max_turns)])

        if resume is not None:
            args.extend(["--resume", resume.value])
        else:
            args.extend(["--session-id", state.resume.value])

        return args

    def stdin_payload(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: GrokStreamState,
    ) -> bytes | None:
        return None

    def env(self, *, state: GrokStreamState) -> dict[str, str] | None:
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("GROK_DISABLE_AUTOUPDATER", "1")
        return env

    def new_state(self, prompt: str, resume: ResumeToken | None) -> GrokStreamState:
        if resume is not None:
            token = resume
            if token.engine != ENGINE:
                token = ResumeToken(engine=ENGINE, value=resume.value)
        else:
            token = ResumeToken(engine=ENGINE, value=str(uuid4()))
        return GrokStreamState(resume=token, started=False)

    def decode_jsonl(self, *, line: bytes) -> grok_schema.GrokEvent:
        return grok_schema.decode_event(line)

    def decode_error_events(
        self,
        *,
        raw: str,
        line: str,
        error: Exception,
        state: GrokStreamState,
    ) -> list[TakopiEvent]:
        if isinstance(error, msgspec.DecodeError):
            self.get_logger().warning(
                "jsonl.msgspec.invalid",
                tag=self.tag(),
                error=str(error),
                error_type=error.__class__.__name__,
            )
            return []
        return super().decode_error_events(
            raw=raw,
            line=line,
            error=error,
            state=state,
        )

    def invalid_json_events(
        self,
        *,
        raw: str,
        line: str,
        state: GrokStreamState,
    ) -> list[TakopiEvent]:
        return []

    def translate(
        self,
        data: grok_schema.GrokEvent,
        *,
        state: GrokStreamState,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        meta: dict[str, Any] = {"cwd": os.getcwd()}
        if self.model:
            meta["model"] = self.model
        return translate_grok_event(
            data,
            title=self.session_title,
            state=state,
            meta=meta or None,
        )

    def process_error_events(
        self,
        rc: int,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: GrokStreamState,
    ) -> list[TakopiEvent]:
        message = f"grok failed (rc={rc})."
        resume_for_completed = found_session or resume or state.resume
        out: list[TakopiEvent] = []
        if not state.started:
            out.append(
                state.factory.started(
                    resume_for_completed or state.resume,
                    title=self.session_title,
                )
            )
            state.started = True
        out.append(self.note_event(message, state=state, ok=False))
        out.append(
            state.factory.completed_error(
                error=message,
                answer=state.last_assistant_text,
                resume=resume_for_completed,
            )
        )
        return out

    def stream_end_events(
        self,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: GrokStreamState,
    ) -> list[TakopiEvent]:
        resume_for_completed = found_session or resume or state.resume
        message = "grok finished without an end event"
        out: list[TakopiEvent] = []
        if not state.started:
            out.append(
                state.factory.started(
                    resume_for_completed or state.resume,
                    title=self.session_title,
                )
            )
            state.started = True
        out.append(
            state.factory.completed_error(
                error=message,
                answer=state.last_assistant_text,
                resume=resume_for_completed,
            )
        )
        return out


def build_runner(config: EngineConfig, config_path: Path) -> Runner:
    grok_cmd = shutil.which("grok") or "grok"

    model = config.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError(f"Invalid `grok.model` in {config_path}; expected a string.")

    yolo = True if "yolo" not in config else config.get("yolo") is True

    tools = config.get("tools")
    if tools is not None and not isinstance(tools, (str, list, tuple, set)):
        raise ConfigError(
            f"Invalid `grok.tools` in {config_path}; expected a string or list of strings."
        )

    disallowed_tools = config.get("disallowed_tools")
    if disallowed_tools is not None and not isinstance(
        disallowed_tools, (str, list, tuple, set)
    ):
        raise ConfigError(
            f"Invalid `grok.disallowed_tools` in {config_path}; "
            "expected a string or list of strings."
        )

    reasoning_effort = config.get("reasoning_effort")
    if reasoning_effort is not None and not isinstance(reasoning_effort, str):
        raise ConfigError(
            f"Invalid `grok.reasoning_effort` in {config_path}; expected a string."
        )

    max_turns = config.get("max_turns")
    if max_turns is not None and not isinstance(max_turns, int):
        raise ConfigError(
            f"Invalid `grok.max_turns` in {config_path}; expected an integer."
        )

    extra_args_value = config.get("extra_args")
    if extra_args_value is None:
        extra_args: list[str] = []
    elif isinstance(extra_args_value, list) and all(
        isinstance(x, str) for x in extra_args_value
    ):
        extra_args = list(extra_args_value)
    else:
        raise ConfigError(
            f"Invalid `grok.extra_args` in {config_path}; expected a list of strings."
        )

    title = str(model) if model is not None else "grok"

    return GrokRunner(
        grok_cmd=grok_cmd,
        model=model,
        yolo=yolo,
        tools=tools,
        disallowed_tools=disallowed_tools,
        reasoning_effort=reasoning_effort,
        max_turns=max_turns,
        extra_args=extra_args,
        session_title=title,
    )


BACKEND = EngineBackend(
    id="grok",
    build_runner=build_runner,
    cli_cmd="grok",
    install_cmd="Install Grok Build CLI (grok) and ensure it is on PATH",
)
