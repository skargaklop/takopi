# Takopi Roadmap

## Task 1: Robust `/compact` Command Dispatch (DONE)

Completed 2026-08-04/05: dispatch robustness (`4669620`), production fixes + lifecycle feedback (`bca5e46`), handoff-as-new-session (`26ee9cb`), cross-engine extension (`9e20fd5`). Req 5 landed as the approve -> summarize -> NEW session flow (plan `docs/plans/2026-08-04-compact-handoff-new-session.md`), superseding the in-place same-session wording.

### Problem

The `/compact` slash command does not yet work in all message contexts:

- Replying to a message from an existing session does not reliably route `/compact` to that session's engine.
- The relative order of `/compact` and other slash commands (e.g., `/codex`, `/claude`, `/opencode`) in a single message is not consistently resolved.
- Live report (2026-08-04): replying `/compact` (bare or with instructions) to an `omp` session yields no visible result. Verified compounding causes: (a) the ACP compact path is a test-only stub - no production ACP transport exists (`AcpClient._resolve_transport` raises `Subprocess ACP transport not yet implemented`; `omp`/`grok` never override `create_acp_client`); (b) `AcpCompactMixin.compact()` converts every failure into a `CompletedEvent(ok=False)` that `run_compact_job` discards (`async for ... : pass`), so failures and successes are both invisible; (c) `/compact <instructions>` was delivered to the agent as a plain-text prompt via the prompt batcher (fixed in `4669620`, pending deploy verification).

### Requirements

1. `/compact` must work when sent as a reply to any message belonging to an existing session — it should compact that session's resume token, regardless of which engine created it.
2. `/compact` must work in any position relative to other slash commands in the same message. Example: both `/codex /compact` and `/compact /codex` should resolve correctly.
3. If the target engine does not support compaction (`compact_support() == CompactSupport.none`), Takopi must:
   - Notify the user that this agent does not support native compaction.
   - Ask the user whether to send the prompt as a plain text compaction request to the agent anyway (i.e., pass the raw compaction prompt through the normal `run()` path, letting the agent handle it as a regular prompt).
   - Only proceed after explicit user confirmation.
4. No silent compact jobs: every `/compact` invocation must produce user-visible lifecycle feedback - an acknowledgement on acceptance, a completion notice (honest per mode: real compaction vs handoff summary), and a failure reply when `compact()` raises OR yields a non-ok `CompletedEvent`. Discarding runner events in `run_compact_job` is forbidden.
5. `omp` and `grok` are `handoff_only`. `/compact` on any engine without true compaction (handoff_only or none) shows an approval card (two buttons); on approve, Takopi produces a handoff summary in the OLD session, seeds a NEW session with it, and reroutes future messages to the new session id (actual context reduction, honestly labeled). The summary is echoed to the user (truncated). A `/handoff` command (Task 7) will offer the same migration on true-compaction engines.
6. Deployment verification is part of done: after any rebuild, verify the installed artifact (grep the uv-tools `site-packages` for the new symbols, check file dates) and verify exactly one takopi instance is running. Live evidence 2026-08-04: the bridge kept executing a 2026-08-02 build while believed rebuilt.

### Scope

- `src/takopi/telegram/loop.py` — command dispatch and reply-context resolution
- `src/takopi/scheduler.py` — `ThreadJob.kind` field and compact job routing (partially done in prior session)
- `src/takopi/runners/` — `compact_support()` return values per runner
- `src/takopi/runners/_acp.py`, `omp.py`, `grok.py` - reclassify compact support to `handoff_only` until Task 6 lands
- `docs/plans/2026-08-04-compact-production-failure-gap-closure.md` - gap-closure plan
- `tests/test_telegram_compact_dispatch.py` - loop-level coverage incl. lifecycle feedback

---

## Task 2: Pi Plan and Goal Mode Support

### Problem

Pi runner does not support `plan` and `goal` modes, even though the required pi extensions are installed globally on this machine.

### Requirements

1. The pi runner build script (`build_runner()` in `src/takopi/runners/pi.py`) must detect whether the pi plan-mode extension (`@narumitw/pi-plan-mode`) is installed globally.
2. Detection method: check `~/.pi/agent/npm/node_modules/` (or the pi extension directory) for the plan-mode extension package.
3. If the extension is installed:
   - `plan` mode must append `--plan` to the pi CLI args (delegating to the extension).
   - `goal` mode must inject the autonomous-goal prompt prefix (same pattern as other runners).
4. If the extension is NOT installed, `plan`/`goal` modes should fall back gracefully (soft-plan prompt prefix or a user-facing message).

### Investigation Steps

1. **Subagent documentation gathering:** Dispatch a read-only subagent to study the pi plan-mode extension source at `~/.pi/agent/npm/node_modules/@narumitw/pi-plan-mode/src/plan-mode.ts` and any other relevant pi documentation.
2. **Save documentation locally:** Store key findings (CLI flags, behavior, config requirements) in `docs/reference/runners/pi/` for future reference.
3. **Study takopi code:** Review existing plan/goal mode patterns in `src/takopi/runners/modes.py` and how other runners (codex, opencode, claude) implement them.
4. **Create implementation plan:** Write a `.md` plan document.
5. **Execute:** Implement via subagent.

### Plan

- `docs/plans/2026-08-05-pi-plan-mode-detection.md` - approved spec (extension detection + graceful fallback; `--plan` append and goal prefix already landed).

### Scope

- `src/takopi/runners/pi.py` — `build_args()`, extension detection
- `src/takopi/runners/modes.py` — shared mode logic
- `docs/reference/runners/pi/` — saved documentation

---

## Task 3: Subagent and Skill Selection Support

### Problem

Takopi cannot currently direct an agent to use a specific subagent or skill for a given task. Users have no way to specify "use the code-reviewer subagent" or "apply the TDD skill" when sending a prompt.

### Requirements

1. Study the documentation for each supported agent (codex, claude, opencode, pi, grok, agy) to determine:
   - Whether the agent CLI supports specifying a subagent/profile/role for a given invocation.
   - Whether the agent CLI supports activating or referencing a specific skill.
   - What CLI flags or config keys control these selections.
2. Save all relevant documentation locally under `docs/reference/runners/<engine>/`.
3. Where supported, add Takopi config and/or slash-command syntax to specify a subagent and/or skill per prompt.

### Potential Interfaces

- Per-engine config keys: `[codex] subagent = "..."`, `[claude] skill = "..."`.
- Slash-command syntax: `/codex --subagent reviewer fix the bug` or `/claude --skill tdd write tests for X`.
- Decision (user, 2026-08-05): skills are dynamic per user - skill selection uses free-form inline (`--skill <name>`) or slash (`/skill <name>`) forms only; no per-skill command registration, no static enumeration or validation in takopi; the harness resolves names against the user's own skill lis list. Amendment: the generic slash forms `/skill <name>` and `/subagent <name>` are equally supported (free-form args, NOT per-skill registered commands); bare `/skill <name>` sets the sticky session selection (`off` clears).

### Plan

- `docs/plans/2026-08-05-subagent-skill-selection.md` - approved spec (A0 docs via cheap-model read-only subagents; pilot engine first).
- Per-session sticky selection: remember the chosen subagent/skill for the session until changed.

### Investigation Steps

1. **Subagent documentation gathering:** Dispatch read-only subagents to study each agent's CLI documentation (codex `--help`, claude docs, opencode docs, pi extensions, etc.).
2. **Save documentation locally:** Store findings per engine in `docs/reference/runners/<engine>/`.
3. **Study takopi code:** Review `build_args()` for each runner to understand where subagent/skill flags would be injected.
4. **Create implementation plan:** Write a `.md` plan document.
5. **Execute:** Implement per-engine via subagents.

### Scope

- `src/takopi/runners/*.py` — `build_args()` per engine
- `src/takopi/settings.py` — new per-engine config keys if needed
- `docs/reference/runners/` — saved documentation

---

## Task 4: New Agent Support — Droid, Cline, Kilo

### Overview

Add support for three additional agent harnesses as separate Takopi runners.

### General Approach (applies to all three)

For each new agent, follow this workflow:

1. **Documentation gathering (subagent):** Dispatch a read-only subagent to study the agent's CLI documentation, flag set, output format, session/resume mechanism, and any MCP or tool-calling support.
2. **Save documentation locally:** Store findings in `docs/reference/runners/<engine>/`.
3. **Study takopi code:** Review existing runner implementations (`JsonlSubprocessRunner`, `BaseRunner`) and the `EngineBackend` registration pattern to understand the integration contract.
4. **Create implementation plan:** Write a `.md` plan document covering the runner class, `build_args()`, `build_runner()`, resume token format, stream parsing, and config keys.
5. **Execute plan (subagent):** Dispatch a code-editing subagent to implement the runner following the approved plan.

### 4a. Droid

- CLI tool: `droid` (Factory AI)
- Investigate: output format (JSON streaming?), session/resume mechanism, plan-mode support, subagent support.
- Config table: `[droid]` with model, extra_args, etc.

### 4b. Cline

- CLI tool: `cline` (VS Code extension, headless mode)
- Investigate: headless invocation method, output format, session persistence, tool approval flags.
- Config table: `[cline]` with model, allowed_tools, etc.

### 4c. Kilo

- CLI tool: `kilo` (or `kilo-code`)
- Investigate: CLI interface, output format, session/resume, MCP support.
- Config table: `[kilo]` with model, extra_args, etc.

### Scope per agent

- `src/takopi/runners/<engine>.py` — new runner module
- `src/takopi/engines.py` — register new engine ID
- `src/takopi/settings.py` — engine config documentation
- `docs/reference/runners/<engine>/` — saved documentation
- `docs/reference/config.md` — config table documentation
- `tests/test_<engine>_runner.py` — runner tests

---

## Task 5: Clean Shutdown Without Asyncio Pipe-Transport Noise (Windows) (DONE)

Resolved by earlier shutdown/cleanup work (`c4e1817`, `fc3f7eb`, `42ccb1a`). User-verified 2026-08-05: Ctrl+C produces no noise. Engineering artifacts completed per `docs/plans/2026-08-05-shutdown-transport-close.md`: req 2 (explicit `close_process_streams()` at every spawn site — `manage_subprocess` + codex app-server `stop()`), req 3 (`shutdown_timeout_s` config key, bounded per-stream timeout), req 4 (child-interpreter regression test). Investigation findings: `docs/reference/shutdown/pipe-transport-cleanup.md`. Only the mid-run e2e proof (Ctrl+C with a live agent subprocess) remains user-side.

### Plan

- `docs/plans/2026-08-05-shutdown-transport-close.md` - finish reqs 2-4 (transport-close helper, bounded timeout, noise regression test) + mid-run e2e.

### Problem

On Ctrl+C, after `shutdown.interrupted [takopi.cli.run]`, the interpreter emits repeated deallocator tracebacks (live log 2026-08-04, CPython 3.14, Windows ProactorEventLoop):

```text
Exception ignored while calling deallocator <function _ProactorBasePipeTransport.__del__ ...>
...
ValueError: I/O operation on closed pipe
Exception ignored while calling deallocator <function BaseSubprocessTransport.__del__ ...>
```

Root-cause hypothesis: runner subprocesses are killed (`taskkill /T /F` in `manage_subprocess`) and reaped via `proc.wait()`, but the asyncio pipe transports (stdin/stdout/stderr) are never explicitly closed. At interpreter teardown the transports are garbage-collected unclosed; `__del__` issues a `ResourceWarning` whose `__repr__` touches `fileno()` on an already-closed pipe, producing the `ValueError` noise. Prior related work: `c4e1817` (graceful shutdown), `42ccb1a` (process-tree cleanup), `plan-process-tree-cleanup.md`; this task is the remaining transport-close gap.

### Requirements

1. On SIGINT/SIGTERM, normal exit, and `/cancel`, every runner subprocess transport is explicitly closed and awaited before the event loop stops: zero `Exception ignored` deallocator tracebacks and zero `unclosed transport` ResourceWarnings on Windows + CPython 3.14.
2. Cover every spawn site: `manage_subprocess()` (`src/takopi/utils/subprocess.py`), the codex app-server client, ACP runners, and any direct `anyio.open_process()` callers.
3. Shutdown stays bounded: transport closing must not hang on wedged pipes (timeout configurable via settings - no hardcoded values).
4. Regression coverage: an integration test that starts a run with a live subprocess, interrupts with SIGINT, and asserts stderr contains no `Exception ignored` / `unclosed transport` (Windows-marked); unit tests for the close helper.
5. Preserve the constraints recorded in `EXPERIENCE.md`: no stored `CancelScope` objects in `PromptInputBatcher`; no outer `CancelScope` around `run_main_loop`.

### Investigation Steps

1. Read-only subagent: trace every subprocess lifecycle - spawn sites, transport ownership, shutdown ordering in `src/takopi/cli/run.py` (~line 329) through `anyio.run` teardown; confirm whether `Process.aclose()` or stdio stream `aclose()` is ever called on each path. Do NOT modify any files.
2. Verify CPython 3.14 proactor behavior vs 3.13 and the anyio version in `uv.lock` (does `Process.wait()` close transports?).
3. Save findings in `docs/reference/shutdown/pipe-transport-cleanup.md`.
4. Write an implementation plan (`.md` in `docs/plans/`).
5. Execute via subagent (TDD); verify by reproducing the Ctrl+C scenario end-to-end on Windows.

### Scope

- `src/takopi/utils/subprocess.py` - transport close in `manage_subprocess()` / new helper
- `src/takopi/runner.py`, `src/takopi/runner_bridge.py`, `src/takopi/runners/_acp.py`, codex app-server client - per-spawn-site cleanup
- `src/takopi/cli/run.py` - shutdown ordering
- `src/takopi/settings.py` - shutdown timeout config key
- `tests/test_shutdown.py` - regression coverage
- `docs/reference/shutdown/` - saved findings
---

## Task 6: Real Compaction for ACP Runners (grok, omp)

### Problem

The `acp` compact mode introduced in `f23baba` is a test-only stub: the only transport in the tree is `FakeAcpTransport`, production runners never override `create_acp_client`, and `AcpClient._resolve_transport` raises `Subprocess ACP transport not yet implemented`. Tests pass because they inject the fake transport. Production evidence (2026-08-04, omp session) also shows `/compact` delivered via `session/prompt` reaches the model as a plain user turn, so harness-side interception is unproven even once a transport exists.

### Requirements

1. Research each harness (grok, omp): ACP `available_commands` advertisement, whether slash commands sent via `session/prompt` are intercepted server-side, and the stdio JSON-RPC transport contract. Save findings under `docs/reference/runners/<engine>/`.
2. Implement a production subprocess ACP transport (stdin/stdout JSON-RPC) with the same message ordering the tests assume via `FakeAcpTransport`.
3. Only restore `mode="acp"` / `true_compaction=True` per engine when real compaction is verified end-to-end against the live harness; otherwise keep `handoff_only`.
4. Add an integration smoke test that runs the real CLI (marked, skippable in CI) proving `/compact` is not delivered to the model as plain text.

### Investigation Steps

1. Read-only subagent: study harness docs/source for ACP transport + `available_commands` semantics; save to `docs/reference/runners/`.
2. Write an implementation plan (`.md` in `docs/plans/`).
3. Execute via subagent with TDD.

### Scope

- `src/takopi/runners/_acp.py` - real transport + client hardening
- `src/takopi/runners/omp.py`, `grok.py` - `create_acp_client` overrides, support re-declaration
- `tests/test_acp_client.py`, `tests/test_acp_compact_runners.py`
- `docs/reference/runners/omp/`, `docs/reference/runners/grok/`
---

## Task 7: `/handoff` Command for All Engines (DONE)

### Problem

The handoff-as-new-session flow (Task 1, plan `docs/plans/2026-08-04-compact-handoff-new-session.md`, decisions D1/D2 approved) is only reachable via `/compact` on engines WITHOUT native compaction. Users have no way to trigger the same summary + new-session migration on engines that DO compact natively - e.g. when they want a clean session break with a fresh context instead of in-place compaction.

### Requirements

1. New built-in `/handoff` slash command available for EVERY engine (codex, claude, opencode, pi, omp, grok, agy, and plugin runners incl. `CompactSupport.none`).
2. `/handoff` executes the identical flow as `/compact` on no-compaction engines:
   - explicit user approval via two inline buttons before anything runs;
   - handoff summary produced in the old session (instructions supported: `/handoff keep the test plan`);
   - NEW session seeded with the FULL summary (new session id);
   - routing flips to the new session; truncated summary echo to the user.
3. Reply-context and ordering parity with `/compact`: works as a reply to any session message and in any position relative to engine selectors (`/handoff /codex` and `/codex /handoff` both resolve).
4. No resolved session -> guidance reply (same as `/compact`).
5. DRY: one shared migration executor used by both commands. The only differences are the entry command and that `/handoff` ignores `compact_support()` entirely (applies even to true-compaction engines).
6. Command contract clarity (document in `commands-and-directives.md`):
   - `/compact` = reduce context: native in-place compaction when supported, handoff-migration (with approval) otherwise.
   - `/handoff` = always: approval -> summary -> new session, for every engine.

### Dependencies

- Task 1 handoff-as-new-session implementation (approved plan above) must land first; this task adds the `/handoff` entry point on top of the shared executor.

### Plan

- `docs/plans/2026-08-04-handoff-command.md` - approved delta spec (entry points only; executor inherited from the Task 1 handoff plan).

### Investigation Steps

1. No new research expected; reuse the verified mechanics from the Task 1 handoff plan.
2. Write an implementation plan (`.md` in `docs/plans/`) covering the `/handoff` entry point and shared-executor refactor.
3. Execute via subagent with TDD.

### Scope

- `src/takopi/telegram/commands/parse.py` - recognize `handoff` as a leading command token (with selector ordering parity)
- `src/takopi/telegram/commands/compact.py` (or a new shared `handoff.py`) - entry point + shared migration executor
- `src/takopi/telegram/commands/meta_args.py`, `menu.py` - register pure-meta command + bot menu entry
- `src/takopi/telegram/prompt_batch.py` - add `handoff` to `CONTROL_COMMANDS`
- `tests/test_telegram_handoff_command.py` (or extend the compact dispatch tests)
- `docs/how-to/compact-session.md`, `docs/reference/commands-and-directives.md`, `changelog.md`
---

## Task 8: Cross-Engine Handoff (Destination Engine Selection) (DONE)

### Problem

The handoff-as-new-session flow always creates the new session on the SAME engine (omp -> omp). Users cannot migrate a session across harnesses - e.g. summarize an omp session and continue it as a NEW grok session. User request 2026-08-04: "I want to make handoff from omp to grok."

### Requirements

1. Optional destination clause on both commands: `/handoff [/source] [to <dest>] [instructions]` and `/compact [/source] [to <dest>] [instructions]`.
2. `to` is consumed only when followed by a KNOWN engine id (leading `/` tolerated); otherwise it stays instructions (`/handoff to do list` = instructions).
3. Destination validation happens BEFORE the approval card: unknown/unavailable engine -> error reply, no card, no wasted agent turn.
4. Approval card names both engines when destination differs ("handoff from omp to a NEW grok session? ...").
5. Phase 2 seeds with `engine_override = destination or source`; store flip and footers then reference the destination engine.
6. `/compact to <other-engine>` forces the handoff-migration path (with approval) even on compaction-capable engines; same-engine or absent destination keeps native behavior.
7. No `to` clause -> destination = source engine (backward compatible with the Task 1 plan).
8. Works with ALL harnesses: every configured engine is valid as BOTH source and destination (incl. plugin runners and `CompactSupport.none` engines); engine lists are derived from the router at runtime - no hardcoded engine names.

### Dependencies

- Task 1 handoff-new-session implementation (executor + approval infra).
- Task 7 recommended first (shares `parse.py` / `compact.py`; this spec rebases on the generalized `parse_command_invocation`).

### Plan

- `docs/plans/2026-08-04-cross-engine-handoff.md` - approved delta spec.

### Scope

- `src/takopi/telegram/commands/parse.py` - `to <engine>` clause, `destination_engine` field
- `src/takopi/scheduler.py` - `ThreadJob.handoff_target`
- `src/takopi/telegram/commands/compact.py` - pending field, validation, approval text, forced-handoff routing
- `src/takopi/telegram/loop.py` - phase 2 `engine_override`, completion wording
- `tests/test_telegram_compact_dispatch.py`, parser test matrix
- `docs/reference/commands-and-directives.md`, `docs/how-to/compact-session.md`, `changelog.md`
---

## Task 9: Grok Stream Coalescing (Per-Word Steps Bug) (DONE)

### Problem

Live report 2026-08-05: grok progress renders each WORD as a separate step and on its own line - "working - grok - 5m 35s - step 3517", progress lines like "v to", "v understand", "v spawn". Root cause (code-verified): `translate_grok_event` (`src/takopi/runners/grok.py:99-111`) maps EVERY `StreamThoughtEvent` to a completed `note` action; the grok CLI emits thought JSONL events at word/token granularity, so `action_count` (the `step N` header) explodes and every word prints on its own action line. Existing tests use idealized one-thought-per-event fixtures.

### Requirements

1. Consecutive thought deltas coalesce into ONE step/action per thought block (flush on non-thought event or stream end); step count reflects real actions, not words.
2. No per-word lines in progress; thinking stays visible as coalesced note actions (renderer truncates as today).
3. `StreamTextEvent` accumulation and final-answer content unchanged.
4. Audit the pi runner (`note_event`, `pi.py:505`) for the same granularity pattern; fix if shared (DRY helper), document the finding either way.
5. Regression tests built from a REAL captured grok JSONL sample (word-granularity, production-shaped), not idealized fixtures.
6. Engine-local fix only: no renderer/progress changes, no new config knobs.

### Investigation Steps

1. Capture raw grok CLI JSONL (same args as `build_args()`) into `docs/reference/runners/grok/stream-sample.jsonl`; verify word-granularity at the CLI level and chunk spacing.
2. Audit pi CLI note events the same way.
3. Execute the approved plan via subagent (TDD).

### Plan

- `docs/plans/2026-08-05-grok-stream-coalescing.md` - approved spec (Option A: runner-side coalescing buffer).

### Scope

- `src/takopi/runners/grok.py` - pending-thought buffer + flush
- (conditional) `src/takopi/runners/pi.py` or a shared helper module
- `tests/test_grok_runner.py` ((conditional) `tests/test_pi_runner.py`)
- `docs/reference/runners/grok/stream-sample.jsonl` - captured sample
- `changelog.md`

### Post-implementation notes

- **Pi audit (requirement 4):** Pi's `note_event` (`pi.py:494-514`) is only used for error-path messages (`process_error_events`), NOT for streaming thoughts — pi does not map `StreamThoughtEvent` to actions the way grok does. No shared bug, no DRY helper needed. Pi is unaffected.
- **Sample capture (requirement 5):** Captured real grok CLI JSONL at `docs/reference/runners/grok/stream-sample.jsonl` (374 lines, word-granularity `thought` events). Confirmed thoughts precede text events; join strategy `"".join(chunks)` preserves embedded spaces.
---

## Task 10: Grok Final Message Contains Full Narration (DONE)

Implemented in `6ba5d99` (text segmentation, narration -> progress notes, both sample replays). User-confirmed in production 2026-08-05.

### Problem

Live report 2026-08-05: the FINAL grok message dumps the entire reasoning/narration transcript ("Let me read the plan first... Now let me check...") before the real answer; the body split into two Telegram messages. Root cause (evidence-backed): in agentic runs the grok harness emits intermediate narration as `text` stream events; `translate_grok_event` accumulates ALL text chunks into `last_assistant_text` (`grok.py:122-123`), and `render_final_parts` renders the body from the answer only (`markdown.py:236-240`). The Task 9 sample (math prompt) had no narration, hiding the bug.

### Requirements

1. The final message body contains ONLY the actual answer (trailing text run per the approved delimiter rule).
2. Narration stays visible in PROGRESS as coalesced note actions (Task 9 style); it never leaks into the final body.
3. Backward compatible: single-turn runs keep the full-text answer; all existing grok tests stay green unless intentionally re-spec'd.
4. The delimiter rule is validated on a REAL agentic capture before implementation (`docs/reference/runners/grok/stream-sample-agentic.jsonl`).
5. Engine-local only: no renderer/progress/settings changes, no new config.

### Plan

- `docs/plans/2026-08-05-grok-answer-narration-split.md` - approved spec (text segmentation; last segment = answer; narration -> progress notes).

### Scope

- `src/takopi/runners/grok.py` - text segmentation + narration-to-note coalescing
- `tests/test_grok_runner.py` - narration/answer split tests + both sample replays
- `docs/reference/runners/grok/stream-sample-agentic.jsonl` - real agentic capture
- `changelog.md`
---

## Task 11: Grok Stream Protocol Completion (DONE)

### Problem

Live evidence 2026-08-05: every grok run logs `jsonl.msgspec.invalid` warnings for `available_commands`, `usage`, `tool_call`, `tool_call_update` (`Invalid value ... at $.type`); the events are dropped, so tool calls never become actions - a 22m run showed "step 3". Mid-run usage telemetry is lost. Separately, a run ended with `grok run stopped (cancelled)` after 48s without a user cancel - cause unclassified (takopi-side, CLI-internal, or upstream API). Root cause: `schemas/grok.py` models only 4 of the ~8 emitted event types.

### Requirements

1. Schema-complete decoding: `tool_call`, `tool_call_update`, `usage`, `available_commands` decode into typed structs (field shapes from a real capture, `forbid_unknown_fields=False`).
2. Tool calls become real actions (started/completed, kind/title via the shared `tool_actions.py` helpers); progress steps reflect actual tool activity; duplicate starts for the same id are forbidden.
3. Mid-run `usage` events merge into the terminal `CompletedEvent.usage` (end-event usage wins).
4. Forward compatibility: unknown future event types are skipped at DEBUG level - no warning spam; only genuinely malformed JSON warns.
5. Cancellation: classify the `stopReason=cancelled` cause (takopi-side vs CLI-internal vs upstream API), fix if takopi-side (pinned by a test), otherwise document + honest user-facing reason.
6. No regressions to Task 9 (coalescing) and Task 10 (narration split) behaviors.

### Plan

- `docs/plans/2026-08-05-grok-stream-protocol-completion.md` - approved spec.

### Scope

- `src/takopi/schemas/grok.py` - 4 new event structs + unknown-type catch-all
- `src/takopi/runners/grok.py` - tool action mapping, usage merge, DEBUG demotion
- `tests/test_grok_schema.py`, `tests/test_grok_runner.py`
- `docs/reference/runners/grok/stream-sample-agentic.jsonl` - full-fidelity capture + cancellation analysis
- `changelog.md`
---

### Post-implementation notes

- **A0 capture:** `docs/reference/runners/grok/stream-sample-tools.jsonl` (79 lines, trimmed from a 632-line live run). Captured event shapes: `tool_call` (`toolCallId`, `toolName`, `kind`, `status`, `rawInput`), `tool_call_update` (`toolCallId`, `status`, `content`, `rawOutput`), `usage` (`usage` dict), `available_commands` (`tools`, `commands`).
- **Cancellation (requirement 5):** The capture did not reproduce a `stopReason=cancelled` end event. The existing mapping (`stop not in {"error","aborted","cancelled","canceled"}` → `ok=False`) already produces an honest user-facing message (`grok run stopped (cancelled)`). Without a reproducible capture, the cause is most likely CLI-internal (the grok harness cancelling after a timeout or upstream API error), not takopi-side. No code change needed; behavior pinned by `test_cancel_stop_reason_maps_to_error`.
- **Forward compat (requirement 4):** `decode_event` peeks the `type` field before decoding. Known types go through the tagged-union decoder; unknown types return `StreamUnknownEvent(type_name=...)` — no `ValidationError`, no WARNING. Only genuinely malformed JSON reaches `decode_error_events` and logs a WARNING.
- **Tool-kind mapping:** Grok provides its own `kind`/`title` fields on `tool_call` (e.g. `kind="list"`, `title="list_dir"`), but these don't map to takopi's `ActionKind` literal. The shared `tool_kind_and_title` helper is used instead for consistency with the claude runner. Unrecognized grok tool names (e.g. `list_dir`, `read_file`) fall through to generic `("tool", <toolName>)`.

---

## Task 12: Plan-Mode Read-Only Contradiction (Self-Cancellation) (DONE)

### Problem

Live evidence 2026-08-05: repeated `grok run stopped (cancelled)` mid-run in plan mode. The spawn log shows the contradiction in one frame: the prompt commands "PLAN MODE: you MUST produce a plan as a .md ... before finishing" while args contain `--permission-mode plan` (harness-enforced read-only). Both cancellations fired as the agent attempted to act (run verification / edit ROADMAP); the CLI exits rc=0 with `stopReason=cancelled`. Root cause: `build_send_instruction(plan_mode=True)` (`outbound_files.py:114-120`) appends a mandatory plan-file write to EVERY plan-mode prompt, but native plan-mode runners (grok `grok.py:351`, claude `claude.py:324`) forbid writes; the grok harness cancels the whole turn on forbidden operations. The instruction is also redundant: `plan_auto_file` already auto-delivers `outgoing/plan-*.md` from the answer text. Soft-plan runners (codex, omp, opencode) are unaffected. (Task 11 post-notes classified the cancel as "CLI-internal"; this task identifies the concrete trigger and removes it.)

### Requirements

1. Mode-aware plan instruction: runners declare `plan_enforcement` (`native_readonly` vs `soft`, mirroring the compact_support attribute pattern); native runners get a read-only variant - plan as final TEXT answer, no write/execute instructions, Takopi auto-delivers.
2. Native plan runs complete WITHOUT self-cancellation; the plan reaches the user via `plan_auto_file` (no harness writes).
3. Honest cancellation surfacing: plan-mode `stopReason=cancelled` maps to a read-only explanation message; non-plan cancels keep the existing text.
4. Audit claude native plan mode with the same prompt (cancel vs graceful deny); wording fix applies regardless.
5. Soft-plan path byte-identical (wording and file delivery unchanged).

### Plan

- `docs/plans/2026-08-05-plan-mode-readonly-contradiction.md` - approved spec.

### Scope

- `src/takopi/outbound_files.py` - enforcement-aware instruction variants
- `src/takopi/runners/grok.py`, `claude.py` - `plan_enforcement` attribute, cancellation mapping
- Injection call site (`runner_bridge.py` or executor)
- `tests/test_outbound_files.py`, `tests/test_grok_runner.py`, (conditional) `tests/test_claude_runner.py`
- docs + `changelog.md`


### Post-implementation notes

- **Enforcement wiring:** `GrokRunner.plan_enforcement = "native_readonly"` and `ClaudeRunner.plan_enforcement = "native_readonly"` (class attributes, default `"soft"` everywhere else). The executor reads `getattr(entry.runner, "plan_enforcement", "soft")` and passes it to `append_send_instruction(enforcement=...)`.
- **Cancellation mapping (grok only):** `GrokStreamState.plan_mode: bool` is set `True` in `build_args` when `--permission-mode plan` is used. The `StreamEndEvent` case checks `state.plan_mode and stop in {"cancelled","canceled"}` → produces the read-only explanation. Non-plan cancels keep `"grok run stopped (cancelled)"`. Claude does not self-cancel on forbidden writes (its harness denies gracefully), so no claude-side cancellation mapping was needed.
- **Claude audit (requirement 4):** Claude's harness in `--permission-mode plan` does NOT cancel the turn on forbidden writes — it denies the tool call and continues. The wording fix (read-only variant) still applies to avoid confusing the agent, but no cancellation mapping is needed for claude.
- **Auto-file delivery:** `plan_auto_file` (default-on) writes `outgoing/plan-<ts>.md` from the answer text. Native plan runners now rely on this path exclusively (no `[[takopi-send]]` marker expected).
---

---

## Task 13: Grok Tool Titles + Narration Delimiter Upgrade

### Problem

Live evidence 2026-08-05 (pi implementation run):
1. Progress shows generic identical tool lines ("v tool: run_terminal_command" x5, "v tool: todo_write") with no actual command/path - unlike other harnesses (claude shows "bash: ls"-style titles). Root cause: `tool_kind_and_title` (`tool_actions.py`) knows only claude tool names; grok names (`run_terminal_command`, `read_file`, `search_replace`, `list_dir`, `todo_write`, `spawn_subagent`) fall through to generic `(`"tool"`, name)` (`grok.py:198-201`); real args sit in `rawInput`.
2. The final message still contains narration ("Good progress - 22 passed... Let me fix both tests:") before the real summary: `_close_text_segment` (`grok.py:120-123`) closes text segments only on thought blocks, so narration produced between tool calls stays glued to the trailing answer segment.

### Requirements

1. Tool actions display like other harnesses: real command/path/pattern titles (`command: uv run pytest ...`, `read: 'file'`, `ls: '.'`) via a grok-local adapter that normalizes names/inputs and delegates to the shared `tool_kind_and_title` (no grok names leak into the shared helper).
2. Field names for every grok tool's `rawInput` recorded from real captures (`docs/reference/runners/grok/tool-fields.md`) - no guessing.
3. `tool_call`/`tool_call_update` close the current text segment (like thoughts do): narration between tool calls becomes progress notes; trailing text after the last delimiter is the answer; finals lose the concatenated narration format.
4. `tool_call_update` completion reuses the SAME kind/title as the start (existing meta cache untouched).
5. No regressions to Task 9 (coalescing), Task 10 (thought-delimited split), Task 11 (tool actions, usage, unknown types).

### Plan

- `docs/plans/2026-08-05-grok-tool-titles-and-delimiters.md` - approved spec.

### Scope

- `src/takopi/runners/grok.py` - `_grok_tool_kind_and_title` adapter + segment closing on tool events
- `tests/test_grok_runner.py`
- `docs/reference/runners/grok/tool-fields.md`, `runner.md`
- `changelog.md`

---

## Workflow Convention

All non-trivial tasks in this roadmap follow this sequence:

```
1. Subagents gather documentation  →  save locally in docs/reference/
2. Study existing takopi code       →  understand integration points
3. Write implementation plan        →  .md file in docs/plans/
4. Execute plan via subagent        →  code + tests
5. Verify: pytest + ruff + smoke    →  full suite green
```

Never skip the documentation-gathering and plan-writing phases. The user requires evidence-based implementation, not speculation.
