# Compacting session context

Long sessions accumulate context. Use `/compact` to reduce it without losing the conversation thread.

## Quick start

Send `/compact` in any chat or topic where Takopi has an active session:

```
/compact
```

You can also pass instructions to focus the compaction:

```
/compact keep the test plan and current blockers
```

Takopi resolves the active session from:

1. The chat/topic's stored session (if any)
2. A reply to a Takopi progress or final message

### Reply context and ordering

- **Reply to any message**: `/compact` works when replying to a final message with a resume footer (e.g. `` `claude resume xyz` ``). The engine is resolved from the footer token.
- **Reply to an active run**: `/compact` waits for the active run to finish, then compacts the same session.
- **Any ordering with engine selectors**: both `/codex /compact` and `/compact /codex` resolve identically — the compact job targets the codex session.
- **Engine precedence**: explicit selector > reply-footer engine > chat/topic default.

## What happens

Takopi enqueues a compact job on the same per-thread scheduler as normal prompts. This means:

- **Serialization**: compact waits for any active run on the same thread to finish.
- **No new session**: compact always operates on an existing `ResumeToken`.
- **Same queue**: a compact job is queued behind pending prompts, and vice versa.

## Engine support

| Engine | Mode | True compaction | Instructions |
|--------|------|-----------------|--------------|
| claude | `slash_prompt` | yes | yes |
| pi | `slash_prompt` | yes | yes |
| codex | `slash_prompt` | yes | no |
| opencode | `native_api` | yes | no |
| grok | `handoff_only` | no (handoff summary) | yes |
| omp | `handoff_only` | no (handoff summary) | yes |
| agy | `handoff_only` | no (handoff summary) | yes |

### Slash-prompt compaction (claude, pi, codex)

Takopi sends `/compact [instructions]` as a normal prompt to the runner. The engine's native `/compact` command handles the actual context reduction.

### Native API compaction (opencode)

Takopi calls the OpenCode server's session compact endpoint directly (`POST /api/session/<id>/compact`), then waits for completion.

### Handoff-only compaction (grok, omp, agy)

These engines do not have a verified true compact command. Instead, Takopi sends a handoff-summary prompt that asks the agent to summarize the session for continuation. This is **not real compaction** — the agent is told not to claim that compaction occurred.

An ACP-based compact path exists in the codebase (`_acp.py`) but is test-only until a subprocess transport is implemented. When available, grok and omp may return to ACP-based true compaction.

## When instructions are not supported

If you pass instructions to an engine that doesn't accept them (e.g., `/compact keep tests` on codex), Takopi warns you and runs compact without the instructions.

## Engines without compaction support

When the target engine does not support compaction (`mode == "none"`), Takopi shows a confirmation message with inline buttons:

- **Send anyway**: sends a plain-text compaction request as a regular prompt (using the `handoff_prompt` builder). This is **not real context reduction** — the agent receives a summary request as a normal message.
- **Cancel**: dismisses the request.

The confirmation ensures you know that the agent will not perform native compaction.

Third-party runners can implement compaction by providing `compact_support()` and `compact()` methods. See the [plugin API reference](../reference/plugin-api.md#compaction) for details.

Runners without compaction support are handled gracefully — Takopi reports that the engine does not support compact.

## Troubleshooting: nothing happens

If `/compact` produces no visible result (no ack, no completion, no error):

1. **Stale installed artifact.** The bridge process may be running an older build. Rebuild:

   ```powershell
   uv tool uninstall takopi
   uv tool install --no-cache .
   ```

2. **Verify the artifact:**

   ```powershell
   # Check that the new code is present in site-packages
   Select-String -Path "%APPDATA%\uv\tools\takopi\Lib\site-packages\takopi\telegram\loop.py" -Pattern "parse_compact_invocation"
   # Check file dates are today
   Get-ChildItem "%APPDATA%\uv\tools\takopi\Lib\site-packages\takopi\telegram\commands\compact.py" | Select-Object LastWriteTime
   ```

3. **Ensure exactly ONE takopi process** before testing:

   ```powershell
   Get-Process -Name "takopi*" -ErrorAction SilentlyContinue | Stop-Process -Force
   ```

4. **Restart the bridge** and retry `/compact`. You should see an ack message ("compacting…" or "creating handoff summary…") within seconds.
