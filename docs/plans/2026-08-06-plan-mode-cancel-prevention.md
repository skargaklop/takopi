# Plan-Mode Cancel Prevention - Plan-Spec (Roadmap Task 15)

> Live evidence 2026-08-06 (AFTER the Task 12 rebuild): a `/plan` grok run
> still ends "error - grok - 2m 28s - step 22" with the NEW honest message
> "plan-mode turn cancelled by the harness (attempted a forbidden
> write/execute in read-only mode)". Task 12 fixed the message and removed
> the mandatory-write instruction; the cancellation itself remains.

**Interpretation:** with the self-inflicted write instruction gone, the
agent still hits the harness plan-mode abort by its own initiative -
attempting a tool call (e.g. run a command, write a file) or a
plan-approval flow that headless cannot answer. Which trigger fires is
UNKNOWN; Task 11 already proved the cancellation is not reproducible on
demand in normal runs. A0 must capture a real plan-mode cancellation
before any fix is chosen.

**Goals:**
1. A `/plan` run on grok completes and the plan reaches the user - no
   spurious cancellation.
2. If a cancellation still happens with plan content present, the user
   gets the plan (salvage) instead of an opaque error.

## Tasks

### Task A0 - Capture and classify the trigger (investigation, read-only)

1. Reproduce `/plan <task>` on grok with the current build; capture the
   full stream to
   `docs/reference/runners/grok/stream-sample-plan-cancel.jsonl`.
2. Identify the last events before the `stopReason=cancelled` end:
   - a `tool_call` for a write/execute tool -> forbidden-op abort;
   - a plan-approval/exit-request shape -> headless-approval abort;
   - neither -> record the actual shape.
3. Probe the alternative: run with `--deny` rules instead of
   `--permission-mode plan` on a write-inducing prompt - does the harness
   DENY the tool and let the turn continue (graceful) or cancel the turn
   (same abort)? Record which.
4. Record findings in `docs/reference/runners/grok/plan-mode-cancel.md`.
   The A0 outcome selects the Task B path:

**Path A (deny-rules are graceful):** grok plan mode uses `--deny` rules
for mutating tools instead of `--permission-mode plan`; turn completes;
plan delivered as text + auto-file.

**Path B (no graceful enforcement exists):** grok plan mode switches to the
soft prompt prefix (like codex/omp/opencode) - no harness enforcement, no
cancellations; the plan auto-file path delivers the plan. Document the
trade-off (no hard read-only guarantee on grok).

**Path C (approval-flow abort):** keep native plan mode; map the
approval-request cancel pattern to a successful completion carrying the
plan answer (no error), with the note "plan presented (read-only mode);
approve manually by continuing the session".

### Task B - Salvage safety net (implement regardless of A/B/C)

When a plan-mode run ends `stopReason=cancelled` AND the session produced
a non-empty trailing answer/plan text: complete as `ok=True` (or a
soft-warning variant), deliver the plan text, and append the note
"turn ended by plan-mode enforcement; nothing was executed". When the
answer is empty, keep the Task 12 error message. This converts every
remaining spurious cancel into a usable outcome.

### Task A - Failing tests (RED)

1. Plan-mode cancelled end WITH trailing plan text -> ok/soft completion,
   plan delivered, enforcement note appended (salvage).
2. Plan-mode cancelled end with EMPTY answer -> Task 12 error message
   (regression).
3. Per the chosen A0 path: `--deny` args built for plan mode (Path A), or
   soft prefix instead of `--permission-mode plan` (Path B), or
   approval-cancel -> success mapping (Path C).
4. Non-plan cancellations unchanged; Task 9/10/11 suites green.

### Task C - Verification gate

```
uv run pytest tests/test_grok_runner.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: `/plan <task>` on grok completes; the plan is delivered; if a
cancel ever slips through, the plan content still reaches the user.

## Files touched

- M `src/takopi/runners/grok.py` (path A/B/C change + salvage mapping)
- (conditional) M `src/takopi/runners/modes.py` (soft-plan reuse)
- M `tests/test_grok_runner.py`
- A `docs/reference/runners/grok/stream-sample-plan-cancel.jsonl`,
  `plan-mode-cancel.md`
- M `changelog.md`

## Risks and pitfalls

- Path selection MUST follow the A0 capture - no fix before the trigger is
  classified (the Task 11 investigation already showed guessing fails).
- Salvage must not mask REAL user cancels: a user-initiated `/cancel`
  keeps its current semantics - the salvage path applies only to
  harness-side plan-mode aborts with content (distinguish via plan mode
  state + stopReason, not user cancel flags).
- Soft-plan fallback (Path B) trades hard enforcement for reliability;
  document it explicitly in the runner reference.
- Do not commit unless the user explicitly asks.