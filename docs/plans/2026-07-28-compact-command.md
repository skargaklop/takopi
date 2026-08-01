# Compact Command Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Telegram `/compact` command to Takopi that works across every production engine backend in Takopi's engine list. The command must compact or produce a handoff-quality continuity summary for the current resumed session, and it must accept an optional user prompt such as `/compact preserve API decisions and failing tests`.

**Architecture:** Implement `/compact` as a built-in Telegram meta command, not as a plugin command and not as a per-runner API expansion. Resolve the active session token using the same Telegram scope rules as normal prompts, then enqueue a compaction prompt through the existing scheduler. Use native Claude `/compact` when the current session engine is Claude. For the other harnesses, use an explicit fallback compaction prompt unless a future verified CLI contract proves a native trigger.

**Tech Stack:** Python 3.10+, Takopi Telegram bridge, existing `ThreadScheduler`, existing `ResumeResolver`, pytest, ruff.

**ASCII implementation sketch:**

```text
Telegram message: /compact [optional focus prompt]
        |
        v
parse_slash_command -> command_id="compact", args_text="..."
        |
        v
_dispatch_builtin_command(...)
        |
        v
handle_compact_command(...)
        |
        v
resolve current resumed session
  explicit resume > active reply > reply footer > topic store > chat store
        |
        v
build payload
  claude -> /compact [args]
  others -> explicit continuity-summary prompt + optional args
        |
        v
dispatch_prompt_run(..., resume_override=target_resume)
        |
        v
ThreadScheduler.enqueue_resume(...)
```

---

## Current-State Findings

Production engine backends are registered in [pyproject.toml](D:/Projects/takopi/pyproject.toml:42):

```toml
[project.entry-points."takopi.engine_backends"]
codex = "takopi.runners.codex:BACKEND"
claude = "takopi.runners.claude:BACKEND"
opencode = "takopi.runners.opencode:BACKEND"
pi = "takopi.runners.pi:BACKEND"
omp = "takopi.runners.omp:BACKEND"
grok = "takopi.runners.grok:BACKEND"
agy = "takopi.runners.agy:BACKEND"
```

The production scope is therefore:

```python
PRODUCTION_COMPACT_ENGINES = frozenset(
    {"codex", "claude", "opencode", "pi", "omp", "grok", "agy"}
)
```

`mock` and `ScriptRunner` are test harnesses only. They should be used in tests, but not shown as user-selectable compaction engines.

The shared runner contract in [runner.py](D:/Projects/takopi/src/takopi/runner.py:699) only exposes prompt execution:

```python
class Runner(Protocol):
    engine: EngineId

    def format_resume(self, token: ResumeToken) -> str: ...
    def extract_resume(self, text: str | None) -> ResumeToken | None: ...
    def run(
        self,
        prompt: str,
        resume: ResumeToken | None,
    ) -> AsyncIterator[TakopiEvent]: ...
```

There is no existing `compact()` method and no existing `/compact` Telegram built-in. The correct v1 integration is to transform `/compact` into a prompt and send it through the already serialized resumed-run path.

Evidence for native compaction is uneven:

| Engine | Current resumed dispatch | Local evidence | v1 behavior |
|---|---|---|---|
| `claude` | `claude -p ... --resume <id> -- <prompt>` | Fixture advertises `compact` in Claude `slash_commands`. | Send native `/compact` or `/compact <user prompt>`. |
| `codex` | App-server `thread/resume` then `turn/start`; exec mode uses `codex exec resume <id> -`. | Takopi renders `contextCompaction` events, but no trigger endpoint or local slash/ACP contract is proven. | Send explicit fallback prompt. Never send `/compact` over ACP unless that capability is advertised. |
| `opencode` | `opencode run --format json --session <id> -- <prompt>` | No local compact flag or command evidence. | Send explicit fallback prompt. |
| `pi` | `pi --print --mode json --session <id> <prompt>` | Pi schema models `auto_compaction_start/end`, but not a user-trigger command. | Send explicit fallback prompt. |
| `omp` | `omp --print --mode json --resume <id> <prompt>` | Reuses Pi event style; no local compact trigger. | Send explicit fallback prompt. |
| `grok` | `grok -p <prompt> ... --resume <id>` | No local compact flag or command evidence. | Send explicit fallback prompt. |
| `agy` | `agy ... --conversation <id> -p <prompt>` | No local compact flag or command evidence. | Send explicit fallback handoff prompt only; never present this as real context compaction. |

Important implementation rule: the feature can be "implemented for all harnesses" by supporting every engine in the command and preserving session targeting, but it must not falsely claim native context-window compaction where only a prompt-based continuity summary is proven.

Hard implementation constraints:

- Never send literal `/compact` over ACP unless the active ACP harness explicitly advertises a compact command/capability. Event observation such as `contextCompaction` is not enough to infer trigger support.
- Never present an `agy` fallback handoff summary as real compaction. UI copy, docs, logs, and tests should call it a handoff or continuity summary.
- Respect per-session locks and event invariants for every runner. `/compact` must enqueue through the existing scheduler for the target resume token and must not bypass runner event sequencing, active-turn ownership, or completion/footer behavior.

---

## User-Facing Behavior

Add a Telegram command:

```text
/compact
/compact <user focus prompt>
```

Expected behavior:

1. `/compact` targets the current active session for the Telegram chat/topic scope.
2. `/compact <prompt>` passes the prompt as compaction instructions.
3. Replying with `/compact` to a bot message from an older session compacts that replied session.
4. If a message replies to a currently running progress message, the compaction request queues behind that active run for the same resume token.
5. If there is no active or stored resumed session, Takopi replies with an actionable error and does not start a fresh agent run.

Suggested error:

```text
no active session to compact.
reply to a Takopi progress/final message, or send a normal prompt first.
```

Examples:

```text
/compact
/compact preserve decisions, changed files, failing tests, and next steps
```

Native Claude payload:

```text
/compact
/compact preserve decisions, changed files, failing tests, and next steps
```

Fallback payload for non-Claude engines:

```text
Compact this session for reliable continuation.

Preserve:
- current user goal and latest instruction
- active project and relevant paths
- decisions already made
- files changed or inspected
- commands run and verification results
- open blockers, risks, and next steps

Write the result as a concise continuation summary that can be used by the next agent turn.

User focus:
preserve decisions, changed files, failing tests, and next steps
```

---

## Files To Change

### 1. Reserve `/compact`

File: [src/takopi/ids.py](D:/Projects/takopi/src/takopi/ids.py:9)

Add `compact` to `RESERVED_CHAT_COMMANDS`:

```python
RESERVED_CHAT_COMMANDS = frozenset(
    {
        "cancel",
        "file",
        "new",
        "agent",
        "model",
        "reasoning",
        "trigger",
        "topic",
        "ctx",
        "plan",
        "goal",
        "queue",
        "compact",
    }
)
```

Why: project aliases, engine ids, and plugin commands must not steal `/compact`.

### 2. Classify `/compact` As Pure Meta

File: [src/takopi/telegram/commands/meta_args.py](D:/Projects/takopi/src/takopi/telegram/commands/meta_args.py:15)

Add `compact` to `_PURE_META`:

```python
_PURE_META = frozenset(
    {
        "cancel",
        "file",
        "new",
        "ctx",
        "topic",
        "queue",
        "compact",
        "trigger",
        "model",
        "reasoning",
    }
)
```

Why: unlike `/plan` and `/goal`, `/compact <text>` must not fall through as a normal prompt. The handler owns session targeting and prompt construction.

### 3. Add Menu Entry

File: [src/takopi/telegram/commands/menu.py](D:/Projects/takopi/src/takopi/telegram/commands/menu.py:58)

Add:

```python
("compact", "compact current session"),
```

near `/queue`.

### 4. Add Compact Prompt Builder

New file: `src/takopi/telegram/commands/compact.py`

Keep this module small. It should parse no complex flags in v1. It should only:

- format native Claude payloads;
- format fallback payloads for other engines;
- provide a focused handler helper or reusable pure functions;
- avoid modifying runner adapters.

Code example:

```python
from __future__ import annotations

from ...model import EngineId

NATIVE_COMPACT_ENGINES = frozenset({"claude"})

COMPACT_FALLBACK = """Compact this session for reliable continuation.

Preserve:
- current user goal and latest instruction
- active project and relevant paths
- decisions already made
- files changed or inspected
- commands run and verification results
- open blockers, risks, and next steps

Write the result as a concise continuation summary that can be used by the next agent turn."""


def build_compact_prompt(engine: EngineId, args_text: str) -> str:
    focus = (args_text or "").strip()
    if engine == "claude":
        return "/compact" if not focus else f"/compact {focus}"
    if not focus:
        return COMPACT_FALLBACK
    return f"{COMPACT_FALLBACK}\n\nUser focus:\n{focus}"
```

Do not put CLI-specific flags here. The existing runners already know how to pass one prompt into a resumed session.

### 5. Route Built-In Command

File: [src/takopi/telegram/loop.py](D:/Projects/takopi/src/takopi/telegram/loop.py:238)

Import the handler/prompt builder and add a `compact` branch in `_dispatch_builtin_command`.

The command needs access to scheduler/running-task state. `TelegramCommandContext` already carries both:

```python
@dataclass(frozen=True, slots=True)
class TelegramCommandContext:
    ...
    scheduler: ThreadScheduler | None = None
    running_tasks: Mapping[MessageRef, object] | None = None
```

Add branch after `/queue` or near it:

```python
if command_id == "compact":
    handler = partial(
        handle_compact_command,
        cfg,
        msg,
        args_text,
        ambient_context,
        topic_store,
        chat_prefs,
        resolved_scope=resolved_scope,
        scope_chat_ids=scope_chat_ids,
        scheduler=ctx.scheduler,
        running_tasks=ctx.running_tasks,
        dispatch_prompt_run=ctx.dispatch_prompt_run,
    )
    task_group.start_soon(handler)
    return True
```

This code example shows the desired shape, but `TelegramCommandContext` currently does not expose `dispatch_prompt_run`. Implement that via the next step instead of calling runners directly.

### 6. Add A Narrow Resume Override

File: [src/takopi/telegram/loop.py](D:/Projects/takopi/src/takopi/telegram/loop.py:1579)

Current `dispatch_prompt_run(...)` resolves a session from the incoming message, reply, running task, or stored topic/chat session. `/compact` must reuse the selected target session and prevent accidental fresh-session creation.

Add a narrow optional parameter:

```python
resume_override: ResumeToken | None = None
```

Use it before `resume_resolver.resolve(...)`:

```python
if resume_override is not None:
    resume_decision = ResumeDecision(
        resume_token=resume_override,
        handled_by_running_task=False,
    )
else:
    resume_decision = await resume_resolver.resolve(...)
```

Also force engine routing from the override:

```python
if resume_override is not None:
    run_engine_id = resume_override.engine
else:
    run_engine_id = _resolve_run_engine(...)
```

Why: without this, `/compact` can select the default engine or create a fresh session when the user intended to compact an existing one.

### 7. Resolve The Current Compact Target

Prefer extracting a small helper around existing `ResumeResolver` usage instead of duplicating all lookup rules.

Recommended helper signature:

```python
async def resolve_current_resume_for_command(
    *,
    cfg: TelegramBridgeConfig,
    msg: TelegramIncomingMessage,
    resolved: ResolvedMessage,
    resume_resolver: ResumeResolver,
    topic_key: tuple[int, int] | None,
    chat_session_key: tuple[int, int | None] | None,
    reply_id: int | None,
    engine_for_session: EngineId,
    prompt_text: str,
) -> ResumeToken | None:
    decision = await resume_resolver.resolve(
        resume_token=resolved.resume_token,
        reply_id=reply_id,
        chat_id=msg.chat_id,
        user_msg_id=msg.message_id,
        thread_id=msg.thread_id,
        chat_session_key=chat_session_key,
        topic_key=topic_key,
        engine_for_session=engine_for_session,
        prompt_text=prompt_text,
        user_resume=resolved.user_resume,
        bare_resume_id=resolved.bare_resume_id,
        reply_resume=resolved.reply_resume,
    )
    if decision.handled_by_running_task:
        return None
    return decision.resume_token
```

However, for `/compact`, active running-task replies should queue compaction behind the active session, not inject a prompt through `send_with_resume` before payload mapping. If the current helper returns `handled_by_running_task=True`, add a `resolve_only` mode or a separate method that returns the running task resume token without scheduling.

Better shape:

```python
async def resolve_resume_token_only(...) -> ResumeToken | None:
    # same precedence as ResumeResolver.resolve
    # explicit user resume
    # bare resume id
    # reply to active running progress message -> running_task.resume
    # reply footer resume
    # topic stored session
    # chat stored session
```

Keep this helper in `loop.py` for v1 because it depends on local Telegram state stores. Extract to `telegram/resume.py` only if the implementation starts making `loop.py` harder to read.

### 8. Handler Flow

Expected handler pseudocode:

```python
async def handle_compact_command(...):
    reply = make_reply(cfg, msg)

    if scheduler is None:
        await reply(text="compact is unavailable.")
        return

    resolved = cfg.runtime.resolve_message(
        text=args_text,
        reply_text=msg.reply_to_text,
        ambient_context=ambient_context,
        chat_id=msg.chat_id,
    )

    engine_resolution = await resolve_engine_defaults(
        explicit_engine=resolved.engine_override,
        context=resolved.context,
        chat_id=msg.chat_id,
        topic_key=topic_key,
    )
    engine_for_session = _resolve_run_engine(
        engine_default=engine_resolution.engine,
        user_resume=resolved.user_resume,
        reply_resume=resolved.reply_resume,
    )

    resume = await resolve_resume_token_only(...)
    if resume is None:
        await reply(
            text=(
                "no active session to compact.\n"
                "reply to a Takopi progress/final message, or send a normal prompt first."
            )
        )
        return

    compact_prompt = build_compact_prompt(resume.engine, resolved.prompt)
    compact_resolved = ResolvedMessage(
        prompt=compact_prompt,
        resume_token=resume,
        engine_override=resume.engine,
        context=resolved.context,
        context_source=resolved.context_source,
        plan=False,
        goal=None,
        user_resume=resume,
        bare_resume_id=None,
        reply_resume=None,
    )

    await dispatch_prompt_run(
        msg=msg,
        prompt_text=compact_prompt,
        resolved=compact_resolved,
        topic_key=topic_key,
        chat_session_key=chat_session_key,
        reply_ref=reply_ref,
        reply_id=reply_id,
        resume_override=resume,
    )
```

Implementation note: the exact `ResolvedMessage` construction should match the live dataclass fields in `transport_runtime.py`. Keep `plan=False` and `goal=None`; compaction should not inherit sticky plan/goal modes.

---

## Test Plan (TDD First)

Write tests before implementation.

### Test 1: Meta Classification

File: [tests/test_plan_goal_modes.py](D:/Projects/takopi/tests/test_plan_goal_modes.py:54)

Add `compact` to the pure-meta matrix:

```python
def test_compact_is_pure_meta() -> None:
    from takopi.telegram.commands.meta_args import should_handle_as_meta_command

    engines = ("codex", "claude", "opencode", "pi", "omp", "grok", "agy")
    assert should_handle_as_meta_command("compact", "", engine_ids=engines) is True
    assert (
        should_handle_as_meta_command(
            "compact",
            "preserve decisions",
            engine_ids=engines,
        )
        is True
    )
```

### Test 2: Prompt Mapping

New file: `tests/test_telegram_compact_command.py`

```python
import pytest

from takopi.telegram.commands.compact import build_compact_prompt


def test_claude_compact_uses_native_slash_command() -> None:
    assert build_compact_prompt("claude", "") == "/compact"
    assert (
        build_compact_prompt("claude", "preserve API decisions")
        == "/compact preserve API decisions"
    )


@pytest.mark.parametrize(
    "engine",
    ["codex", "opencode", "pi", "omp", "grok", "agy"],
)
def test_other_engines_use_fallback_prompt(engine: str) -> None:
    prompt = build_compact_prompt(engine, "preserve failing tests")
    assert prompt.startswith("Compact this session for reliable continuation.")
    assert "User focus:\npreserve failing tests" in prompt
    assert not prompt.startswith("/compact")
```

### Test 3: Command Menu

File: [tests/test_telegram_bridge.py](D:/Projects/takopi/tests/test_telegram_bridge.py:138)

Extend `test_build_bot_commands_includes_cancel_and_engine`:

```python
assert {"command": "compact", "description": "compact current session"} in commands
```

### Test 4: Reserved Ids

Add a focused assertion in an existing ids/config test:

```python
from takopi.ids import RESERVED_CHAT_COMMANDS


def test_compact_is_reserved_chat_command() -> None:
    assert "compact" in RESERVED_CHAT_COMMANDS
```

### Test 5: Stored Session Dispatch

Use existing Telegram bridge fakes and `ScriptRunner`.

Coverage:

1. Store a Claude resume token for the chat or topic.
2. Send `/compact`.
3. Assert the script runner receives prompt `/compact`.
4. Assert the resume token is the stored token.

Example shape:

```python
async def test_compact_uses_stored_claude_session(tmp_path: Path) -> None:
    runner = ScriptRunner(
        [Return(answer="compacted")],
        engine="claude",
        resume_value="claude-session",
    )
    cfg = make_cfg(tmp_path, runner=runner, stateful=True)
    await cfg.chat_session_store.set_session_resume(
        chat_id,
        None,
        ResumeToken(engine="claude", value="claude-session"),
    )

    await route_message(make_message("/compact", chat_id=chat_id))

    assert runner.calls[-1].prompt == "/compact"
    assert runner.calls[-1].resume == ResumeToken(
        engine="claude",
        value="claude-session",
    )
```

Adjust exact fake APIs to match [tests/test_telegram_bridge.py](D:/Projects/takopi/tests/test_telegram_bridge.py).

### Test 6: Fallback For Every Non-Claude Engine

Parametrize over `codex`, `opencode`, `pi`, `omp`, `grok`, `agy`:

```python
@pytest.mark.parametrize("engine", ["codex", "opencode", "pi", "omp", "grok", "agy"])
async def test_compact_fallback_for_non_claude_engine(engine: str, tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="summary")], engine=engine, resume_value="sid")
    cfg = make_cfg(tmp_path, runner=runner, stateful=True)
    await store_resume(cfg, engine, "sid")

    await route_message(make_message("/compact preserve blockers"))

    call = runner.calls[-1]
    assert call.resume == ResumeToken(engine=engine, value="sid")
    assert call.prompt.startswith("Compact this session for reliable continuation.")
    assert "User focus:\npreserve blockers" in call.prompt
```

### Test 7: No Session Does Not Launch

```python
async def test_compact_without_session_replies_error_and_does_not_run(tmp_path: Path) -> None:
    runner = ScriptRunner([Return(answer="should not run")], engine="codex")
    cfg = make_cfg(tmp_path, runner=runner, stateful=True)

    await route_message(make_message("/compact"))

    assert not runner.calls
    assert any("no active session to compact" in sent.text for sent in cfg.bot.sent)
```

### Test 8: Running Session Queues, Does Not Steer

Use the existing queue tests as reference. The important assertion is that a compact request for a busy resume token becomes a queued scheduler job and does not use Codex steering.

```python
async def test_compact_queues_behind_busy_thread(...) -> None:
    ...
    assert queued_job.text.startswith("Compact this session")
    assert queued_job.resume == ResumeToken(engine="codex", value="thread-id")
```

---

## Implementation Sequence

1. Add tests for meta classification, reserved command, menu entry, and prompt mapping.
2. Implement `src/takopi/telegram/commands/compact.py` with `build_compact_prompt`.
3. Add `compact` to `ids.py`, `meta_args.py`, `menu.py`, and `handlers.py`.
4. Run the first focused tests and confirm they fail only before the relevant implementation step.
5. Add or extract the token-only resume resolver path in `telegram/loop.py`.
6. Add `resume_override` to `dispatch_prompt_run`.
7. Wire `_dispatch_builtin_command` to run `/compact`.
8. Add integration tests for stored sessions, reply-footer sessions, active running-task replies, no-session errors, and every production engine.
9. Update [docs/reference/commands-and-directives.md](D:/Projects/takopi/docs/reference/commands-and-directives.md:70) to document `/compact`.
10. Run focused tests, then full verification.

Suggested verification commands:

```powershell
Set-Location -LiteralPath D:\Projects\takopi
$env:PYTHONUTF8 = '1'
python -m pytest tests/test_plan_goal_modes.py tests/test_telegram_compact_command.py -q
python -m pytest tests/test_telegram_bridge.py -q
python -m pytest tests/test_transport_runtime.py tests/test_codex_runner_helpers.py tests/test_claude_runner.py -q
ruff check .
python -m py_compile src/takopi/telegram/commands/compact.py src/takopi/telegram/loop.py src/takopi/ids.py
```

Do not commit unless the user explicitly asks for a commit.

---

## Documentation Update

Add this to [docs/reference/commands-and-directives.md](D:/Projects/takopi/docs/reference/commands-and-directives.md:70):

```markdown
| `/compact` | Compact or summarize the active resumed session. `/compact <focus>` passes focus instructions. Claude uses native `/compact`; other engines receive a fallback continuity-summary prompt unless their native compact trigger is later verified. |
```

Add a capability matrix column:

```markdown
| Engine | Queue (Takopi FIFO) | Mid-turn steer | Plan mode | Goal loop | Compact |
|---|---:|---:|---|---|---|
| codex | yes | yes (app-server) | soft prompt | soft note | fallback continuity prompt |
| claude | yes | no | `--permission-mode plan` | `/goal` in prompt | native `/compact` prompt |
| grok | yes | no | `--permission-mode plan` | best-effort `/goal` prompt | fallback continuity prompt |
| agy | yes | no | `--mode plan` | soft note | fallback handoff summary, not real compaction |
| omp | yes | no | `omp.plan_mode=soft\|yolo\|off` | soft note | fallback continuity prompt |
| pi | yes | no | `--plan` (pi-plan-mode extension) | soft note | fallback continuity prompt |
| opencode | yes | no | soft, or `--agent` if `opencode.plan_agent` set | soft note | fallback continuity prompt |
```

---

## Risks And Pitfalls

- Do not send literal `/compact` to every engine unless a native contract is verified. That would be speculative for Codex, OpenCode, Pi, OMP, Grok, and Agy.
- Do not send `/compact` over ACP unless the ACP harness advertises compact support. Do not infer support from event names alone.
- Do not describe `agy` fallback output as compaction. It is a handoff/continuity summary.
- Do not create a new session when `/compact` has no session target. Compaction is meaningful only for an existing thread.
- Do not bypass `ThreadScheduler`. Direct runner calls can race an active turn and break Takopi's per-thread FIFO behavior.
- Do not violate per-session locks or runner event invariants. The compact command should use the same enqueue/run/finalization path as normal resumed prompts.
- Do not inherit sticky `/plan` or `/goal` settings. Compaction should run as a normal resumed prompt.
- Do not make `/compact` a plugin command. Built-ins are reserved and need access to Telegram session state.
- Do not expand the runner protocol unless future verified CLIs expose native compaction APIs that cannot be represented as a prompt.

---

## Subagent Research Notes

The delegated `gpt-5.6-terra` read-only agent confirmed:

- supported production backends are `codex`, `claude`, `opencode`, `pi`, `omp`, `grok`, and `agy`;
- Takopi has no current `/compact` command and no runner-level compaction API;
- Claude has local fixture evidence for a native `/compact` slash command;
- Codex only has local evidence for receiving/rendering `contextCompaction` events, not triggering them;
- Pi models automatic compaction events but no user-trigger mechanism;
- all other harnesses should use a fallback continuity-summary prompt in v1;
- `/compact` must retain the current session resume token and should use the normal scheduler.

The main inconvenience reported by the subagent was evidence quality: local source proves observation for some compaction events, but not invocation contracts. The implementation should therefore document fallback semantics precisely.
