# Grok Build CLI runner

Takopi engine id: **`grok`**

## Scope

Run Grok Build CLI non-interactively via headless mode:

```text
grok -p <prompt> --output-format streaming-json [--yolo] [-m <model>] [--session-id <uuid>|--resume <id>]
```

### Non-goals (v1)

- ACP / `grok agent stdio` long-lived JSON-RPC

## Resume UX

Canonical resume line:

```text
`grok --resume <session_id>`
```

Also accepted: `grok -r <session_id>`.

For **new** sessions Takopi pre-generates a UUID and passes `--session-id` so a `StartedEvent` can be emitted immediately (Grok only reports `sessionId` on the final `end` event).

## Permissions

Telegram automation cannot answer interactive tool prompts. Takopi defaults `yolo = true` (`--yolo`). Explicit deny rules and PreToolUse hooks still apply on the Grok side.

## Plan mode

Grok uses the **shared soft-plan prompt prefix** (Path B) instead of
native `--permission-mode plan`. The native flag caused spurious turn
cancellations: in headless mode the harness cannot answer interactive
approval prompts, so any write/execute attempt cancelled the entire turn
with `stopReason=cancelled`. The soft-plan prefix instructs the agent to
work in read-only planning mode at the prompt level — same approach used
by codex, omp, opencode, and pi (fallback).

**Trade-off:** soft-plan drops the hard read-only guarantee. The agent is
*instructed* not to write/execute but is not physically prevented from
doing so. This is acceptable for a headless Telegram bridge (the agent
runs with `--yolo` in non-plan mode anyway; every other runner already
uses soft-plan).

**Salvage safety net:** if a plan-mode run still ends with
`stopReason=cancelled` for any reason (upstream abort, timeout), and
plan text was produced, the plan is delivered as a soft success with the
note "turn ended by plan-mode enforcement; nothing was executed" instead
of an opaque error. A plan-mode cancel with no plan text keeps the honest
error message.

See [plan-mode-cancel.md](plan-mode-cancel.md) for the full trigger
classification and path-selection rationale.

## Config

See [Config reference — grok](../../config.md#grok).

## Streaming events

| Grok `type` | Takopi mapping |
|-------------|----------------|
| `text` | Accumulate into the current text segment (answer or narration) |
| `thought` | Buffered, coalesced into one note `ActionEvent` per contiguous block (flushed by the next non-thought event); also closes the current text segment as narration |
| `tool_call` | `action_started` via `_grok_tool_kind_and_title` adapter (maps grok names → canonical, e.g. `run_terminal_command`→`command`); duplicate starts for the same `toolCallId` are suppressed; also closes the current text segment as narration |
| `tool_call_update` | `action_completed` (status `completed` → `ok=True`, `error` → `ok=False`); also closes the current text segment as narration |
| `usage` | Buffered as `mid_stream_usage`; merged into terminal `CompletedEvent.usage` (end-event usage takes precedence) |
| `available_commands` | Ignored (no action, no warning) |
| `end` | `CompletedEvent` with usage / sessionId; answer = trailing text run |
| `error` | `CompletedEvent(ok=False)`; answer = trailing text run |
| other / unknown | `StreamUnknownEvent` catch-all — DEBUG log, no events, no warning spam (forward compatibility) |

### Answer/narration split

In agentic multi-turn runs, the grok CLI emits `text` events for both
**narration** (assistant commentary between tool calls, e.g. "Let me read
the plan first...") and the **final answer**. Without segmentation, all
text is concatenated into the final message, producing large dumps of
reasoning followed by the actual answer.

Takopi segments text at `thought` and `tool_call` boundaries: when a
thought block or tool call arrives, the preceding text run is closed as
narration and becomes a coalesced note action in progress (same flush
style as thought coalescing). The **trailing text run** (after the last
thought/tool event, with no subsequent delimiter) is the answer and goes
into `CompletedEvent.answer`.

Single-turn Q&A runs (contiguous text, no thoughts interleaved) produce
one text segment → answer = full text (backward compatible).

See `stream-sample.jsonl` (math, single-turn),
`stream-sample-agentic.jsonl` (multi-turn with narration), and
`stream-sample-tools.jsonl` (tool-heavy agentic run with `tool_call`,
`tool_call_update`, `usage`, `available_commands`) for reference
captures.

### Tool-title display contract

Grok tool names differ from the claude-shaped names the shared
`tool_kind_and_title` helper understands. The `_grok_tool_kind_and_title`
adapter translates grok names and normalizes input fields before
delegating:

- `run_terminal_command` → `bash` → kind `command`, title = relativized command
- `read_file` → `read` → kind `tool`, title = `` read: '<path>' ``
- `search_replace`/`write` → `edit` → kind `file_change`, title = relativized path
- `list_dir` → `ls` → kind `tool`, title = `` ls: '<path>' ``
- `grep` → `grep` → kind `tool`, title = pattern
- `todo_write` → `todowrite` → kind `note`
- `spawn_subagent` → `task` → kind `subagent`, title = description
- unknown tools → generic `(tool, tool_name)` fallback

Input fields `target_file`→`file_path` and `target_directory`→`path`
are normalized so the shared helper's path-key lookup succeeds. See
[tool-fields.md](tool-fields.md) for the full field-shape reference.
