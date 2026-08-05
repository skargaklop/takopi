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

### Handoff-as-new-session (grok, omp, agy, and engines without compaction)

These engines do not have a verified native compact command. Instead of appending a summary to the same session (which grows context), Takopi performs a **handoff to a new session** — actual context reduction, honestly labeled:

1. **Approval gate.** `/compact` shows a message explaining what will happen, with **approve handoff** and **cancel** buttons. Nothing runs until you approve.
2. **Phase 1 — summary.** Takopi asks the agent in the OLD session to produce a handoff summary (goal, decisions, files, next steps).
3. **Phase 2 — new session.** Takopi starts a NEW session seeded with the full summary and a "acknowledge briefly and wait" instruction. The new session ID replaces the old one in routing — future messages go to the new session automatically.
4. **Completion.** A message confirms the handoff, and the summary is echoed (truncated for display). The old session stays available via its resume footer but is no longer the default.

**Important:** after a handoff, send **fresh messages** — do not reply to pre-handoff messages. Replies to old messages still route to the old session via their resume footer.

If phase 1 fails (error or empty summary), no new session is created and the old session remains active.

An ACP-based compact path exists in the codebase (`_acp.py`) but is test-only until a subprocess transport is implemented.

Third-party runners can implement compaction by providing `compact_support()` and `compact()` methods. See the [plugin API reference](../reference/plugin-api.md#compaction) for details.

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
