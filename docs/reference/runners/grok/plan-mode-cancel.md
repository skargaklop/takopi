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

## Chosen enforcement path: **native plan mode + read-only allow-list**

Grok plan mode keeps native `--permission-mode plan` AND restricts the
toolset to a read-only allow-list via `--tools read_file,list_dir,grep,web_search`.
This solves the cancellation problem at its root:

- Mutating tools (`write`, `search_replace`, `run_terminal_command`,
  `todo_write`) are **physically absent** from the agent's toolset.
- The agent cannot call a tool that requires approval, so no approval
  prompt fires, so the harness never cancels the turn.
- `stopReason=end_turn` — the agent produces its plan as text and ends
  cleanly (proven by Task 16 probe D2).

### Why this works (and the alternatives don't)

The cancellation root cause is: `--permission-mode plan` denies mutating
tools at the **approval layer**. In headless mode the harness cannot answer
the interactive approval prompt, so it cancels the turn. Auto-approve flags
(`--always-approve`) do **not** override plan-mode denial (probe D4:
cancelled). Deny-lists (`--deny`, `--disallowed-tools`) don't prevent the
call — the agent still invokes the tool and the denial triggers the same
cancel (probe D5: cancelled via `run_terminal_command`).

The allow-list is the only mechanism that removes the tool **before** the
agent can attempt it. With no mutating tool to call, there is no denial,
no prompt, and no cancel.

### Why an allow-list, not a deny-list?

A deny-list (`--disallowed-tools`) is fragile: every mutating tool name
must be enumerated, and a missed name (or a new tool added in a grok CLI
update) silently allows the write. An allow-list is fail-closed: only the
explicitly listed read-only tools are available; everything else is absent
by default.

### Probe matrix (Task 16, 2026-08-06)

Write-inducing prompt: "Create the file plan-probe.md ... then stop."

| Case | Config | stopReason | File written | Text | Verdict |
|------|--------|------------|-------------|------|---------|
| **D2** | **plan + --tools readonly** | **end_turn** | **No** | **Yes** | **WIN** |
| D1 | bypassPermissions + --tools readonly | end_turn | No | Yes | ok (slower: agent loops on search_tool) |
| D3 | bypassPermissions + write in tools | end_turn | **Yes** | Yes | LOSE (read-only broken) |
| D4 | plan + --always-approve | cancelled | No | No | FAIL (auto-approve doesn't override plan denial) |
| D5 | default + --disallowed-tools | cancelled | No | No | FAIL (deny triggers same cancel) |

**Winner: D2** — `--permission-mode plan --tools read_file,list_dir,grep,web_search`.

### Trade-off

The allow-list is a fixed set of built-in tools. If a future grok version
adds a new read-only tool (e.g. a code-search tool), it would not be
available in plan mode until the allow-list is updated. This is an
acceptable, explicit trade-off for reliable hard enforcement. MCP tools
are also excluded by the allow-list (they are not in the built-in set).

## Salvage safety net (defense in depth)

Even with the allow-list, a plan-mode run could still end with
`stopReason=cancelled` for unrelated reasons (upstream API cancellation,
timeout-induced abort, etc.). The salvage net converts such a cancellation
into a usable outcome:

- **Plan-mode cancel + non-empty trailing answer** → `ok=True` with the
  plan text delivered as the answer, plus the note
  "turn ended by plan-mode enforcement; nothing was executed".
- **Plan-mode cancel + empty answer** → keeps the honest error message.
- **Non-plan cancellations** → unchanged (old "grok run stopped
  (cancelled)" message). A genuine user `/cancel` takes a different code
  path and is not masked.
