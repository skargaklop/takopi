# Grok Stream Coalescing - Plan-Spec (Roadmap Task 9)

> Live bug report 2026-08-05: grok progress renders each WORD as a separate
> step and on its own line - "working - grok - 5m 35s - step 3517" with
> progress lines "v to", "v understand", "v spawn", "v sites" (the "v" is
> the completed-action check icon).

**Root cause (code-verified):** `translate_grok_event`
(`src/takopi/runners/grok.py:99-111`) maps EVERY `StreamThoughtEvent` to a
completed `note` action. The grok CLI emits `thought` JSONL events at
word/token granularity, so each word becomes one action: the header
`step N` (`markdown.py` `state.action_count`) explodes and every word prints
on its own action line (`format_action_line`). Text deltas
(`StreamTextEvent`, grok.py:94-97) are already accumulated correctly and are
NOT part of the bug.

**Existing tests use idealized fixtures** (one thought event per action,
`tests/test_grok_runner.py:176-182`) - the word-granularity production shape
was never tested.

**Goal:** one action/step per THOUGHT BLOCK instead of per word; readable
progress; text/answer path untouched; no new config knobs.

**Chosen design (Option A - runner-side coalescing):**

```
GrokStreamState gains: pending_thought: list[str]

StreamThoughtEvent(data)   -> buffer data (skip empties); emit NOTHING
any non-thought event      -> flush first: ONE action_completed(kind="note",
                              title=joined buffer) if buffer non-empty,
                              then translate the event as today
stream end / error         -> flush before the completed event
```

- Action id uses the existing `note_seq` once per flush.
- Title = joined buffer text; the renderer already truncates action lines
  (`MAX_PROGRESS_CMD_LEN`) and shows only `max_actions` - no extra capping.
- Event-driven only: no timers, no background tasks.
- Join strategy (space vs no-space chunks) decided from the REAL captured
  sample (Task A0); default `"".join(parts)`, fallback `" ".join(parts)`.

**Rejected alternatives:** B - render thoughts as plain text (loses step
visibility); C - renderer-side merge (state lives in two places, touches
every engine).

## Tasks (TDD)

### Task A0 - Capture real CLI output (investigation, read-only)

1. Run the grok CLI manually with a tiny prompt using the same args
   `build_args()` produces (`-p`/jsonl mode), capture raw stdout JSONL to
   `docs/reference/runners/grok/stream-sample.jsonl`.
2. Verify from the RAW sample: thought events are word-granularity at the
   CLI level (not a takopi split), whether chunks carry leading spaces, and
   whether text/thought events interleave.
3. Audit pi (`note_event`, `pi.py:505`) with the same method; record whether
   the same coalescing is needed there.

### Task A - Failing tests (RED)

`tests/test_grok_runner.py` (fixtures built from the real sample shape):

1. Word-granularity thought stream (N consecutive thought events) -> exactly
   ONE note action whose title contains the joined text.
2. thought, thought, text, thought, end -> TWO note actions, then the
   completed event; order preserved.
3. Empty `data` thought events -> no action, no empty title.
4. Step count regression: the word-granularity fixture yields
   `action_count == <real blocks>` (not N words).
5. Thought-then-end: the pending thought flushes BEFORE the completed event.
6. Schema tests (`test_grok_schema.py`) stay green unchanged (decoder is
   untouched).

If the A0 audit shows pi shares the pattern: mirror tests 1-2 for pi in
`tests/test_pi_runner.py` and apply the same fix (shared helper, DRY).

### Task B - Implementation (GREEN)

**B1. `runners/grok.py`:** add `pending_thought: list[str]` to
`GrokStreamState`; buffer in the `StreamThoughtEvent` case; add
`_flush_pending_thought(state, out)` used by every other case and by
`stream_end_events`/`process_error_events` paths; keep `note_seq` semantics.

**B2. (conditional, per A0) pi runner:** same buffer; if both runners need
it, extract one shared helper (e.g. in `runners/_compact_mixin.py` sibling
module or `runner.py`) - no duplicated buffer logic.

**B3. Docs:** `docs/reference/runners/grok/` notes (event granularity,
sample file reference); changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_grok_runner.py tests/test_grok_schema.py tests/test_pi_runner.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: send a prompt to a grok session via Telegram; progress shows a
sane step count and coalesced thinking lines (no per-word spam); final
message unchanged.

## Files touched

- M `src/takopi/runners/grok.py` (buffer + flush)
- (conditional) M `src/takopi/runners/pi.py` or shared helper module
- M `tests/test_grok_runner.py` ((conditional) `tests/test_pi_runner.py`)
- A `docs/reference/runners/grok/stream-sample.jsonl` (captured sample)
- M `changelog.md`

## Risks and pitfalls

- Do not change `StreamTextEvent` accumulation - the final answer text must
  stay byte-identical.
- Flush ordering: the coalesced note must precede the event that triggered
  the flush (progress chronology).
- Title spacing must come from the real sample, not guessed - per-word
  chunks may or may not carry leading spaces.
- Keep it engine-local: no renderer/progress changes, no new settings.
- Do not commit unless the user explicitly asks.