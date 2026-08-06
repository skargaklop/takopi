from pathlib import Path

import pytest

import takopi.runtime_loader as runtime_loader
from takopi.config import ConfigError
from takopi.settings import TakopiSettings


def test_build_runtime_spec_minimal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runtime_loader.shutil, "which", lambda _cmd: "/bin/echo")
    settings = TakopiSettings.model_validate(
        {
            "transport": "telegram",
            "watch_config": True,
            "transports": {"telegram": {"bot_token": "token", "chat_id": 123}},
        }
    )
    config_path = tmp_path / "takopi.toml"
    config_path.write_text(
        'transport = "telegram"\n\n[transports.telegram]\n'
        'bot_token = "token"\nchat_id = 123\n',
        encoding="utf-8",
    )

    spec = runtime_loader.build_runtime_spec(
        settings=settings,
        config_path=config_path,
    )

    assert spec.router.default_engine == settings.default_engine
    runtime = spec.to_runtime(config_path=config_path)
    assert runtime.default_engine == settings.default_engine
    assert runtime.watch_config is True


def test_resolve_default_engine_unknown(tmp_path: Path) -> None:
    settings = TakopiSettings.model_validate(
        {
            "transport": "telegram",
            "transports": {"telegram": {"bot_token": "token", "chat_id": 123}},
        }
    )
    with pytest.raises(ConfigError, match="Unknown default engine"):
        runtime_loader.resolve_default_engine(
            override="unknown",
            settings=settings,
            config_path=tmp_path / "takopi.toml",
            engine_ids=["codex"],
        )


def test_build_router_propagates_retry_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build_router must propagate retry_max_attempts/retry_base_delay_s onto runners."""
    from takopi.runner import JsonlSubprocessRunner

    monkeypatch.setattr(runtime_loader.shutil, "which", lambda _cmd: "/bin/echo")
    settings = TakopiSettings.model_validate(
        {
            "transport": "telegram",
            "transports": {"telegram": {"bot_token": "token", "chat_id": 123}},
            "runners": {"retry_max_attempts": 5, "retry_base_delay_s": 2.0},
        }
    )
    config_path = tmp_path / "takopi.toml"
    config_path.write_text(
        'transport = "telegram"\n\n[transports.telegram]\n'
        'bot_token = "token"\nchat_id = 123\n',
        encoding="utf-8",
    )

    spec = runtime_loader.build_runtime_spec(
        settings=settings,
        config_path=config_path,
    )

    # Find at least one JSONL runner and verify retry settings propagated.
    jsonl_runners = [
        e.runner
        for e in spec.router.entries
        if isinstance(e.runner, JsonlSubprocessRunner)
    ]
    assert jsonl_runners, "expected at least one JsonlSubprocessRunner"
    for runner in jsonl_runners:
        assert runner.retry_max_attempts == 5
        assert runner.retry_base_delay_s == 2.0
