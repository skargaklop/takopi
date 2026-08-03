from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import anyio
from anyio.abc import Process

from ..logging import get_logger

logger = get_logger(__name__)


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


def _signal_process(
    proc: Process,
    sig: signal.Signals | None,
    *,
    fallback: Callable[[], None],
    log_event: str,
) -> None:
    if proc.returncode is not None:
        return
    if os.name == "posix" and proc.pid is not None:
        try:
            os.killpg(proc.pid, sig)
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


@asynccontextmanager
async def manage_subprocess(
    cmd: Sequence[str], **kwargs: Any
) -> AsyncIterator[Process]:
    """Ensure subprocesses and their descendants are killed on cleanup.

    POSIX: SIGTERM → 2s grace → SIGKILL the process group.
    Windows: immediate ``taskkill /T /F`` (TerminateProcess only kills
    the direct child, leaving grandchildren orphaned).
    """
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
