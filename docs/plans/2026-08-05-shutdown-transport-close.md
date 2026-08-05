# Shutdown Transport Close - Plan-Spec (Finish Task 5)

> Roadmap Task 5 remaining work. Status: the SYMPTOM is resolved and marked
> DONE (user-verified 2026-08-05: Ctrl+C = no noise, via `c4e1817`,
> `fc3f7eb`, `42ccb1a`). This spec finishes the engineering artifacts:
> explicit transport close at every spawn site (req 2), bounded/configurable
> shutdown (req 3), and regression coverage (req 4) - plus the mid-run e2e
> proof the idle-time test may have missed.

**Root-cause model (to confirm in Task A0):** runner subprocesses are killed
and reaped, but their asyncio pipe transports (stdin/stdout/stderr) are never
explicitly closed. On Windows + ProactorEventLoop + CPython 3.14 the
transports are GC'd unclosed at interpreter teardown; `__del__` issues a
ResourceWarning whose `__repr__` touches `fileno()` on a closed pipe ->
"Exception ignored ... ValueError: I/O operation on closed pipe".

**Verified current state:**

- `manage_subprocess` (`utils/subprocess.py:94`): kill + `proc.wait()`, NO
  stream close. Used by `runner.py:710` (JsonlSubprocessRunner: claude/pi/
  grok/omp class) and `runners/agy.py:236`.
- Codex app-server (`runners/codex.py:756` spawn via `anyio.open_process`;
  `stop()` ~786-808): `kill_process_tree` / terminate + wait, NO stream
  close. `self._proc` swap is lock-guarded and idempotent - keep that pattern.
- `runner.py:423/431` closes `proc.stdin` only, on the normal payload path
  (not a shutdown close).
- `cli/run.py:329-334`: KeyboardInterrupt -> log -> `typer.Exit(130)`;
  `anyio.run` teardown cancels tasks; transports fall to GC afterwards.
- Existing guards in `tests/test_shutdown.py` (3 tests): cancellation
  terminate, no custom SIGINT handler, no manual outer scope. None asserts
  the noise.

## Tasks (TDD)

### Task A0 - anyio/CPython semantics check (investigation, read-only)

1. Pinned anyio version in `uv.lock`: does `Process.wait()` close stdio
   streams? What exactly does `Process.aclose()` close, and can it block on
   undrained pipes?
2. CPython 3.14 proactor notes on pipe-transport close behavior.
3. Save one page of findings in
   `docs/reference/shutdown/pipe-transport-cleanup.md` (roadmap investigation
   step 3).

### Task A - Failing tests (RED)

New `tests/test_subprocess_close.py` (unit, fake streams):

1. `close_process_streams` closes stdin, stdout, stderr (recording fakes).
2. Error-tolerant and idempotent: streams raising `OSError`, `ValueError`,
   `ClosedResourceError` -> no raise; second call is a no-op.
3. Bounded: a stream whose `aclose()` hangs -> returns within the timeout
   (assert elapsed < limit with `anyio.move_on_after`).

Extend `tests/test_shutdown.py` (integration, real subprocesses):

4. `manage_subprocess` with piped stdin/stdout/stderr under a cancelled
   scope: after exit, no stream resource warnings (capture `warnings`/
   `ResourceWarning` in-process where observable).
5. THE regression (req 4): child-interpreter test - a spawned
   `python -c` script runs `anyio.run(main)` where `main` starts a piped
   subprocess via `manage_subprocess`, self-cancels after ~0.2s, exits;
   pytest asserts child stderr contains neither "Exception ignored" nor
   "unclosed transport". This MUST be a child process: the deallocator noise
   only triggers at real interpreter teardown, never in-process.
6. Codex app-server: unit-level test that `stop()` also closes the process
   streams (fake proc with recording streams).

### Task B - Implementation (GREEN)

**B1. `src/takopi/utils/subprocess.py`:** add
`DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0` (single module constant) and

```
async def close_process_streams(proc, *, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_S) -> None
```

- closes stdin then stdout/stderr (or `Process.aclose()` per A0 findings),
- per-stream `move_on_after(timeout)` bound,
- swallows `OSError`/`ValueError`/`ClosedResourceError`/`BrokenResourceError`,
- never raises, idempotent.

**B2. `manage_subprocess`:** in the `finally` block, after kill + wait, call
`close_process_streams(proc, timeout=close_timeout)`; new optional param
`close_timeout: float | None = None` (None -> the module constant).

**B3. `runners/codex.py` `stop()`:** after kill + wait, same close call.
Keep the existing lock-guarded `_proc` swap and idempotency.

**B4. Settings (req 3).** `RunnerSettings` (`settings.py:223`) +=
`shutdown_timeout_s: float = 5.0`; pass through where a settings object
already flows (runner build path); otherwise the module constant applies.
Document the key in `docs/reference/config.md`. No other hardcoded timeouts
may be introduced.

**B5. Note for Task 6:** one docstring line in `runners/_acp.py`: the future
production ACP transport must close via `close_process_streams`.

### Task C - Docs and roadmap

- `changelog.md`: entry.
- `ROADMAP.md` Task 5: extend the DONE note - reqs 2-4 landed (link this
  spec), only the mid-run e2e remains user-side.

### Task D - Verification gate

```
uv run pytest tests/test_subprocess_close.py tests/test_shutdown.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e (the REAL proof): start takopi, start an agent run (any runner with
a live subprocess), press Ctrl+C MID-RUN -> console shows no
"Exception ignored" / "unclosed transport" noise.

## Files touched

- M `src/takopi/utils/subprocess.py` (helper + integration)
- M `src/takopi/runners/codex.py` (`stop()` close)
- M `src/takopi/settings.py` (`RunnerSettings.shutdown_timeout_s`)
- M `src/takopi/runners/_acp.py` (docstring note only)
- A `tests/test_subprocess_close.py`; M `tests/test_shutdown.py`
- A `docs/reference/shutdown/pipe-transport-cleanup.md`
- M `docs/reference/config.md`, `changelog.md`, `ROADMAP.md`

## Risks and pitfalls

- Closing streams can race reader tasks that still drain stdout/stderr:
  tolerate `ClosedResourceError` on the read side; never reorder the existing
  kill -> wait sequence.
- `Process.aclose()` may block on undrained pipes (A0 must confirm) -
  the per-stream timeout bound is mandatory, shutdown must never hang.
- Do NOT reintroduce a custom SIGINT handler or an outer CancelScope
  (`tests/test_shutdown.py` guards 36/52 protect this).
- The noise is proactor/Windows-specific: in-process assertions alone are
  insufficient - the child-interpreter test (A5) is the real guard.
- Do not commit unless the user explicitly asks.