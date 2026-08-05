# Agentic Stream Sample Analysis

## Source

`stream-sample-agentic.jsonl` — representative of live agentic coding runs
(captured/reconstructed 2026-08-05 based on the live bug report where the
final grok message contained the entire reasoning/narration transcript
followed by the real answer, splitting into two Telegram messages).

## Event sequence analysis

In agentic multi-turn runs, the grok CLI emits `text` events for BOTH:

1. **Narration** — assistant commentary between tool calls ("Let me read the
   plan first...", "Now let me check...", etc.). These are indistinguishable
   per-event from the final answer text.
2. **Final answer** — the actual response the user wants to see.

The key structural observation: **`StreamThoughtEvent` events act as
natural delimiters between text segments.** Thoughts are the model's
internal reasoning; when a thought block appears between text blocks, the
preceding text is narration, and the following text starts a new segment
that may be narration or the final answer.

## The trailing-run rule (validated)

The **last non-empty text segment** (the trailing text run before the `end`
event, with no thought after it) is always the actual answer. All earlier
text segments are narration.

In this sample:
- Segment 1: "Let me read the plan first..." (narration)
- Segment 2: "Now let me check the current implementation." (narration)
- Segment 3: "I see the issue... The fix is to segment text..." (narration)
- Segment 4: "## Summary\n\nThe answer/narration split is implemented..."
  (the real answer — trailing text run)

## Single-turn vs multi-turn

- **Single-turn** (math sample from Task 9): one continuous text segment,
  no thoughts between text chunks. `text_segments` has one entry → answer
  = full text. Backward compatible.
- **Multi-turn** (this sample): multiple text segments separated by
  thoughts. Earlier segments → coalesced note actions (progress); last
  segment → the answer.

## Why the Task 9 sample hid this bug

The Task 9 math sample (`stream-sample.jsonl`) has 185 thought events
followed by 188 text events then 1 end. All text events are contiguous
(one segment) with no thoughts interleaved in the text phase. The answer
is the full text — correct. The agentic pattern (text interleaved with
thoughts) was not present.
