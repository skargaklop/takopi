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

## Config

See [Config reference — grok](../../config.md#grok).

## Streaming events

| Grok `type` | Takopi mapping |
|-------------|----------------|
| `text` | Accumulate into the current text segment (answer or narration) |
| `thought` | Buffered, coalesced into one note `ActionEvent` per contiguous block (flushed by the next non-thought event); also closes the current text segment as narration |
| `tool_call` | `action_started` via shared `tool_kind_and_title` (command/file/tool kind); duplicate starts for the same `toolCallId` are suppressed |
| `tool_call_update` | `action_completed` (status `completed` → `ok=True`, `error` → `ok=False`) |
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

Takopi segments text at `thought` event boundaries: when a thought block
arrives, the preceding text run is closed as narration and becomes a
coalesced note action in progress (same flush style as thought coalescing).
The **trailing text run** (after the last thought, with no subsequent
thought) is the answer and goes into `CompletedEvent.answer`.

Single-turn Q&A runs (contiguous text, no thoughts interleaved) produce
one text segment → answer = full text (backward compatible).

See `stream-sample.jsonl` (math, single-turn),
`stream-sample-agentic.jsonl` (multi-turn with narration), and
`stream-sample-tools.jsonl` (tool-heavy agentic run with `tool_call`,
`tool_call_update`, `usage`, `available_commands`) for reference
captures.
