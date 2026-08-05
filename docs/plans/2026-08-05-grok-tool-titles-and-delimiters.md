# Grok Tool Titles + Narration Delimiter Upgrade - Plan-Spec (Task 13)

> Live evidence 2026-08-05 (pi implementation run):
> 1. Progress shows useless identical lines: "v tool: run_terminal_command"
>    x5, "v tool: get_command_or_subagent_output", "v tool: todo_write" -
>    no actual command/path like other harnesses show (claude: "bash: ls").
> 2. The final message STILL contains narration ("Good progress - 22
>    passed... Let me fix both tests:") concatenated before the real
>    summary - the Task 10 thought-delimited split cannot cut narration
>    inside the trailing text segment.

**Root causes (code-verified):**

- `tool_kind_and_title` (`runners/tool_actions.py`) knows claude names
  (Bash/Read/Edit/Glob/Grep/Task). Grok tool names
  (`run_terminal_command`, `read_file`, `search_replace`, `list_dir`,
  `grep`, `todo_write`, `spawn_subagent`, ...) fall through to the generic
  `("tool", tool_name)` tail (`grok.py:198-201`). Real args live in
  `rawInput` (sample: `{"target_file": "pyproject.toml"}`,
  `{"target_directory": "."}`).
- `_close_text_segment` (`grok.py:120-123`) closes text segments ONLY on
  thought blocks. Narration produced between tool calls stays glued to the
  trailing answer segment -> leaks into the final body.

**Chosen design:**

1. **Grok tool-title adapter (engine-local, reuses the shared helper).**
   `_grok_tool_kind_and_title(tool_name, raw_input)` in `grok.py`:
   - name map: `run_terminal_command`->`bash`, `read_file`->`read`,
     `search_replace`->`edit`, `list_dir`->`ls`, `grep`->`grep`,
     `todo_write`->`todowrite`, `spawn_subagent`->`task`,
     `get_command_or_subagent_output`/unknown -> None (generic fallback).
   - input map: `target_file`->`file_path`, `target_directory`->`path`
     (merged over raw_input), `command`/`pattern`/`description` pass
     through unchanged.
   - delegates to `tool_kind_and_title(canonical, normalized_input,
     path_keys=("file_path","path","target_file","target_directory"))`.
   Result: `command: uv run pytest ...`, `read: \'pyproject.toml\'`,
   `file_change: \'src/...\'`, `ls: \'.\'` - same display contract as
   claude.
2. **Tool events as narration delimiters.** `tool_call` (and
   `tool_call_update`) close the current text segment via the existing
   `_close_text_segment` before emitting their action events. Narration
   between tool calls -> note actions (progress); the trailing text after
   the last delimiter = the answer. This also removes the concatenated
   "strange format" from finals (narration no longer reaches the body).

## Tasks (TDD)

### Task A0 - Field shapes (investigation, read-only)

1. From the existing samples (`stream-sample-tools.jsonl`,
   `stream-sample-agentic.jsonl`) plus one fresh tool-heavy capture if any
   field is missing, record each grok tool\'s `rawInput` keys
   (`run_terminal_command.command`?, `search_replace.target_file`?,
   `grep.pattern`?, `spawn_subagent.description/prompt`?) in
   `docs/reference/runners/grok/tool-fields.md`. Field names drive the
   input map - no guessing.

### Task A - Failing tests (RED)

`tests/test_grok_runner.py` (fixtures from real shapes):

1. `run_terminal_command` (`{"command": "uv run pytest -q"}`) ->
   (`"command"`, title containing `uv run pytest -q`) on start AND complete
   (meta cache reuse).
2. `read_file`/`search_replace`/`list_dir`/`grep` -> read/file_change/ls/
   grep titles with the path/pattern from `target_file`/`target_directory`/
   `pattern`.
3. `todo_write` -> (`"note"`, todos title); unknown tool -> generic
   fallback (regression).
4. Narration between two tool calls -> note action; trailing segment after
   the last tool event = answer (the pi-run paste shape, minimized).
5. No trailing text after the last tool event -> answer falls back to the
   last segment (today\'s rule).
6. Regression: Task 9 coalescing, Task 10 thought-delimited split,
   Task 11 tool action/usage/unknown-type suites stay green.

### Task B - Implementation (GREEN)

**B1. `runners/grok.py`:** `_grok_tool_kind_and_title` adapter (name map +
input normalization) replacing the direct `tool_kind_and_title` call at
the `tool_call` case; meta cache keys unchanged.

**B2. `runners/grok.py`:** `_close_text_segment(state)` invoked in the
`tool_call`/`tool_call_update` cases (after flushing pending thought,
before emitting the tool action).

**B3. Docs:** `docs/reference/runners/grok/tool-fields.md` (A0) +
`runner.md` display-contract note; changelog entry.

### Task C - Verification gate

```
uv run pytest tests/test_grok_runner.py tests/test_grok_schema.py -q
uv run pytest
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check src tests
```

User e2e: any tool-heavy grok run -> progress lines show real
commands/paths like claude ("command: uv run pytest", "read: \'file\'");
the final message contains only the summary.

## Files touched

- M `src/takopi/runners/grok.py` (adapter + segment closing)
- M `tests/test_grok_runner.py`
- A `docs/reference/runners/grok/tool-fields.md`
- M `docs/reference/runners/grok/runner.md`, `changelog.md`

## Risks and pitfalls

- The shared helper stays claude-shaped; ALL grok-specific names/keys live
  in the grok adapter (no grok names leak into `tool_actions.py`).
- Field names come from the A0 capture evidence, never assumptions.
- Do not change `tool_call_meta` caching - `tool_call_update` completion
  must reuse the SAME kind/title as the start event.
- Closing segments on tool events must not reorder the Task 9 thought
  flush (thought note precedes the triggering event).
- Do not commit unless the user explicitly asks.