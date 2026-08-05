# `/handoff` Command for All Engines - Plan-Spec

> Roadmap Task 7. Delta spec on top of the approved Task 1 plan
> `2026-08-04-compact-handoff-new-session.md` (approve -> summarize ->
> NEW session -> reroute; decisions D1/D2 locked). This document defines ONLY
> the differences; all migration mechanics, executor internals, failure
> handling, echo behavior (D2), and risks are inherited from that plan.

**Dependency:** the Task 1 handoff-new-session implementation must land first.
This spec assumes `handoff_seed_prompt()`, `ThreadJob.kind == "handoff"`,
`run_handoff_job`, and the approval infrastructure
(`pending_compact_confirms`, `takopi:compact:confirm/decline`, markup) exist.

**Goal:** `/handoff` runs the same migration flow for EVERY engine, including
true-compaction ones (claude, codex, pi, opencode) - for users who want a
clean session break instead of in-place compaction.

**Command contract (to document):**

- `/compact` = reduce context: native in-place compaction when supported,
  handoff-migration (with approval) otherwise.
- `/handoff` = always: approval -> summary -> new session, for every engine.
  Ignores `compact_support()` entirely.

**Flow sketch (delta only):**

```text
/handoff [ /engine ] [instructions...]   (any position, any reply context)
  |
  v
parse_handoff_invocation (generalized parser, flag="handoff")
  |
  v
handle_handoff_command = handle_compact_command(..., force_handoff=True)
  |  session resolution: unchanged (selector > footer > running > stores)
  |  support check: SKIPPED - always route to the approval gate
  |
  v
approval card (wording variant by engine capability, see B4)
  [approve handoff] [cancel]
  |
  v approve -> ThreadJob(kind="handoff") -> run_handoff_job (UNCHANGED)
```

## Tasks (TDD)

### Task A - Failing tests (RED)

Parser unit matrix (`tests/test_telegram_compact_command.py` or new
`tests/test_telegram_handoff_command.py`):

1. `"/handoff"` -> `(None, None)`; `"/handoff@mybot"` -> `(None, None)`.
2. `"/handoff keep tests"` -> `(None, "keep tests")`.
3. `"/handoff /codex"` / `"/codex /handoff"` -> `("codex", None)`;
   with instructions -> `("codex", "keep tests")`.
4. Multi-line tail preserved (same rules as the compact parser).
5. `"/handoff /plan"` -> `(None, "/plan")` (unknown slash token stops scan).
6. No `handoff` token -> `None` (incl. non-leading `"keep /handoff"`).
7. Generalization regression: the full `4669620` compact parser matrix stays
   green through the shared implementation.

Loop-level dispatch tests (extend `tests/test_telegram_compact_dispatch.py`):

8. TRUE-compaction engine (claude-class double), `/handoff` reply -> approval
   card WITH buttons; NOTHING runs (no native compact, no run).
9. approve -> phase 1 `run(handoff_prompt)` on the old token; phase 2 seed
   run with `resume=None`; store flips to the new token; completion message.
10. `/handoff` on a handoff engine -> identical flow as `/compact` there.
11. decline -> no runs; store unchanged.
12. `/handoff` with no resolvable session -> guidance reply.
13. `/handoff keep tests` with batch debounce > 0 -> NOT batched
    (`CONTROL_COMMANDS`).
14. Registration: `should_handle_as_meta_command("handoff", ...)` is True;
    `build_bot_commands` contains a `handoff` entry.
15. Regression: `/compact` on a true-compaction engine stays immediate
    (no approval gate); `/compact` selector-ordering tests stay green.

### Task B - Implementation (GREEN)

**B1. Parser generalization (`telegram/commands/parse.py`).** Add
`parse_command_invocation(text, *, flag: str, engine_ids)`; re-implement
`parse_compact_invocation` as a one-line delegate (`flag="compact"`) so the
`4669620` tests keep passing; add
`parse_handoff_invocation(...) = parse_command_invocation(..., flag="handoff")`.
Pathological combos are deterministic and documented: `/handoff /compact`
-> handoff with instructions `"/compact"`; `/compact /handoff` -> compact
with instructions `"/handoff"` (first flag wins, second becomes text).

**B2. Registration (parity with compact, nothing more):**
`meta_args.py` `_PURE_META` += `"handoff"`; `menu.py` command tuple +=
`("handoff", "new session with handoff summary")`;
`prompt_batch.py` `CONTROL_COMMANDS` += `"handoff"`.
No `ids.py` change: `compact` is intentionally absent from
`RESERVED_CHAT_COMMANDS`; keep `handoff` unreserved for identical dispatch
behavior. Re-export the new parser/handler via `commands/handlers.py`.

**B3. Handler entry (`telegram/commands/compact.py`).**
`handle_compact_command(..., force_handoff: bool = False)`: when True, skip
the `compact_support()` branch entirely and route every engine to the
approval gate. No support modes are evaluated on the `/handoff` path.

**B4. Approval text variants (`compact.py`).** One builder, two templates:
- no-compaction engines (either command): the Task 1 text with the
  "cannot compact natively" explanation;
- true-compaction engines (`/handoff` only): neutral variant - "start a NEW
  session with a handoff summary instead of compacting in place? Takopi will:
  1) ask the agent for a handoff summary, 2) seed a new session with it,
  3) route future messages there. [approve handoff] [cancel]".

**B5. `route_message` hook (`loop.py`).** Immediately after the compact hook:
`handoff_invocation = parse_handoff_invocation(...)`; on match: cancel the
batch key (mirrors compact), `tg.start_soon(handle_compact, instructions,
engine, force_handoff=True, ...)`, return. Order: compact hook first, then
handoff (deterministic for pathological combos).

**B6. Callback/executor: NO changes.** The confirm callback already enqueues
`ThreadJob(kind="handoff")`; `run_handoff_job` is engine-agnostic.

### Task C - Docs and roadmap

- `docs/reference/commands-and-directives.md`: `/handoff` row + the
  `/compact` vs `/handoff` contract block.
- `docs/how-to/compact-session.md`: short `/handoff` section linking the
  handoff-migration behavior.
- `changelog.md`: entry.
- `ROADMAP.md`: mark Task 7 as specced (link this file; narrow patch).

### Task D - Verification gate

```
uv run pytest tests/test_telegram_handoff_command.py tests/test_telegram_compact_dispatch.py tests/test_telegram_compact_command.py tests/test_telegram_prompt_batch.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

Live e2e (single instance, verified artifact): `/handoff` on a claude session
-> approval card (neutral wording) -> approve -> summary -> new session ->
routing flipped; `/compact` on the same engine still compacts in place.

## Files touched

- M `src/takopi/telegram/commands/parse.py` (generalized parser + wrappers)
- M `src/takopi/telegram/commands/compact.py` (`force_handoff`, approval text
  variants)
- M `src/takopi/telegram/commands/handlers.py` (re-exports)
- M `src/takopi/telegram/commands/meta_args.py` (`_PURE_META`)
- M `src/takopi/telegram/commands/menu.py` (menu entry)
- M `src/takopi/telegram/prompt_batch.py` (`CONTROL_COMMANDS`)
- M `src/takopi/telegram/loop.py` (handoff hook, immediately after compact)
- M `tests/test_telegram_compact_command.py` or A
  `tests/test_telegram_handoff_command.py`; M
  `tests/test_telegram_compact_dispatch.py`
- M docs + `changelog.md` + `ROADMAP.md` (specced marker)

## Risks and pitfalls

- Do not disturb the Task 1 executor; this spec adds entry points only. If the
  Task 1 implementation renamed any symbol referenced here, update the
  references, not the design.
- Parser generalization must keep the `4669620` compact matrix byte-identical
  in behavior (delegate, do not rewrite).
- Approval wording must not claim the engine "cannot compact" when the user
  explicitly chose `/handoff` on a compaction-capable engine.
- Batcher, meta-command registry, and menu must all gain `handoff` together;
  a missing one produces silent misrouting (the 2026-08-04 batcher lesson).
- Do not commit unless the user explicitly asks.