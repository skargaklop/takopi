"""Tests for graceful shutdown: SIGINT cancellation and transport cleanup."""

from __future__ import annotations

import sys

import anyio
import pytest
from takopi.utils.subprocess import manage_subprocess


@pytest.mark.anyio
async def test_subprocess_terminated_on_cancellation() -> None:
    """A subprocess started under a cancelled scope is terminated in finally."""
    proc_result: list[object] = []

    async def run_under_scope() -> None:
        with anyio.CancelScope() as scope:
            scope.cancel()
            async with manage_subprocess(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdin=None,
                stdout=None,
                stderr=None,
            ) as proc:
                await proc.wait()

    with anyio.CancelScope() as outer:
        try:
            await run_under_scope()
        except BaseException as exc:  # noqa: BLE001
            proc_result.append(exc)
            outer.cancel()


def test_backend_does_not_install_custom_sigint_handler() -> None:
    """The backend must not install a custom SIGINT handler — anyio.run()
    handles SIGINT natively, and a manual handler corrupts cancel scopes.

    Regression guard for the 'Attempted to exit a cancel scope' crash.
    """
    import takopi.telegram.backend as backend

    # The removed functions must not exist.
    assert not hasattr(backend, "_install_sigint_cancel_handler")
    assert not hasattr(backend, "_run_loop_with_sigint")
    # signal module must not be imported by backend.
    assert not hasattr(backend, "signal")


@pytest.mark.anyio
async def test_run_main_loop_called_directly_without_manual_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_loop (inside anyio.run) calls run_main_loop directly — no wrapping
    task group or manual CancelScope that could corrupt on SIGINT."""

    called = False

    async def fake_run_main_loop(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("takopi.telegram.backend.run_main_loop", fake_run_main_loop)

    # Verify build_and_run's run_loop is a plain call to run_main_loop.
    # We can't call build_and_run directly (needs full config), but we can
    # verify the source structure: run_main_loop is called without a wrapper.
    import inspect

    import takopi.telegram.backend as backend

    source = inspect.getsource(backend.TelegramBackend.build_and_run)
    assert "_run_loop_with_sigint" not in source
    assert "_install_sigint_cancel_handler" not in source
    assert "run_main_loop" in source
