# Long Telegram prompts

Sometimes a prompt is longer than one comfortable message: you paste a stack
trace in several parts, or type a `/codex` instruction and then send the body
as a follow-up. Takopi can combine those messages into one prompt.

## How it works

When prompt batching is enabled (default), consecutive **text-only** messages
are grouped into one prompt if all of these hold:

- same chat;
- same topic/thread (or none);
- same sender;
- same reply target (`reply_to_message_id`);
- each message arrives within `prompt_batch_debounce_s` (default `0.75s`) of the
  previous activity;
- the message is text-only: not a control command, not a forwarded-only
  message, not a voice note, document, or media album.

The assembled prompt then goes through the normal pipeline: directive parsing,
trigger checks, session resume, and queueing. One batch is exactly one job -
never several queued runs.

## Examples

### Split engine directive

```
/codex refactor this module
Preserve public API.
Add tests before code.
```

becomes one run:

```
codex  -  refactor this module

Preserve public API.
Add tests before code.
```

### Pasted stack trace

```
Explain this stack trace:
<part 1>
<part 2>
```

### Plan / goal prompts

```
/plan build the API
more details here
```

```
/goal all tests pass
also lint clean
```

Both chunks are one plan-mode / goal-mode run.

## What is never batched

- Control commands: `/cancel`, `/new`, `/ctx`, `/agent`, `/model`,
  `/reasoning`, `/trigger`, `/queue`, `/file`, `/topic`.
- Bare `/plan` and bare `/goal` (sticky/help forms).
- Voice notes, documents, media albums, forwarded-only messages.
- Messages from a different sender, chat, topic, or reply target.

Forwarded messages that arrive right after a batched prompt are still attached
to it (like the `forward_coalesce_s` behavior for single prompts).

## Configuration

Under `[transports.telegram]`:

```toml
prompt_batch_enabled = true      # master switch
prompt_batch_debounce_s = 0.75   # quiet window; 0 disables batching
prompt_batch_max_messages = 8    # flush immediately at this many chunks
prompt_batch_max_chars = 120000  # upper bound on the assembled prompt
prompt_batch_separator = "blank_line"  # or "newline"
```

`prompt_batch_max_chars` is an upper bound on the assembled prompt. If adding
the next message would exceed it, Takopi flushes the current batch first and
starts a new prompt batch with the new message.

Set `prompt_batch_debounce_s = 0` (or `prompt_batch_enabled = false`) for
strict one-message-per-prompt behavior.
