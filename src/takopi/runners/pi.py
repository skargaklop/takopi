from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path, PurePath
from typing import Any
from uuid import uuid4

import msgspec

from ..backends import EngineBackend, EngineConfig
from ..config import ConfigError
from ..logging import get_logger
from ..model import (
    Action,
    ActionEvent,
    ActionKind,
    ActionLevel,
    ActionPhase,
    CompletedEvent,
    EngineId,
    ResumeToken,
    StartedEvent,
    TakopiEvent,
)
from ..runner import JsonlSubprocessRunner, ResumeTokenMixin, Runner
from .modes import apply_soft_plan_prompt, run_modes
from ._compact_mixin import SlashCompactMixin
from .run_options import get_run_options
from ..schemas import pi as pi_schema
from ..utils.paths import get_run_base_dir
from .tool_actions import tool_kind_and_title

logger = get_logger(__name__)

ENGINE: EngineId = "pi"

_TOKEN_PATTERN = r'(?P<token>"[^"]+"|\'[^\']+\'|[^\s`]+)'
_RESUME_RE = re.compile(
    rf"(?im)^\s*`?pi\s+(?:--session|resume|--resume|-r|-s)\s+{_TOKEN_PATTERN}`?(?:\s|$)"
)
_RESUME_LINE_RE = re.compile(
    rf"(?im)^\s*`?pi\s+(?:--session|resume|--resume|-r|-s)\s+{_TOKEN_PATTERN}`?\s*$"
)

_SESSION_ID_PREFIX_LEN = 8


@dataclass(slots=True)
class PiStreamState:
    resume: ResumeToken
    allow_id_promotion: bool = False
    pending_actions: dict[str, Action] = field(default_factory=dict)
    last_assistant_text: str | None = None
    last_assistant_error: str | None = None
    last_usage: dict[str, Any] | None = None
    started: bool = False
    note_seq: int = 0


def _looks_like_session_path(token: str) -> bool:
    if not token:
        return False
    if token.endswith(".jsonl"):
        return True
    if "/" in token or "\\" in token:
        return True
    return token.startswith("~")


def _short_session_id(session_id: str) -> str:
    if not session_id:
        return session_id
    if "-" in session_id:
        return session_id.split("-", 1)[0]
    if len(session_id) > _SESSION_ID_PREFIX_LEN:
        return session_id[:_SESSION_ID_PREFIX_LEN]
    return session_id


def _maybe_promote_session_id(state: PiStreamState, session_id: str | None) -> None:
    if not session_id:
        return
    if state.started:
        return
    if not state.allow_id_promotion:
        return
    if not _looks_like_session_path(state.resume.value):
        return
    state.resume = ResumeToken(engine=ENGINE, value=_short_session_id(session_id))
    state.allow_id_promotion = False


def _action_event(
    *,
    phase: ActionPhase,
    action: Action,
    ok: bool | None = None,
    message: str | None = None,
    level: ActionLevel | None = None,
) -> ActionEvent:
    return ActionEvent(
        engine=ENGINE,
        action=action,
        phase=phase,
        ok=ok,
        message=message,
        level=level,
    )


def _extract_text_blocks(content: Any) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    if not parts:
        return None
    return "".join(parts).strip() or None


def _assistant_error(message: dict[str, Any]) -> str | None:
    stop_reason = message.get("stopReason")
    if stop_reason in {"error", "aborted"}:
        error = message.get("errorMessage")
        if isinstance(error, str) and error:
            return error
        return f"pi run {stop_reason}"
    return None


def _tool_kind_and_title(
    name: str,
    args: dict[str, Any],
) -> tuple[ActionKind, str]:
    return tool_kind_and_title(name, args, path_keys=("path",))


def _last_assistant_message(messages: Any) -> dict[str, Any] | None:
    if not isinstance(messages, list):
        return None
    for item in reversed(messages):
        if isinstance(item, dict) and item.get("role") == "assistant":
            return item
    return None


def translate_pi_event(
    event: pi_schema.PiEvent,
    *,
    title: str,
    meta: dict[str, Any] | None,
    state: PiStreamState,
) -> list[TakopiEvent]:
    out: list[TakopiEvent] = []
    if isinstance(event, pi_schema.SessionHeader):
        _maybe_promote_session_id(state, event.id)
        if not state.started:
            out.append(
                StartedEvent(
                    engine=ENGINE,
                    resume=state.resume,
                    title=title,
                    meta=meta or None,
                )
            )
            state.started = True
        return out

    if not state.started:
        out.append(
            StartedEvent(
                engine=ENGINE,
                resume=state.resume,
                title=title,
                meta=meta or None,
            )
        )
        state.started = True

    match event:
        case pi_schema.ToolExecutionStart(
            toolCallId=tool_id, toolName=tool_name, args=args
        ):
            if not isinstance(args, dict):
                args = {}
            if isinstance(tool_id, str) and tool_id:
                name = str(tool_name or "tool")
                kind, title_str = _tool_kind_and_title(name, args)
                detail: dict[str, Any] = {"tool_name": name, "args": args}
                if kind == "file_change":
                    path = args.get("path")
                    if path:
                        detail["changes"] = [{"path": str(path), "kind": "update"}]
                action = Action(id=tool_id, kind=kind, title=title_str, detail=detail)
                state.pending_actions[action.id] = action
                out.append(_action_event(phase="started", action=action))
            return out

        case pi_schema.ToolExecutionEnd(
            toolCallId=tool_id, toolName=tool_name, result=result, isError=is_error
        ):
            if isinstance(tool_id, str) and tool_id:
                action = state.pending_actions.pop(tool_id, None)
                name = str(tool_name or "tool")
                if action is None:
                    action = Action(id=tool_id, kind="tool", title=name, detail={})
                detail = dict(action.detail)
                detail["result"] = result
                detail["is_error"] = is_error
                out.append(
                    _action_event(
                        phase="completed",
                        action=Action(
                            id=action.id,
                            kind=action.kind,
                            title=action.title,
                            detail=detail,
                        ),
                        ok=not is_error,
                    )
                )
            return out

        case pi_schema.MessageEnd(message=message):
            if isinstance(message, dict) and message.get("role") == "assistant":
                text = _extract_text_blocks(message.get("content"))
                if text:
                    state.last_assistant_text = text
                usage = message.get("usage")
                if isinstance(usage, dict):
                    state.last_usage = usage
                error = _assistant_error(message)
                if error:
                    state.last_assistant_error = error
            return out

        case pi_schema.AgentEnd(messages=messages):
            assistant = _last_assistant_message(messages)
            if assistant:
                text = _extract_text_blocks(assistant.get("content"))
                if text:
                    state.last_assistant_text = text
                usage = assistant.get("usage")
                if isinstance(usage, dict):
                    state.last_usage = usage
                error = _assistant_error(assistant)
                if error:
                    state.last_assistant_error = error

            ok = state.last_assistant_error is None
            error = state.last_assistant_error
            answer = state.last_assistant_text or ""

            out.append(
                CompletedEvent(
                    engine=ENGINE,
                    ok=ok,
                    answer=answer,
                    resume=state.resume,
                    error=error,
                    usage=state.last_usage,
                )
            )
            return out

        case _:
            return out


class PiRunner(SlashCompactMixin, ResumeTokenMixin, JsonlSubprocessRunner):
    compact_accepts_instructions = True
    engine: EngineId = ENGINE
    resume_re: re.Pattern[str] = _RESUME_RE
    session_title: str = "pi"
    logger = logger

    def __init__(
        self,
        *,
        extra_args: list[str],
        model: str | None,
        provider: str | None,
        plan_mode_extension: bool = True,
    ) -> None:
        self.extra_args = extra_args
        self.model = model
        self.provider = provider
        self.plan_mode_extension = plan_mode_extension
        self._plan_warning_logged = False

    def format_resume(self, token: ResumeToken) -> str:
        if token.engine != ENGINE:
            raise RuntimeError(f"resume token is for engine {token.engine!r}")
        return f"`pi --session {self._quote_token(token.value)}`"

    def run(
        self, prompt: str, resume: ResumeToken | None
    ) -> AsyncIterator[TakopiEvent]:
        return super().run(prompt, resume)

    def extract_resume(self, text: str | None) -> ResumeToken | None:
        if not text:
            return None
        found: str | None = None
        for match in self.resume_re.finditer(text):
            token = match.group("token")
            if not token:
                continue
            token = token.strip()
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
                token = token[1:-1]
            found = token
        if not found:
            return None
        return ResumeToken(engine=self.engine, value=found)

    def is_resume_line(self, line: str) -> bool:
        return bool(_RESUME_LINE_RE.match(line))

    def command(self) -> str:
        import sys

        return "pi.cmd" if sys.platform == "win32" else "pi"

    def _resolve_session_path(self, session_id: str) -> str:
        """Resolve a session UUID to its full file path, so Pi doesn't prompt
        about cross-project fork when the session belongs to a different directory."""
        if _looks_like_session_path(session_id):
            return session_id
        from pathlib import Path as _Path

        agent_dir = _Path(
            os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")
        ).expanduser()
        sessions_root = agent_dir / "sessions"
        if not sessions_root.is_dir():
            return session_id
        for project_dir in sorted(sessions_root.iterdir()):
            if not project_dir.is_dir():
                continue
            for f in project_dir.iterdir():
                if f.name.endswith(".jsonl") and session_id in f.name:
                    return str(f.resolve())
        return session_id

    def _final_prompt(self, prompt: str) -> str:
        """Apply goal/plan mode mutations to the prompt.

        - Goal mode: injects the autonomous-goal prefix (unchanged).
        - Plan mode + extension: delegates to the extension via ``--plan``,
          no prompt mutation.
        - Plan mode + no extension: applies the soft-plan prompt prefix
          (graceful fallback) and logs a one-time warning.
        """
        run_options = get_run_options()
        plan, goal = run_modes(run_options)
        if goal is not None:
            body = prompt.strip()
            note = f"(autonomous goal — work until: {goal})"
            return f"{note}\n\n{body}" if body else note
        if plan and not self.plan_mode_extension:
            if not self._plan_warning_logged:
                logger.warning("pi.plan_mode_extension_missing")
                self._plan_warning_logged = True
            return apply_soft_plan_prompt(prompt)
        return prompt

    @staticmethod
    def _prompt_needs_stdin(prompt: str) -> bool:
        """True when the prompt must be sent via stdin instead of a CLI arg.

        ``pi.cmd`` (the Windows batch wrapper) rejects argv elements containing
        newlines with "batch file arguments are invalid" (rc=126). The
        autonomous-goal prefix and any multi-line user prompt inject newlines,
        so they are piped through stdin; single-line prompts keep the argv
        path to match the existing session/attachment ordering contract.
        """
        return "\n" in prompt

    def build_args(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: PiStreamState,
    ) -> list[str]:
        run_options = get_run_options()
        plan, _goal = run_modes(run_options)
        final_prompt = self._final_prompt(prompt)
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
        if plan and self.plan_mode_extension:
            args.append("--plan")
        session_value = self._resolve_session_path(state.resume.value)
        args.extend(["--session", session_value])
        # Layer B: pi accepts @file references in the initial message list.
        if run_options is not None:
            args.extend(
                f"@{attachment.rel_path}"
                for attachment in run_options.attachments
                if attachment.kind == "image" and attachment.rel_path
            )
        if not self._prompt_needs_stdin(final_prompt):
            args.append(self._sanitize_prompt(final_prompt))
        return args

    def stdin_payload(
        self,
        prompt: str,
        resume: ResumeToken | None,
        *,
        state: PiStreamState,
    ) -> bytes | None:
        final_prompt = self._final_prompt(prompt)
        if not self._prompt_needs_stdin(final_prompt):
            return None
        return final_prompt.encode()

    def env(self, *, state: PiStreamState) -> dict[str, str] | None:
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("CI", "1")
        return env

    def new_state(self, prompt: str, resume: ResumeToken | None) -> PiStreamState:
        if resume is None:
            session_path = self._new_session_path()
            token = ResumeToken(engine=ENGINE, value=session_path)
            return PiStreamState(
                resume=token,
                allow_id_promotion=True,
            )
        return PiStreamState(resume=resume)

    def translate(
        self,
        data: pi_schema.PiEvent,
        *,
        state: PiStreamState,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
    ) -> list[TakopiEvent]:
        if isinstance(data, pi_schema.PiUnknownEvent):
            self.get_logger().debug(
                "pi.stream.unknown_type",
                tag=self.tag(),
                type_name=data.type_name,
            )
            return []
        meta: dict[str, Any] = {"cwd": os.getcwd()}
        if self.model:
            meta["model"] = self.model
        if self.provider:
            meta["provider"] = self.provider
        return translate_pi_event(
            data,
            title=self.session_title,
            meta=meta or None,
            state=state,
        )

    def decode_jsonl(
        self,
        *,
        line: bytes,
    ) -> pi_schema.PiEvent:
        return pi_schema.decode_event(line)

    def decode_error_events(
        self,
        *,
        raw: str,
        line: str,
        error: Exception,
        state: PiStreamState,
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

    def process_error_events(
        self,
        rc: int,
        *,
        resume: ResumeToken | None,
        found_session: ResumeToken | None,
        state: PiStreamState,
    ) -> list[TakopiEvent]:
        message = f"pi failed (rc={rc})."
        resume_for_completed = found_session or resume or state.resume
        return [
            self.note_event(message, state=state),
            CompletedEvent(
                engine=ENGINE,
                ok=False,
                answer=state.last_assistant_text or "",
                resume=resume_for_completed,
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
        message = "pi finished without an agent_end event"
        return [
            CompletedEvent(
                engine=ENGINE,
                ok=False,
                answer=state.last_assistant_text or "",
                resume=resume_for_completed,
                error=message,
                usage=state.last_usage,
            )
        ]

    def _new_session_path(self) -> str:
        cwd = get_run_base_dir() or Path.cwd()
        session_dir = _default_session_dir(cwd)
        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat()
        safe_timestamp = timestamp.replace(":", "-").replace(".", "-")
        token = uuid4().hex
        filename = f"{safe_timestamp}_{token}.jsonl"
        return str(session_dir / filename)

    def _sanitize_prompt(self, prompt: str) -> str:
        if prompt.startswith("-"):
            return f" {prompt}"
        return prompt

    def _quote_token(self, token: str) -> str:
        if not token:
            return token
        needs_quotes = any(ch.isspace() for ch in token)
        if not needs_quotes and '"' not in token:
            return token
        escaped = token.replace('"', '\\"')
        return f'"{escaped}"'


def _default_session_dir(cwd: PurePath) -> Path:
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR")
    base = Path(agent_dir).expanduser() if agent_dir else Path.home() / ".pi" / "agent"
    cwd_str = str(cwd).lstrip("/\\")
    safe_path_part = cwd_str.translate(str.maketrans({"/": "-", "\\": "-", ":": "-"}))
    safe_path = f"--{safe_path_part}--"
    return base / "sessions" / safe_path


_PLAN_MODE_EXTENSION_PACKAGE = "@narumitw/pi-plan-mode"


def detect_plan_mode_extension(root: Path | None = None) -> bool:
    """True when the ``@narumitw/pi-plan-mode`` extension is installed.

    Checks ``<root>/@narumitw/pi-plan-mode`` (directory existence). The
    default root is the conventional pi extension install path
    ``~/.pi/agent/npm/node_modules``. Injectable ``root`` for tests; no
    config key because the path is a pi-ecosystem convention.
    """
    if root is None:
        agent_dir = os.environ.get("PI_CODING_AGENT_DIR")
        base = (
            Path(agent_dir).expanduser() if agent_dir else Path.home() / ".pi" / "agent"
        )
        root = base / "npm" / "node_modules"
    return (root / _PLAN_MODE_EXTENSION_PACKAGE).is_dir()


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
            f"Invalid `pi.extra_args` in {config_path}; expected a list of strings."
        )

    model = config.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError(f"Invalid `pi.model` in {config_path}; expected a string.")

    provider = config.get("provider")
    if provider is not None and not isinstance(provider, str):
        raise ConfigError(f"Invalid `pi.provider` in {config_path}; expected a string.")

    return PiRunner(
        extra_args=extra_args,
        model=model,
        provider=provider,
        plan_mode_extension=detect_plan_mode_extension(),
    )


BACKEND = EngineBackend(
    id="pi",
    build_runner=build_runner,
    cli_cmd="pi",
    install_cmd="npm install -g @mariozechner/pi-coding-agent",
)
