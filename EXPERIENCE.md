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

## 2026-08-04: Compact production failure investigation (omp session)

- Root causes verified, in user-impact order: (1) the uv-tools install at
  %APPDATA%/uv/tools/takopi/Lib/site-packages/takopi was stale (2026-08-02)
  despite a believed rebuild - file dates in site-packages are the source of
  truth, not the install command exit code; (2) the ACP compact path is a
  test-only stub (no production transport; omp/grok never override
  create_acp_client; _resolve_transport raises); (3) AcpCompactMixin.compact()
  converts failures into CompletedEvent(ok=False) events which run_compact_job
  discards - total silence for success and failure; (4) /compact <instructions>
  was routed as a plain prompt by the prompt batcher (fixed in 4669620).
- The 4669620 implementation passed tests with injected FakeAcpTransport, which
  masked the missing production transport. Tests with injected fakes must be
  paired with one production-path assertion (no transport override) before a
  feature is declared done.
- Two python.exe takopi instances were observed with identical start times;
  duplicate pollers split get_updates and cause intermittent "nothing happens"
  reports. Verify a single instance after every (re)start.
- Process evidence beat process claims: the bridge restarted after the commit
  but still executed the old build because the installed artifact never
  changed.
## 2026-08-04: Compact production-failure gap closure

- Swapping a base-class import on the same file line as another import
  consumed the neighboring `get_run_options` import silently (omp.py). The
  `CUT 23.=23` removed the entire line, not just the `AcpCompactMixin` symbol.
  When cutting an import line that shares a file with other imports, always
  re-read the file afterward and verify no neighboring imports were lost.
- The edit-tool `PUT N.=N:` replaces the target line. When using it to change
  a class declaration, the body line immediately below (e.g. `engine: EngineId`)
  can be silently consumed if it was on the next line. Always re-read after a
  `PUT N.=N:` to confirm the surrounding lines survived.
- `HandoffCompactMixin` with a class-level `compact_handoff_note` field lets
  each runner customize the note without duplicating `compact_support()` and
  `compact()` in every class. Prefer one shared mixin over inline copies.
- `run_compact_job` must consume the terminal `CompletedEvent` and report
  honest status. Discarding events via `async for _event in runner.compact():
  pass` is total failure silence — success and failure look identical to the
  user. Always inspect the `CompletedEvent.ok` field and surface it.
- Ack-on-enqueue is essential for perceived latency: without it, the user
  sends `/compact` and waits seconds with no feedback before the runner
  produces output. A one-line ack ("compacting…" / "creating handoff summary…")
  closes the feedback gap.
- Tests that inject `FakeAcpTransport` and assert `mode == "acp"` become
  incorrect when the production path switches to handoff. When migrating a
  runner's compact mode, update both the support-mode tests and the
  delegation tests in the same commit.

## 2026-08-05: Handoff-as-new-session compact flow

- Pre-existing `tg.start_soon(handle_compact_confirm, ..., confirmed=True)` bug
  in loop.py was masked because no test exercised the compact confirm callback
  through `run_main_loop`. When adding tests that yield `TelegramCallbackQuery`
  in the poller, this bug surfaced. `start_soon` does not accept kwargs — always
  use `functools.partial` for keyword arguments.
- The approval gate unifies `handoff_only` and `none` engines into one code
  path (D1 approved). Both show an approval card; the only difference is the
  disclaimer text. Do not branch on `mode == "none"` separately — check
  `support.true_compaction` to gate.
- `run_handoff_job` phase 2 relies on `run_job` wrapping
  `scheduler.note_thread_known` internally, which writes the new `ResumeToken`
  to `chat_session_store` on the `StartedEvent`. No explicit store update is
  needed — the routing flip is automatic. This is the verified mechanic from
  the plan.
- The summary echo (D2) must carry the FULL summary in the seed prompt but
  only a TRUNCATED version to the user display. `prepare_telegram_multi`
  with `MAX_BODY_CHARS` handles the split; the seed prompt is never truncated.
- Testing the callback flow through the poller requires yielding a
  `TelegramCallbackQuery` with `message_id` matching the confirmation card's
  send-assigned ID. `FakeTransport._next_id` starts at 1, so the first `send`
  gets `message_id=1` — the callback `_cb(message_id=1)` targets it.
- The "cancelled" text from a declined callback appears in `transport.edit_calls`,
  not `transport.send_calls`. Always check both when asserting on callback
  outcomes.
