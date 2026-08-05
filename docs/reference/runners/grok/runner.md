# Grok Build CLI runner

Takopi engine id: **`grok`**

## Scope

Run Grok Build CLI non-interactively via headless mode:

```text
grok -p <prompt> --output-format streaming-json [--yolo] [-m <model>] [--session-id <uuid>|--resume <id>]
```

### Non-goals (v1)

- ACP / `grok agent stdio` long-lived JSON-RPC
- Full tool-call `ActionEvent` fidelity (headless streaming-json documents `text`, `thought`, `end`, `error` only)

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
| `end` | `CompletedEvent` with usage / sessionId; answer = trailing text run |
| `error` | `CompletedEvent(ok=False)`; answer = trailing text run |
| other | Ignored (msgspec decode error dropped) |

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

See `stream-sample.jsonl` (math, single-turn) and
`stream-sample-agentic.jsonl` (multi-turn with narration) for reference
captures.
