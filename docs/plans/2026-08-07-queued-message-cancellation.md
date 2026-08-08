# Task 21 Reliable Queued-Message Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Telegram’s queued-message lifecycle truthful and race-safe: a prompt waiting behind an active run shows queue controls, Cancel removes exactly that pending job, claim transfers the progress message to the new active run, stale/repeated callbacks are harmless, `/queue` reports scheduler truth, and failures never silently lose prompts.

**Architecture:** Keep `ThreadScheduler` engine-agnostic and make it the sole authority for pending/claimed state. Preserve exact `ResumeToken(engine, value)` identity; Task 22 already removed OMP truncation, so no new canonicalization layer is justified. Add explicit scheduler lifecycle results and injected claim/failure observers so Telegram presentation follows state transitions instead of predicting them with `is_busy()`. Continue using progress-message references as cancellation identities. Queue cancellation removes only a pending job; after atomic claim, the worker—not the queued-cancel path—owns the job and its existing progress reference.

**Tech stack:** Python 3.14, AnyIO locks/events/task groups, Telegram transport/presenter, pytest-anyio, `ScriptRunner`, structlog, Ruff, ty, Zensical.

---

## Context and reviewed-draft decisions

### Verified current behavior

- `src/takopi/scheduler.py:44-227` stores pending jobs in `_pending_by_thread`, indexes cancellable jobs in `_queued_by_progress[(chat_id, progress_message_id)]`, and serializes queue operations with one AnyIO lock.
- `_thread_worker()` correctly waits on `_busy_until` before popping a pending job. The draft’s statement that it pops before waiting is stale. The real race begins after the atomic pop: `_queued_by_progress` is removed before `run_thread_job()`/`handle_message()` edits the card to `starting` and registers the new `RunningTask`.
- `enqueue()` returns no disposition. `src/takopi/telegram/loop.py:2122-2148` samples `is_busy()`, sends `queued` or `starting`, then enqueues. The sample, send, and enqueue are not one state transition; enqueue exceptions have no visible recovery and can leave a sent card claiming work exists.
- `TelegramPresenter.render_progress()` already gives `queued` cards `STEER_CANCEL_MARKUP` when steerable and `CANCEL_MARKUP` otherwise. No presenter change is currently required. A terminal `cancelled`/`steered` label clears the keyboard.
- `handle_callback_cancel()` first resolves the exact progress reference in `running_tasks`, then tries `scheduler.cancel_queued()`. Pending cancellation is already isolated from active tasks. The indistinguishable `None` result makes claimed, previously cancelled, and unknown callbacks all report the same misleading message.
- `handle_callback_steer()` atomically claims the queued job before awaiting runner control and requeues it on steering failure. This contract must remain intact.
- `/queue` resolves a `ResumeToken`, then reads `list_queued_for_thread()` and `is_busy()`. Pending count semantics are correct; a claimed/running job is busy, not queued. Accuracy depends on all paths using the same exact token.
- `run_thread_job()` delegates prompt failures to `run_engine()`/`handle_message()`, which renders ordinary runner errors. Exceptions before or outside that error-rendering boundary reach `_thread_worker()`, which only logs `scheduler.job_failed`; that is a silent user-visible loss.
- Task 22 is complete: OMP preserves full session IDs. The draft’s truncated/full OMP key canonicalization and its associated regression are obsolete and must be removed rather than institutionalized.

### Locked decisions

1. **Exact thread identity:** `ThreadScheduler.thread_key(ResumeToken)` remains the only queue key. Do not normalize, abbreviate, case-fold, alias, or otherwise rewrite engine/session values. Routing code must pass the resolved token unchanged to `note_thread_known()`, enqueue, cancellation metadata, and `/queue`.
2. **Pending identity:** `(chat_id, progress_message_id)` remains the cancellation key. Do not cancel by chat, engine, session, position, or prompt text.
3. **Explicit enqueue disposition:** `enqueue()`/`enqueue_resume()` return an enum-like result indicating `QUEUED` or `CLAIMABLE` based on scheduler state while holding the lock. Telegram may initially render optimistically, but must reconcile using this result; claim notification remains the final authority.
4. **Atomic claim boundary:** The worker removes the job from both pending indexes under the lock. It then invokes an injected `on_job_claimed(job)` observer before `_run_job(job)`. Telegram uses that observer to edit the same progress card from `queued` to `starting`; the ordinary runner path then replaces/registers that exact reference.
5. **Cancel result:** `cancel_queued()` returns a discriminated `CANCELLED | ALREADY_CLAIMED | NOT_FOUND` result, with the job only for `CANCELLED`. Keep a bounded claimed-progress record only until the corresponding job finishes; do not create an unbounded tombstone set. A repeated callback after a successful cancellation may resolve as `NOT_FOUND`, but remains a no-op with an idempotent acknowledgement.
6. **No cross-job cancellation:** `ALREADY_CLAIMED` never searches for or cancels “the active task on the same thread.” Before `running_tasks` owns that exact progress reference, answer `already started`; once it owns the exact reference, the existing active-run path may cancel that newly claimed run. Never cancel the predecessor or another message by matching only its resume token.
7. **Failure ownership:** Add an injected `on_job_failed(job, exc)` observer. `_thread_worker()` calls it after logging an unexpected `_run_job` exception, then continues FIFO. Telegram edits that job’s existing progress card to a terminal error state. Observer failure is logged separately and does not stop the worker.
8. **Transactional enqueue failure:** If task-group startup fails after insertion, roll back the exact job, progress index, and active-thread marker under the lock before re-raising. Telegram catches enqueue failure, edits the already-sent card to terminal `error` with cleared controls, and includes a bounded prompt preview plus safe error text. It must not say `queued` after failure.
9. **Queue semantics:** `/queue`’s `queued: N` counts only pending deque entries. A claimed job is removed from `N`; while it runs, `busy: yes`. Do not add an “in-flight queued” count or engine-specific hints.
10. **All-engine coverage:** Scheduler logic contains no engine allowlist. Integration tests derive cases from `cfg.runtime.engine_ids`, including a runtime-discovered synthetic plugin engine, and use fake runners so no local CLI is required.
11. **Resume-not-ready:** The draft’s proposed fallback enqueue is unsafe because no stable `ResumeToken` exists. Keep the existing honest “resume token not ready” response unless Task 21 reproduction proves it caused the reported queued card; do not invent a thread identity.
12. **Markup scope:** Preserve active-run cancellation and Codex steering. Change `bridge.py`/presenter code only if the faithful transport test disproves the existing markup contract.

## File map

### Production

- `src/takopi/scheduler.py` — enqueue/cancel result types, bounded claimed state, atomic rollback, claim/failure observers, and worker lifecycle.
- `src/takopi/telegram/loop.py` — observer wiring, enqueue reconciliation, visible enqueue/worker failure rendering, and exact progress-reference reuse.
- `src/takopi/telegram/commands/cancel.py` — discriminated cancel handling and idempotent callback text.
- `src/takopi/telegram/commands/queue_cmd.py` — only if tests expose a token-resolution or state-snapshot defect; do not change correct pending-count semantics speculatively.
- `src/takopi/telegram/bridge.py` / `src/takopi/presenter.py` — expected no production change.

### Tests and docs

- Create `tests/test_scheduler_queue.py` for deterministic scheduler state/race contracts.
- Create `tests/test_telegram_queue.py` for cancellation presentation and callback routing.
- Extend `tests/test_telegram_prompt_batch_integration.py` for faithful main-loop queue/control behavior across runtime engines.
- Extend `tests/telegram_fakes.py` only with reusable synchronization/callback helpers required by those integration tests.
- Update `docs/reference/commands-and-directives.md`, `changelog.md`, and the Task 21 completion record in `ROADMAP.md` after verification.
- Preserve `docs/plans/2026-08-07-queued-message-cancellation.md` as the historical investigation draft; do not implement its stale OMP canonicalization or pop-before-wait claims.

## Critical anchors

1. `src/takopi/scheduler.py:44-180,188-227` — lock-owned pending/index transitions and worker claim/error path.
2. `src/takopi/telegram/loop.py:1332-1435,1917-1941,2052-2148` — queued card rendering, scheduled job execution, and enqueue TOCTOU.
3. `src/takopi/telegram/commands/cancel.py:19-99,102-166` — exact-ref active cancel, pending cancel, and steer claim/requeue.
4. `src/takopi/telegram/bridge.py:42-55,79-102,139-147` — existing queue controls and terminal keyboard clearing.
5. `src/takopi/runner_bridge.py:435-505` — progress-card replacement and exact-ref `RunningTask` ownership.

---

## Task 1: Freeze scheduler lifecycle contracts with failing tests

**Files:**
- Create: `tests/test_scheduler_queue.py`
- Reference: `src/takopi/scheduler.py`

- [ ] **Step 1: Add deterministic queue and ordering tests**

Use `anyio.Event` barriers, never sleeps, to prove:

- a known busy token keeps two jobs pending and addressable by their distinct progress references;
- cancelling the second removes only the second while the first remains queued;
- releasing the active predecessor runs remaining jobs FIFO;
- cancelled jobs never reach `run_job`;
- same session value under different engines and different session values under one engine remain isolated.

- [ ] **Step 2: Add cancel-before/after-claim race tests**

Pause the worker in `on_job_claimed` after the atomic pop. Assert:

- before claim: `cancel_queued()` returns `CANCELLED` with the exact job;
- after claim: it returns `ALREADY_CLAIMED`, does not mutate another pending job, and does not invoke cancellation on any running task;
- after job completion: claimed tracking is released and a stale lookup returns `NOT_FOUND`;
- a repeated successful-cancel callback is a harmless `NOT_FOUND` and no job runs twice.

- [ ] **Step 3: Add failure and rollback tests**

Assert an unexpected `run_job` exception invokes `on_job_failed` exactly once and the next pending job still runs. Use a task-group fake whose `start_soon()` raises to prove enqueue rolls back the deque, progress index, and active marker before re-raising; a later valid enqueue on the same token must start normally.

- [ ] **Step 4: Run the RED gate**

```text
PYTHONUTF8=1 uv run pytest -q --no-cov tests/test_scheduler_queue.py
```

Expected before implementation: missing result/observer contracts and rollback assertions fail.

**Commit:** `test: define queued job lifecycle races`

---

## Task 2: Implement scheduler-owned transitions

**Files:**
- Modify: `src/takopi/scheduler.py`
- Test: `tests/test_scheduler_queue.py`
- Verify: `tests/test_compact_event_invariants.py`

- [ ] **Step 1: Add typed public results and observers**

Define small enum/dataclass contracts rather than string literals:

- `EnqueueDisposition.QUEUED | CLAIMABLE`;
- `CancelQueuedStatus.CANCELLED | ALREADY_CLAIMED | NOT_FOUND`;
- `CancelQueuedResult(status, job=None)` with construction enforcing that only `CANCELLED` carries a job;
- `JobClaimed` and `JobFailed` async callback aliases, defaulting to no-op observers for non-Telegram uses.

Keep `claim_queued()`’s existing `ThreadJob | None` contract for Codex steering; it is a deliberate consumer claim, not a cancel query.

- [ ] **Step 2: Make enqueue atomic and reversible**

While holding `_lock`, insert the job, progress index, and active marker and determine whether a predecessor/busy event means the new job is pending. Start a worker only for a newly active thread. If `start_soon()` raises, reacquire the lock and remove only this insertion plus its marker when still owned by this enqueue, then re-raise. Return the disposition.

Do not await transport callbacks while holding `_lock` and do not allocate copies of the queue to determine disposition.

- [ ] **Step 3: Track only active claims**

At worker pop, move a progress key from `_queued_by_progress` into `_claimed_by_progress`. Invoke `on_job_claimed(job)` outside the lock, then `_run_job(job)`. In `finally`, remove that exact claimed key even if claim notification, job execution, or failure notification raises. `cancel_queued()` checks pending first, then claimed, then absent.

Steer claims must remove pending state without entering worker-claimed state. `requeue_front()` restores the pending index after steer failure.

- [ ] **Step 4: Surface unexpected job failures without stopping FIFO**

Retain `scheduler.job_failed` logging. Call `on_job_failed(job, exc)` once outside the lock; catch/log observer failure under a distinct event, then continue. Cancellation exceptions must retain normal AnyIO cancellation semantics and must not be converted to job failures.

- [ ] **Step 5: Run focused GREEN checks**

```text
PYTHONUTF8=1 uv run pytest -q --no-cov tests/test_scheduler_queue.py tests/test_compact_event_invariants.py
PYTHONUTF8=1 uv run ruff check src/takopi/scheduler.py tests/test_scheduler_queue.py
PYTHONUTF8=1 uv run ty check src/takopi/scheduler.py tests/test_scheduler_queue.py
```

**Commit:** `fix: make scheduler queue transitions explicit`

---

## Task 3: Make Telegram cancellation idempotent and exact

**Files:**
- Create: `tests/test_telegram_queue.py`
- Modify: `src/takopi/telegram/commands/cancel.py`
- Verify: `tests/test_telegram_bridge.py`

- [ ] **Step 1: Add callback-routing tests before implementation**

Using `FakeTransport`, `FakeBot`, and exact `MessageRef` keys, cover:

- pending Cancel returns `dropped from queue.`, edits the same card to `cancelled`, and clears `inline_keyboard`;
- only the selected queued job is removed at queue depth greater than one;
- repeated/stale callback is acknowledged as already absent and causes no second edit or run;
- `ALREADY_CLAIMED` answers `already started.` without setting the predecessor’s or another thread’s `cancel_requested` event;
- if the exact progress reference has become a `RunningTask`, the existing active-run path sets only that task’s cancellation event and answers `cancelling...`;
- typed `/cancel` and callback Cancel share the same scheduler result semantics;
- Codex steer/cancel markup and `claim_queued()`/requeue-on-steer-failure behavior stay unchanged.

- [ ] **Step 2: Consume discriminated scheduler results**

Refactor only the pending branch in `handle_cancel()` and `handle_callback_cancel()`. Centralize result-to-action logic enough to keep typed and callback behavior consistent without coupling scheduler code to Telegram. `CANCELLED` performs one terminal edit; `ALREADY_CLAIMED` reports that the job started; `NOT_FOUND` reports that it is no longer queued. Do not fall back to resume-token matching.

- [ ] **Step 3: Run focused checks**

```text
PYTHONUTF8=1 uv run pytest -q --no-cov tests/test_telegram_queue.py tests/test_telegram_bridge.py
PYTHONUTF8=1 uv run ruff check src/takopi/telegram/commands/cancel.py tests/test_telegram_queue.py
PYTHONUTF8=1 uv run ty check src/takopi/telegram/commands/cancel.py tests/test_telegram_queue.py
```

**Commit:** `fix: make queued cancellation exact and idempotent`

---

## Task 4: Bind Telegram cards to scheduler transitions

**Files:**
- Modify: `src/takopi/telegram/loop.py`
- Modify: `tests/test_telegram_queue.py`
- Verify: `src/takopi/telegram/bridge.py`

- [ ] **Step 1: Add presentation-transition tests**

Cover the direct helpers with a transport that captures every send/edit:

- a truly pending job ends with label `queued` and cancel-only markup for a non-steerable runner;
- a steerable pending job preserves steer+cancel markup;
- claim edits that same message reference to `starting` before runner execution owns it;
- a prompt that is immediately claimable does not remain labelled `queued`;
- enqueue failure edits the sent card to terminal `error`, clears controls, includes a bounded prompt preview and safe exception detail, and leaves no scheduler entry;
- unexpected worker failure edits that job’s card to terminal `error`; the following job still transitions and runs.

Assert transport payloads, not formatter source strings.

- [ ] **Step 2: Add reusable queue card rendering helpers**

Keep `_send_queued_progress()` for the initial card. Add narrow helpers to edit a `ThreadJob.progress_ref` to `starting` or terminal `error` using its stored engine, context, plan, and goal metadata. Extend terminal progress-label recognition to `error` only if the existing final renderer cannot represent this observer failure without creating a second message. Any terminal path must clear markup.

- [ ] **Step 3: Wire scheduler observers at construction**

Construct `ThreadScheduler` with Telegram-local `on_job_claimed` and `on_job_failed` closures. The claim observer edits before execution. The failure observer edits the existing card and includes a bounded, sanitized failure message; it does not requeue because execution may have partially started.

- [ ] **Step 4: Reconcile enqueue outcome and failure**

In `dispatch_prompt_run()`, keep the sent progress reference, await `enqueue_resume()`, and use the returned disposition to reconcile the label. The claim observer wins any later race. Wrap only enqueue/state reconciliation—not runner execution—in `try/except`; render a terminal error on failure and log structured engine/chat/progress/error fields. Never emit a second “queued” acknowledgement.

Apply the same typed return mechanically to the `send_with_resume()` callable contract and compact/handoff enqueue callsites, without changing their user workflows.

- [ ] **Step 5: Run focused checks**

```text
PYTHONUTF8=1 uv run pytest -q --no-cov tests/test_telegram_queue.py tests/test_telegram_bridge.py tests/test_compact_event_invariants.py
PYTHONUTF8=1 uv run ruff check src/takopi/telegram/loop.py src/takopi/telegram/bridge.py tests/test_telegram_queue.py
PYTHONUTF8=1 uv run ty check src/takopi/telegram/loop.py src/takopi/telegram/bridge.py tests/test_telegram_queue.py
```

**Commit:** `fix: synchronize Telegram queue cards with claims`

---

## Task 5: Verify `/queue`, FIFO, and runtime engine isolation end to end

**Files:**
- Modify: `tests/test_telegram_prompt_batch_integration.py`
- Modify: `tests/telegram_fakes.py` only if shared event barriers are needed
- Modify: `src/takopi/telegram/commands/queue_cmd.py` only if tests fail on a real defect

- [ ] **Step 1: Build a faithful multi-runner integration fixture**

Create blocking `ScriptRunner` instances from `cfg.runtime.engine_ids`, not a production engine-name list. Add one synthetic runner through the existing entry-point/plugin fixture so the runtime tuple proves plugin/new-engine coverage. Each runner records prompt, resume token, start, and completion; barriers control claim order deterministically.

- [ ] **Step 2: Exercise the actual main loop and callback dispatch**

For every ID returned by the configured runtime:

1. start one resumable run and wait until `note_thread_known()` establishes busy state;
2. submit two prompts to that exact session;
3. inspect the actual queued `RenderedMessage.extra.reply_markup`;
4. issue `/queue` and assert `busy: yes`, `queued: 2`, and FIFO previews;
5. send a real `takopi:cancel` callback for the second card;
6. assert `queued: 1`, the selected card is terminal/cancelled, and the predecessor is untouched;
7. release the active run and assert only the first queued prompt starts with the exact engine/session token;
8. while it runs, assert `busy: yes`, `queued: 0`;
9. release it and assert no cancelled subprocess invocation occurred.

- [ ] **Step 3: Add engine/session isolation cases**

Queue concurrently for two engine IDs sharing the same session string and for two session strings on one engine. Cancel one progress reference and prove the other queues/orderings are unchanged. This is the required cross-engine guarantee; do not add engine conditionals to production code.

- [ ] **Step 4: Re-test Codex steering semantics**

Run the existing steer integration against the same faithful transport: queued Codex control contains steer+cancel, steer atomically removes one pending job, steer failure restores it to the front, and queued Cancel never interrupts the predecessor.

- [ ] **Step 5: Run integration checks**

```text
PYTHONUTF8=1 uv run pytest -q --no-cov tests/test_telegram_prompt_batch_integration.py tests/test_telegram_queue.py tests/test_telegram_bridge.py
PYTHONUTF8=1 uv run ruff check tests/test_telegram_prompt_batch_integration.py tests/telegram_fakes.py
PYTHONUTF8=1 uv run ty check tests/test_telegram_prompt_batch_integration.py tests/telegram_fakes.py
```

**Commit:** `test: verify queue controls across runtime engines`

---

## Task 6: Document the final queue contract

**Files:**
- Modify: `docs/reference/commands-and-directives.md`
- Modify: `changelog.md`

- [ ] **Step 1: Update queue/cancel documentation**

Document observable semantics only:

- `queued: N` counts pending jobs for the resolved exact engine/session;
- queued cards keep cancel, plus steer only when active turn control exists;
- successful queued cancellation removes one job and clears its controls;
- after claim the card transitions to the active run; stale/repeated callbacks are safe;
- enqueue or scheduler execution failures become visible terminal errors.

Do not document internal maps, OMP-specific identity workarounds, or claim engine-specific queue behavior.

- [ ] **Step 2: Add a changelog entry**

Mention reliable queued Cancel controls, exact per-message cancellation, truthful queue state, and visible failures across runtime-discovered runners.

- [ ] **Step 3: Build documentation**

```text
PYTHONUTF8=1 uv run zensical build --strict
```

**Commit:** `docs: define reliable queued cancellation contract`

---

## Task 7: Final verification and roadmap completion

**Files:**
- Modify: `ROADMAP.md`

- [ ] **Step 1: Run formatting, lint, and typing gates**

```text
PYTHONUTF8=1 uv run ruff format --check .
PYTHONUTF8=1 uv run ruff check .
PYTHONUTF8=1 uv run ty check src tests
```

All must pass without suppressions or configuration weakening.

- [ ] **Step 2: Run lifecycle and full-suite gates**

```text
PYTHONUTF8=1 uv run pytest -q --no-cov tests/test_scheduler_queue.py tests/test_telegram_queue.py tests/test_telegram_prompt_batch_integration.py tests/test_telegram_bridge.py tests/test_compact_event_invariants.py tests/test_subprocess_close.py
PYTHONUTF8=1 uv run pytest -q --no-cov
PYTHONUTF8=1 uv run pytest -q
```

The last command must retain the repository’s 81% coverage gate. `tests/test_subprocess_close.py` is mandatory because worker/cancellation changes must not regress shutdown.

- [ ] **Step 3: Faithful Telegram transport smoke**

The integration fixture is the required automated end-to-end proof: inspect the exact sent message’s inline keyboard, dispatch the callback through the main-loop handler, observe the same card’s terminal edit, and verify the predecessor runner remains blocked. If bot credentials and a consenting test chat are configured, additionally repeat once against live Telegram on OMP and one other configured engine; record it as supplemental, not a CI requirement.

- [ ] **Step 4: Mark Task 21 complete**

Change the heading to `## Task 21: Reliable Queued-Message Cancellation and Cross-Engine Queueing (DONE)` and replace `Plan: TBD` with the implemented root cause, behavior, commit list, and exact verification counts. Do not mark complete until every gate above passes.

**Commit:** `docs: mark Task 21 as DONE in ROADMAP`

---

## Acceptance checklist

- [ ] A genuinely pending Telegram card displays Cancel; steer is present only when turn control exists.
- [ ] Controls remain until atomic claim or cancellation, then the same card changes state.
- [ ] Cancel removes exactly the job keyed by its progress message and never starts it.
- [ ] Cancel-before-claim, cancel-after-claim, stale, and repeated callbacks are deterministic and harmless.
- [ ] A queued callback never cancels the predecessor or another engine/session.
- [ ] Active-run cancellation and Codex mid-turn steering retain current behavior.
- [ ] `/queue` reports exact-token scheduler truth: pending only in `queued: N`, claimed/running as busy.
- [ ] Enqueue rollback and unexpected worker failures produce visible terminal feedback and no silent loss.
- [ ] FIFO continues after cancellation and after a failed job.
- [ ] Tests derive engine cases from runtime discovery and include a synthetic plugin engine.
- [ ] No OMP ID canonicalization, runner allowlist, polling loop, OS-specific primitive, or duplicate scheduler is introduced.
- [ ] Ruff, ty, focused tests, full suite, coverage, documentation build, and subprocess-close gates pass.
