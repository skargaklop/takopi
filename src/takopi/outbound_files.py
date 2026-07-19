"""Agent → user outbound file delivery (marker protocol + plan auto-file).

Agents write files under the project root and emit::

    [[takopi-send: relative/path/file.ext]]

Takopi validates (whitelist, deny_globs, root, size) and the transport sends
documents. Plan mode can auto-write ``outgoing/plan-*.md`` when no .md/.html
was delivered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Sequence

from .telegram.files import (
    deny_reason,
    normalize_relative_path,
    resolve_path_within_root,
)

# Exact marker line (optional surrounding whitespace).
_SEND_MARKER_RE = re.compile(
    r"(?im)^\s*\[\[takopi-send:\s*(?P<path>[^\]]+?)\s*\]\]\s*$"
)

PLAN_SEND_EXTENSIONS = frozenset({".md", ".html"})


@dataclass(frozen=True, slots=True)
class OutboundFile:
    """A file ready (or attempted) for delivery."""

    rel_path: str
    abs_path: Path | None = None
    content: bytes | None = None
    filename: str | None = None
    ok: bool = True
    error: str | None = None
    auto: bool = False


@dataclass(frozen=True, slots=True)
class OutboundProcessResult:
    answer: str
    files: tuple[OutboundFile, ...] = ()
    notes: tuple[str, ...] = ()
    plan_satisfied: bool | None = None


@dataclass(frozen=True, slots=True)
class OutboundSettings:
    """Subset of transports.telegram.files used for outbound send."""

    enabled: bool = False
    send_enabled: bool = True
    send_extensions: tuple[str, ...] = ()
    deny_globs: tuple[str, ...] = ()
    max_bytes: int = 50 * 1024 * 1024
    max_files: int = 10
    plan_require_send: bool = True
    plan_auto_file: bool = True
    outgoing_dir: str = "outgoing"

    @property
    def active(self) -> bool:
        return bool(self.enabled and self.send_enabled)


def normalize_extension(value: str) -> str:
    ext = value.strip().lower()
    if not ext:
        return ext
    return ext if ext.startswith(".") else f".{ext}"


def parse_send_markers(text: str) -> tuple[str, list[str]]:
    """Return (answer_without_markers, relative_paths in order)."""
    if not text:
        return "", []
    paths: list[str] = []
    kept: list[str] = []
    for line in text.splitlines():
        match = _SEND_MARKER_RE.match(line)
        if match is None:
            kept.append(line)
            continue
        raw = (match.group("path") or "").strip().strip("\"'")
        if raw:
            paths.append(raw)
    cleaned = "\n".join(kept).strip()
    return cleaned, paths


def build_send_instruction(
    *,
    extensions: Sequence[str],
    plan_mode: bool = False,
) -> str:
    ext_list = ", ".join(normalize_extension(e) for e in extensions if e)
    lines = [
        "[Takopi file delivery]",
        "To send a file to the user via Takopi (not Telegram agent tools):",
        "1. Write the file under the project root.",
        "2. Include a line exactly like:",
        "   [[takopi-send: relative/path/to/file.ext]]",
        f"Allowed extensions: {ext_list or '(none configured)'}",
        "Paths must stay inside the project (no absolute paths outside the repo).",
    ]
    if plan_mode:
        lines.extend(
            [
                "PLAN MODE: you MUST produce a plan as a .md (preferred) or .html file",
                "and include a [[takopi-send: ...]] marker for it before finishing.",
            ]
        )
    return "\n".join(lines)


def append_send_instruction(
    prompt: str,
    *,
    settings: OutboundSettings,
    plan_mode: bool = False,
) -> str:
    if not settings.active:
        return prompt
    block = build_send_instruction(
        extensions=settings.send_extensions,
        plan_mode=plan_mode,
    )
    body = prompt.strip()
    if not body:
        return block
    if "[[takopi-send:" in body and "[Takopi file delivery]" in body:
        return prompt
    return f"{body}\n\n{block}"


def _validate_and_load(
    rel_raw: str,
    *,
    run_root: Path,
    settings: OutboundSettings,
) -> OutboundFile:
    allowed = {normalize_extension(e) for e in settings.send_extensions}
    rel = normalize_relative_path(rel_raw)
    if rel is None:
        return OutboundFile(rel_path=rel_raw, ok=False, error="invalid path")
    rel_s = rel.as_posix()
    ext = normalize_extension(rel.suffix)
    if ext not in allowed:
        return OutboundFile(
            rel_path=rel_s, ok=False, error=f"extension not allowed: {ext or '(none)'}"
        )
    denied = deny_reason(rel, settings.deny_globs)
    if denied is not None:
        return OutboundFile(
            rel_path=rel_s, ok=False, error=f"path denied by rule: {denied}"
        )
    target = resolve_path_within_root(run_root, rel)
    if target is None:
        return OutboundFile(rel_path=rel_s, ok=False, error="path escapes project root")
    if not target.is_file():
        return OutboundFile(rel_path=rel_s, ok=False, error="file does not exist")
    try:
        size = target.stat().st_size
        if size > settings.max_bytes:
            return OutboundFile(rel_path=rel_s, ok=False, error="file is too large")
        content = target.read_bytes()
    except OSError as exc:
        return OutboundFile(rel_path=rel_s, ok=False, error=f"read failed: {exc}")
    if len(content) > settings.max_bytes:
        return OutboundFile(rel_path=rel_s, ok=False, error="file is too large")
    return OutboundFile(
        rel_path=rel_s,
        abs_path=target,
        content=content,
        filename=target.name,
        ok=True,
    )


def write_plan_auto_file(
    answer: str,
    *,
    run_root: Path,
    outgoing_dir: str,
) -> OutboundFile:
    """Write cleaned answer to outgoing/plan-<ts>.md under run_root."""
    rel_dir = normalize_relative_path(outgoing_dir) or Path("outgoing")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    rel = rel_dir / f"plan-{stamp}.md"
    target = resolve_path_within_root(run_root, rel)
    if target is None:
        return OutboundFile(
            rel_path=rel.as_posix(),
            ok=False,
            error="outgoing path escapes project root",
            auto=True,
        )
    body = answer.strip() or "# Plan\n\n(empty agent answer)\n"
    if not body.endswith("\n"):
        body += "\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        content = body.encode("utf-8")
    except OSError as exc:
        return OutboundFile(
            rel_path=rel.as_posix(),
            ok=False,
            error=f"write failed: {exc}",
            auto=True,
        )
    return OutboundFile(
        rel_path=rel.as_posix(),
        abs_path=target,
        content=content,
        filename=target.name,
        ok=True,
        auto=True,
    )


def process_outbound_answer(
    answer: str,
    *,
    run_root: Path | None,
    settings: OutboundSettings,
    plan_mode: bool = False,
) -> OutboundProcessResult:
    """Parse markers, load files, optional plan auto-file. Pure (no Telegram)."""
    if not settings.active or run_root is None:
        # Leave markers untouched when outbound send is off.
        return OutboundProcessResult(answer=answer)

    cleaned, marker_paths = parse_send_markers(answer)
    files: list[OutboundFile] = []
    notes: list[str] = []
    seen: set[str] = set()

    for raw in marker_paths:
        if len(files) >= settings.max_files:
            notes.append(
                f"send limit reached ({settings.max_files}); further files skipped."
            )
            break
        key = raw.strip().replace("\\", "/")
        if key in seen:
            continue
        seen.add(key)
        item = _validate_and_load(raw, run_root=run_root, settings=settings)
        files.append(item)
        if item.ok:
            notes.append(f"sent: `{item.rel_path}`")
        else:
            notes.append(f"not sent `{item.rel_path}`: {item.error}")

    plan_satisfied: bool | None = None
    if plan_mode and settings.plan_require_send:
        sent_plan = any(
            f.ok
            and f.rel_path
            and normalize_extension(Path(f.rel_path).suffix) in PLAN_SEND_EXTENSIONS
            for f in files
        )
        if not sent_plan and settings.plan_auto_file:
            auto = write_plan_auto_file(
                cleaned,
                run_root=run_root,
                outgoing_dir=settings.outgoing_dir,
            )
            if auto.ok and len(files) < settings.max_files:
                files.append(auto)
                notes.append(f"sent (plan auto): `{auto.rel_path}`")
                sent_plan = True
            elif not auto.ok:
                notes.append(f"plan auto-file failed: {auto.error}")
        plan_satisfied = sent_plan
        if not sent_plan:
            notes.append(
                "plan mode requires a .md or .html file delivered via "
                "[[takopi-send: path]] (or plan auto-file)."
            )

    if notes:
        note_block = "\n".join(notes)
        final = f"{cleaned}\n\n{note_block}".strip() if cleaned else note_block
    else:
        final = cleaned

    return OutboundProcessResult(
        answer=final,
        files=tuple(files),
        notes=tuple(notes),
        plan_satisfied=plan_satisfied,
    )


def settings_from_files_config(files_cfg: object) -> OutboundSettings:
    """Build OutboundSettings from TelegramFilesSettings (duck-typed)."""
    enabled = bool(getattr(files_cfg, "enabled", False))
    send_enabled = bool(getattr(files_cfg, "send_enabled", True))
    exts = getattr(files_cfg, "send_extensions", None) or list(
        _default_exts_fallback()
    )
    deny = getattr(files_cfg, "deny_globs", None) or []
    max_bytes = int(
        getattr(files_cfg, "max_download_bytes", None) or (50 * 1024 * 1024)
    )
    max_files = int(getattr(files_cfg, "max_send_files_per_run", None) or 10)
    return OutboundSettings(
        enabled=enabled,
        send_enabled=send_enabled,
        send_extensions=tuple(normalize_extension(str(e)) for e in exts),
        deny_globs=tuple(str(g) for g in deny),
        max_bytes=max_bytes,
        max_files=max(1, max_files),
        plan_require_send=bool(getattr(files_cfg, "plan_require_send", True)),
        plan_auto_file=bool(getattr(files_cfg, "plan_auto_file", True)),
        outgoing_dir=str(getattr(files_cfg, "outgoing_dir", None) or "outgoing"),
    )


def _default_exts_fallback() -> list[str]:
    return [
        ".jpg",
        ".png",
        ".gif",
        ".pdf",
        ".md",
        ".html",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
    ]
