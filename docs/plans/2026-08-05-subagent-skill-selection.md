# Subagent and Skill Selection - Plan-Spec (Roadmap Task 3)

> Roadmap Task 3. User mandate (2026-08-05): harness documentation must be
> gathered by read-only subagents running CHEAP models (e.g.
> deepseek-v4-flash class), one per harness, saved under
> `docs/reference/runners/<engine>/`.
>
> User decision (2026-08-05): skill lists are wide and dynamic - every
> user has their own skills. Selection syntax is DUAL (user amendment 2026-08-05): the inline
> options `--skill <name>` / `--subagent <name>` AND the generic slash
> tokens `/skill <name>` / `/subagent <name>` (one free-form argument
> each; NO per-skill registered commands, NO static enumeration, NO name
> validation in takopi). The name passes through to
> the harness, which resolves it against the user's own skill list and
> owns any unknown-skill error.

**Goal:** users can direct a run to a specific subagent or skill:
`/codex --subagent reviewer fix the bug`, `/claude --skill tdd write tests`,
per-engine config defaults (`[codex] subagent = "..."`), and per-session
sticky selection - but only for harnesses whose support is verified by the
A0 documentation pass. No invented flags.

**Interface shape (locked):** two equivalent forms, both parsed only in
the leading command area (alongside the engine selector):
- inline options: `--skill <name>`, `--subagent <name>`
- slash tokens: `/skill <name>`, `/subagent <name>` - generic commands
  with one free-form name argument (NOT per-skill registrations; the bot
  menu gets at most one `/skill` and one `/subagent` entry)
Example: `/codex --skill tdd write tests` == `/codex /skill tdd write tests`.
Sticky per session: bare `/skill <name>` (no prompt) sets the sticky
selection for the chat/topic; `/skill off` (or `clear`) clears; bare
`/skill` shows the current value - mirrors the sticky `/plan` pattern.
One-shot use (with a prompt) overrides sticky for that run only.
Precedence: inline one-shot > sticky > per-engine config default > none.

## Phase 0 - Documentation gathering (cheap-model subagents)

Dispatch 6 read-only investigation subagents (cheap model, no code edits,
scope-locked), one per harness. Each brief:

- Run/inspect the harness CLI help and local docs/config:
  - codex: `codex --help`, `~/.codex/` (config.toml profiles, agents)
  - claude: claude docs, `~/.claude/agents/`, `--agents` JSON, Skill tool,
    `/slash` skills
  - opencode: opencode docs, `opencode.json` agents, `--agent`
  - pi + omp: pi CLI flags, `~/.pi/agent/npm/node_modules/` extensions
    (incl. how omp inherits pi flags via PiRunner)
  - grok: `grok --help` (seed evidence already verified: `--agent <NAME|
    definition-file>`, `--agents <JSON>` inline definitions, `spawn_subagent`
    tool, skills via advertised commands), `~/.grok/`
  - agy: agy CLI help/docs
- Answer exactly: (a) how to select a subagent/agent/profile for a single
  headless invocation (exact flags/syntax), (b) how to activate a named
  skill, (c) relevant config keys, (d) evidence quotes with source.
- Save to `docs/reference/runners/<engine>/subagents-skills.md`.
- Constraints: read-only; do NOT modify any files outside the target doc
  path; report difficulties/pitfalls (appended to `EXPERIENCE.md`).

Output of the phase: a capability matrix (engine x subagent support x skill
support x exact syntax) in `docs/reference/runners/capability-matrix.md`.

## Phase 1 - Plumbing + one pilot engine (TDD)

### Task A - Failing tests (RED)

1. Parser: extract skill/subagent from the leading command area in BOTH
   forms (`--skill X` == `/skill X`, `--subagent X` == `/subagent X`),
   returning the cleaned prompt; missing value -> user-facing usage error;
   `@bot` suffixes unaffected; bare `/skill <name>` (no prompt) detected
   as the sticky-setter form; names are free-form pass-through (no
   membership check).
2. Precedence: inline option > sticky session > config default > none
   (per engine).
3. Pilot engine wiring (the best-documented one from A0, likely grok
   `--agent`): build_args injects the verified flag exactly per the saved
   doc contract.
4. Sticky store: set/clear/show per chat/topic mirrors the sticky-plan
   pattern (`chat_prefs`/`topic_store`).
5. Unsupported engine (per matrix): clean user-facing note, no flag
   injected.

### Task B - Implementation (GREEN)

- B1. Parser + `EngineRunOptions.subagent/skill` fields (`run_options.py`).
- B2. Settings: per-engine config keys (documented in
  `docs/reference/config.md`).
- B3. Sticky selection via the bare slash form (`/skill <name>` set,
  `off`/`clear` clear, bare show) stored in the existing prefs/topic
  stores (mirrors sticky `/plan`).
- B4. Pilot runner `build_args` injection.
- B5. Docs + changelog.

## Phase 2 - Remaining engines

Wire each harness per the A0 matrix, one commit per engine, each with its
own runner tests. Engines without verified support get the documented
no-op note only.

## Verification gate (per phase)

```
uv run pytest -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e (pilot): `/grok --subagent <name> <task>` selects the agent;
sticky set persists for the session; config default applies otherwise.

## Risks and pitfalls

- No flag may be wired without A0 evidence quotes; the matrix is the
  contract.
- Subagent feedback quality: cheap models must still produce exact flag
  names with sources; spot-check one harness result against the local CLI
  before Phase 1 design freeze.
- Parser must not eat prompt text: options only parse in the leading
  command area (same discipline as the compact invocation parser).
- Sticky state must not leak across chats/topics (store keys follow the
  existing prefs pattern).
- Skill names are dynamic per user; takopi never validates them against a
  list. Harness-side unknown-skill errors surface to the user unchanged.
- Do not commit unless the user explicitly asks.