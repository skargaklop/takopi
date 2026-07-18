from __future__ import annotations

from takopi.runners.codex import CodexRunner
from takopi.runners.omp import OmpRunner
from takopi.runners.pi import PiRunner
from takopi.runners.run_options import (
    EngineRunOptions,
    PromptAttachment,
    apply_run_options,
    merge_run_options,
)
from takopi.settings import TelegramFilesSettings
from takopi.telegram.files import (
    format_image_prompt_annotation,
    image_upload_path,
    is_image_document,
)


def test_files_settings_image_defaults() -> None:
    cfg = TelegramFilesSettings()
    assert cfg.image_subdir == "images"
    assert cfg.image_default_prompt == "Describe this image."
    assert cfg.image_force_prompt is True


def test_is_image_document_mime_and_photo() -> None:
    assert is_image_document(
        mime_type="image/png", file_name="x.bin", raw=None
    )
    assert is_image_document(
        mime_type=None, file_name="shot.JPG", raw=None
    )
    assert is_image_document(
        mime_type=None, file_name=None, raw={"width": 100, "height": 80}
    )
    assert not is_image_document(
        mime_type="application/pdf", file_name="a.pdf", raw=None
    )


def test_image_upload_path_is_unique_under_subdir() -> None:
    p1 = image_upload_path("incoming", "images", "photo.jpg", None)
    p2 = image_upload_path("incoming", "images", "photo.jpg", None)
    assert p1.parts[:2] == ("incoming", "images")
    assert p1.suffix == ".jpg"
    assert p1 != p2


def test_format_image_prompt_annotation() -> None:
    single = format_image_prompt_annotation(["incoming/images/a.jpg"])
    assert "[image]" in single
    assert "incoming/images/a.jpg" in single
    multi = format_image_prompt_annotation(
        ["incoming/images/a.jpg", "incoming/images/b.png"]
    )
    assert "[images]" in multi
    assert "b.png" in multi


def test_merge_run_options_attachments() -> None:
    base = EngineRunOptions(model="m", reasoning="high")
    att = PromptAttachment(
        rel_path="incoming/images/a.jpg",
        abs_path=r"D:\proj\incoming\images\a.jpg",
        kind="image",
    )
    merged = merge_run_options(base, attachments=(att,))
    assert merged is not None
    assert merged.model == "m"
    assert merged.attachments == (att,)


def test_codex_build_args_includes_image_flags() -> None:
    runner = CodexRunner(codex_cmd="codex", extra_args=[], title="codex")
    att = PromptAttachment(
        rel_path="incoming/images/a.jpg",
        abs_path=r"C:\proj\incoming\images\a.jpg",
        kind="image",
    )
    with apply_run_options(EngineRunOptions(attachments=(att,))):
        args = runner.build_args("hello", None, state=None)
    assert "-i" in args
    assert r"C:\proj\incoming\images\a.jpg" in args


def test_pi_build_args_includes_at_path() -> None:
    runner = PiRunner(extra_args=[], model=None, provider=None)
    state = runner.new_state("hi", None)
    att = PromptAttachment(
        rel_path="incoming/images/a.jpg",
        abs_path="/tmp/a.jpg",
        kind="image",
    )
    with apply_run_options(EngineRunOptions(attachments=(att,))):
        args = runner.build_args("what color?", None, state=state)
    assert "@incoming/images/a.jpg" in args
    assert args[-1] == "what color?"


def test_omp_build_args_includes_at_path() -> None:
    runner = OmpRunner(extra_args=[], model=None, provider=None)
    att = PromptAttachment(
        rel_path="incoming/images/b.png",
        abs_path="/tmp/b.png",
        kind="image",
    )
    with apply_run_options(EngineRunOptions(attachments=(att,))):
        args = runner.build_args("describe", None, state=runner.new_state("x", None))
    assert "@incoming/images/b.png" in args
