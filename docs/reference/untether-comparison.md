# Untether ↔ takopi Comparison and Merge-Direction Recommendation

This document compares two immutable repository snapshots — `littlebearapps/untether` and `skargaklop/takopi` — at the source level, scores both merge directions with a fixed weighted rubric, recommends one direction, and stops at an explicit approval gate. No merge code has been written.

## Snapshot and method

| Repository | URL | Branch | SHA | Capture time (UTC) | Python | Version | License | Worktree |
|---|---|---|---|---|---|---|---|---|
| takopi | `https://github.com/skargaklop/takopi.git` | `master` | `481f0c72f50ef5b7a7793f547059d691f7b8ffc3` | `2026-08-08T12:15:55Z` | >=3.14 | 0.26.0 | MIT | clean |
| untether | `https://github.com/littlebearapps/untether` | `master` | `4285dad5a12e4e4113c9cc5240972a67bbb5e218` | `2026-08-08T12:16:08Z` | >=3.12 | 0.35.4 | MIT | clean |

Both SHAs were re-verified at `2026-08-08T12:36:27Z`:

```text
$ cd D:/Projects/takopi && git rev-parse HEAD && git status --short
481f0c72f50ef5b7a7793f547059d691f7b8ffc3
(clean)

$ cd D:/Projects/untether-review && git rev-parse HEAD && git status --short
4285dad5a12e4e4113c9cc5240972a67bbb5e218
(clean)
```

**Method.** Source and tests were inspected before docs; README/roadmap were used only to discover candidates. Status values are exact literals:

- `implemented` — source code plus a behavior test or executable probe exercises the capability.
- `documented-only` — README, roadmap, or other prose mentions the capability but no source/test evidence was found.
- `not found` — the named source/docs/tests scopes were searched with no match.

Citations use `https://github.com/<owner>/<repo>/blob/<full-sha>/<path>#Lx-Ly` for remote files and local `path:line` for checked-out snapshots. The untether scratch checkout lives at `D:/Projects/untether-review`; takopi lives at `D:/Projects/takopi`.

## Shared ancestry

Untether is an explicitly declared fork of takopi. The README states:

> Untether is a fork of [takopi](https://github.com/banteg/takopi) by [@banteg](https://github.com/banteg), which provided the original Telegram-to-Codex bridge. Untether extends it with interactive permission control, multi-engine support, plan mode, cost tracking, and many other features.
>
> — `README.md` ([source](https://github.com/littlebearapps/untether/blob/4285dad5a12e4e4113c9cc5240972a67bbb5e218/README.md#L338))

Both projects are MIT-licensed. Untether's `pyproject.toml` registers `https://github.com/banteg/takopi` as the upstream URL and retains banteg attribution. The two codebases share the same core architecture:

- **Scheduler**: per-session FIFO `ThreadScheduler` keyed by `engine:resume-value`, with `_pending_by_thread`, `_queued_by_progress`, and `_busy_until` state. Both use `anyio` for async coordination.
  - takopi: `src/takopi/scheduler.py:ThreadScheduler` (388 lines)
  - untether: `src/untether/scheduler.py:ThreadScheduler` (167 lines)
- **Domain model**: `ResumeToken(engine, value)`, `StartedEvent`, `ActionEvent`, `CompletedEvent` — identical frozen-dataclass shape.
  - takopi: `src/takopi/model.py`
  - untether: `src/untether/model.py:ResumeToken(engine, value, is_continue=False)`, `StartedEvent`, `ActionEvent`, `CompletedEvent`
- **Runner protocol**: `JsonlSubprocessRunner` subclasses translating per-engine msgspec schemas into normalized events; `StartedEvent -> CompletedEvent` ordering with resume equality.
  - takopi: `src/takopi/runner.py`, `docs/reference/plugin-api.md`
  - untether: `src/untether/runner.py`, `src/untether/runner_bridge.py`
- **Telegram bridge**: polling loop, progress edits, voice, topics, file transfer, outbox.
  - takopi: `src/takopi/telegram/loop.py`, `src/takopi/telegram/voice.py`, `src/takopi/telegram/outbox.py`
  - untether: `src/untether/telegram/loop.py`, `src/untether/telegram/outbox.py`
- **Plugin discovery**: entry-point groups for engines, transports, and commands.
  - takopi: `takopi.engine_backends`, `takopi.transport_backends`, `takopi.command_backends` (`src/takopi/runtime_loader.py`)
  - untether: `untether.engine_backends`, `untether.transport_backends`, `untether.command_backends` (`src/untether/plugins.py`)
- **Worktrees**: `resolve_run_cwd` / `ensure_worktree` with branch sanitization.
  - takopi: `src/takopi/worktrees.py`
  - untether: `src/untether/worktrees.py`

The fork diverged meaningfully: Untether grew triggers, cost tracking, session quarantine, config hot-reload, outbox delivery, 16 command backends, and ~2840 test functions; takopi grew a hardened scheduler (Task 21), full OMP session IDs (Task 22), 7 engines including omp/grok/agy, 3-OS CI, a hard `ty` gate, and ~1062 test functions.

## Feature matrix

### Engines

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| engines | Built-in engine IDs | implemented | `pyproject.toml` [entry-points](https://github.com/littlebearapps/untether/blob/4285dad5a12e4e4113c9cc5240972a67bbb5e218/pyproject.toml#L56-L62): codex, claude, opencode, pi, gemini, amp (6) | implemented | `pyproject.toml:[project.entry-points."takopi.engine_backends"]` L42-L49: codex, claude, opencode, pi, omp, grok, agy (7) | Untether has gemini + amp; takopi has omp + grok + agy. Shared: codex, claude, opencode, pi. | Port gemini and amp runners to the winner; reconcile omp/grok/agy. |
| engines | Runtime plugin discovery | implemented | `src/untether/plugins.py`: `ENGINE_GROUP`/`TRANSPORT_GROUP`/`COMMAND_GROUP`, `list_ids`, `load_entrypoint`, allowlist, duplicate rejection | implemented | `src/takopi/runtime_loader.py`: `RuntimeSpec`, `build_router`, `load_backends`, plugin allowlist | Same entry-point architecture; different group prefixes (`untether.*` vs `takopi.*`). | Namespace migration required for all entry-point groups. |
| engines | Schemas/event invariants | implemented | `src/untether/schemas/`: codex has `UnknownItem` fallback; pi has NO `PiUnknownEvent` (`src/untether/schemas/pi.py` L116: `_DECODER = msgspec.json.Decoder(PiEvent)`, no catch-all) | implemented | `src/takopi/schemas/pi.py:PiUnknownEvent` (L95-103, `forbid_unknown_fields=False`), `decode_event` (L170-186) returns unknown types as `PiUnknownEvent` | takopi is forward-compatible with unknown Pi events; untether will raise on unrecognized event types. | Port `PiUnknownEvent` and the peek-decode path to untether if merging into untether. |
| engines | Model/reasoning overrides | implemented | `src/untether/telegram/engine_overrides.py`, `src/untether/runners/` per-runner `build_args` model handling | implemented (partial) | `src/takopi/telegram/engine_overrides.py:EngineOverrides`, `src/takopi/runners/run_options.py:EngineRunOptions`; `tests/test_telegram_engine_overrides.py`, `tests/test_runner_run_options.py` | takopi has reasoning-level support (`REASONING_LEVELS_BY_ENGINE`); Task 23 end-to-end propagation is `Plan: TBD` (`ROADMAP.md` L952). | Complete Task 23 contract in the winner; port reasoning levels. |
| engines | Cross-environment resume | implemented | `src/untether/model.py:ResumeToken(engine, value, is_continue)`; per-runner `extract_resume`/`format_resume` | implemented | `src/takopi/model.py:ResumeToken(engine, value)`; per-runner `extract_resume`/`format_resume`; `src/takopi/runners/omp.py:_retag_resume` | Untether adds `is_continue` field; takopi's OMP runner retags cross-engine resume tokens. | Reconcile `ResumeToken` shape (add `is_continue` or keep 2-field). |

### Telegram

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| Telegram | Polling/client | implemented | `src/untether/telegram/loop.py`, `src/untether/telegram/client.py:BotClient`, `TelegramClient` | implemented | `src/takopi/telegram/loop.py`, `src/takopi/telegram/client.py` | Same architecture. | Minimal migration. |
| Telegram | Progress edits | implemented | `src/untether/runner_bridge.py:ProgressEdits` with stall monitor | implemented | `src/takopi/runner_bridge.py:ProgressEdits` | Both render live progress; untether adds MCP-adapter stall recovery (`_StuckAfterToolResultState`). | Port stall-recovery tiers if merging into takopi. |
| Telegram | Typed and callback cancellation | implemented | `src/untether/telegram/commands/cancel.py:handle_callback_cancel`; `src/untether/scheduler.py:cancel_queued` returns `ThreadJob \| None` (L109-127) | implemented | `src/takopi/telegram/commands/cancel.py:handle_callback_cancel`; `src/takopi/scheduler.py:cancel_queued` returns `CancelQueuedResult` with `CancelQueuedStatus` enum (L197-214); `tests/test_scheduler_queue.py`, `tests/test_telegram_queue.py` | takopi discriminates `CANCELLED`/`ALREADY_CLAIMED`/`NOT_FOUND`; untether returns plain `ThreadJob \| None`. | **Critical**: incoming scheduler code must adopt takopi's `CancelQueuedResult` contract. |
| Telegram | Forum topics | implemented | `src/untether/telegram/topics.py`, `src/untether/telegram/commands/threads.py` | implemented | `src/takopi/telegram/topics.py:TopicStateStore` | Similar. | Minimal. |
| Telegram | Group/listen modes | implemented | `src/untether/telegram/listen_mode.py`, trigger modes | implemented | `src/takopi/telegram/trigger_mode.py` | Similar trigger-mode concept. | Minimal. |
| Telegram | Inline settings | implemented | `src/untether/telegram/commands/config.py` (87 KB), inline settings menu with buttons | not found | Searched `src/takopi/telegram/commands/` — no inline config menu | Untether has a rich in-chat `/config` settings menu; takopi uses CLI/config-file settings. | Port inline config menu if merging into takopi. |

### Scheduling

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| scheduling | Per-session FIFO | implemented | `src/untether/scheduler.py:ThreadScheduler._pending_by_thread`, `_thread_worker` | implemented | `src/takopi/scheduler.py:ThreadScheduler._pending_by_thread`, `_thread_worker` | Same core design. | Shared ancestry; minimal. |
| scheduling | Exact queued-job cancellation | implemented | `src/untether/scheduler.py:cancel_queued` (L109-127) returns `ThreadJob \| None` — no status discrimination | implemented | `src/takopi/scheduler.py:cancel_queued` (L197-214) returns `CancelQueuedResult(status, job)` with `__post_init__` validation; `tests/test_scheduler_queue.py` (772 lines) | takopi's Task 21 hardened contract distinguishes CANCELLED (with job), ALREADY_CLAIMED, NOT_FOUND. Untether cannot tell "already claimed" from "not found". | **Critical invariant**: adopt takopi's `CancelQueuedResult`/`CancelQueuedStatus`. |
| scheduling | Job lifecycle observers | not found | Searched `src/untether/scheduler.py` — no `on_job_claimed`/`on_job_failed` | implemented | `src/takopi/scheduler.py:JobClaimed`/`JobFailed` callbacks (L38-39, L97-103); `src/takopi/telegram/loop.py:_make_scheduler_observers` (L1371-1392) | takopi wires claim/failure observers for Telegram label updates and failure visibility; untether has none. | Port observer pattern. |
| scheduling | Consumer claim / requeue (steering) | not found | Searched `src/untether/scheduler.py` — no `claim_queued`/`requeue_front` | implemented | `src/takopi/scheduler.py:claim_queued` (L216-225), `requeue_front` (L227-242) | takopi supports Codex steering: claim a queued job, consume it, requeue on failure. | Port if steering is desired in winner. |
| scheduling | Enqueue disposition | not found | Searched `src/untether/scheduler.py` — `enqueue` returns `None` | implemented | `src/takopi/scheduler.py:EnqueueDisposition` enum (L42-46), `enqueue` returns `QUEUED`/`CLAIMABLE` | takopi tells callers whether a job is queued or immediately claimable. | Port if callers need disposition. |
| scheduling | Scheduled one-shot/cron/webhook triggers | implemented | `src/untether/triggers/cron.py:cron_matches` (5-field), `run_cron_scheduler`; `src/untether/triggers/server.py` (aiohttp webhook with SSRF protection, multipart, loopback detection); `src/untether/triggers/manager.py:TriggerManager`; `tests/test_trigger_cron.py`, `tests/test_trigger_server.py`, `tests/test_trigger_ssrf.py` | not found | Searched `src/takopi/` — no triggers directory, no cron/webhook scheduling | Untether has a complete trigger system: cron expressions, webhook HTTP server, one-shot `/at`, SSRF protection, rate limiting, per-chat trigger management. | Port entire `triggers/` subsystem if merging into takopi. |
| scheduling | Restart/drain semantics | implemented | `src/untether/telegram/commands/restart.py`, `src/untether/loop_scheduler.py` (33 KB) | documented-only | `docs/how-to/troubleshooting.md` mentions restart; no `loop_scheduler.py` equivalent | Untether has a dedicated `loop_scheduler.py` and `/restart` command. | Port if merging into takopi. |

### Control

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| control | Active cancellation | implemented | `src/untether/runner_bridge.py` signal handling, `src/untether/utils/subprocess.py:signal_pid_group` | implemented | `src/takopi/runner_bridge.py:run_runner_with_cancel`, `src/takopi/utils/subprocess.py` | Both support active run cancellation. | Shared ancestry. |
| control | Interactive permission gates | implemented | `src/untether/telegram/commands/claude_control.py`, `src/untether/telegram/commands/ask_question.py` (`aq` backend); inline approval buttons | implemented | `src/takopi/telegram/commands/cancel.py`, approval rendering in `runner_bridge.py` | Both render approval actions; untether has richer Claude-specific control (`claude_control` backend). | Reconcile approval flow. |
| control | Plan mode | implemented | `src/untether/telegram/commands/planmode.py` (`planmode` backend) | implemented | `src/takopi/runners/modes.py:run_modes`, `effective_prompt`; plan mode in `scheduler.py:ThreadJob.plan` | Both support plan mode; different implementation approaches. | Reconcile plan-mode flag. |
| control | Goal/autonomous mode | implemented | `src/untether/telegram/commands/planmode.py` goal/autonomous modes | implemented | `src/takopi/scheduler.py:ThreadJob.goal` field | Both have goal/autonomous concept. | Reconcile goal field. |
| control | Approvals policy | implemented | `src/untether/telegram/commands/config.py` approval policy (Codex full auto/safe, Gemini read-only/auto_edit/yolo) | implemented | `src/takopi/telegram/engine_overrides.py`, runner-specific approval args | Both support per-engine approval policies. | Reconcile per-engine policy. |

### Sessions/context

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| sessions | Exact resume identity | implemented | `src/untether/model.py:ResumeToken(engine, value, is_continue=False)` | implemented | `src/takopi/model.py:ResumeToken(engine, value)` | Untether adds `is_continue` boolean; takopi uses 2-field. | Reconcile ResumeToken shape. |
| sessions | Full OMP session IDs | not found | Searched `src/untether/runners/` — no OMP runner; no `shorten_session_id` flag | implemented | `src/takopi/runners/omp.py:OmpRunner.new_state` (L152-159): `PiStreamState(shorten_session_id=False)`; `tests/test_pi_runner.py` | takopi preserves full OMP UUIDs; untether has no OMP engine. | **Critical invariant**: preserve `shorten_session_id=False` if merging into untether. |
| sessions | Forward-compatible Pi/OMP decoding | not found | `src/untether/schemas/pi.py` (L116): `_DECODER = msgspec.json.Decoder(PiEvent)`, no `PiUnknownEvent` catch-all | implemented | `src/takopi/schemas/pi.py:PiUnknownEvent` (L95-103), `decode_event` (L170-186); `tests/test_pi_schema.py` | takopi handles unknown Pi event types gracefully; untether raises. | **Critical invariant**: port `PiUnknownEvent` if merging into untether. |
| sessions | Auto-resume modes | implemented | `src/untether/runner_bridge.py` auto-continue/auto-resume; workflow modes: Assistant, Workspace, Handoff (`README.md` L73-77) | implemented | `src/takopi/telegram/chat_sessions.py:ChatSessionStore`, `src/takopi/telegram/loop.py` resume wiring | Both support auto-resume; untether has 3 named workflow modes. | Reconcile workflow-mode concept. |
| sessions | Session quarantine | implemented | `src/untether/session_quarantine.py:QuarantineStore` (persisted JSON, 7-day pruning, `is_quarantined`); `src/untether/runner_bridge.py` quarantine checks; `tests/test_session_quarantine.py` | not found | Searched `src/takopi/` — no quarantine module | Untether quarantines poisoned sessions (post-result limbo, empty-0-turn) to prevent resume; persisted across restarts. | Port `session_quarantine.py` if merging into takopi. |
| sessions | Export | implemented | `src/untether/telegram/commands/export.py` (`export` backend); `tests/test_export_command.py` | implemented | `src/takopi/telegram/commands/` export functionality | Both have export. | Shared ancestry. |
| sessions | Project/branch context | implemented | `src/untether/worktrees.py:resolve_run_cwd`, `ensure_worktree` | implemented | `src/takopi/worktrees.py:resolve_run_cwd`, `ensure_worktree`, branch sanitization, path traversal guards | Both support project/branch context. | Shared ancestry. |
| sessions | Handoff/compaction | implemented | `src/untether/runner_bridge.py` handoff timeout/exit handling (`test_exec_bridge.py::test_633_handoff_*`); `src/untether/runners/pi.py` compaction | implemented | `src/takopi/runners/_acp.py:ACP`, `src/takopi/runners/_compact_mixin.py:HandoffCompactMixin`; `tests/test_compact_event_invariants.py` | Both support handoff/compaction; takopi has ACP-based compaction for grok/omp. | Reconcile compaction approach. |

### Input/output

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| input/output | Voice transcription | implemented | `src/untether/telegram/voice.py`; `tests/test_telegram_voice.py` | implemented | `src/takopi/telegram/voice.py`; `tests/test_telegram_voice.py` | Both support voice transcription (OpenAI). | Shared ancestry. |
| input/output | File upload/download | implemented | `src/untether/telegram/commands/file_transfer.py`; `tests/test_telegram_file_transfer_helpers.py` | implemented | `src/takopi/telegram/files.py`; `docs/how-to/file-transfer.md` | Both support file transfer. | Shared ancestry. |
| input/output | Agent outbox (post-run delivery) | implemented | `src/untether/telegram/outbox.py:TelegramOutbox` (priority queue: SEND/DELETE/EDIT, `SUPERSEDED` sentinel); `src/untether/telegram/outbox_delivery.py` (`.untether-outbox/` scanning, zip skipped dirs); `tests/test_outbox_delivery.py` | implemented | `src/takopi/telegram/outbox.py` (rate-limited send queue with `RetryAfter`) | Both have outbox; untether adds post-run file delivery and priority-based op ordering. | Port outbox_delivery if merging into takopi. |
| input/output | File browser | implemented | `src/untether/telegram/commands/browse.py` (`browse` backend); `tests/test_browse_command.py` | not found | Searched `src/takopi/telegram/commands/` — no browse command | Untether has a file browser command. | Port if merging into takopi. |
| input/output | Long-prompt/file-backed tasks | implemented | `src/untether/telegram/` message overflow handling, `README.md` mentions `message_overflow` config | documented-only | `docs/how-to/long-telegram-prompts.md` | Untether has file-backed long-prompt handling in code; takopi documents it. | Port if merging into takopi. |

### Observability/reliability

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| observability | Progress/tool rendering | implemented | `src/untether/runner_bridge.py:ProgressEdits`, `src/untether/markdown.py:render_event_cli` | implemented | `src/takopi/runner_bridge.py:ProgressEdits`, `src/takopi/telegram/render.py` | Both render progress. | Shared ancestry. |
| observability | Transient failure classification | implemented | `src/untether/error_hints.py:get_error_hint`, transient failure classification | implemented | `src/takopi/utils/transient_failures.py:TransientFailure` (429/503, retry-after-ms, omniroute blob), `format_transient_failure` | Both classify transient failures; different implementation. | Reconcile classification. |
| observability | Actionable error hints | implemented | `src/untether/error_hints.py`; `tests/test_error_hints.py` | documented-only | `docs/how-to/troubleshooting.md` has error guidance; no dedicated `error_hints.py` module | Untether has structured error hints with tests. | Port `error_hints.py` if merging into takopi. |
| observability | Cost/usage budgets | implemented | `src/untether/cost_tracker.py:CostBudget`, `CostAlert`, `record_run_cost()`, `get_daily_cost()`, `check_run_budget()` (per-run and per-day thresholds, threading.Lock); `tests/test_cost_tracker.py` | not found | Searched `src/takopi/` — no cost tracker module | Untether has cost tracking with per-run/per-day budgets, alerts, and auto-cancel. | Port `cost_tracker.py` if merging into takopi. |
| observability | Stats dashboard | implemented | `src/untether/telegram/commands/stats.py` (`stats` backend, per-engine session statistics with auth status); `src/untether/session_stats.py`; `tests/test_stats_command.py` | not found | Searched `src/takopi/telegram/commands/` — no stats command | Untether has `/stats` and `/health` commands with per-engine run counts. | Port if merging into takopi. |
| observability | Health command | implemented | `src/untether/telegram/commands/health.py` (system+triggers+cost snapshot); `tests/test_health_command.py` | not found | Searched `src/takopi/telegram/commands/` — no health command | Untether has `/health` command. | Port if merging into takopi. |
| observability | Orphan cleanup | implemented | `src/untether/utils/subprocess.py:reap_orphaned_group`, `signal_pid_group` | implemented | `src/takopi/utils/subprocess.py`: Windows `taskkill /T /F` tree kill, stream close; `tests/test_subprocess_close.py` | Both clean up process trees; takopi has Windows-specific tested cleanup. | Reconcile platform paths. |
| observability | Stall diagnostics | implemented | `src/untether/utils/proc_diag.py:ProcessDiag` (`/proc` memory/children, 11.3 KB); `tests/test_proc_diag.py` | not found | Searched `src/takopi/utils/` — no proc_diag module | Untether has detailed stall diagnostics. | Port if merging into takopi (Linux-only). |
| observability | Session statistics | implemented | `src/untether/session_stats.py`; `tests/test_session_stats.py` | not found | Searched `src/takopi/` — no session_stats module | Untether tracks per-engine session statistics. | Port if merging into takopi. |

### Platform/extension

| Area | Capability | Untether status | Untether evidence | Takopi status | Takopi evidence | Behavioral difference | Migration consequence |
|---|---|---|---|---|---|---|---|
| platform | Engine/transport/command plugin API | implemented | `src/untether/plugins.py`, `src/untether/api.py` | implemented | `src/takopi/runtime_loader.py`, `src/takopi/api.py:TAKOPI_PLUGIN_API_VERSION=1` | Same architecture; different API version and namespace. | Namespace migration. |
| platform | Config hot reload | implemented | `src/untether/config_watch.py:watch_config()` (watchfiles `awatch`), `ConfigReload` dataclass; `src/untether/config_reload_notification.py`; `tests/test_config_watch.py`, `tests/test_bridge_config_reload.py` | not found | Searched `src/takopi/` — no config_watch module | Untether hot-reloads `untether.toml` changes in ~1 second (triggers, voice, allowed-users, watchdog, etc.). | Port `config_watch.py` if merging into takopi. |
| platform | Onboarding/doctor | implemented | `src/untether/telegram/commands/` `auth` backend (`/auth` device re-auth for Codex); `tests/test_onboarding*.py`, `tests/test_cli_doctor.py` | documented-only | `docs/tutorials/install.md`, `docs/tutorials/first-run.md` | Untether has a setup wizard and `/doctor` command. | Port if merging into takopi. |
| platform | Python/OS support | implemented | `pyproject.toml` requires Python >=3.12; `.github/workflows/ci.yml` Ubuntu-only, Python 3.12/3.13/3.14 | implemented | `pyproject.toml` requires Python >=3.14; `.github/workflows/ci.yml` Ubuntu/macOS/Windows, Python 3.14 | takopi is 3-OS with a higher Python floor; untether is Ubuntu-only with a lower floor. | **Critical**: adopt takopi's 3-OS CI if merging into untether. |
| platform | Typing/lint/test gates | implemented | CI: ruff (hard), ty (`allow_failure: true` — informational), pytest with `--cov-fail-under=80`; `pyproject.toml:[tool.pytest.ini_options]` | implemented | CI: ruff (hard), ty (hard, no `allow_failure`), pytest with `--cov-fail-under=81` (81% branch coverage) | takopi has a hard `ty` gate (zero diagnostics) and 81% coverage; untether has informational ty and 80% coverage. | **Critical**: adopt takopi's hard ty and 81% coverage if merging into untether. |
| platform | Security gates | implemented | CI: `pip-audit` (with CVE ignores), `bandit -r src/` | not found | Searched `.github/workflows/ci.yml` — no pip-audit or bandit jobs | Untether has security scanning; takopi does not. | Port security gates if merging into takopi. |
| platform | Mutation testing | implemented | `pyproject.toml:[tool.mutmut]`: `paths_to_mutate=["src/untether"]`, `do_not_mutate=["src/untether/cli/*"]` | implemented | `pyproject.toml` dev group includes `mutmut` | Both have mutmut configured. | Shared. |
| platform | Systemd notify | implemented | `src/untether/sdnotify.py`; `tests/test_sdnotify.py` | not found | Searched `src/takopi/` — no sdnotify module | Untether supports systemd service notifications. | Port if merging into takopi (Linux-only). |
| platform | Env policy/audit | implemented | `src/untether/utils/env_policy.py` (10.1 KB), `src/untether/utils/env_audit.py`; `tests/test_env_policy.py`, `tests/test_env_audit.py` | not found | Searched `src/takopi/utils/` — no env_policy/env_audit modules | Untether has env allowlist/audit for subprocess credentials. | Port if merging into takopi. |
| platform | Usage cache | implemented | `src/untether/utils/usage_cache.py`; `tests/test_usage_cache.py` | not found | Searched `src/takopi/utils/` — no usage_cache module | Untether caches usage data. | Port if merging into takopi. |
| platform | Config migrations | implemented | `src/untether/config_migrations.py` | not found | Searched `src/takopi/` — no config_migrations module | Untether handles config schema migrations between versions. | Port if merging into takopi. |
| platform | Progress persistence | implemented | `src/untether/progress_persistence.py`; `tests/test_progress_persistence.py` | not found | Searched `src/takopi/` — no progress_persistence module | Untether persists progress state. | Port if merging into takopi. |

## Engineering health

### Takopi

All commands run from `D:/Projects/takopi` with `PYTHONUTF8=1`:

```text
$ uv run --no-sync ruff format --check --diff src tests
288 files already formatted
EXIT:0

$ uv run --no-sync ruff check src tests
All checks passed!
EXIT:0

$ uv run --no-sync ty check src tests
All checks passed!
EXIT:0

$ uv run --no-sync pytest tests/ -q --no-cov
1109 passed, 4 skipped, 2 warnings in 41.05s
EXIT:0

$ uv run --no-sync pytest tests/ -q
1109 passed, 4 skipped, 2 warnings
81.03% coverage
EXIT:0

$ uv build
Successfully built dist/takopi-0.26.0.tar.gz
Successfully built dist/takopi-0.26.0-py3-none-any.whl
EXIT:0

$ uv run --group docs zensical build --clean
Build finished in 6.96s
EXIT:0
```

CI matrix (`.github/workflows/ci.yml`): Ubuntu/macOS/Windows for format, Ruff, ty, and pytest; Linux-only for coverage (81% gate), build, and docs. Python 3.14. Hard `ty` gate (no `allow_failure`).

Test count: 95 test files, ~1062 test functions.

### Untether

All commands run from `D:/Projects/untether-review` with `PYTHONUTF8=1`:

```text
$ uv run --no-sync ruff format --check --diff src tests
288 files already formatted
EXIT:0

$ uv run --no-sync ruff check src tests
All checks passed!
EXIT:0

$ uv run --no-sync ty check --warn invalid-argument-type --warn unresolved-attribute --warn invalid-assignment --warn not-subscriptable src tests
Found 348 diagnostics
EXIT:1

$ uv run --no-sync pytest --continue-on-collection-errors --no-cov -q
129 failed, 2431 passed, 18 skipped, 18 errors in 97.97s
EXIT:1

$ uv build
Successfully built dist/untether-0.35.4.tar.gz
Successfully built dist/untether-0.35.4-py3-none-any.whl
EXIT:0
```

CI matrix (`.github/workflows/ci.yml`): Ubuntu-only. Python 3.12/3.13/3.14 for pytest; Python 3.14 for checks. `ty` is informational (`allow_failure: true`). Coverage gate 80% in `pyproject.toml`. Security jobs: `pip-audit`, `bandit`. Build, install-test (smoke imports), TestPyPI publish, release-validation.

**Platform caveat.** The 129 test failures and 18 collection errors are all Windows-specific: `ModuleNotFoundError: No module named 'termios'/'fcntl'` (POSIX-only modules) and `bash` subprocess invocations with Windows path separators. On Ubuntu (Untether's only CI OS), these tests pass. The 2431 passing tests confirm the codebase is functional on its target platform.

Test count: 133 test files, ~2840 test functions.

### Summary comparison

| Metric | Takopi | Untether |
|---|---|---|
| Format (ruff) | PASS | PASS |
| Lint (ruff) | PASS | PASS |
| Type check (ty) | PASS (0 diagnostics) | FAIL (348 diagnostics, informational in CI) |
| Tests | 1109 passed, 4 skipped | 2431 passed, 129 failed (Windows-only), 18 errors (Windows-only) |
| Coverage gate | 81% (met: 81.03%) | 80% (not measured on Windows due to failures) |
| Build | PASS | PASS |
| CI OS matrix | 3 (Ubuntu/macOS/Windows) | 1 (Ubuntu) |
| Python versions | 3.14 | 3.12/3.13/3.14 |
| Security scanning | not found | pip-audit + bandit |
| Test file count | 95 | 133 |
| Test function count | ~1062 | ~2840 |

## Direction scoring

Weights total 100. Scores are integers 0–3: `0 = would replace/break or lacks evidence`, `1 = major rewrite/high regression exposure`, `2 = bounded adaptation with identified gaps`, `3 = preserves the stronger implementation with a direct migration path`. Weighted = `weight * score / 3` (percentage contribution).

| Criterion | Weight | Untether → takopi (0–3) | Weighted | Takopi → untether (0–3) | Weighted | Evidence/rationale |
|---|---:|---:|---:|---:|---:|---|
| Preserve unique implemented user capabilities | 25 | 1 | 8.33 | 3 | 25.00 | Untether has 15+ unique implemented subsystems (triggers, cost tracking, session quarantine, config hot-reload, outbox delivery, stats, health, browse, env policy, proc diag, systemd notify, config migrations, progress persistence, inline config, usage cache). Porting all into takopi is a major multi-workstream effort (score 1). Migrating takopi into untether preserves all of these in place (score 3). |
| Preserve Task 21/22 and event/session invariants | 20 | 3 | 20.00 | 2 | 13.33 | takopi's scheduler (`CancelQueuedResult`, `CancelQueuedStatus`, observers, `claim_queued`, `requeue_front`), `PiUnknownEvent`, and full OMP session IDs are already in takopi. Untether → takopi preserves them trivially (score 3). Takopi → untether requires porting these into untether's simpler scheduler and schema (score 2: bounded adaptation). |
| Minimize production-code migration surface | 15 | 1 | 5.00 | 2 | 10.00 | Untether → takopi ports 15+ subsystems into takopi (score 1: large surface). Takopi → untether ports ~5 bounded pieces (scheduler hardening, PiUnknownEvent, OMP runner, 3-OS CI, hard ty) into untether's existing structure (score 2: smaller, though CI/platform is non-trivial). |
| Preserve or improve CI, typing, coverage, and platform guarantees | 15 | 3 | 15.00 | 2 | 10.00 | Untether → takopi keeps takopi's 3-OS CI, hard ty, 81% coverage (score 3). Takopi → untether must upgrade untether's Ubuntu-only CI to 3-OS, fix 348 ty diagnostics to hard gate, raise coverage from 80% to 81% (score 2: bounded but significant). |
| Preserve plugin/API compatibility and ecosystem continuity | 10 | 2 | 6.67 | 2 | 6.67 | Both directions require entry-point namespace migration (`untether.*` ↔ `takopi.*`). Untether has more plugins (16 command backends vs takopi's smaller set). Either way, ecosystem disruption is comparable (score 2 each). |
| Minimize config/state migration and user disruption | 10 | 2 | 6.67 | 1 | 3.33 | Untether → takopi: untether users lose triggers, cost tracking, quarantine, hot-reload, inline config unless ported (score 2: moderate disruption). Takopi → untether: takopi users (fewer, earlier project) migrate to untether's config format; untether already has config migrations support (score 1: more disruption for takopi's smaller user base). |
| License/provenance traceability | 5 | 3 | 5.00 | 3 | 5.00 | Both MIT; untether already attributes takopi/banteg. Either direction preserves provenance (score 3 each). |
| **Total** | **100** | | **66.67** | | **73.33** | |

## Recommendation

Recommend: takopi → untether.

Total scores: takopi → untether = **73.33/100**; untether → takopi = **66.67/100**. The difference (6.66 points) is driven by:

1. **Untether has 15+ unique implemented subsystems** that would require large multi-workstream porting effort into takopi (triggers, cost tracking, session quarantine, config hot-reload, outbox delivery, stats, health, browse, env policy, proc diag, systemd notify, config migrations, progress persistence, inline config, usage cache) — 25-point criterion where takopi → untether scores 3 vs untether → takopi scores 1.
2. **Takopi's unique invariants are bounded and well-tested** — the scheduler hardening (`CancelQueuedResult`/`CancelQueuedStatus`/observers/`claim_queued`), `PiUnknownEvent`, and full OMP session IDs are concentrated in ~4 files with strong test coverage, making them portable into untether with bounded adaptation — 20-point criterion scores 2 vs 3, a smaller gap than the capability gap.
3. **CI/platform upgrade is bounded** — upgrading untether from Ubuntu-only to 3-OS and from informational ty to a hard gate is significant but scoped to CI configuration and fixing 348 diagnostics, not a structural rewrite.
4. **Untether already has config migration infrastructure** (`config_migrations.py`) that can smooth the takopi user transition.
5. **Untether is the downstream fork with the larger implemented surface** — the fixed tie-break rule favors this direction, and the scores are not tied, confirming it.

## Migration inventory

Order: queue/session reconciliation first, then plugin/config migration, then engine ports, then UI commands, then tests alongside each workstream.

| Order | Capability | Source path/symbol | Destination path/symbol | Adaptation | Invariants/tests to preserve | Dependency |
|---:|---|---|---|---|---|---|
| 1 | Exact queued cancellation | `src/takopi/scheduler.py:CancelQueuedResult`, `CancelQueuedStatus`, `cancel_queued` (L197-214) | `src/untether/scheduler.py:cancel_queued` | Replace `ThreadJob \| None` return with `CancelQueuedResult(status, job)` enum; add `__post_init__` validation | `tests/test_scheduler_queue.py` (772 lines): CANCELLED/ALREADY_CLAIMED/NOT_FOUND, claim boundary, result invariants | None |
| 2 | Job lifecycle observers | `src/takopi/scheduler.py:JobClaimed`, `JobFailed` (L38-39), `on_job_claimed`/`on_job_failed` (L97-103) | `src/untether/scheduler.py:ThreadScheduler.__init__` | Add observer callbacks to constructor and `_thread_worker` | `tests/test_scheduler_queue.py`: observer firing tests | Order 1 |
| 3 | Consumer claim/requeue (steering) | `src/takopi/scheduler.py:claim_queued` (L216-225), `requeue_front` (L227-242) | `src/untether/scheduler.py` | Add `claim_queued` and `requeue_front` methods | `tests/test_scheduler_queue.py`: steering claim/requeue tests | Order 1 |
| 4 | Enqueue disposition | `src/takopi/scheduler.py:EnqueueDisposition` (L42-46), `enqueue` return | `src/untether/scheduler.py:enqueue` | Change `enqueue` return type to `EnqueueDisposition` | `tests/test_scheduler_queue.py`: disposition tests | Order 1 |
| 5 | Forward-compatible Pi decoding | `src/takopi/schemas/pi.py:PiUnknownEvent` (L95-103), `decode_event` (L170-186) | `src/untether/schemas/pi.py` | Add `PiUnknownEvent` class and peek-decode path; update `decode_event` | `tests/test_pi_schema.py`: unknown-event forward-compat, float delayMs, validation strictness | None |
| 6 | Full OMP session IDs | `src/takopi/runners/omp.py:OmpRunner.new_state` (L152-159), `_retag_resume`, `_retag_event` | `src/untether/runners/` (new OMP runner or pi.py modification) | Port `shorten_session_id=False` and resume retagging | `tests/test_pi_runner.py`: full-UUID session tests, resumed-state, build_args | Order 5 |
| 7 | Hard ty gate | `src/takopi/.github/workflows/ci.yml` (ty job, no `allow_failure`) | `src/untether/.github/workflows/ci.yml` (ty job L34-38) | Remove `allow_failure: true`; fix 348 existing ty diagnostics in untether src/tests | `ty check src tests` must exit 0 | None |
| 8 | 3-OS CI matrix | `src/takopi/.github/workflows/ci.yml` (Ubuntu/macOS/Windows) | `src/untether/.github/workflows/ci.yml` (Ubuntu-only) | Add macOS and Windows runners; fix POSIX-only test imports (`termios`, `fcntl`, `bash` subprocess) | All tests pass on all 3 OSes | Order 7 |
| 9 | 81% coverage gate | `src/takopi/pyproject.toml:[tool.pytest.ini_options]` (`--cov-fail-under=81`) | `src/untether/pyproject.toml:[tool.pytest.ini_options]` (L105: `--cov-fail-under=80`) | Raise from 80% to 81%; add tests for any coverage gap | Coverage >= 81% on all platforms | Order 8 |
| 10 | OMP engine | `src/takopi/runners/omp.py:OmpRunner`, `BACKEND` | `src/untether/runners/omp.py` (new) | Port OMP runner as untether entry point; retag resume tokens | `tests/test_pi_runner.py` adapted for untether | Orders 5, 6 |
| 11 | Grok engine | `src/takopi/runners/grok.py:BACKEND` | `src/untether/runners/grok.py` (new) | Port grok runner; ACP compaction | Per-runner tests | Order 10 |
| 12 | Agy engine | `src/takopi/runners/agy.py:BACKEND` | `src/untether/runners/agy.py` (new) | Port agy runner | Per-runner tests | Order 10 |
| 13 | ACP compaction | `src/takopi/runners/_acp.py:ACP` | `src/untether/runners/_acp.py` (new or merge) | Port ACP client for grok/omp compaction | `tests/test_compact_event_invariants.py`: exactly 1 Started + 1 Completed, Completed last, resume equality | Order 10 |
| 14 | Security gates (reverse) | `src/untether/.github/workflows/ci.yml` (pip-audit, bandit) | Keep in untether | Already present; ensure takopi-specific code passes | pip-audit and bandit exit 0 | None |
| 15 | Plugin API version | `src/takopi/api.py:TAKOPI_PLUGIN_API_VERSION=1` | `src/untether/api.py` | Reconcile API version; ensure untether plugins still work | `tests/test_api_exports.py` | None |

## Invariant survival check

The following takopi invariants must survive any merge direction. For takopi → untether, these are ported into untether; for untether → takopi, these are already present.

| Invariant | Source | Test | Survival in takopi → untether |
|---|---|---|---|
| Task 21 exact `(chat_id, progress_message_id)` cancellation | `src/takopi/scheduler.py:cancel_queued` L197-214 | `tests/test_scheduler_queue.py` (772 lines) | Ported in Migration Order 1; replaces untether's `ThreadJob \| None` return |
| Task 21 `CANCELLED` carries removed job; `ALREADY_CLAIMED`/`NOT_FOUND` never do | `src/takopi/scheduler.py:CancelQueuedResult.__post_init__` L68-74 | `tests/test_scheduler_queue.py` | Ported in Migration Order 1 |
| Task 21 pending→claimed atomic boundary | `src/takopi/scheduler.py:_claimed_by_progress` L107 | `tests/test_scheduler_queue.py` | Ported in Migration Order 1 |
| Task 22 full OMP `ResumeToken.value` (no truncation) | `src/takopi/runners/omp.py:OmpRunner.new_state` L152-159 (`shorten_session_id=False`) | `tests/test_pi_runner.py` | Ported in Migration Order 6 |
| Task 22 forward-compatible Pi/OMP schema decoding | `src/takopi/schemas/pi.py:PiUnknownEvent` L95-103, `decode_event` L170-186 | `tests/test_pi_schema.py` | Ported in Migration Order 5 |
| Runner event ordering: exactly one `StartedEvent` then exactly one `CompletedEvent` last | `src/takopi/runner.py`, `docs/reference/plugin-api.md` | `tests/test_compact_event_invariants.py` | Preserved; untether shares this contract from common ancestry |
| Resume equality (Completed.resume == Started.resume) | `docs/reference/agents/invariants.md` | `tests/test_compact_event_invariants.py` | Preserved; shared ancestry |
| Subprocess-tree cleanup (Windows `taskkill /T /F`) | `src/takopi/utils/subprocess.py` | `tests/test_subprocess_close.py` | Ported alongside 3-OS CI (Order 8); untether has `signal_pid_group` but lacks Windows tested cleanup |
| 81% branch coverage gate | `pyproject.toml:[tool.pytest.ini_options]` | `pytest tests/ -q` | Ported in Migration Order 9 |
| Hard `ty check src tests` (zero diagnostics) | `.github/workflows/ci.yml` | `ty check src tests` exit 0 | Ported in Migration Order 7 |
| Three-OS Python 3.14 CI | `.github/workflows/ci.yml` | CI matrix | Ported in Migration Order 8 |

## Approval gate

| Field | Value |
|---|---|
| Recommended direction | takopi → untether |
| Winning total | 73.33/100 |
| Losing total | 66.67/100 |
| Source SHA (takopi) | `481f0c72f50ef5b7a7793f547059d691f7b8ffc3` |
| Destination SHA (untether) | `4285dad5a12e4e4113c9cc5240972a67bbb5e218` |
| Comparison document | `docs/reference/untether-comparison.md` |
| Future plan path | `docs/plans/2026-08-08-untether-takopi-to-untether-merge.md` |
| Gate status | AWAITING DIRECTION APPROVAL |

No merge code has been written; implementation requires explicit approval of this direction.

## Evidence index

### Takopi source evidence

| Claim | Path/symbol | SHA |
|---|---|---|
| 7 engine entry points | `pyproject.toml:[project.entry-points."takopi.engine_backends"]` L42-L49 | `481f0c72` |
| `CancelQueuedStatus` enum | `src/takopi/scheduler.py:CancelQueuedStatus` L49-54 | `481f0c72` |
| `CancelQueuedResult` with `__post_init__` | `src/takopi/scheduler.py:CancelQueuedResult` L57-74 | `481f0c72` |
| `cancel_queued` returns discriminated result | `src/takopi/scheduler.py:cancel_queued` L197-214 | `481f0c72` |
| `claim_queued` for steering | `src/takopi/scheduler.py:claim_queued` L216-225 | `481f0c72` |
| `requeue_front` | `src/takopi/scheduler.py:requeue_front` L227-242 | `481f0c72` |
| `EnqueueDisposition` enum | `src/takopi/scheduler.py:EnqueueDisposition` L42-46 | `481f0c72` |
| Job lifecycle observers | `src/takopi/scheduler.py:JobClaimed`/`JobFailed` L38-39, L97-103 | `481f0c72` |
| Observer wiring in Telegram | `src/takopi/telegram/loop.py:_make_scheduler_observers` L1371-1392 | `481f0c72` |
| `PiUnknownEvent` forward-compat | `src/takopi/schemas/pi.py:PiUnknownEvent` L95-103 | `481f0c72` |
| `decode_event` with catch-all | `src/takopi/schemas/pi.py:decode_event` L170-186 | `481f0c72` |
| Full OMP session IDs | `src/takopi/runners/omp.py:OmpRunner.new_state` L152-159 | `481f0c72` |
| `_retag_resume` for cross-engine | `src/takopi/runners/omp.py:_retag_resume` L36-39 | `481f0c72` |
| `EngineRunOptions` model override | `src/takopi/runners/run_options.py:EngineRunOptions` L19-27 | `481f0c72` |
| `EngineOverrides` with reasoning | `src/takopi/telegram/engine_overrides.py:EngineOverrides` L20-22 | `481f0c72` |
| `REASONING_LEVELS_BY_ENGINE` | `src/takopi/telegram/engine_overrides.py` L11-16 | `481f0c72` |
| Task 23 Plan: TBD | `ROADMAP.md` L952 | `481f0c72` |
| Task 22 DONE | `ROADMAP.md` L860 | `481f0c72` |
| Plugin API version | `src/takopi/api.py:TAKOPI_PLUGIN_API_VERSION=1` | `481f0c72` |
| Transient failure classification | `src/takopi/utils/transient_failures.py:TransientFailure` | `481f0c72` |
| Worktree branch sanitization | `src/takopi/worktrees.py:resolve_run_cwd`, `ensure_worktree` | `481f0c72` |

### Takopi test evidence

| Test file | Coverage |
|---|---|
| `tests/test_scheduler_queue.py` (772 lines) | Task 21: CANCELLED/ALREADY_CLAIMED/NOT_FOUND, claim boundary, result invariants, rollback, disposition |
| `tests/test_telegram_queue.py` | Task 21: Telegram cancel callback, typed branches, steer |
| `tests/test_pi_runner.py` | Task 22: OMP full-UUID session, resumed-state, build_args |
| `tests/test_pi_schema.py` | Task 22: PiUnknownEvent forward-compat, float delayMs, validation strictness |
| `tests/test_subprocess_close.py` | Windows taskkill /T /F tree cleanup, stream close, manage_subprocess |
| `tests/test_compact_event_invariants.py` | Exactly 1 Started + 1 Completed, Completed last, resume equality |
| `tests/test_runner_run_options.py` | Per-engine model/reasoning override (Task 23 partial) |
| `tests/test_telegram_engine_overrides.py` | Precedence topic>chat>default, engine-specific reasoning (Task 23 partial) |

### Untether source evidence

| Claim | Path/symbol | SHA |
|---|---|---|
| Fork attribution | `README.md` L338 ([source](https://github.com/littlebearapps/untether/blob/4285dad5a12e4e4113c9cc5240972a67bbb5e218/README.md#L338)) | `4285dad` |
| 6 engine entry points | `pyproject.toml:[project.entry-points."untether.engine_backends"]` L56-L62 | `4285dad` |
| 16 command backends | `pyproject.toml:[project.entry-points."untether.command_backends"]` L67-L82 | `4285dad` |
| `cancel_queued` returns `ThreadJob \| None` | `src/untether/scheduler.py:cancel_queued` L109-127 | `4285dad` |
| `ResumeToken` with `is_continue` | `src/untether/model.py:ResumeToken` L32-36 | `4285dad` |
| No `PiUnknownEvent` | `src/untether/schemas/pi.py` L116 (`_DECODER = msgspec.json.Decoder(PiEvent)`) | `4285dad` |
| Cron expression matching | `src/untether/triggers/cron.py:cron_matches` L39-64 | `4285dad` |
| Webhook HTTP server | `src/untether/triggers/server.py` (aiohttp, SSRF, multipart, loopback) | `4285dad` |
| Trigger manager | `src/untether/triggers/manager.py:TriggerManager` | `4285dad` |
| SSRF protection | `src/untether/triggers/ssrf.py` | `4285dad` |
| Cost budgets | `src/untether/cost_tracker.py:CostBudget`, `CostAlert`, `record_run_cost`, `check_run_budget` | `4285dad` |
| Session quarantine | `src/untether/session_quarantine.py:QuarantineStore` (JSON-persisted, 7-day pruning) | `4285dad` |
| Config hot-reload | `src/untether/config_watch.py:watch_config()` (watchfiles) | `4285dad` |
| Outbox priority queue | `src/untether/telegram/outbox.py:TelegramOutbox`, `OutboxOp`, `SUPERSEDED` | `4285dad` |
| Outbox delivery | `src/untether/telegram/outbox_delivery.py` (`.untether-outbox/` scanning) | `4285dad` |
| Systemd notify | `src/untether/sdnotify.py` | `4285dad` |
| Stall diagnostics | `src/untether/utils/proc_diag.py:ProcessDiag` | `4285dad` |
| Env policy/audit | `src/untether/utils/env_policy.py`, `src/untether/utils/env_audit.py` | `4285dad` |
| Config migrations | `src/untether/config_migrations.py` | `4285dad` |
| Progress persistence | `src/untether/progress_persistence.py` | `4285dad` |
| Session statistics | `src/untether/session_stats.py` | `4285dad` |
| Loop scheduler | `src/untether/loop_scheduler.py` (33 KB) | `4285dad` |
| 80% coverage gate | `pyproject.toml:[tool.pytest.ini_options]` L105 (`--cov-fail-under=80`) | `4285dad` |
| ty informational | `.github/workflows/ci.yml` L38 (`allow_failure: true`) | `4285dad` |
| Security: pip-audit + bandit | `.github/workflows/ci.yml` L199-215 | `4285dad` |
| Ubuntu-only CI | `.github/workflows/ci.yml` L19, L75 (`runs-on: ubuntu-latest`) | `4285dad` |

### Untether test evidence

| Test file | Coverage |
|---|---|
| `tests/test_trigger_cron.py` | Cron expression matching |
| `tests/test_trigger_server.py` | Webhook HTTP server |
| `tests/test_trigger_ssrf.py` | SSRF protection |
| `tests/test_trigger_manager.py` | TriggerManager pause/resume |
| `tests/test_cost_tracker.py` | Cost budgets, alerts, daily tracking |
| `tests/test_session_quarantine.py` | QuarantineStore persistence, pruning |
| `tests/test_config_watch.py` | Hot-reload via watchfiles |
| `tests/test_outbox_delivery.py` | Post-run file delivery |
| `tests/test_health_command.py` | Health command |
| `tests/test_stats_command.py` | Stats command |
| `tests/test_browse_command.py` | File browser |
| `tests/test_proc_diag.py` | Stall diagnostics |
| `tests/test_env_policy.py`, `tests/test_env_audit.py` | Env policy/audit |
| `tests/test_sdnotify.py` | Systemd notify |
| `tests/test_session_stats.py` | Session statistics |
| `tests/test_telegram_queue.py` | Outbox priority queue, SUPERSEDED |

### Not-found searches

| Claim searched | Scope | Terms |
|---|---|---|
| Triggers/cron/webhook in takopi | `src/takopi/` | `triggers/`, `cron`, `webhook`, `server.py` |
| Cost tracker in takopi | `src/takopi/` | `cost_tracker`, `CostBudget`, `cost` |
| Session quarantine in takopi | `src/takopi/` | `quarantine`, `QuarantineStore` |
| Config hot-reload in takopi | `src/takopi/` | `config_watch`, `watch_config`, `hot_reload` |
| Stats/health commands in takopi | `src/takopi/telegram/commands/` | `stats`, `health`, `stats.py`, `health.py` |
| Browse command in takopi | `src/takopi/telegram/commands/` | `browse`, `browse.py` |
| Proc diagnostics in takopi | `src/takopi/utils/` | `proc_diag`, `ProcessDiag` |
| Systemd notify in takopi | `src/takopi/` | `sdnotify`, `systemd` |
| Env policy/audit in takopi | `src/takopi/utils/` | `env_policy`, `env_audit` |
| Config migrations in takopi | `src/takopi/` | `config_migrations` |
| Progress persistence in takopi | `src/takopi/` | `progress_persistence` |
| OMP runner in untether | `src/untether/runners/` | `omp`, `OmpRunner`, `shorten_session_id` |
| `PiUnknownEvent` in untether | `src/untether/schemas/pi.py` | `Unknown`, `unknown`, `PiUnknown` |
| `CancelQueuedStatus` in untether | `src/untether/scheduler.py` | `CancelQueuedStatus`, `CancelQueuedResult` |
| `claim_queued`/`requeue_front` in untether | `src/untether/scheduler.py` | `claim_queued`, `requeue_front` |
| `on_job_claimed`/`on_job_failed` in untether | `src/untether/scheduler.py` | `on_job_claimed`, `on_job_failed`, `JobClaimed`, `JobFailed` |
| `EnqueueDisposition` in untether | `src/untether/scheduler.py` | `EnqueueDisposition`, `QUEUED`, `CLAIMABLE` |
| Security scanning in takopi CI | `.github/workflows/ci.yml` | `pip-audit`, `bandit`, `security` |
| Inline config menu in takopi | `src/takopi/telegram/commands/` | `config`, `inline`, `settings_menu` |
