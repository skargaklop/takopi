# Compact Runner API and ACP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/compact [instructions]` to Takopi across `codex`, `claude`, `opencode`, `pi`, `omp`, `grok`, and `agy`, while preserving runner event order, resume-token reuse, and per-session serialization. Long-prompt Telegram batching is already implemented in the separate `docs/plans/2026-08-01-telegram-multi-message-input.md` plan and is no longer part of this plan's remaining scope.

**Architecture:** Add a core compact capability model in `src/takopi/compact.py`, expose optional `compact_support()` and `compact(...)` runner methods, and route the Telegram `/compact` command through the same command/backend shape Takopi exposes via `takopi.api`. Slash-capable runners delegate to `run("/compact ...", resume)`, OpenCode uses its documented native HTTP compact endpoint, ACP runners use a minimal JSON-RPC stdio client only after the agent advertises `compact`, and `agy` is explicitly handoff-only rather than true compaction. Telegram multi-message prompt assembly already lives in the separate batching plan, so this document should not reintroduce that work.

**Tech Stack:** Python 3.14, anyio, msgspec, httpx, pytest, pytest-cov, ruff, Takopi `CommandContext`/`CommandResult`, Takopi `ThreadScheduler`, ACP JSON-RPC over stdio.

**ASCII implementation sketch:**

```text
User sends /compact [instructions]
        |
        v
Telegram route_message()
        |
        v
Telegram command parser -> built-in CommandBackend-compatible CompactCommand
        |
        v
Resolve existing ResumeToken only
  reply active run > reply footer > topic session > chat session > explicit resume
        |
        v
runner = runtime.resolve_runner(resume_token=token)
support = runner.compact_support()
        |
        +-- none ----------> user-visible unsupported response
        |
        +-- slash_prompt ---> runner.run("/compact [instructions]", token)
        |
        +-- native_api ----> OpenCode POST /api/session/{id}/compact + wait/events
        |
        +-- acp -----------> ACP initialize/resume + require advertised compact + prompt
        |
        +-- handoff_only --> handoff summary prompt, labelled as handoff only
        |
        v
Existing per-ResumeToken queue/session lock
        |
        v
StartedEvent -> 0..N ActionEvent -> CompletedEvent(last)
completed.resume == started.resume
```

**Scope update:** long-prompt batching is already shipped and tested in `docs/plans/2026-08-01-telegram-multi-message-input.md`. Keep this document focused on compact runner support and the cleanup items listed below.

## Cleanup Candidates To Review

These look like local scratch or temporary artifacts and should be removed only after verifying any references first:

- `scripts/_scan_mojibake.py`
- `docs/plans/2026-08-01-cancel-scope-shutdown-fix.md`

Keep generated caches in place:

- `.pytest_cache/`
- `.pytest-tmp-codex/`
- `.ruff_cache/`
- `.uv-cache/`

---

## Verified Inputs

### Local Takopi Shape

The local checkout is Python 3.14+ and version `0.26.0` in [pyproject.toml](D:/Projects/takopi/pyproject.toml). Production engines are registered under `takopi.engine_backends`:

```toml
codex = "takopi.runners.codex:BACKEND"
claude = "takopi.runners.claude:BACKEND"
opencode = "takopi.runners.opencode:BACKEND"
pi = "takopi.runners.pi:BACKEND"
omp = "takopi.runners.omp:BACKEND"
grok = "takopi.runners.grok:BACKEND"
agy = "takopi.runners.agy:BACKEND"
```

The current runner protocol in [src/takopi/runner.py](D:/Projects/takopi/src/takopi/runner.py) only has:

```python
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
```

The command plugin API is exported via [src/takopi/api.py](D:/Projects/takopi/src/takopi/api.py) and uses `CommandContext`, `CommandResult`, and `CommandExecutor` from [src/takopi/commands.py](D:/Projects/takopi/src/takopi/commands.py).

The runner contract is already documented in [docs/reference/specification.md](D:/Projects/takopi/docs/reference/specification.md): exactly one `StartedEvent`, exactly one final `CompletedEvent`, and `CompletedEvent.resume == StartedEvent.resume`.

### External CLI / Protocol Evidence

- Claude Code documents `/compact` as true conversation-history compaction and says it needs an existing conversation.
- Codex CLI docs list `/compact` as summarizing visible chat to free tokens. Local Codex app-server support still needs a concrete method-level test; do not assume ACP.
- Pi docs list `/compact [prompt]` as manual context compaction with optional custom instructions.
- OpenCode V2 docs say the CLI has no separate `compact` subcommand, but the server API supports `POST /api/session/:sessionID/compact`; manual compaction runs at a safe drain boundary and coalesces repeated pending requests.
- ACP v1 defines `session/prompt`, `session/load`, `session/resume`, `session/update`, and `available_commands_update`; available commands have a `name`. Takopi must not send `/compact` over ACP unless the active ACP agent advertises a command named `compact`.
- Grok Build docs confirm ACP support via `grok agent stdio` / `npx @xai-official/grok... agent stdio`.
- OMP docs confirm `omp acp` and describe ACP over JSON-RPC.

### Telegram Multi-Message Prompt Surface

Current Telegram routing concentrates prompt handling in [src/takopi/telegram/loop.py](D:/Projects/takopi/src/takopi/telegram/loop.py):

- `route_message()` classifies the update, handles cancel/commands/media, then builds `_PendingPrompt` and calls `ForwardCoalescer.schedule()`.
- `_parse_slash_command()` in [src/takopi/telegram/commands/parse.py](D:/Projects/takopi/src/takopi/telegram/commands/parse.py) already keeps multiline bodies inside one Telegram message, but it does not combine separate messages.
- `ForwardCoalescer` already debounces by `(chat_id, thread_id, sender_id)` and can append immediately-following forwarded messages to a prompt.
- A subsequent ordinary prompt currently replaces the pending prompt instead of merging with it.
- `_dispatch_pending_prompt()` resolves directives from `pending.text`, then appends forwarded text and sends one prompt to the normal dispatch path.
- `MediaGroupBuffer` is separate and should remain separate; media albums are keyed by Telegram `media_group_id`.
- Incoming message types expose no native Telegram "this message is a continuation of the previous oversized message" marker. The product rule must be explicit and configurable.

Recommended product rule:

```text
When transports.telegram.prompt_batch_debounce_s > 0:
  collect consecutive batchable text messages from the same
  chat + topic/thread + sender + reply target
  until a quiet window expires or a configured limit is reached.
  Then dispatch one assembled prompt through the existing prompt path.

When prompt_batch_debounce_s == 0:
  preserve current behavior.
```

Batchable messages:

- plain prompt text;
- engine/project directive prompt starts such as `/codex ...`;
- dual-mode agent prompt starts such as `/plan <prompt>` and `/goal <condition>`;
- `/compact [instructions]`, so long compact instructions can span multiple Telegram messages.

Non-batchable messages:

- `/cancel`;
- state-changing/control commands such as `/new`, `/ctx`, `/agent`, `/model`, `/reasoning`, `/trigger`, `/queue`, `/file`, `/topic`;
- document/media/voice updates;
- forwarded messages, which already belong to `ForwardCoalescer`;
- messages from a different sender, chat, topic/thread, or reply target.

This feature must not combine unrelated quick messages by default. Keep it opt-in with `prompt_batch_debounce_s = 0.0` unless product owners explicitly choose a nonzero default later.

---

## Hard Contracts

Keep these invariant in tests and implementation:

```text
Runner emits:
1x StartedEvent -> 0..N ActionEvent -> 1x CompletedEvent(last)

completed.resume == started.resume

Per-ResumeToken lock:
never run concurrently on the same session key f"{engine}:{token}"

/compact:
must reuse an existing ResumeToken
must never start a new session
must never infer ACP command support without advertisement

Multi-message prompt batching:
must be opt-in by config
must preserve message order
must not batch control commands, media uploads, voice transcription, or forwarded-only messages
must dispatch exactly one prompt after assembly
```

Additional semantic constraints:

- `agy` support is `handoff_only`, `true_compaction=False`. UI, docs, event titles, and tests must say "handoff summary", not "compaction".
- Instructions passed to a runner that does not accept instructions must produce a user-visible warning and then drop the instructions.
- OpenCode instructions are unsupported in v1 because the documented compact endpoint accepts a compact request, not a free-form prompt.
- ACP compact must be capability-gated by `available_commands_update.availableCommands[].name == "compact"`.
- If a runner cannot compact an existing session, return unsupported; do not create a new session or fork.

---

## Capability Matrix

| Engine | Mode | Accepts instructions | True compaction | Implementation path |
|---|---|---:|---:|---|
| `claude` | `slash_prompt` | yes | yes | `run("/compact [instructions]", resume)` |
| `pi` | `slash_prompt` | yes | yes | `run("/compact [instructions]", resume)` |
| `codex` | `slash_prompt` | no | yes | `run("/compact", resume)`; warn and drop instructions |
| `opencode` | `native_api` | no | yes | HTTP `POST /api/session/{id}/compact`, then wait/follow events |
| `grok` | `acp` | yes | yes if advertised | `grok agent stdio`, load/resume, require advertised `compact`, `session/prompt` |
| `omp` | `acp` | yes | yes if advertised | `omp acp`, load/resume, require advertised `compact`, `session/prompt` |
| `agy` | `handoff_only` | yes | no | `run(HANDOFF_SUMMARY_PROMPT, resume)` with handoff labels |

`mode="none"` remains the default for third-party runners and old plugins.

---

## Task 1: Core Compact Model

**Files:**

- Create: `src/takopi/compact.py`
- Modify: `src/takopi/api.py`
- Test: `tests/test_compact_core.py`

**Step 1: Write failing tests**

```python
from takopi.compact import (
    COMPACT_NONE,
    CompactSupport,
    compact_prompt,
    handoff_prompt,
    warn_if_dropping_instructions,
)


def test_compact_prompt_formats_optional_instructions() -> None:
    assert compact_prompt(None) == "/compact"
    assert compact_prompt("") == "/compact"
    assert compact_prompt("keep failing tests") == "/compact keep failing tests"


def test_default_none_support() -> None:
    assert COMPACT_NONE == CompactSupport(
        mode="none",
        accepts_instructions=False,
        true_compaction=False,
        note="compaction is not supported by this runner",
    )


def test_handoff_prompt_is_not_labelled_compaction() -> None:
    text = handoff_prompt("preserve blockers")
    assert "handoff summary" in text.lower()
    assert "User focus:\npreserve blockers" in text
    assert "real compaction" not in text.lower()


def test_warning_when_instructions_are_dropped() -> None:
    msg = warn_if_dropping_instructions("codex", "keep API contracts")
    assert "codex" in msg
    assert "instructions are not supported" in msg
```

**Step 2: Implement `src/takopi/compact.py`**

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from .model import EngineId, ResumeToken, TakopiEvent

CompactMode = Literal["slash_prompt", "native_api", "acp", "handoff_only", "none"]


@dataclass(frozen=True, slots=True)
class CompactSupport:
    mode: CompactMode
    accepts_instructions: bool
    true_compaction: bool
    note: str | None = None


COMPACT_NONE = CompactSupport(
    mode="none",
    accepts_instructions=False,
    true_compaction=False,
    note="compaction is not supported by this runner",
)


class CompactUnsupportedError(RuntimeError):
    pass


@runtime_checkable
class CompactRunner(Protocol):
    def compact_support(self) -> CompactSupport: ...

    def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]: ...


def normalize_instructions(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def compact_prompt(instructions: str | None) -> str:
    text = normalize_instructions(instructions)
    return "/compact" if text is None else f"/compact {text}"


def handoff_prompt(instructions: str | None) -> str:
    base = """Create a handoff summary for continuing this session.

This is not real context compaction. Do not claim that the session was compacted.

Preserve:
- current user goal and latest instruction
- active project and relevant paths
- decisions already made
- files changed or inspected
- commands run and verification results
- open blockers, risks, and next steps

Write a concise handoff summary for the next agent turn."""
    text = normalize_instructions(instructions)
    return base if text is None else f"{base}\n\nUser focus:\n{text}"


def warn_if_dropping_instructions(engine: EngineId, instructions: str | None) -> str | None:
    text = normalize_instructions(instructions)
    if text is None:
        return None
    return (
        f"{engine} compact instructions are not supported yet; "
        "running compact without the supplied instructions."
    )


def get_compact_support(runner: object) -> CompactSupport:
    method = getattr(runner, "compact_support", None)
    if method is None:
        return COMPACT_NONE
    result = method()
    if not isinstance(result, CompactSupport):
        raise TypeError("compact_support() must return CompactSupport")
    return result
```

**Step 3: Export from `takopi.api`**

Add `CompactSupport`, `CompactMode`, `CompactRunner`, `CompactUnsupportedError`, `compact_prompt`, and `get_compact_support` to [src/takopi/api.py](D:/Projects/takopi/src/takopi/api.py).

**Step 4: Run**

```powershell
Set-Location -LiteralPath D:\Projects\takopi
$env:PYTHONUTF8 = '1'
python -m pytest tests/test_compact_core.py -q
```

Expected before implementation: import failures. Expected after implementation: pass.

---

## Task 2: Runner Protocol Defaults

**Files:**

- Modify: `src/takopi/runner.py`
- Modify: `src/takopi/runners/mock.py`
- Test: `tests/test_runner_contract.py`

**Step 1: Write failing tests**

```python
import pytest

from takopi.compact import COMPACT_NONE, CompactUnsupportedError
from takopi.model import ResumeToken
from takopi.runners.mock import ScriptRunner


def test_runner_default_compact_support_is_none() -> None:
    runner = ScriptRunner([], engine="mock", resume_value="sid")
    assert runner.compact_support() == COMPACT_NONE


@pytest.mark.anyio
async def test_runner_default_compact_raises() -> None:
    runner = ScriptRunner([], engine="mock", resume_value="sid")
    with pytest.raises(CompactUnsupportedError):
        async for _ in runner.compact(ResumeToken(engine="mock", value="sid")):
            pass
```

**Step 2: Add default methods**

Add to `BaseRunner` and `MockRunner`. Keep command code using `get_compact_support(runner)` so older third-party runner plugins without these methods still behave as `mode="none"`.

```python
from .compact import COMPACT_NONE, CompactSupport, CompactUnsupportedError


class BaseRunner(SessionLockMixin):
    ...
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
```

Update the `Runner` protocol with optional compact methods:

```python
class Runner(Protocol):
    ...
    def compact_support(self) -> CompactSupport: ...

    def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]: ...
```

Compatibility note: because `get_compact_support()` uses `getattr`, old plugins still work even if their class does not physically define these methods.

**Step 3: Run**

```powershell
python -m pytest tests/test_runner_contract.py::test_runner_default_compact_support_is_none tests/test_runner_contract.py::test_runner_default_compact_raises -q
```

---

## Task 3: Slash Compact Mixin

**Files:**

- Create: `src/takopi/runners/_compact_mixin.py`
- Modify: `src/takopi/runners/claude.py`
- Modify: `src/takopi/runners/pi.py`
- Modify: `src/takopi/runners/codex.py`
- Test: `tests/test_compact_slash_mixin.py`
- Test: runner-specific tests for Claude, Pi, Codex

**Step 1: Write failing tests**

```python
import pytest

from takopi.compact import CompactSupport
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
from takopi.runners._compact_mixin import SlashCompactMixin
from takopi.runners.mock import Return, ScriptRunner


class SlashScriptRunner(SlashCompactMixin, ScriptRunner):
    compact_accepts_instructions = True


@pytest.mark.anyio
async def test_slash_compact_delegates_to_run_with_instructions() -> None:
    runner = SlashScriptRunner([Return(answer="done")], engine="claude")
    resume = ResumeToken(engine="claude", value="sid")
    events = [evt async for evt in runner.compact(resume, "keep tests")]

    assert runner.calls[-1] == ("/compact keep tests", resume)
    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].resume == events[0].resume


class NoInstructionSlashRunner(SlashCompactMixin, ScriptRunner):
    compact_accepts_instructions = False


@pytest.mark.anyio
async def test_slash_compact_drops_instructions_when_unsupported() -> None:
    runner = NoInstructionSlashRunner([Return(answer="done")], engine="codex")
    resume = ResumeToken(engine="codex", value="sid")
    _ = [evt async for evt in runner.compact(resume, "drop this")]
    assert runner.calls[-1] == ("/compact", resume)
```

**Step 2: Implement mixin**

```python
from __future__ import annotations

from collections.abc import AsyncIterator

from ..compact import CompactSupport, compact_prompt
from ..model import ResumeToken, TakopiEvent


class SlashCompactMixin:
    compact_accepts_instructions = True
    compact_true_compaction = True

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="slash_prompt",
            accepts_instructions=self.compact_accepts_instructions,
            true_compaction=self.compact_true_compaction,
        )

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        if instructions and not self.compact_accepts_instructions:
            instructions = None
        async for event in self.run(compact_prompt(instructions), resume):
            yield event
```

**Step 3: Wire runners**

Use leftmost mixin inheritance so mixin methods win:

```python
class ClaudeRunner(SlashCompactMixin, ResumeTokenMixin, JsonlSubprocessRunner):
    compact_accepts_instructions = True
```

```python
class PiRunner(SlashCompactMixin, ResumeTokenMixin, JsonlSubprocessRunner):
    compact_accepts_instructions = True
```

```python
class CodexRunner(SlashCompactMixin, ResumeTokenMixin, JsonlSubprocessRunner):
    compact_accepts_instructions = False
```

For `AppServerCodexRunner`, either inherit `SlashCompactMixin` with `compact_accepts_instructions=False` or implement a Codex-specific compact path if `thread/compact/start` is verified from the local generated app-server schema. Do not use ACP for Codex compact unless Codex ACP support is explicitly introduced and advertises the command.

**Step 4: Run**

```powershell
python -m pytest tests/test_compact_slash_mixin.py tests/test_claude_runner.py tests/test_pi_runner.py tests/test_codex_runner_helpers.py -q
```

---

## Task 4: OpenCode Native API Compact

**Files:**

- Modify: `src/takopi/runners/opencode.py`
- Create: `tests/test_opencode_compact.py`
- Update: `docs/reference/config.md`

**Step 1: Write failing tests with fake HTTP transport**

Use `httpx.MockTransport` or a tiny test server. The runner should not require the real OpenCode server in unit tests.

```python
import pytest

from takopi.compact import CompactSupport
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
from takopi.runners.opencode import OpenCodeRunner


def test_opencode_compact_support_is_native_api() -> None:
    runner = OpenCodeRunner(opencode_cmd="opencode")
    assert runner.compact_support() == CompactSupport(
        mode="native_api",
        accepts_instructions=False,
        true_compaction=True,
        note="OpenCode compact uses the server API, not a CLI subcommand",
    )


@pytest.mark.anyio
async def test_opencode_compact_posts_to_session_endpoint(mock_opencode_api) -> None:
    runner = OpenCodeRunner(
        opencode_cmd="opencode",
        compact_api_base_url=mock_opencode_api.url,
        compact_http_client=mock_opencode_api.client,
    )
    resume = ResumeToken(engine="opencode", value="ses_abc")

    events = [evt async for evt in runner.compact(resume, None)]

    assert mock_opencode_api.requests == [
        ("POST", "/api/session/ses_abc/compact"),
        ("POST", "/api/session/ses_abc/wait"),
    ]
    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].resume == events[0].resume == resume
```

**Step 2: Add config fields**

Add optional config in `build_runner`:

```toml
[opencode]
compact_api_base_url = "http://127.0.0.1:4096"
compact_wait = true
```

Implementation should also accept `OPENCODE_API_URL` as an override. Do not hide a hardcoded remote URL in code.

**Step 3: Implement event wrapper**

```python
async def compact(self, resume: ResumeToken, instructions: str | None = None):
    if resume.engine != ENGINE:
        raise RuntimeError(...)
    if instructions:
        yield _warning_event("opencode.compact.instructions", ...)

    factory = EventFactory(ENGINE)
    yield factory.started(
        resume,
        title="OpenCode compact",
        meta={"compact": {"mode": "native_api", "true_compaction": True}},
    )

    await self._client.post(f"/api/session/{resume.value}/compact", json={})
    if self.compact_wait:
        await self._client.post(f"/api/session/{resume.value}/wait", json={})

    yield factory.completed_ok(
        answer="OpenCode compaction requested.",
        resume=resume,
    )
```

If the HTTP call fails, still emit `StartedEvent` first, then a final `CompletedEvent(ok=False, resume=resume, error=...)`.

**Step 4: Run**

```powershell
python -m pytest tests/test_opencode_compact.py tests/test_opencode_runner.py -q
```

---

## Task 5: Minimal ACP Client

**Files:**

- Create: `src/takopi/runners/_acp.py`
- Create: `tests/test_acp_client.py`

**Step 1: Write fake ACP server tests**

The fake server should be a subprocess-like object or in-memory stream pair that records JSON-RPC messages and emits responses/notifications.

Tests:

- initialize sends client info/capabilities;
- load/resume uses existing `resume.value`;
- `available_commands_update` with `name="compact"` enables compact;
- missing `compact` raises before any `/compact` `session/prompt`;
- prompt payload is text content and includes `/compact [instructions]`;
- session updates map to Takopi action/completed events without breaking event invariants.

Example assertion:

```python
@pytest.mark.anyio
async def test_acp_compact_requires_advertised_command(fake_acp) -> None:
    client = AcpClient(command="fake", args=[], transport=fake_acp.transport)
    await client.initialize()
    await client.resume_or_load("sid")
    fake_acp.emit_available_commands([])

    with pytest.raises(AcpCommandUnavailableError):
        await client.require_command("compact")

    assert not any(
        msg["method"] == "session/prompt"
        for msg in fake_acp.requests
    )
```

**Step 2: Implement client**

Core API:

```python
class AcpCommandUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class AcpClient:
    command: str
    args: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None

    async def initialize(self) -> None: ...
    async def resume_or_load(self, session_id: str) -> None: ...
    async def wait_for_available_commands(self) -> set[str]: ...
    async def require_command(self, name: str) -> None: ...
    async def prompt(self, session_id: str, text: str) -> AsyncIterator[AcpEvent]: ...
```

Protocol flow:

```python
await client.request("initialize", {
    "protocolVersion": 1,
    "clientInfo": {"name": "takopi", "version": TAKOPI_VERSION},
    "clientCapabilities": {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
    },
})

if initialize_result.agentCapabilities.loadSession:
    await client.request("session/load", {"sessionId": resume.value})
elif initialize_result.agentCapabilities.sessionCapabilities.resume is not None:
    await client.request("session/resume", {"sessionId": resume.value})
else:
    raise AcpCommandUnavailableError("ACP agent cannot load/resume sessions")

commands = await client.wait_for_available_commands()
if "compact" not in commands:
    raise AcpCommandUnavailableError("ACP agent did not advertise compact")

await client.request("session/prompt", {
    "sessionId": resume.value,
    "prompt": [{"type": "text", "text": compact_prompt(instructions)}],
})
```

Do not use `session/new` in any compact path.

**Step 3: Map ACP updates**

Keep v1 mapping small:

- `agent_message_chunk` accumulates answer text;
- `agent_thought_chunk`, `tool_call`, `tool_call_update`, `plan` become `ActionEvent(kind="note"|"tool"|"turn")`;
- prompt response stop reason maps to `CompletedEvent(ok=...)`;
- missing final response maps to `CompletedEvent(ok=False, resume=resume)`.

**Step 4: Run**

```powershell
python -m pytest tests/test_acp_client.py -q
```

---

## Task 6: ACP Compact Mixins for Grok and OMP

**Files:**

- Modify: `src/takopi/runners/grok.py`
- Modify: `src/takopi/runners/omp.py`
- Test: `tests/test_grok_compact_acp.py`
- Test: `tests/test_omp_compact_acp.py`

**Step 1: Add mixin**

Create in `src/takopi/runners/_acp.py` or separate `_acp_compact_mixin.py`:

```python
class AcpCompactMixin:
    acp_command: str
    acp_args: list[str]
    compact_accepts_instructions = True

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="acp",
            accepts_instructions=self.compact_accepts_instructions,
            true_compaction=True,
            note="ACP compact requires advertised compact command",
        )

    async def compact(self, resume: ResumeToken, instructions: str | None = None):
        if resume.engine != self.engine:
            raise RuntimeError(...)
        factory = EventFactory(self.engine)
        yield factory.started(
            resume,
            title=f"{self.engine} compact",
            meta={"compact": {"mode": "acp", "true_compaction": True}},
        )
        try:
            async with self.create_acp_client() as client:
                await client.initialize()
                await client.resume_or_load(resume.value)
                await client.require_command("compact")
                async for update in client.prompt(resume.value, compact_prompt(instructions)):
                    for event in translate_acp_update(update, engine=self.engine, resume=resume):
                        yield event
            yield factory.completed_ok(answer=f"{self.engine} compaction completed.", resume=resume)
        except Exception as exc:
            yield factory.completed_error(error=str(exc), resume=resume)
```

**Step 2: Grok wiring**

Use documented ACP command:

```python
class GrokRunner(AcpCompactMixin, ResumeTokenMixin, JsonlSubprocessRunner):
    def create_acp_client(self) -> AcpClient:
        return AcpClient(
            command=self.grok_cmd,
            args=["agent", "stdio"],
            cwd=os.getcwd(),
        )
```

**Step 3: OMP wiring**

Use documented ACP command:

```python
class OmpRunner(AcpCompactMixin, PiRunner):
    def create_acp_client(self) -> AcpClient:
        return AcpClient(command=self.command(), args=["acp"], cwd=os.getcwd())
```

**Step 4: Tests**

For both engines:

- support mode is `acp`;
- when fake server advertises compact, it sends `session/prompt` with `/compact ...`;
- when fake server omits compact, it emits final `CompletedEvent(ok=False)` and never sends prompt;
- event sequence satisfies started/completed invariant.

**Step 5: Run**

```powershell
python -m pytest tests/test_grok_compact_acp.py tests/test_omp_compact_acp.py -q
```

---

## Task 7: Agy Handoff-Only Compact

**Files:**

- Modify: `src/takopi/runners/agy.py`
- Test: `tests/test_agy_runner.py`

**Step 1: Write failing tests**

```python
import pytest

from takopi.compact import CompactSupport
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
from takopi.runners.agy import AgyRunner


def test_agy_compact_support_is_handoff_only() -> None:
    runner = AgyRunner(agy_cmd="agy")
    assert runner.compact_support() == CompactSupport(
        mode="handoff_only",
        accepts_instructions=True,
        true_compaction=False,
        note="Antigravity has no verified true compact command in Takopi",
    )


@pytest.mark.anyio
async def test_agy_compact_uses_handoff_prompt(monkeypatch) -> None:
    runner = FakeAgyRunner()
    resume = ResumeToken(engine="agy", value="conv-1")

    events = [evt async for evt in runner.compact(resume, "preserve blockers")]

    assert "handoff summary" in runner.calls[-1][0].lower()
    assert "preserve blockers" in runner.calls[-1][0]
    assert isinstance(events[0], StartedEvent)
    assert isinstance(events[-1], CompletedEvent)
    assert events[-1].resume == events[0].resume
    assert events[0].meta["compact"]["true_compaction"] is False
```

**Step 2: Implement**

```python
def compact_support(self) -> CompactSupport:
    return CompactSupport(
        mode="handoff_only",
        accepts_instructions=True,
        true_compaction=False,
        note="Antigravity handoff summary only; not real compaction",
    )


async def compact(self, resume: ResumeToken, instructions: str | None = None):
    prompt = handoff_prompt(instructions)
    async for event in self.run(prompt, resume):
        yield _mark_agy_handoff(event)
```

`_mark_agy_handoff()` should add metadata on `StartedEvent` and avoid text like "compacted".

**Step 3: Run**

```powershell
python -m pytest tests/test_agy_runner.py -q
```

---

## Task 8: Command Registration and Dispatch

**Files:**

- Create: `src/takopi/commands/compact.py`
- Modify: `src/takopi/commands.py`
- Modify: `src/takopi/api.py`
- Modify: `src/takopi/telegram/commands/menu.py`
- Modify: `src/takopi/telegram/commands/meta_args.py`
- Modify: `src/takopi/telegram/loop.py`
- Modify: `src/takopi/telegram/commands/executor.py`
- Test: `tests/test_telegram_compact_command.py`
- Test: `tests/test_command_registry.py`

**Design choice**

Implement `CompactCommand` with the same `CommandBackend` shape as command plugins, but register it as a core built-in command, not as a third-party entry point. This satisfies the `takopi.api`/`CommandContext` pattern while preserving access to internal Telegram session state.

Do not let plugin commands override `/compact`.

**Step 1: Parser tests**

```python
from takopi.commands.compact import parse_compact_instructions


def test_parse_compact_instructions() -> None:
    assert parse_compact_instructions("/compact") is None
    assert parse_compact_instructions("/compact   ") is None
    assert parse_compact_instructions("/compact foo") == "foo"
    assert parse_compact_instructions("foo") == "foo"
```

`parse_slash_command()` already provides `args_text`, so command handling should use `args_text.strip() or None`.

**Step 2: Add compact execution service**

Extend `_TelegramCommandExecutor` with a compact-specific method rather than making plugin commands know Telegram stores:

```python
class CommandExecutor(Protocol):
    ...
    async def compact_current(
        self,
        instructions: str | None = None,
    ) -> CommandResult: ...
```

In `_TelegramCommandExecutor`, inject a callable:

```python
compact_current: Callable[[str | None], Awaitable[CommandResult]] | None = None
```

If unavailable, return `CommandResult(text="compact is unavailable for this transport.")`.

**Step 3: Add built-in command backend**

```python
from takopi.api import CommandContext, CommandResult


class CompactCommand:
    id = "compact"
    description = "compact current session"

    async def handle(self, ctx: CommandContext) -> CommandResult | None:
        instructions = ctx.args_text.strip() or None
        return await ctx.executor.compact_current(instructions)


BACKEND = CompactCommand()
```

**Step 4: Resolve existing resume only**

In `telegram/loop.py`, build a `compact_current()` closure that can access:

- `msg`;
- `reply_id`;
- `reply_ref`;
- `topic_key`;
- `chat_session_key`;
- `state.running_tasks`;
- `state.topic_store`;
- `state.chat_session_store`;
- `scheduler`;
- `cfg.runtime`.

Resolution order should match normal prompts but must be token-only:

```python
async def resolve_resume_token_only(...) -> ResumeToken | None:
    if resolved.user_resume is not None:
        return resolved.user_resume
    if resolved.bare_resume_id is not None:
        return ResumeToken(engine=engine_for_session, value=resolved.bare_resume_id)
    if reply_id is not None:
        task = state.running_tasks.get(MessageRef(...))
        if task and task.resume:
            return task.resume
    if resolved.reply_resume is not None:
        return resolved.reply_resume
    stored = await topic_store.get_session_resume(...)
    if stored is not None:
        return stored
    return await chat_session_store.get_session_resume(...)
```

If no token:

```python
return CommandResult(
    text=(
        "no active session to compact.\n"
        "reply to a Takopi progress/final message, or send a normal prompt first."
    )
)
```

Never call `runner.compact(None, ...)`.

**Step 5: Enqueue compact on the same lock**

The cleanest implementation is to extend scheduler jobs:

```python
@dataclass(frozen=True, slots=True)
class ThreadJob:
    ...
    kind: Literal["prompt", "compact"] = "prompt"
    compact_instructions: str | None = None
```

Then in scheduler run job:

```python
if job.kind == "compact":
    await run_compact_job(job)
else:
    await run_prompt_job(job)
```

Do not send the compact call directly from the command handler.

**Step 6: Implement runner compact dispatch**

```python
async def run_compact_job(job: ThreadJob) -> None:
    entry = cfg.runtime.resolve_runner(
        resume_token=job.resume_token,
        engine_override=job.resume_token.engine,
    )
    runner = entry.runner
    support = get_compact_support(runner)

    if support.mode == "none":
        await send_final_error(...)
        return

    instructions = job.compact_instructions
    if instructions and not support.accepts_instructions:
        await send_warning_to_user(...)
        instructions = None

    async for event in runner.compact(job.resume_token, instructions):
        await handle_event(event)
```

This keeps the per-session `ThreadScheduler` queue as the outer lock and runner `SessionLockMixin` as the inner invariant.

**Step 7: setMyCommands canonical list**

Add `/compact` to [src/takopi/telegram/commands/menu.py](D:/Projects/takopi/src/takopi/telegram/commands/menu.py):

```python
("compact", "compact current session"),
```

Add to [src/takopi/telegram/commands/meta_args.py](D:/Projects/takopi/src/takopi/telegram/commands/meta_args.py) as pure meta so `/compact foo` never falls through as a normal prompt.

**Step 8: Tests**

Required integration tests:

- `/compact` without a stored/replied/active session sends error and no runner call.
- `/compact instructions` for Claude sends `/compact instructions`.
- `/compact instructions` for Codex warns and sends `/compact`.
- `/compact instructions` for OpenCode warns and calls native API.
- `/compact instructions` for `agy` marks handoff only.
- `/compact` reply to active progress message queues behind the active run.
- `/compact` never changes stored chat/topic session token.
- `build_bot_commands()` includes `compact`.

**Step 9: Run**

```powershell
python -m pytest tests/test_telegram_compact_command.py tests/test_command_registry.py tests/test_telegram_bridge.py -q
```

---

## Task 9: Event Invariant Tests For Every Compact Mode

**Files:**

- Create: `tests/test_compact_event_invariants.py`

**Step 1: Add shared assertion helper**

```python
from takopi.model import CompletedEvent, StartedEvent, TakopiEvent


def assert_compact_event_invariants(events: list[TakopiEvent]) -> None:
    started = [e for e in events if isinstance(e, StartedEvent)]
    completed = [e for e in events if isinstance(e, CompletedEvent)]
    assert len(started) == 1
    assert len(completed) == 1
    assert events[-1] is completed[0]
    assert completed[0].resume == started[0].resume
```

**Step 2: Parametrize all engines**

Use fake runners/clients for each mode:

```python
@pytest.mark.parametrize(
    "engine",
    ["claude", "pi", "codex", "opencode", "grok", "omp", "agy"],
)
async def test_compact_event_invariants_for_all_engines(engine: str) -> None:
    ...
    assert_compact_event_invariants(events)
```

**Step 3: Session lock test**

```python
@pytest.mark.anyio
async def test_compact_serializes_with_active_run_same_resume() -> None:
    # Arrange a running prompt on ResumeToken(engine="claude", value="sid")
    # Queue compact for same token.
    # Assert compact begins only after active run completes.
```

This test must prove both layers:

- `ThreadScheduler` queues same `ThreadKey`.
- Runner compact methods use existing `SessionLockMixin` or `run(...)` so direct runner calls cannot overlap.

**Step 4: Run**

```powershell
python -m pytest tests/test_compact_event_invariants.py -q
```

---

## Task 10: Docs

**Files:**

- Modify: `docs/reference/specification.md`
- Modify: `docs/reference/commands-and-directives.md`
- Modify: `docs/reference/plugin-api.md`
- Modify: `docs/reference/config.md`
- Create: `docs/how-to/compact.md`

**Specification additions**

Add to runner protocol section:

````markdown
### Runner compaction protocol

Runners MAY implement:

```python
def compact_support(self) -> CompactSupport: ...
async def compact(
    self,
    resume: ResumeToken,
    instructions: str | None = None,
) -> AsyncIterator[TakopiEvent]: ...
```

`compact()` MUST receive an existing `ResumeToken`. It MUST NOT create a new
session. If it emits `StartedEvent`, it MUST emit exactly one final
`CompletedEvent`, and `CompletedEvent.resume` MUST equal `StartedEvent.resume`.
````

**User docs**

Add command:

```markdown
| `/compact [instructions]` | Compact the active resumed session where the runner supports true compaction. `agy` produces a handoff summary only. |
```

Add matrix:

```markdown
| Engine | Compact |
|---|---|
| claude | true, `/compact [instructions]` |
| pi | true, `/compact [instructions]` |
| codex | true, `/compact`; instructions dropped with warning |
| opencode | true, server API; instructions dropped with warning |
| grok | true only when ACP advertises `compact` |
| omp | true only when ACP advertises `compact` |
| agy | handoff summary only, not real compaction |
```

**How-to**

`docs/how-to/compact.md` should include:

- how to use `/compact`;
- how instructions behave per runner;
- how to reply to a final/progress message to target a session;
- how to send long `/compact` instructions across several Telegram messages when prompt batching is enabled;
- unsupported/no-session errors;
- explicit warning that `/compact` never starts a new session;
- explicit warning that `agy` is handoff-only.

---

## Task 11: Multi-Message Prompt Batching

**Files:**

- Create: `src/takopi/telegram/prompt_batch.py`
- Modify: `src/takopi/settings.py`
- Modify: `src/takopi/telegram/bridge.py`
- Modify: `src/takopi/telegram/backend.py`
- Modify: `src/takopi/telegram/loop.py`
- Modify: `tests/telegram_fakes.py`
- Test: `tests/test_telegram_prompt_batch.py`
- Test: focused additions in `tests/test_telegram_bridge.py`
- Docs: `docs/reference/config.md`, `docs/reference/transports/telegram.md`, `docs/reference/commands-and-directives.md`, `docs/how-to/compact.md`

**Design**

Add a dedicated `PromptBatcher` for ordinary text prompt chunks. Do not fold this into `ForwardCoalescer`; forwarded-message attachment and long-prompt chunking have different product rules and different failure modes.

The batcher should sit in `route_message()` before batchable prompt/compact dispatch. It should receive fully built `TelegramMsgContext`, but it should not resolve directives itself beyond determining whether the first slash token is a control command that must bypass batching.

Recommended config:

```python
class TelegramTransportSettings(BaseModel):
    ...
    prompt_batch_debounce_s: float = Field(default=0.0, ge=0)
    prompt_batch_max_messages: StrictInt = Field(default=6, ge=2)
    prompt_batch_max_chars: StrictInt = Field(default=120_000, ge=4096)
    prompt_batch_separator: Literal["newline", "blank_line"] = "blank_line"
```

Wire through:

```python
@dataclass(frozen=True, slots=True)
class TelegramBridgeConfig:
    ...
    prompt_batch_debounce_s: float = 0.0
    prompt_batch_max_messages: int = 6
    prompt_batch_max_chars: int = 120_000
    prompt_batch_separator: Literal["newline", "blank_line"] = "blank_line"
```

Add to `TelegramLoopState`:

```python
prompt_batches: dict[PromptBatchKey, PromptBatchState]
prompt_batch_debounce_s: float
prompt_batch_max_messages: int
prompt_batch_max_chars: int
prompt_batch_separator: Literal["newline", "blank_line"]
```

**Step 1: Write unit tests for batch decisions**

Create `tests/test_telegram_prompt_batch.py`:

```python
from takopi.telegram.prompt_batch import (
    PromptBatchPart,
    PromptBatchSettings,
    should_batch_message,
    join_prompt_parts,
)


def test_join_prompt_parts_blank_line_separator() -> None:
    parts = [
        PromptBatchPart(message_id=1, text="/compact preserve decisions"),
        PromptBatchPart(message_id=2, text="and failing tests"),
    ]
    assert (
        join_prompt_parts(parts, separator="blank_line")
        == "/compact preserve decisions\n\nand failing tests"
    )


def test_join_prompt_parts_preserves_order_by_message_id() -> None:
    parts = [
        PromptBatchPart(message_id=3, text="third"),
        PromptBatchPart(message_id=1, text="first"),
        PromptBatchPart(message_id=2, text="second"),
    ]
    assert join_prompt_parts(parts, separator="newline") == "first\nsecond\nthird"


def test_control_commands_are_not_batchable() -> None:
    settings = PromptBatchSettings(enabled=True)
    assert should_batch_message("/compact keep this", settings=settings) is True
    assert should_batch_message("/codex do work", settings=settings) is True
    assert should_batch_message("/plan design", settings=settings) is True
    assert should_batch_message("/cancel", settings=settings) is False
    assert should_batch_message("/new", settings=settings) is False
    assert should_batch_message("/ctx", settings=settings) is False
    assert should_batch_message("/file put x.txt", settings=settings) is False
```

Expected before implementation: import failure.

**Step 2: Implement pure helper module**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .commands.parse import parse_slash_command

type PromptBatchSeparator = Literal["newline", "blank_line"]

CONTROL_COMMANDS = frozenset(
    {
        "cancel",
        "new",
        "ctx",
        "agent",
        "model",
        "reasoning",
        "trigger",
        "queue",
        "file",
        "topic",
    }
)


@dataclass(frozen=True, slots=True)
class PromptBatchSettings:
    enabled: bool
    max_messages: int = 6
    max_chars: int = 120_000
    separator: PromptBatchSeparator = "blank_line"


@dataclass(frozen=True, slots=True)
class PromptBatchKey:
    chat_id: int
    thread_id: int | None
    sender_id: int
    reply_to_message_id: int | None


@dataclass(frozen=True, slots=True)
class PromptBatchPart:
    message_id: int
    text: str


@dataclass(slots=True)
class PromptBatchState:
    first_msg: object
    parts: list[PromptBatchPart] = field(default_factory=list)
    cancel_scope: object | None = None


def should_batch_message(text: str, *, settings: PromptBatchSettings) -> bool:
    if not settings.enabled:
        return False
    if not text.strip():
        return False
    command_id, args_text = parse_slash_command(text)
    if command_id is None:
        return True
    if command_id in CONTROL_COMMANDS:
        return False
    if command_id == "compact":
        return True
    # Engine/project directives and dual-mode `/plan <prompt>` / `/goal <condition>`
    # are intentionally allowed; final directive resolution happens after joining.
    return bool(args_text.strip())


def join_prompt_parts(
    parts: list[PromptBatchPart],
    *,
    separator: PromptBatchSeparator,
) -> str:
    sep = "\n" if separator == "newline" else "\n\n"
    return sep.join(part.text for part in sorted(parts, key=lambda part: part.message_id))
```

Keep this module free of runner/runtime imports so it can be tested cheaply.

**Step 3: Add loop-side batcher**

In `src/takopi/telegram/loop.py`, add a `PromptBatcher` class near `ForwardCoalescer` or import it from `prompt_batch.py` if implementation stays small. The loop class owns async sleeps and dispatch callbacks:

```python
class PromptBatcher:
    def __init__(
        self,
        *,
        task_group: TaskGroup,
        debounce_s: float,
        sleep: Callable[[float], Awaitable[None]],
        dispatch: Callable[[_PendingPrompt], Awaitable[None]],
        pending: dict[PromptBatchKey, PromptBatchState],
        max_messages: int,
        max_chars: int,
        separator: PromptBatchSeparator,
    ) -> None: ...

    def cancel(self, key: PromptBatchKey) -> None: ...

    def schedule(self, pending: _PendingPrompt) -> bool:
        # Return True when consumed into a pending batch.
        # Return False when caller should continue normal immediate routing.
```

Schedule behavior:

```python
def schedule(self, pending: _PendingPrompt) -> bool:
    msg = pending.msg
    if msg.sender_id is None or self._debounce_s <= 0:
        return False
    text = pending.text
    if not should_batch_message(text, settings=self._settings):
        return False
    key = PromptBatchKey(
        chat_id=msg.chat_id,
        thread_id=msg.thread_id,
        sender_id=msg.sender_id,
        reply_to_message_id=msg.reply_to_message_id,
    )
    state = self._pending.get(key)
    if state is None:
        state = PromptBatchState(first_msg=msg)
        self._pending[key] = state
    state.parts.append(PromptBatchPart(message_id=msg.message_id, text=text))
    if len(state.parts) >= self._max_messages or total_chars(state.parts) >= self._max_chars:
        self._task_group.start_soon(self._flush_now, key, state)
    else:
        self._reschedule(key, state)
    return True
```

Flush behavior:

```python
async def _flush_now(self, key: PromptBatchKey, state: PromptBatchState) -> None:
    if self._pending.get(key) is not state:
        return
    self._pending.pop(key, None)
    first = state.first_msg
    text = join_prompt_parts(state.parts, separator=self._separator)
    pending = _PendingPrompt(
        msg=first,
        text=text,
        ambient_context=state.ambient_context,
        chat_project=state.chat_project,
        topic_key=state.topic_key,
        chat_session_key=state.chat_session_key,
        reply_ref=state.reply_ref,
        reply_id=state.reply_id,
        is_voice_transcribed=False,
        forwards=[],
    )
    await self._dispatch(pending)
```

Store the original `_PendingPrompt` metadata in `PromptBatchState` rather than only the raw `msg`; the first message determines context, reply target, and directive root. Later chunks are plain appended content.

**Step 4: Wire `route_message()`**

The insertion point is after context building, after immediate cancel handling, and before built-in/plugin/engine command dispatch for batchable text:

```python
if classification.is_cancel:
    prompt_batcher.cancel(prompt_batch_key_for(msg))
    ...
    return

if prompt_batcher.schedule(
    _PendingPrompt(
        msg=msg,
        text=text,
        ambient_context=ambient_context,
        chat_project=chat_project,
        topic_key=topic_key,
        chat_session_key=chat_session_key,
        reply_ref=reply_ref,
        reply_id=reply_id,
        is_voice_transcribed=False,
        forwards=[],
    )
):
    return
```

Then continue to current command/media/forward handling for non-batchable messages.

Important ordering:

- Do not batch forwarded-only messages; keep `ForwardCoalescer.attach_forward()` first.
- Do not batch media group documents; keep `MediaGroupBuffer.add()` first.
- Do not batch voice messages; voice transcription is async and should remain a single prompt after transcription.
- Do not batch `/file put` uploads or `/file get`.
- For `/compact`, batching must occur before built-in command dispatch so multi-message instructions are joined and then parsed as one `/compact` command.

**Step 5: Add config wiring tests**

Update `tests/telegram_fakes.py` `make_cfg()` to accept:

```python
prompt_batch_debounce_s: float = 0.0,
prompt_batch_max_messages: int = 6,
prompt_batch_max_chars: int = 120_000,
prompt_batch_separator: str = "blank_line",
```

Add settings tests:

```python
def test_telegram_prompt_batch_defaults() -> None:
    settings = load_settings(...)
    tg = settings.transports.telegram
    assert tg.prompt_batch_debounce_s == 0.0
    assert tg.prompt_batch_max_messages == 6
    assert tg.prompt_batch_max_chars == 120_000
    assert tg.prompt_batch_separator == "blank_line"
```

Add validation tests for negative debounce, too-low max messages, too-low char limit, and invalid separator.

**Step 6: Add integration tests**

Add to `tests/test_telegram_bridge.py` or `tests/test_telegram_prompt_batch.py`:

```python
@pytest.mark.anyio
async def test_consecutive_prompt_chunks_run_once() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        runner=runner,
        prompt_batch_debounce_s=0.05,
        forward_coalesce_s=0.0,
    )

    async def poller(_cfg):
        yield _msg(1, "first chunk")
        yield _msg(2, "second chunk")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "first chunk\n\nsecond chunk"
```

```python
@pytest.mark.anyio
async def test_compact_instructions_can_span_messages() -> None:
    runner = CompactScriptRunner([Return(answer="compacted")], engine="claude")
    cfg = make_cfg(
        runner=runner,
        prompt_batch_debounce_s=0.05,
    )
    await store_session(cfg, ResumeToken(engine="claude", value="sid"))

    async def poller(_cfg):
        yield _msg(1, "/compact preserve decisions")
        yield _msg(2, "and failed tests")

    await run_main_loop(cfg, poller)

    assert runner.compact_calls == [
        (ResumeToken(engine="claude", value="sid"), "preserve decisions\n\nand failed tests")
    ]
```

```python
@pytest.mark.anyio
async def test_engine_directive_resolves_after_joining() -> None:
    codex_runner = ScriptRunner([Return(answer="ok")], engine="codex")
    claude_runner = ScriptRunner([Return(answer="wrong")], engine="claude")
    cfg = make_multi_runner_cfg(
        [codex_runner, claude_runner],
        default_engine="claude",
        prompt_batch_debounce_s=0.05,
    )

    async def poller(_cfg):
        yield _msg(1, "/codex summarize")
        yield _msg(2, "this long pasted text")

    await run_main_loop(cfg, poller)

    assert codex_runner.calls[0][0] == "summarize\n\nthis long pasted text"
    assert not claude_runner.calls
```

Additional required integration cases:

- different sender does not batch;
- different chat does not batch;
- different topic/thread does not batch;
- different `reply_to_message_id` does not batch;
- delay longer than `prompt_batch_debounce_s` creates two runs;
- `/cancel` cancels the pending batch and then performs existing cancel behavior;
- `/new` cancels the pending batch before clearing sessions;
- `/ctx`, `/model`, `/reasoning`, `/queue`, `/file` bypass batching;
- forwarded messages still attach to the pending prompt through `ForwardCoalescer`;
- existing `test_run_main_loop_coalesces_forwarded_messages_after_prompt` still passes;
- mentions-only trigger mode still suppresses non-triggering batches.

**Step 7: Documentation**

Add to `docs/reference/config.md` under `[transports.telegram]`:

```markdown
| `prompt_batch_debounce_s` | float | `0.0` | Quiet window for combining consecutive text messages from the same sender/chat/topic/reply target into one prompt. Disabled by default. |
| `prompt_batch_max_messages` | int | `6` | Maximum text chunks in one prompt batch. |
| `prompt_batch_max_chars` | int | `120000` | Maximum assembled prompt characters before immediate flush. |
| `prompt_batch_separator` | `"newline"`\|`"blank_line"` | `"blank_line"` | Separator used between chunks. |
```

Add a section to `docs/reference/transports/telegram.md`:

````markdown
## Long prompt batching

Telegram may split or make users split a long prompt into multiple messages.
When `prompt_batch_debounce_s` is greater than zero, Takopi waits for that
quiet window and combines consecutive batchable text messages from the same
sender/chat/topic/reply target into one prompt.

Control commands, media uploads, voice messages, and forwarded-only messages are
not batched. `/compact [instructions]` is batchable, so long compaction
instructions can be sent across several messages.
````

Add to `docs/how-to/compact.md`:

````markdown
For long compact instructions:

```text
/compact preserve decisions and files
include failing tests
include exact next steps
```

Send those as consecutive Telegram messages within `prompt_batch_debounce_s`.
Takopi will assemble them as one `/compact` command.
````

**Step 8: Run focused verification**

```powershell
Set-Location -LiteralPath D:\Projects\takopi
$env:PYTHONUTF8 = '1'
python -m pytest tests/test_telegram_prompt_batch.py -q
python -m pytest tests/test_telegram_bridge.py -k "batch or compact or forward" -q
python -m pytest tests/test_settings.py tests/test_settings_contract.py -q
ruff check src/takopi/telegram/prompt_batch.py src/takopi/telegram/loop.py src/takopi/settings.py
```

Expected final behavior:

- `prompt_batch_debounce_s = 0.0` preserves current routing.
- When enabled, several consecutive qualifying text messages become one prompt.
- `/compact` instructions can span messages.
- Commands/media/voice/forwards retain existing behavior.
- No batch can cross sender/chat/topic/reply boundaries.

---

## Final Verification

Run focused tests first:

```powershell
Set-Location -LiteralPath D:\Projects\takopi
$env:PYTHONUTF8 = '1'
python -m pytest tests/test_compact_core.py tests/test_compact_slash_mixin.py -q
python -m pytest tests/test_opencode_compact.py tests/test_acp_client.py -q
python -m pytest tests/test_grok_compact_acp.py tests/test_omp_compact_acp.py -q
python -m pytest tests/test_telegram_compact_command.py tests/test_compact_event_invariants.py -q
python -m pytest tests/test_telegram_prompt_batch.py -q
```

Run regression tests:

```powershell
python -m pytest tests/test_runner_contract.py tests/test_telegram_bridge.py tests/test_transport_runtime.py -q
python -m pytest -q
ruff check .
python -m py_compile src/takopi/compact.py src/takopi/runners/_compact_mixin.py src/takopi/runners/_acp.py src/takopi/commands/compact.py src/takopi/telegram/prompt_batch.py
```

Expected final state:

- coverage remains at or above `--cov-fail-under=81`;
- `/compact` appears in Telegram `setMyCommands`;
- unsupported compact never starts a new session;
- all compact jobs use the existing per-session queue;
- every compact mode preserves event invariants;
- ACP compact refuses to run unless `compact` is advertised;
- `agy` output is labelled handoff summary, not real compaction.
- multi-message prompt batching is disabled by default and, when enabled, combines only qualifying same-scope text chunks into one prompt.

---

## Implementation Order With Commits

1. `test: cover compact core contracts`
2. `feat: add compact support model`
3. `test: cover slash compact runners`
4. `feat: add slash compact runner mixin`
5. `test: cover opencode compact api`
6. `feat: add opencode native compact`
7. `test: cover acp compact client`
8. `feat: add acp compact support`
9. `test: cover telegram compact command`
10. `feat: add compact command dispatch`
11. `docs: mark long-prompt batching as complete in the separate batching plan`
12. `cleanup: remove scratch artifacts after reference cleanup`
13. `docs: finalize compact plan references`

Only commit if the user explicitly asks for commits.

---

## Source References Used For This Plan

- Takopi local code: [pyproject.toml](D:/Projects/takopi/pyproject.toml), [runner.py](D:/Projects/takopi/src/takopi/runner.py), [commands.py](D:/Projects/takopi/src/takopi/commands.py), [api.py](D:/Projects/takopi/src/takopi/api.py), [scheduler.py](D:/Projects/takopi/src/takopi/scheduler.py), runner files under [src/takopi/runners](D:/Projects/takopi/src/takopi/runners).
- Takopi Telegram batching/routing code: [loop.py](D:/Projects/takopi/src/takopi/telegram/loop.py), [commands/parse.py](D:/Projects/takopi/src/takopi/telegram/commands/parse.py), [bridge.py](D:/Projects/takopi/src/takopi/telegram/bridge.py), [settings.py](D:/Projects/takopi/src/takopi/settings.py), [tests/test_telegram_bridge.py](D:/Projects/takopi/tests/test_telegram_bridge.py), [tests/telegram_fakes.py](D:/Projects/takopi/tests/telegram_fakes.py).
- Subagent read-only exploration (`gpt-5.6-terra`) confirmed: `ForwardCoalescer` only appends forwarded text; ordinary messages replace pending prompts; `_dispatch_pending_prompt()` resolves directives after pending text is assembled; media-group buffering is separate; Telegram incoming messages do not expose a continuation marker; the safe implementation point is a dedicated `PromptBatcher` before batchable command/prompt dispatch.
- Claude Code slash commands: https://code.claude.com/docs/en/agent-sdk/slash-commands
- Codex developer commands: https://developers.openai.com/codex/developer-commands
- Codex app-server protocol: https://developers.openai.com/codex/app-server
- OpenCode compaction: https://opencode.ai/v2/docs/compaction
- OpenCode API: https://opencode.ai/v2/docs/api
- Pi usage and `/compact [prompt]`: https://pi.dev/docs/latest/usage
- ACP v1 schema: https://agentclientprotocol.com/protocol/v1/schema
- Grok Build ACP command: https://zed.dev/acp/agent/grok-build
- Grok Build ACP support overview: https://x.ai/news/grok-build-cli
- OMP ACP: https://github.com/can1357/oh-my-pi

[[takopi-send: D:\Projects\takopi\docs\plans\2026-07-29-compact-runner-api-acp.md]]
