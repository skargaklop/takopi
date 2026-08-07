from __future__ import annotations

from pathlib import Path

import pytest

from takopi.schemas import pi as pi_schema


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / name


def _decode_fixture(name: str) -> list[str]:
    path = _fixture_path(name)
    errors: list[str] = []

    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            pi_schema.decode_event(line)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"line {lineno}: {exc.__class__.__name__}: {exc}")

    return errors


@pytest.mark.parametrize(
    "fixture",
    [
        "pi_stream_success.jsonl",
        "pi_stream_error.jsonl",
        "pi_print_mode_events.jsonl",
    ],
)
def test_pi_schema_parses_fixture(fixture: str) -> None:
    errors = _decode_fixture(fixture)
    assert not errors, f"{fixture} had {len(errors)} errors: " + "; ".join(errors[:5])


@pytest.mark.parametrize(
    "fixture",
    [
        "omp_stream_compatibility.jsonl",
        "omp_stream_capacity_error.jsonl",
    ],
)
def test_pi_schema_parses_omp_compat_fixture(fixture: str) -> None:
    """OMP fixtures must fully decode with no validation errors.

    Before Task 22, ``notice`` and float ``delayMs`` lines were dropped with
    ``msgspec.ValidationError``. After Task 2 they decode cleanly:
    ``notice`` becomes ``PiUnknownEvent`` and ``delayMs`` accepts floats.
    """
    errors = _decode_fixture(fixture)
    assert not errors, f"{fixture} had {len(errors)} errors: " + "; ".join(errors[:5])


def test_delay_ms_accepts_int() -> None:
    """Integer delayMs decodes as int (unchanged precision)."""
    event = pi_schema.decode_event(
        '{"type":"auto_retry_start","attempt":1,"maxAttempts":3,"delayMs":1250,"errorMessage":null}'
    )
    assert isinstance(event, pi_schema.AutoRetryStart)
    assert event.delayMs == 1250
    assert isinstance(event.delayMs, int)


def test_delay_ms_accepts_float() -> None:
    """Float delayMs decodes as float (producer emits jittered floats).

    OMP computes retry delays via ``baseDelayMs * 2^(attempt-1) * (1 - random*0.25)``,
    which almost always produces a non-integer float. The schema must preserve
    the producer's precision without rounding or coercion.
    """
    event = pi_schema.decode_event(
        '{"type":"auto_retry_start","attempt":1,"maxAttempts":3,"delayMs":392.19364808040206,"errorMessage":null}'
    )
    assert isinstance(event, pi_schema.AutoRetryStart)
    assert event.delayMs == 392.19364808040206
    assert isinstance(event.delayMs, float)


def test_unknown_tag_notice_becomes_unknown_event() -> None:
    """Unknown valid string tags become PiUnknownEvent, not ValidationError."""
    event = pi_schema.decode_event(
        '{"type":"notice","level":"info","message":"test","source":"system"}'
    )
    assert isinstance(event, pi_schema.PiUnknownEvent)
    assert event.type_name == "notice"


def test_unknown_tag_future_event_becomes_unknown_event() -> None:
    """Synthetic forward-compatible tags also become PiUnknownEvent."""
    event = pi_schema.decode_event('{"type":"future_event","payload":{"x":1}}')
    assert isinstance(event, pi_schema.PiUnknownEvent)
    assert event.type_name == "future_event"


def test_malformed_json_raises_decode_error() -> None:
    """Genuinely malformed JSON still raises msgspec.DecodeError."""
    import msgspec

    with pytest.raises(msgspec.DecodeError):
        pi_schema.decode_event("{not valid json")


def test_missing_type_raises_validation_error() -> None:
    """Missing type field still raises (not silently treated as unknown)."""
    import msgspec

    with pytest.raises(msgspec.ValidationError):
        pi_schema.decode_event('{"foo":"bar"}')


def test_non_string_type_raises_validation_error() -> None:
    """Non-string type still raises (not silently treated as unknown)."""
    import msgspec

    with pytest.raises(msgspec.ValidationError):
        pi_schema.decode_event('{"type":123}')


def test_known_tag_missing_required_field_raises() -> None:
    """Known tag with missing required field still raises ValidationError."""
    import msgspec

    with pytest.raises(msgspec.ValidationError):
        pi_schema.decode_event('{"type":"tool_execution_start","toolName":"read"}')
