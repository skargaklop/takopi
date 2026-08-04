# Compact Production Failure - Gap-Closure Plan

> Supersedes the open items of `2026-08-04-compact-dispatch-robustness.md`
> (implemented in `4669620`). Trigger: live report 2026-08-04 - replying
> `/compact` (bare) to an `omp` session produced no visible result, and
> `/compact compact` was delivered to the agent as a plain-text prompt.
> Roadmap Task 1 requirements 4-6 cover this plan.

**Goal:** Make `/compact` actually work and be visibly honest in production for
every engine, starting with `omp`/`grok`; eliminate silent compact jobs; make
deployment verifiable.

**Tech Stack:** Python 3.14, anyio, pytest, ruff, ty, uv.

---

## Verified Evidence (no speculation)

1. **Stale installed artifact.** The uv-tools package at
   `%APPDATA%/uv/tools/takopi/Lib/site-packages/takopi` has file dates
   2026-08-02 13:32: no `parse_compact_invocation` in `telegram/loop.py`, no
   `telegram/commands/compact.py`, no `"compact"` in `prompt_batch.py`
   `CONTROL_COMMANDS`. The bridge process restarted 2026-08-04 22:28:17 (after
   commit `4669620` at 22:26:58) but kept executing the 2026-08-02 build.
   The rebuild did not update the installed artifact.
2. **ACP compact is a test-only stub.** The only transport in the tree is
   `FakeAcpTransport` (`src/takopi/runners/_acp.py:41`). `omp` and `grok` never
   override `create_acp_client`; the base returns `AcpClient(transport=None)`,
   and `_resolve_transport` raises
   `RuntimeError("Subprocess ACP transport not yet implemented")`
   (`_acp.py:167-170`). Production ACP compact can never succeed.
3. **Total failure silence.** `AcpCompactMixin.compact()` catches every
   exception and yields `CompletedEvent(ok=False, error=...)`
   (`_acp.py:218-224`); `run_compact_job` discards every event
   (`loop.py:1695-1696`, `async for ... : pass`). The `except` error-reply in
   `run_compact_job` only fires for runners whose `compact()` raises - ACP
   runners never raise. Successes are equally invisible (no ack, no completion
   notice).
4. **Plain-text passthrough.** `/compact compact` reached the omp model as a
   user-turn text (agent reply quoted it). On the 2026-08-02 build this came
   from the prompt batcher (`compact` absent from `CONTROL_COMMANDS`). It also
   proves the harness treats `/compact` prompt text as plain input, so even a
   working ACP transport would need harness-side interception for real
   compaction (Task 6).
5. **Duplicate-instance anomaly.** Two `python.exe takopi.exe` processes were
   observed with identical start timestamps. Duplicate pollers split
   `get_updates` and cause intermittent "nothing happens" reports.

## Root Causes

- R1: Rebuild procedure did not deploy (stale uv wheel/cache or wrong source);
  no post-install verification existed.
- R2: `omp`/`grok` declare `mode="acp"`, `true_compaction=True` with no
  production transport - a dishonest capability declaration.
- R3: Compact jobs are silent by construction (event discarding +
  exception-to-event conversion + `notify=False`-only error path).
- R4: (Fixed in `4669620`, kept as regression guard) batcher swallowed
  `/compact <instructions>`.

## Tasks (TDD)

### Task A - Failing tests (RED)

Extend `tests/test_telegram_compact_dispatch.py` (loop-level, existing fakes):

1. Handoff runner session (agy-class double delegating `compact()` to `run()`):
   reply `/compact` -> `run()` receives exactly `handoff_prompt(instructions)`;
   user gets a visible ack and a completion notice.
2. `compact()` raises `RuntimeError` -> user-visible failure reply,
   `notify=True`.
3. `compact()` yields `CompletedEvent(ok=False, error="boom")` without raising
   -> user-visible failure reply (covers the ACP-shaped failure mode).
4. Success with `true_compaction=False` -> completion text says handoff, not
   "compacted" (honest wording guard).

Extend `tests/test_omp_runner.py` and `tests/test_grok_runner.py`:

5. `compact_support()` returns `mode="handoff_only"`, `true_compaction=False`.
6. `compact()` delegates to `run()` with the `handoff_prompt` text.

### Task B - Implementation (GREEN)

**B1. Shared handoff mixin (DRY).** Add `HandoffCompactMixin` to
`src/takopi/runners/_compact_mixin.py` next to `SlashCompactMixin`:
`compact_support()` -> `CompactSupport(mode="handoff_only",
accepts_instructions=True, true_compaction=False, note=<overridable>)`;
`compact()` -> `run(handoff_prompt(instructions), resume)`. Migrate `agy` to
the mixin (preserve its exact `note` via class attr) and swap
`AcpCompactMixin` for `HandoffCompactMixin` in `OmpRunner` and `GrokRunner`.
Leave `_acp.py` in place for Task 6; mark its module docstring "test-only
until Task 6".

**B2. Lifecycle feedback in `run_compact_job` (`loop.py`).** Consume events;
track the terminal `CompletedEvent`. On success reply with an honest short
status ("compaction completed." when `true_compaction`, else "handoff summary
finished."); on `ok=False` or exception reply "compact failed: <error>" with
`notify=True`. Do not echo the model answer (the handoff summary is for the
next agent turn, not the user).

**B3. Ack on enqueue (`commands/compact.py`).** After successful resolution
and support-check, reply "compacting <engine> session <id>..." (handoff mode:
"creating handoff summary for <engine> session..."), `notify=False`. Keep the
existing none-support confirm flow untouched (its tests stay green).

**B4. Deploy verification protocol (docs).** Add to
`docs/how-to/compact-session.md` a "nothing happens?" troubleshooting section
and to `readme.md`/docs the rebuild protocol:

```
uv tool uninstall takopi
uv tool install --no-cache .
# verify artifact:
#   grep site-packages loop.py for parse_compact_invocation
#   check site-packages file dates == today
#   ensure exactly ONE takopi process before testing
```

**B5. Docs and changelog.** Update the engine matrix in
`docs/how-to/compact-session.md` and `docs/reference/commands-and-directives.md`
(omp/grok: handoff summary, not real compaction), `changelog.md` entry, and
note the test-only status of the ACP path in `docs/reference/plugin-api.md`.

### Task C - Verification gate

```
uv run pytest tests/test_telegram_compact_dispatch.py tests/test_omp_runner.py tests/test_grok_runner.py tests/test_agy_compact.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

Then user e2e on the live bot (single instance, verified artifact): reply
`/compact` to an omp session -> visible ack + "handoff summary finished.";
`/compact keep tests` -> same path, instructions forwarded.

## Files touched

- M `src/takopi/runners/_compact_mixin.py` (add `HandoffCompactMixin`)
- M `src/takopi/runners/agy.py` (adopt mixin, preserve note)
- M `src/takopi/runners/omp.py`, `src/takopi/runners/grok.py` (swap mixins)
- M `src/takopi/runners/_acp.py` (docstring: test-only until Task 6)
- M `src/takopi/telegram/loop.py` (`run_compact_job` feedback)
- M `src/takopi/telegram/commands/compact.py` (ack on enqueue)
- M `tests/test_telegram_compact_dispatch.py`, `test_omp_runner.py`,
  `test_grok_runner.py`, possibly `test_agy_compact.py`
- M `docs/how-to/compact-session.md`, `docs/reference/commands-and-directives.md`,
  `docs/reference/plugin-api.md`, `changelog.md`

## Risks and pitfalls

- Do not break the `4669620` confirm-flow and ordering tests; run the full
  suite, not only new files.
- Keep `FakeAcpTransport` and ACP tests intact for Task 6.
- The ack/status wording must never claim real compaction for handoff mode
  (honesty is the point of the reclassification).
- `run_compact_job` is a closure inside `run_main_loop`; test through the
  loop-level fakes, not by extracting new untested helpers.
- Narrow patches in `loop.py`; re-read before editing (pair-editing rule).
- Do not commit unless the user explicitly asks.