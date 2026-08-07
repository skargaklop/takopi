# changelog

## unreleased

### omp/pi stream compatibility

- forward-compatible Pi/OMP stream decoding: unknown-but-valid `type` tags (e.g. `notice`, `auto_retry_start`) now decode to `PiUnknownEvent` and produce one DEBUG diagnostic per line instead of raising `jsonl.msgspec.invalid`. Known event structs remain strict. Malformed lines stay line-local — the decoder skips the bad line and continues translating later events.
- float `delayMs` tolerance: OMP 17.2.10 emits float `duration`/`ttft`/`delayMs` values; the schema now accepts `int | float | None` without rounding or normalizing producer precision.
- full OMP session IDs: OMP opts out of Pi's abbreviated session-ID behavior via an explicit `shorten_session_id` policy on `PiStreamState`. OMP `StartedEvent`/resume footers now surface the complete UUID (e.g. `019fde20-f307-7000-a94b-3b2d53fee35d`), matching `omp --resume <full-uuid>`.
- OmniRoute 503 capacity classification: the shared `transient_failures` classifier now recognizes OMP's bare `503 … retry-after-ms=…` prefix (no `http`/`status` keyword) and deduplicates the provider-suffixed reason. Capacity 503s are attributed to OmniRoute (surfaced through OMP), not OMP-owned capacity. Pre-start `rc=0` retries and `stopReason:"error"` completions both classify as transient.
- file-backed task workflow: non-image document uploads with `auto_put_mode="prompt"` now instruct the agent to execute the task contained in the uploaded file (`Execute the task specified in this file: \`<path>\`.`) instead of annotating with a passive `[uploaded file: ...]` marker. Turns long structured prompts into first-class file-backed runs.
- `live_omp` pytest marker and live OMP stream smoke (`tests/test_omp_stream_live.py`): spawns the real `omp` CLI, translates the JSONL stream through `OmpRunner`, and asserts a clean Started/Completed lifecycle plus full session-id preservation. Skipped when `omp` is absent.

### ci

- cross-platform GitHub Actions CI matrix: `.github/workflows/ci.yml` now runs lint (`format`, `ruff`, `ty`) and `pytest` on `ubuntu-latest`, `macos-latest`, and `windows-latest`. `ty` is a hard gate (Task 18 reached zero diagnostics). Coverage gate (`--cov-fail-under=81`) runs on Linux only to avoid triple-counting. `PYTHONUTF8=1` is set on all jobs. `build` and `docs` stay Linux-only. The `notify-commit` Telegram job is removed.

### typing

- zero-diagnostic `ty check src tests` baseline: corrected all 41 diagnostics at the source (structural `self` protocols for compact mixins, `ReplyCallable` named protocol returning `MessageRef | None`, Telegram `message_id` narrowing, `meta_args` default return, `loop.py` optional narrowing, cross-platform `_kill_process_group` typing). No `# type: ignore`, `cast(Any, ...)`, or rule weakenings.

### features

- production ACP stdio transport: `SubprocessAcpTransport` implements newline-delimited JSON-RPC 2.0 over a managed subprocess with exact framing, ID correlation, queued `session/update` notifications, server-request `-32601` replies, and `AcpProtocolError` for malformed/EOF/timeout/mismatch responses. `AcpClient` is an async context manager with protocol-version-1 gating, capability-driven `session/load`/`session/resume` (never `session/new`), and `session/prompt` for compact. Reuses `manage_subprocess`, `drain_stderr`, and AnyIO streams — no JSON-RPC dependency added.
- `shutdown_timeout_s` propagation: `JsonlSubprocessRunner.shutdown_timeout_s` now feeds `manage_subprocess(close_timeout=...)`, and `runtime_loader.build_router` propagates `RunnerSettings.shutdown_timeout_s` alongside startup/idle/retry settings. Closes the gap between documented config and runtime use.
- `live_acp` pytest marker and per-engine ACP compact smoke probes (`tests/test_grok_compact_acp.py`, `tests/test_omp_compact_acp.py`): skip without `TAKOPI_GROK_ACP_SESSION_ID`/`TAKOPI_OMP_ACP_SESSION_ID`. Both Grok and OMP remain `HandoffCompactMixin` (`mode="handoff_only"`, `true_compaction=False`) until each harness's own probe passes. Evidence records at `docs/reference/runners/{grok,omp}/acp-compact.md`.


### features

- runner compaction protocol: runners MAY implement `compact_support()` and `compact()` to participate in `/compact`. Five modes: `slash_prompt` (claude, pi, codex), `native_api` (opencode), `handoff_only` (agy, omp, grok), `none`. Compact jobs serialize on the same `ThreadScheduler` as prompt jobs. See [specification §5.7](reference/specification.md#57-runner-compaction-protocol-may).
- show a `plan` or `goal` mode badge in the Telegram message footer, preceding the `ctx:` line, so active plan/goal runs are visible at a glance.
- global `[runners]` config section: `startup_timeout_s` (60s default), `idle_timeout_s` (900s default), `kill_tree_on_cancel` (true default). Applied to all runners uniformly, never duplicated per engine.
- transient upstream failure retry for JSONL runners: `JsonlSubprocessRunner` now classifies stderr/`CompletedEvent.error` for transient HTTP 503/429 and API capacity errors via `classify_transient_failure()`, retries with linear backoff (`retry_base_delay_s * attempt`) up to `retry_max_attempts` times, and emits a clean user-facing message ("\<engine\> upstream is temporarily unavailable") instead of raw JSON blobs. Retries are safe — no retry after session start, actions, or answer output; cancellation during backoff aborts promptly.
- `[runners] retry_max_attempts` (3 default, min 1) and `retry_base_delay_s` (5.0 default, min 0.0) config keys controlling transient failure retry behavior, applied globally to all runners.
- process-tree cleanup on cancellation: Windows now uses `taskkill /T /F` to kill the entire subprocess tree (POSIX already uses process groups via `os.killpg`). Fixes orphaned `opencode.exe` / MCP server processes surviving cancellation.
- codex app-server cleanup: `_AppServerClient.stop()` method terminates the app-server process tree on stdout-close or shutdown; previously the process was never killed.
- `CREATE_NEW_PROCESS_GROUP` flag on Windows subprocess creation, mirroring POSIX `start_new_session=True`.
- `[opencode] print_logs` and `[opencode] log_level` config keys to pass `--print-logs` and `--log-level` to the OpenCode CLI.
- `takopi doctor` now reports runner processes (codex, claude, opencode, etc.) and flags potential orphaned processes.
- `/compact` dispatch robustness: works from any reply context (final message footer, active run) and in any order relative to engine selectors (`/codex /compact` = `/compact /codex`). Engine precedence: explicit selector > reply-footer token > chat/topic default.
- `/compact` confirmation flow for engines without native compaction: inline keyboard with "send anyway" (plain-text handoff prompt) and "cancel" buttons, replacing the previous flat refusal.
- `/compact` errors are now surfaced to the user (previously silently swallowed by the scheduler).
- `/compact` acknowledges on enqueue: an immediate message ("compacting…" or "creating handoff summary…") confirms the job was queued, before the runner starts.
- `/compact` lifecycle feedback: the terminal `CompletedEvent` is now consumed and reported — success says "compaction completed." (true compaction) or "handoff summary finished." (handoff-only); failure says "compact failed: <error>".
- omp and grok compact now use `HandoffCompactMixin` (handoff-summary prompt via `run()`) instead of the test-only ACP path. ACP compact (`AcpCompactMixin`, `FakeAcpTransport`) remains in the codebase for future subprocess-transport work.
- `HandoffCompactMixin` shared mixin in `_compact_mixin.py` — used by agy, omp, and grok; replaces inline `compact_support()`/`compact()` implementations.
- `/compact` handoff-as-new-session: engines without true compaction (handoff_only + none) now show an approval card (two buttons). On approve: (1) handoff summary produced in the OLD session, (2) NEW session seeded with the full summary via `handoff_seed_prompt`, (3) routing flips to the new session id automatically, (4) summary echoed to the user (truncated). Actual context reduction, honestly labeled.
- `handoff_seed_prompt(summary)` in `compact.py`: seeds a new session with the full handoff summary and a "acknowledge briefly and wait" instruction.
- `ThreadJob.kind` now includes `"handoff"` for the two-phase migration job.
- Fixed pre-existing `tg.start_soon(confirmed=True)` kwargs bug in compact confirm/decline callback dispatch (now uses `functools.partial`).
- `/handoff` command for all engines: always runs the approval → handoff summary → new-session migration, even on engines with native compaction. Ignores `compact_support()` entirely. Shares the same executor, parser, and approval gate as `/compact` (DRY). On no-compaction engines `/compact` and `/handoff` are identical; on true-compaction engines `/compact` compacts in place while `/handoff` forces a clean session break.
- cross-engine handoff: `/handoff to <engine>` and `/compact to <engine>` migrate a session to a different engine (e.g. omp → grok). The destination receives the seed prompt via normal `run()` — no compact support needed, so any configured engine is valid. Parser recognizes `to <known-engine>` (leading `/` tolerated); unknown/non-engine words stay as instructions. Unavailable destinations fail before the approval card. `CompactInvocation.destination_engine`, `ThreadJob.handoff_target`, and `PendingCompactConfirm.destination_engine` carry the target through the pipeline.
- explicit transport close at every subprocess spawn site: `close_process_streams()` closes stdio pipe transports after kill+wait in `manage_subprocess()` and the codex app-server `stop()`, preventing the proactor `__del__` ResourceWarning / "Exception ignored … ValueError: I/O operation on closed pipe" noise at interpreter teardown. Bounded per-stream timeout (`shutdown_timeout_s` config key, 5s default). Child-interpreter regression test guards against the noise recurring.
- grok tool-title adapter: grok tool calls now show real commands and paths in progress (e.g. `command: uv run pytest`, `read: 'file'`, `file_change: 'src/...'`) instead of useless generic `tool: <name>`. The `_grok_tool_kind_and_title` adapter maps grok names (`run_terminal_command`→`bash`, `read_file`→`read`, `search_replace`→`edit`, `list_dir`→`ls`, etc.) and normalizes input fields (`target_file`→`file_path`) before delegating to the shared helper.
- grok tool events as narration delimiters: `tool_call` and `tool_call_update` now close the current text segment, so narration produced between tool calls no longer leaks into the final answer. Only the trailing text run after the last tool event becomes the answer.
- grok tool-call mapping: `tool_call` and `tool_call_update` events from the grok CLI now become `action_started` / `action_completed` `ActionEvent`s via the shared `tool_kind_and_title` helper (same pattern as the claude runner). Tool activity is visible in progress steps instead of being silently dropped. Duplicate `tool_call` starts for the same `toolCallId` are suppressed.
- grok usage telemetry: mid-stream `usage` events are buffered and merged into the terminal `CompletedEvent.usage` (end-event usage takes precedence on conflicts).
- grok forward compatibility: unknown event types (e.g. future CLI additions) now decode to a `StreamUnknownEvent` catch-all (DEBUG log, no events) instead of raising `msgspec.ValidationError` and spamming the log at WARNING level. Only genuinely malformed JSON triggers a warning.
- subagent and skill selection: `/codex --subagent <name> <prompt>` (or `/subagent <name>`) selects a named subagent for a one-shot run; `--skill <name>` (or `/skill <name>`) selects a skill. Both forms parse in the leading command area alongside the engine selector and are name-passthrough (no validation — the harness resolves the name). Sticky `/subagent set <name>` / `/subagent off` / `/subagent clear` (chat-scoped) mirrors `/plan`. Wired for grok, claude, and opencode (`--agent`); codex maps to `--profile`. See [capability matrix](reference/runners/capability-matrix.md).
- grok plan-mode hard enforcement (Task 16): grok plan mode now keeps native `--permission-mode plan` AND restricts the toolset to a read-only allow-list (`--tools read_file,list_dir,grep,web_search`). Mutating tools are physically absent from the agent's toolset, so no approval prompt fires and the turn completes cleanly (`stopReason=end_turn`) instead of being cancelled. Proven by probe D2. Reverts the Task 15 soft-plan fallback. The salvage net remains as defense in depth. See [plan-mode-cancel.md](reference/runners/grok/plan-mode-cancel.md) for the probe matrix.
- grok plan-mode salvage safety net: when a plan-mode run still ends with `stopReason=cancelled` (e.g. upstream abort) and plan text was produced, the plan is now delivered as a soft success with the note "turn ended by plan-mode enforcement; nothing was executed" instead of an opaque error. An empty-answer plan-mode cancel keeps the honest read-only error. Non-plan and user-initiated cancels are unaffected.

### changes

- pi plan mode now detects the `@narumitw/pi-plan-mode` extension at runner startup. When detected, `--plan` is appended (delegating to the extension). When absent, Takopi falls back to the shared soft-plan prompt prefix and logs a one-time `pi.plan_mode_extension_missing` warning instead of blindly passing `--plan`. Removed the `pi.plan_flag` config flag — it is no longer needed.
- grok `plan_enforcement` changed from `"soft"` to `"allowlist"`, reflecting the switch from the soft-plan prompt prefix to native `--permission-mode plan` + read-only `--tools` allow-list (Task 16 hard enforcement).

### fixes

- pipe multi-line pi prompts (autonomous-goal prefix and any user prompt with newlines) through stdin instead of a CLI arg, fixing `pi failed (rc=126)` on Windows where `pi.cmd` rejects argv elements containing newlines.
- replying to a prior run's message now carries that run's engine forward for routing and stored-session lookups (previously only an explicit `/engine resume <id>` did, so replying to a non-default-engine run could start the default engine instead).
- outbound file delivery (`[[takopi-send: ...]]`) now accepts absolute paths that resolve inside the project root, not just project-relative paths. Paths escaping the root are still rejected.
- graceful shutdown on Ctrl+C: SIGINT now cooperatively cancels the event loop instead of tearing it down, so subprocesses are terminated and the HTTP connection pool is closed cleanly (eliminates `unclosed transport` / `ValueError: I/O operation on closed pipe` warnings on exit).
- grok progress no longer renders each **word** as a separate step: the grok CLI emits `thought` events at word/token granularity, and each was mapped to its own `ActionEvent` (step 1, step 2, … step 3517). Runner-side coalescing now buffers consecutive `thought` chunks and flushes them as a single note action when a non-thought event (text/end/error) arrives. No timers, no background tasks — purely event-driven. Existing renderer truncation caps the title.
- plan-mode read-only contradiction fixed: native plan-mode runners (grok `--permission-mode plan`, claude `--permission-mode plan`) run in harness-enforced read-only mode, but the injected instruction told the agent to "MUST produce a plan as a .md file" — a forbidden write. The grok harness cancels the entire turn on forbidden operations in headless mode, causing repeated `grok run stopped (cancelled)`. The instruction is now mode-aware: native read-only runners get "present the plan as your final TEXT answer, do NOT write files — Takopi saves and delivers your plan automatically" (auto-file delivery covers it); soft-plan runners (codex, omp, opencode) keep the existing file-write instruction unchanged. When a plan-mode run is cancelled by the harness, the error message honestly states "plan-mode turn cancelled by the harness (attempted a forbidden write/execute in read-only mode)" instead of the opaque "grok run stopped (cancelled)".

## v0.26.0 (2026-07-18)

### features

- Telegram image support for all engines: save photos under `incoming/images/`, append path annotations to prompts, optional image-only default prompt
- Codex native `-i` image args; Pi/OMP `@path` attachment args via run options
- New files settings: `image_subdir`, `image_default_prompt`, `image_force_prompt`

## v0.25.0 (2026-07-18)

### features

- add Antigravity CLI engine (`agy`) via headless plain-text `-p` mode with `--conversation` resume

## v0.24.0 (2026-07-18)

### features

- add Grok Build CLI engine runner (`grok`) via headless streaming-json
- richer Telegram progress headers (bold status, monospaced engine) and chat markdown: GFM/single-tilde strikethrough, `||spoiler||`, `++underline++`, blockquotes

### fixes

- treat Telegram `editMessageText` 400 "message is not modified" as a benign no-op instead of `telegram.http_error`

## v0.23.4 (2026-05-25)

### changes

- require Sulguk 0.12.0 for loose list item rendering and remove the local first-paragraph list shim

## v0.23.3 (2026-05-16)

### fixes

- keep loose ordered and unordered list item text on the marker line in Telegram messages [#243](https://github.com/banteg/takopi/pull/243)

## v0.23.2 (2026-05-15)

### changes

- support Telegram `/reasoning` overrides for Claude and PI with engine-specific allowed levels [#241](https://github.com/banteg/takopi/pull/241)

### fixes

- send Telegram file downloads back to the correct forum topic [#181](https://github.com/banteg/takopi/pull/181)
- render Codex context compaction events as progress actions [#240](https://github.com/banteg/takopi/pull/240)

## v0.23.1 (2026-05-15)

### fixes

- retry transient Telegram network errors instead of dropping requests or downloads [#239](https://github.com/banteg/takopi/pull/239)
- guard OpenCode against pure numeric prompts that crash the CLI parser [#237](https://github.com/banteg/takopi/pull/237)
- route Telegram callback data to matching command backends [#238](https://github.com/banteg/takopi/pull/238)

## v0.23.0 (2026-05-15)

### changes

- use `codex app-server` by default, enabling app-server commentary rendering and turn controls while keeping `codex.mode = "exec"` for the legacy `codex exec --json` runner [#236](https://github.com/banteg/takopi/pull/236)
- add Telegram `steer` / `cancel` buttons for queued Codex continuations when an active turn can accept steering [#236](https://github.com/banteg/takopi/pull/236)

### fixes

- keep busy queued jobs addressable until they actually start, so steer/cancel callbacks still work while a thread is occupied [#236](https://github.com/banteg/takopi/pull/236)
- prevent steered queued prompts from also running later as duplicate turns [#236](https://github.com/banteg/takopi/pull/236)
- surface Codex app-server shutdown during active turns as a rendered runner error instead of a silent missing-completion failure [#236](https://github.com/banteg/takopi/pull/236)

## v0.22.4 (2026-05-15)

### fixes

- show resume lines on queued Telegram continuation messages [#234](https://github.com/banteg/takopi/pull/234)

## v0.22.3 (2026-03-02)

### changes

- allow coercible `chat_id` values in config [#186](https://github.com/banteg/takopi/pull/186)

### fixes

- make `[transports.telegram]` optional for external transports and validate it only when telegram is used [#177](https://github.com/banteg/takopi/pull/177)
- deny root-level files with default `deny_globs` [#216](https://github.com/banteg/takopi/pull/216)

## v0.22.2 (2026-02-24)

### fixes

- prevent Telegram `400 Bad Request` failures on local/relative markdown links by dropping invalid `text_link` entities [#214](https://github.com/banteg/takopi/pull/214)

## v0.22.1 (2026-02-10)

### fixes

- preserve ordered list numbering when nested list indentation is malformed in telegram render output [#202](https://github.com/banteg/takopi/pull/202)

## v0.22.0 (2026-02-10)

### changes

- support Codex `phase` values and unknown action kinds in commentary rendering [#201](https://github.com/banteg/takopi/pull/201)

## v0.21.5 (2026-02-08)

### fixes

- dedupe redelivered telegram updates to prevent duplicate runs in DMs [#198](https://github.com/banteg/takopi/pull/198)

### changes

- read package version from metadata instead of a hardcoded `__version__` constant

### docs

- rotate telegram invite link

## v0.21.4 (2026-01-22)

### changes

- add allowed user gate to telegram [#179](https://github.com/banteg/takopi/pull/179)

## v0.21.3 (2026-01-21)

### fixes

- ignore implicit topic root replies in telegram [#175](https://github.com/banteg/takopi/pull/175)

## v0.21.2 (2026-01-20)

### fixes

- clear chat sessions on cwd change [#172](https://github.com/banteg/takopi/pull/172)

### docs

- add takopi-slack plugin to reference [#168](https://github.com/banteg/takopi/pull/168)

## v0.21.1 (2026-01-18)

### fixes

- separate telegram voice transcription client [#166](https://github.com/banteg/takopi/pull/166)
- disable telegram link previews by default [#160](https://github.com/banteg/takopi/pull/160)

### docs

- align engine terminology in telegram and docs [#162](https://github.com/banteg/takopi/pull/162)
- add takopi-discord plugin to plugins reference [#164](https://github.com/banteg/takopi/pull/164)

## v0.21.0 (2026-01-16)

### changes

- add `takopi config` subcommand [#153](https://github.com/banteg/takopi/pull/153)
- make telegram /ctx work everywhere [#159](https://github.com/banteg/takopi/pull/159)
- improve telegram command planning and testability [#158](https://github.com/banteg/takopi/pull/158)
- simplify telegram loop and jsonl runner [#155](https://github.com/banteg/takopi/pull/155)
- refactor telegram schemas and parsing with msgspec [#156](https://github.com/banteg/takopi/pull/156)

### tests

- improve coverage and raise threshold to 80% [#154](https://github.com/banteg/takopi/pull/154)
- stabilize mutmut runs and extend telegram coverage [#157](https://github.com/banteg/takopi/pull/157)

### docs

- add opengraph meta fallbacks [#150](https://github.com/banteg/takopi/pull/150)

## v0.20.0 (2026-01-15)

### changes

- add telegram mentions-only trigger mode [#142](https://github.com/banteg/takopi/pull/142)
- add telegram /model and /reasoning overrides [#147](https://github.com/banteg/takopi/pull/147)
- coalesce forwarded telegram messages [#146](https://github.com/banteg/takopi/pull/146)
- export plugin utilities for transport development [#137](https://github.com/banteg/takopi/pull/137)

### fixes

- handle forwarded uploads for telegram [#149](https://github.com/banteg/takopi/pull/149)
- preserve directives for voice transcripts [#141](https://github.com/banteg/takopi/pull/141)
- resolve claude.cmd via shutil.which on windows [#124](https://github.com/banteg/takopi/pull/124)

### docs

- add takopi-scripts plugin to plugins list [#140](https://github.com/banteg/takopi/pull/140)

## v0.19.0 (2026-01-15)

### changes

- overhaul onboarding with persona-based setup flows [#132](https://github.com/banteg/takopi/pull/132)
- add queued cancel placeholder for Telegram runs [#136](https://github.com/banteg/takopi/pull/136)
- prefix Telegram voice transcriptions for agent awareness [#135](https://github.com/banteg/takopi/pull/135)

### docs

- refresh onboarding docs with new widgets and hero flow [#138](https://github.com/banteg/takopi/pull/138)
- fix docs site mobile layout and font consistency [#139](https://github.com/banteg/takopi/pull/139)
- link to takopi.dev docs site

## v0.18.0 (2026-01-13)

### changes

- add per-chat and per-topic default agent via `/agent set` command [#109](https://github.com/banteg/takopi/pull/109)
- add session resume shorthand for pi runner [#113](https://github.com/banteg/takopi/pull/113)
- expose `sender_id` and `raw` fields on `MessageRef` for plugins [#112](https://github.com/banteg/takopi/pull/112)

### fixes

- recreate stale topic bindings when topic is deleted and recreated [#127](https://github.com/banteg/takopi/pull/127)
- use stdout session header for pi runner [#126](https://github.com/banteg/takopi/pull/126)

### docs

- restructure docs into diataxis format and switch to zensical [#121](https://github.com/banteg/takopi/pull/121) [#125](https://github.com/banteg/takopi/pull/125)

## v0.17.1 (2026-01-12)

### fixes

- fix telegram /new command crash [#106](https://github.com/banteg/takopi/pull/106)
- track telegram sessions for plugin runs [#107](https://github.com/banteg/takopi/pull/107)
- align telegram prompt upload resume flow [#105](https://github.com/banteg/takopi/pull/105)

## v0.17.0 (2026-01-12)

### changes

- add chat session mode (`session_mode = "chat"`) for auto-resume per chat without replying, reset with `/new` [#102](https://github.com/banteg/takopi/pull/102)
- add `message_overflow = "split"` to send long responses as multiple messages instead of trimming [#101](https://github.com/banteg/takopi/pull/101)
- add `show_resume_line` option to hide resume lines when auto-resume is available [#100](https://github.com/banteg/takopi/pull/100)
- add `auto_put_mode = "prompt"` to start a run with the caption after uploading a file [#97](https://github.com/banteg/takopi/pull/97)
- expose `thread_id` to plugins via run context [#99](https://github.com/banteg/takopi/pull/99)
- use tomli-w for config serialization [#103](https://github.com/banteg/takopi/pull/103)
- add `voice_transcription_model` setting for local whisper servers [#98](https://github.com/banteg/takopi/pull/98)

### docs

- document chat sessions, message overflow, and voice transcription model settings

## v0.16.0 (2026-01-12)

### fixes

- harden telegram file transfer handling [#84](https://github.com/banteg/takopi/pull/84)

### changes

- simplify runtime, config, and telegram internals [#85](https://github.com/banteg/takopi/pull/85)
- refactor telegram boundary types [#90](https://github.com/banteg/takopi/pull/90)

### docs

- add tips section to user guide
- rework readme

## v0.15.0 (2026-01-11)

### changes

- add telegram file transfer support [#83](https://github.com/banteg/takopi/pull/83)

### docs

- document telegram file transfers [#83](https://github.com/banteg/takopi/pull/83)

## v0.14.1 (2026-01-10)

### changes

- add topic scope and thread-aware replies for telegram topics [#81](https://github.com/banteg/takopi/pull/81)

### docs

- update telegram topics docs and user guide for topic scoping [#81](https://github.com/banteg/takopi/pull/81)

## v0.14.0 (2026-01-10)

### changes

- add telegram forum topics support with `/topic` command for binding threads to projects/branches, persistent resume tokens per topic, and `/ctx` for inspecting or updating bindings [#80](https://github.com/banteg/takopi/pull/80)
- add inline cancel button to progress messages [#79](https://github.com/banteg/takopi/pull/79)
- add config hot-reload via watchfiles [#78](https://github.com/banteg/takopi/pull/78)

### docs

- add user guide and telegram topics documentation [#80](https://github.com/banteg/takopi/pull/80)

## v0.13.0 (2026-01-09)

### changes

- add per-project chat routing [#76](https://github.com/banteg/takopi/pull/76)

### fixes

- hardcode codex exec flags [#75](https://github.com/banteg/takopi/pull/75)
- reuse project root for current branch when resolving worktrees [#77](https://github.com/banteg/takopi/pull/77)

### docs

- normalize casing in the readme and changelog

## v0.12.0 (2026-01-09)

### changes

- add optional telegram voice note transcription (routes transcript like typed text) [#74](https://github.com/banteg/takopi/pull/74)

### fixes

- fix plugin allowlist matching and windows session paths [#72](https://github.com/banteg/takopi/pull/72)

### docs

- document telegram voice transcription settings [#74](https://github.com/banteg/takopi/pull/74)

## v0.11.0 (2026-01-08)

### changes

- add entrypoint-based plugins for engines/transports plus a `takopi plugins` command and public API docs [#71](https://github.com/banteg/takopi/pull/71)

### fixes

- create pi sessions under the run base dir [#68](https://github.com/banteg/takopi/pull/68)
- skip git repo checks for codex runs [#66](https://github.com/banteg/takopi/pull/66)

## v0.10.0 (2026-01-08)

### changes

- add transport registry with `--transport` overrides and a `takopi transports` command [#69](https://github.com/banteg/takopi/pull/69)
- migrate config loading to pydantic-settings and move telegram credentials under `[transports.telegram]` [#65](https://github.com/banteg/takopi/pull/65)
- include project aliases in the telegram slash-command menu with validation and limits [#67](https://github.com/banteg/takopi/pull/67)

### fixes

- validate worktree roots instead of treating nested paths as worktrees [#63](https://github.com/banteg/takopi/pull/63)
- harden onboarding with clearer config errors, safe backups, and refreshed command menu wording [#70](https://github.com/banteg/takopi/pull/70)

### docs

- add architecture and lifecycle diagrams
- call out the default worktrees directory [#64](https://github.com/banteg/takopi/pull/64)
- document the transport registry and onboarding changes [#69](https://github.com/banteg/takopi/pull/69)

## v0.9.0 (2026-01-07)

### projects and worktrees

- register repos with `takopi init <alias>` and target them via `/project` directives
- route runs to git worktrees with `@branch` — takopi resolves or creates worktrees automatically
- replies preserve context via `ctx: project @branch` footers, no need to repeat directives
- set `default_project` to skip the `/project` prefix entirely
- per-project `default_engine` and `worktree_base` configuration

### changes

- transport/presenter protocols plus transport-agnostic `exec_bridge`
- move telegram polling + wiring into `takopi.telegram` with transport/presenter adapters
- list configured projects in the startup banner

### fixes

- render `ctx:` footer lines consistently (backticked + hard breaks) and include them in final messages

### breaking

- remove `takopi.bridge`; use `takopi.runner_bridge` and `takopi.telegram` instead

### docs

- add a projects/worktrees guide and document `takopi init` behavior in the readme

## v0.8.0 (2026-01-05)

### changes

- queue telegram requests with rate limits and retry-after backoff [#54](https://github.com/banteg/takopi/pull/54)

### docs

- improve documentation coverage [#52](https://github.com/banteg/takopi/pull/52)
- align runner guide with factory pattern
- add missing pr links in the changelog

## v0.7.0 (2026-01-04)

### changes

- migrate logging to structlog with structured pipelines and redaction [#46](https://github.com/banteg/takopi/pull/46)
- add msgspec schemas for jsonl decoding across runners [#37](https://github.com/banteg/takopi/pull/37)

## v0.6.0 (2026-01-03)

### changes

- interactive onboarding: run `takopi` to set up bot token, chat id, and default engine via guided prompts [#39](https://github.com/banteg/takopi/pull/39)
- lockfile to prevent multiple takopi instances from racing the same bot token [#30](https://github.com/banteg/takopi/pull/30)
- re-run onboarding anytime with `takopi --onboard`

## v0.5.3 (2026-01-02)

### changes

- default claude allowed tools to `["Bash", "Read", "Edit", "Write"]` when not configured [#29](https://github.com/banteg/takopi/pull/29)

## v0.5.2 (2026-01-02)

### changes

- show not installed agents in the startup banner (while hiding them from slash commands)

### fixes

- treat codex reconnect notices as non-fatal progress updates instead of errors [#27](https://github.com/banteg/takopi/pull/27)
- avoid crashes when codex tool/file-change events omit error fields [#27](https://github.com/banteg/takopi/pull/27)

## v0.5.1 (2026-01-02)

### changes

- relax telegram ACL to check chat id only, enabling use in group chats and channels [#26](https://github.com/banteg/takopi/pull/26)
- improve onboarding documentation and add tests [#25](https://github.com/banteg/takopi/pull/25)

## v0.5.0 (2026-01-02)

### changes

- add an opencode runner via the `opencode` cli with json event parsing and resume support [#22](https://github.com/banteg/takopi/pull/22)
- add a pi agent runner via the `pi` cli with jsonl streaming and resume support [#24](https://github.com/banteg/takopi/pull/24)
- document the opencode and pi runners, event mappings, and stream capture tips

### fixes

- fix path relativization so progress output does not strip sibling directories [#23](https://github.com/banteg/takopi/pull/23)
- reduce noisy debug logging from markdown_it/httpcore

## v0.4.0 (2026-01-02)

### changes

- add auto-router runner selection with configurable default engine [#15](https://github.com/banteg/takopi/pull/15)
- make auto-router the default entrypoint; subcommands or `/{engine}` prefixes override for new threads
- add `/cancel` + `/{engine}` command menu sync on startup
- show engine name in progress and final message headers
- omit progress/action log lines from final output for cleaner answers [#21](https://github.com/banteg/takopi/pull/21)

### fixes

- improve codex exec error rendering with stderr extraction [#18](https://github.com/banteg/takopi/pull/18)
- preserve markdown formatting and resume footer when trimming long responses [#20](https://github.com/banteg/takopi/pull/20)

## v0.3.0 (2026-01-01)

### changes

- add a claude code runner via the `claude` cli with stream-json parsing and resume support [#9](https://github.com/banteg/takopi/pull/9)
- auto-discover engine backends and generate cli subcommands from the registry [#12](https://github.com/banteg/takopi/pull/12)
- add `BaseRunner` session locking plus a `JsonlSubprocessRunner` helper for jsonl subprocess engines
- add jsonl stream parsing and subprocess helpers for runners
- lazily allocate per-session locks and streamline backend setup/install metadata
- improve startup message formatting and markdown rendering
- add a debug onboarding helper for setup troubleshooting

### breaking

- runner implementations must define explicit resume parsing/formatting (no implicit standard resume pattern)

### fixes

- stop leaking a hidden `engine-id` cli option on engine subcommands

### docs

- add a runner guide plus claude code docs (runner, events, stream-json cheatsheet)
- clarify the claude runner file layout and add guidance for jsonl-based runners
- document "minimal" runner mode: started+completed only, completed-only actions allowed

## v0.2.0 (2025-12-31)

### changes

- introduce runner protocol for multi-engine support [#7](https://github.com/banteg/takopi/pull/7)
  - normalized event model (`started`, `action`, `completed`)
  - actions with stable ids, lifecycle phases, and structured details
  - engine-agnostic bridge and renderer
- add `/cancel` command with progress message targeting [#4](https://github.com/banteg/takopi/pull/4)
- migrate async runtime from asyncio to anyio [#6](https://github.com/banteg/takopi/pull/6)
- stream runner events via async iterators (natural backpressure)
- per-thread job queues with serialization for same-thread runs
- render resume as `codex resume <token>` command lines
- various rendering improvements including file edits

### breaking

- require python 3.14+
- remove `--profile` flag; configure via `[codex].profile` only

### fixes

- serialize new sessions once resume token is known
- preserve resume tokens in error renders [#3](https://github.com/banteg/takopi/pull/3)
- preserve file-change paths in action events [#2](https://github.com/banteg/takopi/pull/2)
- terminate codex process groups on cancel (posix)
- correct resume command matching in bridge

## v0.1.0 (2025-12-29)

### features

- telegram bot bridge for openai codex cli via `codex exec`
- stateless session resume via `` `codex resume <token>` `` lines
- real-time progress updates with ~2s throttling
- full markdown rendering with telegram entities (markdown-it-py + sulguk)
- per-session serialization to prevent race conditions
- interactive onboarding guide for first-time setup
- codex profile configuration
- automatic telegram token redaction in logs
- cli options: `--debug`, `--final-notify`, `--version`
