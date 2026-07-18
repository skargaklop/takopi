from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..backends import EngineBackend, EngineConfig
from ..config import ConfigError
from ..model import ActionEvent, CompletedEvent, EngineId, ResumeToken, StartedEvent, TakopiEvent
from ..runner import Runner
from .pi import PiRunner, PiStreamState, pi_schema
from .run_options import get_run_options

ENGINE: EngineId = "omp"

_TOKEN_PATTERN = r'(?P<token>"[^"]+"|\'[^\']+\'|[^\s`]+)'
_RESUME_RE = re.compile(
    rf"(?im)^\s*`?(?:(?:/)?omp\s+(?:--resume|--session|-r|-s|resume))\s+{_TOKEN_PATTERN}`?(?:\s|$)"
)
_RESUME_LINE_RE = re.compile(
    rf"(?im)^\s*`?(?:(?:/)?omp\s+(?:--resume|--session|-r|-s|resume))\s+{_TOKEN_PATTERN}`?\s*$"
)


def _retag_resume(token: ResumeToken | None) -> ResumeToken | None:
    if token is None or token.engine == ENGINE:
        return token
    return ResumeToken(engine=ENGINE, value=token.value)


def _retag_event(event: TakopiEvent) -> TakopiEvent:
    match event:
        case StartedEvent():
            return replace(
                event,
                engine=ENGINE,
                resume=_retag_resume(event.resume),
                title="omp",
            )
        case ActionEvent():
            return replace(event, engine=ENGINE)
        case CompletedEvent():
            return replace(
                event,
                engine=ENGINE,
                resume=_retag_resume(event.resume),
            )
        case _:
            return event


def _unquote_token(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


class OmpRunner(PiRunner):
    engine: EngineId = ENGINE
    session_title: str = "omp"
    resume_re: re.Pattern[str] = _RESUME_RE

    def format_resume(self, token: ResumeToken) -> str:
        if token.engine != ENGINE:
            raise RuntimeError(f"resume token is for engine {token.engine!r}")
        return f"`omp --resume {self._quote_token(token.value)}`"

    def extract_resume(self, text: str | None) -> ResumeToken | None:
        if not text:
            return None
        found: str | None = None
        for match in _RESUME_RE.finditer(text):
            token = match.group("token")
            if token:
                found = _unquote_token(token)
        if not found:
            return None
        return ResumeToken(engine=ENGINE, value=found)

    def is_resume_line(self, line: str) -> bool:
        return bool(_RESUME_LINE_RE.match(line))

    def command(self) -> str:
        return "omp"

    def build_args(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: PiStreamState,
    ) -> list[str]:
        run_options = get_run_options()
        args: list[str] = [*self.extra_args, "--print", "--mode", "json"]
        if self.provider:
            args.extend(["--provider", self.provider])
        model = self.model
        if run_options is not None and run_options.model:
            model = run_options.model
        if model:
            args.extend(["--model", model])
        if run_options is not None and run_options.reasoning:
            args.extend(["--thinking", str(run_options.reasoning)])
        if resume is not None:
            args.extend(["--resume", resume.value])
        if run_options is not None:
            args.extend(
                f"@{attachment.rel_path}"
                for attachment in run_options.attachments
                if attachment.kind == "image" and attachment.rel_path
            )
        args.append(self._sanitize_prompt(prompt))
        return args

    def new_state(self, prompt: str, resume: ResumeToken | None) -> PiStreamState:
        if resume is not None:
            return PiStreamState(resume=resume)
        return PiStreamState(
            resume=ResumeToken(engine=ENGINE, value="pending.jsonl"),
            allow_id_promotion=True,
        )

    def translate(
        self,
        data: pi_schema.PiEvent,
        *,
        state: PiStreamState,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        meta: dict[str, Any] = {"cwd": os.getcwd()}
        if self.model:
            meta["model"] = self.model
        if self.provider:
            meta["provider"] = self.provider
        return [
            _retag_event(event)
            for event in super().translate(
                data,
                state=state,
                resume=resume,
                found_session=found_session,
            )
        ]

    def process_error_events(
        self,
        rc: int,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: PiStreamState,
    ) -> list[TakopiEvent]:
        message = f"{ENGINE} failed (rc={rc})."
        resume_for_completed = found_session or resume or state.resume
        return [
            self.note_event(message, state=state),
            CompletedEvent(
                engine=ENGINE,
                ok=False,
                answer=state.last_assistant_text or "",
                resume=_retag_resume(resume_for_completed),
                error=message,
                usage=state.last_usage,
            ),
        ]

    def stream_end_events(
        self,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: PiStreamState,
    ) -> list[TakopiEvent]:
        resume_for_completed = found_session or resume or state.resume
        message = f"{ENGINE} finished without an agent_end event"
        return [
            CompletedEvent(
                engine=ENGINE,
                ok=False,
                answer=state.last_assistant_text or "",
                resume=_retag_resume(resume_for_completed),
                error=message,
                usage=state.last_usage,
            )
        ]


def build_runner(config: EngineConfig, config_path: Path) -> Runner:
    extra_args_value = config.get("extra_args")
    if extra_args_value is None:
        extra_args = []
    elif isinstance(extra_args_value, list) and all(
        isinstance(x, str) for x in extra_args_value
    ):
        extra_args = list(extra_args_value)
    else:
        raise ConfigError(
            f"Invalid `omp.extra_args` in {config_path}; expected a list of strings."
        )

    model = config.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError(f"Invalid `omp.model` in {config_path}; expected a string.")

    provider = config.get("provider")
    if provider is not None and not isinstance(provider, str):
        raise ConfigError(f"Invalid `omp.provider` in {config_path}; expected a string.")

    return OmpRunner(
        extra_args=extra_args,
        model=model,
        provider=provider,
    )


BACKEND = EngineBackend(
    id=ENGINE,
    build_runner=build_runner,
    cli_cmd="omp",
    install_cmd="bun install -g @oh-my-pi/pi-coding-agent",
)
