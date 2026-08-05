# Grok Stream Protocol Completion - Plan-Spec (Roadmap Task 11)

> Live evidence 2026-08-05: every run logs
> `jsonl.msgspec.invalid ... Invalid value "available_commands|usage|
> tool_call|tool_call_update" - at $.type` warnings, and a 22-minute run
> shows only "step 3" - tool activity is invisible. Separately, a run ended
> with `grok run stopped (cancelled)` after 48s without user cancel.

**Root cause (code-verified):** `schemas/grok.py` models only 4 event types
(text/thought/end/error), but the grok CLI (Claude-Code-compatible harness,
`--output-format streaming-json`) also emits `tool_call`,
`tool_call_update`, `usage`, and `available_commands`. Each unmatched line
raises msgspec `ValidationError` -> warning spam + the event is DROPPED:
tool calls never become actions (progress steps miss all real work), mid-run
usage telemetry is lost.

**Reuse (DRY):** the claude runner already maps tool events to actions via
the shared `src/takopi/runners/tool_actions.py` helpers
(`tool_kind_and_title`, `tool_input_path`) - same pattern, ACP-style event
names.

## Tasks (TDD)

### Task A0 - Full-fidelity capture + cancellation diagnosis (read-only)

1. Capture a tool-heavy agentic run to
   `docs/reference/runners/grok/stream-sample-agentic.jsonl` (extend the
   Task 10 sample if it lacks tool events). Extract the exact field shapes
   of `tool_call`, `tool_call_update`, `usage`, `available_commands`.
2. Cancellation: reproduce/observe a `stopReason=cancelled` end event;
   classify the cause - takopi-side kill (scheduler/cancel scope),
   CLI-internal cancel, or upstream API failure (omniroute) - from the raw
   stream + takopi logs. Record findings next to the sample; the fix
   approach depends on the class.

### Task A - Failing tests (RED)

`tests/test_grok_schema.py` (fixtures from the real capture):

1. The 4 new types decode into their structs (no ValidationError).
2. Forward-compat: an unknown future type (e.g. `{"type":"mystery"}`)
   decodes to the catch-all / is skipped at DEBUG level - NO warning spam.

`tests/test_grok_runner.py`:

3. `tool_call` (Bash `ls`) -> action_started with kind/title from the shared
   helper (e.g. command kind, title `ls`); step count increments.
4. `tool_call_update` (same id, status completed, ok) -> the same action
   completes; a failed update completes with `ok=False`.
5. `usage` event mid-stream -> merged into the terminal
   `CompletedEvent.usage` (end-event usage takes precedence on conflicts).
6. `available_commands` -> no action, no warning (debug only).
7. Narration/answer split (Task 10) and thought coalescing (Task 9) suites
   stay green.
8. Cancellation mapping: end with `stopReason=cancelled` ->
   `CompletedEvent(ok=False, error="grok run stopped (cancelled)")`
   (existing behavior pinned).

### Task B - Implementation (GREEN)

**B1. `schemas/grok.py`:** add `StreamToolCallEvent` (tag `tool_call`),
`StreamToolCallUpdateEvent` (tag `tool_call_update`), `StreamUsageEvent`
(tag `usage`), `StreamAvailableCommandsEvent` (tag `available_commands`) -
all `forbid_unknown_fields=False`, optional fields shaped from the A0
capture (ids, name/title, kind, status, ok/result, usage dicts). Add a
catch-all: unknown `type` -> `StreamUnknownEvent(type_name)` tolerated; the
runner logs it at DEBUG.

**B2. `runners/grok.py` `translate_grok_event`:**
- `tool_call` -> `factory.action_started(action_id=<id>, kind=<shared>,
  title=<shared>, detail=...)` via `tool_actions.tool_kind_and_title`;
- `tool_call_update` -> matching `action_completed`/`updated` by id, `ok`
  from status;
- `usage` -> accumulate into `GrokStreamState`; merged into the terminal
  completed event (end usage wins);
- `available_commands` / unknown -> DEBUG log, no events.

**B3. Invalid-line handling:** genuine malformed JSON keeps the existing
warning; unknown-but-valid types move to DEBUG (no spam).

**B4. Cancellation:** per A0 classification - takopi-side cause gets fixed
and pinned by a test; CLI/API-side gets an honest user-facing message
(already present) + a docs note. No auto-resume (out of scope).

**B5. Docs:** `docs/reference/runners/grok/` event table updated (all 8+
types); changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_grok_schema.py tests/test_grok_runner.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: run a tool-heavy grok task - progress shows real tool actions
(read/edit/bash steps), zero `msgspec.invalid` warnings in the log, usage
present at completion; if a cancel recurs, the message states the reason.

## Files touched

- M `src/takopi/schemas/grok.py` (4 new event structs + catch-all)
- M `src/takopi/runners/grok.py` (tool action mapping, usage merge, debug
  demotion)
- M `tests/test_grok_schema.py`, `tests/test_grok_runner.py`
- A/M `docs/reference/runners/grok/stream-sample-agentic.jsonl` (+ analysis
  note incl. cancellation classification)
- M `changelog.md`

## Risks and pitfalls

- Field shapes must come from the REAL capture (A0), never guessed -
  ACP-style events vary across harness versions.
- `forbid_unknown_fields=False` stays on every struct (forward tolerance).
- Do not regress the Task 9/10 behaviors (coalescing, narration split);
  their tests are the guard.
- Action ids must correlate `tool_call` with `tool_call_update`; duplicate
  starts for the same id are a bug - pin with a test.
- Do not commit unless the user explicitly asks.