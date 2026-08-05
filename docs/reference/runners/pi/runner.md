Below is a concrete implementation spec for the **Pi (pi-coding-agent CLI)** runner shipped in Takopi (v0.5.0).

---

## Scope

### Goal

Provide the **`pi`** engine backend so Takopi can:

* Run Pi non-interactively via the **pi CLI** (`pi --print`).
* Stream progress by parsing **`--mode json`** (newline-delimited JSON). Each line is a JSON object.
* Support resumable sessions via **`--session <token>`** (Takopi emits a canonical resume line the user can reply with).

### Non-goals (v1)

* Interactive TUI flows (session picker, prompts, etc.)
* RPC mode (requires a long-running process and JSON commands)

---

## UX and behavior

### Engine selection

* Default: `takopi` (auto-router uses `default_engine` from config)
* Override: `takopi pi`

### Resume UX (canonical line)

Takopi appends a **single backticked** resume line at the end of the message, like:

```text
`pi --session ccd569e0`
```

Notes:

* `pi --resume/-r` opens an interactive session picker, so Takopi uses `--session <token>` instead.
* The resume token is the **session id** (short prefix), derived from the session
  header line (`{"type":"session", ...}`) emitted to stdout in `--mode json`.
  This requires **pi-coding-agent >= 0.45.1**.
* If the path contains spaces, the runner will quote it.

### Non-interactive runs

Use `--print` and `--mode json` for headless JSONL output.

Pi does not accept `-- <prompt>` to protect prompts starting with `-`. Takopi prefixes a leading space if the prompt begins with `-` so it is not parsed as a flag.

---

## Config additions

Takopi config lives at `~/.takopi/takopi.toml`.

Add a new optional `[pi]` section.

Recommended schema:

=== "takopi config"

    ```sh
    takopi config set default_engine "pi"
    takopi config set pi.model "..."
    takopi config set pi.provider "..."
    takopi config set pi.extra_args "[]"
    ```

=== "toml"

    ```toml
    # ~/.takopi/takopi.toml

    default_engine = "pi"

    [pi]
    model = "..."               # optional; passed as --model
    provider = "..."            # optional; passed as --provider
    extra_args = []             # optional list of strings, appended verbatim
    ```

Notes:

* `extra_args` lets you pass new Pi flags without changing Takopi.
* Session files are stored under Pi's default session dir:
  `~/.pi/agent/sessions/--<cwd>--` (with path separators replaced by `-`).

---

## Code changes (by file)

### 1) New file: `src/takopi/runners/pi.py`

Expose a module-level `BACKEND = EngineBackend(...)`.

#### Runner invocation

The runner should launch Pi in headless JSON mode:

```text
pi --print --mode json --session <session.jsonl> <prompt>
```

When resuming, `<session.jsonl>` is replaced by the resume token extracted from the chat.

#### Event translation

Pi JSONL output is `AgentSessionEvent` (from `@mariozechner/pi-agent-core`).
The runner should translate:

* `tool_execution_start` -> `action` (phase: started)
* `tool_execution_end` -> `action` (phase: completed)
* `agent_end` -> `completed`

For the final answer, use the most recent assistant message text (from
`message_end` events). For errors, if the assistant stopReason is `error` or
`aborted`, emit `completed(ok=false, error=...)`.

---

## Installation and auth

Install the CLI globally:

```text
npm install -g @mariozechner/pi-coding-agent
```

Minimum supported pi version: **0.45.1**.

Auth is stored under `~/.pi/agent/auth.json`. Run `pi` once interactively to
set up credentials before using Takopi.

---

## Known pitfalls

* `--resume` is interactive; Takopi uses `--session <path>` instead.
* Prompts that start with `-` are interpreted as flags by the CLI. Takopi
  prefixes a space to make them safe.

---

## Plan and Goal mode

### Plan mode

Takopi detects the `@narumitw/pi-plan-mode` extension at runner startup by
checking for `~/.pi/agent/npm/node_modules/@narumitw/pi-plan-mode`.

- **Extension present:** `--plan` is appended to the pi CLI args, delegating
  plan behavior to the extension (read-only tools, structured questions,
  `plan_mode_complete`).
- **Extension absent:** `--plan` is NOT appended. Takopi falls back to the
  shared soft-plan prompt prefix (read-only planning instruction) and logs a
  one-time `pi.plan_mode_extension_missing` warning.

See [plan-mode-extension.md](plan-mode-extension.md) for the full extension
contract.

### Goal mode

Goal mode is prompt-based and needs no extension. It prepends
`(autonomous goal — work until: <condition>)` to the user prompt. When both
plan and goal are set, goal takes priority (`run_modes` returns the goal and
clears plan).

### Multi-line prompts and stdin

Both the autonomous-goal prefix and the soft-plan prefix inject newlines into
the prompt. Because `pi.cmd` (the Windows batch wrapper) rejects argv
elements containing newlines, multi-line prompts are piped through stdin
instead of passed as a CLI arg.

---

If you want, I can also add a sample `takopi.toml` snippet to the README or
include a small quickstart section for Pi in the onboarding panel.
