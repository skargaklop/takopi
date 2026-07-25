# Plan/Goal Mode Indicator in Telegram Footer

## Goal

When an agent run is in **plan mode** or **goal mode**, show a mode badge in the Telegram message footer, immediately preceding the existing `ctx: <project>` line. This gives the user an at-a-glance signal that the run is read-only (plan) or autonomous (goal) without requiring them to recall which slash command they used.

## Current State

The Telegram message footer is assembled in `MarkdownFormatter._format_footer` (`src/takopi/markdown.py:242`) from `ProgressState` fields:

```
<ctx line>        ← state.context_line  (e.g. `ctx: takopi @feat`)
<resume line>     ← state.resume_line   (e.g. `codex resume <uuid>`)
```

`context_line` is a pre-formatted string composed at three call sites by `format_context_line(context, projects=...)` (`src/takopi/directives.py:188`):

1. `executor.py:224` — main run path (`_run_engine`), has `run_options` with `plan`/`goal`.
2. `loop.py:1065` — queued progress (`_send_queued_progress`), `plan`/`goal` available at the caller (`loop.py:1641-1642`).
3. `cancel.py:186` — cancelled/edited message (`_edit_labelled_message`), `job.plan`/`job.goal` available on `ThreadJob` (`scheduler.py:28-29`).

`run_options` (`EngineRunOptions`, `runners/run_options.py:20`) carries `plan: bool` and `goal: str | None`. `ThreadJob` (`scheduler.py:18`) carries `plan: bool` and `goal: str | None`.

There is currently **no** UI affordance showing plan/goal state during a run.

## Design

**Approach: augment `context_line` at composition time.** Add a single helper that produces a mode badge string, and prepend it to the `context_line` at all three call sites. This requires no changes to `ProgressState`, `handle_message`, `ProgressEdits`, `snapshot()`, or the `Presenter`/`MarkdownFormatter` — the badge rides along inside the existing `context_line` string.

**Why not a new `ProgressState` field:** That would require threading a new parameter through `snapshot()` → `ProgressState` → `_format_footer` → `render_progress`/`render_final`, plus updates to every snapshot call site and the Presenter protocol. The badge is purely cosmetic metadata that belongs with the context line; baking it into the same string is the minimal, contract-preserving change.

### Badge format

- Plan mode: `` `plan` `` (inline code, lowercase, no colon).
- Goal mode: `` `goal` `` (inline code, lowercase, no colon). The goal condition itself is **not** shown in the footer (it can be long and is already injected into the agent prompt); the badge only signals that the run is autonomous.
- Both present: goal wins (consistent with `run_modes` where goal takes precedence over plan) → show `` `goal` ``.

### Resulting footer shapes

With context + plan:
```
`plan` `ctx: takopi @feat`
`codex resume 0199...`
```

With context + goal:
```
`goal` `ctx: takopi`
`codex resume 0199...`
```

Without context (no project bound) + plan:
```
`plan`
`codex resume 0199...`
```

The badge is space-separated from the ctx line, both rendered as inline code on the same footer line. When there is no `ctx:` line, the badge still appears as its own footer line.

## Implementation

### Step 1 — Add the badge helper (`src/takopi/directives.py`)

Add `format_mode_badge(plan: bool, goal: str | None) -> str | None` next to `format_context_line`:

- Returns `` `goal` `` if `goal` is truthy.
- Returns `` `plan` `` if `plan` is truthy.
- Returns `None` otherwise.

This is a pure function, trivially unit-testable.

### Step 2 — Add a footer-composition helper (`src/takopi/directives.py`)

Add `compose_context_line(context, projects, *, plan, goal) -> str | None` that:

1. Computes `badge = format_mode_badge(plan, goal)`.
2. Computes `ctx = format_context_line(context, projects=projects)`.
3. If both: return `f"{badge} {ctx}"`.
4. If only badge: return `badge`.
5. If only ctx: return `ctx`.
6. Else: `None`.

This keeps the badge-precedes-ctx rule in one place and is the single call for all three sites.

### Step 3 — Wire into the three call sites

Replace `runtime.format_context_line(context)` with `runtime.compose_context_line(context, plan=..., goal=...)` at:

1. **`executor.py:224`** (`_run_engine`): pass `plan = bool(run_options and run_options.plan)`, `goal = run_options.goal if run_options else None`.
2. **`loop.py:1065`** (`_send_queued_progress`): add `plan`/`goal` params to the function signature (defaulting `False`/`None`), pass them through from the caller at `loop.py:1620` (where `plan`/`goal` are already in scope at `loop.py:1641-1642`).
3. **`cancel.py:186`** (`_edit_labelled_message`): pass `plan=job.plan`, `goal=job.goal`.

Add `compose_context_line` as a method on `TransportRuntime` (`transport_runtime.py:446`, next to `format_context_line`) delegating to the module-level helper, so call sites use the same `runtime.compose_context_line(...)` pattern.

### Step 4 — Tests (TDD, written before/with implementation)

- `tests/test_directives.py` (or nearest existing directives test file):
  - `test_format_mode_badge_plan` → `` `plan` ``
  - `test_format_mode_badge_goal` → `` `goal` `` (goal wins over plan)
  - `test_format_mode_badge_none` → `None`
  - `test_compose_context_line_with_plan_and_ctx` → `` `plan` `ctx: z80 @feat` ``
  - `test_compose_context_line_goal_only_no_ctx` → `` `goal` ``
  - `test_compose_context_line_no_mode_returns_ctx` → existing `ctx:` line unchanged
  - `test_compose_context_line_no_mode_no_ctx` → `None`

- `tests/test_exec_render.py`: extend `test_progress_renderer_footer_includes_ctx_before_resume` (or add a sibling) to assert the badge precedes ctx when plan/goal is set in `context_line`.

### Step 5 — Docs

Update `docs/reference/commands-and-directives.md` "Context footer" section to document the optional mode badge preceding the `ctx:` line.

### Step 6 — Changelog

Add `unreleased` entry under `features`.

## Alternatives Considered

1. **New `ProgressState.mode_line` field.** Rejected — requires protocol/Presenter changes and offers no benefit over string composition for a cosmetic badge.
2. **Badge in the header (status line) instead of footer.** Rejected — the header shows engine/elapsed/label and is already busy; the footer is where context metadata lives, so it's the consistent home.
3. **Show the full goal condition text.** Rejected — goal conditions can be long and are already injected into the agent prompt; the badge is a status signal, not a replay.
4. **Separate `format_mode_line` returned alongside `context_line`.** Rejected — would need a new tuple type threaded everywhere; composition into one string is simpler and preserves the existing single-field contract.

## Risks & Verification

- **Risk:** Footer line gets long with badge + ctx + resume. **Mitigation:** badge is short (4-5 chars); the ctx and resume lines already coexist on one footer line via `HARD_BREAK`, and Telegram handles multi-line footers fine.
- **Risk:** Existing footer tests break. **Mitigation:** The badge only appears when plan/goal is set; existing tests that pass no mode produce identical output. TDD tests assert the new behavior.
- **Verification:** Unit tests for the helpers; existing `test_exec_render.py` and `test_exec_bridge.py` footer assertions remain green for non-plan runs; add one assertion for the plan/goal case. Run the full `test_telegram_bridge.py` suite.
