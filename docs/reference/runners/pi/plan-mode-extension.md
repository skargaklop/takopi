# Pi Plan-Mode Extension (`@narumitw/pi-plan-mode`)

This document records the contract between Takopi and the
`@narumitw/pi-plan-mode` extension. Takopi delegates plan mode to the
extension when it is detected, and falls back to a prompt-based soft-plan
mode when it is absent.

## Package

- **Name:** `@narumitw/pi-plan-mode`
- **License:** MIT
- **Repository:** `https://github.com/narumiruna/pi-extensions`
  (`extensions/pi-plan-mode`)
- **Peer deps:** `@earendil-works/pi-coding-agent`, `@earendil-works/pi-tui`
  (Pi ≥ 0.80.6 required at time of writing)

## Install path (conventional)

```
~/.pi/agent/npm/node_modules/@narumitw/pi-plan-mode/
```

This is the standard `pi install npm:@narumitw/pi-plan-mode` target. Takopi
detects the extension by checking for this directory.

## CLI contract

The extension registers a `--plan` CLI flag:

| Flag | Behavior |
|------|----------|
| `--plan` | Starts the session in Plan mode (read-only exploration, structured questions, plan completion via `plan_mode_complete` tool). |

Plan mode is a conversational collaboration mode, not TODO tracking. When
active:

- Built-in read-only tools (`read`, limited `bash`, `grep`, `find`, `ls`) are
  enabled; `edit`, `write`, and `update_plan` are blocked.
- Extension/custom tools are disabled by default (opt-in via `/plan tools`).
- The agent must call `plan_mode_complete({ plan })` as its standalone final
  action to submit a structured Markdown plan.
- `plan_mode_question` follows Codex's `request_user_input` pattern (1–3
  concise questions with options + free-form Other).

Settings are read from `$PI_CODING_AGENT_DIR/pi-plan-mode.json` (normally
`~/.pi/agent/pi-plan-mode.json`). The file is optional and never created
automatically.

## Behavior without the extension

Passing `--plan` to Pi without the extension installed is **untested
behavior** — Pi core does not ship a built-in plan mode, so the flag may be
silently ignored or produce an error depending on the Pi version. Takopi
treats this as unsafe and **never appends `--plan` when the extension is not
detected**. Instead it falls back to the shared soft-plan prompt prefix
(`modes.apply_soft_plan_prompt`) and logs a one-time warning:
`pi.plan_mode_extension_missing`.

## Goal mode (out of scope for this extension)

Goal mode is unrelated to `pi-plan-mode`. It is implemented as a prompt
prefix (`(autonomous goal — work until: <condition>)`) injected by
`PiRunner._final_prompt`. No extension is needed. Goal takes priority over
plan when both are set (`run_modes` returns `(False, goal)` in that case).

## Other extensions (out of scope — YAGNI)

These pi extensions exist but are not detected or gated by Takopi:

- `@narumitw/pi-goal-list-loop-audit`
- `@narumitw/pi-dynamic-workflows`

They may be documented here if Takopi adds support for them in the future.
