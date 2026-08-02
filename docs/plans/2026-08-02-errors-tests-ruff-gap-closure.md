# Takopi Error, Test, and Ruff Gap-Closure Plan

## Summary

Close the failures recorded in `D:/Projects/takopi/20260801-errors-unfixed.md`, reconcile every current pytest failure with the actual runner and Telegram contracts, and leave `ruff check .` clean. The primary runtime defect is the Telegram outbox lifecycle: `TelegramOutbox.ensure_worker()` manually enters an AnyIO task group in the task that first sends a message, while `TelegramClient.close()` exits that group from the main-loop cleanup task. AnyIO requires cancel scopes to be entered and exited by the same task, which is why polling cancellation ends in `RuntimeError`.

Long Telegram prompt batching and compact runner support are existing features and remain in scope only for regression compatibility. Their behavior must not be weakened to make tests pass.

```text
polling cancelled
      |
      v
run_main_loop finally (shielded cleanup)
      |
      v
transport.close -> TelegramClient.close -> TelegramOutbox.close
      |
      X  task-group scope owned by an earlier sender task

fixed lifecycle:
single lifecycle owner starts worker -> stop signal -> owner exits task group
      |
      v
transport closes without cross-task cancel-scope exit
      |
      v
pytest contracts + Ruff clean
```

## Current Evidence and Boundaries

- `20260801-errors-unfixed.md` contains the shutdown traceback at `src/takopi/telegram/loop.py:2585`, followed by separate `agy` subprocess exits with `rc=1`; do not classify those as one failure without reproducing them independently.
- `src/takopi/telegram/backend.py` already has no custom SIGINT handler. The previous fix addressed one source of cancel-scope corruption but did not repair the outbox ownership violation.
- `src/takopi/telegram/loop.py` shields transport cleanup, which is correct for allowing cleanup during cancellation, but shielding cannot make an AnyIO task group safely exit from the wrong task.
- `src/takopi/telegram/outbox.py` is the defect boundary: it calls `await anyio.create_task_group().__aenter__()` in `ensure_worker()` and `await self._tg.__aexit__(...)` in `close()`.
- The current Ruff baseline has five findings: two `UP035` import migrations in `scripts/onboarding_preview.py`, one unused import in `tests/test_outbound_files.py`, and three `E402` imports in `tests/test_plan_goal_modes.py`.
- Preserve the existing dirty worktree. Do not restore deleted scratch files or generated caches, and do not edit installed files under `site-packages`.

## Implementation Changes

### 1. Establish a reproducible baseline

Before modifying code, run and record:

```powershell
Set-Location -LiteralPath 'D:\Projects\takopi'
uv run pytest -q --no-cov
uv run pytest -q
uv run ruff check .
```

Capture the exact failing node IDs, traceback roots, coverage result, and Ruff diagnostics. Run the focused shutdown/outbox, compact, prompt-batch, runner-contract, and Telegram integration groups separately so a full-suite timeout or Windows-only failure cannot hide the causal result.

### 2. Repair Telegram outbox task ownership

Use one explicit lifecycle owner for the outbox worker. The implementation must keep the existing enqueue/coalescing/rate-limit behavior and must not create a new worker per message.

- Remove the cross-task manual `TaskGroup.__aenter__()`/`__aexit__()` pattern from `TelegramOutbox`.
- Start the worker inside a task group owned by the Telegram client/transport lifecycle, or introduce an equivalent owner task whose only responsibility is to enter, run, and exit that group in the same task.
- Make shutdown idempotent. It must signal the worker to stop, resolve/fail pending operations, wait for worker termination, and close the underlying HTTP client exactly once.
- Keep `run_main_loop` cleanup shielded and preserve cancellation propagation after transport cleanup.
- Preserve direct `TelegramClient` use in onboarding and tests through a small, documented lifecycle-compatible API. Existing call sites must not be left with an unstarted worker or an unclosed task group.
- Ensure cancellation while an outbox request is in flight cannot strand `OutboxOp.done`, leave `_pending` entries unresolved, or restart a closed worker.
- Do not “fix” the exception by suppressing `RuntimeError`, skipping `__aexit__`, or editing AnyIO in `site-packages`; those approaches leak task-group state and only move the crash.

### 3. Add shutdown and outbox regression coverage first

Write failing tests before the implementation change, following the repository TDD requirement. Add coverage for:

- a request that starts the outbox worker, followed by cancellation of the polling/main-loop task, completes cleanup without a cancel-scope mismatch;
- `TelegramClient.close()` called from a different task than the task that enqueued the first request;
- repeated `close()` calls, close with no worker, close with pending operations, and close while a request is blocked;
- every pending waiter is resolved during shutdown;
- the underlying `BotClient.close()` is called once and only after the outbox worker has stopped;
- ordinary queue behavior still coalesces edits, honors priorities/rate limits, retries `RetryAfter`, and rejects new work after close;
- the existing `run_main_loop` shielded cleanup remains effective when the poller raises `CancelledError`.

Prefer a deterministic fake bot and AnyIO events over sleeps. Assert the absence of the exact error text from the report and assert worker/task completion, not merely that an exception was swallowed.

### 4. Reconcile all pytest failures against contracts

After the shutdown tests expose the lifecycle behavior, run the full suite and triage each failure into one of three categories:

1. **Implementation regression:** repair source behavior and add a focused regression test.
2. **Intentional contract change:** update the stale test and the relevant specification/config documentation, with an assertion for the new behavior.
3. **Environment-only failure:** isolate it with an explicit Windows marker or fixture and document the prerequisite; do not relax production contracts or delete the test.

Audit the following contracts explicitly because compact and prompt batching were recently added:

- Runner event sequence remains exactly `StartedEvent -> 0..N ActionEvent -> CompletedEvent`, with `CompletedEvent` last and matching the started resume token.
- Compact always reuses an existing `ResumeToken`, never starts a session, never sends `/compact` over ACP unless `compact` is advertised, and preserves the per-resume lock.
- `agy` remains a handoff summary, not true compaction.
- Codex drops unsupported compact instructions with a user-visible warning; OpenCode does the same for its native API mode.
- Rapid Telegram text messages combine only when their batching key matches, preserve order, and dispatch once; control commands, media, voice, and unrelated chat/thread/sender/reply keys remain isolated.
- Batch flushing, compact jobs, runner jobs, and shutdown do not violate the scheduler/session lock or strand tasks.
- Telegram response splitting retains all content, respects paragraph/sentence boundaries where possible, and keeps the configured inter-message delay at or above 100 ms.

Use real behavioral tests for these paths. Do not replace assertions with source-string checks except for the existing backend SIGINT regression guard where source structure is the intended contract.

### 5. Remove the five Ruff findings with narrow edits

Apply only the required lint changes, then run Ruff again:

- `scripts/onboarding_preview.py`: import `Iterable` and `Iterator` from `collections.abc`.
- `tests/test_outbound_files.py`: remove the unused `write_plan_auto_file` import, unless baseline execution proves the import is required for an intentional side effect; if so, replace it with an explicit side-effect mechanism and document why.
- `tests/test_plan_goal_modes.py`: move the three imports currently at lines 348-350 above executable module-level statements, or isolate the intentional late import inside the test/function that needs it. Preserve the test’s import isolation purpose if that is why the imports are delayed.

Do not use a blanket Ruff ignore for `E402`, `F401`, or `UP035`. Run `uv run ruff check .` and `uv run ruff format --check .`; if formatting is needed, apply it only after the behavioral fixes and review the diff for unrelated churn.

### 6. Verify and document the final state

Run these checks in order:

```powershell
Set-Location -LiteralPath 'D:\Projects\takopi'
uv run ruff check .
uv run ruff format --check .
uv run pytest -q --no-cov tests/test_shutdown.py tests/test_telegram_queue.py tests/test_telegram_client.py
uv run pytest -q --no-cov tests/test_compact_core.py tests/test_compact_event_invariants.py tests/test_acp_client.py tests/test_acp_compact_runners.py tests/test_telegram_compact_command.py tests/test_telegram_prompt_batch.py tests/test_telegram_prompt_batch_integration.py
uv run pytest -q --no-cov
uv run pytest -q
```

If the full suite has pre-existing Windows-only failures, compare against a clean baseline and report each remaining node ID and reason. The acceptance condition is zero new failures, zero unclassified failures, zero Ruff findings, no cancel-scope traceback during a controlled shutdown, and no regression in compact/batching/splitting contracts.

Update the relevant shutdown, Telegram transport, and compact documentation with the actual lifecycle rule and user-visible limitations. Keep `20260801-errors-unfixed.md` as the historical report unless a later cleanup request explicitly authorizes removing it.

## Assumptions

- This plan covers implementation and verification; the current turn remains read-only except for creating this plan artifact.
- The canonical fix will remain in `src/takopi`, not in the UV-installed copy or AnyIO’s `site-packages`.
- Existing compact and long-prompt behavior is the compatibility baseline; no feature rollback is acceptable as a way to reduce test failures.
- TDD is mandatory: each behavior change gets a failing regression test before source changes.
- No commit, package rebuild, or global installation is required for the implementation plan; after source changes, the editable `src/` checkout is verified with the project’s test commands.

[[takopi-send: D:\Projects\takopi\docs\plans\2026-08-02-errors-tests-ruff-gap-closure.md]]
