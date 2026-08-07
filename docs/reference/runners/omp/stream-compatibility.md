# OMP/Pi stream compatibility

This document records real-world evidence about the OMP (Oh My Pi) `--mode json`
JSONL streaming protocol and how Takopi handles edge cases that the producer
emits but the original schema did not anticipate.

## Evidence capture

**Date:** 2026-08-07
**OMP version:** `omp/17.2.10`
**OS:** Windows 10 Pro (win32 10.0.19045), x64
**Command (canonical):**

```text
omp --print --mode json [--resume <FULL_SESSION_ID>] <prompt>
```

### Direct captures

1. **Live runs (2026-08-07):** 20+ native `omp --print --mode json` invocations
   against the OmniRoute `glm-5.2-1m-combined` model. All succeeded without
   capacity errors (OmniRoute capacity was sufficient). These captures proved
   the normal event vocabulary and revealed previously-unhandled nested
   `assistantMessageEvent` sub-types (`toolcall_start`, `toolcall_delta`,
   `toolcall_end`) — all safely absorbed by the existing `message_update`
   envelope since `assistantMessageEvent` is decoded as `dict[str, Any]`.

2. **Historical Takopi log** (`~/.takopi/takopi.log:1825-1829`, 2026-08-06):
   records three decoder rejections during an OMP resume of session
   `019fd7f2-d1dd-7000-97dd-dc3d5627ab43`:

   - `Expected \`int | null\`, got \`float\` - at \`$.delayMs\`` (twice)
   - `Invalid value 'notice' - at \`$.type\``
   - Process exited `rc=0`; the agent-run itself failed with
     `503 Chat admission capacity is temporarily unavailable. Retry shortly.`
     (an OmniRoute routing-application response surfaced through OMP).

   The Takopi log retained validation errors but not the rejected raw JSONL
   payloads, so it is **corroborating evidence only**, not the source of raw
   records.

3. **OMP source code** (`@oh-my-pi/pi-coding-agent@17.2.10`, bundled
   `dist/cli.js`): authoritatively confirms the three event shapes that could
   not be live-captured because they are capacity-load-dependent:

   ### `auto_retry_start` with float `delayMs`

   The retry-delay computation function `KRi(baseDelayMs, attempt)`:

   ```js
   function KRi(n, i) {
     let h = Math.min(Math.max(0, n) * 2 ** Math.max(0, i - 1), Qm1);
     let f = 1 - Math.random() * zm1;
     return h * f;
   }
   // Qm1 = 8000 (max delay cap), zm1 = 0.25 (jitter range 0–25%)
   // default retry.baseDelayMs = 500
   ```

   The jitter multiplier `(1 - Math.random() * 0.25)` almost always produces a
   non-integer float. Example: `500 * 2^0 * 0.784... = 392.19...`. This is why
   `delayMs` arrives as a float, not an integer.

   Emitted as:
   `{type:"auto_retry_start", attempt, maxAttempts, delayMs, errorMessage, errorId}`

   ### `notice`

   Emitted via `emitNotice(level, message, source)`:

   `{type:"notice", level, message, source}`

   This is an informational/operational notice (e.g. "Switched to fallback
   provider", "Context window optimized"). It carries no answer/tool/usage
   semantic and does not alter turn or session state.

   ### Terminal OmniRoute 503 failure with `rc=0`

   When retries are exhausted, the process still exits `0` (transport success)
   while the agent-run fails. The `agent_end`/`turn_end` message carries
   `stopReason:"error"`, `errorStatus:503`, and the OmniRoute error text.

### Sanitization

All captures were sanitized: prompt content replaced with `<redacted prompt>`,
assistant text replaced with `<redacted assistant text>`, real session IDs
retained only where they are non-sensitive protocol shape examples (the
historical `019fd7f2` session ID was already public in the Takopi log). No
credentials, Telegram identifiers, or user content was committed.

The sanitized probe is at `probes/stream-retry-notice.jsonl`.

## Current behavior (before Task 22)

- `auto_retry_start` with float `delayMs`: the line is **dropped** by
  `PiRunner.decode_error_events()`, which logs one `jsonl.msgspec.invalid`
  WARNING and skips the line. Decoding continues per-line, so later events
  remain visible.
- `notice`: same — dropped as an invalid `type` union member.
- OmniRoute 503 with `rc=0`: the process exits `0`, so the harness transport
  succeeds. The translated `CompletedEvent(ok=False)` flows through the shared
  `JsonlSubprocessRunner.run_impl()` failure path. Because prior
  start/action/answer output makes replay unsafe, the result is one clean
  failed completion — no retry.

## Compatibility boundary (after Task 22)

| Scenario | Behavior |
|---|---|
| Known tag, well-formed | Strict decode (unchanged) |
| Known tag, malformed required field | `msgspec.ValidationError`; line skipped; decoding continues |
| Unknown string tag (e.g. `notice`, `future_event`) | Decoded to `PiUnknownEvent`; one DEBUG `pi.stream.unknown_type`; no Takopi event |
| `delayMs` as float | Decoded as `float`; precision preserved (no rounding/coercion) |
| Malformed JSON | `msgspec.DecodeError`; line skipped; later lines preserved |
| OMP session ID | Full UUID preserved and round-tripped |
| Pi session ID | Abbreviated (8-char / dash-prefix), unchanged |
| OmniRoute 503 capacity failure (`rc=0`) | Shared transient classification + clean formatting; no OMP-specific subsystem |

## Provenance

The `503 Chat admission capacity is temporarily unavailable` error originates
from **OmniRoute** (the routing application that fronts the model provider),
surfaced through OMP. It is **not** evidence of an OMP-owned admission-capacity
system. All documentation, fixtures, and test names use this provenance.
