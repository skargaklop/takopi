# Takopi → Untether Gap-Closure and Cutover Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `subagent-driven-development` or `executing-plans`; execute the ordered sections with their verification gates, preserving the safety and rollback rules below.

**Goal:** Close the remaining source, verification, roadmap, configuration, state, and runtime gaps in the Takopi-to-Untether migration without regressing Untether-only behavior.

**Architecture:** Reuse Untether’s command backend, scheduler, run-options object, existing `RunOutcome`, Telegram stores, presenter/transport, runner lifecycle, and plugin contracts. Add only the missing consumers and transactional seams; keep live cutover actions last and reversible.

**Tech stack:** Python 3.12–3.14, AnyIO, msgspec/Pydantic settings, Telegram transport, uv, pytest, Ruff, ty, GitHub Actions.

---

## Objective and authority

Finish the migration specified by `D:/Projects/takopi/docs/plans/2026-08-09-takopi-untether-audit-cutover-plan.md`, correct its evidence ledger against the current Untether tree, carry the genuinely unfinished Takopi roadmap work requested by the user, and re-prove the already-completed live cutover. Source and behavior tests in `D:/Projects/untether` override stale completion language in `docs/audits/2026-08-09-takopi-feature-port-audit.md`; `D:/Projects/takopi/docs/reference/untether-comparison.md` remains mandatory historical evidence, not current truth. `D:/Projects/takopi/ROADMAP.md` is the sole roadmap carryover source.

Before editing, record the Untether and Takopi revisions and working-tree state. The last read-only audit saw Untether `f23881123522a5336201934d7ec48a82eb7ef0bf` and Takopi `e51e256850d9a3b1bde447690a1c9fc6db6474cf`; treat both as `unverified — confirm first` at execution time. Preserve all unrelated user changes. Never print Telegram credentials, allowed-user/chat IDs, resume tokens, state contents, lock fingerprints, or secret environment values.

## Reconciled disposition matrix

### Implemented — retain and regression-test

- Scheduler cancellation/claim/requeue, enqueue dispositions, lifecycle observers, FIFO isolation, prompt batching, `EngineRunOptions` and `ThreadJob` directive fields, Pi/OMP forward-compatible decoding, full OMP IDs, OMP/Grok/Agy registration, compact core/mixins/ACP, Windows stream closure, three-OS pytest, and the 81% branch-coverage configuration are present.
- Directives, goal-over-plan precedence, mode badges/context composition, Pi plan extension fallback, newline-terminated stdin, Telegram spoiler/underline/strike preprocessing, file-task annotation, runner settings, transient retry skeleton, startup/idle read guards, queue command, and compact/handoff dispatch have source implementations. Their audit rows must be changed from blanket “ported/complete” to the precise current classifications below where integration proof is absent.
- Preserve Untether-only Gemini/Amp, triggers, costs/budgets, quarantine, config watch/migrations, outbox delivery, stats/health/browse/auth/config/model commands, environment policy/audit, diagnostics/watchdogs, persistence, systemd notification, security/release jobs, plugin discovery, approval refire, path/URL redaction, recent-event ring, subprocess ownership, and queue steering/cancellation.

### Partial or missing — close in this execution

1. **Compact/handoff approval and card lifecycle — partial.** `src/untether/telegram/commands/compact.py:PendingCompactConfirm` exists but is unused; `handle_compact_command()` immediately enqueues handoff-only and cross-engine work and sends ad-hoc messages. `run_compact_job()` and `run_handoff_job()` in `telegram/loop.py` also send separate status/failure/completion messages.
2. **Atomic handoff routing — missing proof and unsafe success detection.** `run_handoff_job()` calls `run_job()` with the ordinary `wrap_on_thread_known()` persistence callback, so the destination token can be written as soon as it is known, before the destination seed reaches successful completion. `run_job()` returns no outcome, and phase two currently declares success after it returns even if the runner emitted `CompletedEvent(ok=False)`.
3. **Meta-command and harness consumption — partial.** Directive parsing carries `plan`/`goal`/`skill`/`subagent`, but Untether lacks Takopi's dual-mode `/plan`/`/goal` classifier, sticky plan storage, `/subagent` preference handler/storage, and Claude/OpenCode `--agent` consumption. `format_mode_badge()`/`compose_context_line()` exist but have no consumers. Their source-backed presentation contract is plan/goal only; absent skill/subagent badges are not a gap. Skill remains intentionally one-shot data only because neither Takopi’s completed implementation nor current harness evidence provides a safe CLI injection or sticky skill contract.
4. **Cancellation and ACP lifecycle settings — partial.** `RunnerSettings.kill_tree_on_cancel` and `shutdown_timeout_s` are assigned by `runtime_loader.py`, but `JsonlSubprocessRunner` has no consuming attributes and `manage_subprocess()` unconditionally calls Windows `kill_process_tree()` with a hard-coded POSIX wait. ACP clients retain a hard-coded 60-second request timeout instead of consuming `startup_timeout_s`.
5. **Retry/timeout terminal behavior — partial.** `JsonlSubprocessRunner.run_impl()` retries only before a visible start/action/answer and uses linear backoff, but final/non-replay transient failures flush the provider `CompletedEvent` unchanged. `_iter_jsonl_with_timeouts()` also silently treats startup/idle expiry like EOF.
6. **Pi goal-list extension — missing.** `src/untether/runners/pi.py:_final_prompt()` always applies the autonomous-goal prefix. It has no detector/state for `pi-goal-list-loop-audit` and no first-message `<task-goal>…</task-goal>` seed.
7. **Hard verification gates — partial.** `.github/workflows/ci.yml` keeps `ty` informational with `allow_failure: true`; format/Ruff/ty run only on Ubuntu. Focused port tests mostly test helpers/defaults rather than the loop/runtime contracts. No fresh complete branch-coverage or native engine evidence is recorded.
8. **Audit accuracy — stale.** The audit ledger identifies old HEAD `daca548c`, says all E-items are complete, calls roadmap Tasks 4/20 not applicable, incorrectly claims Pi goal-list seeding and Claude/OpenCode subagent injection were ported, and does not distinguish implemented data fields from missing consumers.
9. **Live configuration/state — runtime-unverified.** The inspected `C:/Users/DELL E5570/.untether/untether.toml` still contains the obsolete top-level `[logging]` table. The startup launcher and global tool were already repaired. Earlier cutover evidence says the three stores were copied and two CWD-bound chat sessions were intentionally cleared; a later read-only audit saw Untether's chat-session store empty while Takopi's remained populated. Treat this as a conflict to resolve safely at execution time, not permission to overwrite post-cutover Untether state.

### Runtime-unverified

- Native OMP/Grok/Agy/ACP compact/handoff probes, post-change Telegram approval/card/routing behavior, one-poller ownership after restart/logon, and pre-cutover Windows service/scheduled-task inventory require live tools or authorized Telegram access. Deterministic fixtures remain mandatory even when credentials are unavailable.

### Superseded / not applicable / stale historical claims

- `[[takopi-send: path]]` is superseded by `.untether-outbox`; Takopi namespace/release chores and removed image config keys are not applicable; `pi.plan_flag` is superseded by extension detection. The comparison’s claims that Untether lacks scheduler hardening, Pi/OMP compatibility, registered OMP/Grok/Agy runners, Windows cleanup, three-OS tests, and an 81% threshold are stale.
- Roadmap disposition is explicit: carry Takopi Tasks 4, 20, and 23 under Untether **Future** because the user selected those three. Task 4 is speculative and not a migration blocker, but remains a requested research item; Task 20 is partial because adapters/evidence are incomplete; Task 23 is substantially implemented but its full documented/tested acceptance matrix is incomplete. Do not add E12/E13 as roadmap features: they are mandatory closure work in Steps 10 and 12. Task 24’s evaluation, direction choice, and migration execution are this plan’s already-approved work, so do not duplicate it as a roadmap bullet or add a misleading new “Shipped” claim.

## Ordered implementation

### 1. Freeze evidence and correct the audit method

Read current revisions/status and rerun the ledger reconciliation before behavior edits. Update `D:/Projects/untether/docs/audits/2026-08-09-takopi-feature-port-audit.md` only after implementation/tests establish final dispositions. Retain citations to the authoritative plan and comparison, update both HEAD fields, use the requested vocabulary (`implemented`, `partial`, `missing`, `runtime-unverified`, `superseded`, `not-applicable`, `stale`), and split source behavior, deterministic verification, runtime evidence, and roadmap-only work. Replace the incorrect E5 and completion table claims; record that the earlier global `uv` tool failure was stale installed code repaired by a forced local-source reinstall, with no source change required.
Before closing ledger rows E2/E3/A16, distinguish parser/data-field presence from behavior: sticky/meta dispatch, plan/goal card composition, and Claude/OpenCode subagent injection remain partial until their destination tests pass. Record `/skill` as intentionally one-shot, carried-but-not-injected data. Record that badges/context footers intentionally show only plan/goal, matching Takopi’s source; skill/subagent remain observable through command status/argument tests rather than a new card badge. Do not invent sticky skill or skill CLI-injection contracts.

### 2. Implement authorization-scoped compact/handoff confirmation

Use `src/untether/telegram/commands/compact.py` for the operation record and decision logic, and `telegram/loop.py` for loop-owned scheduler/state/transport integration; do not add a second command dispatcher. Replace dead `PendingCompactConfirm` with a record containing an opaque random token, operation kind, source resume, instructions, destination engine, chat/thread/session routing keys, initiating sender ID, original user message ID, progress `MessageRef`, creation/expiry monotonic times, and claimed state. The callback payload carries only `compact:<token>:confirm|cancel`; never include resumes/instructions.

Add a bounded registry to `TelegramLoopState` plus prune/claim helpers. A claim is atomic and one-shot: require the same chat/thread and authorized initiating user (normal global callback allowlist remains the first gate), reject expired/missing/already-claimed tokens idempotently, answer every callback query, and clear the keyboard. Use a conservative five-minute expiry; expired records edit the same card to `expired` when touched/pruned and never enqueue. Bound retained pending records to 256, pruning expired/oldest records before insertion.

`handle_compact_command()` behavior:

- Native same-engine true compaction remains immediate and FIFO-queued.
- Handoff-only support, explicit `/handoff`, and every cross-engine destination create one confirmation card with source/destination and a concise warning that a new destination session will be seeded. They do not enqueue until Confirm.
- Cancel edits that same card to terminal `cancelled`; repeated/stale callbacks are harmless.
- Confirm edits the card to `queued`, stores its ref in `ThreadJob.progress_ref`, and enqueues exactly once on the source resume FIFO. If enqueue fails, edit the same card to `failed` and discard the claim.

Add the compact callback interception before generic command callback dispatch in `telegram/loop.py`; reuse its existing sender allowlist logic and transport `answer_callback_query`. Keep `PendingCompactConfirm` internal—no callback registration through plugin `CommandBackend` because the operation needs loop scheduler and routing stores.

### 3. Restore the source-backed meta-command and subagent surface

Port Takopi's `telegram/commands/meta_args.py`, `plan_cmd.py`, `goal_cmd.py`, and `subagent_cmd.py` behavior into Untether's existing command-backend/pre-dispatch architecture rather than adding a parallel dispatcher. Classification is exact: `/plan` with no args or one of `on|off|clear|show` is meta; other `/plan <prompt>` falls through as a plan run. Bare `/goal` is help; non-empty `/goal <condition>` falls through. `/subagent`, `/subagent show|off|clear`, and `/subagent set <name>` are meta; `/subagent <name> <prompt>` is one-shot. Existing pure commands remain meta. Keep `/planmode` as the separate Claude permission-mode command; do not conflate it with agent plan prompting.

Add nullable plan-mode persistence to `ChatPrefsStore` and `TopicStateStore` using their existing versioned, locked, atomic-write patterns. Resolution precedence is explicit one-shot goal, explicit one-shot plan, topic sticky plan, chat sticky plan, default off; any goal forces effective plan false. Plan preference mutations require the same private-chat/group-admin authorization used by Takopi and apply to topic scope when an eligible topic exists, otherwise chat scope. Add chat-scoped nullable subagent persistence; explicit one-shot subagent wins over sticky. Preserve unknown legacy fields during read/write according to each store's current migration policy.

Add `--agent <name>` to Claude and OpenCode argument construction when `EngineRunOptions.subagent` is present, matching current Grok behavior and Takopi's captured CLI evidence; in OpenCode, the explicit subagent replaces its plan-agent selection. Pi/OMP/Agy and Codex remain documented no-ops because no equivalent native flag is proven. Skill remains parsed/carried one-shot data only and is not injected or made sticky. Wire menu/reserved-command and prompt-batching classification so meta forms never spawn and free-form dual-mode forms batch/run normally.

### 4. Make one card own the complete operation lifecycle

Introduce narrow loop helpers that render/edit compact/handoff cards without changing the general presenter. Card states are `confirmation`, `queued`, `claimed`, `running summary`, `seeding destination`, and terminal `completed`, `cancelled`, `expired`, or `failed`. Every transition edits `job.progress_ref`; remove `send_plain()` lifecycle calls from `handle_compact_command()`, `run_compact_job()`, and `run_handoff_job()`. The optional rendered summary may be a separate final content message only after the lifecycle card is terminal; it is not another status card.

Extend `_on_job_claimed()` to branch on `job.kind` and edit the operation card rather than constructing a normal prompt tracker. `_on_job_failed()` already edits by `progress_ref`; give compact/handoff a safe operation-specific failure body and clear controls. Catch cancellation separately: propagate AnyIO cancellation after a shielded terminal-card edit and leave routing unchanged. User-visible failures must pass through `user_safe_error()` and must not contain raw provider JSON.

Compose the existing plan/goal-only `format_mode_badge()`/context footer for ordinary queued/running/cancelled/completed prompt cards at every current `format_context_line()` callsite. Do not add skill/subagent badges without a source-backed display contract. Keep directive values only in `EngineRunOptions`/`ThreadJob`; remove the temporary positional `plan/goal/skill/subagent` parameters from nested `run_job()` and have every dispatch path supply one options object. This clean cutover prevents prompt, queued, batched, trigger, compact/handoff seed, and callback paths from diverging.

### 5. Make handoff routing transactional

Do not use ordinary `wrap_on_thread_known()` persistence during phase-two seeding. Reuse `runner_bridge.RunOutcome(cancelled, completed, resume)`; do not create a second terminal-result abstraction. Change `handle_message(...) -> None` to return the final `RunOutcome`, propagate it through `telegram/commands/executor.py:_run_engine()` and the loop’s `run_job()` seam, and preserve all ordinary prompt callbacks and result rendering. `send_result_message()` remains the owner of normal final rendering/deletion. For handoff phase two, capture the destination resume in memory only and pass no topic/chat persistence callback. Extend `_CaptureTransport` only as needed to retain the rendered result plus the propagated `RunOutcome`, giving command/executor tests an observable seam rather than asserting helper internals.

Commit routing only when all invariants hold: phase one produced a `RunOutcome` whose `completed` is present and `ok=True` with a non-empty summary; destination `RunOutcome.cancelled` is false; destination `completed` is present and `ok=True`; destination `resume` exists and its engine matches `handoff_target`; and the operation was not otherwise cancelled. Then persist that token to the applicable `TopicStateStore.set_session_resume()` and/or `ChatSessionStore.set_session_resume()` and edit the card `completed`. Missing terminal events, false completion, empty summary, destination exception, missing/mismatched token, persistence error, or cancellation edits `failed`/`cancelled` and leaves the old routing value untouched. If one of two stores writes and the second fails, restore the captured prior values in the first store before reporting failure; a rollback failure is logged as a high-severity invariant breach with redacted identifiers and the operation remains failed.

The full summary—not the Telegram-truncated display—must feed `handoff_seed_prompt()`. Same-engine handoff still creates a new session. Preserve the warning that replies to old messages retain their embedded old resume.

### 6. Wire runner lifecycle and ACP settings completely

In `src/untether/utils/subprocess.py`, extend `manage_subprocess(..., shutdown_timeout_s: float = 5.0, kill_tree_on_cancel: bool = True)`. On Windows, true retains `taskkill /T /F`; false terminates, waits, then kills and waits for the direct child only. On POSIX, preserve process-group termination but replace the hard-coded ten-second wait with `shutdown_timeout_s`. Post-exit orphan reaping and stream/process `aclose()` remain unconditional.

Add `shutdown_timeout_s` and `kill_tree_on_cancel` attributes to `JsonlSubprocessRunner` and pass both to every `manage_subprocess()` call it owns. Audit direct callers, including Claude and ACP subprocess transport: they must consume the global values through declared runner/transport attributes or explicitly document why a fixed plugin-owned default is retained. `kill_tree_on_cancel=false` controls only the additive Windows descendant-tree kill; direct-child reaping, POSIX process-group cleanup, watchdog cleanup, and orphan reaping stay enabled. Preserve `ProgressEdits._enforce_cancel_teardown()` and its existing `_CANCEL_ESCALATION_S`, `_CANCEL_ESCALATION_POLL_S`, and `_CANCEL_SIGKILL_GRACE_S` safety path; do not gate it on this Windows-only setting because `signal_pid_group()` is POSIX-only.

Wire ACP `request_timeout_s` from the owning runner's `startup_timeout_s or 60.0` and `close_timeout_s` from `shutdown_timeout_s`, including compact client factories. Add positive validation (`gt=0`) for startup, idle, and shutdown timeouts; keep retry attempts `ge=1` and base delay `ge=0`.

Add Windows-faked and POSIX-faked tests proving tree kill true/false, direct child always reaped, timeout escalation, process-group/watchdog behavior unchanged, clean exit untouched, and stream/aclose cleanup on every path. Assert runtime-loader values reach real JSONL and ACP consumers rather than only fake attributes.

### 7. Finish retry and timeout contracts

Refactor `JsonlSubprocessRunner.run_impl()` so one classifier result drives both retry and final rendering. Retry only if no `StartedEvent`, `ActionEvent`, or non-empty answer has become visible; total attempts equal `retry_max_attempts`; delays are `retry_base_delay_s * attempt` before attempts 2..N. Do not replay cancellation, malformed/non-transient failures, or any run that exposed possible side effects/output.

When a classified transient error cannot retry or exhausts attempts, replace its terminal error with `format_transient_failure(failure)` while preserving safe answer/resume/usage fields. Never flush the raw provider blob. Emit one retry note per delay and exactly one terminal failure. Maintain the existing richer watchdog, stderr capture, approval, memory guard, environment, and diagnostic paths.

Make `_iter_jsonl_with_timeouts()` distinguish EOF from timeout and surface a deterministic startup/idle failure to its caller instead of silently ending iteration. Startup timeout applies before the first decoded/visible event; idle timeout resets after each line. Zero/negative values are not accepted by `RunnerSettings`; add `gt=0` validation for startup, idle, and shutdown. Tests use fake clocks/streams and cover first-line timeout, between-line timeout, normal EOF, cancellation, 503 twice then success (attempt count 3; delays base and 2×base), non-transient single attempt, started/action/non-empty-answer no replay, and sanitized exhaustion.

### 8. Complete Pi goal-extension behavior without regressing plan mode

In `src/untether/runners/pi.py`, generalize the existing extension-root lookup into a package detector and add `_GOAL_LIST_EXTENSION_PACKAGE = "pi-goal-list-loop-audit"` plus `detect_goal_list_extension(root: Path | None = None) -> bool`. Resolve both extension flags once in `build_runner()` and store them on `PiRunner`; no filesystem probing per run.

Goal precedence remains above plan. With a goal and the goal-list extension present on a fresh session, make the first message exactly `<task-goal>{escaped goal}</task-goal>\n\n{user prompt}` (omit the second block for an empty user prompt); escape `&`, `<`, and `>` in the goal so user content cannot close the directive. Do not also add the autonomous-goal prefix. On resumed/continued sessions, do not reseed the extension; use the normal user prompt because the goal list belongs to the seeded session. Without the extension, retain the current `(autonomous goal — work until: …)` prefix. Plan behavior remains: `--plan` with `@narumitw/pi-plan-mode`, soft-plan prefix and one warning without it. Goal always suppresses `--plan`.

Route any multi-line/directive payload through `stdin_payload()` with exactly one trailing newline; single-line ordinary prompts remain argv-based. Add tests for both detectors, fresh goal seed, escaped goal, empty prompt, resumed no-reseed, fallback prefix, goal-over-plan, extension-present plan args, one-time fallback warning, and UTF-8/newline behavior.

### 9. Move focused tests to observable integration seams

Keep useful helper tests in `tests/test_takopi_ported_behaviors.py`, but add behavior coverage in existing destination modules where available rather than growing one migration grab-bag:

- `tests/test_telegram_compact_dispatch.py` (create): command interception, no-active-session, native immediate path, approval required for handoff-only/explicit/cross-engine, authorization, opaque/expiring/idempotent callbacks, enqueue failure, one-card transitions, FIFO claim, cancellation, phase-one/seed failure, full summary, and atomic route commit/rollback for topic and common chat.
- `tests/test_runner_retry.py` and `tests/test_runner_timeouts.py` (create): the contracts in Steps 6 and 7 using a minimal fake JSONL runner and deterministic sleep/stream fakes.
- `tests/test_directives.py` (create) plus command/store tests: parser errors and goal precedence; meta-versus-run classification; plan chat/topic precedence and authorization; goal help; sticky/one-shot subagent precedence; menu and prompt-batch behavior; plan/goal badges on queued/running/cancelled/completed cards; absence of invented skill/subagent badges; Claude/Grok/OpenCode `--agent`; and documented no-op engines. Exercise `_CaptureTransport`/executor results where command output is the observable contract.
- Existing Pi runner tests: Step 8 plus model/run-options coexistence.
- Existing renderer tests (locate the current renderer test module before adding): exact entities outside code, literal markers in inline/fenced code, malformed/unclosed markers.
- `tests/test_telegram_files.py` plus the upload/loop integration fixture: exact non-image annotation `Execute the task specified in this file: `incoming/<name>`.` and exactly one attachment; image behavior unchanged.
- Existing scheduler/queue tests: compact/handoff jobs share per-resume FIFO and do not regress exact cancel/claim/steer behavior.
- ACP/OMP/Grok/Agy fixture suites: compact factories/events, forward-compatible schemas, capacity failures, and preserved full OMP IDs.

Tests assert visible events, transport sends/edits, store values, spawned args/payloads, and attempt counts—never source text or mere attribute assignment.

### 10. Make CI gates honest and cross-platform

First run `uv run --no-sync ty check src tests` and fix all diagnostics at source, including Windows portability around `signal.SIGKILL`, AnyIO checkpoint usage, path assumptions, and test doubles. Then remove `allow_failure: true`. Expand `checks` to an OS × task matrix for format, Ruff, and ty on Ubuntu, macOS, and Windows while retaining lock/docs as single Ubuntu jobs; set `PYTHONUTF8=1` for cross-platform cells. Avoid shell-specific command indirection on Windows: give matrix rows direct `uv run` commands or OS-specific shells. Keep pytest Python 3.12/3.13/3.14 compatibility and the existing three-OS Python 3.14 job; keep branch coverage as one Linux source of truth.

Do not carry forward advisory ignores blindly. Run `pip-audit` first; for every reproducing advisory, update to the smallest compatible fixed dependency and regenerate `uv.lock`. Remove an ignore only when the locked package is fixed; retain an ignore only when the advisory is in tooling not controlled by the project and record evidence in the ledger. Add no new ignore.

### 11. Carry the user-selected unfinished Takopi roadmap work without claiming delivery

Append exactly three bullets under `D:/Projects/untether/ROADMAP.md` **Future**, using its current bold-bullet format and avoiding Shipped/Near-term/Mid-term promises:

- **Additional coding-agent engines** — requested carryover of Takopi Task 4. Research and, only where a stable headless protocol exists, add Droid, Cline, Kilo, Warp, Open Interpreter, Mimo Code, ZCode, and Kimi Code through Untether’s plugin runner contract, with captured protocol evidence, resume/config/docs, and fixture/live-gated tests. This is speculative research, not a migration acceptance gate.
- **Cross-engine tool-action detail parity** — requested carryover of partial Takopi Task 20. Capture real tool input fields and normalize command/path/pattern titles and narration segmentation for Codex, OpenCode, Pi/OMP, and Agy while preserving shared generic helpers and existing Grok/Claude behavior.
- **End-to-end model override guarantees** — requested carryover of substantially implemented Takopi Task 23. Document precedence and harness limitations; prove explicit per-run > topic > chat > engine/runner default behavior, persistent-scope isolation, and new/resumed/queued/batched/handoff propagation through `EngineRunOptions` and each native runner/ACP request without cross-scope bleed.

These are roadmap-only; do not implement their broad feature scope during migration closure. Do not add Task 24: its evaluation and chosen Takopi→Untether execution are represented by this plan and audit. Do not add E12/E13 roadmap bullets: hard `ty` and cross-platform static checks are mandatory execution gates, not future product work.

### 12. Align docs, changelog, and live config/state

Update the audit ledger after all deterministic checks, and add concise user-facing entries to `CHANGELOG.md` for compact/handoff safety, meta/directive parity, runner lifecycle/retry sanitization, Pi goal extension, and CI hardening. Document `[runners]` keys and semantics in the existing config reference (locate exact section first), including positive bounds, attempts meaning, linear backoff, ACP timeout mapping, and the narrow Windows meaning of `kill_tree_on_cancel`. Update command/directive documentation for confirmation, plan/goal/subagent precedence, no-op skill/subagent harnesses, model precedence/limitations, and goal-extension behavior. Do not create a second migration plan document.

Back up `C:/Users/DELL E5570/.untether/untether.toml` with restricted access, then remove only its obsolete `[logging]` table. Preserve effective non-default logging through the implementation's existing `TAKOPI_LOG_LEVEL`/`TAKOPI_LOG_FILE` environment controls if required; do not rename those variables during migration and never echo their values. Validate with the config loader and `untether doctor`. The config permits unknown top-level tables, so successful parsing alone does not prove cleanup—inspect table names without values.

Do not redo the startup rewrite or overwrite state blindly. Confirm the Startup line still targets `D:/Projects/untether/.venv/Scripts/untether.exe`, unrelated lines are unchanged, the installed tool imports the cross-platform `untether.lockfile`, and no Takopi poller/lock remains. Before any state action, stop all pollers, make restricted backups of both state directories, validate each of the three version-1 files by schema/mtime/count metadata without printing keys or values, and determine which store has post-cutover writes. If Untether contains newer writes, keep it authoritative. Recopy a Takopi file only when Untether's counterpart is absent/invalid and Takopi's is the last valid pre-cutover source; never merge by hand, never copy locks/logs, and rerun startup-CWD session validation afterward. Intentional clearing of CWD-bound sessions is not drift.

## Verification and release gates

Run from `D:/Projects/untether` with UTF-8 enabled. Stop at the first failing mandatory gate, fix the cause, and rerun that gate plus affected focused suites.

1. **Focused behavior:** run compact/handoff, scheduler queue, directives/meta/store/footer, Claude/OpenCode/Grok argument construction, Pi/schema, retry/timeout, subprocess/ACP, renderer, file/upload, prompt-batch, and ACP/OMP/Grok/Agy modules identified in Step 9 with `-q --no-cov`.
2. **Static gates:**
   - `uv run --no-sync ruff format --check src tests`
   - `uv run --no-sync ruff check src tests`
   - `uv run --no-sync ty check src tests` — zero diagnostics
   - `uv lock --check`
3. **Full tests:** `uv run --no-sync pytest tests/ -q --no-cov` on Windows, macOS, and Linux/Python 3.14; Ubuntu Python 3.12 and 3.13 compatibility cells. On Ubuntu/Python 3.14 run `uv run --no-sync pytest tests/ -q --cov=untether --cov-branch --cov-report=term-missing --cov-fail-under=81` and record the measured percentage.
4. **Docs/package:** run `uv run --no-sync python scripts/docs_prebuild.py` then `uv run --no-sync zensical build --clean`; `uv build`; `uvx twine check dist/*`; `uvx check-wheel-contents dist/*.whl`; install the wheel into a clean environment and import Untether plus every registered engine and transport backend, including `untether.lockfile` on Windows.
5. **Security:** `uv run --no-sync bandit -r src/ -c pyproject.toml -q`; `uv run --no-sync pip-audit --skip-editable --progress-spinner=off` with only evidence-justified existing tooling ignores if unavoidable.
6. **Runtime/native probes:** where installed/configured, run native OMP/Grok/Agy/ACP compact/handoff and model-override probes using environment-gated tests registered as `live_omp`, `live_grok`, `live_agy`, and `live_acp` markers (or the repository's documented equivalent if established first). Missing CLI/credentials classify only that probe `runtime-unverified`; deterministic tests may not be waived.
7. **Authorized Telegram smoke:** with exactly one Untether poller, verify one ordinary prompt/reply, `/health`, existing resume, topic routing, non-image file annotation, compact confirmation Cancel, compact confirmation Confirm, one-card lifecycle, successful route switch, and failed seed retaining old routing. Inspect logs for polling conflict, raw provider blobs, duplicate terminal messages, or credential leakage.
8. **Restart ownership:** verify the Startup target, restart/logoff-logon through the actual launcher, and repeat the one-process and authorized reply/health checks. Do not report process IDs or sensitive config.

## Rollback and failure rules

- Code/CI failure: do not alter the live runtime; restore only changes from this execution, preserving unrelated work.
- Config validation failure: restore the backed-up Untether config; do not point Untether at Takopi config.
- Runtime smoke failure: stop Untether, verify its lock/process is released, restore the previous launcher/config, and restart the last known-good owner. Never merge Untether-written state back into Takopi.
- Handoff runtime failure must itself prove the product invariant: the old route remains active and the single operation card reaches an honest terminal state.
- State schema rejection: leave the original sensitive JSON untouched, start without that file only if safe, and report the lost state category; never invent a converter.

## Completion criteria

Complete only when every source gap above has an observable test, all mandatory deterministic gates pass, the audit ledger matches current evidence, the three user-selected **Future** roadmap bullets exist exactly once with no Task 24 or E12/E13 duplicate, the obsolete live logging table is gone without secret disclosure, state authority is resolved without overwriting newer Untether writes, and runtime checks are either passed or narrowly recorded as `runtime-unverified` with the unavailable external prerequisite. No dead confirmation state, positional directive propagation, missing sticky/meta consumer, duplicate lifecycle message, raw transient provider error, premature route write, discarded `RunOutcome`, unwired runner/ACP setting, or false subagent-injection/badge claim remains.
