from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

import takopi.runners.agy as agy_runner
from takopi.model import ResumeToken
from takopi.runners.agy import ENGINE, AgyRunner, parse_conversation_id


def test_agy_resume_format_and_extract() -> None:
    runner = AgyRunner(agy_cmd="agy")
    token = ResumeToken(engine=ENGINE, value="sid-123")

    assert runner.format_resume(token) == "`agy --conversation sid-123`"
    assert runner.extract_resume("`agy --conversation sid-123`") == token
    assert runner.extract_resume("agy --conversation=other") == ResumeToken(
        engine=ENGINE, value="other"
    )
    # -c is --continue (most recent), not conversation id
    assert runner.extract_resume("agy -c other") is None
    assert runner.extract_resume("`claude --resume sid`") is None


def test_is_resume_line() -> None:
    runner = AgyRunner(agy_cmd="agy")
    assert runner.is_resume_line("`agy --conversation sid`")
    assert runner.is_resume_line("agy --conversation=sid")
    assert not runner.is_resume_line("agy -c sid")
    assert not runner.is_resume_line("`grok --resume sid`")


def test_build_runner_uses_shutil_which(monkeypatch) -> None:
    expected = r"C:\Tools\agy.exe"
    called: dict[str, str] = {}

    def fake_which(name: str) -> str | None:
        called["name"] = name
        return expected

    monkeypatch.setattr(agy_runner.shutil, "which", fake_which)
    runner = cast(AgyRunner, agy_runner.build_runner({}, Path("takopi.toml")))

    assert called["name"] == "agy"
    assert runner.agy_cmd == expected
    assert runner.yolo is True


def test_build_args_new_session() -> None:
    runner = AgyRunner(
        agy_cmd="agy",
        model="gemini-3-pro",
        yolo=True,
        extra_args=["--sandbox"],
    )
    args = runner.build_args("hello", None)

    assert "--sandbox" in args
    assert args[args.index("-p") + 1] == "hello"
    assert args[args.index("--model") + 1] == "gemini-3-pro"
    assert "--dangerously-skip-permissions" in args
    assert "--conversation" not in args


def test_build_args_resume() -> None:
    runner = AgyRunner(agy_cmd="agy", yolo=False)
    resume = ResumeToken(engine=ENGINE, value="conv-1")
    args = runner.build_args("continue", resume)

    assert args[args.index("--conversation") + 1] == "conv-1"
    assert args[args.index("-p") + 1] == "continue"
    assert "--dangerously-skip-permissions" not in args


def test_parse_conversation_id_from_logs() -> None:
    text = "Starting...\nCreated conversation aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\n"
    assert (
        parse_conversation_id(text)
        == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )

    resume_line = "Resume with: agy --conversation bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert (
        parse_conversation_id(resume_line)
        == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )

    assert parse_conversation_id("no id here") is None


def test_new_state_generates_uuid_for_new_session() -> None:
    runner = AgyRunner(agy_cmd="agy")
    state = runner.new_state("hi", None)
    assert state.resume.engine == ENGINE
    UUID(state.resume.value)
    assert state.allow_id_promotion is True


def test_new_state_uses_resume_token() -> None:
    runner = AgyRunner(agy_cmd="agy")
    resume = ResumeToken(engine=ENGINE, value="existing")
    state = runner.new_state("hi", resume)
    assert state.resume == resume
    assert state.allow_id_promotion is False


def test_backend_id() -> None:
    assert agy_runner.BACKEND.id == "agy"
    assert agy_runner.BACKEND.cli_cmd == "agy"


@pytest.mark.anyio
async def test_drain_stderr_start_soon_accepts_positional_args() -> None:
    """Regression: anyio TaskGroup.start_soon rejects kwargs for the task."""
    import anyio

    runner = AgyRunner(agy_cmd="agy")
    state = runner.new_state("hi", None)

    async def fake_stream():
        if False:  # pragma: no cover
            yield b""
        return

    # ByteReceiveStream-like: empty stream ends immediately via IncompleteRead path
    # Exercise start_soon with the same positional signature as run_impl.
    send, recv = anyio.create_memory_object_stream[bytes](1)
    await send.aclose()

    async with anyio.create_task_group() as tg:
        tg.start_soon(runner._drain_stderr_capture, recv, state, "agy")

