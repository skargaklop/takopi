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
