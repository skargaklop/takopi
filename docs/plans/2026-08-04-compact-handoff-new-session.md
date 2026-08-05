# Handoff-as-New-Session Compact Flow - Implementation Plan

> User directive (2026-08-04): "Session compacted = context reduced. If there
> is no compaction, we write handoff and start the NEW session with this
> handoff with new session id = context reduced! But before handoff the user
> must explicitly approve it - Takopi should send a message with two buttons."
>
> Amends the handoff behavior shipped in `bca5e46` (in-place handoff inside
> the SAME session) and the none-engine flow from
> `4669620`. Roadmap Task 1 requirement 5 is reworded by this plan.
>
> Decisions approved by the user (2026-08-04): D1 = yes (unify `none` engines),
> D2 = yes (echo the summary to the user, truncated).

**Goal:** For engines without native compaction, `/compact` becomes:
explicit user approval (two inline buttons) -> handoff summary in the OLD
session -> NEW session seeded with the summary -> routing switches to the new
session id. Result: actual context reduction, honestly labeled.

**Current vs desired:**

- Current (`bca5e46`): `/compact` on a handoff engine runs immediately,
  appends the summary to the SAME transcript. Context grows; no approval.
- Desired: approval gate first; summary produced in the old session; a NEW
  session (new resume token) is seeded with it; future messages route to the
  new session.

**Verified mechanics this design relies on:**

- `run_job` wraps `on_thread_known` internally
  (`loop.py:1674-1676` -> `wrap_on_thread_known`, `loop.py:1583-1606`), which
  writes the new `ResumeToken` into `topic_store` and `chat_session_store` on
  the run `StartedEvent`. A seed run through `run_job` therefore flips routing
  to the new session id with no extra store code.
- `run_compact_job` (`loop.py:1686-1738`) already consumes runner events and
  holds the terminal `CompletedEvent`; `final_event.answer` is the summary
  capture point.
- The approval infrastructure from `4669620` already exists:
  `pending_compact_confirms` state, `_supersede_pending`,
  `COMPACT_CONFIRM_MARKUP`, `takopi:compact:confirm/decline` callback branch,
  `PendingCompactConfirm` dataclass.

**Flow sketch:**

```text
/compact (reply or selector) on a handoff_only engine session
  |
  v
resolve session (unchanged, 4669620 logic)
  |
  v
approval message: "<engine> cannot compact natively.
  Takopi will: 1) ask the agent for a handoff summary,
  2) start a NEW session seeded with it,
  3) route future messages there.
  The old session stays available but is no longer default."
  [approve handoff] [cancel]        <- two inline buttons
  |
  +-- cancel -> "cancelled", end
  v approve
enqueue ThreadJob(kind="handoff") on the OLD thread key
  |
  v
phase 1: runner.compact(old_token, instructions)
         -> run(handoff_prompt) in OLD session; capture CompletedEvent.answer
         -> failure / empty answer: "compact failed: ...", keep old session
  |
  v
ack: "creating handoff summary for <engine> session..."
  |
  v
phase 2: run_job(seed_prompt(summary), resume_token=None,
                  engine_override=old engine, same thread/session keys)
         -> new session id appears; stores flip routing to it (automatic)
         -> progress renders to the user like a normal run
  |
  v
completion message:
  "handoff complete - new <engine> session started with the summary.
   Send your next message to continue. Do not reply to pre-handoff
   messages; they still point to the old session."
```

## Decisions (approved by the user, 2026-08-04)

- **D1 - unify `none` engines into this flow: APPROVED.** The same
  approval + migrate flow applies; the confirmation text keeps the extra
  disclaimer ("this agent does not support compaction at all"). This replaces
  the `4669620` behavior (plain-prompt handoff in the SAME session) and keeps
  one code path (DRY). `PendingCompactConfirm` is unchanged.
- **D2 - echo the summary to the user: APPROVED (truncated).** After
  completion, send the summary as a separate message via the existing
  markdown-split path (`prepare_telegram_multi`, `MAX_BODY_CHARS`), first
  chunk truncated with an ellipsis note when oversized. Transparency for what
  was carried over; the seed prompt always carries the FULL summary
  (never truncated).

## Tasks (TDD)

### Task A - Failing tests (RED)

Extend `tests/test_telegram_compact_dispatch.py`:

1. handoff engine `/compact` reply -> approval message WITH inline keyboard;
   nothing runs yet (regression vs `bca5e46` immediate execution).
2. approve -> phase 1: `run()` called with `handoff_prompt(instructions)` on
   the OLD token; phase 2: `run()` called with `resume=None` and a prompt
   containing the full summary; `chat_session_store` afterwards holds the NEW
   token; completion message mentions the new session.
3. next plain message in the chat routes to the NEW token (store-based
   resume resolution).
4. decline -> no runs, cancelled reply, store unchanged.
5. phase 1 yields `CompletedEvent(ok=False, error=...)` -> failure reply
   (`notify=True`); NO phase 2; store still holds the OLD token.
6. empty/whitespace `answer` -> treated as failure (no phase 2).
7. true-compaction engine (claude-class double): NO approval gate; immediate
   compact exactly as today (regression guard).
8. instructions forwarded: `/compact keep tests` -> `handoff_prompt` receives
   the focus text.
9. none engine (approved D1) -> approval text includes the disclaimer; approve ->
   same migrate flow.
10. Ordering regressions from `4669620` (`/compact /omp`, `/omp /compact`)
    stay green; the approval gate applies after selector resolution.
11. Topic-mode variant of test 2 when topic fixtures allow (store flip in
    `topic_store`); otherwise chat-session mode only + note in the plan.

New unit tests in `tests/test_compact_core.py`:

12. `handoff_seed_prompt(summary)` embeds the full summary and the
    "brief acknowledgement / wait for the user" instruction.

### Task B - Implementation (GREEN)

**B1. `src/takopi/compact.py`:** add `handoff_seed_prompt(summary: str) -> str`
- template: "You are continuing work from a previous session. The handoff
  summary below is your memory of that work. Reply with a one-line
  acknowledgement and wait for the user's next instruction." + full summary.

**B2. `src/takopi/scheduler.py`:** extend `ThreadJob.kind` Literal with
`"handoff"` (one-line change; scheduler queue logic is kind-agnostic).

**B3. `src/takopi/telegram/commands/compact.py`:** in
`handle_compact_command`, branch `support.mode == "handoff_only"` (and `none`, per approved D1) into the approval gate: explanation text + two buttons
(`COMPACT_CONFIRM_MARKUP` reused; button labels: "approve handoff" /
"cancel"); store `PendingCompactConfirm` (unchanged shape - D1 approved).
True-compaction engines keep the immediate path with the existing ack.

**B4. `src/takopi/telegram/commands/compact.py` (callback):**
`handle_compact_confirm_callback` enqueues `ThreadJob(kind="handoff")`
(instead of the plain-prompt job) carrying `compact_instructions`.

**B5. `src/takopi/telegram/loop.py`:** add `run_handoff_job(job)` next to
`run_compact_job`; branch in `run_thread_job` on `kind == "handoff"`.
Phase 1 mirrors the `run_compact_job` event-consumption/failure pattern;
on success with non-empty `answer`: send the phase ack, then `await run_job(...)`
with `resume_token=None`, `engine_override=job.resume_token.engine`,
`chat_session_key=job.session_key`, same `thread_id`, and
`scheduler.note_thread_known` (wrapped internally by `run_job`).
Completion + truncated summary echo (approved D2).

**B6. Wording constants:** keep all user-facing strings in the two modules
above; no new config keys; no hardcoded limits (split/truncation reuses
`MAX_BODY_CHARS`).

### Task C - Docs and roadmap

- `ROADMAP.md` Task 1 requirement 5 rewording: handoff engines get approval +
  summarize + new-session + reroute semantics (narrow patch).
- `docs/how-to/compact-session.md`: rewrite the handoff section (approval
  flow, new-session semantics, "send fresh messages, do not reply to
  pre-handoff messages" guidance, echo behavior (approved D2)).
- `docs/reference/commands-and-directives.md`: matrix row update.
- `changelog.md`: entry.

### Task D - Verification gate

```
uv run pytest tests/test_telegram_compact_dispatch.py tests/test_compact_core.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

Live e2e (user, single instance, verified artifact): reply `/compact` to an
omp session -> approval card -> approve -> summary phase -> seed turn renders
-> completion message -> send "what were we working on?" as a FRESH message ->
the agent answers from the handoff summary (proves context carried to the new
session id).

## Files touched

- M `src/takopi/compact.py` (`handoff_seed_prompt`)
- M `src/takopi/scheduler.py` (`kind` Literal)
- M `src/takopi/telegram/commands/compact.py` (approval gate + callback)
- M `src/takopi/telegram/bridge.py` (button labels/markup const reuse)
- M `src/takopi/telegram/loop.py` (`run_handoff_job`, branch)
- M `tests/test_telegram_compact_dispatch.py`, `tests/test_compact_core.py`
- M `ROADMAP.md`, `docs/how-to/compact-session.md`,
  `docs/reference/commands-and-directives.md`, `changelog.md`
- No runner changes: `HandoffCompactMixin` stays as the summary producer.

## Risks and pitfalls

- Routing race: between approval and the seed run `StartedEvent`, fresh
  messages still resolve the old stored token. Accepted (small window);
  serialized per old-thread for replies; documented in the completion text.
- Replying to PRE-handoff messages after migration routes to the OLD session
  (footer token precedence). Mitigation is user guidance only; do not rewrite
  old footers.
- Seed turn costs one extra agent turn (latency/quota) - inherent to portable
  session creation; documented.
- Seed prompt must carry the FULL summary; truncation (approved D2) applies
  only to the user echo.
- Pending approvals are in-memory; a bridge restart answers "request expired"
  (existing `4669620` behavior).
- If the seed run fails to start, stores keep the old token; the failure
  surfaces through the normal run rendering. Acceptable; do not add rollback.
- Keep the `4669620` ordering/parser tests and the `bca5e46` lifecycle tests
  green except the intentional approval-gate behavior change.
- Do not commit unless the user explicitly asks.