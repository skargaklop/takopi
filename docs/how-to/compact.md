# Compact a session

`/compact` reduces the context size of an active session so long conversations
can continue without hitting context limits. It never starts a new session —
it always operates on an existing resume token.

## Usage

```
/compact                  — compact the current session
/compact keep tests       — compact with custom instructions
```

Reply to a Takopi **progress** or **final** message to target a specific session.
If no session is found (no stored session, no reply target, no active run),
Takopi replies:

> no active session to compact.
> reply to a Takopi progress/final message, or send a normal prompt first.

## How Takopi finds the session

Resolution order (token-only — `/compact` never creates a new session):

1. Explicit resume line in the reply message
2. Reply to an active run's progress message
3. Stored session for the current chat/topic scope

If none of these yield a resume token, the command fails with the error above.

## Per-engine behavior

| Engine | Mode | Instructions | Notes |
|--------|------|-------------|-------|
| `claude` | `slash_prompt` | accepted | Sends `/compact <instructions>` to the CLI |
| `pi` | `slash_prompt` | accepted | Sends `/compact <instructions>` to the CLI |
| `codex` | `slash_prompt` | dropped (with warning) | Sends bare `/compact`; instructions are not supported by Codex compact |
| `opencode` | `native_api` | dropped (with warning) | Calls the OpenCode server compact API directly |
| `grok` | `acp` | accepted | Uses ACP `session/prompt` — only works when the agent advertises the `compact` command |
| `omp` | `acp` | accepted | Uses ACP `session/prompt` — only works when the agent advertises the `compact` command |
| `agy` | `handoff_only` | accepted | Generates a handoff summary, **not real compaction**. The summary preserves goals, decisions, files changed, and next steps. |

When instructions are dropped (Codex, OpenCode), Takopi sends a warning before
running the compact:

> codex compact instructions are not supported yet; running compact without the
> supplied instructions.

## ACP capability gating

For `grok` and `omp`, Takopi connects via ACP (Agent Client Protocol) and checks
whether the agent advertises the `compact` command. If the agent does not
advertise it, Takopi emits a failed completion event without sending a prompt.
This is by design — ACP compact is only attempted when the capability is present.

## Serialization with active runs

`/compact` jobs are enqueued on the same per-thread `ThreadScheduler` as
regular prompt jobs. If a run is active on the same session, the compact job
waits in the FIFO queue until the run completes. This prevents concurrent
operations on the same resume token.

## Multi-message instructions

When prompt batching is enabled (`prompt_batch_enabled = true`, the default),
you can send `/compact` instructions across multiple Telegram messages. For
example:

```
/compact preserve the following decisions
and keep all failing test names
also keep the deployment plan
```

Takopi collects these chunks during the debounce window, joins them, and sends
the assembled text as a single `/compact` command. Control commands like
`/cancel`, `/new`, and `/ctx` bypass batching and are handled immediately.

## What `/compact` does not do

- **Never starts a new session.** If there is no existing session, it fails.
- **Does not change the stored session token.** The chat/topic session binding
  remains the same after compaction.
- **`agy` is not real compaction.** It produces a handoff summary that the next
  turn reads as context, but the full conversation history is not compressed.

## See also

- [Commands and directives](../reference/commands-and-directives.md) — full command reference
- [Specification §5.7](../reference/specification.md#57-runner-compaction-protocol-may) — normative compaction protocol
- [Plugin API](../reference/plugin-api.md) — `CompactRunner`, `CompactSupport`, `SlashCompactMixin`, `AcpCompactMixin`

# Compacting session context

Use `/compact` to reduce the context size of an active session. This is useful
when a conversation has grown long and the runner is approaching context limits.

## Basic usage

```
/compact
```

Compacts the current session's context. Takopi resolves the session from:

1. **Reply** — reply to a Takopi progress or final message to target that session.
2. **Active session** — if the chat/topic has a stored session, it is used.
3. **No session** — if none is found, Takopi replies with an error.

```
/compact keep the test plan and recent decisions
```

Optional free-form text after `/compact` passes **instructions** to the
compactor. The instructions tell the compactor what to preserve.

## Per-engine behavior

| Engine | Compact | Instructions |
|--------|---------|-------------|
| `claude` | true (`/compact` slash command) | accepted |
| `pi` | true (`/compact` slash command) | accepted |
| `codex` | true (`/compact` slash command) | dropped with warning |
| `opencode` | true (server API) | dropped with warning |
| `grok` | true only when ACP advertises `compact` | accepted |
| `omp` | true only when ACP advertises `compact` | accepted |
| `agy` | **handoff summary only** — not real compaction | accepted |

When instructions are not supported (e.g. `codex`, `opencode`), Takopi warns
the user and runs compact without the supplied instructions.

## Multi-message instructions (prompt batching)

When [prompt batching](long-telegram-prompts.md) is enabled, you can split
long `/compact` instructions across several Telegram messages:

```
/compact preserve the following:
- the test plan in tests/
- the API contract in src/api.py
- decisions about the database schema
```

Each message is sent as a separate Telegram message. Takopi assembles them
into one `/compact` instruction before dispatching. The debounce window
(default 0.75s) waits for all chunks to arrive.

## Important notes

- **`/compact` never starts a new session.** It always operates on an existing
  resume token. If no session is found, it errors instead of creating one.
- **`/compact` serializes with active runs.** If a run is in progress on the
  same session, the compact job queues behind it on the same
  `ThreadScheduler`. The compact runs only after the active run completes.
- **`agy` is handoff-only.** Antigravity has no verified true compact command.
  `/compact` on `agy` generates a handoff summary for the next agent turn — it
  does not reduce context. The summary explicitly states it is not real
  compaction.
- **`/compact` does not change the stored session token.** The chat/topic
  session binding remains the same after compaction.

## Errors

| Error message | Cause |
|---------------|-------|
| `no active session to compact. Reply to a Takopi progress/final message, or send a normal prompt first.` | No resume token found (no reply, no stored session, no active run). |
| `<engine> does not support compact.` | Runner returns `CompactSupport(mode="none")`. |
| `<engine> compact instructions are not supported yet; running compact without the supplied instructions.` | Instructions were supplied but the runner does not accept them. |
