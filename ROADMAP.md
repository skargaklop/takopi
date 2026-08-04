# Takopi Roadmap

## Task 1: Robust `/compact` Command Dispatch

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
5. `omp` and `grok` must not declare `mode="acp"` / `true_compaction=True` until a production ACP transport exists and harness-side interception of `/compact` is proven (Task 6). Reclassify them as `handoff_only` (delegate `compact()` to `run(handoff_prompt(instructions))`, same as `agy`) so `/compact` works honestly through the normal session path.
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

## Task 5: Clean Shutdown Without Asyncio Pipe-Transport Noise (Windows)

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
