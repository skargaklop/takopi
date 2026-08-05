"""Tests for ``close_process_streams`` and shutdown transport cleanup.

Roadmap Task 5 (reqs 2-4): explicit transport close at every spawn site,
bounded shutdown, and regression coverage for the proactor pipe-transport
noise.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import pytest
from anyio import BrokenResourceError, ClosedResourceError

from takopi.utils.subprocess import DEFAULT_SHUTDOWN_TIMEOUT_S, close_process_streams


# ---------------------------------------------------------------------------
# Fake stream objects
# ---------------------------------------------------------------------------


@dataclass
class FakeStream:
    """Records aclose() calls and optionally raises or hangs."""

    name: str
    closed: bool = False
    raise_on_close: Exception | None = None
    hang_seconds: float = 0.0
    close_history: list[str] = field(default_factory=list, repr=False)

    async def aclose(self) -> None:
        if self.hang_seconds > 0:
            await anyio.sleep(self.hang_seconds)
        self.close_history.append(self.name)
        self.closed = True
        if self.raise_on_close is not None:
            raise self.raise_on_close


@dataclass
class FakeProc:
    """Minimal process stand-in with stdin/stdout/stderr stream attrs."""

    _stdin: FakeStream | None = None
    _stdout: FakeStream | None = None
    _stderr: FakeStream | None = None

    @property
    def stdin(self) -> FakeStream | None:
        return self._stdin

    @property
    def stdout(self) -> FakeStream | None:
        return self._stdout

    @property
    def stderr(self) -> FakeStream | None:
        return self._stderr


# ---------------------------------------------------------------------------
# Test 1: closes stdin, stdout, stderr
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_close_process_streams_closes_all_three() -> None:
    """close_process_streams closes stdin, stdout, stderr."""
    history: list[str] = []
    stdin = FakeStream(name="stdin", close_history=history)
    stdout = FakeStream(name="stdout", close_history=history)
    stderr = FakeStream(name="stderr", close_history=history)
    proc = FakeProc(stdin, stdout, stderr)

    await close_process_streams(proc)

    assert stdin.closed
    assert stdout.closed
    assert stderr.closed


# ---------------------------------------------------------------------------
# Test 2: error-tolerant and idempotent
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_close_process_streams_tolerates_errors() -> None:
    """Streams raising OSError/ValueError/ClosedResourceError -> no raise."""
    stdin = FakeStream(name="stdin", raise_on_close=OSError("boom"))
    stdout = FakeStream(name="stdout", raise_on_close=ValueError("bad"))
    stderr = FakeStream(name="stderr", raise_on_close=ClosedResourceError())
    proc = FakeProc(stdin, stdout, stderr)

    # Must not raise.
    await close_process_streams(proc)


@pytest.mark.anyio
async def test_close_process_streams_tolerates_broken_resource() -> None:
    """BrokenResourceError is also swallowed."""
    stdin = FakeStream(name="stdin", raise_on_close=BrokenResourceError())
    proc = FakeProc(stdin, None, None)

    await close_process_streams(proc)
    assert stdin.closed


@pytest.mark.anyio
async def test_close_process_streams_idempotent() -> None:
    """Second call is a no-op, not an error."""
    stdin = FakeStream(name="stdin")
    stdout = FakeStream(name="stdout")
    stderr = FakeStream(name="stderr")
    proc = FakeProc(stdin, stdout, stderr)

    await close_process_streams(proc)
    # Second call must not raise even though streams are already closed.
    await close_process_streams(proc)


@pytest.mark.anyio
async def test_close_process_streams_handles_none_streams() -> None:
    """None streams (e.g. stdin=None) are handled gracefully."""
    proc = FakeProc(None, None, None)
    await close_process_streams(proc)  # must not raise


# ---------------------------------------------------------------------------
# Test 3: bounded — a hanging stream returns within the timeout
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_close_process_streams_bounded_by_timeout() -> None:
    """A stream whose aclose() hangs -> returns within the timeout."""
    from anyio import move_on_after

    # stdin hangs for 10s; we bound the close at 0.1s.
    stdin = FakeStream(name="stdin", hang_seconds=10.0)
    stdout = FakeStream(name="stdout")
    stderr = FakeStream(name="stderr")
    proc = FakeProc(stdin, stdout, stderr)

    start = time.monotonic()
    with move_on_after(5.0):
        await close_process_streams(proc, timeout=0.1)
    elapsed = time.monotonic() - start

    # Should return well under the outer guard.
    assert elapsed < 2.0
    # stdout/stderr may or may not have been reached depending on per-stream
    # timeout semantics, but the overall call must not hang.


@pytest.mark.anyio
async def test_close_process_streams_per_stream_timeout() -> None:
    """Each stream gets its own timeout — a fast stream after a slow one still closes."""
    slow = FakeStream(name="slow", hang_seconds=10.0)
    fast = FakeStream(name="fast")
    proc = FakeProc(slow, fast, None)

    start = time.monotonic()
    await close_process_streams(proc, timeout=0.15)
    elapsed = time.monotonic() - start

    # slow timed out (~0.15s), fast closed (~0s) -> total ~0.15s, not 10s+.
    assert elapsed < 1.0
    assert fast.closed


# ---------------------------------------------------------------------------
# Test 4: DEFAULT_SHUTDOWN_TIMEOUT_S constant exists
# ---------------------------------------------------------------------------


def test_default_shutdown_timeout_constant() -> None:
    """The module exposes a DEFAULT_SHUTDOWN_TIMEOUT_S constant."""
    assert DEFAULT_SHUTDOWN_TIMEOUT_S == 5.0


# ---------------------------------------------------------------------------
# Test 5: manage_subprocess closes streams on cancellation
# (integration — real subprocess, in-process warning capture)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_manage_subprocess_no_resource_warnings_on_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After manage_subprocess exits under cancellation, the pipe streams
    should have been explicitly closed (no ResourceWarning for the transports).

    We let the subprocess actually start, then cancel the scope so the
    ``finally`` block runs. We assert that ``close_process_streams`` was
    invoked during cleanup.
    """
    from takopi.utils import subprocess as subprocess_utils

    closed_flag: list[bool] = []
    original_close = subprocess_utils.close_process_streams

    async def tracking_close(proc: object, **kwargs: object) -> None:
        closed_flag.append(True)
        await original_close(proc, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess_utils, "close_process_streams", tracking_close)

    with anyio.move_on_after(5) as scope:
        async with subprocess_utils.manage_subprocess(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        ) as proc:
            # Let the process actually start.
            assert proc.pid is not None
            await anyio.sleep(0.1)
            scope.cancel()
            await proc.wait()

    assert closed_flag, "close_process_streams was not called during cleanup"


# ---------------------------------------------------------------------------
# Test 6: child-interpreter regression test (req 4)
# THE regression guard: spawns a child python that runs manage_subprocess,
# self-cancels, and exits. Asserts child stderr has no deallocator noise.
# This must be a child process — the noise only fires at real teardown.
# ---------------------------------------------------------------------------


_CHILD_SCRIPT = """\
import anyio
from takopi.utils.subprocess import manage_subprocess
import sys

async def main():
    async with anyio.create_task_group() as tg:
        async def spawn():
            async with manage_subprocess(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=None,
                stdout=None,
                stderr=None,
            ) as proc:
                await proc.wait()
        tg.start_soon(spawn)
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

anyio.run(main)
"""


@pytest.mark.anyio
async def test_child_interpreter_no_deallocator_noise(tmp_path: Path) -> None:
    """A child interpreter that starts a subprocess via manage_subprocess,
    self-cancels, and exits — its stderr must contain no
    'Exception ignored' or 'unclosed transport' noise.

    This is the real regression guard (req 4): the deallocator noise only
    triggers at real interpreter teardown, never in-process.
    """
    script = tmp_path / "child.py"
    script.write_text(_CHILD_SCRIPT, encoding="utf-8")

    result = await anyio.run_process(
        [sys.executable, "-W", "error::ResourceWarning", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    stderr = result.stderr.decode("utf-8", errors="replace")
    assert "Exception ignored" not in stderr, (
        f"Deallocator noise in child stderr:\n{stderr}"
    )
    assert "unclosed transport" not in stderr.lower(), (
        f"Unclosed transport warning in child stderr:\n{stderr}"
    )


# ---------------------------------------------------------------------------
# Test 7: Codex app-server stop() closes process streams (unit-level)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_codex_appserver_stop_closes_streams() -> None:
    """_AppServerClient.stop() closes the process streams after kill+wait."""
    from takopi.runners.codex import _AppServerClient

    stdin = FakeStream(name="stdin")
    stdout = FakeStream(name="stdout")
    stderr = FakeStream(name="stderr")

    class FakeAnyioProc:
        """Minimal anyio Process stand-in with already-exited child."""

        def __init__(self) -> None:
            self._stdin = stdin
            self._stdout = stdout
            self._stderr = stderr

        @property
        def stdin(self):
            return self._stdin

        @property
        def stdout(self):
            return self._stdout

        @property
        def stderr(self):
            return self._stderr

        @property
        def pid(self):
            return 99999

        @property
        def returncode(self):
            return 0  # already exited — stop() skips kill/wait

        async def wait(self):
            return 0

        def kill(self):
            pass

        def terminate(self):
            pass

    client = _AppServerClient(codex_cmd="fake-codex", extra_args=[])
    client._proc = FakeAnyioProc()

    await client.stop()

    assert stdin.closed, "stdin was not closed by stop()"
    assert stdout.closed, "stdout was not closed by stop()"
    assert stderr.closed, "stderr was not closed by stop()"
    assert client._proc is None
