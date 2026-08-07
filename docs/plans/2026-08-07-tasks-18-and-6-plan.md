# Tasks 18 and 6 Implementation Plan

> **For agentic workers:** Execute in order with TDD. Task 18 must establish a zero-diagnostic checkpoint before Task 6 changes begin.

## Context

ROADMAP Task 18 requires reducing `ty check src tests` from 41 diagnostics to zero by correcting annotations, protocols, narrowing, assignments, and return paths rather than suppressing errors. ROADMAP Task 6 requires replacing the fake-only ACP client boundary with a production stdio JSON-RPC subprocess transport, while retaining `handoff_only` independently for Grok and OMP until each harness proves true `/compact` interception end to end.

Order the type cleanup first so ACP lands on a zero-diagnostic baseline. The end state is zero `ty` diagnostics, a production-capable and cross-platform ACP transport, and honest per-harness compaction capability based only on recorded live evidence.

## Approach

### 1. Establish and preserve a zero-diagnostic baseline (Task 18)

Run `uv run ty check src tests` first and retain the captured 41-diagnostic inventory as the checklist. Fix source contracts before test-only narrowing. Do not change type-checker rules or add `# type: ignore`, `cast(Any, ...)`, or equivalent suppressions.

1. Correct the seven source-side gaps:
   - `src/takopi/runners/_compact_mixin.py`: add a private structural protocol containing `compact_accepts_instructions: bool` and `run(prompt: str, resume: ResumeToken | None) -> AsyncIterator[TakopiEvent]`; annotate the `self` parameter of both mixin `compact()` methods with that protocol. Do not add a concrete `run()` stub because mixin-first MRO would intercept the real runner.
   - `src/takopi/runners/_acp.py`: apply the same self-protocol pattern for `engine: EngineId`, `compact_accepts_instructions`, and `create_acp_client()`. Step 2 replaces the remaining `Any` client/transport surface.
   - `src/takopi/telegram/commands/compact.py`: narrow `ref.message_id` before using it as a `dict[tuple[int, int], PendingCompactConfirm]` key. Telegram confirmation IDs must be integers; raise `RuntimeError("telegram compact confirmation returned a non-integer message id")` for the generic transport's `str` case rather than silently losing confirmation state.
   - `src/takopi/telegram/commands/meta_args.py`: return `False` after the known pure-meta and dual-mode branches so unknown commands satisfy the declared `bool` contract and continue through normal prompt routing.
   - `src/takopi/telegram/commands/reply.py`: define a named reply callable protocol with keyword parameters matching actual callsites and awaited result `MessageRef | None`, matching `send_plain()`.
   - `src/takopi/telegram/loop.py::handle_reload`: bind `reload.settings.transports.telegram` once and use `telegram.model_dump() if telegram is not None else {}`. An absent Telegram table is a restart-required transport change, not an attribute access on `None`.
   - `src/takopi/utils/subprocess.py`: introduce a platform-neutral `_kill_process_group(pid: int, sig: signal.Signals) -> None` helper that calls the dynamically resolved `os.killpg`; `_signal_process()` calls it only on POSIX. Add unit cases for success, `ProcessLookupError`, and generic `OSError`, preserving the existing process-method fallback and process-tree behavior.
2. Correct test annotations and fakes without weakening assertions:
   - Type both `prompt_batch_separator` parameters in `tests/telegram_fakes.py` as `Literal["newline", "blank_line"]`, and `_chat_cfg.session_mode` in `tests/test_telegram_prompt_batch_integration.py` as `Literal["stateless", "chat"]`.
   - Replace `tests/test_outbound_files.py::_settings(**kwargs)` with explicit keyword-only overrides for the only exercised fields: `enabled: bool | None`, `send_extensions: tuple[str, ...] | None`, `max_files: int | None`, and `plan_auto_file: bool | None`; use `dataclasses.replace` on the base value.
   - In settings tests, bind `telegram = settings.transports.telegram`, assert non-`None`, then inspect fields. In doctor tests, bind/assert `detail` before substring checks. In compact/OpenCode tests, bind and assert concrete `StartedEvent`/`CompletedEvent` values before reading `.resume` or `.ok`.
   - In `tests/test_telegram_compact_dispatch.py`, make `FakeTransport` implement `Transport.delete`; give `FakeBot.answer_callback_query` the exact optional `text`/`show_alert` parameters and `bool` return; replace the invalid `TakopiEvent()` alias construction with a successful `CompletedEvent` carrying the supplied resume token.
   - In `tests/test_compact_event_invariants.py`, test `AcpCompactMixin` with a dedicated typed fake runner rather than assigning `_acp_transport` to `GrokRunner`, which currently inherits `HandoffCompactMixin`.
3. After each root-cause group, run its focused test file and `uv run ty check src tests`. Task 18 is complete only at `All checks passed!` with zero diagnostics.

### 2. Replace the fake-only ACP boundary with a production stdio transport (Task 6)

Refactor `src/takopi/runners/_acp.py` around a typed, sequential JSON-RPC v1 transport. No reusable JSON-RPC stdio transport exists in the repository; reuse `manage_subprocess`, `drain_stderr`, AnyIO streams, and the global lifecycle timeouts rather than adding a dependency.

1. Introduce exact transport contracts:
   - `type JsonObject = dict[str, Any]`.
   - `class AcpTransport(Protocol)` with async `start()`, `close()`, `send_request(request: JsonObject) -> Any`, and `read_notification() -> JsonObject | None`.
   - `class AcpProtocolError(RuntimeError)` for invalid framing, EOF, response correlation failures, timeouts, protocol-version mismatch, and JSON-RPC errors.
   - `@dataclass(slots=True) class SubprocessAcpTransport` with `command`, `args`, `cwd`, `env`, `close_timeout_s`, and `request_timeout_s`.
2. `SubprocessAcpTransport.start()` manually enters `manage_subprocess([command, *args], stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=cwd, env=env, close_timeout=close_timeout_s)`, retains that context until `close()`, validates all three pipes, creates one persistent `BufferedByteReceiveStream` for stdout, and drains stderr in a retained AnyIO task group. `close()` is idempotent: close stdin, cancel/join the stderr task, then exit the managed-process context. `manage_subprocess` remains responsible for shielded process-tree termination, wait, and bounded stream cleanup on normal exit, exception, and cancellation.
3. Encode every outgoing object as compact UTF-8 JSON plus exactly one `b"\n"`. Serialize requests with an AnyIO lock; the client permits one in-flight request. While awaiting its matching response ID:
   - queue `session/update` notifications in receive order;
   - answer an unexpected server request carrying `method` and `id` with JSON-RPC `-32601 Method not found` so unsupported client capabilities cannot deadlock the agent;
   - reject non-object messages, malformed response objects, a different response ID, EOF before response, and JSON-RPC `error` with `AcpProtocolError`;
   - treat stderr as logs only, never as protocol framing.
4. Update `FakeAcpTransport` to implement no-op `start()`/`close()` while preserving request recording and queued responses. Change `AcpClient.transport` to `AcpTransport | None`; `_resolve_transport()` lazily constructs `SubprocessAcpTransport` from the client fields.
5. Make `AcpClient` an async context manager. `__aenter__` starts the resolved transport and `__aexit__` always closes it. `AcpCompactMixin.compact()` uses `async with self.create_acp_client()`.
6. Correct the existing ACP v1 wire contract:
   - Send `initialize` with protocol version 1 and reject a selected version other than 1 using `AcpProtocolError("ACP agent selected unsupported protocol version: <value>")`.
   - `session/load` and `session/resume` params are exactly `{"sessionId": session_id, "cwd": cwd or os.getcwd(), "mcpServers": []}`. Never call `session/new` during compaction.
   - Parse commands only from `method == "session/update"`, `params.update.sessionUpdate == "available_commands_update"`, and `params.update.availableCommands[].name`. Remove the flattened fake-only notification shape and update all fixtures.
   - Send `session/prompt` with `sessionId` and one text content block containing `compact_prompt(instructions)`.
   - Map `agent_message_chunk` to accumulated answer text; `agent_thought_chunk` to note actions; `tool_call`/`tool_call_update` to tool actions; and `plan` to turn actions. The prompt response supplies the terminal stop reason. Only `end_turn` succeeds; cancellation, refusal, unknown/missing stop reason, or a missing final response yields `CompletedEvent(ok=False, resume=resume, error=...)`.
7. Apply `request_timeout_s` to every request and to `wait_for_available_commands()`. Command-advertisement timeout/EOF raises `AcpCommandUnavailableError("ACP agent did not advertise available commands")`; request timeout raises `AcpProtocolError("ACP <method> request timed out")`. Reuse global `RunnerSettings.startup_timeout_s`; do not add engine-specific settings.

### 3. Wire each harness only after independent live proof

The installed entry points are `grok agent stdio` and `omp acp`. Implement candidate factories and probes, but change capability reporting only for a harness whose own smoke passes.

1. Add `shutdown_timeout_s: float = DEFAULT_SHUTDOWN_TIMEOUT_S` to `JsonlSubprocessRunner`, pass it to existing `manage_subprocess(close_timeout=...)`, and propagate `RunnerSettings.shutdown_timeout_s` in `runtime_loader.build_router` beside startup/idle/retry settings. This closes the existing gap between documented configuration and runtime use.
2. Candidate factories:
   - Grok: `AcpClient(command=self.grok_cmd, args=["agent", "stdio"], cwd=os.getcwd(), close_timeout_s=self.shutdown_timeout_s, request_timeout_s=self.startup_timeout_s or 60.0)`.
   - OMP: `AcpClient(command=self.command(), args=["acp"], cwd=os.getcwd(), close_timeout_s=self.shutdown_timeout_s, request_timeout_s=self.startup_timeout_s or 60.0)`.
   Unit tests assert exact command/args/cwd/timeouts and absence of `session/new`.
3. Add and register one `@pytest.mark.live_acp` smoke per engine. Require the CLI on PATH plus an existing session ID from `TAKOPI_GROK_ACP_SESSION_ID` or `TAKOPI_OMP_ACP_SESSION_ID`; otherwise skip. Initialize, load/resume, require advertised `compact`, send `/compact takopi-live-smoke-<uuid>`, and fail if the marker appears in any `agent_message_chunk`. Genuine interception additionally requires an explicit harness compaction lifecycle/update or another documented harness signal discovered during research; `end_turn`, silence, or token heuristics alone are insufficient.
4. Run probes independently and save CLI version, exact command, sanitized transcript, advertised commands, and interception signal under `docs/reference/runners/grok/acp-compact.md` and `docs/reference/runners/omp/acp-compact.md`. Record failed/unsupported findings too, dated 2026-08-06 or the actual verification date.
5. For each passing engine, replace `HandoffCompactMixin` with `AcpCompactMixin`, report `mode="acp"`/`true_compaction=True`, and convert only that engine's unit expectations to ACP. For each skipped or failing engine, keep `HandoffCompactMixin`, `mode="handoff_only"`, and `true_compaction=False`; do not attach an unused concrete factory. One engine's evidence never enables the other.
6. Validate `resume.engine == self.engine` before starting. Thereafter preserve exactly one `StartedEvent`, one final `CompletedEvent`, and identical resume tokens. Missing load/resume capability, missing command advertisement, protocol error, unsuccessful stop reason, launch failure, and cancellation close the subprocess and yield a clean failed completion; they never create a session or fall back to the normal headless `/compact` prompt.
7. Update `docs/reference/plugin-api.md`, `docs/reference/specification.md`, both runner pages, and `changelog.md` to match the evidence-backed per-engine state. Remove blanket “test-only ACP” language only after the production transport exists.

## Critical files & anchors

- `ROADMAP.md:219-243` — Task 6 requirements and independent evidence gate.
- `ROADMAP.md:647-676` — Task 18 zero-diagnostic contract.
- `src/takopi/runners/_acp.py:33-245` — fake-only transport resolution, client protocol, compact lifecycle.
- `src/takopi/runners/_compact_mixin.py:16-66` — missing structural `run()` contract.
- `src/takopi/utils/subprocess.py:18-192` — bounded teardown and cross-platform process-tree signaling.
- `src/takopi/runner.py:196-200,738-745` — lifecycle attributes and subprocess close timeout.
- `src/takopi/runtime_loader.py:164-173` — global timeout propagation.
- `src/takopi/runners/grok.py:411-444` and `src/takopi/runners/omp.py:70-114` — current handoff inheritance and factory command inputs.
- `tests/test_acp_client.py` — protocol/client tests; replace flattened notifications with official envelopes.
- `tests/test_acp_compact_runners.py` — per-engine capability, factory, and invariant tests.
- `tests/test_subprocess.py`, `tests/test_subprocess_close.py` — transport shutdown and Windows proactor regressions.
- Task 18 diagnostic files: `src/takopi/telegram/commands/{compact,meta_args,reply}.py`, `src/takopi/telegram/loop.py`, `tests/telegram_fakes.py`, and `tests/test_{acp_compact_runners,cli_doctor,compact_event_invariants,compact_slash_mixin,opencode_compact,outbound_files,settings,settings_contract,telegram_compact_dispatch,telegram_prompt_batch_integration}.py`.

## TDD execution sequence

1. Fix Task 18 one root-cause group at a time: focused failing test/diagnostic, minimal source correction, focused pass, then rerun `ty`.
2. Add failing transport tests for newline framing, monotonic/matching IDs, notification interleaving, server-request `-32601`, JSON-RPC errors, malformed input, EOF, timeout, idempotent close, launch failure, cancellation, and process exit; implement minimally.
3. Add failing client/mixin tests for version rejection, exact load/resume params, no `session/new`, command gating before prompt, update mapping, stop-reason failure, resume-engine validation, and event invariants; implement minimally.
4. Add failing runner factory/timeout tests, implement global propagation and candidate factories, then run fake-subprocess integration tests.
5. Run marked live probes and apply the independent Grok/OMP decision. Convert only passing harness expectations and documentation.

## Verification

Set `PYTHONUTF8=1` for every Windows command.

1. Task 18 checkpoint:
   - `uv run ty check src tests` → exit 0, `All checks passed!`, zero diagnostics.
   - `uv run pytest -q --no-cov tests/test_cli_doctor.py tests/test_compact_event_invariants.py tests/test_compact_slash_mixin.py tests/test_opencode_compact.py tests/test_outbound_files.py tests/test_settings.py tests/test_settings_contract.py tests/test_subprocess.py tests/test_telegram_compact_dispatch.py tests/test_telegram_prompt_batch_integration.py` → all pass.
2. ACP checkpoint:
   - `uv run pytest -q --no-cov tests/test_acp_client.py tests/test_acp_compact_runners.py tests/test_compact_event_invariants.py tests/test_subprocess.py` → all pass.
   - `uv run pytest -q --no-cov tests/test_subprocess_close.py` on Windows, macOS, and Linux → all pass with no `Exception ignored`, `unclosed transport`, leaked child, or teardown hang. This target must pass even though the previous broad regression excluded it.
3. Independent evidence:
   - `uv run pytest -q --no-cov -m live_acp tests/test_grok_compact_acp.py` with `TAKOPI_GROK_ACP_SESSION_ID` → pass enables Grok ACP; skip/fail retains Grok handoff-only.
   - `uv run pytest -q --no-cov -m live_acp tests/test_omp_compact_acp.py` with `TAKOPI_OMP_ACP_SESSION_ID` → pass enables OMP ACP; skip/fail retains OMP handoff-only.
   - For each enabled harness, invoke `/compact takopi-live-smoke-<uuid>` through the bridge against that existing session and observe acknowledgement plus honest completion; the marker must be absent from assistant output and the saved transcript must contain the explicit interception signal.
4. Final regression:
   - `uv run ruff format --check .` and `uv run ruff check .` → exit 0.
   - `uv run ty check src tests` → zero diagnostics.
   - `uv run pytest -q --ignore=tests/test_subprocess_close.py` → no regressions, while retaining the separate targeted cross-platform result above.
   - After the lifecycle fix, `uv run pytest -q` on Windows, macOS, and Linux → all pass without ACP pipe-finalizer warnings.

## Assumptions & contingencies

- Verified locally on 2026-08-06: `grok agent stdio --help` and `omp acp --help` exist. This proves entry points only, not compact advertisement or interception.
- ACP framing and command envelopes are protocol facts: UTF-8 newline-delimited JSON-RPC 2.0 on stdio; commands arrive inside `session/update.params.update`; compaction attaches to an existing session and never calls `session/new`.
- Specific `usage_update`/`compaction_update` names and payloads are **unverified — confirm first** against each harness's sanitized live transcript or source before encoding smoke assertions. If neither harness exposes an explicit compaction signal, both remain handoff-only even though the production transport ships.
- `session/load` versus `session/resume` remains capability-driven. A harness advertising neither for an existing session is unsupported and remains handoff-only.
- stdout is protocol-only; stderr is drained/logged. Bounded, shielded cleanup must run under cancellation.
- Existing regression evidence is 1014 passed, 1 skipped with `tests/test_subprocess_close.py` excluded. Task 6 touches that lifecycle, so this file becomes a required targeted and cross-platform gate, not an accepted exclusion.
