from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from typing import Any

import anyio
from anyio import BrokenResourceError, ClosedResourceError
from anyio.abc import Process

from ..logging import get_logger

logger = get_logger(__name__)

#: Default per-stream close timeout (seconds). Shutdown must never hang on
#: a wedged pipe; each stream close is individually bounded by this value
#: (or the ``close_timeout`` override). Configurable globally via
#: ``RunnerSettings.shutdown_timeout_s``.
DEFAULT_SHUTDOWN_TIMEOUT_S: float = 5.0


async def wait_for_process(proc: Process, timeout: float) -> bool:
    with anyio.move_on_after(timeout) as scope:
        await proc.wait()
    return scope.cancel_called


def terminate_process(proc: Process) -> None:
    _signal_process(
        proc,
        signal.SIGTERM,
        fallback=proc.terminate,
        log_event="subprocess.terminate.failed",
    )


def kill_process(proc: Process) -> None:
    _signal_process(
        proc,
        getattr(signal, "SIGKILL", None),
        fallback=proc.kill,
        log_event="subprocess.kill.failed",
    )


async def kill_process_tree(proc: Process) -> None:
    """Kill the process and all its descendants.

    On Windows uses ``taskkill /T /F`` which walks the OS process tree by
    parent-PID. On POSIX delegates to :func:`kill_process` which already
    uses ``os.killpg`` for process-group kills.
    """
    if proc.pid is None or proc.returncode is not None:
        return
    if os.name == "nt":
        try:
            await anyio.run_process(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except FileNotFoundError:
            kill_process(proc)
        return
    kill_process(proc)


def _kill_process_group(pid: int, sig: signal.Signals) -> None:
    """Send *sig* to the POSIX process group of *pid* via ``os.killpg``.

    ``os.killpg`` is POSIX-only; resolving it dynamically keeps the module
    importable (and type-checkable) on Windows, where callers never invoke it.
    """
    killpg = getattr(os, "killpg", None)
    if killpg is None:  # pragma: no cover - non-POSIX platform
        return
    killpg(pid, sig)


def _signal_process(
    proc: Process,
    sig: signal.Signals | None,
    *,
    fallback: Callable[[], None],
    log_event: str,
) -> None:
    if proc.returncode is not None:
        return
    if os.name == "posix" and proc.pid is not None and sig is not None:
        try:
            _kill_process_group(proc.pid, sig)
            return
        except ProcessLookupError:
            return
        except OSError as exc:
            logger.debug(
                log_event,
                error=str(exc),
                error_type=exc.__class__.__name__,
                pid=proc.pid,
            )
    try:
        fallback()
    except ProcessLookupError:
        return


async def close_process_streams(
    proc: Any, *, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_S
) -> None:
    """Explicitly close the stdio pipe transports of *proc*.

    On Windows + ProactorEventLoop, asyncio pipe transports that are never
    explicitly closed are GC'd at interpreter teardown; ``__del__`` issues a
    ``ResourceWarning`` whose ``__repr__`` touches ``fileno()`` on a closed
    pipe, producing the "Exception ignored … ValueError: I/O operation on
    closed pipe" noise. This helper closes stdin first (it owns the write
    transport), then stdout/stderr, so the transports are properly
    disposed before teardown.

    *proc* is typed :data:`typing.Any` rather than :class:`Process` because
    the function accesses streams dynamically via ``getattr`` and must
    accept both real anyio ``Process`` objects and test fakes.

    The function is:

    - **Error-tolerant**: swallows ``OSError``, ``ValueError``,
      ``ClosedResourceError``, and ``BrokenResourceError`` — expected when
      the stream was already closed or the pipe broke after kill.
    - **Bounded**: each stream close is individually wrapped in
      ``anyio.move_on_after(timeout)`` so a wedged pipe cannot hang
      shutdown.
    - **Idempotent**: a second call is a no-op (closed streams raise, which
      is swallowed).
    - **Never raises**: always returns normally.
    """
    streams: list[Any] = []
    for attr in ("stdin", "stdout", "stderr"):
        stream = getattr(proc, attr, None)
        if stream is not None:
            streams.append(stream)
    for stream in streams:
        with (
            anyio.move_on_after(timeout),
            suppress(OSError, ValueError, ClosedResourceError, BrokenResourceError),
        ):
            await stream.aclose()


@asynccontextmanager
async def manage_subprocess(
    cmd: Sequence[str],
    *,
    close_timeout: float | None = None,
    **kwargs: Any,
) -> AsyncIterator[Process]:
    """Ensure subprocesses and their descendants are killed on cleanup.

    POSIX: SIGTERM → 2s grace → SIGKILL the process group.
    Windows: immediate ``taskkill /T /F`` (TerminateProcess only kills
    the direct child, leaving grandchildren orphaned).

    After kill + wait, the stdio pipe transports are explicitly closed via
    :func:`close_process_streams` (bounded by *close_timeout*, default
    :data:`DEFAULT_SHUTDOWN_TIMEOUT_S`) to prevent the proactor
    "Exception ignored … ValueError: I/O operation on closed pipe" noise
    at interpreter teardown.
    """
    if close_timeout is None:
        close_timeout = DEFAULT_SHUTDOWN_TIMEOUT_S
    if os.name == "posix":
        kwargs.setdefault("start_new_session", True)
    elif os.name == "nt":
        kwargs.setdefault(
            "creationflags",
            subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    proc = await anyio.open_process(cmd, **kwargs)
    try:
        yield proc
    finally:
        if proc.returncode is None:
            with anyio.CancelScope(shield=True):
                if os.name == "nt":
                    # On Windows, terminate() only kills the direct child.
                    # Kill the entire tree immediately via taskkill /T /F.
                    await kill_process_tree(proc)
                    await proc.wait()
                else:
                    terminate_process(proc)
                    timed_out = await wait_for_process(proc, timeout=2.0)
                    if timed_out:
                        await kill_process_tree(proc)
                        await proc.wait()
        # Explicitly close the stdio pipe transports to prevent the proactor
        # __del__ ResourceWarning / ValueError noise at teardown. Shielded so
        # the close runs even under cancellation (the whole point of this
        # cleanup is shutdown / Ctrl+C resilience).
        with anyio.CancelScope(shield=True):
            await close_process_streams(proc, timeout=close_timeout)
