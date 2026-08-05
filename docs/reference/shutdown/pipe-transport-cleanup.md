# Pipe-Transport Cleanup on Shutdown

Investigation findings for Roadmap Task 5 (shutdown transport close).
Source: anyio 4.12.0, CPython 3.14, Windows ProactorEventLoop.

## 1. anyio `Process` hierarchy

`anyio.abc.Process` extends `anyio.abc.AsyncResource`, so it has an
`aclose()` method. The concrete asyncio backend implementation lives in
`anyio._backends._asyncio.Process`.

### `Process.aclose()` (asyncio backend)

```python
async def aclose(self) -> None:
    with CancelScope(shield=True) as scope:
        if self._stdin:
            await self._stdin.aclose()
        if self._stdout:
            await self._stdout.aclose()
        if self._stderr:
            await self._stderr.aclose()

        scope.shield = False
        try:
            await self.wait()
        except BaseException:
            scope.shield = True
            self.kill()
            await self.wait()
            raise
```

Key observations:

- **`aclose()` closes all three stdio streams in sequence, then waits for
  the process to exit.** It is not a stream-only close — it includes a
  `wait()` at the end.
- The initial `shield=True` protects the stream closes from external
  cancellation; it is dropped to `False` before `wait()` so the wait CAN be
  cancelled. On cancellation it kills + waits again (shielded).
- The `wait()` at the end means `aclose()` can block if the child process
  never exits — but in our shutdown path the process is already killed and
  reaped before we close streams, so `wait()` returns immediately.

### `Process.wait()` (asyncio backend)

```python
async def wait(self) -> int:
    return await self._process.wait()
```

**`wait()` does NOT close any transports.** It only waits for the child to
exit and returns the exit code. The underlying `asyncio.subprocess.Process`
transport is left open.

### Stream wrapper `aclose()`

The stream properties (`stdin`, `stdout`, `stderr`) are wrapper objects:

| Wrapper | `aclose()` does |
|---------|-----------------|
| `StreamWriterWrapper` (stdin) | Sets `_closed = True`, calls `self._stream.close()` (closes the underlying `asyncio.StreamWriter` → transport), checkpoints. |
| `StreamReaderWrapper` (stdout/stderr) | Sets `ClosedResourceError` exception on the `asyncio.StreamReader`, checkpoints. Does NOT close the transport directly — the transport is owned by the process/subprocess-transport. |

**Critical detail:** closing `stdin` via the wrapper DOES close the write
transport (because `StreamWriter.close()` calls `_transport.close()`). But
closing `stdout`/`stderr` via the reader wrapper does NOT close the read
transports — it only signals `EndOfStream` to readers.

## 2. Where the noise comes from

On CPython 3.14 + Windows ProactorEventLoop:

1. The child is killed (`taskkill /T /F`) and reaped (`proc.wait()`).
2. The `Process` object and its transport wrappers fall out of scope and
   are garbage-collected at interpreter teardown.
3. `_ProactorBasePipeTransport.__del__` fires a `ResourceWarning`
   ("unclosed transport") and, during `__repr__`, touches `fileno()` on an
   already-closed pipe handle → `ValueError: I/O operation on closed pipe`
   printed as "Exception ignored in: ...".

The fix: **explicitly close the transports before teardown.** Since the
reader-wrapper `aclose()` does not close read transports, the most reliable
approach is to call the underlying asyncio subprocess transport's
`close()`/`terminate()` via `Process.aclose()` (which does the full
sequence) OR to close each stream wrapper individually (for stdin this
closes the transport; for stdout/stderr it prevents reader tasks from
racing, and the GC-warning is suppressed because the wrapper is marked
consumed).

**Decision:** call `Process.aclose()` is NOT ideal in our path because it
includes a `wait()` that could block on a wedged process and our callers
already do kill→wait. Instead, we close each stream wrapper individually
with a per-stream timeout bound, which closes the stdin transport directly
and marks the reader streams as consumed. This matches what
`_forcibly_shutdown_process_pool_on_exit` does internally (it calls
`_transport.close()` on each stream). If a stream wrapper lacks a
transport accessor, we fall back to its `aclose()`.

## 3. CPython 3.14 proactor notes

- `_ProactorBasePipeTransport.__del__` emits a `ResourceWarning` if the
  transport was never `.close()`'d. On 3.14 the `__repr__` used during the
  warning message accesses `self._fileno` which may already be `-1`
  (closed) → the secondary `ValueError`.
- Calling `_transport.close()` before the object is GC'd prevents the
  `ResourceWarning` entirely.
- The `__del__` is triggered at real interpreter teardown, never in-process
  — this is why in-process `ResourceWarning` capture is insufficient and
  the regression test must use a child interpreter.

## 4. Implications for `close_process_streams`

1. Close `stdin` first (it owns the write transport; closing it prevents
   further writes and the write-transport `ResourceWarning`).
2. Close `stdout`/`stderr` (marks readers consumed; the read transports
   are owned by the subprocess transport and are closed when the process
   object's transport is closed — which happens implicitly when the
   `asyncio.subprocess.Process` is GC'd AFTER the streams are closed, or
   when the subprocess transport itself is closed).
3. Per-stream timeout bound is mandatory: a wedged pipe should not hang
   shutdown.
4. Tolerate `OSError`, `ValueError`, `ClosedResourceError`,
   `BrokenResourceError` — these are expected if the stream was already
   closed or the pipe is broken after kill.
5. Idempotent: a second call must be a no-op, not raise.
