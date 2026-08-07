"""Tests for Grok and OMP ACP compact candidate factory parameters.

Both runners currently use ``HandoffCompactMixin`` (handoff-only) until
live ACP evidence is recorded.  These tests verify the candidate factory
parameters that would be used if ACP compaction is enabled.
"""

from __future__ import annotations

import pytest

from takopi.runners._acp import AcpClient


def test_grok_candidate_factory_params() -> None:
    """Grok ACP client uses grok agent stdio with lifecycle timeouts."""
    from takopi.runners.grok import GrokRunner

    runner = GrokRunner()
    # Candidate factory would produce:
    client = AcpClient(
        command=runner.grok_cmd,
        args=["agent", "stdio"],
        cwd=None,
        close_timeout_s=runner.shutdown_timeout_s,
        request_timeout_s=runner.startup_timeout_s or 60.0,
    )
    assert client.command == "grok"
    assert client.args == ["agent", "stdio"]
    assert client.close_timeout_s == runner.shutdown_timeout_s


def test_omp_candidate_factory_params() -> None:
    """OMP ACP client uses omp acp with lifecycle timeouts."""
    from takopi.runners.omp import OmpRunner

    runner = OmpRunner.__new__(OmpRunner)
    runner.extra_args = []
    runner.model = None
    runner.provider = None
    runner.plan_mode = "soft"
    # Candidate factory would produce:
    client = AcpClient(
        command=runner.command(),
        args=["acp"],
        cwd=None,
        close_timeout_s=runner.shutdown_timeout_s,
        request_timeout_s=runner.startup_timeout_s or 60.0,
    )
    assert client.command == "omp"
    assert client.args == ["acp"]


@pytest.mark.anyio
async def test_shutdown_timeout_propagation(tmp_path) -> None:
    """JsonlSubprocessRunner.shutdown_timeout_s defaults exist and propagate."""
    from takopi.runner import JsonlSubprocessRunner
    from takopi.utils.subprocess import DEFAULT_SHUTDOWN_TIMEOUT_S

    assert JsonlSubprocessRunner.shutdown_timeout_s == DEFAULT_SHUTDOWN_TIMEOUT_S


def test_grok_remains_handoff_only() -> None:
    """Grok stays handoff-only without live ACP evidence."""
    from takopi.compact import CompactSupport
    from takopi.runners.grok import GrokRunner

    runner = GrokRunner()
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "handoff_only"
    assert support.true_compaction is False


def test_omp_remains_handoff_only() -> None:
    """OMP stays handoff-only without live ACP evidence."""
    from takopi.compact import CompactSupport
    from takopi.runners.omp import OmpRunner

    runner = OmpRunner.__new__(OmpRunner)
    runner.extra_args = []
    runner.model = None
    runner.provider = None
    runner.plan_mode = "soft"
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "handoff_only"
    assert support.true_compaction is False
