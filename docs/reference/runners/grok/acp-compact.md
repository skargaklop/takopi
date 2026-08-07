# Grok ACP Compact — Evidence Record

**Date:** 2026-08-07
**Status:** Handoff-only (not enabled)

## CLI

- Command: `grok agent stdio`
- Version: `grok 0.2.118 (1e1687c1cf)`
- Entry point verified: `grok agent stdio --help` exists.

## ACP Compact Probe

**Result:** SKIPPED — no `TAKOPI_GROK_ACP_SESSION_ID` provided.

Without an existing session ID, the live ACP compact probe cannot run.
The production transport (`SubprocessAcpTransport`) ships and is verified
via unit and integration tests, but Grok remains `handoff_only`
(`true_compaction=False`) until an independent live smoke passes.

## Requirements for Enabling

1. Set `TAKOPI_GROK_ACP_SESSION_ID` to an existing Grok session.
2. Run `uv run pytest -q --no-cov -m live_acp tests/test_grok_compact_acp.py`.
3. The probe must confirm:
   - `initialize` selects protocol version 1.
   - `session/load` or `session/resume` succeeds for the existing session.
   - The `compact` command is advertised in `available_commands_update`.
   - `/compact <marker>` does NOT echo the marker in `agent_message_chunk`.
   - An explicit harness compaction lifecycle/update signal is present
     (not just `end_turn`, silence, or token heuristics).
4. Only then replace `HandoffCompactMixin` with `AcpCompactMixin` on
   `GrokRunner` and set `mode="acp"`, `true_compaction=True`.
