# Grok Answer/Narration Split - Plan-Spec (Roadmap Task 10)

> Live bug report 2026-08-05: the FINAL grok message contains the entire
> reasoning/narration transcript ("Let me read the plan first... Now let me
> check...") followed by the real answer; the body was so large it split
> into two Telegram messages. Progress coalescing (Task 9) works - "step 1".

**Root cause (evidence-backed):**

- `render_final_parts` renders body = `answer` ONLY
  (`src/takopi/markdown.py:236-240`); actions never appear in finals.
- `answer` = `state.last_assistant_text` = accumulation of ALL
  `StreamTextEvent` chunks (`runners/grok.py:122-123`).
- In agentic coding runs the grok harness emits intermediate NARRATION
  (assistant text between tool calls) as `text` events, indistinguishable
  per-event from the final answer text. Everything is concatenated into the
  final message.
- The A0 sample from Task 9 (`stream-sample.jsonl`: 185 thought + 188 text +
  1 end, math prompt) has NO narration - text = pure answer - so the sample
  hid this bug.

**Goal:** the final message contains ONLY the actual answer. Narration stays
visible in PROGRESS (as coalesced note actions, same style as Task 9
thoughts) but never leaks into the final body.

**Chosen design (text segmentation, evidence-validated in Task A0):**

```
GrokStreamState gains: text_segments: list[str]  (closed narration blocks)
current text accumulation continues as today

StreamThoughtEvent  -> close the current text segment (it is narration),
                       start a new one; keep thought buffering (Task 9)
StreamTextEvent     -> keep accumulating into the current segment
StreamEndEvent      -> answer = LAST non-empty segment (trailing text run)
                       earlier segments -> coalesced note actions
                       (progress narration, same flush style as thoughts)
```

- Single-turn runs (one text segment, no thoughts) -> answer = full text.
  Backward compatible with the math sample and every existing test.
- No final answer (all narration) -> answer = last segment (same as today).
- Narration -> note actions: coalesced per segment, one action each,
  skipped when empty/whitespace (mirrors `_flush_pending_thought` rules).

**Rejected alternatives:** cap/truncate the final body (hides the problem,
loses the answer too); renderer-side filtering (engine-specific knowledge in
the shared renderer); regex narration detection (fragile, unverifiable).

## Tasks (TDD)

### Task A0 - Capture a REAL agentic stream (investigation, read-only)

1. Run the grok CLI on a small multi-step task (read a file, edit, verify)
   with the same args `build_args()` produces; capture raw JSONL to
   `docs/reference/runners/grok/stream-sample-agentic.jsonl`.
2. Analyze the event sequence: where narration appears relative to thought
   and text events, and whether the final answer is always the trailing
   text run. If the trailing-run rule FAILS on the real capture, re-spec
   the delimiter from the evidence before writing Task B.
3. Record the analysis as a short note next to the sample.

### Task A - Failing tests (RED)

`tests/test_grok_runner.py` (fixtures from the agentic capture):

1. narration-text, thought, narration-text, answer-text, end -> final
   answer == last text block ONLY; narration blocks became note actions.
2. Single text block (math shape) -> answer == full text (backward compat).
3. Narration-only stream -> answer == last segment (today\'s behavior).
4. Empty/whitespace segments -> no note actions, no empty titles.
5. Replay `stream-sample-agentic.jsonl` end-to-end through the runner:
   answer == the real final answer from the capture; narration absent from
   the answer; step count sane.
6. Replay `stream-sample.jsonl` (math): answer unchanged
   ("**391**." content), coalescing from Task 9 intact.
7. Existing `test_grok_runner.py` and `test_grok_schema.py` suites stay
   green unmodified except where the new behavior intentionally changes
   expectations (document each).

### Task B - Implementation (GREEN)

**B1. `runners/grok.py`:** text segmentation in `translate_grok_event` as
specified above; narration-to-note coalescing reuses the Task 9 flush
helper pattern (extract a shared private helper if duplication appears -
DRY, but keep it engine-local).

**B2. Docs:** `docs/reference/runners/grok/` - one paragraph on the
narration/answer split + the agentic sample reference; changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_grok_runner.py tests/test_grok_schema.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: run a multi-step task in a grok session; the final Telegram
message contains ONLY the summary/answer; narration visible in progress;
no 2/2-split dumps of reasoning.

## Files touched

- M `src/takopi/runners/grok.py` (segmentation + narration notes)
- M `tests/test_grok_runner.py`
- A `docs/reference/runners/grok/stream-sample-agentic.jsonl` (+ analysis
  note)
- M `changelog.md`

## Risks and pitfalls

- The delimiter rule MUST be validated on the real agentic capture (A0)
  before implementation; if narration and answer are not separated by
  thought events in practice, the plan re-specs from evidence.
- Backward compatibility: single-turn Q&A must keep the full-text answer.
- Keep it engine-local: no renderer/progress/settings changes.
- Narration note titles follow the Task 9 truncation path (renderer caps
  line width); no unbounded titles in progress either.
- Do not commit unless the user explicitly asks.