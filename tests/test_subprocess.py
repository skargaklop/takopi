import os
import sys
from pathlib import Path

import anyio
import pytest

from takopi.utils import subprocess as subprocess_utils


@pytest.mark.anyio
async def test_manage_subprocess_kills_when_terminate_times_out(
    monkeypatch,
) -> None:
    async def fake_wait_for_process(_proc, timeout: float) -> bool:
        _ = timeout
        return True

    monkeypatch.setattr(subprocess_utils, "wait_for_process", fake_wait_for_process)

    async with subprocess_utils.manage_subprocess(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)",
        ]
    ) as proc:
        assert proc.returncode is None

    assert proc.returncode is not None
    assert proc.returncode != 0


def _is_process_alive(pid: int) -> bool:
    """Check if a process is alive, cross-platform."""
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
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
        return True


@pytest.mark.anyio
async def test_manage_subprocess_kills_process_tree(tmp_path: Path) -> None:
    """On cancellation, the entire process tree must be killed, not just the wrapper."""
    marker = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time, pathlib\n"
        "p = subprocess.Popen("
        "[sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid))\n"
        "time.sleep(300)\n"
    )
    cmd = [sys.executable, "-c", script]

    with anyio.move_on_after(5):
        async with subprocess_utils.manage_subprocess(cmd) as proc:
            assert proc.pid is not None
            while not marker.exists():
                await anyio.sleep(0.05)

    assert marker.exists(), "child did not start before cleanup"
    child_pid = int(marker.read_text())
    await anyio.sleep(0.3)
    assert not _is_process_alive(child_pid), (
        f"child {child_pid} survived cleanup"
    )
