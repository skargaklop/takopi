# OpenCode Intermittent Failure Investigation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Takopi's OpenCode runner reliable when OpenCode hangs, is cancelled, or leaves child processes behind, and add enough telemetry to prove whether the prompt reached OpenCode.

**Architecture:** Keep the existing `JsonlSubprocessRunner` and `OpenCodeRunner` shape. Fix the process-lifecycle layer first because Takopi currently launches `opencode.cmd`, but on Windows a surviving `opencode.exe` child can remain after cancellation. Add focused runner/process tests, then add OpenCode-specific diagnostics and configurable idle/timeout handling.

**Tech Stack:** Python 3.14, AnyIO, pytest, Ruff, Windows PowerShell/process APIs, OpenCode CLI `1.17.13`.

**ASCII implementation sketch:**

```text
 Telegram message
   |
   v
 Takopi route_message / handle_message
   |
   v
 OpenCodeRunner.build_args()
   |
   +--> opencode.cmd run --format json [--session ...] -- <prompt>
   |
   v
 JsonlSubprocessRunner stdout/stderr/process lifecycle
   |
   +--> success: step_start/text/tool_use/step_finish -> CompletedEvent
   |
   +--> failure today: wrapper cancelled, child opencode.exe survives
            |
            v
      Fix Windows process tree cleanup + timeout/diagnostics
```

---

## Current Evidence

Takopi does send the prompt to OpenCode at the subprocess boundary.

Evidence from `C:\Users\DELL E5570\.takopi\takopi.log`:

| Telegram message | Takopi event sequence | Result |
| --- | --- | --- |
| `2488` | `runner.start` -> `subprocess.spawn` -> `subprocess.exit rc=0` -> `runner.completed` | completed |
| `2492` | `runner.start` -> `subprocess.spawn` -> `handle.cancelled` | cancelled before completion |
| `2494` | `runner.start` -> `subprocess.spawn` -> `handle.cancelled` | cancelled before completion |
| `2496` | `runner.start` -> `subprocess.spawn` -> `subprocess.exit rc=0` -> `runner.completed` | completed |
| `2501` | `runner.start` -> `subprocess.spawn` -> `handle.cancelled` after `1063s` | hung/no completion |
| `2503` | `runner.start` -> `subprocess.spawn` -> `subprocess.exit rc=0` -> `runner.completed` | completed |
| `2509` | `runner.start` -> `subprocess.spawn` -> `subprocess.exit rc=0` -> `runner.completed` | completed |
| `2513` | `runner.start` -> `subprocess.spawn` -> `subprocess.exit rc=0` -> `runner.completed` | completed |
| `2538` | `runner.start` -> `subprocess.spawn` -> `subprocess.exit rc=0` -> `runner.completed` | completed after live recheck |

For every OpenCode `subprocess.spawn`, Takopi's logged argv has the shape:

```text
opencode.cmd run --format json [--session <session_id>] -- <prompt>
```

The last argv element length matches the assembled prompt length plus Takopi mode/file-delivery instructions when those are injected.

Evidence from `C:\Users\DELL E5570\.local\share\opencode\log\opencode.log`:

- Session `ses_03902ca8fffenoPwJvMUyxQW1V` was created by OpenCode at `2026-08-03T09:38:30Z`.
- OpenCode logged `process` and `stream` entries for that session after Takopi spawned it.
- The hung Takopi run at `2026-08-03T09:45:33Z` maps to OpenCode run `2f023227`, which logged:
  - `loop session.id=ses_03902ca8fffenoPwJvMUyxQW1V step=0`
  - `process session.id=ses_03902ca8fffenoPwJvMUyxQW1V`
  - `stream providerID=omniroute modelID=vertex/gemini-3.5-flash ...`
- Windows still has a live `opencode.exe` child whose parent PID is the cancelled Takopi-spawned wrapper process and whose command line contains the same session id and prompt prefix.
- That live child has MCP children such as `chrome-devtools-mcp`, `@z_ai/mcp-server`, and `mcp-server-windows-x64.exe`.

Live recheck at `2026-08-03T13:40:49+03:00` changed the interpretation of the newest process:

- PID `19092` / child `9976` was a normal live Takopi-launched OpenCode run for Telegram `user_msg_id=2538`, session `ses_038e7f483ffeA9c5elELZNUHj9`.
- Takopi later logged `subprocess.exit rc=0` at `2026-08-03T10:40:43Z` and `runner.completed` at `2026-08-03T10:40:46Z` for that same message.
- Therefore this current run was not a failure and should not be used as evidence of a stuck OpenCode process.
- The old PID `15984` from the cancelled `user_msg_id=2501` run still remains live, with MCP descendants, and its direct wrapper parent is gone. That remains evidence of Takopi process-tree cleanup failure.

Conclusion: the intermittent failure is not "OpenCode never receives the prompt" for the inspected runs. Takopi sends the prompt, and OpenCode starts processing it. Some OpenCode runs are slow, and OpenCode itself may hang or abort, but Takopi's bug is narrower and still real: after Telegram cancellation, Takopi can leave the Windows OpenCode child process tree running.

## Likely Root Cause

`src/takopi/utils/subprocess.py` only creates a new process group on POSIX:

```python
if os.name == "posix":
    kwargs.setdefault("start_new_session", True)
proc = await anyio.open_process(cmd, **kwargs)
```

On cancellation, it calls `proc.terminate()` / `proc.kill()` on Windows. That targets the direct process, which is `opencode.cmd`, not necessarily the real `opencode.exe` child and its MCP children.

The observed result is a surviving `opencode.exe` process for the cancelled Takopi run. Later successful runs prove that this does not always block OpenCode, but it can still cause intermittent behavior through:

- concurrent OpenCode work against the same session id;
- stale MCP child processes;
- OpenCode DB/WAL contention in `C:\Users\DELL E5570\.local\share\opencode\opencode.db`;
- Takopi waiting forever because stdout never emits a final JSON event;
- session state becoming confusing because Takopi considers the turn cancelled while OpenCode continues.

## Non-Root Findings

The following are noise or secondary problems, not the main prompt-delivery failure:

- Duplicate OpenCode skill-name warnings are frequent, but successful runs have the same warning pattern.
- Telegram `getUpdates` network errors exist, but the failing OpenCode run already reached `runner.start` and `subprocess.spawn`.
- Takopi's current info log does not include JSONL receive events or OpenCode stderr unless pipeline tracing/debug is enabled, so a future failure may still need stronger diagnostics.
- A live OpenCode process is not automatically a bug. The `user_msg_id=2538` process looked suspicious during evidence collection, but logs later showed normal completion.
- OpenCode can be buggy or slow by itself. Takopi should handle that explicitly with cancellation cleanup, idle diagnostics, and clear status, not by assuming every long run is a prompt-delivery failure.

## Task 1: Add A Process-Tree Cleanup Regression Test

**Files:**

- Modify: `tests/test_subprocess_utils.py` or create it if absent.
- Modify: `src/takopi/utils/subprocess.py` only after the failing test exists.

**Step 1: Write the failing test**

Create a Windows-specific test that starts a wrapper process which spawns a child process, then exits/cancels the managed context and asserts the child is gone.

Sketch:

```python
@pytest.mark.anyio
async def test_manage_subprocess_kills_windows_child_tree(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows process-tree regression")

    marker = tmp_path / "child.pid"
    cmd = [
        sys.executable,
        "-c",
        (
            "import subprocess, sys, time, pathlib;"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)']);"
            f"pathlib.Path({str(marker)!r}).write_text(str(p.pid));"
            "time.sleep(300)"
        ),
    ]

    with anyio.move_on_after(1):
        async with manage_subprocess(cmd) as proc:
            while not marker.exists():
                await anyio.sleep(0.05)
            raise anyio.get_cancelled_exc_class()

    child_pid = int(marker.read_text())
    assert not process_exists(child_pid)
```

The helper can use `Get-CimInstance` through Python's `subprocess.run()` or a small `ctypes`/`os.kill(pid, 0)` check on Windows. Keep it test-local.

**Step 2: Verify it fails**

Run:

```powershell
Set-Location -LiteralPath 'D:\Projects\takopi'
$env:PYTHONUTF8='1'
uv run pytest tests/test_subprocess_utils.py -q
```

Expected before implementation: the child process remains alive.

## Task 2: Implement Windows Process-Tree Termination

**Files:**

- Modify: `src/takopi/utils/subprocess.py`
- Test: `tests/test_subprocess_utils.py`

**Step 1: Add a Windows process-tree kill helper**

Implementation sketch:

```python
async def kill_process_tree(proc: Process) -> None:
    if proc.pid is None or proc.returncode is not None:
        return
    if os.name == "nt":
        await anyio.run_process(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    kill_process(proc)
```

Keep POSIX behavior through the existing process-group signal path.

**Step 2: Use process-tree cleanup in `manage_subprocess()`**

Implementation sketch:

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

On Windows, consider calling `taskkill /T` during the terminate phase too if terminating the wrapper does not stop the child tree. Keep the grace period configurable only if tests or real behavior show it is needed.

**Step 3: Verify**

Run:

```powershell
$env:PYTHONUTF8='1'
uv run pytest tests/test_subprocess_utils.py tests/test_runner_utils.py -q
```

Expected: new regression passes and existing runner lifecycle tests still pass.

## Task 3: Add OpenCode Prompt-Delivery And Spawn Diagnostics Tests

**Files:**

- Modify: `tests/test_opencode_runner.py`
- Modify: `src/takopi/runners/opencode.py`
- Modify: `src/takopi/runner.py` only if shared instrumentation belongs there.

**Step 1: Add assertions for argv shape**

Extend existing `test_build_args_new_session()` and `test_build_args_with_resume()` to assert:

- the final argv item is exactly the effective prompt;
- `--` appears immediately before the prompt;
- `--session <id>` appears only for resumed runs;
- numeric prompt normalization still appends `.`.

**Step 2: Add prompt fingerprint telemetry, not raw prompt duplication**

Current `runner.start` and `subprocess.spawn` log full prompt/argv. For diagnosis without leaking entire prompts, add fields:

```python
prompt_len=len(prompt)
prompt_sha256=hash_prompt(prompt)
prompt_preview=safe_preview(prompt)
```

Keep raw prompt logging behind debug if current behavior is intentionally used for diagnostics. If changing this is too large for this bugfix, add the fingerprint in addition to existing fields first.

**Step 3: Verify**

Run:

```powershell
$env:PYTHONUTF8='1'
uv run pytest tests/test_opencode_runner.py tests/test_runner_utils.py -q
```

Expected: tests confirm prompt stays the final argv element.

## Task 4: Add OpenCode Idle/No-JSON Progress Handling

**Files:**

- Modify: `src/takopi/settings.py`
- Modify: `src/takopi/runners/opencode.py`
- Modify: `src/takopi/runner.py` if shared JSONL idle support is cleaner.
- Test: `tests/test_opencode_runner.py` or `tests/test_runner_utils.py`
- Docs: `docs/reference/config.md`, `docs/reference/runners/opencode/runner.md`

**Step 1: Add configuration**

Add `[opencode]` settings parsed in `build_runner()`:

```toml
[opencode]
model = "provider/model"       # existing
plan_agent = "plan"            # existing
print_logs = false             # new
log_level = "WARN"             # new: DEBUG/INFO/WARN/ERROR
startup_timeout_s = 60         # new: no session/start event guard
idle_timeout_s = 900           # new: no stdout event guard after start
kill_tree_on_cancel = true     # new, Windows-relevant
```

Do not hardcode operational thresholds in code. Defaults should preserve normal long-running work but prevent indefinite silent hangs.

**Step 2: Wire OpenCode CLI diagnostics**

In `OpenCodeRunner.build_args()`:

```python
if self.print_logs:
    args.append("--print-logs")
if self.log_level:
    args.extend(["--log-level", self.log_level])
```

Use this only when configured or debug mode is active. Avoid noisy default logs in normal Telegram output.

**Step 3: Add idle guard**

Implement a shared or OpenCode-specific wrapper around `iter_json_lines()` that records the last stdout JSONL event time. If no `step_start` arrives within `startup_timeout_s`, complete with a clear error:

```text
opencode produced no JSON events within 60s; prompt was spawned but no session started
```

If a session started but no stdout event arrives for `idle_timeout_s`, terminate the process tree and emit:

```text
opencode idle timeout after 900s; session <id> was still running
```

**Step 4: Tests**

Add fake stream tests:

- no stdout JSON before startup timeout -> `CompletedEvent(ok=False)` with useful error;
- started event then no more stdout -> idle timeout;
- normal multi-step stream still completes;
- cancellation invokes process-tree cleanup path.

## Task 5: Preserve Takopi Session Lock Invariants

**Files:**

- Test: `tests/test_opencode_runner.py`
- Maybe modify: `src/takopi/runner.py`

The existing test `test_run_serializes_same_session()` should be strengthened for cancellation:

```python
async def test_opencode_same_session_lock_released_after_cancel() -> None:
    ...
```

Expected contract:

- Takopi never runs two OpenCode turns concurrently for the same `ResumeToken`.
- If a turn is cancelled, the lock is released only after the process tree has been cleaned.
- A later prompt for the same session is queued behind cleanup, not started while the orphan is still alive.

## Task 6: Add A Diagnostic Command Or Doctor Check

**Files:**

- Modify: `src/takopi/cli/doctor.py`
- Test: `tests/test_cli_doctor.py`
- Docs: `docs/reference/runners/opencode/runner.md`

Add a read-only doctor check:

```text
OpenCode:
  version: 1.17.13
  data dir: C:\Users\...\ .local\share\opencode
  active opencode processes: N
  possible Takopi-orphaned processes: N
```

Do not kill processes in doctor mode. Only report exact PIDs, session IDs when visible, and recommended command.

## Task 7: Verification

Run focused tests:

```powershell
Set-Location -LiteralPath 'D:\Projects\takopi'
$env:PYTHONUTF8='1'
uv run pytest tests/test_subprocess_utils.py tests/test_runner_utils.py tests/test_opencode_runner.py -q
```

Run relevant Telegram/runner regression tests:

```powershell
$env:PYTHONUTF8='1'
uv run pytest tests/test_telegram_bridge.py tests/test_telegram_prompt_batch.py tests/test_telegram_prompt_batch_integration.py -q
```

Run lint:

```powershell
$env:PYTHONUTF8='1'
uv run ruff check .
```

Run the full suite if focused checks pass:

```powershell
$env:PYTHONUTF8='1'
uv run pytest -q
```

Manual smoke:

1. Start Takopi with `TAKOPI_TRACE_PIPELINE=1` and `[opencode] print_logs = true`.
2. Send `/opencode <short prompt>` and confirm `runner.start`, `subprocess.spawn`, OpenCode `process`, OpenCode `stream`, `subprocess.exit`, and `runner.completed`.
3. Send a prompt that runs long, cancel it from Telegram, then verify no descendant `opencode.exe`, `cmd.exe`, or MCP process remains under the Takopi-spawned PID.
4. Send another prompt to the same OpenCode session and confirm it starts only after cleanup.

## Immediate Operational Note

There is currently at least one live OpenCode process from an old cancelled Takopi run: PID `15984`, session `ses_03902ca8fffenoPwJvMUyxQW1V`, created at `2026-08-03 12:45:33` local time. The newer `user_msg_id=2538` OpenCode run completed normally and is not part of the stale-process evidence.

Do not kill stale processes as part of plan-mode work. Before implementation or a live smoke test, inspect the old process tree again with:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'opencode|node|cmd' -and $_.CommandLine -match 'ses_03902ca8fffenoPwJvMUyxQW1V' } |
  Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine
```

If the user approves cleanup, terminate only the confirmed stale process tree with `taskkill /PID 15984 /T /F`, after rechecking that it is still the same old cancelled Takopi session.

## Handoff

Implement in this order:

1. Process-tree cleanup regression test.
2. Windows process-tree cleanup implementation.
3. OpenCode argv/prompt-delivery tests.
4. OpenCode diagnostics and timeout settings.
5. Doctor check.
6. Focused tests, Ruff, then full pytest.

Do not change OpenCode prompt transport until tests prove argv passing is the problem. Current evidence says argv passing works; lifecycle cleanup and no-completion handling are the gaps.

[[takopi-send: D:\Projects\takopi\docs\plans\2026-08-03-opencode-intermittent-failure.md]]
