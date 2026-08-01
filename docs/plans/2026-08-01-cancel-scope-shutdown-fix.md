# Fix: Cancel-Scope Crash on SIGINT Shutdown + Logging Options

## Problem 1: `RuntimeError: Attempted to exit a cancel scope that isn't the current tasks's current cancel scope`

### Root Cause

`backend.py:179-191` wraps `run_main_loop` in a `CancelScope` and installs a SIGINT handler that calls `scope.cancel()`:

```python
async def run_loop() -> None:
    with anyio.CancelScope() as scope:
        restore = _install_sigint_cancel_handler(scope)
        try:
            await run_main_loop(...)
        finally:
            restore()
anyio.run(run_loop)
```

When SIGINT arrives, the signal handler calls `scope.cancel()`. This injects a `Cancelled` exception into the task running `run_main_loop`. However, `run_main_loop` internally uses `async with anyio.create_task_group()` (line 1485+). The cancellation propagates through nested cancel scopes inside the task group. When the inner task group's `__aexit__` runs during cancellation, the scope stack can get into an inconsistent state — the outer scope (from `run_loop`) is no longer the task's "current" scope by the time its `__exit__` runs, because the cancellation unwinding has already popped inner scopes.

On Windows + asyncio, this manifests reliably because the signal handler runs in the main thread and the cancellation interacts with the `_ProactorBasePipeTransport` cleanup (the "unclosed transport" warnings are a downstream symptom of the same unclean shutdown).

Additionally, `run.py:314` catches `KeyboardInterrupt` — but with the custom SIGINT handler installed, `KeyboardInterrupt` is never raised (the handler cancels the scope instead). The crash escapes `anyio.run`, bypassing the `KeyboardInterrupt` catch, and produces the traceback in `20260801-errors.md`.

### Fix

**Replace the manual SIGINT handler + `CancelScope` with anyio's built-in cancellation-on-SIGINT.** The `anyio.run()` function on the asyncio backend already installs a SIGINT handler that cancels the root task cooperatively. The custom `_install_sigint_cancel_handler` is fighting anyio's own SIGINT handling.

Change `backend.py:179-193` from:

```python
async def run_loop() -> None:
    with anyio.CancelScope() as scope:
        restore = _install_sigint_cancel_handler(scope)
        try:
            await run_main_loop(...)
        finally:
            restore()

anyio.run(run_loop)
```

To:

```python
async def run_loop() -> None:
    await run_main_loop(...)

anyio.run(run_loop)
```

anyio's `run()` installs its own SIGINT handler that raises `KeyboardInterrupt` after the task group cleans up (Python 3.14's `asyncio.Runner` does the same). This means:
- SIGINT → anyio cancels the root task → `run_main_loop`'s `finally` block runs (`transport.close()`) → all nested scopes unwind cleanly → `KeyboardInterrupt` is raised after cleanup → caught by `run.py:314`.

Remove `_install_sigint_cancel_handler` entirely (dead code after the change).

**Why this is safe:** anyio's built-in SIGINT handling is the documented, supported mechanism. The manual handler was a workaround that conflicts with anyio's scope tracking. The `finally` block in `run_main_loop` (line 2538-2540) uses `CancelScope(shield=True)` for `transport.close()`, which correctly runs during cancellation. The `restore()` in the `finally` of `run_loop` is also no longer needed.

## Problem 2: Network Errors (ReadTimeout, ReadError) during getUpdates

### Assessment

These are **expected and benign**. Telegram long-polling uses a 50s timeout (`poll_incoming`, parsing.py:229). `ReadTimeout` means the connection sat idle for the poll timeout with no response — this is normal for long-polling when no updates arrive. `ReadError` means the TCP connection was reset (transient network blip).

The existing code already handles these correctly:
1. `_request` (client_api.py:240-250) catches `httpx.HTTPError` (which includes `ReadTimeout` and `ReadError`), logs at `error` level, and raises `TelegramRetryAfter(2.0)`.
2. `_call_with_retry_after` (client.py) catches `TelegramRetryAfter`, sleeps, and retries.
3. `poll_incoming` (parsing.py:226-245) loops `while True`, so the retry resumes polling.

**No code change needed.** The only improvement is to **downgrade the log level from `error` to `warning`** for transient network errors on `getUpdates` specifically, since they are expected during normal operation and the `error` level is noisy. This is a minor UX improvement, not a bug fix.

Optional: add a special case in `_request` or a wrapper that logs `getUpdates` network errors at `warning` instead of `error`, since they are self-healing.

## Problem 3: Unclosed Transport Warnings

### Assessment

The `_ProactorBasePipeTransport.__del__` warnings ("unclosed transport") are a downstream symptom of Problem 1 — the unclean shutdown from the cancel-scope crash prevents `transport.close()` from running properly, leaving httpx connections dangling. Fixing Problem 1 (clean shutdown) eliminates these warnings because `run_main_loop`'s `finally` block will execute correctly.

**No separate fix needed** — resolved by Problem 1 fix.

## Logging Options (Informational)

takopi has these logging controls (all env-var driven, no config-file option):

| Mechanism | How | Effect |
|---|---|---|
| `--debug` CLI flag | `takopi --debug` or `takopi run --debug` | Sets `TAKOPI_LOG_LEVEL=debug`, writes to `debug.log` |
| `TAKOPI_LOG_LEVEL` env var | `debug` / `info` / `warning` / `error` | Minimum log level (default: `info`) |
| `TAKOPI_LOG_FILE` env var | Path to file | Append logs to file |
| `TAKOPI_LOG_FORMAT` env var | `console` / `json` | Output format (default: console) |
| `TAKOPI_LOG_COLOR` env var | `1` / `0` | Force color on/off |
| `TAKOPI_TRACE_PIPELINE` env var | `1` / `0` | Show pipeline events at info level |

**There is no config-file option for constant/persistent logging.** To enable file logging without `--debug`, set `TAKOPI_LOG_FILE` in the environment:

```bat
set TAKOPI_LOG_FILE=C:\path\to\takopi.log
set TAKOPI_LOG_LEVEL=debug
takopi
```

Or in the `.bat` launcher. A config-file option (`[logging] file = ...`, `[logging] level = ...`) would be a separate feature request.

## Implementation Steps

### Step 1: Fix cancel-scope crash (backend.py)

- Remove `_install_sigint_cancel_handler` function (lines 85-104).
- Simplify `run_loop` to call `run_main_loop` directly without the manual `CancelScope` + SIGINT handler.
- Remove the `import signal` if it becomes unused.

### Step 2: Downgrade getUpdates network errors to warning (client_api.py)

- In `_request`, when `method == "getUpdates"`, log network errors at `warning` instead of `error`. Add a parameter or check.

### Step 3: Tests

- Test that SIGINT during `run_main_loop` produces a clean shutdown (no `RuntimeError`). This requires an integration test or a focused test on `run_loop`.
- The existing `test_telegram_polling.py` tests should still pass.

### Step 4: Changelog

## Verification

- Run `test_telegram_polling.py` and `test_telegram_bridge.py`.
- Manual: start takopi, send SIGINT (Ctrl+C), confirm clean exit (no traceback, no unclosed transport warnings).
