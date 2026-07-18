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
