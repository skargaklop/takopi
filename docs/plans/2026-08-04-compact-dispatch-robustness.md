# Compact Dispatch Robustness Implementation Plan

> Task 1 of ROADMAP.md: Robust `/compact` Command Dispatch.
> Confirmed design decision (user, 2026-08-04): for engines with
> `CompactSupport.mode == "none"`, the confirmed fallback prompt sent through
> the normal `run()` path is the plain-English `handoff_prompt(instructions)`
> builder from `src/takopi/compact.py` (same builder as agy `handoff_only`),
> sent only after explicit inline-button confirmation.

**Goal:** Make `/compact` resolve correctly from any reply context and in any
position relative to other slash commands, and add a notify -> confirm ->
plain-text fallback flow for engines without native compaction.

**Architecture:** Single compact entry point in `route_message` driven by a pure
parser (`parse_compact_invocation`); session resolution reuses the normal prompt
path reply-footer extraction (`TransportRuntime.extract_resume`) and
`ResumeResolver` with a compact mode; confirmation reuses the existing
inline-keyboard + callback-query infrastructure (`takopi:cancel`/`takopi:steer`
pattern). Compact jobs keep flowing through `ThreadScheduler`
(`ThreadJob.kind`), preserving per-thread FIFO serialization.

**Tech Stack:** Python 3.13, anyio, pytest, ruff, ty, uv.

**ASCII sketch:**

```text
Telegram message (any order): /compact [/engine] [instructions...]
        |
        v
route_message
  parse_compact_invocation(text, engine_ids)  (pure, leading slash tokens only)
        | None -> normal dispatch; invocation -> compact path (batch canceled)
        v
telegram/commands/compact.py::handle_compact_command
  engine precedence: explicit selector > reply-footer token > chat/topic default
  token precedence: running-task token (awaited) > reply footer > topic store
                    > chat store
        |
        +-- support.mode == "none" --> confirmation [send anyway][cancel]
        |      confirm -> enqueue kind="prompt" job, handoff_prompt(instructions)
        |      decline -> no-op, buttons cleared
        v
scheduler.enqueue(ThreadJob(kind="compact"))  (serializes behind active run)
        v
runner.compact(resume_token, instructions)    (errors surfaced to user)
```

---

## Current-State Findings (evidence)

Message flow today (`src/takopi/telegram/loop.py`):
`route_message` -> `_classify_message` (`parse_slash_command`, line 659) ->
`PromptInputBatcher.schedule` (line 2407) -> `_dispatch_builtin_command`
(line 2409; compact branch line 526) -> `_handle_compact_command` (line 246) ->
`ResumeResolver.resolve` (line 1158) -> `ThreadJob(kind="compact")` ->
`run_compact_job` (line 1762).

### Req 1 - reply-context routing broken in three ways (lines 246-323)

1. `engine = cfg.runtime.resolve_engine(engine_override=None, context=None)`
   (line 264): always the global default engine; chat/topic defaults and the
   replied session engine are ignored.
2. `reply_resume=None` hardcoded (line 278): the replied-to message resume-line
   footer (e.g. `` `claude resume xyz` ``) is never extracted. The normal prompt
   path gets it via `resolve_message` -> `router.extract_resume`
   (`transport_runtime.py:213`); `ResumeResolver` Priority 3 (line 1218) is dead
   for compact.
3. Replying `/compact` to an ACTIVE run progress message hits Priority 2
   (line 1199) -> `send_with_resume(prompt_text="")`: enqueues an EMPTY prompt
   into the running session instead of compacting.

### Req 2 - ordering (`parse.py:12` parses only the FIRST slash token)

- `/compact /codex` -> `command_id="compact"`, `args_text="/codex"` ->
  `"/codex"` becomes compact instructions.
- `/codex /compact` -> `command_id="codex"` -> normal codex run with prompt
  `"/compact"`; the scheduler compact path, instructions normalization, and
  per-runner compact modes (opencode `native_api`, agy `handoff_only`, mock
  `none`) never engage.

### Req 3 - mode="none" (line 298)

Flat refusal, no notify/confirm/passthrough flow.

### Gap A (batching)

`"compact"` missing from `CONTROL_COMMANDS` (`prompt_batch.py:21`).
`/compact <instructions>` is batchable (line 70) and `prompt_batcher.schedule`
runs BEFORE builtin dispatch (`loop.py:2407`) -> with debounce > 0 the command
is swallowed into a prompt batch and never compacts.

### Gap B (silent failures)

`run_compact_job` (line 1762) discards all events; exceptions are logged by the
scheduler but never shown to the user.

### Reusable infrastructure

- Inline keyboards + callback routing: `bridge.py:42`
  (`takopi:cancel`/`takopi:steer`), explicit branches in `route_update`
  (line 2611); `cancel.py` handler pattern.
- `_wait_for_resume` awaits a running task token; scheduler `_busy_until`
  serializes jobs per thread key, so a compact job waits behind an active run.
- Test fakes: `tests/telegram_fakes.py` (`make_cfg`, `make_multi_runner_cfg`,
  `FakeTransport`, `FakeBot`); `MockRunner` declares `COMPACT_NONE`;
  `ScriptRunner` records calls.
- GRACE is not adopted in `src/` (no markers) - no GRACE artifacts to update.

---

## Tasks (TDD: tests first)

### Task 1 - Failing tests (RED)

New `tests/test_telegram_compact_dispatch.py` (loop-level, via fakes):

1. `/compact` replying to a FINAL message with footer `` `claude resume xyz` ``
   (claude non-default) -> `compact()` on the claude runner with token `xyz`;
   default engine untouched.
2. `/compact` replying to an ACTIVE run progress message -> no empty-prompt job;
   compact runs only after the active run finishes (proves scheduler
   serialization).
3. `/codex /compact` AND `/compact /codex` (reply context) -> both produce a
   compact job on the codex session.
4. `/compact keep tests` with prompt_batch debounce > 0 -> compact dispatches;
   no batched prompt run.
5. none-support engine -> confirmation message carries `inline_keyboard`;
   confirm callback enqueues a `kind="prompt"` job whose text equals
   `handoff_prompt(instructions)` (import the builder; do not hardcode the
   string); decline -> no job, buttons cleared.
6. Instructions-warning path preserved (codex `accepts_instructions=False` ->
   warning + `instructions=None`).
7. No-session `/compact` -> guidance reply (regression guard).

Test double: `CompactableScriptRunner(ScriptRunner)` overriding
`compact_support()`/`compact()` and recording compact calls; none-case via
`MockRunner`.

Extend `tests/test_telegram_compact_command.py` with the parser unit matrix:

- None cases: `""`, `"hello"`, `"/codex fix bug"`, `"/new"`,
  `"keep /compact"` (non-leading).
- `"/compact"` -> `(None, None)`; `"/compact@mybot"` -> `(None, None)`.
- `"/compact keep tests"` -> `(None, "keep tests")`.
- `"/compact /codex"` -> `("codex", None)`;
  `"/compact /codex keep tests"` -> `("codex", "keep tests")`.
- `"/codex /compact"` -> `("codex", None)`;
  `"/codex /compact keep tests"` -> `("codex", "keep tests")`.
- `"/codex@mybot /compact"` -> `("codex", None)`.
- `"/compact /plan"` -> `(None, "/plan")` (unknown slash token stops scanning;
  becomes instructions).
- `"/codex /claude /compact"` -> raises (multiple engine selectors).
- Multiline: `"/compact\nkeep tests"` -> `(None, "keep tests")`;
  `"/codex /compact\nline1\nline2"` -> `("codex", "line1\nline2")`.

Extend `tests/test_telegram_prompt_batch.py`: `compact` is a control command
(never batches).

### Task 2 - Parser + batching fix (GREEN, unit level)

`src/takopi/telegram/commands/parse.py`:

- Add frozen dataclass
  `CompactInvocation(engine: EngineId | None, instructions: str | None)`.
- Add `parse_compact_invocation(text, *, engine_ids) -> CompactInvocation | None`.
  Scan LEADING slash tokens only (mirror `parse_directives`
  first-non-empty-line handling for multi-line); strip `@bot` suffixes; collect
  the compact flag plus at most one engine id (second engine -> `ValueError`,
  mirroring `parse_directives` "multiple engine directives"); first non-slash or
  unknown slash token stops scanning; remainder (with following lines rebuilt) =
  instructions, normalized via `compact.normalize_instructions`; compact flag
  absent -> `None`.

`src/takopi/telegram/prompt_batch.py`: add `"compact"` to `CONTROL_COMMANDS`
(defense-in-depth).

### Task 3 - Dispatch rework

New `src/takopi/telegram/commands/compact.py` (SRP; `loop.py` is ~2700 lines and
per-command modules are the established pattern). Move `_handle_compact_command`
there, extended:

- Reply-footer token via a new public passthrough
  `TransportRuntime.extract_resume(text)` (3 lines; avoids `resolve_message`
  `DirectiveError` surface on bogus `ctx:` lines in replied messages).
- Engine precedence: explicit selector > matching reply-footer token >
  chat/topic-aware default via `resolve_engine_defaults` (replaces the
  global-default-only lookup). Selector present but footer engine mismatches ->
  ignore the footer token, fall back to the stored session for the selected
  engine.
- Pass `reply_resume` into `ResumeResolver.resolve`.

`ResumeResolver.resolve(..., for_compact: bool = False)`: under the flag,
Priority 2 awaits `_wait_for_resume(running_task)` and RETURNS the token (the
compact job serializes behind the active run via `_busy_until`) instead of
enqueueing an empty prompt; token not ready -> return `None` and the caller
replies with guidance. Mode flag chosen over a separate method to avoid
duplicating the P3-P5 chain (documented tradeoff).

`loop.py` `route_message`: immediately after `build_message_context` and cancel
handling:
`invocation = parse_compact_invocation(text, engine_ids=cfg.runtime.engine_ids)`;
if non-`None`: `prompt_batcher.cancel(key)` (mirrors `/new`),
`tg.start_soon(compact handler)`, `return`. Single entry point covering both
orderings; runs before the trigger-mode gate exactly like the current compact
branch.

Remove the now-dead `compact` branch in `_dispatch_builtin_command` and the
`compact_callback` field from `TelegramCommandContext` (grep-verified; single
dispatch path, DRY). Update `telegram/commands/handlers.py` re-exports.

`run_compact_job`: try/except -> user-visible error reply (scheduler still
logs); ack on enqueue (`notify=False`). Full progress rendering of compact
events stays out of scope (future work).

### Task 4 - Confirmation flow (Req 3)

`bridge.py`: `COMPACT_CONFIRM_CALLBACK_DATA = "takopi:compact:confirm"`,
`COMPACT_DECLINE_CALLBACK_DATA = "takopi:compact:decline"`, markup constant
with `[send anyway][cancel]` buttons (protocol constants, same pattern as
`takopi:cancel`).

`send_plain`: add optional `reply_markup` param and return the `MessageRef`
(backward compatible).

`TelegramLoopState`:
`pending_compact_confirms: dict[tuple[int, int], PendingCompactConfirm]` keyed
by `(chat_id, confirmation_message_id)`; supersede prior pending entries per
(chat, thread).

None-support path in `compact.py`: notification + question message with buttons;
store `PendingCompactConfirm(resume_token, instructions, user_msg_id,
thread_id, session_key)`. Message text states plainly: the engine does not
support native compaction; the agent will receive a plain-text compaction
request as a regular prompt; not real context reduction.

`route_update`: explicit `elif` branch BEFORE generic callback dispatch ->
`handle_compact_confirm_callback`: pop pending (missing -> answer
"request expired"); confirm -> `scheduler.enqueue(ThreadJob(kind="prompt",
text=handoff_prompt(instructions), resume_token=..., thread_id, session_key))`;
decline -> no-op; both -> `answer_callback_query` + edit the confirmation
message with cleared buttons (`CLEAR_MARKUP`).

### Task 5 - Docs and changelog

- `docs/how-to/compact-session.md`: reply-context routing, ordering equivalence,
  none-support confirm flow and its plain-text handoff semantics.
- `docs/reference/commands-and-directives.md`: `/compact` row updated.
- `changelog.md`: entry under the next/unreleased section.

### Task 6 - Verification gate

```
uv run pytest tests/test_telegram_compact_dispatch.py tests/test_telegram_compact_command.py tests/test_telegram_prompt_batch.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
python -m py_compile src/takopi/telegram/commands/compact.py src/takopi/telegram/loop.py src/takopi/telegram/commands/parse.py src/takopi/telegram/bridge.py src/takopi/transport_runtime.py
```

Grep for removed references: `compact_callback`, `_handle_compact_command`.
Do not commit unless the user explicitly asks.

---

## Files touched

- M `src/takopi/telegram/commands/parse.py` (`CompactInvocation` + parser)
- M `src/takopi/telegram/prompt_batch.py` (`CONTROL_COMMANDS`)
- A `src/takopi/telegram/commands/compact.py` (handler + pending state +
  callback handler)
- M `src/takopi/telegram/commands/handlers.py` (re-exports)
- M `src/takopi/telegram/loop.py` (route hook, `ResumeResolver` compact mode,
  wiring, dead-branch removal, `run_compact_job` error surfacing)
- M `src/takopi/telegram/bridge.py` (callback constants/markup; `send_plain`
  markup + `MessageRef` return)
- M `src/takopi/transport_runtime.py` (`extract_resume` passthrough)
- A `tests/test_telegram_compact_dispatch.py`
- M `tests/test_telegram_compact_command.py`
- M `tests/test_telegram_prompt_batch.py`
- M `docs/how-to/compact-session.md`, `docs/reference/commands-and-directives.md`,
  `changelog.md`
- Expected ZERO changes: `src/takopi/scheduler.py` (`kind` routing verified
  complete), `src/takopi/runners/*` (per-engine `compact_support()` values
  verified, incl. mock = `none` for tests). Any deviation must be justified in
  the execution report.

## Execution model

Scoped code-editing subagent (general-purpose, no model override) restricted to
the files above; never touches `site-packages`; TDD order enforced. The subagent
must report difficulties/pitfalls; append the feedback to
`D:/Projects/takopi/EXPERIENCE.md` per workspace convention.

## Risks and pitfalls

- `loop.py` is a God-file under active pair-editing: narrow patches only;
  re-read before each edit.
- The claim "compact waits behind an active run" must be proven by test 2, not
  assumed.
- Removing `compact_callback` / the `_dispatch_builtin_command` compact branch:
  grep for external/plugin references first.
- Compact interception must cancel a pending prompt batch for the same key
  (mirrors `/new`) so prior batched text is not polluted.
- Instructions that legitimately start with a slash (e.g. `/compact /plan`)
  degrade to instructions by design; documented, not an error.
- Do not bypass `ThreadScheduler`; do not create a session when none resolves;
  do not inherit sticky plan/goal for compact jobs (carried over from the prior
  plan).
- Callback data strings are wire-protocol constants (existing `takopi:cancel`
  pattern), not configurable values; no new config keys are introduced.