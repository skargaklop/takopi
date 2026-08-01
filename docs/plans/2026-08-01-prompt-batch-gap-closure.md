# Prompt Batch Gap Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the gaps between the claimed Telegram multi-message input implementation and the live Takopi checkout, while preserving the SIGINT/AnyIO shutdown fix.

**Architecture:** Keep prompt batching as a Telegram input assembly layer, not as `/compact` logic and not as a replacement for existing directive/session/queue dispatch. Add missing settings, bridge wiring, batcher state, command routing for assembled text, and shutdown regression coverage so rapid Telegram text chunks become one prompt without reintroducing the `CancelScope` crash.

**Tech Stack:** Python 3.14, anyio, pydantic, Takopi Telegram loop, `ThreadScheduler`, pytest, ruff, PowerShell.

**ASCII implementation sketch:**

```text
+ Pasted agent report
        |
        v
+ Live checkout verification
        |
        +--> prompt_batch.py/tests exist
        +--> runtime symbols/settings/wiring missing
        +--> shutdown fix present and must be preserved
        |
        v
+ RED tests
        |
        v
+ Settings -> Bridge config -> PromptInputBatcher -> route_message integration
        |
        v
+ Trigger/plugin/resume/queue/forward/cancel verification
        |
        v
+ Ruff + focused tests + broader regression suite
```

---

## Verified Current State

This plan is based on the live checkout at `D:\Projects\takopi`, not only the pasted report.

The report is not true for the current tree:

- `src/takopi/telegram/prompt_batch.py` exists.
- `tests/test_telegram_prompt_batch.py` exists.
- `tests/test_telegram_prompt_batch_integration.py` exists.
- `docs/how-to/long-telegram-prompts.md` exists.
- `PromptInputBatcher`, `PromptBatchKey`, and `PromptBatchState` do not exist in `src/takopi/telegram/loop.py`.
- `prompt_batch_enabled`, `prompt_batch_debounce_s`, `prompt_batch_max_messages`, `prompt_batch_max_chars`, and `prompt_batch_separator` do not exist in `src/takopi/settings.py`.
- `TelegramBridgeConfig` has no prompt-batch fields in `src/takopi/telegram/bridge.py`.
- `tests/telegram_fakes.py` has `make_cfg()` but no `make_multi_runner_cfg()`.
- Runtime routing still sends normal prompts to `ForwardCoalescer.schedule()` at `src/takopi/telegram/loop.py:2112`.
- Focused prompt-batch tests fail during collection, so the claimed `42 prompt-batch tests` are not currently passing.

Observed RED command:

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch.py' `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch_integration.py' `
  -q
```

Observed failures:

```text
ImportError: cannot import name 'PromptInputBatcher' from 'takopi.telegram.loop'
ImportError: cannot import name 'make_multi_runner_cfg' from 'tests.telegram_fakes'
```

Shutdown fix state:

- `_run_loop_with_sigint()` exists in `src/takopi/telegram/backend.py`.
- It installs SIGINT cancellation on `task_group.cancel_scope`, not on a separately entered outer `anyio.CancelScope`.
- `tests/test_shutdown.py` passes with focused `--no-cov`.

Observed shutdown verification:

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_shutdown.py' -q --no-cov
```

Expected:

```text
4 passed
```

Important command note:

- In PowerShell, call the venv Python with `& 'D:\Projects\takopi\.venv\Scripts\python.exe'`.
- The form `.\.venv\Scripts\python.exe` was not reliable from the observed shell invocation.
- Use `--no-cov` for small focused tests. The repo-level coverage gate makes tiny focused runs fail even when the tests pass.

---

## Hard Rules

1. Do not remove or rewrite the shutdown fix in `src/takopi/telegram/backend.py`.
2. Do not add an outer `with anyio.CancelScope()` around `run_main_loop()`.
3. SIGINT must cancel the owning task group's `cancel_scope`.
4. Prompt batching must not start a new session.
5. Prompt batching must not bypass `ThreadScheduler`.
6. Prompt batching must not treat Agy handoff or `/compact` as special; this is a separate Telegram input feature.
7. All limits and timing values must be configurable in settings.
8. Tests must be written or corrected before implementation code.
9. Preserve existing dirty worktree changes unless the user explicitly approves reverting them.
10. Do not commit unless the user explicitly asks for a commit.

---

## Gap List

### Gap 1: Existing Tests Cannot Collect

`tests/test_telegram_prompt_batch.py` imports missing `PromptInputBatcher`.

`tests/test_telegram_prompt_batch_integration.py` imports missing `make_multi_runner_cfg`.

Closure condition:

```text
Both prompt-batch test files collect and execute.
```

### Gap 2: Settings Are Documented But Rejected

Docs already advertise `prompt_batch_*` settings, but `TelegramTransportSettings` forbids unknown keys.

Closure condition:

```text
Takopi accepts documented prompt_batch_* TOML keys and validates invalid values.
```

### Gap 3: Bridge Config Has No Runtime Fields

`TelegramBridgeConfig` has no way to carry prompt-batch config into `run_main_loop()`.

Closure condition:

```text
Backend settings are copied into TelegramBridgeConfig and then used by run_main_loop().
```

### Gap 4: No PromptInputBatcher Runtime

Only pure helper logic exists. There is no in-loop batching state or debounce timer.

Closure condition:

```text
Rapid eligible text messages from the same key flush as one _PendingPrompt.
```

### Gap 5: Route Order Still Dispatches Too Early

`route_message()` dispatches built-ins and plugin commands before any assembled text exists.

Closure condition:

```text
Batchable plugin commands and engine directives are parsed after joining.
Control commands still bypass batching immediately.
```

### Gap 6: Trigger Mode Must Evaluate Assembled Text

In mentions mode, message 1 may not mention the bot while message 2 does.

Closure condition:

```text
The assembled prompt triggers exactly once if the final joined text matches mentions-mode rules.
```

### Gap 7: Forward Coalescing Interaction Is Undefined

Forwarded messages currently attach only to `ForwardCoalescer.pending`, not to a future prompt batch.

Closure condition:

```text
Forward text following a pending text batch attaches to that batch without losing existing forward behavior.
```

### Gap 8: Max-Char Semantics Are Wrong In Existing Test Intent

The current integration test expects two 3000-character chunks to join under `prompt_batch_max_chars=4096`, producing more than 4096 assembled characters.

Closure condition:

```text
Max chars is enforced as an upper bound on assembled text.
When adding the next chunk would exceed the limit, flush the existing batch first and process the new chunk separately.
```

### Gap 9: Shutdown Crash Must Not Return

The prompt-batch implementation will add debounce tasks and likely stored cancellation handles.

Closure condition:

```text
No code path stores a CancelScope and later exits it from another task.
SIGINT during pending debounce shutdown exits cleanly.
```

### Gap 10: Docs Contain Encoding Defects

`src/takopi/telegram/prompt_batch.py` and `docs/how-to/long-telegram-prompts.md` contain mojibake representing a broken UTF-8 dash.

Closure condition:

```text
Replace mojibake with ASCII hyphen wording or valid UTF-8 text.
```

---

## Task 1: Stabilize The RED Test Surface

**Files:**

- Modify: `tests/test_telegram_prompt_batch.py`
- Modify: `tests/test_telegram_prompt_batch_integration.py`
- Modify: `tests/telegram_fakes.py`

**Step 1: Keep the current collection failure as the first RED proof**

Run:

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch.py' `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch_integration.py' `
  -q --no-cov
```

Expected before implementation:

```text
ImportError: cannot import name 'PromptInputBatcher'
ImportError: cannot import name 'make_multi_runner_cfg'
```

**Step 2: Fix test support only where necessary**

Add `make_multi_runner_cfg()` to `tests/telegram_fakes.py`:

```python
def make_multi_runner_cfg(
    transport: FakeTransport,
    runners: list[ScriptRunner],
    *,
    default_engine: str,
    forward_coalesce_s: float = 0.0,
    media_group_debounce_s: float = 0.0,
    prompt_batch_enabled: bool = True,
    prompt_batch_debounce_s: float = 0.75,
    prompt_batch_max_messages: int = 8,
    prompt_batch_max_chars: int = 120_000,
    prompt_batch_separator: str = "blank_line",
) -> TelegramBridgeConfig:
    exec_cfg = ExecBridgeConfig(
        transport=transport,
        presenter=MarkdownPresenter(),
        final_notify=True,
    )
    runtime = TransportRuntime(
        router=AutoRouter(
            entries=[
                RunnerEntry(engine=runner.engine, runner=runner)
                for runner in runners
            ],
            default_engine=default_engine,
        ),
        projects=_empty_projects(),
    )
    return TelegramBridgeConfig(
        bot=FakeBot(),
        runtime=runtime,
        chat_id=123,
        startup_msg="",
        exec_cfg=exec_cfg,
        forward_coalesce_s=forward_coalesce_s,
        media_group_debounce_s=media_group_debounce_s,
        prompt_batch_enabled=prompt_batch_enabled,
        prompt_batch_debounce_s=prompt_batch_debounce_s,
        prompt_batch_max_messages=prompt_batch_max_messages,
        prompt_batch_max_chars=prompt_batch_max_chars,
        prompt_batch_separator=prompt_batch_separator,
    )
```

Also extend existing `make_cfg()` with the same prompt-batch keyword arguments so the integration tests can construct configs.

**Step 3: Correct the max-char integration test before implementation**

Replace the current expectation in `test_prompt_batch_max_chars_flushes_immediately`.

The test must expect two separate calls when the second chunk would exceed the configured limit:

```python
assert [call[0] for call in runner.calls] == [big, big]
```

If a chunk alone exceeds `prompt_batch_max_chars`, it should still be dispatched alone rather than dropped.

**Step 4: Run collection again**

Expected after test-support changes and before runtime implementation:

```text
Tests collect.
Runtime behavior tests fail because PromptInputBatcher/settings/wiring are not implemented yet.
```

---

## Task 2: Add Prompt Batch Settings

**Files:**

- Modify: `src/takopi/settings.py`
- Modify: `tests/test_settings.py`

**Step 1: Add failing settings tests**

Add tests for defaults:

```python
def test_telegram_prompt_batch_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "takopi.toml"
    settings = TakopiSettings.model_validate(
        {
            "transport": "telegram",
            "transports": {
                "telegram": {"bot_token": "token", "chat_id": 123}
            },
        }
    )

    telegram = settings.transports.telegram
    assert telegram is not None
    assert telegram.prompt_batch_enabled is True
    assert telegram.prompt_batch_debounce_s == 0.75
    assert telegram.prompt_batch_max_messages == 8
    assert telegram.prompt_batch_max_chars == 120_000
    assert telegram.prompt_batch_separator == "blank_line"
```

Add validation tests:

```python
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("prompt_batch_debounce_s", -0.1),
        ("prompt_batch_max_messages", 0),
        ("prompt_batch_max_chars", 0),
        ("prompt_batch_separator", "comma"),
    ],
)
def test_telegram_prompt_batch_invalid_values(
    tmp_path: Path,
    key: str,
    value: object,
) -> None:
    data = {
        "transport": "telegram",
        "transports": {
            "telegram": {
                "bot_token": "token",
                "chat_id": 123,
                key: value,
            }
        },
    }

    with pytest.raises(ConfigError, match=key):
        validate_settings_data(data, config_path=tmp_path / "takopi.toml")
```

**Step 2: Implement settings**

Add to `TelegramTransportSettings`:

```python
    prompt_batch_enabled: bool = True
    prompt_batch_debounce_s: float = Field(default=0.75, ge=0)
    prompt_batch_max_messages: StrictInt = Field(default=8, ge=1)
    prompt_batch_max_chars: StrictInt = Field(default=120_000, ge=1)
    prompt_batch_separator: Literal["newline", "blank_line"] = "blank_line"
```

**Step 3: Run settings tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_settings.py' -q --no-cov
```

Expected:

```text
pass
```

---

## Task 3: Wire Settings Through Backend And Bridge

**Files:**

- Modify: `src/takopi/telegram/bridge.py`
- Modify: `src/takopi/telegram/backend.py`
- Modify: `tests/test_telegram_backend.py`
- Modify: `tests/test_telegram_bridge.py` if an existing bridge-config test is a better fit

**Step 1: Add failing wiring test**

Add or extend a backend config construction test so it proves TOML settings reach `TelegramBridgeConfig`:

```python
assert cfg.prompt_batch_enabled is True
assert cfg.prompt_batch_debounce_s == 0.75
assert cfg.prompt_batch_max_messages == 8
assert cfg.prompt_batch_max_chars == 120_000
assert cfg.prompt_batch_separator == "blank_line"
```

**Step 2: Add dataclass fields**

Add to `TelegramBridgeConfig`:

```python
    prompt_batch_enabled: bool = True
    prompt_batch_debounce_s: float = 0.75
    prompt_batch_max_messages: int = 8
    prompt_batch_max_chars: int = 120_000
    prompt_batch_separator: Literal["newline", "blank_line"] = "blank_line"
```

**Step 3: Copy transport settings in backend**

When constructing `TelegramBridgeConfig`, pass:

```python
prompt_batch_enabled=settings.prompt_batch_enabled,
prompt_batch_debounce_s=settings.prompt_batch_debounce_s,
prompt_batch_max_messages=settings.prompt_batch_max_messages,
prompt_batch_max_chars=settings.prompt_batch_max_chars,
prompt_batch_separator=settings.prompt_batch_separator,
```

Do not change `_run_loop_with_sigint()` except for type annotations if required.

**Step 4: Run focused tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_backend.py' `
  'D:\Projects\takopi\tests\test_telegram_bridge.py' `
  -q --no-cov
```

Expected:

```text
pass or only known unrelated baseline failures; record exact failures
```

---

## Task 4: Implement PromptInputBatcher Without Unsafe CancelScope Ownership

**Files:**

- Modify: `src/takopi/telegram/loop.py`
- Modify: `tests/test_telegram_prompt_batch.py`

**Step 1: Define key/state types**

Use a key that separates all scopes where accidental joining would be wrong:

```python
@dataclass(frozen=True, slots=True)
class PromptBatchKey:
    chat_id: int
    thread_id: int | None
    sender_id: int
    reply_id: int | None
    topic_key: tuple[int, int] | None
    chat_session_key: tuple[int, int | None] | None


@dataclass(slots=True)
class PromptBatchState:
    pending: _PendingPrompt
    parts: list[PromptBatchPart]
    token: int = 0
```

Do not reuse `ForwardKey`; it does not include reply/session/topic enough for this feature.

**Step 2: Implement `PromptInputBatcher.key_for()`**

Rules:

- return `None` when `sender_id is None`;
- return `None` for voice/document/media messages;
- return `None` when `should_batch_text()` returns false;
- include chat/thread/sender/reply/topic/session fields.

**Step 3: Implement debounce without cross-task scope exit risk**

Preferred shape: use token invalidation rather than storing externally entered cancel scopes.

```python
class PromptInputBatcher:
    def _reschedule(self, key: PromptBatchKey, state: PromptBatchState) -> None:
        state.token += 1
        token = state.token
        self._task_group.start_soon(self._debounce_flush, key, state, token)

    async def _debounce_flush(
        self,
        key: PromptBatchKey,
        state: PromptBatchState,
        token: int,
    ) -> None:
        await self._sleep(self._debounce_s)
        current = self._pending.get(key)
        if current is not state or current.token != token:
            return
        await self.flush(key)
```

This avoids storing a `CancelScope` in a shared object and calling it from a different task.

**Step 4: Implement `schedule()`**

Behavior:

- if disabled or not batchable, return `False`;
- if no existing state, create one and start debounce;
- if existing state and adding next part would exceed max chars, flush existing first and schedule current as a new batch;
- if max messages is reached, flush immediately;
- return `True` when the caller should not continue normal immediate dispatch.

Max-char helper:

```python
def _joined_len(parts: list[PromptBatchPart], separator: str) -> int:
    sep_len = 1 if separator == "newline" else 2
    return sum(len(part.text) for part in parts) + sep_len * max(0, len(parts) - 1)
```

Important:

- Max chars is an assembled prompt upper bound.
- Do not join a second chunk if the joined text would exceed `max_chars`.
- If one single message exceeds `max_chars`, allow it as one prompt.

**Step 5: Implement `flush()` and `cancel()`**

`flush()` must:

- remove the state from the pending map;
- join parts in message-id order;
- update `pending.text`;
- use the first message as `pending.msg`;
- preserve context fields from the first pending message;
- append forwards if attached;
- call `dispatch(pending)`.

`cancel()` must:

- remove pending state for a key;
- invalidate token;
- not touch another task's active `CancelScope`.

**Step 6: Run unit tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch.py' -q --no-cov
```

Expected:

```text
pass
```

---

## Task 5: Integrate Batcher Into `run_main_loop()`

**Files:**

- Modify: `src/takopi/telegram/loop.py`
- Modify: `tests/test_telegram_prompt_batch_integration.py`

**Step 1: Add state storage**

Extend `TelegramLoopState`:

```python
    prompt_batches: dict[PromptBatchKey, PromptBatchState]
```

Initialize it in `run_main_loop()`:

```python
prompt_batches={},
```

**Step 2: Create `_dispatch_registered_command()`**

After batching, plugin commands need the assembled text and assembled args.

Add a helper near `_dispatch_pending_prompt()`:

```python
async def _dispatch_registered_command(
    pending: _PendingPrompt,
    *,
    command_id: str,
    args_text: str,
) -> None:
    msg = pending.msg
    chat_id = pending.msg.chat_id
    overrides_thread_id = (
        pending.topic_key[1] if pending.topic_key is not None else None
    )
    engine_resolution = await resolve_engine_defaults(
        explicit_engine=None,
        context=pending.ambient_context,
        chat_id=chat_id,
        topic_key=pending.topic_key,
    )
    default_engine_override = (
        engine_resolution.engine
        if engine_resolution.source in {"directive", "topic_default", "chat_default"}
        else None
    )
    engine_overrides_resolver = partial(
        _resolve_engine_run_options,
        chat_id,
        overrides_thread_id,
        chat_prefs=state.chat_prefs,
        topic_store=state.topic_store,
    )
    await dispatch_command(
        cfg,
        msg,
        pending.text,
        command_id,
        args_text,
        state.running_tasks,
        scheduler,
        wrap_on_thread_known(
            scheduler.note_thread_known,
            pending.topic_key,
            pending.chat_session_key,
        ),
        pending.chat_session_key is not None or pending.topic_key is not None,
        default_engine_override,
        engine_overrides_resolver,
    )
```

If exact `stateful_mode` cannot be reconstructed this way, store it on `_PendingPrompt`.

**Step 3: Add `_dispatch_batched_prompt()`**

This helper receives the assembled `_PendingPrompt` and then performs command/trigger decisions on the assembled text:

```python
async def _dispatch_batched_prompt(pending: _PendingPrompt) -> None:
    command_id, args_text = parse_slash_command(pending.text)
    if command_id is not None and command_id not in state.reserved_commands:
        if command_id not in state.command_ids:
            refresh_commands()
        if command_id in state.command_ids:
            await _dispatch_registered_command(
                pending,
                command_id=command_id,
                args_text=args_text,
            )
            return

    trigger_mode = await resolve_trigger_mode(
        chat_id=pending.msg.chat_id,
        thread_id=pending.msg.thread_id,
        chat_prefs=state.chat_prefs,
        topic_store=state.topic_store,
    )
    if trigger_mode == "mentions" and not should_trigger_run(
        pending.msg,
        bot_username=state.bot_username,
        runtime=cfg.runtime,
        command_ids=state.command_ids,
        reserved_chat_commands=state.reserved_chat_commands,
        text_override=pending.text,
    ):
        return

    await _dispatch_pending_prompt(pending)
```

This requires Task 6's `text_override` change.

**Step 4: Instantiate `PromptInputBatcher`**

Create it next to `ForwardCoalescer`:

```python
prompt_batcher = PromptInputBatcher(
    task_group=tg,
    debounce_s=cfg.prompt_batch_debounce_s if cfg.prompt_batch_enabled else 0.0,
    sleep=sleep,
    dispatch=_dispatch_batched_prompt,
    pending=state.prompt_batches,
    max_messages=cfg.prompt_batch_max_messages,
    max_chars=cfg.prompt_batch_max_chars,
    separator=cfg.prompt_batch_separator,
)
```

**Step 5: Use it from `route_message()`**

The safe order:

1. handle forwarded/media/cancel/control commands immediately;
2. build context;
3. handle `/new` and other built-ins immediately;
4. handle voice/doc paths immediately;
5. create `_PendingPrompt`;
6. if reply target is an active running task, decide whether batching is enabled for that reply key; do not bypass batching just because the target is busy;
7. call `prompt_batcher.schedule(pending)`;
8. if it returns false, use existing `ForwardCoalescer.schedule(pending)`.

Control commands must cancel pending batches for the same key where applicable:

```python
if classification.is_cancel:
    prompt_batcher.cancel_by_message(msg, ctx)
    ...

if command_id == "new":
    prompt_batcher.cancel_by_message(msg, ctx)
    ...
```

If implementing `cancel_by_message()` adds too much complexity, compute the key from a synthetic pending and call `cancel(key)`.

**Step 6: Run integration tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch_integration.py' `
  -q --no-cov
```

Expected:

```text
pass
```

---

## Task 6: Add `text_override` To Trigger Checks

**Files:**

- Modify: `src/takopi/telegram/trigger_mode.py`
- Modify: `tests/test_telegram_trigger_mode.py`

**Step 1: Add failing test**

```python
def test_should_trigger_run_uses_text_override_for_mentions() -> None:
    msg = TelegramIncomingMessage(
        transport="telegram",
        chat_id=123,
        message_id=1,
        text="first chunk",
    )

    assert should_trigger_run(
        msg,
        bot_username="bot",
        runtime=runtime,
        command_ids=set(),
        reserved_chat_commands=set(),
        text_override="first chunk\n\nhello @bot",
    )
```

Use existing fixtures in `tests/test_telegram_trigger_mode.py` for `runtime`.

**Step 2: Implement narrow signature change**

```python
def should_trigger_run(
    msg: TelegramIncomingMessage,
    *,
    bot_username: str | None,
    runtime: TransportRuntime,
    command_ids: set[str],
    reserved_chat_commands: set[str],
    text_override: str | None = None,
) -> bool:
    text = text_override if text_override is not None else (msg.text or "")
```

Existing callers need no changes except `_dispatch_batched_prompt()`.

**Step 3: Run trigger tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_trigger_mode.py' -q --no-cov
```

Expected:

```text
pass
```

---

## Task 7: Preserve Forward Coalescing And Add Batch Attachment

**Files:**

- Modify: `src/takopi/telegram/loop.py`
- Modify: `tests/test_telegram_prompt_batch_integration.py`

**Step 1: Keep existing forward behavior green**

Before editing forward behavior, run:

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_bridge.py' -q --no-cov
```

Record any pre-existing failures.

**Step 2: Attach forwarded messages to pending prompt batches**

Add to `PromptInputBatcher`:

```python
def attach_forward(self, msg: TelegramIncomingMessage) -> bool:
    if msg.sender_id is None:
        return False
    for key, state in list(self._pending.items()):
        if (
            key.chat_id == msg.chat_id
            and key.thread_id == msg.thread_id
            and key.sender_id == msg.sender_id
        ):
            text = msg.text
            if text.strip():
                state.pending.forwards.append((msg.message_id, text))
                self._reschedule(key, state)
                return True
    return False
```

Keep this narrow. Do not attach forwards across reply targets or topics if that creates ambiguity.

**Step 3: Update `route_message()` forward branch**

```python
if classification.is_forward_candidate:
    if prompt_batcher.attach_forward(msg):
        return
    forward_coalescer.attach_forward(msg)
    return
```

**Step 4: Run forward-related tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch_integration.py::test_prompt_batch_forwarded_messages_attach_to_batch' `
  'D:\Projects\takopi\tests\test_telegram_bridge.py' `
  -q --no-cov
```

Expected:

```text
pass or only known unrelated baseline failures; record exact failures
```

---

## Task 8: Add Shutdown Regression For Pending Batch Debounce

**Files:**

- Modify: `tests/test_shutdown.py`
- Possibly modify: `src/takopi/telegram/backend.py` only if the existing fix is broken

**Step 1: Add a regression test that fails if an outer CancelScope returns**

The existing test covers SIGINT cancellation of `_run_loop_with_sigint()`. Add a batching-specific variant after `PromptInputBatcher` exists:

```python
@pytest.mark.anyio
async def test_sigint_with_pending_prompt_batch_does_not_corrupt_cancel_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_main_loop(*_args: object, **_kwargs: object) -> None:
        async with anyio.create_task_group() as tg:
            async def sleeper() -> None:
                await anyio.sleep_forever()

            tg.start_soon(sleeper)
            handler = signal.getsignal(signal.SIGINT)
            assert callable(handler)
            handler(signal.SIGINT, None)
            await anyio.sleep_forever()

    monkeypatch.setattr("takopi.telegram.backend.run_main_loop", fake_run_main_loop)

    await _run_loop_with_sigint(
        object(),
        watch_config=None,
        default_engine_override=None,
        transport_id="telegram",
        transport_config=None,
    )
```

If a real prompt-batch integration shutdown test is feasible, prefer it over this synthetic child-task test.

**Step 2: Static review guard**

Run:

```powershell
Select-String -LiteralPath 'D:\Projects\takopi\src\takopi\telegram\backend.py' `
  -Pattern 'with anyio.CancelScope'
```

Expected:

```text
No outer CancelScope wrapping run_main_loop.
```

It is acceptable for other modules to use task-local `CancelScope`, but shared stored scopes must be reviewed carefully.

**Step 3: Run shutdown tests**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_shutdown.py' -q --no-cov
```

Expected:

```text
pass
```

---

## Task 9: Fix Encoding/Mojibake And Align Docs With Runtime

**Files:**

- Modify: `src/takopi/telegram/prompt_batch.py`
- Modify: `docs/how-to/long-telegram-prompts.md`
- Modify: `docs/reference/config.md`
- Modify: `docs/reference/transports/telegram.md`
- Modify: `docs/reference/commands-and-directives.md`

**Step 1: Add or run an encoding scan**

```powershell
Select-String -Path `
  'D:\Projects\takopi\src\takopi\telegram\prompt_batch.py',`
  'D:\Projects\takopi\docs\how-to\long-telegram-prompts.md' `
  -Pattern '\u0432\u0402|\uFFFD'
```

Expected before fix:

```text
matches found
```

**Step 2: Replace mojibake with ASCII**

Prefer ASCII wording:

```text
queueing - the existing dispatcher handles those on the assembled prompt
```

**Step 3: Align docs with actual max-char semantics**

Docs must say:

```text
If adding the next message would exceed prompt_batch_max_chars, Takopi flushes the current batch first and starts a new prompt batch with the new message.
```

Do not document "joins beyond max chars".

**Step 4: Run docs/source grep**

```powershell
Select-String -Path 'D:\Projects\takopi\src\**\*','D:\Projects\takopi\docs\**\*' `
  -Pattern '\u0432\u0402|\uFFFD'
```

Expected:

```text
No prompt-batch-related mojibake remains.
```

---

## Task 10: Final Verification

**Files:**

- No new implementation files unless previous tasks require them.

**Step 1: Run prompt-batch focused suite**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch.py' `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch_integration.py' `
  -q --no-cov
```

Expected:

```text
42 passed
```

If the number changes because tests were corrected, report the exact count and why.

**Step 2: Run focused regression suite**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest `
  'D:\Projects\takopi\tests\test_shutdown.py' `
  'D:\Projects\takopi\tests\test_settings.py' `
  'D:\Projects\takopi\tests\test_telegram_backend.py' `
  'D:\Projects\takopi\tests\test_telegram_bridge.py' `
  'D:\Projects\takopi\tests\test_transport_runtime.py' `
  -q --no-cov
```

Expected:

```text
pass or exact known unrelated failures listed
```

**Step 3: Run ruff**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m ruff check `
  'D:\Projects\takopi\src\takopi\telegram\backend.py' `
  'D:\Projects\takopi\src\takopi\telegram\bridge.py' `
  'D:\Projects\takopi\src\takopi\telegram\loop.py' `
  'D:\Projects\takopi\src\takopi\telegram\prompt_batch.py' `
  'D:\Projects\takopi\src\takopi\telegram\trigger_mode.py' `
  'D:\Projects\takopi\src\takopi\settings.py' `
  'D:\Projects\takopi\tests\test_shutdown.py' `
  'D:\Projects\takopi\tests\test_settings.py' `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch.py' `
  'D:\Projects\takopi\tests\test_telegram_prompt_batch_integration.py' `
  'D:\Projects\takopi\tests\telegram_fakes.py'
```

Expected:

```text
All checks passed!
```

**Step 4: Run full suite**

```powershell
$env:PYTHONUTF8='1'
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -m pytest
```

Expected:

```text
No new failures.
If Windows baseline failures remain, compare against a clean baseline and list exact failed tests.
```

**Step 5: Verify source imported by installed UV tool**

```powershell
$env:PYTHONUTF8='1'
takopi --version
& 'D:\Projects\takopi\.venv\Scripts\python.exe' -c "import takopi, pathlib; print(pathlib.Path(takopi.__file__).resolve())"
```

Expected:

```text
Takopi imports from D:\Projects\takopi\src\takopi
```

Restart the running Takopi process after code changes; an already running process will not reload Python modules automatically.

---

## Implementation Order

1. Protect the shutdown fix first by keeping `tests/test_shutdown.py` green.
2. Fix test support and max-char test semantics.
3. Add settings and bridge/backend wiring.
4. Implement `PromptInputBatcher` as a pure runtime component with token invalidation, not shared outer `CancelScope` ownership.
5. Integrate route-message dispatch after assembled text.
6. Add trigger text override.
7. Restore forward interaction.
8. Fix docs and mojibake.
9. Run focused and broad verification.

This order prevents the earlier agent from repeating the crash fix regression: batching is introduced only after the shutdown invariant is already covered, and the batcher design avoids externally entered cancel scopes.

---

## Acceptance Criteria

- Prompt-batch tests collect and pass.
- `prompt_batch_*` settings are accepted by `TelegramTransportSettings`.
- Docs no longer advertise settings rejected by config validation.
- Rapid text chunks from the same sender/chat/topic/reply target become one prompt.
- Different sender/chat/topic/reply target does not batch.
- Control commands, voice, documents, and media albums bypass batching.
- Plugin commands with long arguments dispatch once using assembled args.
- Engine directives are resolved after joining.
- Mentions trigger mode evaluates assembled text.
- Replies to busy active sessions enqueue as one job.
- Existing `ForwardCoalescer` behavior is preserved.
- `prompt_batch_max_chars` is an actual assembled-text upper bound.
- SIGINT during Telegram loop shutdown does not raise `RuntimeError: Attempted to exit a cancel scope that isn't the current tasks's current cancel scope`.
- Ruff passes on touched Python files.
- Full suite has no new failures beyond verified pre-existing Windows baseline failures.

---

## Subagent Findings And Pitfalls

Read-only subagent `019fbb83-80db-7ff3-8b5e-91bf6ab0e3f1` independently confirmed:

- helper/tests exist but runtime implementation is missing;
- settings and bridge wiring are missing;
- no batcher is integrated into `route_message()`;
- integration support lacks `make_multi_runner_cfg()`;
- documented settings are currently rejected by strict pydantic config;
- prompt-batch docs/source contain mojibake;
- shutdown fix exists and must keep using the task group's own cancellation scope.

Pitfalls reported:

- Shell working directory handling was unreliable, so use explicit absolute paths or `Set-Location -LiteralPath`.
- Bare Python import was unreliable; use the project venv or `uv run`.
- Pytest cache warnings on Windows are present and should not be confused with prompt-batch failures.
- The checkout is dirty, so preserve user/agent changes and avoid broad rewrites.
