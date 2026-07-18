# Antigravity CLI (`agy`) runner

Takopi engine id: **`agy`**

## Scope

Run Google Antigravity CLI non-interactively via headless print mode:

```text
agy [-p <prompt>] [--model <id>] [--dangerously-skip-permissions]
    [--conversation <uuid>]
```

### Non-goals (v1)

- Stream-json / live tool ActionEvents (CLI prints plain text on stdout)
- Antigravity GUI / IDE automation
- ACP mode

## Resume UX

Canonical resume line:

```text
`agy --conversation <session_id>`
```

Also accepted: `agy -c <session_id>`.

New sessions pre-generate a UUID for early `StartedEvent` locking; if the CLI logs a conversation id, the runner may promote the resume token to the real id.

## Permissions

Telegram cannot answer interactive tool prompts. Takopi defaults `yolo = true` (`--dangerously-skip-permissions`). Prefer configuring `settings.json` allow rules for production.

## Config

See [Config reference — agy](../../config.md#agy-antigravity-cli).

## Events

| Phase | Takopi |
|-------|--------|
| process start | `StartedEvent` |
| process exit | `CompletedEvent` with full stdout as `answer` |
