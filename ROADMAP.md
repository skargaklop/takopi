# Takopi Roadmap

## Task 1: Robust `/compact` Command Dispatch

### Problem

The `/compact` slash command does not yet work in all message contexts:

- Replying to a message from an existing session does not reliably route `/compact` to that session's engine.
- The relative order of `/compact` and other slash commands (e.g., `/codex`, `/claude`, `/opencode`) in a single message is not consistently resolved.

### Requirements

1. `/compact` must work when sent as a reply to any message belonging to an existing session — it should compact that session's resume token, regardless of which engine created it.
2. `/compact` must work in any position relative to other slash commands in the same message. Example: both `/codex /compact` and `/compact /codex` should resolve correctly.
3. If the target engine does not support compaction (`compact_support() == CompactSupport.none`), Takopi must:
   - Notify the user that this agent does not support native compaction.
   - Ask the user whether to send the prompt as a plain text compaction request to the agent anyway (i.e., pass the raw compaction prompt through the normal `run()` path, letting the agent handle it as a regular prompt).
   - Only proceed after explicit user confirmation.

### Scope

- `src/takopi/telegram/loop.py` — command dispatch and reply-context resolution
- `src/takopi/scheduler.py` — `ThreadJob.kind` field and compact job routing (partially done in prior session)
- `src/takopi/runners/` — `compact_support()` return values per runner

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
