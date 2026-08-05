from __future__ import annotations
from dataclasses import dataclass

from ...compact import normalize_instructions
from ...model import EngineId


def is_cancel_command(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    command = stripped.split(maxsplit=1)[0]
    return command == "/cancel" or command.startswith("/cancel@")


def _parse_slash_command(text: str) -> tuple[str | None, str]:
    stripped = text.lstrip()
    if not stripped.startswith("/"):
        return None, text
    lines = stripped.splitlines()
    if not lines:
        return None, text
    first_line = lines[0]
    token, _, rest = first_line.partition(" ")
    command = token[1:]
    if not command:
        return None, text
    if "@" in command:
        command = command.split("@", 1)[0]
    args_text = rest
    if len(lines) > 1:
        tail = "\n".join(lines[1:])
        args_text = f"{args_text}\n{tail}" if args_text else tail
    return command.lower(), args_text


@dataclass(frozen=True, slots=True)
class CompactInvocation:
    """Parsed result of a /compact (or /handoff) invocation with optional engine selector."""

    engine: EngineId | None
    instructions: str | None


def parse_command_invocation(
    text: str,
    *,
    flag: str,
    engine_ids: tuple[EngineId, ...],
) -> CompactInvocation | None:
    """Detect a slash command (``/compact`` or ``/handoff``) in any leading position.

    Scans leading slash tokens (mirroring parse_directives). Recognizes
    exactly one ``flag`` token and at most one engine selector, in any
    order. A second engine selector raises ``ValueError`` (mirrors
    parse_directives "multiple engine directives"). First non-slash or
    unknown slash token stops scanning; the remainder is the instructions.

    Returns ``None`` when no ``flag`` token is found among the leading
    slash tokens.
    """
    stripped = text.lstrip()
    if not stripped.startswith("/"):
        return None

    lines = stripped.splitlines()
    if not lines:
        return None
    first_line = lines[0]
    tokens = first_line.split()
    if not tokens:
        return None

    engine_map = {eid.lower(): eid for eid in engine_ids}

    engine: EngineId | None = None
    found_flag = False
    consumed = 0

    for token in tokens:
        if not token.startswith("/"):
            break
        name = token[1:]
        if "@" in name:
            name = name.split("@", 1)[0]
        if not name:
            break
        key = name.lower()

        if key == flag:
            found_flag = True
            consumed += 1
            continue

        engine_candidate = engine_map.get(key)
        if engine_candidate is not None:
            if engine is not None:
                raise ValueError(f"multiple engine selectors in /{flag}")
            engine = engine_candidate
            consumed += 1
            continue

        # Unknown slash token — stop scanning.
        break

    if not found_flag:
        return None

    # Reconstruct instructions from remaining tokens on this line + following lines.
    remaining_on_line = tokens[consumed:]
    tail_lines = lines[1:]
    parts: list[str] = []
    if remaining_on_line:
        parts.append(" ".join(remaining_on_line))
    if tail_lines:
        parts.append("\n".join(tail_lines))
    raw_instructions = " ".join(parts).strip() if parts else ""
    instructions = normalize_instructions(raw_instructions)

    return CompactInvocation(engine=engine, instructions=instructions)


def parse_compact_invocation(
    text: str,
    *,
    engine_ids: tuple[EngineId, ...],
) -> CompactInvocation | None:
    """Detect a ``/compact`` command. Delegates to :func:`parse_command_invocation`."""
    return parse_command_invocation(text, flag="compact", engine_ids=engine_ids)


def parse_handoff_invocation(
    text: str,
    *,
    engine_ids: tuple[EngineId, ...],
) -> CompactInvocation | None:
    """Detect a ``/handoff`` command. Delegates to :func:`parse_command_invocation`."""
    return parse_command_invocation(text, flag="handoff", engine_ids=engine_ids)
