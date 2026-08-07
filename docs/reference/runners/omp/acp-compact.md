# OMP ACP Compact — Evidence Record

**Date:** 2026-08-07
**Status:** Handoff-only (not enabled)

## CLI

- Command: `omp acp`
- Version: `omp/17.2.10`
- Entry point verified: `omp acp --help` exists.

## ACP Compact Probe

**Result:** SKIPPED — no `TAKOPI_OMP_ACP_SESSION_ID` provided.

Without an existing session ID, the live ACP compact probe cannot run.
The production transport (`SubprocessAcpTransport`) ships and is verified
via unit and integration tests, but OMP remains `handoff_only`
(`true_compaction=False`) until an independent live smoke passes.

## Requirements for Enabling

1. Set `TAKOPI_OMP_ACP_SESSION_ID` to an existing OMP session.
2. Run `uv run pytest -q --no-cov -m live_acp tests/test_omp_compact_acp.py`.
3. The probe must confirm:
   - `initialize` selects protocol version 1.
   - `session/load` or `session/resume` succeeds for the existing session.
   - The `compact` command is advertised in `available_commands_update`.
   - `/compact <marker>` does NOT echo the marker in `agent_message_chunk`.
   - An explicit harness compaction lifecycle/update signal is present
     (not just `end_turn`, silence, or token heuristics).
4. Only then replace `HandoffCompactMixin` with `AcpCompactMixin` on
   `OmpRunner` and set `mode="acp"`, `true_compaction=True`.
