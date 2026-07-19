# Routing & sessions

Takopi supports both **stateless** and **chat** modes for session handling. In stateless mode, each message starts a new session unless you reply to continue. In chat mode, new messages auto-resume the previous session.

## Continuation (how threads persist)

Takopi continues threads using this **priority order** (highest first):

1. **Explicit resume in the user message** (always wins)
   - Engine resume line: `codex resume <id>`, `` `claude --resume <id>` ``, `agy --conversation <id>`, …
   - Universal alias (all engines, including Antigravity/`agy`): `resume <id>`, `--resume <id>`, `-r <id>`, …
   - With engine directive: `/claude resume <id> …`, `/agy resume <id> …`
   - Beats reply footer, reply-to-running, topic store, and chat store.
2. **Reply to an active running progress message** (queue / wait for that thread).
3. **Reply-to-continue** via resume line in the replied-to bot message footer.
4. **Forum topics** (optional) — per-topic stored session (`telegram_topics_state.json`). Reset with `/new`.
5. **Chat sessions** (optional) — `session_mode = "chat"` (`telegram_chat_sessions_state.json`). Reset with `/new`.
6. **New session** when nothing above applies.

Reply-to-continue and auto-resume still work when the user does **not** type an explicit resume.

## Routing (how Takopi picks a runner)

For each message, Takopi:

- parses directive prefixes (`/<engine-id>`, `/<project-alias>`, `@branch`) from the first non-empty line
- attempts to extract a resume token by polling available runners
- if a resume token is found, routes to the matching runner; otherwise uses the configured default engine

## Serialization (why you don’t get overlapping runs)

Takopi allows parallel runs across **different threads**, but enforces serialization within a thread:

- Telegram side: jobs are queued FIFO per thread.
- Runner side: runners enforce per-resume-token locks (so the same session can’t be resumed concurrently).

The precise invariants are specified in the [Specification](../reference/specification.md).

## Related

- [Conversation modes](../tutorials/conversation-modes.md)
- [Chat sessions](../how-to/chat-sessions.md)
- [Commands & directives](../reference/commands-and-directives.md)
- [Context resolution](../reference/context-resolution.md)
