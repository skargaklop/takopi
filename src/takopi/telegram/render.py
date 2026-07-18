from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from markdown_it import MarkdownIt
from sulguk import transform_html

from ..markdown import MarkdownParts, assemble_markdown_parts

MAX_BODY_CHARS = 3500

# commonmark + GFM strikethrough (~~text~~). Keep html=False so agent/user
# content cannot inject raw HTML. Blockquotes and emphasis are already
# commonmark and map to Telegram blockquote/bold/italic entities via sulguk.
# Extra chat markup (outside code): ||spoiler||, ~strike~, ++underline++.
_MD_RENDERER = MarkdownIt("commonmark", {"html": False}).enable("strikethrough")
_BULLET_RE = re.compile(r"(?m)^(\s*)•")
_FENCE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>[`~]{3,})(?P<info>.*)$")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_ORDERED_ITEM_RE = re.compile(r"^(?P<indent>[ \t]{0,3})(?P<marker>\d+[.)])\s+")
_UNORDERED_ITEM_RE = re.compile(r"^(?P<indent>[ \t]{0,3})[-+*]\s+")

# Telegram-friendly chat extensions (applied outside fenced/inline code).
_FENCED_BLOCK_RE = re.compile(
    r"(?ms)^(?P<indent>[ \t]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n"
    r"(?P<body>.*?)"
    r"^(?P=indent)(?P=fence)[ \t]*$"
)
_INLINE_CODE_RE = re.compile(r"(?P<code>`+)(?P<body>.+?)(?P=code)")
_SPOILER_RE = re.compile(r"\|\|(?P<body>[^|\n]+?)\|\|")
_UNDERLINE_RE = re.compile(r"\+\+(?P<body>[^+\n]+?)\+\+")
_SINGLE_STRIKE_RE = re.compile(r"(?<!~)~(?P<body>[^~\n]+?)~(?!~)")

# Private-use markers survive markdown-it text nodes for post-HTML expansion.
_MARK_SPOILER_OPEN = "\ue010"
_MARK_SPOILER_CLOSE = "\ue011"
_MARK_UNDERLINE_OPEN = "\ue012"
_MARK_UNDERLINE_CLOSE = "\ue013"
_CODE_PLACEHOLDER = "\ue020{0}\ue021"


@dataclass(frozen=True, slots=True)
class _FenceState:
    fence: str
    indent: str
    header: str


def _normalize_nested_list_markers(md: str) -> str:
    if not md:
        return md

    lines: list[str] = []
    ordered_indent: str | None = None
    fence_state: _FenceState | None = None

    for raw_line in md.splitlines(keepends=True):
        line, ending = _split_line_ending(raw_line)
        fence_state = _update_fence_state(line, fence_state)
        if fence_state is not None:
            ordered_indent = None
            lines.append(raw_line)
            continue

        if not line.strip():
            ordered_indent = None
            lines.append(raw_line)
            continue

        ordered_match = _ORDERED_ITEM_RE.match(line)
        if ordered_match is not None:
            ordered_indent = ordered_match.group("indent")
            lines.append(raw_line)
            continue

        if ordered_indent is not None:
            unordered_match = _UNORDERED_ITEM_RE.match(line)
            if (
                unordered_match is not None
                and unordered_match.group("indent") == ordered_indent
            ):
                lines.append(f"{ordered_indent}   {line}{ending}")
                continue

            if line.startswith(ordered_indent) and len(line) > len(ordered_indent):
                lines.append(raw_line)
                continue

            ordered_indent = None

        lines.append(raw_line)

    return "".join(lines)


def _protect_code_regions(md: str) -> tuple[str, list[str]]:
    """Replace fenced blocks and inline code with placeholders (fences first)."""
    buckets: list[str] = []

    def stash(chunk: str) -> str:
        idx = len(buckets)
        buckets.append(chunk)
        return _CODE_PLACEHOLDER.format(idx)

    def stash_fence(match: re.Match[str]) -> str:
        return stash(match.group(0))

    protected = _FENCED_BLOCK_RE.sub(stash_fence, md)

    def stash_inline(match: re.Match[str]) -> str:
        return stash(match.group(0))

    protected = _INLINE_CODE_RE.sub(stash_inline, protected)
    return protected, buckets


def _restore_code_regions(md: str, buckets: list[str]) -> str:
    def restore(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if 0 <= idx < len(buckets):
            return buckets[idx]
        return match.group(0)

    return re.sub(r"\ue020(\d+)\ue021", restore, md)


def _apply_chat_markup_extensions(md: str) -> str:
    """Map Telegram-friendly chat markup to markers / GFM outside code regions."""
    if not md:
        return md
    protected, buckets = _protect_code_regions(md)

    def spoiler(match: re.Match[str]) -> str:
        return f"{_MARK_SPOILER_OPEN}{match.group('body')}{_MARK_SPOILER_CLOSE}"

    def underline(match: re.Match[str]) -> str:
        return f"{_MARK_UNDERLINE_OPEN}{match.group('body')}{_MARK_UNDERLINE_CLOSE}"

    def single_strike(match: re.Match[str]) -> str:
        # Reuse GFM strikethrough so sulguk sees <s>.
        return f"~~{match.group('body')}~~"

    protected = _SPOILER_RE.sub(spoiler, protected)
    protected = _UNDERLINE_RE.sub(underline, protected)
    protected = _SINGLE_STRIKE_RE.sub(single_strike, protected)
    return _restore_code_regions(protected, buckets)


def _expand_chat_markup_markers_in_html(html: str) -> str:
    def spoiler(match: re.Match[str]) -> str:
        return f"<tg-spoiler>{html_lib.escape(match.group(1))}</tg-spoiler>"

    def underline(match: re.Match[str]) -> str:
        return f"<u>{html_lib.escape(match.group(1))}</u>"

    html = re.sub(
        f"{re.escape(_MARK_SPOILER_OPEN)}(.*?){re.escape(_MARK_SPOILER_CLOSE)}",
        spoiler,
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        f"{re.escape(_MARK_UNDERLINE_OPEN)}(.*?){re.escape(_MARK_UNDERLINE_CLOSE)}",
        underline,
        html,
        flags=re.DOTALL,
    )
    return html


def render_markdown(md: str) -> tuple[str, list[dict[str, Any]]]:
    normalized = _normalize_nested_list_markers(md or "")
    expanded = _apply_chat_markup_extensions(normalized)
    html = _MD_RENDERER.render(expanded)
    html = _expand_chat_markup_markers_in_html(html)
    rendered = transform_html(html)

    text = _BULLET_RE.sub(r"\1-", rendered.text)

    entities = _sanitize_entities(rendered.entities)
    return text, entities


def _sanitize_entities(entities: list[Any]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for raw in entities:
        entity = dict(raw)
        if entity.get("type") == "text_link":
            url = entity.get("url")
            if not isinstance(url, str) or not _is_supported_text_link_url(url):
                continue
        sanitized.append(entity)
    return sanitized


def _is_supported_text_link_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and bool(parsed.netloc):
        return True
    return parsed.scheme == "tg" and (bool(parsed.netloc) or bool(parsed.path))


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _split_long_line(line: str, max_chars: int) -> list[str]:
    if len(line) <= max_chars:
        return [line]
    content, ending = _split_line_ending(line)
    parts: list[str] = []
    for idx in range(0, len(content), max_chars):
        chunk = content[idx : idx + max_chars]
        if idx + max_chars >= len(content):
            chunk += ending
        parts.append(chunk)
    if not parts and ending:
        parts.append(ending)
    return parts


def _sentence_units(text: str) -> list[str]:
    units: list[str] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        units.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        units.append(text[start:])
    return [unit for unit in units if unit]


def _split_prose_block(block: str, max_chars: int) -> list[str] | None:
    units = _sentence_units(block)
    if len(units) <= 1:
        return None

    pieces: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_long_line(unit, max_chars))
            continue
        if current and len(current) + len(unit) > max_chars:
            pieces.append(current)
            current = ""
        current += unit
    if current:
        pieces.append(current)
    return pieces


def _has_fence_marker(block: str) -> bool:
    return any(_FENCE_RE.match(line) for line in block.splitlines())


def _split_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    if not _has_fence_marker(block):
        prose_pieces = _split_prose_block(block, max_chars)
        if prose_pieces is not None:
            return prose_pieces
    pieces: list[str] = []
    current = ""
    for line in block.splitlines(keepends=True):
        for part in _split_long_line(line, max_chars):
            if not part:
                continue
            if current and len(current) + len(part) > max_chars:
                pieces.append(current)
                current = ""
            current += part
            if len(current) == max_chars:
                pieces.append(current)
                current = ""
    if current:
        pieces.append(current)
    return pieces


def _update_fence_state(line: str, state: _FenceState | None) -> _FenceState | None:
    match = _FENCE_RE.match(line)
    if match is None:
        return state
    fence = match.group("fence")
    indent = match.group("indent")
    if state is None:
        return _FenceState(fence=fence, indent=indent, header=line)
    if fence[0] == state.fence[0] and len(fence) >= len(state.fence):
        return None
    return state


def _scan_fence_state(text: str, state: _FenceState | None) -> _FenceState | None:
    for line in text.splitlines():
        state = _update_fence_state(line, state)
    return state


def _ensure_trailing_newline(text: str) -> str:
    if text.endswith("\n") or text.endswith("\r"):
        return text
    return text + "\n"


def _close_fence_chunk(text: str, state: _FenceState) -> str:
    return _ensure_trailing_newline(text) + f"{state.indent}{state.fence}\n"


def _reopen_fence_prefix(state: _FenceState) -> str:
    return f"{state.header}\n"


def split_markdown_body(body: str, max_chars: int) -> list[str]:
    if not body or not body.strip():
        return []
    max_chars = max(1, int(max_chars))
    segments = re.split(r"(\n{2,})", body)
    blocks: list[str] = []
    for idx in range(0, len(segments), 2):
        paragraph = segments[idx]
        separator = segments[idx + 1] if idx + 1 < len(segments) else ""
        block = paragraph + separator
        if block:
            blocks.append(block)

    chunks: list[str] = []
    current = ""
    state: _FenceState | None = None
    for block in blocks:
        for piece in _split_block(block, max_chars):
            if not current:
                current = piece
                state = _scan_fence_state(piece, state)
                continue
            if len(current) + len(piece) <= max_chars:
                current += piece
                state = _scan_fence_state(piece, state)
                continue

            if state is not None:
                current = _close_fence_chunk(current, state)
            chunks.append(current)
            current = _reopen_fence_prefix(state) if state is not None else ""
            current += piece
            state = _scan_fence_state(piece, state)

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk.strip()]


def trim_body(body: str | None, *, max_chars: int = MAX_BODY_CHARS) -> str | None:
    if not body:
        return None
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return body if body.strip() else None


def prepare_telegram(parts: MarkdownParts) -> tuple[str, list[dict[str, Any]]]:
    trimmed = MarkdownParts(
        header=parts.header or "",
        body=trim_body(parts.body, max_chars=MAX_BODY_CHARS),
        footer=parts.footer,
    )
    return render_markdown(assemble_markdown_parts(trimmed))


def prepare_telegram_multi(
    parts: MarkdownParts, *, max_body_chars: int = MAX_BODY_CHARS
) -> list[tuple[str, list[dict[str, Any]]]]:
    body = parts.body
    if body is not None and not body.strip():
        body = None
    body_chunks = split_markdown_body(body, max_body_chars) if body is not None else []
    if not body_chunks:
        body_chunks = [""]
    total = len(body_chunks)

    payloads: list[tuple[str, list[dict[str, Any]]]] = []
    for idx, chunk in enumerate(body_chunks, start=1):
        header = parts.header or ""
        if idx > 1:
            if header:
                header = f"{header} · continued ({idx}/{total})"
            else:
                header = f"continued ({idx}/{total})"
        payloads.append(
            render_markdown(
                assemble_markdown_parts(
                    MarkdownParts(header=header, body=chunk, footer=parts.footer)
                )
            )
        )
    return payloads
