# Telegram Multi-Message Input Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Combine several consecutive Telegram text messages that arrive within a very small configurable time window into one Takopi prompt, independently from the `/compact` feature.

**Architecture:** Add a Telegram-side text input batcher before prompt dispatch, plugin-command dispatch, and engine-directive execution. The batcher groups only qualifying text messages from the same chat/topic/sender/reply scope, flushes one assembled `_PendingPrompt`, and then lets the existing resolver, `ForwardCoalescer`, `ThreadScheduler`, resume handling, and queue logic work normally. `/compact` remains a separate feature; this batching layer must handle all prompt workflows, not just compact instructions.

**Tech Stack:** Python 3.14, anyio, pydantic settings, Takopi Telegram bridge, existing `_PendingPrompt`, `ForwardCoalescer`, `ThreadScheduler`, pytest, ruff.

**ASCII implementation sketch:**

```text
Several Telegram text messages arrive quickly
        |
        v
route_message()
        |
        +-- media/voice/forward/control command --> existing path
        |
        +-- batchable text -----------------------> PromptInputBatcher
                                                    key:
                                                    chat + topic/thread
                                                    sender + reply target
                                                    |
                                                    v
                                            quiet window / max limits
                                                    |
                                                    v
                                      one assembled _PendingPrompt
                                                    |
                                                    v
                                      _dispatch_pending_prompt()
                                                    |
                                                    v
                             existing directive parsing / context / resume
                                                    |
                                                    v
                                existing ThreadScheduler queue behavior
```

---

## Separation From Compact

This plan is for feature 2 only:

```text
Feature 1: /compact command and runner compaction support.
Feature 2: Telegram multi-message input batching.
```

The batching feature must not be implemented as compact-specific logic. It should work for ordinary prompts, engine directives, project directives, plan/goal prompt runs, plugin commands that accept prompt-like arguments, replies to active sessions, chat-session auto-resume, topics, and stateless workflows.

Compact may benefit from batching only because `/compact ...` is just another Telegram text command after this feature exists. There must be no code path named or shaped as "compact long instructions batching".

---

## Current Code Findings

Prompt routing is concentrated in [src/takopi/telegram/loop.py](D:/Projects/takopi/src/takopi/telegram/loop.py):

- `_PendingPrompt` carries the message, text, ambient context, topic key, chat-session key, reply ref/id, voice flag, and attached forwarded text.
- `route_message()` classifies each update, handles forwards/media/cancel/built-ins/plugin commands, then creates `_PendingPrompt`.
- `_dispatch_pending_prompt()` resolves directives from `pending.text`, then passes one prompt into `dispatch_prompt_run()`.
- `dispatch_prompt_run()` is the right downstream boundary because it resolves engine defaults, resume tokens, replies to active runs, stored topic/chat sessions, and queueing.
- `ForwardCoalescer` waits for a prompt candidate and attaches immediately-following forwarded messages. It is not a general text chunk batcher.
- A normal follow-up text message currently replaces a pending prompt in `ForwardCoalescer`; it is not appended.
- `MediaGroupBuffer` handles Telegram media albums separately by `media_group_id`. Do not mix media album batching with text prompt batching.
- `parse_slash_command()` supports multiline command bodies inside one Telegram message, but not several separate Telegram messages.
- `TelegramTransportSettings` currently has `forward_coalesce_s` and `media_group_debounce_s`, but no generic text prompt batching settings.

There is no Telegram update field that says "this message is part two of the same oversized user prompt." Takopi must define a strict, configurable product rule.

---

## Behavioral Contract

When text batching is enabled, Takopi groups consecutive qualifying text messages if all are true:

- same `chat_id`;
- same `thread_id` or topic scope;
- same `sender_id`;
- same `reply_to_message_id`;
- each message arrives before the quiet window expires;
- each message is text-only and not a forwarded-only message, voice message, document, media group item, or control command;
- configured max message and max char limits are not exceeded.

One batch becomes exactly one prompt. The normal downstream path decides whether that prompt starts a new run, resumes a session, queues behind an active session, dispatches a plugin command, or is ignored by trigger mode.

Queue contract:

- if the assembled prompt targets a busy `ResumeToken`, it must enqueue as one job;
- individual chunks must not enqueue separate jobs;
- a batch must not bypass `ThreadScheduler`;
- same-session FIFO ordering must remain unchanged;
- active-run reply handling must still wait for or reuse the active resume token.

Default behavior:

- add configurable batching with a conservative default quiet window;
- all thresholds must be configurable, not hardcoded;
- expose a simple off switch.

Recommended defaults:

```toml
[transports.telegram]
prompt_batch_enabled = true
prompt_batch_debounce_s = 0.75
prompt_batch_max_messages = 8
prompt_batch_max_chars = 120000
prompt_batch_separator = "blank_line"
```

Reasoning: `0.75s` is small enough to avoid turning chat into a slow interface, but long enough to catch copy/paste or rapid-send split prompts. Users who prefer strict one-message behavior can set `prompt_batch_enabled = false` or `prompt_batch_debounce_s = 0`.

---

## Batchable And Non-Batchable Inputs

Batchable:

- ordinary text prompts;
- engine directives like `/codex ...`, `/claude ...`, `/pi ...`;
- project directives and branch directives at the beginning of the first chunk;
- `/plan <prompt>` and `/goal <condition>` when they are prompt-running forms;
- plugin command messages that are not reserved control commands and have arguments;
- replies to bot progress/final messages, provided every chunk has the same reply target;
- messages in stateless mode, chat-session mode, and topics.

Non-batchable:

- `/cancel`;
- `/new`;
- `/ctx`;
- `/agent`;
- `/model`;
- `/reasoning`;
- `/trigger`;
- `/queue`;
- `/file`;
- `/topic`;
- bare `/plan` sticky/help command;
- bare `/goal` help command;
- empty text;
- forwarded-only messages;
- voice messages;
- documents and media albums;
- messages from a different sender/chat/topic/reply target.

Important distinction:

```text
Batching decides "are these chunks one input?"
Existing dispatch decides "what does this input mean?"
```

Do not duplicate directive, command, engine, project, context, resume, or trigger logic inside the batcher.

---

## Task 1: Pure Batch Decision Module

**Files:**

- Create: `src/takopi/telegram/prompt_batch.py`
- Test: `tests/test_telegram_prompt_batch.py`

**Step 1: Write failing tests**

```python
from takopi.telegram.prompt_batch import (
    PromptBatchPart,
    PromptBatchSettings,
    join_prompt_parts,
    should_batch_text,
)


def test_batch_plain_text_when_enabled() -> None:
    settings = PromptBatchSettings(enabled=True)
    assert should_batch_text("fix this bug", settings=settings) is True


def test_disabled_batcher_never_batches() -> None:
    settings = PromptBatchSettings(enabled=False)
    assert should_batch_text("fix this bug", settings=settings) is False
    assert should_batch_text("/codex fix this", settings=settings) is False


def test_control_commands_do_not_batch() -> None:
    settings = PromptBatchSettings(enabled=True)
    for text in (
        "/cancel",
        "/new",
        "/ctx",
        "/agent claude",
        "/model set x",
        "/reasoning high",
        "/trigger mentions",
        "/queue",
        "/file put a.txt",
        "/topic proj",
    ):
        assert should_batch_text(text, settings=settings) is False


def test_prompt_directives_can_batch() -> None:
    settings = PromptBatchSettings(enabled=True)
    for text in (
        "/codex summarize",
        "/plan refactor",
        "/goal tests pass",
        "/project-alias do work",
        "@branch do work",
    ):
        assert should_batch_text(text, settings=settings) is True


def test_bare_plan_goal_do_not_batch() -> None:
    settings = PromptBatchSettings(enabled=True)
    assert should_batch_text("/plan", settings=settings) is False
    assert should_batch_text("/goal", settings=settings) is False


def test_join_parts_in_message_id_order() -> None:
    parts = [
        PromptBatchPart(message_id=3, text="third"),
        PromptBatchPart(message_id=1, text="first"),
        PromptBatchPart(message_id=2, text="second"),
    ]
    assert join_prompt_parts(parts, separator="newline") == "first\nsecond\nthird"
    assert (
        join_prompt_parts(parts, separator="blank_line")
        == "first\n\nsecond\n\nthird"
    )
```

Expected before implementation: import failure.

**Step 2: Implement pure helpers**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .commands.parse import parse_slash_command
from .commands.goal_cmd import is_sticky_goal_args
from .commands.plan_cmd import is_sticky_plan_args

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
    max_messages: int = 8
    max_chars: int = 120_000
    separator: PromptBatchSeparator = "blank_line"


@dataclass(frozen=True, slots=True)
class PromptBatchPart:
    message_id: int
    text: str


def should_batch_text(text: str, *, settings: PromptBatchSettings) -> bool:
    if not settings.enabled:
        return False
    if not text.strip():
        return False

    command_id, args_text = parse_slash_command(text)
    if command_id is None:
        return True
    if command_id in CONTROL_COMMANDS:
        return False
    if command_id == "plan":
        return not is_sticky_plan_args(args_text)
    if command_id == "goal":
        return not is_sticky_goal_args(args_text)

    # Engine directives, project aliases, and plugin commands with text are
    # interpreted after batching by the existing dispatcher.
    return bool(args_text.strip())


def join_prompt_parts(
    parts: list[PromptBatchPart],
    *,
    separator: PromptBatchSeparator,
) -> str:
    sep = "\n" if separator == "newline" else "\n\n"
    ordered = sorted(parts, key=lambda part: part.message_id)
    return sep.join(part.text for part in ordered)
```

**Step 3: Run tests**

```powershell
Set-Location -LiteralPath D:\Projects\takopi
$env:PYTHONUTF8 = '1'
python -m pytest tests/test_telegram_prompt_batch.py -q
```

---

## Task 2: Settings And Wiring

**Files:**

- Modify: `src/takopi/settings.py`
- Modify: `src/takopi/telegram/bridge.py`
- Modify: `src/takopi/telegram/backend.py`
- Modify: `tests/telegram_fakes.py`
- Test: `tests/test_settings.py`
- Test: `tests/test_settings_contract.py`
- Test: `tests/test_telegram_backend.py`

**Step 1: Write failing settings tests**

```python
def test_telegram_prompt_batch_defaults() -> None:
    settings = load_settings(config_with_telegram())
    tg = settings.transports.telegram
    assert tg.prompt_batch_enabled is True
    assert tg.prompt_batch_debounce_s == 0.75
    assert tg.prompt_batch_max_messages == 8
    assert tg.prompt_batch_max_chars == 120_000
    assert tg.prompt_batch_separator == "blank_line"


def test_telegram_prompt_batch_validation() -> None:
    with pytest.raises(ValidationError):
        load_settings(config_with_telegram("prompt_batch_debounce_s = -1"))
    with pytest.raises(ValidationError):
        load_settings(config_with_telegram("prompt_batch_max_messages = 1"))
    with pytest.raises(ValidationError):
        load_settings(config_with_telegram("prompt_batch_max_chars = 100"))
    with pytest.raises(ValidationError):
        load_settings(config_with_telegram('prompt_batch_separator = "bad"'))
```

**Step 2: Add settings fields**

```python
class TelegramTransportSettings(BaseModel):
    ...
    prompt_batch_enabled: bool = True
    prompt_batch_debounce_s: float = Field(default=0.75, ge=0)
    prompt_batch_max_messages: StrictInt = Field(default=8, ge=2)
    prompt_batch_max_chars: StrictInt = Field(default=120_000, ge=4096)
    prompt_batch_separator: Literal["newline", "blank_line"] = "blank_line"
```

**Step 3: Wire bridge config**

```python
@dataclass(frozen=True, slots=True)
class TelegramBridgeConfig:
    ...
    prompt_batch_enabled: bool = True
    prompt_batch_debounce_s: float = 0.75
    prompt_batch_max_messages: int = 8
    prompt_batch_max_chars: int = 120_000
    prompt_batch_separator: Literal["newline", "blank_line"] = "blank_line"
```

Update `src/takopi/telegram/backend.py`:

```python
cfg = TelegramBridgeConfig(
    ...
    prompt_batch_enabled=settings.prompt_batch_enabled,
    prompt_batch_debounce_s=settings.prompt_batch_debounce_s,
    prompt_batch_max_messages=int(settings.prompt_batch_max_messages),
    prompt_batch_max_chars=int(settings.prompt_batch_max_chars),
    prompt_batch_separator=settings.prompt_batch_separator,
)
```

Update `tests/telegram_fakes.py` `make_cfg()` with matching keyword args so integration tests can set a tiny debounce.

**Step 4: Run**

```powershell
python -m pytest tests/test_settings.py tests/test_settings_contract.py tests/test_telegram_backend.py -q
```

---

## Task 3: PromptInputBatcher

**Files:**

- Modify: `src/takopi/telegram/loop.py`
- Test: `tests/test_telegram_prompt_batch.py`

**Step 1: Write unit tests with fake dispatch**

```python
@pytest.mark.anyio
async def test_batcher_flushes_one_pending_prompt_after_quiet_window() -> None:
    sent: list[_PendingPrompt] = []

    async def dispatch(pending: _PendingPrompt) -> None:
        sent.append(pending)

    batcher = PromptInputBatcher(
        task_group=_TaskGroup(),
        debounce_s=0.01,
        sleep=anyio.sleep,
        dispatch=dispatch,
        max_messages=8,
        max_chars=120_000,
        separator="blank_line",
    )

    assert batcher.schedule(_pending(1, "one")) is True
    assert batcher.schedule(_pending(2, "two")) is True
    await anyio.sleep(0.03)

    assert len(sent) == 1
    assert sent[0].text == "one\n\ntwo"


@pytest.mark.anyio
async def test_batcher_flushes_at_max_messages() -> None:
    ...
```

Expected before implementation: `PromptInputBatcher` missing.

**Step 2: Add key/state dataclasses**

Keep the first `_PendingPrompt` as the metadata source. Later messages contribute only text.

```python
@dataclass(frozen=True, slots=True)
class PromptBatchKey:
    chat_id: int
    thread_id: int | None
    sender_id: int
    reply_to_message_id: int | None


@dataclass(slots=True)
class PromptBatchState:
    first_pending: _PendingPrompt
    parts: list[PromptBatchPart]
    cancel_scope: anyio.CancelScope | None = None
```

**Step 3: Implement batcher**

```python
class PromptInputBatcher:
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
    ) -> None:
        ...

    def key_for(self, pending: _PendingPrompt) -> PromptBatchKey | None:
        sender = pending.msg.sender_id
        if sender is None:
            return None
        return PromptBatchKey(
            chat_id=pending.msg.chat_id,
            thread_id=pending.msg.thread_id,
            sender_id=sender,
            reply_to_message_id=pending.msg.reply_to_message_id,
        )

    def cancel(self, key: PromptBatchKey | None) -> None:
        if key is None:
            return
        state = self._pending.pop(key, None)
        if state is not None and state.cancel_scope is not None:
            state.cancel_scope.cancel()

    def schedule(self, pending: _PendingPrompt) -> bool:
        key = self.key_for(pending)
        if key is None:
            return False
        text = pending.text
        settings = PromptBatchSettings(
            enabled=self._debounce_s > 0,
            max_messages=self._max_messages,
            max_chars=self._max_chars,
            separator=self._separator,
        )
        if not should_batch_text(text, settings=settings):
            return False

        part = PromptBatchPart(message_id=pending.msg.message_id, text=text)
        state = self._pending.get(key)
        if state is None:
            state = PromptBatchState(first_pending=pending, parts=[part])
            self._pending[key] = state
        else:
            state.parts.append(part)

        if len(state.parts) >= self._max_messages or self._char_count(state) >= self._max_chars:
            self._task_group.start_soon(self._flush, key, state)
            return True

        self._reschedule(key, state)
        return True
```

Flush must preserve metadata from the first message:

```python
async def _flush(self, key: PromptBatchKey, state: PromptBatchState) -> None:
    if self._pending.get(key) is not state:
        return
    self._pending.pop(key, None)
    first = state.first_pending
    assembled = join_prompt_parts(state.parts, separator=self._separator)
    await self._dispatch(
        _PendingPrompt(
            msg=first.msg,
            text=assembled,
            ambient_context=first.ambient_context,
            chat_project=first.chat_project,
            topic_key=first.topic_key,
            chat_session_key=first.chat_session_key,
            reply_ref=first.reply_ref,
            reply_id=first.reply_id,
            is_voice_transcribed=first.is_voice_transcribed,
            forwards=first.forwards,
        )
    )
```

**Step 4: Run**

```powershell
python -m pytest tests/test_telegram_prompt_batch.py -q
```

---

## Task 4: Integrate With `route_message()`

**Files:**

- Modify: `src/takopi/telegram/loop.py`
- Test: `tests/test_telegram_bridge.py`

**Step 1: Add loop state**

```python
@dataclass(slots=True)
class TelegramLoopState:
    ...
    prompt_batches: dict[PromptBatchKey, PromptBatchState]
    prompt_batch_enabled: bool
    prompt_batch_debounce_s: float
    prompt_batch_max_messages: int
    prompt_batch_max_chars: int
    prompt_batch_separator: PromptBatchSeparator
```

Initialize from `cfg`:

```python
prompt_batches={},
prompt_batch_enabled=bool(cfg.prompt_batch_enabled),
prompt_batch_debounce_s=max(0.0, float(cfg.prompt_batch_debounce_s)),
prompt_batch_max_messages=max(2, int(cfg.prompt_batch_max_messages)),
prompt_batch_max_chars=max(4096, int(cfg.prompt_batch_max_chars)),
prompt_batch_separator=cfg.prompt_batch_separator,
```

**Step 2: Instantiate batcher**

Create after `_dispatch_pending_prompt()` is defined:

```python
prompt_batcher = PromptInputBatcher(
    task_group=tg,
    debounce_s=(
        state.prompt_batch_debounce_s if state.prompt_batch_enabled else 0.0
    ),
    sleep=sleep,
    dispatch=_dispatch_pending_prompt,
    pending=state.prompt_batches,
    max_messages=state.prompt_batch_max_messages,
    max_chars=state.prompt_batch_max_chars,
    separator=state.prompt_batch_separator,
)
```

**Step 3: Insert scheduling at the correct point**

In `route_message()`, keep the first guards as they are:

```python
if classification.is_forward_candidate:
    forward_coalescer.attach_forward(msg)
    return
if classification.is_media_group_document:
    media_group_buffer.add(msg)
    return
```

Build context. Then handle cancel/new safely:

```python
batch_key = prompt_batcher.key_for_message(msg)

if classification.is_cancel:
    prompt_batcher.cancel(batch_key)
    tg.start_soon(handle_cancel, cfg, msg, state.running_tasks, scheduler)
    return

if command_id == "new":
    prompt_batcher.cancel(batch_key)
    forward_coalescer.cancel(forward_key)
    ...
```

Then schedule batchable text before built-in/plugin command dispatch:

```python
pending = _PendingPrompt(
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

if prompt_batcher.schedule(pending):
    return
```

Continue existing built-in, trigger, voice, document, plugin-command, and prompt fallback flow for non-batchable messages.

Why before built-ins/plugins:

- `/codex part one` followed by `part two` must resolve `/codex` after joining.
- `/plan long...` and `/goal long...` must resolve after joining.
- plugin commands with long argument bodies can batch if they are not reserved control commands.

Why after forward/media guards:

- forwarded-only messages already attach through `ForwardCoalescer`;
- media groups are not text prompts and must stay in `MediaGroupBuffer`.

**Step 4: Run**

```powershell
python -m pytest tests/test_telegram_bridge.py -k "prompt_batch or forward or media_group or trigger" -q
```

---

## Task 5: All Regimes And Workflow Tests

**Files:**

- Modify: `tests/test_telegram_bridge.py`
- Test helper updates as needed.

Use small values in tests:

```python
FAST_PROMPT_BATCH_S = 0.02
```

### Plain Prompt Workflow

```python
@pytest.mark.anyio
async def test_prompt_batch_plain_text_runs_once() -> None:
    runner = ScriptRunner([Return(answer="ok")], engine=CODEX_ENGINE)
    cfg = make_cfg(
        FakeTransport(),
        runner=runner,
        prompt_batch_enabled=True,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
        forward_coalesce_s=0.0,
    )

    async def poller(_cfg):
        yield _msg(1, "first part")
        yield _msg(2, "second part")

    await run_main_loop(cfg, poller)

    assert len(runner.calls) == 1
    assert runner.calls[0][0] == "first part\n\nsecond part"
```

### Engine Directive Workflow

```python
@pytest.mark.anyio
async def test_prompt_batch_engine_directive_resolves_after_joining() -> None:
    codex_runner = ScriptRunner([Return(answer="codex")], engine="codex")
    claude_runner = ScriptRunner([Return(answer="claude")], engine="claude")
    cfg = make_multi_runner_cfg(
        [codex_runner, claude_runner],
        default_engine="claude",
        prompt_batch_enabled=True,
        prompt_batch_debounce_s=FAST_PROMPT_BATCH_S,
    )

    async def poller(_cfg):
        yield _msg(1, "/codex summarize")
        yield _msg(2, "the pasted content")

    await run_main_loop(cfg, poller)

    assert codex_runner.calls[0][0] == "summarize\n\nthe pasted content"
    assert not claude_runner.calls
```

### Plan And Goal Workflows

Cover:

- `/plan build API` + `more details` becomes one plan-mode prompt.
- bare `/plan` remains a sticky command and does not batch.
- `/goal all tests pass` + `also lint` becomes one goal-mode prompt.
- bare `/goal` remains help and does not batch.

### Plugin Command Workflow

Use an existing fake command backend pattern:

```python
@pytest.mark.anyio
async def test_prompt_batch_plugin_command_arguments() -> None:
    class EchoCommand:
        id = "echo"
        description = "echo"

        async def handle(self, ctx):
            return CommandResult(text=f"echo:{ctx.args_text}")

    ...
    yield _msg(1, "/echo first")
    yield _msg(2, "second")
    ...
    assert "echo:first\n\nsecond" in transport.last_message.text
```

### Stateless Reply Workflow

Reply all chunks to the same bot final/progress message:

```python
yield _msg(1, "continue with", reply_to_message_id=99, reply_to_text="done\n`codex resume sid`")
yield _msg(2, "these details", reply_to_message_id=99, reply_to_text="done\n`codex resume sid`")
```

Expected:

- one runner call;
- prompt text joined;
- resume token is `codex:sid`.

### Chat Session Workflow

With `session_mode="chat"`:

- seed chat session resume;
- send two quick messages without replies;
- assert one runner call and one queued/resumed prompt.

### Topic Workflow

With topics enabled:

- same topic/thread batches;
- different topic/thread does not batch;
- topic-bound context is taken from the first chunk and preserved.

### Active Run And Queue Workflow

Arrange an active run with a `Wait` gate, then send two quick messages replying to its progress message.

Expected:

- no chunk is sent directly to runner before the gate releases;
- one queued job exists for the active `ResumeToken`;
- queued job text is the joined prompt;
- after releasing the active run, queued prompt runs once.

### Trigger Mode Workflow

In `mentions` mode:

- if the first chunk triggers the bot and the second chunk does not, the assembled prompt should run once;
- if no chunk triggers the bot, nothing runs;
- if only the second chunk contains the mention, define behavior explicitly in tests.

Recommended behavior: trigger eligibility is evaluated on the assembled prompt after flush. This allows a mention in any chunk to trigger the batch.

Implementation note: because current trigger checks happen before `_PendingPrompt` creation, batching must either:

- schedule potential text batches before trigger filtering and evaluate trigger at flush time; or
- store enough raw messages and evaluate trigger across the assembled text before dispatch.

Choose the second option for clarity:

```python
PromptBatchState.parts: list[PromptBatchPart]
PromptBatchPart.raw: dict[str, object] | None
```

At flush, create a synthetic or first-message-based `TelegramIncomingMessage` with assembled text for `should_trigger_run()`, or add `should_trigger_text(...)` helper.

### Boundaries That Must Not Batch

Add tests for:

- different sender id;
- missing sender id;
- different chat id;
- different thread/topic id;
- different reply id;
- delay beyond debounce creates two prompts;
- max message count flushes immediately;
- max char count flushes immediately;
- `/cancel` cancels pending batch and runs existing cancel behavior;
- `/new` cancels pending batch and clears sessions;
- `/ctx`, `/agent`, `/model`, `/reasoning`, `/trigger`, `/queue`, `/file`, `/topic` bypass batching;
- forwarded messages still attach only through `ForwardCoalescer`;
- media albums still use `MediaGroupBuffer`;
- voice transcription still produces one transcribed prompt and does not join with surrounding text.

**Run**

```powershell
python -m pytest tests/test_telegram_bridge.py -k "batch or queue or trigger or chat_session or topic or forward or media_group or voice" -q
```

---

## Task 6: Queue Safety Audit

**Files:**

- Modify: `tests/test_telegram_bridge.py`
- Modify: `tests/test_telegram_queue.py` if needed.

**Step 1: Prove one batch equals one queued job**

```python
@pytest.mark.anyio
async def test_prompt_batch_queues_as_one_job_for_busy_resume() -> None:
    ...
    jobs = await scheduler.list_queued_for_thread(resume)
    assert len(jobs) == 1
    assert jobs[0].text == "first\n\nsecond"
```

**Step 2: Prove FIFO ordering with surrounding jobs**

Scenario:

1. Active run holds `ResumeToken("codex", "sid")`.
2. User sends quick chunks A1/A2.
3. User sends a separate prompt B after debounce.
4. Release active run.

Expected execution:

```text
active run
batched A prompt
B prompt
```

**Step 3: Prove different resume tokens run independently**

Two chats/topics or explicit reply targets should not block each other beyond existing scheduler behavior.

**Step 4: Run**

```powershell
python -m pytest tests/test_telegram_bridge.py -k "prompt_batch_queues or fifo" -q
```

---

## Task 7: Docs

**Files:**

- Modify: `docs/reference/config.md`
- Modify: `docs/reference/transports/telegram.md`
- Modify: `docs/reference/commands-and-directives.md`
- Create: `docs/how-to/long-telegram-prompts.md`

**Config docs**

Add rows under `[transports.telegram]`:

```markdown
| `prompt_batch_enabled` | bool | `true` | Combine qualifying consecutive text messages into one prompt. |
| `prompt_batch_debounce_s` | float | `0.75` | Quiet window for collecting prompt chunks. Set `0` to disable. |
| `prompt_batch_max_messages` | int | `8` | Maximum chunks in one prompt batch before immediate flush. |
| `prompt_batch_max_chars` | int | `120000` | Maximum assembled prompt size before immediate flush. |
| `prompt_batch_separator` | `"newline"`\|`"blank_line"` | `"blank_line"` | Separator inserted between text chunks. |
```

**Transport docs**

Add a section:

```markdown
## Long user input across several messages

When users send several text messages within `prompt_batch_debounce_s`, Takopi
can treat them as one prompt. The messages must come from the same sender, chat,
topic/thread, and reply target. The assembled prompt then uses the normal
directive parsing, trigger checks, session resume, and queue behavior.

This is independent from `/compact`; it applies to all prompt workflows.
```

**How-to**

Document examples:

```text
/codex refactor this module
Preserve public API.
Add tests before code.
```

```text
Explain this stack trace:
<part 1>
<part 2>
```

Mention that control commands and files are not batched.

---

## Final Verification

Focused tests:

```powershell
Set-Location -LiteralPath D:\Projects\takopi
$env:PYTHONUTF8 = '1'
python -m pytest tests/test_telegram_prompt_batch.py -q
python -m pytest tests/test_telegram_bridge.py -k "batch or queue or trigger or chat_session or topic or forward or media_group or voice" -q
python -m pytest tests/test_settings.py tests/test_settings_contract.py tests/test_telegram_backend.py -q
```

Regression tests:

```powershell
python -m pytest tests/test_telegram_bridge.py tests/test_transport_runtime.py tests/test_telegram_queue.py -q
python -m pytest -q
ruff check .
python -m py_compile src/takopi/telegram/prompt_batch.py src/takopi/telegram/loop.py src/takopi/settings.py src/takopi/telegram/bridge.py src/takopi/telegram/backend.py
```

Expected final state:

- several rapid qualifying Telegram text messages become one prompt;
- queue sees one job per assembled prompt;
- same `ResumeToken` serialization remains intact;
- stateless replies, chat sessions, topics, engine directives, project directives, plan/goal prompts, plugin commands, and mentions trigger mode work with assembled text;
- control commands, media, files, voice, and forwards retain existing behavior;
- compact remains a separate feature.

---

## Implementation Order With Commits

1. `test: cover telegram prompt batch decisions`
2. `feat: add prompt batch helper module`
3. `test: cover prompt batch settings`
4. `feat: wire prompt batch settings`
5. `test: cover telegram prompt batch integration`
6. `feat: add telegram prompt input batcher`
7. `test: cover prompt batch queue safety`
8. `docs: document long telegram prompt batching`

Do not commit unless the user explicitly asks for commits.

---

## Notes From Exploration

- This plan intentionally supersedes the multi-message portion of `docs/plans/2026-07-29-compact-runner-api-acp.md`. It does not supersede that file's separate `/compact` runner API plan.
- The correct downstream boundary is `_dispatch_pending_prompt()`, because directive parsing and scheduling already happen below it.
- Do not add a second queue. Assemble text first, then let `ThreadScheduler` queue the one assembled prompt.
- Keep `ForwardCoalescer` for forwarded messages. Reusing it directly would preserve the current "replace pending ordinary prompt" behavior and blur two different workflows.
