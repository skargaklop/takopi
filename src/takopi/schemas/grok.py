"""Msgspec models and decoder for Grok headless streaming-json output."""

from __future__ import annotations

from typing import Any

import msgspec


class StreamTextEvent(
    msgspec.Struct, tag="text", tag_field="type", forbid_unknown_fields=False
):
    data: str = ""


class StreamThoughtEvent(
    msgspec.Struct, tag="thought", tag_field="type", forbid_unknown_fields=False
):
    data: str = ""


class StreamEndEvent(
    msgspec.Struct, tag="end", tag_field="type", forbid_unknown_fields=False
):
    stopReason: str | None = None
    sessionId: str | None = None
    requestId: str | None = None
    num_turns: int | None = None
    usage: dict[str, Any] | None = None
    modelUsage: dict[str, Any] | None = None
    total_cost_usd: float | None = None
    total_cost_usd_ticks: int | None = None
    cost_is_partial: bool | None = None
    usage_is_incomplete: bool | None = None


class StreamErrorEvent(
    msgspec.Struct, tag="error", tag_field="type", forbid_unknown_fields=False
):
    message: str = ""
    sessionId: str | None = None
    requestId: str | None = None
    num_turns: int | None = None
    usage: dict[str, Any] | None = None
    modelUsage: dict[str, Any] | None = None
    total_cost_usd: float | None = None
    usage_is_incomplete: bool | None = None


type GrokEvent = (
    StreamTextEvent | StreamThoughtEvent | StreamEndEvent | StreamErrorEvent
)

_DECODER = msgspec.json.Decoder(GrokEvent)


def decode_event(line: str | bytes) -> GrokEvent:
    return _DECODER.decode(line)
