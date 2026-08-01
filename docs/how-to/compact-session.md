# Compacting session context

Long sessions accumulate context. Use `/compact` to reduce it without losing the conversation thread.

## Quick start

Send `/compact` in any chat or topic where Takopi has an active session:

```
/compact
```

You can also pass instructions to focus the compaction:

```
/compact keep the test plan and current blockers
```

Takopi resolves the active session from:

1. The chat/topic's stored session (if any)
2. A reply to a Takopi progress or final message

If no session is found, Takopi replies with guidance.

## What happens

Takopi enqueues a compact job on the same per-thread scheduler as normal prompts. This means:

- **Serialization**: compact waits for any active run on the same thread to finish.
- **No new session**: compact always operates on an existing `ResumeToken`.
- **Same queue**: a compact job is queued behind pending prompts, and vice versa.

## Engine support

| Engine | Mode | True compaction | Instructions |
|--------|------|-----------------|--------------|
| claude | `slash_prompt` | yes | yes |
| pi | `slash_prompt` | yes | yes |
| codex | `slash_prompt` | yes | no |
| opencode | `native_api` | yes | no |
| grok | `acp` | yes | yes |
| omp | `acp` | yes | yes |
| agy | `handoff_only` | no (handoff summary) | yes |

### Slash-prompt compaction (claude, pi, codex)

Takopi sends `/compact [instructions]` as a normal prompt to the runner. The engine's native `/compact` command handles the actual context reduction.

### Native API compaction (opencode)

Takopi calls the OpenCode server's session compact endpoint directly (`POST /api/session/<id>/compact`), then waits for completion.

### ACP compaction (grok, omp)

Takopi connects to the engine's ACP (Agent Client Protocol) stdio interface, initializes, loads/resumes the session, checks that the `compact` command is advertised, and sends `/compact` via `session/prompt`. If the engine does not advertise `compact`, the job fails with a user-visible error.

### Handoff-only (agy)

Antigravity has no verified true compact command. Instead, Takopi sends a handoff-summary prompt that asks the agent to summarize the session for continuation. This is **not real compaction** — the agent is told not to claim that compaction occurred.

## When instructions are not supported

If you pass instructions to an engine that doesn't accept them (e.g., `/compact keep tests` on codex), Takopi warns you and runs compact without the instructions.

## Plugin runners

Third-party runners can implement compaction by providing `compact_support()` and `compact()` methods. See the [plugin API reference](../reference/plugin-api.md#compaction) for details.

Runners without compaction support are handled gracefully — Takopi reports that the engine does not support compact.
