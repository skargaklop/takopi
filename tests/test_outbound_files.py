"""Tests for agent → user outbound file markers and plan auto-file."""

from __future__ import annotations

from pathlib import Path

from takopi.outbound_files import (
    OutboundSettings,
    append_send_instruction,
    parse_send_markers,
    process_outbound_answer,
    settings_from_files_config,
    write_plan_auto_file,
)
from takopi.settings import TelegramFilesSettings


def _settings(**kwargs) -> OutboundSettings:
    base = OutboundSettings(
        enabled=True,
        send_enabled=True,
        send_extensions=(
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
        ),
        deny_globs=(".git/**", ".env", "*.pem"),
        max_bytes=50 * 1024 * 1024,
        max_files=10,
        plan_require_send=True,
        plan_auto_file=True,
        outgoing_dir="outgoing",
    )
    if not kwargs:
        return base
    data = {
        "enabled": base.enabled,
        "send_enabled": base.send_enabled,
        "send_extensions": base.send_extensions,
        "deny_globs": base.deny_globs,
        "max_bytes": base.max_bytes,
        "max_files": base.max_files,
        "plan_require_send": base.plan_require_send,
        "plan_auto_file": base.plan_auto_file,
        "outgoing_dir": base.outgoing_dir,
    }
    data.update(kwargs)
    return OutboundSettings(**data)


def test_default_whitelist_from_settings() -> None:
    cfg = TelegramFilesSettings()
    assert cfg.send_enabled is True
    assert ".md" in cfg.send_extensions
    assert ".html" in cfg.send_extensions
    assert ".pdf" in cfg.send_extensions
    ob = settings_from_files_config(cfg)
    # send inactive until files.enabled
    assert ob.active is False
    cfg2 = TelegramFilesSettings(enabled=True)
    assert settings_from_files_config(cfg2).active is True


def test_parse_send_markers_strips_and_collects() -> None:
    text = (
        "Here is the plan.\n"
        "[[takopi-send: docs/plan.md]]\n"
        "And a sheet.\n"
        "[[takopi-send: out/data.xlsx]]\n"
    )
    cleaned, paths = parse_send_markers(text)
    assert paths == ["docs/plan.md", "out/data.xlsx"]
    assert "takopi-send" not in cleaned
    assert "Here is the plan." in cleaned
    assert "And a sheet." in cleaned


def test_process_allows_md_within_root(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "plan.md").write_text("# Plan\n", encoding="utf-8")
    answer = "Done.\n[[takopi-send: docs/plan.md]]\n"
    result = process_outbound_answer(
        answer, run_root=tmp_path, settings=_settings(), plan_mode=False
    )
    assert len(result.files) == 1
    assert result.files[0].ok
    assert result.files[0].content is not None
    assert result.files[0].content.replace(b"\r\n", b"\n") == b"# Plan\n"
    assert "sent:" in result.answer
    assert "[[takopi-send" not in result.answer


def test_process_rejects_bad_extension(tmp_path: Path) -> None:
    (tmp_path / "x.exe").write_bytes(b"MZ")
    result = process_outbound_answer(
        "[[takopi-send: x.exe]]",
        run_root=tmp_path,
        settings=_settings(),
    )
    assert result.files[0].ok is False
    assert "extension" in (result.files[0].error or "")


def test_process_rejects_deny_glob(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    result = process_outbound_answer(
        "[[takopi-send: .env]]",
        run_root=tmp_path,
        settings=_settings(send_extensions=(".env", ".md")),
    )
    # .env is deny_glob *. not necessarily - deny has ".env"
    assert result.files[0].ok is False


def test_process_rejects_escape(tmp_path: Path) -> None:
    result = process_outbound_answer(
        "[[takopi-send: ../secret.md]]",
        run_root=tmp_path,
        settings=_settings(),
    )
    assert result.files[0].ok is False


def test_max_files_cap(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"f{i}.md").write_text(f"{i}", encoding="utf-8")
    answer = "\n".join(f"[[takopi-send: f{i}.md]]" for i in range(3))
    result = process_outbound_answer(
        answer,
        run_root=tmp_path,
        settings=_settings(max_files=2),
    )
    ok = [f for f in result.files if f.ok]
    assert len(ok) == 2
    assert any("limit" in n for n in result.notes)


def test_plan_mode_auto_file(tmp_path: Path) -> None:
    answer = "1. Do A\n2. Do B\n"
    result = process_outbound_answer(
        answer,
        run_root=tmp_path,
        settings=_settings(),
        plan_mode=True,
    )
    assert result.plan_satisfied is True
    autos = [f for f in result.files if f.auto and f.ok]
    assert len(autos) == 1
    assert autos[0].rel_path.startswith("outgoing/plan-")
    assert autos[0].rel_path.endswith(".md")
    assert (tmp_path / autos[0].rel_path).is_file()


def test_plan_mode_marker_satisfies(tmp_path: Path) -> None:
    (tmp_path / "plan.md").write_text("# p\n", encoding="utf-8")
    result = process_outbound_answer(
        "[[takopi-send: plan.md]]\nsee above",
        run_root=tmp_path,
        settings=_settings(),
        plan_mode=True,
    )
    assert result.plan_satisfied is True
    assert not any(f.auto for f in result.files)


def test_plan_mode_no_auto_warns(tmp_path: Path) -> None:
    result = process_outbound_answer(
        "just text plan",
        run_root=tmp_path,
        settings=_settings(plan_auto_file=False),
        plan_mode=True,
    )
    assert result.plan_satisfied is False
    assert any("requires" in n for n in result.notes)


def test_append_send_instruction_plan() -> None:
    s = _settings()
    out = append_send_instruction("fix it", settings=s, plan_mode=True)
    assert "[[takopi-send:" in out
    assert "PLAN MODE" in out
    assert "fix it" in out


def test_inactive_when_files_disabled(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    result = process_outbound_answer(
        "[[takopi-send: a.md]]",
        run_root=tmp_path,
        settings=_settings(enabled=False),
    )
    assert result.files == ()
    # Markers left as plain text when files.enabled is false (no send).
    assert "[[takopi-send: a.md]]" in result.answer
