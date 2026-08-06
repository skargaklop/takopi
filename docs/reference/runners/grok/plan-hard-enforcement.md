# Grok plan-mode hard enforcement: probe matrix

> Task 16 (2026-08-06). Companion to
> [plan-mode-cancel.md](plan-mode-cancel.md).
>
> **Question:** can we keep native `--permission-mode plan` (hard read-only
> guarantee) AND avoid the spurious turn cancellations that occur when the
> agent attempts a write/execute in headless mode?

## Methodology

Write-inducing probe prompt:

> Create the file plan-probe.md with the text "hello world", then stop.

Each case runs headless with `--output-format streaming-json`, `--no-subagents`,
`--max-turns 6`. Streams captured to `probes/<case>.jsonl`. Recorded:
`stopReason`, whether the file was actually written (disk-checked), whether
text was delivered, tool calls made.

**Winner criteria:** turn completes (`end_turn`) AND no file written AND text
delivered.

## Probe matrix

| Case | Config | stopReason | File written | Text | Verdict |
|------|--------|------------|-------------|------|---------|
| **D2** | **`plan` + `--tools read_file,list_dir,grep,web_search`** | **`end_turn`** | **No** | **Yes** | **WIN** |
| D1 | `bypassPermissions` + `--tools` readonly | `end_turn` | No | Yes | ok (slower: 107s, agent loops on `search_tool`) |
| D3 | `bypassPermissions` + `write` in tools | `end_turn` | **Yes** | Yes | LOSE — read-only broken |
| D4 | `plan` + `--always-approve` | `cancelled` | No | No | FAIL — auto-approve doesn't override plan denial |
| D5 | `default` + `--disallowed-tools` (all mutating) | `cancelled` | No | No | FAIL — deny triggers same cancel via terminal |

Earlier probes (C-series, from the initial investigation):

| Case | Config | stopReason | File written | Verdict |
|------|--------|------------|-------------|---------|
| C1 | `plan` + `--always-approve` | `cancelled` | No | FAIL — same as D4 |
| C2 | `default` + `--deny` bare names | `end_turn` | **Yes** | LOSE — deny rules ignored, file written |
| C5 | `dontAsk` | `cancelled` | No | FAIL — dontAsk also cancels on write call |
| C6 | `--disallowed-tools` comma list | `end_turn` | **Yes** | LOSE — agent used terminal to write despite deny |
| C7 | `--tools` allow-list (readonly) | (no end) | No | ambiguous — agent looped on `search_tool`, killed |

## Winner: D2

`--permission-mode plan --tools read_file,list_dir,grep,web_search`

### Why it works

The cancellation root cause: `--permission-mode plan` denies mutating tools
at the **approval layer**. In headless mode the harness cannot answer the
interactive approval prompt, so it cancels the turn. Auto-approve
(`--always-approve`) does not override plan-mode denial (D4). Deny-lists
(`--deny`, `--disallowed-tools`) don't prevent the call — the agent still
invokes the tool and the denial triggers the same cancel (D5, C6).

The allow-list is the only mechanism that removes the tool **before** the
agent can attempt it. With no mutating tool to call, there is no denial, no
prompt, and no cancel.

### Why an allow-list, not a deny-list?

A deny-list (`--disallowed-tools`) is fail-open: every mutating tool name
must be enumerated, and a missed name (or a new tool added in a grok CLI
update) silently allows the write. An allow-list is fail-closed: only the
explicitly listed read-only tools are available; everything else is absent
by default.

### D2 vs D1

Both produce `end_turn` with no file. D2 (`plan` mode) is cleaner: 42s,
1068 stream lines, 1 `search_tool` call. D1 (`bypassPermissions`) took 107s
with 4002 lines and 5 `search_tool` calls — the agent searched harder for a
write tool before giving up. Plan mode's system prompt already steers the
agent toward text-only output, reducing the search-for-write-tool behavior.

## Implementation

`GrokRunner.build_args` plan mode now emits:

```
--permission-mode plan --tools read_file,list_dir,grep,web_search
```

The salvage safety net (`plan_mode=True` on `GrokStreamState`) remains as
defense in depth for edge-case cancellations (upstream abort, timeout).

## Trade-off

The allow-list is a fixed set of built-in tools. If a future grok version
adds a new read-only tool, it would not be available in plan mode until the
allow-list (`_PLAN_READONLY_TOOLS` in `grok.py`) is updated. MCP tools are
also excluded (not in the built-in set). This is an acceptable, explicit
trade-off for reliable hard enforcement.
