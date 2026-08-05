# Pi Plan-Mode Detection + Graceful Fallback - Plan-Spec (Roadmap Task 2)

> Roadmap Task 2 remaining work. Verified current state (2026-08-05):
> - `build_args` (`pi.py:401-402`) appends `--plan` UNCONDITIONALLY when
>   plan mode is active - no detection of the `@narumitw/pi-plan-mode`
>   extension, no fallback when it is absent.
> - Goal mode (`pi.py:354-367`) already injects the autonomous-goal prompt
>   prefix (roadmap req 3b) - no change needed.
> - The extension IS installed on this machine
>   (`~/.pi/agent/npm/node_modules/@narumitw/pi-plan-mode`), so the gap is
>   invisible here and bites on machines without it.

**Goal:** `plan` mode uses native `--plan` when the extension is detected,
and falls back to the soft-plan prompt prefix (with a visible warning) when
it is not. Goal mode stays prompt-based (verified + documented).

**Design:**

- `detect_plan_mode_extension(root: Path | None = None) -> bool` in
  `runners/pi.py`: True when
  `<root>/@narumitw/pi-plan-mode` exists (default root = the conventional
  `~/.pi/agent/npm/node_modules`). Injectable root for tests; no config key
  (the path is a pi-ecosystem convention; YAGNI).
- `build_runner()` resolves and stores `plan_mode_extension: bool` on the
  runner instance (mirrors how other capability attrs live on runners).
- `build_args()`: `plan and plan_mode_extension` -> `--plan`;
  `plan and not plan_mode_extension` -> soft-plan prompt prefix via
  `modes.apply_soft_plan_prompt` (existing, DRY) + one-time
  `logger.warning("pi.plan_mode_extension_missing")`.
- Goal mode: unchanged (`_final_prompt` prefix); covered by tests.

## Tasks (TDD)

### Task A0 - Extension contract notes (investigation, read-only)

1. Read the installed extension (`README`, `package.json`, `src/`) and
   record the `--plan` contract (flag registration, behavior, config) in
   `docs/reference/runners/pi/plan-mode-extension.md`.
2. Record expected CLI behavior when `--plan` is passed WITHOUT the
   extension (error vs ignore) from the docs; if undocumented, note it as
   untested-behavior and keep the fallback as the safe path.

### Task A - Failing tests (RED)

`tests/test_pi_runner.py`:

1. `detect_plan_mode_extension` True/False against fixture roots
   (present/absent package dir).
2. plan + extension -> args contain `--plan`, prompt has NO soft-plan
   prefix.
3. plan + no extension -> args have NO `--plan`, prompt HAS the soft-plan
   prefix, and the missing-extension warning is logged once.
4. goal mode -> autonomous-goal prefix exactly as today (regression);
   goal + plan missing extension -> both fallbacks compose correctly
   (soft-plan prefix + goal prefix, no `--plan`).
5. `build_runner` wires the detection result onto the runner (monkeypatched
   detector).
6. Existing `test_pi_runner.py` and `test_plan_goal_modes.py` suites stay
   green.

### Task B - Implementation (GREEN)

**B1. `runners/pi.py`:** `detect_plan_mode_extension()`, runner attr,
`build_args` gating, warning log.

**B2. Docs:** `docs/reference/runners/pi/plan-mode-extension.md` (A0),
`runner.md` plan/goal section update, changelog entry.

**B3. (optional, only if trivial) `cli/doctor.py`:** show pi plan-mode
extension status next to the pi engine line.

### Task C - Verification gate

```
uv run pytest tests/test_pi_runner.py tests/test_plan_goal_modes.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: `/plan <task>` on pi -> native plan behavior via the extension;
then (optional) rename the extension dir, restart, `/plan` again -> soft
fallback works and the warning appears in the log.

## Files touched

- M `src/takopi/runners/pi.py` (detection, gating, fallback)
- M `tests/test_pi_runner.py` ((conditional) `tests/test_plan_goal_modes.py`)
- A `docs/reference/runners/pi/plan-mode-extension.md`
- (optional) M `src/takopi/cli/doctor.py`
- M `changelog.md`, `ROADMAP.md` (req sync note)

## Risks and pitfalls

- Do not change goal mode - the prompt-prefix path is already correct.
- The soft fallback must reuse `modes.apply_soft_plan_prompt` (no second
  plan prompt implementation).
- Detection must be injectable for tests; do not hardcode beyond the single
  conventional default path.
- `pi-goal-list-loop-audit` and `pi-dynamic-workflows` extensions are out
  of scope (YAGNI) - note them in the reference doc only.
- Do not commit unless the user explicitly asks.