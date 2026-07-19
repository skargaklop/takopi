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
| Combined | `/happy-gadgets @feat/flower-pin observe unseen` | Project + branch. |

Notes:

- Directives are only parsed at the start of the first non-empty line.
- Parsing stops at the first non-directive token (except `/goal`, which consumes the rest of the message as the condition).
- `/plan` and `/goal` are reserved mode tokens (they win over a project alias named `plan` / `goal`).
- If a reply contains a `ctx:` line, Takopi ignores new directives and uses the reply context.
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
| pi | yes | no | soft, or `--plan` if `pi.plan_flag=true` | soft note |
| opencode | yes | no | soft, or `--agent` if `opencode.plan_agent` set | soft note |

See [Context resolution](context-resolution.md) for the full rules.

## Context footer (`ctx:`)

When a run has project context, Takopi appends a footer line rendered as inline code:

- With branch: `` `ctx: <project> @<branch>` ``
- Without branch: `` `ctx: <project>` ``

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
| `/file put <path>` | Upload a document into the repo/worktree (requires file transfer enabled). |
| `/file get <path>` | Fetch a file or directory back into Telegram. |
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
