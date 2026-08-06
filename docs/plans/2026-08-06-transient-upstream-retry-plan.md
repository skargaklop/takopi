# Transient Upstream Retry and Clean Error Handling

## Context

Combine ROADMAP Tasks 14 and 17 into one implementation: detect transient upstream failures from runner streams and subprocess stderr, retry only attempts that provably produced no session or action side effects, and replace opaque provider JSON with one readable terminal error. Grok's observed `Internal error: {json}` 503 capacity failure is the primary acceptance case; shared handling must also cover 429/rate-limit and overload signals without changing non-transient failures. The implementation must behave identically on Windows, macOS, and Linux.

## Approach

### 1. Add one shared transient-failure classifier and formatter

Create `src/takopi/utils/transient_failures.py`; no equivalent exists in `src/takopi/utils/` or the runner modules. Define:

```python
@dataclass(frozen=True, slots=True)
class TransientFailure:
    http_status: int | None
    message: str


def classify_transient_failure(text: str) -> TransientFailure | None: ...


def format_transient_failure(engine: str, failure: TransientFailure) -> str: ...
```

`classify_transient_failure` must:

- Accept the exact observed Grok form `Internal error: {"message": "API error (status 503 Service Unavailable): Chat admission capacity is temporarily unavailable. Retry shortly.", "http_status": 503, ...}` as well as a plain error string from a decoded stream event.
- Strip the `Internal error:` prefix, parse the remaining object with `json.loads`, and read string `message` plus integer `http_status`; malformed JSON falls back to classifying the original text rather than raising.
- Collapse embedded whitespace/newlines to a single line.
- Return transient only for explicit evidence: status 429 or 503; case-insensitive `HTTP 429/503` or `status 429/503`; or the phrases `admission capacity`, `temporarily unavailable`, `overloaded`, `rate limit`/`rate-limit`, `retry shortly`, or `try again later`. Do not classify the bare word `retry`, authentication failures, invalid requests, generic nonzero exits, cancellations, or timeouts.
- Prefer the JSON `http_status`, otherwise extract 429/503 from text, otherwise leave it `None` for an explicit transient phrase.
- Produce `TransientFailure.message` by removing the outer JSON/prefix and a leading `API error (status ...):`, then removing a terminal retry directive such as `Retry shortly.` or `Try again later.`; retain the provider's substantive reason. Empty extracted messages fall back to `Upstream capacity is temporarily unavailable.`.

`format_transient_failure` must return exactly `<engine> upstream is temporarily unavailable<status>: <reason> Try again in a few minutes.`, where `<status>` is ` (HTTP 503)`/` (HTTP 429)` when known and empty otherwise. Normalize punctuation so the reason has one terminal period and the output never contains raw JSON, `Internal error:`, or duplicate retry advice.

### 2. Capture JSONL subprocess stderr and make retry decisions at the shared spawn boundary

Extend `drain_stderr` in `src/takopi/utils/streams.py` with the backward-compatible positional parameter `capture: list[str] | None = None`. Continue structured logging unchanged; when a capture list is supplied, append newline-stripped decoded lines and retain only the latest 200 lines. Existing three-argument callers, including Codex app-server, remain valid.

Refactor `JsonlSubprocessRunner.run_impl` in `src/takopi/runner.py` into an outer attempt loop around the existing `manage_subprocess` block. Add class attributes:

```python
retry_max_attempts: int = 3
retry_base_delay_s: float = 5.0
```

For each attempt, create a fresh runner state and `JsonlStreamState`, pass an attempt-local stderr list to `drain_stderr`, and track only events emitted by that subprocess attempt:

- `StartedEvent` means a session started.
- Any `ActionEvent` means agent work or visible progress occurred.
- A nonblank `CompletedEvent.answer` means output occurred.

Inside the per-attempt event loop, classify each failed `CompletedEvent.error` before it leaves the runner. Construct a replacement `CompletedEvent` with `dataclasses.replace(event, error=format_transient_failure(...))`, preserving answer, resume, and usage. A decoded Grok `type: "error"`, Codex `turn.failed`, OpenCode 429, or Pi/OMP error therefore receives a clean error. Hold a classified failed completion until the subprocess exits and the retry decision is known; yield successful and non-transient completions exactly as today. If a start, action, or nonblank answer already made replay unsafe, the classified completion may be emitted immediately because no retry is possible.

For a nonzero subprocess exit without a terminal stream event, classify `"\n".join(stderr_tail)` before calling the existing runner-specific `process_error_events`. Retry a held stream failure or raw-exit failure only when all four conditions hold: classification is transient, no `StartedEvent` was emitted, no `ActionEvent` was emitted, and no nonblank answer was produced. This is the fail-closed safety boundary; a locally or remotely assigned session token counts as a started session and forbids replay.

`retry_max_attempts` is the total number of subprocess attempts, including the first. If another attempt remains, discard the held failed completion or raw-exit generic events, emit one shared warning action using `note_event` with the exact title `<engine> upstream busy<status>; retrying in <delay>s (attempt <next>/<max>)`, then await `anyio.sleep(delay)`, where `delay = retry_base_delay_s * current_attempt`. Format integral delays without `.0`; include ` (HTTP N)` only when known. The retry note belongs outside the next attempt's safety counters.

If attempts are exhausted, emit the held clean completion. For an exhausted raw-exit failure, obtain the runner-specific completion from `process_error_events`, preserve its answer/resume/usage with `dataclasses.replace`, replace its error, and suppress the runner's generic failure note so raw or duplicate errors do not reach the user. Non-transient stream and process failures must follow the existing paths byte-for-byte.

The backoff sleep must remain inside the caller's AnyIO cancellation scope and must not be shielded. Cancellation during backoff therefore exits immediately and `manage_subprocess` retains its existing Windows process-tree and POSIX process-group cleanup semantics.

### 3. Apply the same classifier to the two non-JSONL runner paths

In `AgyRunner.run_impl` (`src/takopi/runners/agy.py`), classify the captured `stderr_tail` when `rc != 0`. Keep its existing early `StartedEvent`; therefore Agy failures are intentionally never auto-retried under the no-start safety rule. For transient failures, preserve the current answer and resume token but set `CompletedEvent.error` to `format_transient_failure("agy", failure)` and do not copy the raw stderr blob into `answer`; non-transient behavior remains unchanged.

In `_translate_app_notification` (`src/takopi/runners/codex.py`), classify the `turn/completed` error message before constructing `completed_error`. Preserve the answer and resume token and substitute the formatted error only when classification succeeds. Do not retry app-server turns: `thread_start`/`turn_start` and the emitted `StartedEvent` prove the attempt crossed the side-effect boundary. Codex exec already inherits shared JSONL handling.

### 4. Wire and validate global retry configuration

Add these fields to `RunnerSettings` in `src/takopi/settings.py`:

```python
retry_max_attempts: int = Field(default=3, ge=1)
retry_base_delay_s: float = Field(default=5.0, ge=0.0)
```

In `build_router` (`src/takopi/runtime_loader.py`), assign both values to runners exposing the corresponding attributes, following the existing `startup_timeout_s`/`idle_timeout_s` wiring. JSONL runners receive both settings. Do not add engine-specific copies or environment-dependent defaults.

Document both keys in the existing `[runners]` TOML sample/table in `docs/reference/config.md`: `retry_max_attempts` is total attempts and `retry_base_delay_s` is the linear-delay base in seconds. After the behavior and verification pass, consolidate ROADMAP Task 17 into Task 14 and mark both completed by the same implementation rather than leaving duplicate open work.

### 5. Pin classifier, Grok fixtures, retry safety, and cross-platform behavior with tests

Create `tests/fixtures/grok_stream_capacity_error.jsonl` as an explicitly synthesized fixture because no raw 503 stream capture exists. It must contain one object with `type: "error"`, the exact observed `Internal error: {json}` string in `message`, a stable `sessionId`, a stable `requestId`, `num_turns: 0`, and representative `usage`; these are the exact optional fields accepted by `StreamErrorEvent` in `src/takopi/schemas/grok.py`. Also test the observed alternate delivery channel directly: empty JSONL stdout, the same blob on stderr, and process exit code 1.

Add `tests/test_transient_failures.py` for table-driven pure-function contracts:

- observed Grok JSON blob -> status 503 and reason `Chat admission capacity is temporarily unavailable.`;
- 429/rate-limit, overload, whitespace/newline, malformed-prefixed JSON fallback, and phrase-only transient forms;
- authentication, invalid request, cancellation, timeout, generic rc text, and bare `retry` -> `None`;
- exact formatted messages with and without HTTP status and no raw JSON/duplicated advice.

Extend `tests/test_runner_utils.py` using its existing fake `manage_subprocess` pattern to prove the new orchestration:

- two stderr-only transient failures followed by success produce three spawns, delays `base` then `2 * base`, two retry notes, one final completion, and no failed completions;
- three stderr-only failures produce one clean failed completion with no raw JSON or generic rc note;
- a transient failure after a `StartedEvent`, after an `ActionEvent`, or with a nonblank answer spawns once and preserves resume/answer/usage while cleaning the error;
- non-transient rc and stream failures retain current events and messages;
- cancellation during a nonzero backoff prevents the next spawn and propagates cancellation promptly.

Extend `tests/test_grok_runner.py` to replay the synthesized fixture through `translate_grok_event` and assert clean `CompletedEvent.error`, preserved usage/resume, and no retry at the translation layer. Extend `tests/test_agy_runner.py` and `tests/test_codex_runner_helpers.py` for their clean-message-only paths. Extend `tests/test_settings.py` and `tests/test_runtime_loader.py` for defaults, overrides, rejection of attempts below 1 or negative delay, and propagation onto a JSONL runner.

All process fakes must use AnyIO byte streams and argument arrays, not shell commands or platform path syntax, so the same tests execute on Windows, macOS, and Linux.

## Critical files & anchors

- `src/takopi/runner.py` — `JsonlSubprocessRunner.run_impl`: shared live-stream/process-exit boundary where stderr, emitted-event safety state, retries, and final completion converge.
- `src/takopi/runners/grok.py` — `translate_grok_event` `StreamErrorEvent` branch: current Grok error mapping and synthesized 503 fixture entry point.
- `src/takopi/runners/agy.py` — `AgyRunner.run_impl`: plain-text runner with an existing bounded stderr tail outside the JSONL base.
- `src/takopi/runners/codex.py` — `_translate_app_notification` `turn/completed` branch: default app-server error path that does not inherit `JsonlSubprocessRunner`.
- `src/takopi/runtime_loader.py` — `build_router` lifecycle-setting assignments: single global configuration propagation point.

## Verification

Run from `D:\Projects\takopi`. On Windows PowerShell, set `$env:PYTHONUTF8='1'` first; on macOS/Linux use `PYTHONUTF8=1` before each command.

1. Focused new behavior:

```text
uv run pytest tests/test_transient_failures.py tests/test_runner_utils.py tests/test_grok_runner.py tests/test_agy_runner.py tests/test_codex_runner_helpers.py tests/test_settings.py tests/test_runtime_loader.py -q --no-cov
```

Expected: all focused tests pass. The stderr-only Grok simulation must visibly prove `rc=1 + observed 503 blob -> two bounded retries -> one clean terminal error or success`, while a stream error after `StartedEvent` must prove one spawn only.

2. Full regression suite using the repository's current known-failure exclusion:

```text
uv run pytest tests/ -q --no-cov --ignore=tests/test_subprocess_close.py
```

Expected baseline from 2026-08-06: 979 passed, 1 skipped before these new tests; after implementation, all old and new tests pass with no additional failures.

3. Static checks:

```text
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

Expected: both Ruff commands pass. Task 18 remains responsible for the 41 pre-existing `ty` diagnostics; this change must add no diagnostic in touched/new files and must not increase that baseline.

4. Cross-platform proof: run the focused command and full regression command on `windows-latest`, `macos-latest`, and `ubuntu-latest` with Python 3.14. All three are required; passing on fewer platforms is not completion.

## Assumptions & contingencies

- The only observed Grok 503 evidence is the exact error blob and rc/action-count report, not a preserved raw streaming-json capture. The implementation therefore pins both plausible channels: a synthesized `type: "error"` fixture and the observed stderr/nonzero-exit form. If a future real capture uses a different envelope, add that envelope as a fixture and feed its message/stderr text into the same classifier; do not add a Grok-only classifier.
- `retry_max_attempts` means total attempts, not retries; default 3 therefore permits two retries. This resolves Task 17's optional 1–2 retries in favor of Task 14's explicit configurable default.
- A `StartedEvent` is treated as evidence of a started session even when its token was generated locally. This deliberately favors duplicate-work prevention: Grok stream errors, Agy, and Codex app-server receive clean errors but no automatic replay once started.
- Existing runner-specific retry events, such as Codex reconnect notices and Pi `auto_retry_start`, remain owned by their harness. Takopi's outer retry applies only after a terminal transient failure and the strict zero-side-effect guard, so it does not replace or reinterpret those in-stream mechanisms.
