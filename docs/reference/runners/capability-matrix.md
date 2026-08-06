# Subagent / Skill Selection — Capability Matrix

Evidence gathered 2026-08-05 from CLI `--help` output.

| Engine  | Subagent selection                        | Skill activation         | Config key        |
|---------|-------------------------------------------|--------------------------|-------------------|
| grok    | `--agent <NAME>` / `--agents <JSON>`      | via advertised commands  | `[grok] subagent` |
| claude  | `--agent <agent>` / `--agents <json>`     | `/skill-name` in prompt  | `[claude] subagent` |
| codex   | `-p/--profile <name>` (profiles, not agents) | n/a                   | `[codex] subagent` (maps to `--profile`) |
| opencode| `--agent <name>`                          | n/a                      | `[opencode] subagent` |
| pi      | n/a (`-e/--extension <path>` only)        | n/a                      | n/a               |
| omp     | inherits pi flags                         | n/a                      | n/a               |
| agy     | n/a                                      | n/a                      | n/a               |

## Evidence quotes

### grok
```
--agent <NAME>          Agent name or definition file path
--agents <JSON>         Inline subagent definitions as JSON
```

### claude
```
--agent <agent>         Agent for the current session. Overrides the 'agent' setting.
--agents <json>         JSON object defining custom agents
```

### codex
```
-p, --profile <CONFIG_PROFILE_V2>
```

### opencode
```
--agent         agent to use                                          [string]
```

### pi
No named-agent flag. Extensions via `-e/--extension <path>` only.

## Pilot engine

**grok** — best documented `--agent <NAME>` flag, verified via `grok --help`.
Claude follows the same `--agent` pattern. Both wired in Phase 1+2.

## Mapping

Takopi's generic `--subagent <name>` / `/subagent <name>` maps to:
- grok: `--agent <name>`
- claude: `--agent <name>`
- opencode: `--agent <name>`
- codex: `--profile <name>` (best-effort; profiles ≠ agents)
- pi/omp/agy: no-op (clean user-facing note)
