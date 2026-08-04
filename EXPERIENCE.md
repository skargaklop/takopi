# Investigation Notes

## 2026-08-01: Telegram shutdown crash and prompt batching audit

- The read-only investigation found the crash path in the manually added outer
  `CancelScope` in `src/takopi/telegram/backend.py`, triggered while nested
  Telegram task groups and debounce scopes unwind after SIGINT.
- The working tree contained the prompt-batching plan, helper/docs, and tests,
  but not the runtime settings, bridge, loop, or backend wiring. The claimed
  tests therefore failed at collection rather than proving the feature.
- A shell invocation initially ignored its requested working directory; using
  explicit `Set-Location` avoided inspecting the wrong tree.
- The investigation could not run tests under its read-only constraint and
  reported a different interpreter version than the main environment. Verify
  runtime claims in the active UV tool and project environments.

## 2026-08-01: Prompt batching topic verification subagent

- The forked `gpt-5.6-terra` subagent could not reproduce the main-session
  topic test failures and therefore made no edits. Main-session verification
  remained authoritative.
- The worktree was partially staged/dirty, so verification had to avoid
  staging, reverting, or duplicating existing fixes.
- Cancellation remains sensitive: do not restore stored `CancelScope` objects
  in `PromptInputBatcher` and do not add an outer `CancelScope` around
  `run_main_loop`.

## 2026-08-04: Compact dispatch robustness implementation

- **Edit tool `PUT N.=N:` replaces the target line.** When inserting a new import in a multi-line `from X import (...)` block, `PUT 54.=54:` with body `+    handle_compact,` **replaces** line 54 instead of inserting before it. This silently consumed `handle_ctx_command`, `parse_slash_command`, `should_handle_as_meta_command`, `STEER_CALLBACK_DATA`, and `COMPACT_DECLINE_CALLBACK_DATA` across multiple edits. Each was caught by ruff/tests, but the pattern is error-prone. Mitigation: re-read the block after each insertion, or use `PUT >N:` (insert after) when the target line must survive.
- **`PUT N.=N:` on a frozenset element also replaces.** Adding `"compact"` to `CONTROL_COMMANDS` via `PUT 31.=31:` replaced `"file"` instead of appending. Caused a pre-existing test failure. Same root cause as above.
- **`TelegramLoopState` with `slots=True` + `dataclass`**: adding a field requires both the class definition AND the constructor call to be updated. Missing `seen_messages_order` in either location causes `AttributeError`.
- **`anyio.TaskGroup.start_soon` does not accept kwargs.** Positional args only. Use `functools.partial` for keyword arguments.
- **`CompactSupport` dataclass requires `true_compaction: bool`** as a positional argument — not visible from the plan's text. Test doubles must include it.
- **`send_plain` puts `reply_markup` in `RenderedMessage.extra`**, not in `SendOptions`. Tests must check `message.extra["reply_markup"]`, not `options.reply_markup`.
