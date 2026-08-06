import pytest

from takopi.telegram.chat_prefs import ChatPrefsStore


@pytest.mark.anyio
async def test_chat_prefs_store_roundtrip(tmp_path) -> None:
    path = tmp_path / "telegram_chat_prefs_state.json"
    store = ChatPrefsStore(path)
    await store.set_default_engine(123, "codex")
    await store.set_trigger_mode(123, "mentions")
    await store.set_default_engine(123, "codex")
    await store.clear_default_engine(456)

    assert await store.get_default_engine(123) == "codex"
    assert await store.get_trigger_mode(123) == "mentions"

    store2 = ChatPrefsStore(path)
    assert await store2.get_default_engine(123) == "codex"
    assert await store2.get_trigger_mode(123) == "mentions"

    await store2.clear_default_engine(123)
    assert await store2.get_default_engine(123) is None
    assert await store2.get_trigger_mode(123) == "mentions"

    await store2.clear_trigger_mode(123)
    assert await store2.get_trigger_mode(123) is None


@pytest.mark.anyio
async def test_subagent_sticky_roundtrip(tmp_path) -> None:
    path = tmp_path / "telegram_chat_prefs_state.json"
    store = ChatPrefsStore(path)
    await store.set_subagent(123, "reviewer")
    assert await store.get_subagent(123) == "reviewer"
    # Persists across instances.
    store2 = ChatPrefsStore(path)
    assert await store2.get_subagent(123) == "reviewer"


@pytest.mark.anyio
async def test_subagent_sticky_clear(tmp_path) -> None:
    path = tmp_path / "telegram_chat_prefs_state.json"
    store = ChatPrefsStore(path)
    await store.set_subagent(123, "reviewer")
    await store.set_subagent(123, None)
    assert await store.get_subagent(123) is None


@pytest.mark.anyio
async def test_subagent_sticky_empty_string_clears(tmp_path) -> None:
    path = tmp_path / "telegram_chat_prefs_state.json"
    store = ChatPrefsStore(path)
    await store.set_subagent(123, "reviewer")
    await store.set_subagent(123, "   ")
    assert await store.get_subagent(123) is None


@pytest.mark.anyio
async def test_subagent_sticky_unknown_chat_returns_none(tmp_path) -> None:
    store = ChatPrefsStore(tmp_path / "state.json")
    assert await store.get_subagent(999) is None


@pytest.mark.anyio
async def test_subagent_sticky_does_not_isolate_plan_mode(tmp_path) -> None:
    """Setting subagent should not interfere with plan_mode or vice versa."""
    path = tmp_path / "telegram_chat_prefs_state.json"
    store = ChatPrefsStore(path)
    await store.set_plan_mode(123, True)
    await store.set_subagent(123, "reviewer")
    assert await store.get_plan_mode(123) is True
    assert await store.get_subagent(123) == "reviewer"
    # Clearing subagent keeps plan_mode.
    await store.set_subagent(123, None)
    assert await store.get_subagent(123) is None
    assert await store.get_plan_mode(123) is True
