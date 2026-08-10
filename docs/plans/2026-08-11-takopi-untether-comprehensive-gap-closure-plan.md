# Takopi → Untether Comprehensive Gap-Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `subagent-driven-development` or `executing-plans`; execute each numbered slice test-first and commit it only after its focused gate passes.

**Goal:** Materialize the complete 453-commit Takopi audit, preserve the recently edited planning evidence in `D:/Projects/takopi/docs/plans`, and close every verified Untether migration gap: logging, OMP/Grok reliability, Claude-stall diagnosis, Codex steering, plan/goal presentation, long-answer delivery, voice transcription, `/stats`, and installed `/health` reliability.

**Architecture:** Takopi remains immutable behavioral evidence; production changes land only in `D:/Projects/untether`. Reuse Untether’s existing settings/logging startup, runner lifecycle, JSONL decoder, `RunnerTurnControl`, Telegram command registry/dispatcher, stores, presenter/transport, scheduler, `RunOutcome`, `VoiceTranscriber`, and doctor framework. No parallel dispatcher, runner base, retry framework, voice stack, splitter, or health implementation is introduced.

**Tech stack:** Python 3.12–3.14, AnyIO, Pydantic/msgspec, structlog, Telegram Bot API, Codex app-server JSON-RPC, AVT JSON CLI, uv, pytest, Ruff, ty, GitHub Actions.

---

## Context

The prior investigation inspected all 453 ordered Takopi commits through twelve disjoint audit slices and several migration documents, but most per-commit results remained trapped in read-only agent transcripts while visible planning concentrated on `/health`. This plan makes the audit evidence durable first, copies every local plan edited on 2026-08-11 into Takopi’s plan directory, then implements the full verified gap set rather than treating `/health` as the migration.

Current confirmed non-health gaps are Takopi-compatible TOML `[logging]`, production plan/goal indicators, OMP’s invalid timed JSONL read and argv prompt transport, Grok stderr-based transient classification, Codex app-server steering, Groq plus one configured AVT local voice model, explicit completed-run `/stats` semantics, and regression proof for complete Telegram splitting. Claude is a diagnosis task: current code already has cold-start and post-tool-result watchdogs, so source changes are forbidden until a deterministic signature proves a distinct defect.

## Approach

### 1. Preserve all recently edited planning artifacts and establish one authority

Before source edits, re-read `local://` modification times and copy the three plans observed as edited on **2026-08-11** byte-for-byte:

| Session-local source | Repository destination |
|---|---|
| `local://slash-health-migration-gap-plan.md` | `D:/Projects/takopi/docs/plans/2026-08-11-slash-health-migration-gap-plan.md` |
| `local://takopi-untether-complete-gap-audit-plan.md` | `D:/Projects/takopi/docs/plans/2026-08-11-takopi-untether-complete-gap-audit-plan.md` |
| `local://takopi-untether-gap-closure-plan.md` | `D:/Projects/takopi/docs/plans/2026-08-10-takopi-untether-gap-closure-plan.md` |

Also copy this canonical plan to `D:/Projects/takopi/docs/plans/2026-08-11-takopi-untether-comprehensive-gap-closure-plan.md`. The existing 2026-08-10 destination is the repository copy of the same plan, so replace it with the newer local bytes rather than create a duplicate. Do not copy older unchanged local plans that already have repository equivalents. Verify every source/destination pair with SHA-256 equality. These documentation copies form the first independent commit: `docs(plans): preserve complete migration planning evidence`.

The comprehensive plan is authoritative when older plans conflict. In particular, it supersedes the old decisions to remove `[logging]`, postpone voice implementation, or focus migration closure on `/health` alone.

### 2. Materialize and validate the full 453-commit audit before behavior changes

Create `D:/Projects/takopi/docs/plans/2026-08-11-takopi-commit-contract-ledger.md`. Populate it from the twelve audited ordinal ranges `1–38`, `39–76`, `77–114`, `115–152`, `153–190`, `191–228`, `229–266`, `267–304`, `305–342`, `343–380`, `381–418`, and `419–453`. For each commit record ordinal, full SHA, subject, behavioral family, final-contract contribution, and disposition. Then deduplicate into feature rows retaining every contributing SHA, final Takopi source/test/doc anchors, current Untether anchors, and exactly one disposition: `implemented`, `partial`, `missing`, `runtime-unverified`, `superseded`, `not-applicable`, or `stale`.

Validation is mechanical and blocking:

- `git log --all --reverse --format=%H` in `D:/Projects/takopi` yields exactly 453 hashes, first `75fa95752feac42d05dc635c450027c69aa6ae17`, last `d28e5ba7cf449608634c4a3ab6206998e6d4f0ae`;
- every ordered hash occurs in the ledger exactly once; no range boundary overlaps or skips;
- every behavioral row cites a diff, not only a subject;
- removals/refinements resolve to final Takopi behavior;
- `implemented` requires source plus observable test/probe evidence, including relevant error, cancellation, security, and platform behavior.

The prior agent output for ranges 115–152 and 343–380 was truncated/corrupted. Recover those rows from the local Takopi commit history/diffs during execution; do not infer missing rows from summaries. The partially recovered 343–380 candidates—optional Telegram configuration, coercible chat IDs, OpenCode numeric prompts, Codex app-server/compaction rendering, topic-thread document replies, Pi reasoning levels, and malformed-list tightening—remain `unverified — confirm from diff and current Untether source first`. For each confirmed candidate, use this fixed disposition rule: source plus equivalent behavioral tests → `implemented`; equivalent source without the full observable test → `partial` and add the missing regression to the nearest covered slice; no equivalent source → `missing` and append a self-contained numbered subsection immediately before Step 13 containing the exact Takopi symbol, Untether target/callsites, failing test, minimal implementation, focused command, and commit message. Do not edit that behavior until this canonical local plan has been incrementally updated with that subsection; implemented/superseded candidates remain ledger-only.

Reconcile the completed ledger against Takopi’s three migration plans, comparison, roadmap, and Untether’s audit/roadmap. Update `D:/Projects/untether/docs/audits/2026-08-09-takopi-feature-port-audit.md` only after focused tests prove final dispositions. Commit the complete evidence independently: `docs(audit): account for every Takopi commit`.

### 3. Restore Takopi-compatible TOML logging

Test first in `tests/test_settings.py`, `tests/test_logging.py`, and `tests/test_logging_redaction.py`. Add strict `LoggingSettings(level, file, format)` to `src/untether/settings.py` and mount it as `UntetherSettings.logging`. Wire it through `src/untether/cli/run.py` into the existing `src/untether/logging.py::setup_logging()`; do not create another logger configuration path.

The exact precedence is `--debug` > `TAKOPI_LOG_LEVEL` > TOML > default for level, while `TAKOPI_LOG_FILE` and `TAKOPI_LOG_FORMAT` override TOML. Relative files resolve below `~/.untether`, files append as UTF-8, and configuration remains restart-applied. Invalid level/format fails settings validation. File-open failure disables only the file sink and reports a sanitized nonfatal diagnostic. Preserve console color/trace behavior and existing Telegram/OpenAI/GitHub-token redaction; tests must prove raw tokens and configured values never enter logs. Commit: `feat(config): restore TOML logging compatibility`.

### 4. Repair the shared OMP/Grok timed JSONL reader at its root

Re-read `src/untether/runner.py::_iter_jsonl_with_timeouts` and its tests immediately before editing. The latest inspected implementation directly awaited `stdout.readline()` while `anyio.open_process()` supplies a `StreamReaderWrapper` byte receive stream. First add a regression using the real AnyIO wrapper with both deadlines enabled; it must reproduce the missing-`readline` failure.

Replace only the read mechanism: consume the existing `iter_json_lines(stdout)` async iterator one line at a time under the current startup deadline before the first line and idle deadline thereafter. Preserve clean EOF handling, malformed JSON routing through `_iter_jsonl_events`, cancellation, `BrokenResourceError`, `ClosedResourceError`, and `EndOfStream`. Timeout must remain a distinct `RunnerTimeoutError`, never silent EOF. Cover first-line success, later-line success, startup timeout, idle timeout, clean EOF, cancellation, and execution through both OMP and Grok. If execution-time source already uses the AnyIO iterator and the real-wrapper regression passes, record the historical bug as implemented and make no source change. Commit only if changed: `fix(runner): read timed JSONL through AnyIO streams`.

### 5. Preserve Grok stderr so shared transient retry can classify failures

In `tests/test_grok_runner.py` and shared retry tests, reproduce `rc != 0` with bounded sanitized stderr containing `Internal error` and HTTP 503/429. Current `GrokRunner.process_error_events()` emits only `grok failed (rc=N).`, unlike Pi/OMP, so the shared classifier cannot see the transient evidence.

Update `src/untether/runners/grok.py::process_error_events` to use the existing bounded `_stderr_excerpt` pattern used by Pi/OMP. Feed the excerpt into the failed `CompletedEvent.error`; do not add a Grok-only classifier or retry loop. The existing shared `classify_transient_failure()` remains authoritative: retry only before any `StartedEvent`, `ActionEvent`, or non-empty answer; use existing bounded attempts/backoff; preserve cancellation; on unsafe/exhausted retry emit `format_transient_failure()` without raw JSON. Non-transient exits remain one attempt and keep their current safe behavior. Retain an OMP bare-503 regression to prove no shared regression. Commit: `fix(grok): preserve transient stderr for shared retry`.

### 6. Move every OMP prompt from argv to the documented stdin boundary

Authoritative OMP CLI documentation at `D:/Projects/omp-docs-20260702/cli.md:90-102` states one-shot `-p` reads stdin. In `tests/test_omp_runner.py`, prove ordinary, multiline, goal/soft-plan, and larger-than-Windows-command-line prompts are absent from `build_args()` and returned once as newline-terminated UTF-8 by `stdin_payload()`.

Add one private `OmpRunner._final_prompt(...)` helper used by both methods. Remove the prompt argv append while preserving resume, model, provider, thinking, attachment, mode, and sanitization flag order. Reuse `JsonlSubprocessRunner.stdin_payload()` transport, which sends and closes stdin before JSONL consumption. Do not add prompt files, shell pipelines, RPC, or a second subprocess loop. Test exact single delivery and stdin closure. Commit: `fix(omp): transport prompts through stdin`.

### 7. Diagnose Claude startup stalls before permitting a repair

Instrument only sanitized boundaries already owned by `src/untether/runners/claude.py::run_impl`: process spawned, stdin sent/closed, first stdout byte, first stderr byte, first decoded event, silence classification, tool-result watchdog transition, timeout, and process exit. Log event names, durations, byte counts, and exception types only—never prompts, messages, paths, credentials, raw output, transcripts, or environment/config values.

Create deterministic fixtures in `tests/test_claude_runner.py` for: zero-byte cold start; stdout bytes without a full JSON line; stderr-only startup; normal first event; post-tool-result silence; EOF before terminal completion; and cancellation during startup. Correlate the reported live symptom with existing Type B `CLAUDE_STREAM_IDLE_TIMEOUT_MS` or `WatchdogSettings.detect_stuck_after_tool_result` behavior. If one existing mechanism correctly terminates the fixture, add observability/regression coverage only. A source repair is allowed only when a fixture shows a distinct boundary defect; fix that shared boundary minimally and add the failing fixture unchanged. Keep unresolved live-only behavior `runtime-unverified`; never add a third speculative timeout. Commit either `test(claude): expose startup stall boundaries` or, when proven, `fix(claude): repair <exact boundary>`.

### 8. Restore Codex app-server steering and interruption

Port the verified Takopi app-server contract from `D:/Projects/takopi/src/takopi/runners/codex.py` into `src/untether/runners/codex.py`, adapting to Untether’s subprocess/logging/security helpers. Default `codex.mode` to `app_server`; retain explicit `exec` fallback. Preserve one lazy client per runner, JSON-RPC correlation, `thread/start`, `thread/resume`, `turn/start`, notification translation, commentary/plan events, bounded shutdown, stream closure, Windows tree cleanup, sanitized EOF/errors, and no replay after possible side effects.

Implement `_AppServerTurnControl.steer()` as `turn/steer` with `threadId`, `expectedTurnId`, and exactly one text input; implement `interrupt()` as `turn/interrupt`. Publish the control in `StartedEvent.meta["control"]`. In `runner_bridge.py::run_runner_with_cancel`, attach it to `RunningTask.control` before `on_thread_known` and `resume_ready`; call `interrupt()` best-effort before task-group cancellation while preserving cancellation if RPC fails.

Reuse existing scheduler claim/requeue and Telegram steer/cancel paths. Exact-resume matching is mandatory. Successful steer consumes one queued job and edits only its queued card to `steered`; RPC failure requeues it at the front; repeated same-turn steering retains the active control. Never emulate steering by cancel/resubmit. Test initialization/start/resume/turn, exact RPC bodies, control timing, interrupt-before-cancel, duplicate prevention, failure requeue, thread isolation, EOF visibility, and cleanup. Use two green commits: `feat(codex): add app-server turn control`, then `feat(telegram): wire Codex steering lifecycle`.

### 9. Wire visible plan/goal indicators and prove full answer splitting

Reuse `src/untether/directives.py::compose_context_line()` and `format_mode_badge()` at every production `format_context_line()` seam in `telegram/loop.py`, `telegram/commands/cancel.py`, and `telegram/commands/executor.py`. Queued, claimed/running, cancelled, and completed cards show `goal` before the existing context/session identity when goal exists, otherwise `plan`; do not invent skill/subagent badges.

Do not build another splitter. Add presenter/transport regressions proving `message_overflow="split"` delivers all content in ordered Telegram-safe chunks, preserves entity/code-fence boundaries and reply/thread identity, emits exactly one context/resume footer, and attaches terminal controls only to the final part. Preserve explicit `trim`. Change production only if those behavior tests expose a real regression. Commit indicators separately (`feat(telegram): show plan and goal state`); use `fix(telegram): preserve complete split answers` only if code changes.

### 10. Add Groq and exactly one configured local AVT voice backend

Reuse `src/untether/telegram/voice.py::VoiceTranscriber` and `transcribe_voice()`; OpenAI remains the compatibility default. Extend `TelegramTransportSettings` with:

```python
voice_transcription_provider: Literal["openai", "groq", "local"] = "openai"
voice_transcription_groq_api_key: SecretStr | None
voice_transcription_local_command: NonEmptyStr = "D:/Projects/AI-Video-Transcriber/.venv/Scripts/avt.exe"
voice_transcription_local_backend: Literal["whisper", "parakeet"] = "whisper"
voice_transcription_local_model: NonEmptyStr = "base"
voice_transcription_timeout_s: float = Field(default=180.0, gt=0)
```

Groq reuses the existing OpenAI-compatible transcriber with fixed base URL `https://api.groq.com/openai/v1` and model `whisper-large-v3-turbo`; reveal the secret only at the transport call. Custom OpenAI base URLs retain existing SSRF validation.

Add `AvtVoiceTranscriber` that writes private `.ogg` bytes, invokes exactly the configured `avt.exe --quiet transcribe --file <path> --provider local --local-backend <backend>` plus `--local-model <model>` for Whisper, applies the configured AnyIO timeout, bounds stdout/stderr, requires exit zero and JSON with a non-empty string `transcript`, preserves cancellation, and unlinks the temporary file in `finally`. No AVT module imports/server coupling, fallback provider/model, preset probing, model cycling, automatic alternate download, or cache deletion. Doctor reports configured backend/model/cache path and size without contents; missing executable reports local transcription unavailable. Tests cover secret masking, exact argv, Groq boundary, malformed/empty/nonzero output, timeout/cancellation, cleanup, hot reload, existing size/language/SSRF protections, and proof no alternate model is attempted. Commit settings/remote and local adapter as separate green slices.

### 11. Make `/stats` semantics explicit without fabricating runs

Keep the existing `RunStatsRecord(engine, duration_s, action_count, completed_at, triggered)` and `_record_stats_run()` call from successful terminal delivery. `/stats` means **completed runs only**: include registered engine IDs for which records exist, exclude attempts failing before `CompletedEvent`, and do not fabricate zero rows. Update `telegram/commands/stats.py` labels/help text to say `completed runs`; retain current scope filtering and no-sessions response.

Add integration tests around terminal delivery: a successful completed run appears once with engine/action/duration; a pre-completion failure is absent; a failed delivery does not record success; records for Agy/Grok/OMP appear when supplied; empty data does not render invented engines. If current behavior already satisfies the contract, this slice is tests/docs only. Commit: `test(stats): define completed-run semantics` (or `fix(stats): record completed-run semantics` if implementation changes).

### 12. Implement installed-runtime `/health` reliability as one bounded command flow

Execute `local://slash-health-migration-gap-plan.md` without narrowing any earlier slice. First add `/pi hello` resolver regression (`prompt == "hello"`, `engine_override == "pi"`), real installed command-registry tests, generic `error: command unavailable`, and loop dispatch proving `/health` sends HTML without resolver/runner calls.

Add frozen `RuntimeStatusSnapshot(active_runs, queued_jobs, triggers_enabled, cron_count, webhook_count)` to `CommandContext`, `ThreadScheduler.queued_count()`, and optional dispatch timing. `HealthCommand.handle()` sends an immediate alive/uptime/active/queued/trigger summary, retains its `MessageRef`, concurrently gathers system/process/usage collectors with `anyio.to_thread.run_sync`, 1.0-second collector limits and a 2.0-second overall limit, then edits the same message with Service, Process, System, Usage, and Diagnostics sections. Each ordinary failure degrades only its section to `unavailable`/`timed out`; cancellation escapes; no detached task; failed edit leaves the initial response.

Emit only sanitized timing/status events named in the health plan. Extend clean-wheel CI to enumerate/load every `untether.command_backends` entry point and assert name/backend ID equality including `health`. Use the health plan’s five commits, keeping them separate from all other features. Startup-owned Telegram smoke remains last and authorization-gated.

### 13. Reconcile all newly confirmed commit-derived candidates and roadmap authority

After Steps 2–12, revisit every `partial`, `missing`, `stale`, and actionable `runtime-unverified` ledger row. Any confirmed candidate not already covered gets a test-first slice inserted before this step and its own green commit; no candidate may disappear into prose. Update Untether’s roadmap exactly once for genuinely deferred user-facing work. Preserve existing Future Tasks 4, 20, and 23 exactly once; do not add Task 24, E12, or E13. Mark native credentialed probes and unresolved Claude/live Telegram evidence `runtime-unverified`, never `implemented`.

Update the Untether audit, config/operations references, and changelogs to match tested reality. Historical test counts and old cutover claims are evidence only, not acceptance. Preserve unrelated work and commit each independently reviewable slice immediately after its focused verification.

## Critical files & anchors

1. `D:/Projects/untether/src/untether/runner.py::{JsonlSubprocessRunner._iter_jsonl_with_timeouts,run_impl}` — shared AnyIO JSONL timeout and retry boundary for OMP/Grok.
2. `D:/Projects/untether/src/untether/settings.py::{UntetherSettings,TelegramTransportSettings}` — logging and voice configuration authority.
3. `D:/Projects/untether/src/untether/runners/{omp,grok,claude,codex}.py` — four distinct runtime contracts; reuse the common runner lifecycle rather than forking it.
4. `D:/Projects/untether/src/untether/telegram/{loop.py,voice.py,commands/dispatch.py,commands/health.py,commands/stats.py}` — visible command, delivery, and transcription behavior.
5. `D:/Projects/takopi/docs/plans/` plus `D:/Projects/untether/docs/audits/2026-08-09-takopi-feature-port-audit.md` — durable evidence, canonical plan copies, and final disposition authority.

## Verification

Run focused gates from `D:/Projects/untether` with `PYTHONUTF8=1`; each slice’s test must fail before implementation and pass before its commit.

1. **Plan preservation/audit:** SHA-256 compare all four local/repository plan pairs. Generate ordered Takopi hashes and mechanically compare them to the 453 ledger rows; expected sets and order are identical with no duplicates.
2. **Logging:** `uv run --no-sync pytest tests/test_settings.py tests/test_logging.py tests/test_logging_redaction.py -q --no-cov`; expected TOML/env/debug precedence, append, relative path, nonfatal sink failure, and redaction all pass.
3. **OMP/Grok:** `uv run --no-sync pytest tests/test_runner_utils.py tests/test_omp_runner.py tests/test_grok_runner.py -q --no-cov`; expected real AnyIO stream works under both deadlines, OMP prompt is stdin-only, Grok 503/429 retries only before visible progress, and raw provider JSON never reaches terminal output.
4. **Claude:** `uv run --no-sync pytest tests/test_claude_runner.py -q --no-cov`; every startup/stall signature reaches a deterministic existing timeout/watchdog or the exact repaired boundary, while cancellation propagates.
5. **Codex:** `uv run --no-sync pytest tests/test_codex_runner_helpers.py tests/test_runner_bridge.py tests/test_telegram_bridge.py -q --no-cov`; if the port introduces a dedicated app-server module, include that discovered `tests/test_codex_app_server.py` path in the same command. Expected: exact `turn/steer`/`turn/interrupt`, control attached before resume callbacks, one claim, front requeue on RPC failure, and clean shutdown.
6. **Presentation/stats/voice:** discover the current test modules with `glob` before editing, then run the existing directive/presenter/transport/stats/session suites plus `tests/test_settings.py tests/test_telegram_voice.py tests/test_bridge_config_reload.py tests/test_cli_helpers.py -q --no-cov`. Send a >Telegram-limit fenced-code answer through the fixture and observe every ordered chunk, one footer, final controls only. Supply AVT fake JSON and observe one configured invocation/cleanup. Complete/fail runs and observe completed-only stats.
7. **Health:** run the exact focused commands and clean-wheel sweep in `local://slash-health-migration-gap-plan.md`; expected immediate send precedes blocked collectors, the exact same `MessageRef` is edited, failures isolate, and no runner/resolver handles `/health`.
8. **Static/full/package:** `uv run --no-sync ruff format --check src tests`; `uv run --no-sync ruff check src tests`; `uv run --no-sync ty check src tests`; `uv lock --check`; `uv run --no-sync pytest tests/ -q --no-cov`; Linux branch coverage at least 81%; `uv build`; `uvx twine check dist/*`; `uvx check-wheel-contents dist/*.whl`; docs build; Bandit; pip-audit; clean-wheel import/entry-point sweep. Required CI runs Windows/macOS/Linux and supported Python versions.
9. **Authorized runtime last:** verify Startup still owns exactly one Untether poller, then exercise `/health`, `/pi hello`, `/health`, one OMP prompt, one configured voice sample, and one stats-producing completion. Require the poller to survive and logs to contain no secrets/raw provider payload. Missing credentials/authorization marks only these live probes `runtime-unverified`; deterministic gates remain mandatory.

## Assumptions & contingencies

- “Recently edited” is fixed by observed local modification dates: the three plans modified on 2026-08-11 are copied, plus this new canonical plan. If execution discovers another `.md` under `local://` with a 2026-08-11 modification time, add it to the copy table using its existing basename/date convention and SHA-256 proof before committing.
- The complete audit is not allowed to rely on truncated agent transcripts. Missing 115–152 or 343–380 rows are reconstructed from local Git diffs; unavailable historical/live evidence is labeled `runtime-unverified` rather than guessed.
- Current OMP/Grok `readline()` status is source-drift-sensitive. A real-wrapper failing test decides whether production changes are necessary; do not rewrite an already repaired iterator.
- Claude receives no speculative fix. If no deterministic distinct defect reproduces, ship only sanitized boundary observability and tests, and retain the live symptom as `runtime-unverified`.
- One configured local AVT backend/model is authoritative. No fallback/download/cache deletion occurs without a separate operator decision.
- Repository and system state remain read-only until this plan is approved. During execution, preserve unrelated changes and never print credentials, IDs, state contents, prompt/answer bodies, raw probe output, temporary paths, or endpoint secrets.
