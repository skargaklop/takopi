from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID

import takopi.runners.grok as grok_runner
from takopi.model import (
    ActionEvent,
    CompletedEvent,
    ResumeToken,
    StartedEvent,
    TakopiEvent,
)
from takopi.runners.grok import (
    ENGINE,
    GrokRunner,
    GrokStreamState,
    translate_grok_event,
)
from takopi.runners.run_options import EngineRunOptions, apply_run_options
from takopi.schemas import grok as grok_schema


def _load_fixture(name: str) -> list[grok_schema.GrokEvent]:
    path = Path(__file__).parent / "fixtures" / name
    return [
        grok_schema.decode_event(line)
        for line in path.read_bytes().splitlines()
        if line.strip()
    ]


def test_grok_resume_format_and_extract() -> None:
    runner = GrokRunner(grok_cmd="grok")
    token = ResumeToken(engine=ENGINE, value="sid")

    assert runner.format_resume(token) == "`grok --resume sid`"
    assert runner.extract_resume("`grok --resume sid`") == token
    assert runner.extract_resume("grok -r other") == ResumeToken(
        engine=ENGINE, value="other"
    )
    assert runner.extract_resume("`claude --resume sid`") is None


def test_is_resume_line() -> None:
    runner = GrokRunner(grok_cmd="grok")
    assert runner.is_resume_line("`grok --resume sid`")
    assert runner.is_resume_line("grok -r sid")
    assert not runner.is_resume_line("`claude --resume sid`")
    assert not runner.is_resume_line("not a resume line")


def test_build_runner_uses_shutil_which(monkeypatch) -> None:
    expected = r"C:\Tools\grok.exe"
    called: dict[str, str] = {}

    def fake_which(name: str) -> str | None:
        called["name"] = name
        return expected

    monkeypatch.setattr(grok_runner.shutil, "which", fake_which)
    runner = cast(GrokRunner, grok_runner.build_runner({}, Path("takopi.toml")))

    assert called["name"] == "grok"
    assert runner.grok_cmd == expected
    assert runner.yolo is True


def test_build_runner_config_fields() -> None:
    runner = cast(
        GrokRunner,
        grok_runner.build_runner(
            {
                "model": "grok-build",
                "yolo": False,
                "tools": ["read_file", "grep"],
                "disallowed_tools": "web_search",
                "reasoning_effort": "high",
                "max_turns": 7,
                "extra_args": ["--no-auto-update"],
            },
            Path("takopi.toml"),
        ),
    )
    assert runner.model == "grok-build"
    assert runner.yolo is False
    assert runner.tools == ["read_file", "grep"]
    assert runner.disallowed_tools == "web_search"
    assert runner.reasoning_effort == "high"
    assert runner.max_turns == 7
    assert runner.extra_args == ["--no-auto-update"]


def test_build_args_new_session_includes_session_id_and_yolo() -> None:
    runner = GrokRunner(
        grok_cmd="grok",
        model="grok-build",
        yolo=True,
        extra_args=["--no-auto-update"],
    )
    session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    args = runner.build_args("hello world", None, state=state)

    assert args[:1] == ["--no-auto-update"]
    assert "-p" in args
    assert args[args.index("-p") + 1] == "hello world"
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "streaming-json"
    assert "--yolo" in args
    assert args[args.index("-m") + 1] == "grok-build"
    assert args[args.index("--session-id") + 1] == session_id
    assert "--resume" not in args


def test_build_args_resume_uses_resume_flag() -> None:
    runner = GrokRunner(grok_cmd="grok", yolo=False)
    resume = ResumeToken(engine=ENGINE, value="sid-resume")
    state = GrokStreamState(resume=resume, started=False)
    args = runner.build_args("continue", resume, state=state)

    assert args[args.index("--resume") + 1] == "sid-resume"
    assert "--session-id" not in args
    assert "--yolo" not in args


def test_build_args_honors_run_options_model_and_reasoning() -> None:
    runner = GrokRunner(grok_cmd="grok", model="default-model", yolo=True)
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        started=False,
    )
    with apply_run_options(EngineRunOptions(model="override-model", reasoning="low")):
        args = runner.build_args("prompt", None, state=state)

    assert args[args.index("-m") + 1] == "override-model"
    assert "--effort" in args or "--reasoning-effort" in args
    effort_flag = "--effort" if "--effort" in args else "--reasoning-effort"
    assert args[args.index(effort_flag) + 1] == "low"


def test_new_state_generates_uuid_for_new_session() -> None:
    runner = GrokRunner(grok_cmd="grok")
    state = runner.new_state("hi", None)
    assert state.resume.engine == ENGINE
    # Must be a valid UUID string for --session-id
    UUID(state.resume.value)
    assert state.started is False


def test_new_state_uses_resume_token() -> None:
    runner = GrokRunner(grok_cmd="grok")
    resume = ResumeToken(engine=ENGINE, value="existing-sid")
    state = runner.new_state("hi", resume)
    assert state.resume == resume


def test_translate_success_fixture() -> None:
    session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list = []
    for event in _load_fixture("grok_stream_success.jsonl"):
        events.extend(
            translate_grok_event(
                event,
                title="grok",
                state=state,
            )
        )

    assert isinstance(events[0], StartedEvent)
    started = events[0]
    assert started.resume.value == session_id

    thoughts = [
        evt
        for evt in events
        if isinstance(evt, ActionEvent) and evt.action.kind == "note"
    ]
    assert thoughts
    assert "Scanning" in thoughts[0].action.title

    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert events[-1] == completed
    assert completed.ok is True
    assert completed.resume == started.resume
    assert completed.answer == "Hello from Grok."
    assert completed.usage is not None
    assert completed.usage.get("num_turns") == 1


def test_translate_error_fixture() -> None:
    session_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list = []
    for event in _load_fixture("grok_stream_error.jsonl"):
        events.extend(
            translate_grok_event(
                event,
                title="grok",
                state=state,
            )
        )

    started = next(evt for evt in events if isinstance(evt, StartedEvent))
    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert events[-1] == completed
    assert completed.ok is False
    assert completed.error is not None
    assert "auth failed" in completed.error
    assert completed.resume == started.resume
    assert "Partial answer" in completed.answer


def test_translate_emits_started_once() -> None:
    session_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list = []
    for payload in (
        b'{"type":"text","data":"a"}',
        b'{"type":"text","data":"b"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"cccccccc-cccc-cccc-cccc-cccccccccccc"}',
    ):
        events.extend(
            translate_grok_event(
                grok_schema.decode_event(payload),
                title="grok",
                state=state,
            )
        )

    started_events = [evt for evt in events if isinstance(evt, StartedEvent)]
    assert len(started_events) == 1
    completed = next(evt for evt in events if isinstance(evt, CompletedEvent))
    assert completed.answer == "ab"


def test_backend_id() -> None:
    assert grok_runner.BACKEND.id == "grok"
    assert grok_runner.BACKEND.cli_cmd == "grok"


# ---------------------------------------------------------------------------
# Stream coalescing: word-granularity thoughts -> one action per thought block
# ---------------------------------------------------------------------------


def _decode(payload: bytes) -> grok_schema.GrokEvent:
    return grok_schema.decode_event(payload)


def _run_events(
    payloads: list[bytes], *, session_id: str = "dddddddd-dddd-dddd-dddd-dddddddddddd"
) -> tuple[list[TakopiEvent], GrokStreamState]:
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    events: list[TakopiEvent] = []
    for payload in payloads:
        events.extend(
            translate_grok_event(
                _decode(payload),
                title="grok",
                state=state,
            )
        )
    return events, state


def test_coalesce_word_granularity_thoughts_into_one_action() -> None:
    """Test 1: N consecutive thought events -> exactly ONE note action."""
    payloads = [
        b'{"type":"thought","data":"The"}',
        b'{"type":"thought","data":" user"}',
        b'{"type":"thought","data":" wants"}',
        b'{"type":"thought","data":" math."}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    actions = [e for e in events if isinstance(e, ActionEvent)]
    assert len(actions) == 1
    assert "The user wants math." in actions[0].action.title


def test_coalesce_thought_text_thought_end_two_actions() -> None:
    """Test 2: thought, thought, text, thought, thought, end -> notes + empty answer.

    With answer/narration split: the 'answer' text between thought blocks is
    narration (not the final answer). It becomes a narration note action, and
    since there is no trailing text after the second thought block, the final
    answer is empty.
    """
    payloads = [
        b'{"type":"thought","data":"first"}',
        b'{"type":"thought","data":" block"}',
        b'{"type":"text","data":"narration"}',
        b'{"type":"thought","data":"second"}',
        b'{"type":"thought","data":" block"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    actions = [e for e in events if isinstance(e, ActionEvent)]
    # Three note actions: first thought block, narration text, second thought block.
    assert len(actions) == 3
    assert "first block" in actions[0].action.title
    assert "narration" in actions[1].action.title
    assert "second block" in actions[2].action.title
    # No trailing text after the last thought block -> empty answer.
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.answer == ""


def test_coalesce_empty_thought_no_action() -> None:
    """Test 3: empty data thought events -> no action, no empty title."""
    payloads = [
        b'{"type":"thought","data":""}',
        b'{"type":"thought","data":""}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    actions = [e for e in events if isinstance(e, ActionEvent)]
    assert len(actions) == 0


def test_coalesce_whitespace_only_thought_no_action() -> None:
    """Test 3b: whitespace-only thought chunks -> flushed title is empty -> no action."""
    payloads = [
        b'{"type":"thought","data":" "}',
        b'{"type":"thought","data":"  "}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    actions = [e for e in events if isinstance(e, ActionEvent)]
    assert len(actions) == 0


def test_coalesce_step_count_regression() -> None:
    """Test 4: word-granularity fixture yields action_count == blocks, not words.

    Real grok CLI emits ~5 word/token chunks per thought block. Without
    coalescing each becomes a separate step. With coalescing, one consecutive
    run of thoughts collapses to exactly one action.
    """
    payloads = [
        b'{"type":"thought","data":"The"}',
        b'{"type":"thought","data":" user"}',
        b'{"type":"thought","data":" wants"}',
        b'{"type":"thought","data":" math."}',
        b'{"type":"thought","data":"Let me compute."}',
        b'{"type":"text","data":"42"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    actions = [e for e in events if isinstance(e, ActionEvent)]
    # Five consecutive word-chunks collapse to ONE action (not 5 steps).
    assert len(actions) == 1
    assert state.note_seq == 1
    assert "The user wants math.Let me compute." in actions[0].action.title


def test_coalesce_thought_flushes_before_end() -> None:
    """Test 5: pending thought flushes BEFORE the completed event."""
    payloads = [
        b'{"type":"thought","data":"thinking"}',
        b'{"type":"thought","data":" hard"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    # The note action must come before the completed event.
    action_indices = [i for i, e in enumerate(events) if isinstance(e, ActionEvent)]
    completed_indices = [
        i for i, e in enumerate(events) if isinstance(e, CompletedEvent)
    ]
    assert len(action_indices) == 1
    assert len(completed_indices) == 1
    assert action_indices[0] < completed_indices[0]


def test_coalesce_text_path_unchanged() -> None:
    """Regression: StreamTextEvent accumulation is byte-identical.

    Single-turn runs (contiguous text, no thoughts interleaved) produce one
    text segment; the answer is the full text — backward compatible.
    """
    payloads = [
        b'{"type":"text","data":"Hello"}',
        b'{"type":"text","data":" from"}',
        b'{"type":"text","data":" Grok."}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
    ]
    events, state = _run_events(payloads)
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.answer == "Hello from Grok."


# ---------------------------------------------------------------------------
# Answer/narration split: final answer contains ONLY the trailing text run;
# earlier text segments (narration) become coalesced note actions.
# ---------------------------------------------------------------------------


def test_narration_split_answer_is_last_text_block() -> None:
    """Test 1: narration, thought, narration, answer, end -> answer == last block only.

    Multiple text segments separated by thoughts. The final answer is the
    trailing text run (after the last thought). Earlier text segments become
    narration note actions.
    """
    payloads = [
        b'{"type":"text","data":"Let me read the plan first."}',
        b'{"type":"thought","data":"Thinking"}',
        b'{"type":"thought","data":" about it"}',
        b'{"type":"text","data":"Now let me check the code."}',
        b'{"type":"thought","data":"Done thinking"}',
        b'{"type":"text","data":"The real answer is 42."}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"}',
    ]
    events, state = _run_events(payloads)
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Answer = trailing text run only.
    assert completed.answer == "The real answer is 42."
    # Narration segments + thoughts become note actions.
    actions = [e for e in events if isinstance(e, ActionEvent)]
    titles = " ".join(a.action.title for a in actions)
    assert "Let me read the plan first." in titles
    assert "Now let me check the code." in titles


def test_narration_split_single_text_block_backward_compat() -> None:
    """Test 2: single text block (math shape) -> answer == full text.

    No thoughts interleaved in the text run. One segment → answer = full text.
    """
    payloads = [
        b'{"type":"text","data":"**391**."}',
        b'{"type":"end","stopReason":"end_turn","sessionId":"ffffffff-ffff-ffff-ffff-ffffffffffff"}',
    ]
    events, state = _run_events(payloads)
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.answer == "**391**."


def test_narration_split_narration_only_stream() -> None:
    """Test 3: narration-only stream -> answer == last segment (today's behavior).

    All text segments are narration (separated by thoughts). The last segment
    is still treated as the answer, same as a run with no clear delimiter.
    """
    payloads = [
        b'{"type":"text","data":"narration one"}',
        b'{"type":"thought","data":"thinking"}',
        b'{"type":"text","data":"narration two"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"11111111-1111-1111-1111-111111111111"}',
    ]
    events, state = _run_events(payloads)
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Last segment is the answer.
    assert completed.answer == "narration two"
    # First narration segment became a note action.
    actions = [e for e in events if isinstance(e, ActionEvent)]
    titles = " ".join(a.action.title for a in actions)
    assert "narration one" in titles


def test_narration_split_empty_whitespace_segments_no_action() -> None:
    """Test 4: empty/whitespace text segments -> no note actions, no empty titles."""
    payloads = [
        b'{"type":"text","data":""}',
        b'{"type":"text","data":"   "}',
        b'{"type":"thought","data":"real thought"}',
        b'{"type":"text","data":"answer"}',
        b'{"type":"end","stopReason":"EndTurn","sessionId":"22222222-2222-2222-2222-222222222222"}',
    ]
    events, state = _run_events(payloads)
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.answer == "answer"
    actions = [e for e in events if isinstance(e, ActionEvent)]
    # Only the thought action (the empty/whitespace text before it was skipped).
    assert len(actions) == 1
    assert "real thought" in actions[0].action.title


def test_narration_split_agentic_sample_end_to_end() -> None:
    """Test 5: replay stream-sample-agentic.jsonl end-to-end.

    Answer == the real final answer from the capture. Narration absent from
    the answer. Step count sane.
    """
    events, state = _run_events(
        [
            line
            for line in (
                Path(__file__)
                .parent.parent.joinpath(
                    "docs",
                    "reference",
                    "runners",
                    "grok",
                    "stream-sample-agentic.jsonl",
                )
                .read_bytes()
                .splitlines()
            )
            if line.strip()
        ],
        session_id="e1f2a3b4-0001-0001-0001-000000000001",
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Answer is the trailing text run only (the ## Summary block).
    assert completed.answer.startswith("## Summary")
    assert "Let me read the plan first" not in completed.answer
    assert "Now let me check" not in completed.answer
    assert "I see the issue" not in completed.answer
    # Narration segments became note actions (sane count, not word-level).
    actions = [e for e in events if isinstance(e, ActionEvent)]
    assert 3 <= len(actions) <= 10  # narration + thought blocks coalesced


def test_narration_split_math_sample_unchanged() -> None:
    """Test 6: replay stream-sample.jsonl (math) -> answer unchanged.

    The math sample has contiguous text (no thoughts interleaved in the text
    phase). Coalescing from Task 9 is intact; answer is the full text.
    """
    events, state = _run_events(
        [
            line
            for line in (
                Path(__file__)
                .parent.parent.joinpath(
                    "docs", "reference", "runners", "grok", "stream-sample.jsonl"
                )
                .read_bytes()
                .splitlines()
            )
            if line.strip()
        ],
        session_id="c0503384-0f14-4c4c-ab09-688ff5a0141d",
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert "**391**." in completed.answer
    assert completed.ok is True


# ---------------------------------------------------------------------------
# Task 11: tool_call / tool_call_update / usage / available_commands mapping
# ---------------------------------------------------------------------------


def test_tool_call_emits_action_started() -> None:
    """Task A.3: tool_call -> action_started with kind/title from shared helper."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-1","toolName":"list_dir",'
            b'"status":"pending","rawInput":{"target_directory":"."}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.id == "call-1"
    # Grok adapter maps list_dir -> canonical "ls" -> kind "tool" with path.
    assert started[0].action.kind == "tool"
    assert "ls" in started[0].action.title.lower()
    assert "." in started[0].action.title


def test_tool_call_bash_emits_command_kind() -> None:
    """Bash tool_call -> kind 'command' with relativized command."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-bash","toolName":"bash",'
            b'"rawInput":{"command":"ls -la"}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "command"
    assert "ls" in started[0].action.title


def test_tool_call_update_completed_completes_action() -> None:
    """Task A.4: tool_call_update (same id, completed) -> action_completed."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-1","toolName":"read_file",'
            b'"rawInput":{"target_file":"foo.txt"}}',
            b'{"type":"tool_call_update","toolCallId":"call-1","status":"completed"}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    completed = [
        e for e in events if isinstance(e, ActionEvent) and e.phase == "completed"
    ]
    assert len(completed) == 1
    assert completed[0].action.id == "call-1"
    assert completed[0].ok is True


def test_tool_call_update_no_duplicate_starts() -> None:
    """Risks: duplicate tool_call for same id must not create a second start."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-1","toolName":"read_file",'
            b'"rawInput":{"target_file":"foo.txt"}}',
            b'{"type":"tool_call","toolCallId":"call-1","toolName":"read_file",'
            b'"rawInput":{"target_file":"foo.txt"}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1


def test_usage_event_merged_into_completed() -> None:
    """Task A.5: mid-stream usage event -> merged into terminal CompletedEvent.usage."""
    events, state = _run_events(
        [
            b'{"type":"usage","usage":{"input_tokens":100,"output_tokens":5}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Mid-stream usage is present in the merged payload.
    assert completed.usage is not None
    mid_usage = completed.usage.get("mid_stream_usage")
    assert mid_usage == {"input_tokens": 100, "output_tokens": 5}


def test_usage_end_event_takes_precedence() -> None:
    """End-event usage wins on conflict over mid-stream usage."""
    events, state = _run_events(
        [
            b'{"type":"usage","usage":{"input_tokens":100,"output_tokens":5}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd",'
            b'"usage":{"input_tokens":999,"output_tokens":42}}',
        ]
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.usage is not None
    # End-event usage is the top-level "usage" key.
    assert completed.usage["usage"]["input_tokens"] == 999
    # Mid-stream usage preserved separately but doesn't override end usage.
    assert completed.usage["mid_stream_usage"]["input_tokens"] == 100


def test_available_commands_no_action_no_warning() -> None:
    """Task A.6: available_commands -> no action, no events."""
    events, state = _run_events(
        [
            b'{"type":"available_commands","tools":["bash"],"commands":[]}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    actions = [e for e in events if isinstance(e, ActionEvent)]
    assert len(actions) == 0


def test_unknown_type_no_action_no_warning() -> None:
    """Forward-compat: unknown type -> no action, no events (tolerated)."""
    events, state = _run_events(
        [
            b'{"type":"mystery","data":"future"}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    actions = [e for e in events if isinstance(e, ActionEvent)]
    assert len(actions) == 0


def test_cancel_stop_reason_maps_to_error() -> None:
    """Task A.8: stopReason=cancelled -> CompletedEvent(ok=False)."""
    events, state = _run_events(
        [
            b'{"type":"end","stopReason":"cancelled","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.ok is False
    assert "cancelled" in (completed.error or "")


def test_tool_sample_end_to_end() -> None:
    """Replay stream-sample-tools.jsonl: tool actions present, zero decode errors."""
    events, state = _run_events(
        [
            line
            for line in (
                Path(__file__)
                .parent.parent.joinpath(
                    "docs", "reference", "runners", "grok", "stream-sample-tools.jsonl"
                )
                .read_bytes()
                .splitlines()
            )
            if line.strip()
        ],
        session_id="c308f091-88a1-4bbb-9bd9-3c4c2f9a60a5",
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)]
    assert len(completed) == 1
    assert completed[0].ok is True
    # Two tool calls (list_dir + read_file) -> at least 2 started + 2 completed actions.
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    completed_actions = [
        e for e in events if isinstance(e, ActionEvent) and e.phase == "completed"
    ]
    assert len(started) >= 2
    assert len(completed_actions) >= 2
    # Usage telemetry present.
    assert completed[0].usage is not None


# ---------------------------------------------------------------------------
# Task 12: plan-mode read-only cancellation message
# ---------------------------------------------------------------------------


def test_plan_mode_cancelled_has_readonly_explanation() -> None:
    """Plan-mode run cancelled by harness -> honest read-only explanation."""
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="dddddddd-dddd-dddd-dddd-dddddddddddd"),
        started=False,
        plan_mode=True,
    )
    events = translate_grok_event(
        grok_schema.decode_event(
            b'{"type":"end","stopReason":"cancelled","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}'
        ),
        title="grok",
        state=state,
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.ok is False
    assert "read-only" in (completed.error or "").lower()
    assert "forbidden" in (completed.error or "").lower()


def test_non_plan_cancelled_keeps_old_message() -> None:
    """Non-plan cancellation keeps the existing message (no mislabeling)."""
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="dddddddd-dddd-dddd-dddd-dddddddddddd"),
        started=False,
        plan_mode=False,
    )
    events = translate_grok_event(
        grok_schema.decode_event(
            b'{"type":"end","stopReason":"cancelled","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}'
        ),
        title="grok",
        state=state,
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    assert completed.ok is False
    assert completed.error == "grok run stopped (cancelled)"


# ---------------------------------------------------------------------------
# Task 13: Grok tool-title adapter + tool events as narration delimiters
# ---------------------------------------------------------------------------


def test_grok_tool_run_terminal_command_maps_to_command() -> None:
    """run_terminal_command -> kind 'command', title contains the command text."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-cmd","toolName":"run_terminal_command",'
            b'"rawInput":{"command":"uv run pytest -q"}}',
            b'{"type":"tool_call_update","toolCallId":"call-cmd","status":"completed"}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "command"
    assert "uv run pytest" in started[0].action.title


def test_grok_tool_read_file_maps_to_read_with_path() -> None:
    """read_file -> kind 'tool', title shows read: '<path>'."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-read","toolName":"read_file",'
            b'"rawInput":{"target_file":"src/main.py"}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "tool"
    assert "read" in started[0].action.title
    assert "src/main.py" in started[0].action.title


def test_grok_tool_search_replace_maps_to_file_change() -> None:
    """search_replace -> kind 'file_change', title shows relativized path."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-edit","toolName":"search_replace",'
            b'"rawInput":{"target_file":"src/takopi/runners/grok.py"}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "file_change"
    assert "grok.py" in started[0].action.title


def test_grok_tool_list_dir_maps_to_ls_with_path() -> None:
    """list_dir -> kind 'tool', title shows ls: '<path>'."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-ls","toolName":"list_dir",'
            b'"rawInput":{"target_directory":"."}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "tool"
    assert "ls" in started[0].action.title.lower()


def test_grok_tool_grep_maps_to_grep_with_pattern() -> None:
    """grep -> kind 'tool', title shows the pattern."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-grep","toolName":"grep",'
            b'"rawInput":{"pattern":"def translate"}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "tool"
    assert "def translate" in started[0].action.title


def test_grok_tool_todo_write_maps_to_note() -> None:
    """todo_write -> kind 'note', title mentions todos."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-todo","toolName":"todo_write",'
            b'"rawInput":{"todos":[]}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "note"
    assert "todo" in started[0].action.title.lower()


def test_grok_tool_spawn_subagent_maps_to_subagent() -> None:
    """spawn_subagent -> kind 'subagent', title shows description."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-sub","toolName":"spawn_subagent",'
            b'"rawInput":{"description":"explore codebase","prompt":"find all tests"}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "subagent"
    assert "explore codebase" in started[0].action.title


def test_grok_tool_unknown_maps_to_generic_fallback() -> None:
    """Unknown tool name -> generic ('tool', tool_name) fallback (regression)."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-unk","toolName":"mystery_tool",'
            b'"rawInput":{}}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    assert len(started) == 1
    assert started[0].action.kind == "tool"
    assert "mystery_tool" in started[0].action.title


def test_grok_tool_call_meta_reused_on_update() -> None:
    """tool_call_update uses the SAME kind/title as the start event."""
    events, state = _run_events(
        [
            b'{"type":"tool_call","toolCallId":"call-reuse","toolName":"run_terminal_command",'
            b'"rawInput":{"command":"echo hi"}}',
            b'{"type":"tool_call_update","toolCallId":"call-reuse","status":"completed"}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    started = [e for e in events if isinstance(e, ActionEvent) and e.phase == "started"]
    completed_acts = [
        e for e in events if isinstance(e, ActionEvent) and e.phase == "completed"
    ]
    assert len(started) == 1
    assert len(completed_acts) == 1
    assert started[0].action.kind == completed_acts[0].action.kind
    assert started[0].action.title == completed_acts[0].action.title


def test_tool_event_closes_text_segment_narration() -> None:
    """Narration between two tool calls -> note action; trailing text = answer.

    The tool_call acts as a narration delimiter, same as a thought event:
    text before the tool call is narration; text after the last tool event
    is the answer.
    """
    events, state = _run_events(
        [
            b'{"type":"text","data":"Let me check the tests."}',
            b'{"type":"tool_call","toolCallId":"t1","toolName":"run_terminal_command",'
            b'"rawInput":{"command":"uv run pytest"}}',
            b'{"type":"tool_call_update","toolCallId":"t1","status":"completed"}',
            b'{"type":"text","data":"All tests passed. Here is the summary."}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Answer = trailing text after the last tool event.
    assert completed.answer == "All tests passed. Here is the summary."
    # Narration before the tool call became a note action.
    actions = [e for e in events if isinstance(e, ActionEvent)]
    narration_notes = [a for a in actions if "Let me check" in a.action.title]
    assert len(narration_notes) == 1


def test_no_trailing_text_after_tool_answer_falls_back() -> None:
    """No trailing text after the last tool event -> answer is empty (no leak)."""
    events, state = _run_events(
        [
            b'{"type":"text","data":"Running tests."}',
            b'{"type":"tool_call","toolCallId":"t1","toolName":"run_terminal_command",'
            b'"rawInput":{"command":"pytest"}}',
            b'{"type":"tool_call_update","toolCallId":"t1","status":"completed"}',
            b'{"type":"end","stopReason":"EndTurn","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}',
        ]
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # No text after the tool event -> empty answer.
    assert completed.answer == ""


# ---------------------------------------------------------------------------
# Task 15: plan-mode cancel prevention + salvage safety net
# ---------------------------------------------------------------------------

_PLAN_CANCEL_NOTE = "turn ended by plan-mode enforcement; nothing was executed"


def test_plan_mode_cancelled_with_plan_text_salvages_to_ok() -> None:
    """Salvage: plan-mode cancel WITH trailing plan text -> ok completion + note.

    The plan is delivered as the answer; the enforcement note is appended.
    Instead of an opaque error, the user gets a usable plan.
    """
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="dddddddd-dddd-dddd-dddd-dddddddddddd"),
        started=False,
        plan_mode=True,
    )
    # Feed text (the plan) then the cancelled end.
    events: list[TakopiEvent] = []
    events.extend(
        translate_grok_event(
            grok_schema.decode_event(
                b'{"type":"text","data":"## Plan\\nStep 1: Do thing."}'
            ),
            title="grok",
            state=state,
        )
    )
    events.extend(
        translate_grok_event(
            grok_schema.decode_event(
                b'{"type":"end","stopReason":"cancelled","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}'
            ),
            title="grok",
            state=state,
        )
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Salvage: ok=True, plan text delivered, note appended to answer.
    assert completed.ok is True
    assert "## Plan" in (completed.answer or "")
    assert _PLAN_CANCEL_NOTE in (completed.answer or "")
    assert completed.error is None


def test_plan_mode_cancelled_with_empty_answer_keeps_task12_error() -> None:
    """Regression: plan-mode cancel with EMPTY answer -> Task-12 honest error."""
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="dddddddd-dddd-dddd-dddd-dddddddddddd"),
        started=False,
        plan_mode=True,
    )
    events = translate_grok_event(
        grok_schema.decode_event(
            b'{"type":"end","stopReason":"cancelled","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}'
        ),
        title="grok",
        state=state,
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Empty answer -> no salvage; keep the Task-12 error.
    assert completed.ok is False
    assert _PLAN_CANCEL_NOTE not in (completed.answer or "")
    assert "read-only" in (completed.error or "").lower()
    assert "forbidden" in (completed.error or "").lower()


def test_non_plan_cancelled_unchanged_by_salvage() -> None:
    """Non-plan cancellation is NOT salvaged even with text (acceptance criterion 4)."""
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="dddddddd-dddd-dddd-dddd-dddddddddddd"),
        started=False,
        plan_mode=False,
    )
    events: list[TakopiEvent] = []
    events.extend(
        translate_grok_event(
            grok_schema.decode_event(b'{"type":"text","data":"partial answer"}'),
            title="grok",
            state=state,
        )
    )
    events.extend(
        translate_grok_event(
            grok_schema.decode_event(
                b'{"type":"end","stopReason":"cancelled","sessionId":"dddddddd-dddd-dddd-dddd-dddddddddddd"}'
            ),
            title="grok",
            state=state,
        )
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Non-plan cancel: old message, ok=False, no salvage note.
    assert completed.ok is False
    assert _PLAN_CANCEL_NOTE not in (completed.answer or "")
    assert completed.error == "grok run stopped (cancelled)"


def test_plan_mode_build_args_uses_native_plan_and_readonly_tools() -> None:
    """Task 16: plan-mode build_args emits native --permission-mode plan AND
    a read-only --tools allow-list. Mutating tools are physically absent so
    the agent cannot trigger an approval prompt -> no cancellation.

    Proven by probe D2 (end_turn, no file, text delivered).
    """
    runner = GrokRunner(grok_cmd="grok", yolo=True)
    session_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value=session_id),
        started=False,
    )
    with apply_run_options(EngineRunOptions(plan=True)):
        args = runner.build_args("do a thing", None, state=state)

    # plan_mode flag is set for salvage purposes.
    assert state.plan_mode is True
    # Native permission-mode plan IS used (hard enforcement).
    assert "--permission-mode" in args
    assert args[args.index("--permission-mode") + 1] == "plan"
    # Read-only tools allow-list restricts the toolset.
    assert "--tools" in args
    tools_val = args[args.index("--tools") + 1]
    for mutating in ("write", "search_replace", "run_terminal_command", "todo_write"):
        assert mutating not in tools_val, f"{mutating} must be excluded in plan mode"
    for readonly in ("read_file", "list_dir", "grep"):
        assert readonly in tools_val, f"{readonly} must be present in plan mode"
    # --yolo is NOT used in plan mode (no auto-approve needed).
    assert "--yolo" not in args


def test_plan_cancel_replay_from_capture_fixture_salvages() -> None:
    """Replay the A0 capture fixture through translate_grok_event on plan_mode=True.

    The fixture (stream-sample-plan-cancel.jsonl) ends with a cancelled end
    after a write tool_call attempt and has trailing plan text. The salvage
    net must fire: ok=True, plan text delivered, note present.
    """
    fixture = (
        Path(__file__)
        .parent.parent.joinpath(
            "docs", "reference", "runners", "grok", "stream-sample-plan-cancel.jsonl"
        )
        .read_bytes()
        .splitlines()
    )
    payloads = [line for line in fixture if line.strip()]
    state = GrokStreamState(
        resume=ResumeToken(engine=ENGINE, value="c0ffee00-plan-cancel-sample"),
        started=False,
        plan_mode=True,
    )
    events: list[TakopiEvent] = []
    for payload in payloads:
        events.extend(
            translate_grok_event(
                grok_schema.decode_event(payload),
                title="grok",
                state=state,
            )
        )
    completed = [e for e in events if isinstance(e, CompletedEvent)][0]
    # Salvage fired: plan text is in the answer, note appended, no error.
    assert completed.ok is True
    assert "Implementation Plan" in (completed.answer or "")
    assert _PLAN_CANCEL_NOTE in (completed.answer or "")
    assert completed.error is None
