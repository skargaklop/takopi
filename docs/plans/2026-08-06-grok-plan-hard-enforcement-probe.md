# Grok Plan Mode With Hard Enforcement - Probe + Fix (Roadmap Task 16)

> User question (2026-08-06): can we KEEP native `--permission-mode plan`
> and avoid the cancellations - e.g. plan mode + auto-approve ("yolo")
> simultaneously, or another mechanism? Task 15 chose Path B (soft-plan
> prefix) as the safe baseline; this task determines whether a
> hard-enforcement configuration exists and, if so, restores it.

**Known (A0 of Task 15):** in `--permission-mode plan`, a write/execute
tool call requires an approval headless cannot provide -> the harness
cancels the whole turn (`stopReason=cancelled`). Unknown: whether any flag
combination auto-resolves that prompt as deny-and-continue.

**Candidate mechanisms (from `grok --help`, all semantics unproven):**

- C1 `plan` + `--always-approve` - auto-answers prompts; RISK: may execute
  the write (breaks read-only).
- C2 default mode + `--deny` rules for write/execute tools - denial may
  return as a tool error (agent continues) or may cancel identically.
- C3 `plan` + `--rules` read-only reinforcement ("never invoke
  write/execute tools; describe changes as text") - fewer attempts, soft
  guarantee.
- C4 `--sandbox <profile>` - OS-level containment; writes fail as readable
  tool errors; profiles TBD (`grok inspect` / docs).
- C5 `--permission-mode dontAsk` - semantics unknown; probe.

## Tasks

### Task A0 - Probe matrix (investigation; tiny headless runs, capture streams)

Write-inducing probe prompt: "Create the file plan-probe.md with one line,
then stop." (plus a neutral file-read step to keep it realistic). For each
of C1-C5: run headless with `--output-format streaming-json`, capture to
`docs/reference/runners/grok/probes/<case>.jsonl`, record:

- turn completed vs cancelled (`stopReason`),
- whether the file was actually written (read-only preserved?),
- whether the denial/error was visible to the agent as a tool error.

Winner criteria: turn completes AND no file written AND plan text
delivered. Record the matrix in
`docs/reference/runners/grok/plan-hard-enforcement.md`.

### Task A - Failing tests (RED)

1. Winning combo -> `build_args` emits it for plan mode (fixture from the
   winning probe stream).
2. The winning stream replays to a completed run (no cancel mapping).
3. Salvage net (Task 15) tests stay green - it remains the last line of
   defense regardless of the winner.
4. If NO combo wins: keep Path B (soft plan) and pin the finding in docs
   (no code change; test = current behavior regression).

### Task B - Implementation (GREEN)

- B1. `runners/grok.py` `build_args`: plan mode emits the winning flag
  combination (replacing the Path B soft prefix) OR keeps Path B.
- B2. `docs/reference/runners/grok/runner.md` + `plan-mode-cancel.md`:
  the mechanism, the evidence, the trade-offs.
- B3. Changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_grok_runner.py tests/test_plan_goal_modes.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: `/plan <task>` on grok with the winner deployed - the turn
completes, nothing is written, the plan is delivered.

## Files touched

- M `src/takopi/runners/grok.py` (only if a winner exists)
- M `tests/test_grok_runner.py`, (conditional) `test_plan_goal_modes.py`
- A `docs/reference/runners/grok/probes/*.jsonl`,
  `plan-hard-enforcement.md`
- M `changelog.md`

## Ordering note

Task 15 (Path B soft-plan + salvage) is the safe baseline and should be
committed FIRST (it is currently uncommitted in the working tree). Task 16
experiments on top; if no probe wins, Path B stays.

## Risks and pitfalls

- Probe runs are real LLM calls: keep prompts tiny; 5 runs maximum.
- The C1 outcome MUST be checked for an actual file write (worst case:
  silent plan-mode bypass) - assert on disk, not on the stream.
- Sandbox profiles may not exist on Windows - record as a finding, not a
  failure.
- Do not commit unless the user explicitly asks.