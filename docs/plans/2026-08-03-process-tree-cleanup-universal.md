# Process-Tree Cleanup for All Runners — Cross-Platform Plan

## Context

When a Takopi runner is cancelled (Telegram `/cancel` or SIGINT), the subprocess cleanup in `src/takopi/utils/subprocess.py` only kills the direct child process on Windows. It does NOT kill the process tree. On Windows, launching `opencode.cmd` spawns `opencode.exe` as a grandchild, and that `opencode.exe` further spawns MCP servers (`chrome-devtools-mcp`, etc.). When Takopi cancels the wrapper, `proc.terminate()` kills `opencode.cmd` but `opencode.exe` and its children survive as orphans.

On POSIX, `start_new_session=True` + `os.killpg()` correctly kills the entire group. No equivalent exists in the current Windows code path.

**This affects ALL runners**, not just OpenCode: `claude`, `codex` (exec mode), `pi`, `agy`, `grok`, `omp` all spawn subprocesses via `manage_subprocess()`. The codex app-server mode (`_AppServerClient`) uses `anyio.open_process()` directly and has NO cleanup at all — it never terminates the server process.

The existing plan (`docs/plans/2026-08-03-opencode-intermittent-failure.md`) diagnosed this for OpenCode specifically and proposed `taskkill /T /F`. This plan generalizes the fix to all runners and makes it cross-platform from the start.

## Approach

### Step 1 — Add `kill_process_tree()` to subprocess utils

**File:** `src/takopi/utils/subprocess.py`

Add a new async function that kills the entire process tree on Windows using `taskkill /PID <pid> /T /F`, and delegates to the existing `kill_process()` on POSIX (which already uses `os.killpg` for process-group kills).

```python
async def kill_process_tree(proc: Process) -> None:
    """Kill the process and all its descendants."""
    if proc.pid is None or proc.returncode is not None:
        return
    if os.name == "nt":
        await anyio.run_process(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    kill_process(proc)
```

Requires adding `import subprocess` (already present in runner.py, but the utils file doesn't import it currently — it only imports `os`, `signal`, `anyio`, etc.). Add it.

### Step 2 — Use `kill_process_tree()` in `manage_subprocess()`

**File:** `src/takopi/utils/subprocess.py`

Change the `finally` block of `manage_subprocess()` to use `kill_process_tree()` instead of `kill_process()`:

```python
finally:
    if proc.returncode is None:
        with anyio.CancelScope(shield=True):
            terminate_process(proc)
            timed_out = await wait_for_process(proc, timeout=2.0)
            if timed_out:
                await kill_process_tree(proc)
                await proc.wait()
```

This is the single point of fix for `JsonlSubprocessRunner` (claude, pi, codex-exec, opencode, grok, omp) and `AgyRunner` — they all go through `manage_subprocess()`.

### Step 3 — Add `CREATE_NEW_PROCESS_GROUP` on Windows for tree management

**File:** `src/takopi/utils/subprocess.py`

In `manage_subprocess()`, on Windows set `creationflags` to `CREATE_NEW_PROCESS_GROUP` so that the process tree can be cleanly identified and killed. This mirrors the POSIX `start_new_session=True` behavior:

```python
if os.name == "posix":
    kwargs.setdefault("start_new_session", True)
elif os.name == "nt":
    kwargs.setdefault(
        "creationflags",
        subprocess.CREATE_NEW_PROCESS_GROUP,
    )
```

`CREATE_NEW_PROCESS_GROUP` (value 512) makes the child the root of a new process group. Combined with `taskkill /T`, this ensures the entire tree is reachable. Do NOT use `CREATE_NO_WINDOW` — some runners (like codex) may need console access.

### Step 4 — Add cleanup to codex app-server `_AppServerClient`

**File:** `src/takopi/runners/codex.py`

The `_AppServerClient` spawns `codex app-server` via `anyio.open_process()` directly (line 749), bypassing `manage_subprocess()`. It has NO cleanup — when the `_reader_loop` detects stdout EOF (line 901), it nulls `self._proc` but never terminates it.

Add a `stop()` method and call it from `_reader_loop`'s finally:

```python
async def stop(self) -> None:
    """Terminate the app-server process and its tree."""
    proc = self._proc
    if proc is None:
        return
    self._proc = None
    if proc.returncode is None:
        with anyio.CancelScope(shield=True):
            terminate_process(proc)
            timed_out = await wait_for_process(proc, timeout=2.0)
            if timed_out:
                await kill_process_tree(proc)
                await proc.wait()
    # Cancel background tasks
    for task in (self._reader_task, self._stderr_task):
        if task is not None and not task.done():
            task.cancel()
```

Import `terminate_process`, `wait_for_process`, `kill_process_tree` from `..utils.subprocess`.

Call `stop()` in `_reader_loop`'s finally block (line 900-904):

```python
finally:
    await self.stop()
    async with self._state_lock:
        if self._proc is proc:
            self._proc = None
            self._loaded_threads.clear()
    await self._fail_all(failure)
```

Wait — `stop()` already nulls `self._proc`, so the `if self._proc is proc` check after will be False. Restructure: move the proc-nulling logic into `stop()` and simplify the `_reader_loop` finally:

```python
finally:
    await self.stop()
    async with self._state_lock:
        self._loaded_threads.clear()
    await self._fail_all(failure)
```

Also apply the same `CREATE_NEW_PROCESS_GROUP` flag in `start()`:

```python
if os.name == "posix":
    kwargs["start_new_session"] = True
elif os.name == "nt":
    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
```

### Step 5 — Write cross-platform regression test

**File:** `tests/test_subprocess.py` (extend existing)

Add a test that spawns a wrapper process which creates a child, then verifies the child is killed when the managed context exits. Must be cross-platform (no skipif):

```python
@pytest.mark.anyio
async def test_manage_subprocess_kills_process_tree(tmp_path: Path) -> None:
    """On cancellation, the entire process tree must be killed, not just the wrapper."""
    marker = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time, pathlib\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid))\n"
        "time.sleep(300)\n"
    )
    cmd = [sys.executable, "-c", script]

    with anyio.move_on_after(2):
        async with subprocess_utils.manage_subprocess(cmd) as proc:
            while not marker.exists():
                await anyio.sleep(0.05)

    child_pid = int(marker.read_text())
    await anyio.sleep(0.3)
    assert not _is_process_alive(child_pid), f"child {child_pid} survived cleanup"
```

Add a cross-platform `_is_process_alive` helper in the test file:

```python
def _is_process_alive(pid: int) -> bool:
    """Check if a process is alive, cross-platform."""
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True  # permission error = alive but not ours
```

### Step 6 — Write app-server cleanup test

**File:** `tests/test_codex_runner_helpers.py` (extend existing)

Add a test that verifies `_AppServerClient.stop()` kills the subprocess and its tree. Use the `make_executable_script` helper from `tests/_subprocess_helpers.py` to create a fake server that spawns a child:

```python
@pytest.mark.anyio
async def test_app_server_client_stop_kills_process_tree(tmp_path: Path) -> None:
    marker_file = tmp_path / "child.pid"
    server_script = (
        "#!/usr/bin/env python3\n"
        "import subprocess, sys, time, pathlib\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"pathlib.Path({str(marker_file)!r}).write_text(str(p.pid))\n"
        # Keep alive waiting for stdin
        "sys.stdin.read()\n"
    )
    cmd = make_executable_script(tmp_path, server_script, name="codex")
    client = _AppServerClient(codex_cmd=cmd, extra_args=[])
    
    # Start would fail at initialize handshake, but the process is spawned
    with pytest.raises(RuntimeError, match="closed stdout|initialize"):
        with anyio.fail_after(3):
            await client.start()
    
    await client.stop()
    child_pid = int(marker_file.read_text())
    await anyio.sleep(0.3)
    assert not _is_process_alive(child_pid)
```

### Step 7 — Verify existing tests still pass

The `CREATE_NEW_PROCESS_GROUP` flag change in `manage_subprocess` must not break the existing `test_manage_subprocess_kills_when_terminate_times_out` test. That test uses `signal.SIGTERM` interception which works regardless of process group.

Run:
```bash
cd /d/Projects/takopi
PYTHONUTF8=1 uv run pytest tests/test_subprocess.py tests/test_codex_runner_helpers.py tests/test_claude_runner.py tests/test_exec_runner.py tests/test_opencode_runner.py -q --no-cov
uv run ruff check src/takopi/utils/subprocess.py src/takopi/runners/codex.py tests/test_subprocess.py tests/test_codex_runner_helpers.py
```

### Step 8 — Prompt-delivery telemetry (shared, all runners)

**File:** `src/takopi/runner.py` (lines 620-626), tests across runner test files

The current `runner.start` log in the shared `JsonlSubprocessRunner.run_impl` emits the raw prompt and `prompt_len`. Add a SHA-256 fingerprint and short preview so logs are diagnostic without leaking entire prompts:

```python
import hashlib

def _prompt_fingerprint(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]

def _safe_preview(prompt: str, max_len: int = 60) -> str:
    preview = prompt.replace("\n", " ").strip()
    return preview[:max_len] + ("…" if len(preview) > max_len else "")
```

In `run_impl`, augment the `runner.start` log (line 620):

```python
logger.info(
    "runner.start",
    engine=self.engine,
    resume=resume.value if resume else None,
    prompt=prompt,                    # keep for debug; guard behind log level
    prompt_len=len(prompt),
    prompt_sha256=_prompt_fingerprint(prompt),  # new
    prompt_preview=_safe_preview(prompt),         # new
)
```

**Test** (`tests/test_runner_utils.py` or runner-specific test): assert that `_prompt_fingerprint` returns 12 hex chars, that `_safe_preview` truncates at 60, and that the `runner.start` event carries both fields. This is shared infrastructure — all JSONL runners get it automatically.

### Step 9 — Shared JSONL idle/no-output guard (all JSONL runners)

**Files:** `src/takopi/runner.py` (`_iter_jsonl_events`, line 588-607), `src/takopi/settings.py`, tests

This is the generalization of original Task 4. The idle guard belongs in the shared `_iter_jsonl_events()` method because claude, pi, codex-exec, grok, omp, and opencode all stream JSONL through it. Any of them can hang silently.

**Step 1: Add global runner settings** (single global section, NOT per-engine):

Timeouts and lifecycle settings apply to ALL runners. They live in a single `[runners]` table in the global Takopi config (`~/.takopi/takopi.toml`), never duplicated per engine:

```toml
[runners]
startup_timeout_s = 60     # no JSONL event within this → fail fast
idle_timeout_s = 900       # no JSONL event after start within this → kill tree
kill_tree_on_cancel = true # Windows: use taskkill /T /F
```

Add a `RunnerSettings` model to `settings.py`:

```python
class RunnerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    startup_timeout_s: float = 60.0
    idle_timeout_s: float = 900.0
    kill_tree_on_cancel: bool = True
```

Wire it into `TakopiSettings` as a top-level field:

```python
class TakopiSettings(BaseSettings):
    ...
    runners: RunnerSettings = Field(default_factory=RunnerSettings)
```

This is the single source of truth. Runners read timeouts from `settings.runners`, not from `engine_config()`. No per-engine duplication. The defaults preserve current behavior (no timeout = effectively infinite today, but 60s/900s is a safe default that prevents indefinite hangs).

Cross-platform note: `kill_tree_on_cancel` defaults to `True` on all platforms — on POSIX it's a no-op since `os.killpg` already handles the tree. It exists for the Windows `taskkill /T /F` path and can be disabled if a user wants to preserve orphaned subprocesses for debugging.

**Step 2: Implement idle guard in `_iter_jsonl_events`**

Wrap the `async for raw_line in self.iter_json_lines(stdout)` loop (line 598) with two timeout guards:

```python
async def _iter_jsonl_events(self, *, stdout, stream, state, resume, logger, pid,
                              timeouts: RunnerTimeouts | None = None) -> AsyncIterator[TakopiEvent]:
    t = timeouts or RunnerTimeouts()
    last_event = anyio.current_time()
    started = False

    with anyio.move_on_after(t.startup_timeout_s) as startup_scope:
        async for raw_line in self.iter_json_lines(stdout):
            last_event = anyio.current_time()
            started = True
            for evt in self._handle_jsonl_line(...):
                yield evt

    # After loop: check if we exited due to timeout vs normal EOF
    if not started and startup_scope.cancel_called:
        yield self.note_event(
            f"{self.tag()} produced no JSON events within {t.startup_timeout_s:.0f}s; "
            f"prompt was spawned but no session started",
            state=state,
        )
        yield CompletedEvent(engine=self.engine, resume=resume, ok=False,
                             answer="", error="startup timeout")
        return

    if started:
        idle = anyio.current_time() - last_event
        if idle >= t.idle_timeout_s:
            yield self.note_event(
                f"{self.tag()} idle timeout after {t.idle_timeout_s:.0f}s; session still running",
                state=state,
            )
            yield CompletedEvent(engine=self.engine, resume=resume, ok=False,
                                 answer="", error="idle timeout")
            return
```

Wait — the above structure has a subtlety: `move_on_after` cancels the `async for` when the scope expires, but we need the idle timeout to reset on each event, not be a fixed wall-clock from start. Better approach: use `anyio.fail_after` per-read via a wrapping async generator that tracks `last_event` and applies `move_on_after(idle_timeout_s)` around each `__anext__`:

```python
async def _iter_jsonl_with_timeouts(
    self, stdout: Any, *, startup_timeout_s: float, idle_timeout_s: float,
) -> AsyncIterator[bytes]:
    last_event = anyio.current_time()
    first = True
    while True:
        timeout = startup_timeout_s if first else idle_timeout_s
        with anyio.move_on_after(timeout) as scope:
            raw = await self.iter_json_lines(stdout).__anext__()
            last_event = anyio.current_time()
            first = False
            yield raw
            continue
        if scope.cancel_called:
            return  # timeout — caller checks how many events were received
```

Then `_iter_jsonl_events` uses `_iter_jsonl_with_timeouts` instead of `iter_json_lines`, and after the loop, if zero events were received (or the stream ended prematurely), emits the appropriate error event.

**Step 3: OpenCode-specific CLI args** (only genuinely OpenCode-specific part of original Task 4)

**File:** `src/takopi/runners/opencode.py` (`build_args`, line 422)

```python
if self.print_logs:
    args.append("--print-logs")
if self.log_level:
    args.extend(["--log-level", self.log_level])
```

These fields live under `[opencode]` in the global config (engine-specific CLI passthrough, not a lifecycle timeout):

```toml
[opencode]
print_logs = false
log_level = "WARN"
```

This is the ONLY engine-specific config in this plan. All timeout/lifecycle settings (`startup_timeout_s`, `idle_timeout_s`, `kill_tree_on_cancel`) are global under `[runners]`.

**Step 4: Tests** (`tests/test_runner_utils.py` or `tests/test_opencode_runner.py`)

- Fake stream that emits nothing for 60s+ → `CompletedEvent(ok=False)` with "startup timeout" error
- Fake stream that emits start event, then nothing for 900s+ → idle timeout
- Normal multi-event stream → completes normally
- Cancellation invokes process-tree cleanup (already covered by Step 5 test)

### Step 10 — Session lock invariant: lock released only after tree cleanup (all runners)

**File:** `tests/test_runner_utils.py` (shared), referencing `src/takopi/runner.py` `run_with_resume_lock` (lines 72-99)

Generalize original Task 5. The contract applies to ALL runners using `JsonlSubprocessRunner.run_with_resume_lock`:

```python
@pytest.mark.anyio
async def test_lock_released_only_after_process_tree_cleanup(tmp_path) -> None:
    """The resume lock must not release until the subprocess tree is dead."""
    runner = OpenCodeRunner(opencode_cmd=...)  # or any JsonlSubprocessRunner
    token = ResumeToken(engine=ENGINE, value="ses_test")

    cleanup_done = anyio.Event()
    original_run_impl = runner.run_impl

    async def tracking_run_impl(prompt, resume):
        try:
            async for evt in original_run_impl(prompt, resume):
                yield evt
        finally:
            # The manage_subprocess cleanup runs before this finally
            cleanup_done.set()

    runner.run_impl = tracking_run_impl

    async def drain(prompt, resume):
        async for _ in runner.run(prompt, resume):
            pass

    # Start turn 1, cancel it, then verify turn 2 doesn't start until cleanup is done
    async with anyio.create_task_group() as tg:
        tg.start_soon(drain, "first", token)
        await anyio.sleep(0.05)  # let turn 1 start
        tg.cancel_scope.cancel()

    # After cancel, the lock should be released only after process cleanup
    assert cleanup_done.is_set(), "cleanup did not complete before lock release"

    # Second turn should start immediately (not blocked by stale lock)
    started = anyio.Event()
    async def quick_run(prompt, resume):
        started.set()
        yield CompletedEvent(engine=ENGINE, resume=token, ok=True, answer="ok")
    runner.run_impl = quick_run
    async for _ in runner.run("second", token):
        pass
    assert started.is_set()
```

This test should be parametrized across `ClaudeRunner`, `CodexRunner`, `OpenCodeRunner`, `PiRunner` to prove the invariant is universal.

### Step 11 — Doctor check: detect orphaned Takopi processes (all runners)

**File:** `src/takopi/cli/doctor.py`, `tests/test_cli_doctor.py`

Generalize original Task 6. Instead of OpenCode-only, detect ANY processes that look like they were spawned by a Takopi runner (codex, claude, opencode, pi, agy, grok, omp).

**Cross-platform process listing:**

```python
def _list_runner_processes() -> list[ProcessInfo]:
    """List running processes matching known runner commands."""
    targets = {"codex", "claude", "opencode", "pi", "agy", "grok", "omp", "node"}
    if os.name == "nt":
        # Use WMIC or Get-CimInstance Win32_Process
        result = subprocess.run(
            ["wmic", "process", "get", "ProcessId,ParentProcessId,Name,CommandLine",
             "/format:csv"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return _parse_wmic_csv(result.stdout, targets)
    else:
        # Use ps aux
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True,
        )
        return _parse_ps_aux(result.stdout, targets)
```

Doctor output (read-only, no kills):

```text
Runner processes:
  codex:        2 process(es), PIDs: [1234, 5678]
  opencode:     1 process(es), PID: [9012] — parent PID 5678 (possible orphan)
  claude:       0
```

The check flags processes whose parent PID is 1 (init) or whose parent is a dead process — those are likely orphans from cancelled Takopi runs. It does NOT kill anything.

**Test:** Use a fake process list (mock `_list_runner_processes`) and assert the doctor correctly identifies orphans and non-orphans, produces the right output format.

### Step 12 — OpenCode argv/prompt-delivery assertions (OpenCode-specific)

**File:** `tests/test_opencode_runner.py` (`test_build_args_new_session`, `test_build_args_with_resume`)

This is the OpenCode-specific part of original Task 3. Assert:

- The final argv item is exactly the effective prompt
- `--` appears immediately before the prompt
- `--session <id>` appears only for resumed runs
- Numeric prompt normalization still appends `.` (the `_NUMERIC_PROMPT_RE.fullmatch` branch at line 432-433)

This is genuinely OpenCode-specific because only OpenCode passes the prompt as a trailing argv element via `--`. Claude and pi use stdin payloads; codex uses app-server JSON-RPC.

### Step 13 — Final verification (expanded)

Run the full test suite and lint:

```bash
cd /d/Projects/takopi
PYTHONUTF8=1 uv run pytest tests/ -q --no-cov
uv run ruff check .
```

Manual smoke tests (both platforms where possible):

1. **Process tree kill:** Send a prompt to OpenCode, cancel from Telegram, verify no `opencode.exe` children survive (Windows: `tasklist`, POSIX: `pgrep`)
2. **Idle timeout:** Configure `startup_timeout_s = 5`, send a prompt to a runner with a fake slow stream, verify the timeout event fires and the process tree is killed
3. **Doctor check:** Run `takopi doctor`, verify it lists runner processes and flags orphans correctly
4. **Prompt telemetry:** Set log level to DEBUG, send a prompt, verify `runner.start` log contains `prompt_sha256` and `prompt_preview` fields

## Critical files & anchors

- `src/takopi/utils/subprocess.py:69-87` — `manage_subprocess()`, single fix point for all `JsonlSubprocessRunner` subclasses + `AgyRunner`
- `src/takopi/runners/codex.py:726-904` — `_AppServerClient.start()` / `_reader_loop`, currently has no process cleanup
- `src/takopi/runner.py:588-607` — `_iter_jsonl_events()`, where the shared idle guard wraps `iter_json_lines()`
- `src/takopi/runner.py:620-626` — `runner.start` log, where prompt fingerprint/preview are added
- `src/takopi/runner.py:72-99` — `run_with_resume_lock()`, the session lock that must release only after tree cleanup
- `src/takopi/runners/opencode.py:405-435` — `build_args()`, for argv assertions and `--print-logs`/`--log-level` flags
- `src/takopi/cli/doctor.py` — where the orphan-process check is added
- `src/takopi/settings.py:269-278` — `engine_config()`, per-engine config dict pattern (timeouts, print_logs)
- `tests/test_subprocess.py` — existing test file, extend with tree-kill regression test
- `tests/test_codex_runner_helpers.py` — existing test file, extend with app-server cleanup test
- `tests/_subprocess_helpers.py` — existing `make_executable_script()` helper for cross-platform test subprocesses

## Verification

1. **Unit tests:** `PYTHONUTF8=1 uv run pytest tests/test_subprocess.py tests/test_codex_runner_helpers.py -q --no-cov` → new lifecycle tests pass
2. **Full suite:** `PYTHONUTF8=1 uv run pytest tests/ -q --no-cov` → 0 failures
3. **Ruff:** `uv run ruff check .` → 0 errors
4. **Manual smoke (Windows):** Start Takopi, send a prompt to an OpenCode session, cancel from Telegram, verify no `opencode.exe` children survive via `tasklist /FI "IMAGENAME eq opencode.exe"`
5. **Manual smoke (POSIX):** Same flow, verify `pgrep -P <pid>` returns nothing after cancellation

## Assumptions & contingencies

- **Assumption:** `taskkill /T /F` is available on all supported Windows versions (confirmed: ships with Windows since XP). On non-Windows, `kill_process()` with `os.killpg` handles the tree via process groups.
- **Assumption:** `CREATE_NEW_PROCESS_GROUP` (512) is sufficient for `taskkill /T` to reach the entire tree. Verified empirically: `taskkill /T` walks the parent-child relationship tree, not Windows process groups. Even without `CREATE_NEW_PROCESS_GROUP`, `taskkill /T` finds descendants. The flag is added for consistency with the POSIX `start_new_session` pattern.
- **Contingency:** If `CREATE_NEW_PROCESS_GROUP` causes issues with runners that expect console interaction (e.g., agy), remove it and rely solely on `taskkill /T` for tree discovery. The flag is not required for `taskkill /T` to work — it walks the OS process tree by parent PID.
- **Contingency:** If the app-server `_AppServerClient.stop()` interferes with normal EOF-driven shutdown (where the server exits on its own), add a `returncode is not None` guard before terminating.
- **Contingency:** If the shared idle guard in `_iter_jsonl_events` proves too aggressive for legitimate long-running turns (e.g., a claude turn that takes >900s between JSONL events), raise the default `idle_timeout_s` or make it runner-specific via `engine_config()`.
- **Contingency:** If `anyio.move_on_after` around `iter_json_lines().__anext__()` causes issues with anyio's cancellation semantics, fall back to a background watchdog task that sets an event when idle timeout expires.

## What changed from the original version of this plan

The first version of this plan (Steps 1-7 only) excluded original plan Tasks 3-6 with a "scope note" claiming they were "OpenCode-specific." On review, that was wrong:

- **Task 3** (prompt telemetry): The `prompt_sha256`/`prompt_preview` fields live in shared `runner.py` → universal. Only the argv assertions are OpenCode-specific.
- **Task 4** (idle/no-output guard): The timeout wraps shared `iter_json_lines()` used by ALL JSONL runners → universal. Only `--print-logs`/`--log-level` are OpenCode-specific.
- **Task 5** (session lock invariants): "Lock released only after tree cleanup" applies to every runner → universal.
- **Task 6** (doctor check): "Detect orphaned Takopi processes" applies to any runner → universal.

Steps 8-13 now include all of these, generalized where they're universal (Steps 8-11) and isolated where they're genuinely OpenCode-specific (Step 12). The only OpenCode-only code is the `--print-logs`/`--log-level` CLI flags and the argv shape assertions.
