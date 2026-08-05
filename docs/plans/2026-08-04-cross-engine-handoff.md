# Cross-Engine Handoff (Destination Engine Selection) - Plan-Spec

> Roadmap Task 8. Delta spec on top of the approved Task 1 plan
> `2026-08-04-compact-handoff-new-session.md` and the Task 7 spec
> `2026-08-04-handoff-command.md`.
>
> User request (2026-08-04): "Will I be able to make a handoff from one agent
> harness and use it in another? I want to make handoff from omp to grok."
> Answer in the current design: NO - phase 2 seeds the new session with
> `engine_override = job.resume_token.engine` (same engine only), and neither
> the parser, the pending-confirm state, nor the job has a destination field.
>
> Status 2026-08-04: dependencies LANDED during spec writing - Task 1
> handoff-new-session flow (`26ee9cb`) and Task 7 `/handoff` (`f031c9a`).
> All symbols referenced below were verified against the tree after those
> commits.

**Goal:** `/handoff` and `/compact` accept an optional destination engine so a
handoff can migrate a session across harnesses (e.g. omp -> grok):

```
/handoff [/source-engine] [to <dest-engine>] [instructions...]
/compact [/source-engine] [to <dest-engine>] [instructions...]
```

**Why it is cheap here:** the destination engine only receives the seed prompt
through the normal `run()` path - it never needs compact support. Any
available engine is a valid destination.

**Harness coverage (user requirement 2026-08-04):** the feature works with
ALL harnesses. Every configured engine is valid BOTH as a handoff source and
as a destination, including plugin runners and `CompactSupport.none` engines.
Engine lists are always derived at runtime (`runtime.engine_ids`,
`resolve_runner`) - no hardcoded engine names anywhere (parser, validation,
texts, tests).

**Grammar rules:**

- Leading slash tokens: command flag (`handoff`/`compact`) + at most one
  SOURCE engine selector (unchanged, Task 1/Task 7 semantics).
- Optional `to <engine>` clause immediately after the flags: bare word `to`
  followed by a known engine id (leading `/` tolerated: `to /grok`).
- `to` followed by a non-engine word is NOT a clause: `/handoff to do list`
  keeps `to do list` as instructions (engine-id match required).
- At most one `to` clause; a second `to ...` becomes instructions.
- No `to` clause -> destination = source engine (today's behavior,
  backward compatible).
- `/compact to grok` on a compaction-capable engine FORCES the
  handoff-migration path (with approval): in-place compaction cannot satisfy
  a cross-engine request.

**Flow sketch (delta):**

```text
/handoff to grok   (reply to an omp session message)
  |
  v
parser: CompactInvocation + destination_engine="grok"
  |
  v
validate destination: known engine + runner available
  |  unknown/unavailable -> error reply, NO approval card
  v
approval card: "handoff from omp to a NEW grok session?
  Takopi will: 1) ask omp for a handoff summary,
  2) start a NEW grok session seeded with it,
  3) route future messages there."
  [approve handoff] [cancel]
  |
  v approve
ThreadJob(kind="handoff", handoff_target="grok")
  |
  v
phase 1: omp run(handoff_prompt) -> summary     (source engine, unchanged)
phase 2: run_job(seed_prompt(summary), resume=None,
                 engine_override="grok")          (destination engine - NEW)
  -> store flips to the grok token; footer becomes `grok resume ...`
completion: "handoff complete - new grok session started ..."
```

## Tasks (TDD)

### Task A - Failing tests (RED)

Parser (extend the invocation parser matrix):

1. `"/handoff to grok"` -> destination `"grok"`, no instructions.
2. `"/handoff to /grok"` -> same (slash tolerated).
3. `"/handoff /omp to grok keep tests"` -> source `"omp"`, destination
   `"grok"`, instructions `"keep tests"`.
4. `"/handoff to do list"` -> destination None, instructions `"to do list"`
   (`to` + non-engine word stays instructions).
5. `"/compact to grok"` -> destination `"grok"` on the compact path.
6. `"/handoff to unknownengine"` -> destination None, instructions
   `"to unknownengine"` (unknown ids are not consumed).
7. Regression: full Task 1/Task 7 parser matrix without `to` stays
   byte-identical.

Loop-level (extend `tests/test_telegram_compact_dispatch.py`):

8. omp session reply `/handoff to grok` -> approval card names BOTH engines
   ("from omp", "new grok session"); approve -> phase 1 on the omp runner,
   phase 2 `run()` with `engine_override="grok"`, `resume=None`, prompt
   contains the full summary; store flips to the grok token.
9. Next plain message routes to the grok token.
10. `/handoff` (no `to`) -> phase 2 keeps the source engine (regression).
11. Unknown/unavailable destination -> error reply, NO approval card, no job.
12. `/compact to grok` on a true-compaction engine (claude double) -> approval
    card (forced handoff), NOT immediate native compaction.
13. decline -> nothing runs; store unchanged.
14. None engine as source (D1 flow) with `to` -> same migration to the
    destination.
15. Harness coverage: parametrized source x destination pairs across all
    engine doubles (codex, claude, opencode, pi, omp, grok, agy, mock) -
    every configured engine accepted as destination, every session-owning
    engine accepted as source.

### Task B - Implementation (GREEN)

**B1. Parser (`telegram/commands/parse.py`).** Extend
`parse_command_invocation` (landed in `f031c9a`, `parse.py:45`) to also return
`destination_engine: EngineId | None`: after flag/source scanning, match
`to` + engine id (optional leading `/`), case-insensitive; consume both
tokens only when the id is known. No new dataclass - extend
`CompactInvocation` with the field (default None keeps old constructors
valid).

**B2. Job + pending state.** `ThreadJob.handoff_target: EngineId | None = None`
(`scheduler.py:19-30`, one field); `PendingCompactConfirm.destination_engine` (`commands/compact.py:27`, one field) carried from the invocation into the job.

**B3. Validation + approval text (`commands/compact.py`).** Resolve the
destination entry via `cfg.runtime.resolve_runner(resume_token=None,
engine_override=destination)`; on missing/unknown/unavailable reply
"engine <id> is not available for handoff." and stop (no card). Approval
text names both engines when destination differs; single-engine wording
unchanged otherwise.

**B4. Executor (`loop.py` `run_handoff_job`).** Phase 2:
`engine_override = job.handoff_target or job.resume_token.engine`.
Everything else (seed prompt, store flip, completion text, D2 echo)
unchanged; the completion text names the destination engine.

**B5. Forced handoff on `/compact to <other-engine>`.** When a destination
is present and differs from the source engine, `/compact` skips the native
in-place path and routes to the approval gate via the existing `force_handoff or not support.true_compaction` branch (`compact.py:151`). Same destination or no destination: native behavior unchanged.

### Task C - Docs and roadmap

- `docs/reference/commands-and-directives.md`: grammar block for
  `[to <engine>]` on both commands + one cross-engine example.
- `docs/how-to/compact-session.md`: cross-engine paragraph (omp -> grok).
- `changelog.md`: entry.
- `ROADMAP.md`: mark Task 8 as specced (link this file).

### Task D - Verification gate

```
uv run pytest tests/test_telegram_compact_dispatch.py tests/test_telegram_compact_command.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

Live e2e: reply `/handoff to grok` to an omp session -> approval card
(omp -> grok) -> approve -> omp writes the summary -> a NEW grok session is
seeded -> completion -> ask a fresh question; grok answers from the summary.

## Files touched

- M `src/takopi/telegram/commands/parse.py` (`destination_engine` on the
  invocation + `to` clause scanning)
- M `src/takopi/scheduler.py` (`ThreadJob.handoff_target`)
- M `src/takopi/telegram/commands/compact.py` (pending field, validation,
  approval text, forced-handoff routing for `/compact to ...`)
- M `src/takopi/telegram/loop.py` (phase 2 `engine_override`, completion
  wording)
- M `tests/test_telegram_compact_dispatch.py`,
  `tests/test_telegram_compact_command.py` (or handoff test file)
- M docs + `changelog.md` + `ROADMAP.md` (specced marker)

## Dependencies and ordering

- SATISFIED (landed `26ee9cb`): handoff executor `run_handoff_job` (`loop.py:1744`), `kind == "handoff"` branch (`loop.py:1888`), approval infra in `commands/compact.py` (`PendingCompactConfirm` line 27, `handle_compact_confirm_callback` line 243).
- SATISFIED (landed `f031c9a`): generalized `parse_command_invocation` (`parse.py:45`), `CompactInvocation` (`parse.py:38`), `parse_handoff_invocation` (`parse.py:132`), `force_handoff` param (`compact.py:54`), handoff hook in `route_message` (`loop.py:2497`). Build directly on these symbols.

## Risks and pitfalls

- Grammar ambiguity: only consume `to <known engine id>`; never eat
  instruction text. The test matrix pins this (cases 4 and 6).
- Destination = a different engine that is unavailable must fail BEFORE the
  approval card, not after the summary was produced (avoid wasting an agent
  turn).
- The summary text is engine-agnostic; do NOT add engine-specific formatting
  to the seed prompt (KISS).
- Do not special-case destination == source: it is the plain Task 1 flow.
- Do not hardcode engine lists; resolve engines through the router at
  runtime (parser, validation, approval texts, tests).
- Do not commit unless the user explicitly asks.