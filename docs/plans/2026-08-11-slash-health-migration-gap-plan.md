# `/health` Reliability and Migration-Gap Implementation Plan


## Context

- `pyproject.toml` registers `health = "untether.telegram.commands.health:BACKEND"`, and startup logs show `health` in the Telegram command menu. Registration exists in the inspected source/startup instance.
- `telegram/loop.py::_dispatch_batched_prompt()` parses `/health`, refreshes installed command IDs when necessary, starts `dispatch_command`, and returns before `TransportRuntime.resolve_message()` when `health` is registered.
- `telegram/commands/dispatch.py::_dispatch_command()` loads the backend, builds `CommandContext`, runs `HealthCommand.handle()`, wraps HTML in `RenderedMessage`, and sends it through `_TelegramCommandExecutor`.
- `telegram/commands/health.py` already degrades missing Linux `/proc`, process diagnostics, cost data, trigger manager, and uptime data instead of requiring those sources.
- The fatal live traceback comes from a stale wheel path under `D:/Projects/untether/.venv/Lib/site-packages/untether/transport_runtime.py` and uses the removed expression `engine_override=engine_override`. Current source uses `engine_override=directives.engine`; the current venv has `untether.pth` pointing to `D:/Projects/untether/src` and the old package directory is absent. The traceback therefore proves a stale loaded installation/process, not a remaining source defect.
- Existing tests call `HealthCommand` directly. They do not prove installed entry-point discovery, slash classification, generic dispatch, HTML transport delivery, avoidance of prompt resolution, or wheel contents.

## Approach

1. **Lock the resolver and registry boundaries.** In `tests/test_transport_runtime.py`, resolve `/pi hello` and assert `prompt == "hello"` plus `engine_override == "pi"`; also retain the bare-prompt `None` case. In `tests/test_command_registry.py`, use real installed metadata to assert `list_command_ids()` contains `health`, `get_command("health")` loads `untether.telegram.commands.health:BACKEND`, and every `untether.command_backends` entry point satisfies `ep.name == backend.id`. Remove `TransportRuntime._resolve_engine_override()` only after a fresh LSP reference query confirms zero callers. Commit this regression independently.

2. **Make command lookup failure visible without creating a health-only branch.** In `telegram/commands/dispatch.py::_dispatch_command`, keep `get_command(..., required=False)`. When it returns `None`, log the existing sanitized `command.unknown_command` event and send `error: command unavailable` as a reply to the incoming message, then return. Add the equivalent callback toast only if the callback test exposes the same silent path. In the loop integration fixture in `tests/test_telegram_bridge.py`, dispatch `/health` and assert HTML delivery, incoming-message reply linkage, and zero calls to `TransportRuntime.resolve_message()` or runner resolution. A catalog miss after the one existing refresh remains normal prompt behavior for unknown slash text; do not hard-code `health` into the loop.

3. **Add one immutable status seam.** In `commands.py`, add frozen `RuntimeStatusSnapshot(active_runs, queued_jobs, triggers_enabled, cron_count, webhook_count)` and optional `runtime_status` plus `dispatch_started_at` fields on `CommandContext`. In `scheduler.py`, add a side-effect-free `queued_count()` returning the number of jobs in `_queued_by_progress`. At both command and callback context-construction sites in `telegram/commands/dispatch.py`, build the snapshot from `len(running_tasks)`, `scheduler.queued_count()`, and trigger-manager ID snapshots; isolate trigger snapshot exceptions to `triggers_enabled=True` with unavailable counts. Pass `time.monotonic()` captured at dispatch entry. Do not expose `RunningTasks`, `ThreadScheduler`, or `TriggerManager` through the new seam.

4. **Convert `HealthCommand` to bounded progressive delivery.** In `telegram/commands/health.py`, retain `BACKEND`, generic dispatch, HTML, and `notify=False`, but let `handle()` own the complete bounded flow and return `None` after sending. Render and send an initial message immediately through `ctx.executor.send(..., reply_to=ctx.message, notify=False)` containing: `Untether health`, `service: alive`, uptime, active/queued counts, trigger state, and `collecting diagnostics…`. If send returns `None`, log `health.initial_send.failed` with timing/error type only and stop; there is no message to edit.

5. **Collect details concurrently with explicit limits.** Add frozen internal results for `SystemSnapshot`, `ProcessSnapshot`, and `UsageSnapshot`, plus pure renderers. Run three collectors in an AnyIO task group: memory/swap via `_read_meminfo_fields`, process data via `collect_proc_diag(os.getpid())`, and today’s cost via `get_daily_cost()`. Execute each blocking collector with `anyio.to_thread.run_sync(...)`, cap each at 1.0 second with `move_on_after`, and cap the whole group at 2.0 seconds. A timeout, unsupported platform, or ordinary `Exception` sets only that collector to `unavailable`; re-raise AnyIO cancellation and never catch `BaseException`. Keep the command coroutine alive until the bounded group and edit complete—no detached task.

6. **Edit the same message with the detailed snapshot.** Render five HTML sections: **Service** (alive, uptime, active/queued, triggers), **Process** (PID, RSS, FD count, child count), **System** (RAM used/available/percent and swap), **Usage** (today’s API cost), and **Diagnostics** (one `ok`, `unavailable`, or `timed out` status per collector). Call `ctx.executor.edit(initial_ref, detailed_message)`. Unsupported values always display `unavailable`; do not omit sections. If edit returns `None` or raises an ordinary exception, leave the initial message intact and log `health.detail_edit.failed`; do not send a second error message.

7. **Add sanitized latency observations.** Emit `health.initial_send.completed` with `slash_to_send_ms`; `health.collector.completed` with only `collector`, `status`, and `duration_ms`; `health.detail_collection.completed` with `duration_ms`; and `health.detail_edit.completed` with `duration_ms`. Never log credentials, chat/message IDs, bodies, configuration values, state contents, or probe output. Existing transport logs may retain their established identifiers; the new health events do not add them.

8. **Test observable progression and degradation.** Expand `tests/test_health_command.py` with deterministic collectors and a recording `CommandExecutor`: assert initial send occurs before a blocked collector is released; all collectors start before any completes; the returned `MessageRef` is the exact edit target; both payloads are HTML and initial delivery replies to `ctx.message`; active/queued/trigger values come from the immutable snapshot; each timeout/exception affects only its section; non-Linux memory is unavailable; edit failure preserves the initial send; cancellation escapes; and `run_one`, `run_many`, engine resolution, and runner dispatch remain unused. Keep the existing formatting tests only where they defend the new render contract.

9. **Prevent package drift and update migration authority.** Extend the existing clean-wheel CI install step to enumerate/load all command backends and explicitly verify `health`. Update `ROADMAP.md`, `docs/audits/2026-08-09-takopi-feature-port-audit.md`, `docs/how-to/operations.md`, `docs/tests/v0.35.2-integration-test-plan.md`, and changelogs after behavior passes. Record source support as implemented and Startup/live delivery as `runtime-unverified` until the authorized smoke. Preserve Future Tasks 4/20/23 exactly once and do not add Task 24, E12, or E13.

10. **Commit green slices.** Use: `test(runtime): cover engine directive resolution`; `fix(telegram): surface unavailable commands`; `feat(health): deliver progressive diagnostics`; `ci: verify packaged command backends`; `docs: track health runtime reliability`. Commit each immediately after its focused verification; never combine them with logging, voice, Codex steering, mode indicators, Grok retry, or stats work.

11. **Run the Startup-owned smoke last.** Re-confirm the execution-time branch/revision/dirty state and preserve unrelated changes. Verify Startup still invokes `D:/Projects/untether/.venv/Scripts/untether.exe` and the editable `.pth` resolves to `D:/Projects/untether/src`. With authorization, stop the one stale poller through its established launcher, confirm no Takopi/Untether poller remains, start exactly one Startup-owned poller, then issue `/health`, `/pi hello`, and `/health`. Require immediate-summary then same-message-detail behavior, correct engine directive, and a surviving single poller. Without credentials/authorization, mark only this smoke `runtime-unverified`.

## Critical files & anchors

1. `src/untether/telegram/loop.py::_dispatch_batched_prompt` — installed command-ID gate and early return before normal prompt resolution.
2. `src/untether/telegram/commands/dispatch.py::_dispatch_command` — backend lookup, `CommandContext`, HTML wrapping, and send/error behavior.
3. `src/untether/commands.py::{CommandContext,RuntimeStatusSnapshot}` and `src/untether/scheduler.py::ThreadScheduler.queued_count` — immutable active/queued/trigger status seam.
4. `src/untether/telegram/commands/health.py::{HealthCommand,SystemSnapshot,ProcessSnapshot,UsageSnapshot}` — initial renderer, bounded collectors, detailed renderer, and same-message edit.
5. `src/untether/transport_runtime.py::resolve_message`, `tests/test_transport_runtime.py`, `tests/test_health_command.py`, `tests/test_telegram_bridge.py`, and `tests/test_command_registry.py` — resolver, progressive delivery, loop dispatch, and installed registry contracts.
6. `pyproject.toml` plus `.github/workflows/ci.yml` — command entry point and clean-wheel backend sweep.

## Verification

Run from `D:/Projects/untether` in this order:
- If installed metadata does not list `health`, `/health` falls into normal prompt resolution by current loop design; do not add a hard-coded health branch. Packaging/installation verification prevents this drift, while the generic dispatcher supplies a visible safe error when lookup disappears after catalog refresh.
1. `uv run --no-sync pytest tests/test_transport_runtime.py -q --no-cov`
   - Expected: engine-directive regression passes; no `NameError`.
2. `uv run --no-sync pytest tests/test_health_command.py tests/test_telegram_bridge.py tests/test_command_registry.py tests/test_scheduler_queue.py -q --no-cov`
   - Expected: immediate-before-detail ordering, same-reference edit, timeout/exception isolation, HTML reply linkage, active/queued snapshot, generic unavailable response, real registry lookup, no-runner dispatch, and scheduler count tests pass.
3. Run the exact clean-wheel command used by the CI install job.
   - Expected: every command backend loads; `health` is present and its ID matches its entry-point name.
4. `uv run --no-sync ruff format --check src tests && uv run --no-sync ruff check src tests && uv run --no-sync ty check src tests`
   - Expected: zero formatter, lint, and type diagnostics.
5. `uv run --no-sync pytest tests/ -q --no-cov`
   - Expected: full Windows suite passes with only documented skips.
6. Authorized runtime smoke from Approach Step 11.
   - Expected: first `/health` sends an immediate HTML summary and edits that message with details; `/pi hello` resolves Pi normally; second `/health` succeeds; exactly one poller remains alive.

## Assumptions & contingencies

- The source `/health` implementation is retained; no second command implementation, hard-coded loop branch, or fallback alias is added.
- The observed fatal `NameError` explains why a dead poller cannot answer `/health`. Whether an earlier stale wheel omitted `health` and caused that exact slash input to enter prompt resolution is `runtime-unverified` because that wheel directory no longer exists.
- Missing `/proc` on Windows is expected and must render the existing RAM-unavailable fallback, not fail health.
- If the live command fails while the process remains alive, use `command.dispatch`/`command.failed` evidence to isolate entry-point lookup, renderer, or Telegram HTML rejection before changing code.
- All health work is additive to the previous migration issues and tasks. It does not supersede logging, voice transcription, visible plan/goal indicators, long-answer split verification, shared OMP/Grok JSONL repair, `/stats` semantics, roadmap carryovers, or their existing commit boundaries.
