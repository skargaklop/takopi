"""Live ACP compact smoke test for Grok.

Requires ``grok`` on PATH and ``TAKOPI_GROK_ACP_SESSION_ID`` set to an
existing session. Skipped otherwise.

Genuine interception requires an explicit harness compaction lifecycle
signal; ``end_turn``, silence, or token heuristics alone are insufficient.
"""

from __future__ import annotations

import os
import uuid

import pytest

grok = pytest.importorskip("shutil").which("grok")
_SESSION_ID = os.environ.get("TAKOPI_GROK_ACP_SESSION_ID")

pytestmark = pytest.mark.live_acp


@pytest.mark.skipif(
    not _SESSION_ID,
    reason="TAKOPI_GROK_ACP_SESSION_ID not set; cannot probe live ACP",
)
@pytest.mark.anyio
async def test_grok_acp_compact_live() -> None:
    """Probe Grok ACP compact against an existing session."""
    from takopi.runners._acp import AcpClient, AcpCommandUnavailableError

    assert _SESSION_ID is not None  # guarded by skipif
    marker = f"takopi-live-smoke-{uuid.uuid4().hex[:8]}"
    async with AcpClient(
        command="grok",
        args=["agent", "stdio"],
        cwd=os.getcwd(),
        close_timeout_s=10.0,
        request_timeout_s=60.0,
    ) as client:
        await client.initialize()
        await client.resume_or_load(_SESSION_ID)
        await client.wait_for_available_commands()
        try:
            await client.require_command("compact")
        except AcpCommandUnavailableError:
            pytest.skip("Grok ACP agent does not advertise 'compact'")

        updates = [u async for u in client.prompt(_SESSION_ID, f"/compact {marker}")]
        # The marker must NOT appear in any agent output (genuine interception).
        for update in updates:
            assert marker not in update.text, (
                "Grok echoed the compact marker — interception not confirmed"
            )
