from __future__ import annotations

from pathlib import Path

import pytest

from takopi.schemas import grok as grok_schema


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _decode_fixture(name: str) -> list[str]:
    path = _fixture_path(name)
    errors: list[str] = []

    for lineno, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            decoded = grok_schema.decode_event(line)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"line {lineno}: {exc.__class__.__name__}: {exc}")
            continue

        _ = decoded

    return errors


@pytest.mark.parametrize(
    "fixture",
    [
        "grok_stream_success.jsonl",
        "grok_stream_error.jsonl",
    ],
)
def test_grok_schema_parses_fixture(fixture: str) -> None:
    errors = _decode_fixture(fixture)

    assert not errors, f"{fixture} had {len(errors)} errors: " + "; ".join(errors[:5])


def test_grok_schema_decodes_known_event_types() -> None:
    text = grok_schema.decode_event(b'{"type":"text","data":"hi"}')
    thought = grok_schema.decode_event(b'{"type":"thought","data":"thinking"}')
    end = grok_schema.decode_event(
        b'{"type":"end","stopReason":"EndTurn","sessionId":"sid-1"}'
    )
    error = grok_schema.decode_event(
        b'{"type":"error","message":"boom","sessionId":"sid-2"}'
    )

    assert isinstance(text, grok_schema.StreamTextEvent)
    assert text.data == "hi"
    assert isinstance(thought, grok_schema.StreamThoughtEvent)
    assert thought.data == "thinking"
    assert isinstance(end, grok_schema.StreamEndEvent)
    assert end.sessionId == "sid-1"
    assert end.stopReason == "EndTurn"
    assert isinstance(error, grok_schema.StreamErrorEvent)
    assert error.message == "boom"


# ---------------------------------------------------------------------------
# New event types (Task 11): tool_call, tool_call_update, usage,
# available_commands, and unknown-type catch-all.
# ---------------------------------------------------------------------------


def test_schema_decodes_tool_call_event() -> None:
    """Task A.1: tool_call decodes into StreamToolCallEvent (no ValidationError)."""
    decoded = grok_schema.decode_event(
        b'{"type":"tool_call","toolCallId":"call-1","toolName":"list_dir",'
        b'"kind":"list","status":"pending","rawInput":{"target_directory":"."}}'
    )
    assert isinstance(decoded, grok_schema.StreamToolCallEvent)
    assert decoded.toolCallId == "call-1"
    assert decoded.toolName == "list_dir"
    assert decoded.rawInput == {"target_directory": "."}


def test_schema_decodes_tool_call_update_event() -> None:
    """Task A.1: tool_call_update decodes into StreamToolCallUpdateEvent."""
    decoded = grok_schema.decode_event(
        b'{"type":"tool_call_update","toolCallId":"call-1","status":"completed"}'
    )
    assert isinstance(decoded, grok_schema.StreamToolCallUpdateEvent)
    assert decoded.toolCallId == "call-1"
    assert decoded.status == "completed"


def test_schema_decodes_usage_event() -> None:
    """Task A.1: usage decodes into StreamUsageEvent."""
    decoded = grok_schema.decode_event(
        b'{"type":"usage","usage":{"input_tokens":100,"output_tokens":5}}'
    )
    assert isinstance(decoded, grok_schema.StreamUsageEvent)
    assert decoded.usage == {"input_tokens": 100, "output_tokens": 5}


def test_schema_decodes_available_commands_event() -> None:
    """Task A.1: available_commands decodes into StreamAvailableCommandsEvent."""
    decoded = grok_schema.decode_event(
        b'{"type":"available_commands","tools":["bash","read"],"commands":[]}'
    )
    assert isinstance(decoded, grok_schema.StreamAvailableCommandsEvent)
    assert decoded.tools == ["bash", "read"]


def test_schema_unknown_type_is_catch_all_no_warning() -> None:
    """Task A.2: unknown future type decodes to StreamUnknownEvent, no raise."""
    decoded = grok_schema.decode_event(b'{"type":"mystery","data":"future"}')
    assert isinstance(decoded, grok_schema.StreamUnknownEvent)
    assert decoded.type_name == "mystery"


def test_schema_unknown_type_missing_type_field() -> None:
    """Forward-compat: object without a type field also becomes unknown."""
    decoded = grok_schema.decode_event(b'{"data":"no-type-key"}')
    assert isinstance(decoded, grok_schema.StreamUnknownEvent)
    assert decoded.type_name == ""


def test_schema_fixture_with_tool_events_decodes_clean() -> None:
    """The tool-heavy fixture (stream-sample-tools.jsonl) decodes with zero errors."""
    path = Path(__file__).parent.parent.joinpath(
        "docs", "reference", "runners", "grok", "stream-sample-tools.jsonl"
    )
    errors: list[str] = []
    for lineno, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            grok_schema.decode_event(line)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"line {lineno}: {exc.__class__.__name__}: {exc}")
    assert not errors, f"{len(errors)} errors: " + "; ".join(errors[:3])
