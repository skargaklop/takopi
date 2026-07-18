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
| `text` | Accumulate into `CompletedEvent.answer` |
| `thought` | Optional note `ActionEvent` |
| `end` | `CompletedEvent` with usage / sessionId |
| `error` | `CompletedEvent(ok=False)` |
| other | Ignored (msgspec decode error dropped) |
