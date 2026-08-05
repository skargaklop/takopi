# Commands & directives

This page documents Takopi’s user-visible command surface: message directives, in-chat commands, and the CLI.

## Message directives

Takopi parses the first non-empty line of a message for a directive prefix.

| Directive | Example | Effect |
|----------|---------|--------|
| `/<engine-id>` | `/codex fix flaky test` | Select an engine for this message. |
| `/<project-alias>` | `/happy-gadgets add escape-pod` | Select a project alias. |
| `@branch` | `@feat/happy-camera rewind to checkpoint` | Run in a worktree for the branch. |
| `/plan` | `/plan /claude design auth` | Enable **agent plan mode** for this run (read-only / plan-first where the CLI supports it). |
| `/goal …` | `/goal all tests pass` | Enable **goal mode** (autonomous loop until condition). Rest of message is the condition. |
| `resume <id>` | `resume abc123 continue` | **Explicit session resume** (universal alias for all engines, including `agy`). Highest priority over reply/auto-session. |
| Combined | `/happy-gadgets @feat/flower-pin observe unseen` | Project + branch. |

Resume examples (user-typed resume always wins):

- `codex resume <id> continue fixing tests`
- `/claude resume <id> …` or bare `resume <id> …` with sticky/default Claude
- `/agy resume <id> …` or `agy --conversation <id>` (Antigravity; `resume` is an accepted alias)
- Explicit resume beats chat auto-resume and the reply footer session

Notes:

- Directives are only parsed at the start of the first non-empty line.
- Parsing stops at the first non-directive token (except `/goal`, which consumes the rest of the message as the condition).
- `/plan` and `/goal` are reserved mode tokens (they win over a project alias named `plan` / `goal`).
- If a reply contains a `ctx:` line, Takopi ignores new directives and uses the reply context.
- **Multi-message input:** when prompt batching is enabled (default), several rapid text messages from the same sender/chat/topic/reply target are joined into one prompt before directives are parsed, so `/codex fix this` followed by a pasted body becomes one engine directive prompt. Control commands, voice, files, and forwards are never batched. See [Long Telegram prompts](../how-to/long-telegram-prompts.md).
- **Plan** maps to CLI flags when available (`claude`/`grok` `--permission-mode plan`, `agy --mode plan`, optional `omp`/`pi`/`opencode` config). Other engines get a soft plan prompt prefix.
- **Goal** is native for Claude (`-p "/goal …"`). Grok gets a best-effort `/goal` prompt prefix. Other engines get a soft condition note in the prompt.
- When both plan and goal would apply, **goal wins** (plan mode would block unattended tool use).

### Plan / goal / queue / steer capability (engines)

| Engine | Queue (Takopi FIFO) | Mid-turn steer | Plan mode | Goal loop |
|--------|---------------------|----------------|-----------|-----------|
| codex | yes | yes (app-server) | soft prompt | soft note |
| claude | yes | no | `--permission-mode plan` | `/goal` in prompt |
| grok | yes | no | `--permission-mode plan` | best-effort `/goal` prompt |
| agy | yes | no | `--mode plan` | soft note |
| omp | yes | no | `omp.plan_mode=soft\|yolo\|off` | soft note |
| pi | yes | no | `--plan` (pi-plan-mode extension) | soft note |
| opencode | yes | no | soft, or `--agent` if `opencode.plan_agent` set | soft note |

See [Context resolution](context-resolution.md) for the full rules.

## Context footer (`ctx:`)

When a run has project context, Takopi appends a footer line rendered as inline code:

- With branch: `` `ctx: <project> @<branch>` ``
- Without branch: `` `ctx: <project>` ``

If the run is in **plan mode** or **goal mode**, a `` `plan` `` or `` `goal` `` badge precedes the `ctx:` segment on the same footer line (goal wins if both apply). When no project context is bound, the badge appears on its own. Example with plan mode: `` `plan` `ctx: <project> @<branch>` ``.

This line is parsed from replies and takes precedence over new directives.

## Telegram in-chat commands

| Command | Description |
|---------|-------------|
| `/cancel` | Reply to the progress message to stop the current run. |
| `/agent` | Show/set the default engine for the current scope. |
| `/model` | Show/set the model override for the current scope. |
| `/reasoning` | Show/set the reasoning override for the current scope. |
| `/trigger` | Show/set trigger mode (mentions-only vs all). |
| `/plan` | Show sticky plan mode; `/plan on` \| `off` \| `clear` for chat/topic scope. Free-form `/plan <prompt>` (optionally with `/engine`) starts a **plan-mode agent run**. |
| `/goal` | Bare `/goal` shows help. `/goal <condition>` starts a **goal-mode agent run**. |
| `/queue` | Show FIFO queue depth and previews for the active thread (reply to progress/final if needed). |
| `/compact` | Compact the current session's context. Works in any position relative to engine selectors (`/codex /compact` = `/compact /codex`). Optional free-form text passes instructions (e.g. `/compact keep test plan`). Reply to any progress/final message or use in a chat/topic with an active session. Engines with native compaction (claude, pi, codex, opencode) run immediately. Engines without native compaction (grok, omp, agy, or unsupported) show an approval card: approve to produce a handoff summary and start a new session seeded with it (actual context reduction). |
| `/handoff` | Start a new session with a handoff summary from the current session — for **every** engine, including those with native compaction. Works in any position relative to engine selectors (`/codex /handoff` = `/handoff /codex`). Optional free-form text passes instructions (e.g. `/handoff keep the test plan`). Always shows an approval card first (two buttons); on approve: (1) handoff summary produced in the old session, (2) new session seeded with the full summary, (3) routing flips to the new session, (4) summary echoed (truncated). Reply to any progress/final message or use in a chat/topic with an active session. |
| `/file put <path>` | Upload a document into the repo/worktree (requires `transports.telegram.files.enabled`). |
| `/file get <path>` | Fetch a file or directory back into Telegram. |


**Agent → user files (Takopi-mediated):** when files are enabled and `send_enabled` is true, agents may deliver files by writing under the project and including:

```text
[[takopi-send: /absolute/path/file.ext]]
```

Allowed extensions come from `send_extensions` (default: jpg/png/gif/pdf/md/html/doc/docx/xls/xlsx). In **plan mode**, a `.md` or `.html` delivery is required (`plan_require_send`); if missing, Takopi can auto-write `outgoing/plan-*.md` (`plan_auto_file`).
| `/topic <project> @branch` | Create/bind a topic (topics enabled). |
| `/ctx` | Show context binding (chat or topic). |
| `/ctx set <project> @branch` | Update context binding. |
| `/ctx clear` | Remove context binding. |
| `/new` | Clear stored sessions for the current scope (topic/chat). |

### Queue & steer (progress buttons)

- While a thread is busy, new messages on that thread are **queued** (FIFO). Progress shows label `queued`.
- **cancel** drops a queued job or cancels the active run.
- **steer** injects a queued prompt into the **active** turn when the runner exposes turn control (**Codex only** today). For other engines the button is omitted; the job stays queued until the active run finishes.

Notes:

- Outside topics, `/ctx` binds the chat context.
- In topics, `/ctx` binds the topic context.
- `/new` clears sessions but does **not** clear a bound context.
- Sticky `/plan on` merges with per-message `/plan` for subsequent runs in that scope.
- **Dual-mode commands:** `/plan` and `/goal` are both sticky/help bot commands **and** message directives. Free-form text after them starts an agent run (same as prefixing a normal prompt). Other slash commands (`/agent`, `/model`, `/reasoning`, `/trigger`, `/queue`, …) are meta-only and never fall through to a run.
- **Shorthand sets:** `/agent claude`, `/model opus`, `/reasoning high` work without the `set` keyword (same as `/agent set claude`, etc.).

### `/compact` vs `/handoff`

Both share the same engine-resolution, session-resolution, and migration executor. The only difference is which engines take the approval-gate path:

- **`/compact`** = reduce context. Engines with native compaction (claude, pi, codex, opencode) compact **in place** immediately. Engines without native compaction (grok, omp, agy, unsupported) show an approval card for the handoff-migration flow.
- **`/handoff`** = always start a new session with a handoff summary, for **every** engine — including those that can compact natively. Ignores `compact_support()` entirely.

On engines without native compaction, `/compact` and `/handoff` are identical. On engines with native compaction, `/compact` compacts in place while `/handoff` forces the handoff-migration (clean session break with a summary).

## CLI

Takopi’s CLI is an auto-router by default; engine subcommands override the default engine.

### Commands

| Command | Description |
|---------|-------------|
| `takopi` | Start Takopi (runs onboarding if setup/config is missing and you’re in a TTY). |
| `takopi <engine>` | Run with a specific engine (e.g. `takopi codex`). |
| `takopi init <alias>` | Register the current repo as a project. |
| `takopi chat-id` | Capture the current chat id. |
| `takopi chat-id --project <alias>` | Save the captured chat id to a project. |
| `takopi doctor` | Validate Telegram connectivity and related config. |
| `takopi plugins` | List discovered plugins without loading them. |
| `takopi plugins --load` | Load each plugin to validate types and surface import errors. |

### Common flags

| Flag | Description |
|------|-------------|
| `--onboard` | Force the interactive setup wizard before starting. |
| `--transport <id>` | Override the configured transport backend id. |
| `--debug` | Write debug logs to `debug.log`. |
| `--final-notify/--no-final-notify` | Send the final response as a new message vs an edit. |
