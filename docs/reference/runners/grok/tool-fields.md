# Grok CLI Tool Names and rawInput Fields

Recorded from real streaming-json captures
(`stream-sample-tools.jsonl`, `stream-sample-agentic.jsonl`, and live
observation of the Grok Build CLI). These field names drive the
`_grok_tool_kind_and_title` adapter — no guessing.

## Tool name → canonical mapping

The shared helper (`tool_kind_and_title`) knows claude-style names. Grok
uses different names, so the adapter translates them first:

| Grok tool name | Canonical name | Shared helper result |
|----------------|----------------|----------------------|
| `run_terminal_command` | `bash` | `command`, title = relativized command |
| `read_file` | `read` | `tool`, title = `` `read: '<path>'` `` |
| `search_replace` | `edit` | `file_change`, title = relativized path |
| `write` | `edit` | `file_change`, title = relativized path |
| `list_dir` | `ls` | `tool`, title = `` `ls: '<path>'` `` |
| `grep` | `grep` | `tool`, title = pattern |
| `todo_write` | `todowrite` | `note`, title = "update todos" |
| `spawn_subagent` | `task` | `subagent`, title = description/prompt |
| `kill_command_or_subagent` | — | generic fallback `(tool, name)` |
| `get_command_or_subagent_output` | — | generic fallback `(tool, name)` |

## rawInput field → normalized field mapping

The shared helper looks up path keys (`file_path`, `path`, etc.). Grok
uses `target_file` / `target_directory`, so the adapter normalizes:

| Grok field | Normalized field | Used by |
|------------|-----------------|---------|
| `target_file` | `file_path` | read, edit (search_replace, write) |
| `target_directory` | `path` | ls (list_dir) |
| `command` | `command` (pass-through) | bash (run_terminal_command) |
| `pattern` | `pattern` (pass-through) | grep |
| `description` | `description` (pass-through) | task (spawn_subagent) |
| `prompt` | `prompt` (pass-through) | task (spawn_subagent) |

The normalized dict is merged over the original `rawInput` (normalized
keys take precedence), then passed to `tool_kind_and_title` with
`path_keys=("file_path", "path", "target_file", "target_directory")`.

## Evidence

From `stream-sample-tools.jsonl`:

```json
{"type":"tool_call","toolCallId":"call_2b...","toolName":"list_dir",
 "rawInput":{"target_directory":"."}}

{"type":"tool_call","toolCallId":"call_f03...","toolName":"read_file",
 "rawInput":{"target_file":"pyproject.toml"}}
```

Live observation confirms `run_terminal_command.rawInput.command`,
`grep.rawInput.pattern`, and `spawn_subagent.rawInput.description` /
`.prompt` follow the same shapes as the shared helper expects.
