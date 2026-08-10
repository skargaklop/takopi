# Takopi Feature Audit and Untether Cutover Plan

## Context

Audit every usage-enhancing Takopi implementation recorded in `D:/Projects/takopi/docs/**`, `changelog.md`, `ROADMAP.md`, every post-ancestry commit subject/body, and specifically `docs/reference/untether-comparison.md` against current Untether HEAD `daca548c5ab4c5d7c0b9962a25772fe32331f625` (baseline `4285dad5a12e4e4113c9cc5240972a67bbb5e218` plus the migration commit). Port every source-verified missing behavior without regressing Untether’s larger feature surface. Only after the resulting Untether build passes deterministic gates, replace the active Takopi Telegram runtime with Untether while preserving effective settings, credentials, and compatible state.

The comparison document is mandatory evidence but describes the pre-migration baseline: its claims that Untether lacks scheduler hardening, Pi/OMP compatibility, OMP/Grok/Agy, Windows cleanup, three-OS CI, and the 81% threshold are stale after `daca548c`. Direct current-source inspection found the migration incomplete at the Telegram command/dispatch layer, runner retry/settings layer, Pi plan/stdin behavior, presentation layer, and hard typing gate.
## Approach

### 1. Finish the evidence ledger before editing behavior

Create one in-repository audit artifact under Untether’s existing documentation convention and account for every Takopi commit plus every file under `docs/`, `changelog.md`, and `ROADMAP.md`. Each deduplicated claim records: Takopi SHA/doc/source/test evidence, user/operator impact, current Untether source/test evidence, and one disposition: `present`, `ported`, `superseded`, `not-applicable`, or `unverified`. Explicitly re-evaluate every row in `D:/Projects/takopi/docs/reference/untether-comparison.md` against current HEAD rather than copying its baseline status.

Record these already source-verified ports as `present`: hardened scheduler cancellation/claim/requeue/observers; prompt batching; run-options `attachments`, `plan`, `goal`, `skill`, and `subagent`; Pi unknown-event decoding and numeric retry delay; OMP full IDs; OMP/Grok/Agy registration; compact core/mixins/ACP; Windows tree cleanup/stream closure; three-OS CI configuration; and the 81% threshold. Preserve Untether-only Gemini/Amp, triggers, costs, quarantine, hot reload/migrations, outbox delivery, stats/health/browse/auth/config commands, environment policy/audit, diagnostics, persistence, systemd notify, and security/release jobs.

Classify Takopi namespace/package/release chores and speculative ROADMAP Tasks 4 and 20 as `not-applicable`; classify the legacy `takopi-send` marker protocol as `superseded` by `.untether-outbox`. Task 23 is ported only where source behavior exists—run options, directives, and runner handling—not for undocumented native harness behavior.

### 2. Wire the migrated compact/handoff and meta-command surface end to end

Adapt Takopi’s command modules and `telegram/loop.py` handlers into Untether’s existing `CommandBackend` entry-point registry; do not create a second dispatcher. Register and wire the source-backed behavior for compact, handoff, queue, plan, goal, subagent/skill meta arguments, and trigger aliases. The current `telegram/prompt_batch.py` control names and `scheduler.ThreadJob.kind`, `compact_instructions`, and `handoff_target` are data only until the loop consumes them; eliminate dead aliases by connecting every one or removing any alias with no Takopi implementation evidence.

Reuse `src/untether/scheduler.py`’s `claim_queued`, `requeue_front`, `CancelQueuedResult`, and job observers; reuse existing authorization, callback routing, progress/outbox, cost, stats, quarantine, and persisted session stores. Compact and handoff jobs use the same per-resume FIFO as prompts. `/compact` compacts in place only for a native-capable runner; handoff-only engines and `/handoff` require confirmation, summarize the old session, seed the resolved destination, and atomically update future routing only after the seed succeeds. Cancellation or seed failure leaves the original routing unchanged and terminates exactly one progress card.

Port Takopi’s directive parser into Untether’s existing message parse seam with the exact precedence `goal` over `plan`; propagate parsed values through `EngineRunOptions` and `ThreadJob` rather than adding positional loop parameters. `/plan <prompt>` starts a plan run, `/goal <condition>` starts an autonomous goal run, while empty/meta forms retain their sticky/help behavior.

### 3. Port global runner lifecycle settings and safe transient replay

Add the source-backed global settings table to `src/untether/settings.py` and runtime construction:

```python
class RunnerSettings(BaseModel):
    startup_timeout_s: float = 60.0
    idle_timeout_s: float = 900.0
    kill_tree_on_cancel: bool = True
    shutdown_timeout_s: float = 5.0
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay_s: float = Field(default=5.0, ge=0.0)
```

Apply those values in `src/untether/runtime_loader.py` to runners exposing the corresponding attributes, following Takopi’s existing attribute-based wiring; ACP request timeout uses `startup_timeout_s or 60.0`. Merge Takopi’s per-read startup/idle guards and retry loop into Untether’s richer `JsonlSubprocessRunner`; retain Untether watchdogs, approval refire, path/URL redaction, recent-event ring, environment policy, diagnostics, and process ownership.

Retry only a classified transient failure when no session start, action, or answer has been emitted. Total attempts equal `retry_max_attempts`; wait `retry_base_delay_s * current_attempt` before the next attempt. Cancellation, malformed/non-transient errors, or any side-effectful/output event completes without replay. Preserve the clean `format_transient_failure()` terminal message and never surface the provider JSON blob. `kill_tree_on_cancel=false` disables only the additive Windows descendant-tree kill; POSIX process-group cleanup and normal direct-child termination remain intact.

### 4. Complete Pi’s source-backed plan and Windows input behavior

In `src/untether/runners/pi.py`, retain Untether’s filtered environment and richer stream state while porting Takopi’s `detect_plan_mode_extension(root: Path | None = None) -> bool` for `@narumitw/pi-plan-mode` under the conventional Pi extension root. With plan active and the extension present, append `--plan` and do not mutate the prompt. Without it, apply the shared soft-plan prefix and log `pi.plan_mode_extension_missing` once per runner. Goal mode continues to win over plan and uses the shared goal prompt. Also detect the installed `pi-goal-list-loop-audit` extension: when goal mode is active and the extension is present, seed Pi’s extension through the temporary first-message directive `<task-goal>{goal}</task-goal>` and then send the user prompt, rather than substituting Pi’s native `/goal` command, which only exposes status and management operations. Preserve the extension’s scoping invariant—the directive is removed from model context after the first model message—and fall back to the shared goal prompt when the extension is absent, so goal mode remains functional without the optional package.

Change `PiRunner.stdin_payload(prompt, resume)` to return newline-terminated UTF-8 bytes for the multi-line/Windows-safe path exactly as Takopi does; keep existing argument-based attachments/session handling. Empty prompts still produce the source-defined newline payload rather than blocking on inherited stdin.

### 5. Finish user-visible rendering and file prompt parity

Port Takopi’s `format_mode_badge(*, plan: bool, goal: str | None) -> str | None` and context composition so the active mode badge precedes `ctx:` on queued, running, cancelled, and completed cards; goal wins if both values are present.

At Untether’s existing Markdown-to-Telegram renderer, add Takopi’s code-region-safe preprocessing for `||spoiler||`, `++underline++`, single-tilde strike, and GFM `~~strikethrough~~`. Keep raw HTML disabled and leave matching text inside inline code and fenced code literal.

For non-image uploaded task files, emit the exact annotation `Execute the task specified in this file: \`<relative-path>\`.`. Preserve Untether attachment tuples, traversal checks, upload mode, and image behavior. Do not add the removed Takopi file settings `image_subdir`, `image_default_prompt`, or `image_force_prompt` because current Untether intentionally supports images without those schema keys.

### 6. Close behavior-test and hard-gate gaps before runtime cutover

Adapt Takopi’s behavior tests—not source-text assertions—for compact/handoff dispatch and confirmation, ACP factory/client/transport, plan/goal directives and footer badges, Pi extension/stdin behavior, Grok stream/capacity handling, retry safety/backoff, prompt batching integration, runner startup/idle timeouts, subprocess closure, safe markup, exact file annotation, and scheduler/Telegram races. Keep Untether’s existing test layout and fixtures.

Resolve every diagnostic from `uv run --no-sync ty check src tests` to zero, then remove `.github/workflows/ci.yml`’s `allow_failure: true`; do not change warning policy or Python `>=3.12`. A configured threshold is not proof: obtain a complete Linux full-suite run measuring branch coverage at least 81%, plus complete Windows/macOS/Python 3.14 runs. Keep the narrowly Windows-skipped POSIX attestation module; fix, platform-guard, or narrowly skip only genuinely POSIX assertions elsewhere.

### 7. Map the live configuration without exposing credentials

Build `C:/Users/DELL E5570/.untether/untether.toml` from `C:/Users/DELL E5570/.takopi/takopi.toml` without printing raw values. Copy unchanged: top-level engine/project/transport; Telegram token, chat ID, session/resume-line/allowed-user/topic settings; supported file settings; all project path/worktree/default-engine fields; and flat Claude/Grok/Agy engine config.

Delete `transports.telegram.files.image_subdir`, `image_default_prompt`, and `image_force_prompt` because Untether’s files model rejects extras. Drop the Takopi `[logging]` table; preserve its effective non-secret level/file only through Untether’s existing logging environment controls when they differ from defaults. Never point Untether at `.takopi/takopi.toml`: Takopi and Untether locks use different mechanisms and would not prevent duplicate Telegram pollers.

Copy, never move, `telegram_chat_sessions_state.json`, `telegram_topics_state.json`, and `telegram_chat_prefs_state.json` from `.takopi` to `.untether` after Takopi stops; their version-1 filenames and stored fields are compatible, with unknown legacy per-topic plan state intentionally ignored. Never copy `takopi.lock` or log files. Treat these JSON files as sensitive because they contain chat/user IDs and resume tokens.

### 8. Perform a stop-first runtime cutover with deterministic rollback

While Takopi remains active, build and install the verified local Untether wheel/tool from `D:/Projects/untether`, confirm `untether --version` resolves to that build, back up `.takopi` to a timestamped access-protected directory, create `.untether/untether.toml`, and run `untether doctor`. Doctor may call Telegram metadata endpoints but must not start `getUpdates`; never use config commands that reveal token, chat ID, or allowed-user values.

Confirm the live owner with `tasklist`/process command-line inspection and the PID recorded in `takopi.lock` without reporting the PID or fingerprint. The discovered autostart owner is `C:/Users/DELL E5570/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/start.bat`, whose Takopi line launches `D: && takopi`; no service or scheduled task was found (`unverified — confirm first` with read-only service/task queries immediately before cutover).

Gracefully stop that Takopi console first. Verify no `takopi.exe` remains and its lock is released; then recopy the three final state JSON files. Start Untether against `.untether/untether.toml`, observe successful state load and Telegram polling without a conflict error, send one authorized prompt, and verify reply, `/health`, topic routing, resume, and file handling. Confirm exactly one Takopi/Untether poller exists. Only after this health proof, replace only the Takopi launch line in `start.bat` with the verified Untether invocation; preserve unrelated omniroute/codbash/watchmen lines.

If any health check fails, stop Untether and verify its process/lock is released, restore the Startup line, restart Takopi against untouched `.takopi` state, and verify polling/reply. Never merge state written by Untether back into Takopi during rollback.
## Critical files & anchors

- `D:/Projects/untether/src/untether/telegram/loop.py` — prompt dispatch, scheduler observers, progress/session routing, and missing compact/handoff consumers.
- `D:/Projects/untether/src/untether/runner.py` — merge point for startup/idle guards and safe transient replay; preserve its richer destination behavior.
- `D:/Projects/untether/src/untether/runners/pi.py` — missing plan-extension detection and Windows-safe stdin payload.
- `D:/Projects/untether/src/untether/settings.py` — strict Telegram file schema and new global `RunnerSettings` contract.
- `C:/Users/DELL E5570/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/start.bat` — sole discovered Windows autostart owner; edit only after live Untether health proof.
## Verification

Run code gates from `D:/Projects/untether` with `PYTHONUTF8=1` after `uv sync --frozen`:

1. Focused behavior suites: scheduler/cancel/steer; Telegram compact/handoff/meta dispatch; prompt-batch integration; directives/plan/goal/footer; Pi runner/schema; ACP/OMP/Grok/Agy; transient retries and runner timeouts; subprocess close; renderer markup; and file transfer. Use the adapted destination filenames and record the Takopi→Untether test mapping in the audit ledger.
2. Retry proof: a fake JSONL runner fails twice with classified 503 before any event, then succeeds; observe three total attempts and delays `base`, `2*base`. Repeat after a Started event or action and observe exactly one attempt and one clean failure.
3. Compact/handoff proof: confirm old-session approval, exactly one Started and final Completed event with equal resumes, full summary seed, atomic route change only after seed, and no route change on cancellation/seed failure.
4. Pi proof: extension-present plan run contains `--plan` without a soft prefix; extension-absent run has the soft prefix and one warning; a multi-line prompt yields newline-terminated UTF-8 stdin on Windows.
5. Rendering/upload proof: outside code, spoiler/underline/strike become Telegram entities; identical markers inside code stay literal. A non-image upload produces exactly `Execute the task specified in this file: \`incoming/<name>\`.` and one attachment.
6. Static/full gates:
   - `uv run --no-sync ruff format --check src tests`
   - `uv run --no-sync ruff check src tests`
   - `uv run --no-sync ty check src tests` → zero diagnostics
   - `uv run --no-sync pytest tests/ -q --no-cov` on Windows, macOS, and Linux/Python 3.14; Ubuntu compatibility cells on Python 3.12 and 3.13
   - `uv run --no-sync pytest tests/ -q` on Ubuntu/Python 3.14 → complete pass and branch coverage ≥81%
   - `uv lock --check`, `uv build`, `uvx twine check dist/*`, `uvx check-wheel-contents dist/*.whl`
   - install the wheel in a clean environment and import Untether plus every registered backend
   - `uv run --no-sync bandit -r src/ -c pyproject.toml -q`, `uv run --no-sync pip-audit --skip-editable --progress-spinner=off`, and the existing docs build
7. Runtime cutover proof: before stop, `untether doctor` passes against `.untether/untether.toml`; after stop/start there is exactly one poller, one authorized message receives one response, `/health` succeeds, an existing session resumes, a topic routes correctly, and a file-backed task uses the required annotation. After the Startup edit, a logoff/logon repeats the one-process and bot-response checks.
## Assumptions & contingencies

- Current Takopi commit-body access was incomplete through read-only repository-object tooling; the ledger must use `git log --all --format=fuller` during execution and reconcile bodies against the already-inspected changelog aggregate before declaring audit completeness.
- Native OMP/Grok/Agy/ACP probes require installed CLIs and credentials. Deterministic fixtures are mandatory; absent credentials leave only the native probe `unverified`, never the implemented contract.
- `pip-audit` previously reported three advisories in locked `aiohttp 3.14.1`, fixed by 3.14.2/3.14.3. Because the requested end state includes passing security gates, update to the smallest compatible fixed release and regenerate the lock if the audit still reproduces; do not add an ignore.
- If service/task inspection finds another Takopi launcher, disable that launcher in the same stop-first window before Untether starts; preserve a reversible record for rollback.
- If a state file fails version/schema validation, leave the original untouched, start Untether without that one file, and report the lost state category; do not hand-edit sensitive JSON or invent a converter.
