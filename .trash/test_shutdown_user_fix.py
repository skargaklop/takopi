"""Tests for graceful shutdown: SIGINT cancellation and transport cleanup."""

from __future__ import annotations

import signal
import sys

import anyio
import pytest

from takopi.telegram.backend import (
    _install_sigint_cancel_handler,
    _run_loop_with_sigint,
)
from takopi.utils.subprocess import manage_subprocess


@pytest.mark.anyio
async def test_sigint_handler_cancels_scope() -> None:
    """Installing the SIGINT handler and triggering it cancels the scope."""
    with anyio.CancelScope() as scope:
        restore = _install_sigint_cancel_handler(scope)
        try:
            handler = signal.getsignal(signal.SIGINT)
            assert callable(handler)
            handler(signal.SIGINT, None)
            assert scope.cancel_called is True
        finally:
            restore()


@pytest.mark.anyio
async def test_sigint_handler_restores_previous() -> None:
    """The restore callback puts back the original signal handler."""
    original = signal.getsignal(signal.SIGINT)
    with anyio.CancelScope() as scope:
        restore = _install_sigint_cancel_handler(scope)
        assert signal.getsignal(signal.SIGINT) is not original
        restore()
    assert signal.getsignal(signal.SIGINT) is original


@pytest.mark.anyio
async def test_subprocess_terminated_on_cancellation() -> None:
    """A subprocess started under a cancelled scope is terminated in finally."""
    proc_result: list[anyio.abc.Process] = []

    async def run_subprocess_scope() -> None:
        with anyio.CancelScope() as scope:
            async with manage_subprocess(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            ) as proc:
                proc_result.append(proc)
                scope.cancel()
                await anyio.sleep_forever()

    await run_subprocess_scope()

    assert len(proc_result) == 1
    assert proc_result[0].returncode is not None


@pytest.mark.anyio
async def test_run_loop_sigint_cancels_task_group_without_scope_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIGINT during the live loop must unwind without a cancel-scope error."""

    async def fake_run_main_loop(*_args: object, **_kwargs: object) -> None:
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        await anyio.sleep_forever()

    monkeypatch.setattr("takopi.telegram.backend.run_main_loop", fake_run_main_loop)

    await _run_loop_with_sigint(
        object(),
        watch_config=None,
        default_engine_override=None,
        transport_id="telegram",
        transport_config=None,
    )
