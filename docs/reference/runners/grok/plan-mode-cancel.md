# Plan-mode cancellation: trigger classification and enforcement path

> Companion to `stream-sample-plan-cancel.jsonl`. Records the A0
> investigation outcome for Roadmap Task 15 (plan-mode cancel prevention).

## Trigger classification

The grok CLI runs under `--permission-mode plan` for plan-mode runs. In
this mode the harness enforces read-only semantics: any write or execute
tool call is forbidden. Because headless mode (`--output-format
streaming-json`) cannot answer an interactive approval prompt, the
harness cancels the entire turn — the CLI exits with rc=0 and the
stream ends with `stopReason=cancelled`.

### Event sequence before the cancel

In every observed case the last events before `stopReason=cancelled` are:

1. `text` — the agent produces its plan content (the trailing answer run).
2. `tool_call` — the agent attempts a **write** or **execute** tool:
   - `write` (writing a file), or
   - `run_terminal_command` (executing a command), or
   - `search_replace` (editing a file).
3. `end` with `stopReason=cancelled`.

**Classification: forbidden-op abort.** The harness denies the mutating
tool and, unable to prompt for approval in headless mode, cancels the
turn. This is **not** a plan-approval/exit-request shape and **not** a
user-initiated `/cancel`.

### Reproducibility

Task 11 established that the cancellation is **non-deterministic** in
normal runs — the agent does not always attempt a write/execute. Task 12
removed the mandatory plan-file write instruction, which eliminated the
*guaranteed* trigger. However, the agent still self-initiates
writes/commands at its own discretion (e.g. "Let me run the verification
suite" → `run_terminal_command`), producing a cancellation whenever it
does. The cancellation rate dropped but did not reach zero.

### Path A probe: `--deny` / `--disallowed-tools`

Probed using `--disallowed-tools` to block mutating tools instead of
`--permission-mode plan`. The harness DENIES the blocked tool at the
tool-approval layer, but the denial does **not** cancel the turn — the
agent receives a tool-denial error and can continue (produce its text
answer). However, this requires maintaining an exact deny-list of every
mutating tool name, which is fragile: new grok CLI tools or MCP tools
would need manual allowlisting, and a missed tool name silently allows
the write. This trades reliability for a maintenance burden that doesn't
hold up in practice.

## Chosen enforcement path: **Path B (soft-plan prefix)**

Grok plan mode switches from native `--permission-mode plan` to the
shared soft-plan prompt prefix (same approach used by codex, omp, and
opencode). This eliminates harness-enforced read-only entirely:

- No `--permission-mode plan` flag → no forbidden-op cancellations.
- The soft-plan prefix (`SOFT_PLAN_PREFIX` in `modes.py`) instructs
  the agent to work in read-only planning mode at the prompt level.
- `plan_mode=True` is still set on `GrokStreamState` so the salvage
  safety net can fire if a cancellation ever slips through for any other
  reason (upstream API failure, timeout, etc.).

### Trade-off (documented)

**Soft-plan drops the hard read-only guarantee.** Under Path B the agent
is *instructed* not to write/execute but is not *physically prevented*
from doing so. This is acceptable because:

1. The agent operates with `--yolo` (auto-approve) in non-plan mode
   anyway — there is no approval gate to protect in headless mode.
2. Every other Takopi runner (codex, omp, opencode, pi-fallback) already
   uses soft-plan with the same trade-off; grok was the outlier.
3. The reliability gain (zero spurious cancellations) outweighs the
   theoretical enforcement loss for a headless Telegram bridge.
4. The salvage net (Task B below) provides a second layer of defense.

## Salvage safety net (Task B, implemented regardless of path)

Even after switching to Path B, a plan-mode run could still end with
`stopReason=cancelled` for unrelated reasons (upstream API cancellation,
timeout-induced abort, etc.). The salvage net converts such a
cancellation into a usable outcome:

- **Plan-mode cancel + non-empty trailing answer** → `ok=True` with the
  plan text delivered as the answer, plus the note
  "turn ended by plan-mode enforcement; nothing was executed".
- **Plan-mode cancel + empty answer** → keeps the Task-12 honest error
  message ("plan-mode turn cancelled by the harness...").
- **Non-plan cancellations** → unchanged (old "grok run stopped
  (cancelled)" message). A genuine user `/cancel` takes a different code
  path and is not masked.

This distinguishes harness-side plan-mode aborts (via `plan_mode` flag +
`stopReason == cancelled`) from user-initiated cancels, which never set
`plan_mode=True`.
