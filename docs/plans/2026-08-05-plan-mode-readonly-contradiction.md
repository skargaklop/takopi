# Plan-Mode Read-Only Contradiction - Plan-Spec (Roadmap Task 12)

> Live evidence 2026-08-05: repeated `grok run stopped (cancelled)` mid-run
> in plan mode. The spawn log shows the contradiction in one frame: prompt
> contains "PLAN MODE: you MUST produce a plan as a .md ... before
> finishing" while args contain `--permission-mode plan` (harness-enforced
> read-only). Both cancellations fired right as the agent attempted to act
> ("Let me run the full verification suite", "Let me fix that: [ROADMAP
> edit]"); the CLI exits rc=0 with `stopReason=cancelled`.

**Root cause:** `build_send_instruction(plan_mode=True)`
(`src/takopi/outbound_files.py:114-120`) appends a MANDATORY plan-file
write to EVERY plan-mode prompt. Native plan-mode runners - grok
(`grok.py:351`) and claude (`claude.py:324`) - run the harness in read-only
mode, so the instructed write is forbidden; the grok harness cancels the
whole turn on forbidden operations (headless mode cannot prompt for
approval). The instruction is also redundant: `plan_auto_file`
(`outbound_files.py:302-310`) already auto-writes `outgoing/plan-*.md` from
the answer text when no plan file arrives.

**Soft-plan runners are unaffected** (codex, omp, opencode use
`soft_plan=True` prompt prefix; no harness enforcement, writes allowed).

**Goal:** native read-only plan runs never self-cancel over the plan file;
the plan is still delivered to the user; honest cancellation messaging.

**Chosen design:**

1. **Mode-aware instruction.** Runner declares plan enforcement style, one
   attribute (mirrors the compact_support pattern):
   `plan_enforcement: Literal["native_readonly", "soft"] = "soft"`
   (True for grok/claude as `"native_readonly"`). The injection call site
   passes it through; `build_send_instruction` gains the matching variant:
   - native_readonly: "PLAN MODE (read-only): present the plan as your final
     TEXT answer. Do NOT write files or run mutating commands - the harness
     forbids them and will cancel the turn. Takopi saves and delivers your
     plan automatically."
   - soft: current text unchanged.
2. **Delivery without writes:** native path relies on `plan_auto_file`
   (already default-on); `write_plan_auto_file` needs no changes.
3. **Honest cancellation surfacing:** when a plan-mode run ends with
   `stopReason=cancelled`, the runner maps the error to
   "plan-mode turn cancelled by the harness (attempted a forbidden
   write/execute in read-only mode)" instead of the opaque
   "grok run stopped (cancelled)". Requires plan-mode state on
   `GrokStreamState` (build_args already knows).

## Tasks (TDD)

### Task A0 - Reproduce and audit (investigation, read-only)

1. Reproduce a `/plan` grok run; capture the stream; confirm the cancelled
   end event follows a write/execute attempt (or the harness plan-mode
   abort).
2. Audit claude native plan mode with the same mandatory-write prompt:
   does its harness cancel too, or deny gracefully? Record the difference;
   the wording fix applies to both regardless.

### Task A - Failing tests (RED)

`tests/test_outbound_files.py`:

1. `build_send_instruction(plan_mode=True, enforcement="native_readonly")`
   -> text-answer wording; contains no "MUST produce" file requirement.
2. Soft variant byte-identical to today (regression).

`tests/test_grok_runner.py` (and claude if the audit shows cancellation):

3. plan-mode run ending `stopReason=cancelled` -> `CompletedEvent.ok` False
   with the read-only explanation message.
4. Non-plan cancellation keeps the old message (no mislabeling).

Injection wiring (loop/bridge level):

5. The plan-mode instruction injected for a native runner uses the
   native_readonly variant; for a soft runner the soft variant.

### Task B - Implementation (GREEN)

**B1. `outbound_files.py`:** `enforcement` param on
`build_send_instruction`/`append_send_instruction`; the two wording
variants.

**B2. Runner attribute:** `plan_enforcement` on grok + claude
(`"native_readonly"`); default `"soft"` elsewhere (no churn).

**B3. Injection call site:** pass the runner\'s enforcement style into
`append_send_instruction` (locate the exact call site - runner_bridge or
executor - during implementation; it already knows the runner and
`run_options.plan`).

**B4. grok cancellation mapping:** plan-mode flag on `GrokStreamState`;
the cancelled-stop error text per design (claude equivalent if A0 shows
cancellation there).

**B5. Docs:** `docs/how-to/` plan-mode note (native read-only behavior +
auto-file delivery); changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_outbound_files.py tests/test_grok_runner.py tests/test_claude_runner.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: `/plan <task>` on grok -> the run finishes WITHOUT cancellation,
the final message is the plan text, and the plan .md is delivered (auto
file). Repeat once on claude.

## Files touched

- M `src/takopi/outbound_files.py` (enforcement variants)
- M `src/takopi/runners/grok.py` (`plan_enforcement`, cancellation mapping)
- M `src/takopi/runners/claude.py` (`plan_enforcement`; mapping per audit)
- M injection call site (`runner_bridge.py` or executor - located in B3)
- M `tests/test_outbound_files.py`, `tests/test_grok_runner.py`,
  (conditional) `tests/test_claude_runner.py`
- M docs + `changelog.md`

## Risks and pitfalls

- Do not weaken the soft-plan path: its wording and file delivery stay
  byte-identical.
- The native wording must not instruct ANY write/execute - including the
  [[takopi-send]] marker expectation for the plan itself (auto-file covers
  it); other file sends are equally forbidden in read-only mode.
- Keep `plan_require_send` semantics: with auto-file on, native plan runs
  still satisfy the delivery requirement from the answer text.
- Cancellation message changes only for plan-mode runs; non-plan cancels
  keep the existing text (pinned by test 4).
- Do not commit unless the user explicitly asks.