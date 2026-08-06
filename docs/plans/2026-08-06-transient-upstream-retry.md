# Transient Upstream Failure Handling - Plan-Spec (Roadmap Task 14)

> Live evidence 2026-08-06: a grok run failed with rc=1, `action_count=0`,
> `ok=False`, and the user received a raw JSON blob:
> `Internal error: {"message": "API error (status 503 Service Unavailable):
> Chat admission capacity is temporarily unavailable. Retry shortly.",
> "http_status": 503}`. Two takopi-side defects: no automatic retry for a
> retry-asked transient error, and an unformatted JSON blob as the
> user-facing message.

**Goal:** recognized transient upstream failures (HTTP 503/429, admission
capacity, overloaded, rate limit, "retry shortly/again") are retried
automatically with bounded backoff - but ONLY when the run produced zero
side effects; after exhaustion the user gets a one-line clean message.

**Safety rule (non-negotiable):** retry only when the failing attempt
emitted no session start and no actions (`action_count == 0`, empty
answer) - i.e. nothing happened, so re-running cannot duplicate work.

**Design:**

1. **Classifier** (`src/takopi/utils/` or `runner.py`): 
   `classify_failure(rc, text) -> FailureClass(transient: bool,
   http_status: int | None, clean_message: str)`. Parses the
   `Internal error: {json}` blob (json.loads after the prefix), matches
   status 503/429 and transient phrases ("admission capacity",
   "temporarily unavailable", "overloaded", "rate limit", "retry").
   Non-matching -> not transient, message unchanged.
2. **Retry loop** in `JsonlSubprocessRunner.run` (single choke point for
   grok/claude/pi/omp-style runners): on terminal failure -> classify ->
   if transient and zero-progress: yield a progress note action
   ("upstream busy (503); retrying in 5s (1/3)"), sleep backoff, respawn.
   Backoff: `base * attempt` (linear, simple); attempts bounded by
   settings.
3. **Settings (`RunnerSettings`, settings.py:223):**
   `retry_max_attempts: int = 3`, `retry_base_delay_s: float = 5.0`
   (documented defaults; no other hardcoded values).
4. **Exhaustion message:** `<engine> upstream is temporarily unavailable
   (HTTP 503): Chat admission capacity is temporarily unavailable. Try
   again in a few minutes.` - clean text, no JSON.
5. Scope note: codex exec path (`codex.py:672`) and agy (`agy.py:274`) get
   the classifier + clean message too; retry loop wiring per their run
   structure (same policy object, DRY).

## Tasks (TDD)

### Task A - Failing tests (RED)

`tests/test_runner_utils.py` (or new `tests/test_transient_retry.py`):

1. Classifier: the real 503 blob -> transient, status 503, clean message
   extracted; 429/rate-limit text -> transient; "grok failed (rc=2)" /
   unknown -> not transient, message untouched.
2. Retry: fake runner fails transient twice then succeeds -> 3 spawn
   attempts, two backoff note events, one final success completion.
3. Safety: failure AFTER progress (a started session/action) -> NO retry,
   error surfaces immediately.
4. Exhaustion: all attempts fail -> one clean message (no JSON blob),
   ok=False.
5. Settings: defaults applied; explicit config overrides respected.
6. Regression: non-transient failures behave exactly as today.

### Task B - Implementation (GREEN)

- B1. Classifier + policy dataclass.
- B2. Retry loop in `JsonlSubprocessRunner` (+ codex/agy per scope note).
- B3. `RunnerSettings` keys + `docs/reference/config.md` documentation.
- B4. User-facing note/message wording; changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_transient_retry.py tests/test_runner_utils.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: on the next real 503, the run retries automatically with visible
backoff notes; repeated failures end in the clean one-line message.

## Files touched

- M `src/takopi/runner.py` (or `src/takopi/utils/` for the classifier) +
  retry loop
- M `src/takopi/settings.py` (`RunnerSettings` keys)
- M `src/takopi/runners/codex.py`, `runners/agy.py` (classifier reuse)
- A `tests/test_transient_retry.py`; M `tests/test_runner_utils.py`
- M `docs/reference/config.md`, `changelog.md`

## Risks and pitfalls

- Never retry after side effects (progress started) - the zero-progress
  guard is the safety boundary, pinned by test 3.
- Retry sleeps must respect cancellation (anyio sleep inside the cancel
  scope; Ctrl+C during backoff aborts promptly).
- Do not retry forever: bounds come from settings; no infinite loops.
- The classifier must not swallow non-JSON error text (fallback =
  unchanged message).
- Do not commit unless the user explicitly asks.