"""Tests for the minimal ACP (Agent Client Protocol) JSON-RPC stdio client.

Uses an in-memory transport pair to avoid spawning real subprocesses.
"""

from __future__ import annotations


import pytest

from takopi.runners._acp import (
    AcpClient,
    AcpCommandUnavailableError,
    FakeAcpTransport,
)


@pytest.mark.anyio
async def test_initialize_sends_client_info() -> None:
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize",
        {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}},
    )
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()

    sent = transport.requests
    assert sent[0]["method"] == "initialize"
    assert sent[0]["params"]["clientInfo"]["name"] == "takopi"


@pytest.mark.anyio
async def test_resume_or_load_uses_session_load() -> None:
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()
    await client.resume_or_load("sid-123")

    load_req = transport.requests[1]
    assert load_req["method"] == "session/load"
    assert load_req["params"]["sessionId"] == "sid-123"


@pytest.mark.anyio
async def test_available_commands_enables_compact() -> None:
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()
    await client.resume_or_load("sid")
    transport.emit_notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "compact"}, {"name": "edit"}],
            }
        },
    )
    commands = await client.wait_for_available_commands()
    assert "compact" in commands
    await client.require_command("compact")  # should not raise


@pytest.mark.anyio
async def test_compact_requires_advertised_command() -> None:
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()
    await client.resume_or_load("sid")
    transport.emit_notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "edit"}],
            }
        },
    )
    await client.wait_for_available_commands()

    with pytest.raises(AcpCommandUnavailableError):
        await client.require_command("compact")


@pytest.mark.anyio
async def test_prompt_sends_compact_text() -> None:
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    transport.queue_response(
        "session/prompt",
        {"stopReason": "stop"},
    )
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()
    await client.resume_or_load("sid")
    transport.emit_notification(
        "session/update",
        {
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "compact"}],
            }
        },
    )
    await client.wait_for_available_commands()

    events = [update async for update in client.prompt("sid", "/compact keep tests")]

    prompt_req = [r for r in transport.requests if r["method"] == "session/prompt"][0]
    contents = prompt_req["params"]["prompt"]
    assert contents[0]["text"] == "/compact keep tests"
    assert len(events) >= 1
    assert events[-1].stop_reason == "stop"


@pytest.mark.anyio
async def test_no_session_new_in_compact_path() -> None:
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()
    await client.resume_or_load("sid")


@pytest.mark.anyio
async def test_protocol_version_rejection() -> None:
    """Agent selecting a non-1 protocol version raises AcpProtocolError."""
    from takopi.runners._acp import AcpProtocolError

    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize",
        {"protocolVersion": 99, "agentCapabilities": {"loadSession": True}},
    )
    client = AcpClient(command="fake", args=[], transport=transport)
    with pytest.raises(AcpProtocolError, match="unsupported protocol version"):
        await client.initialize()


@pytest.mark.anyio
async def test_resume_or_load_exact_params() -> None:
    """session/load params include cwd and mcpServers."""
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    client = AcpClient(command="fake", args=[], cwd="/tmp/test", transport=transport)
    await client.initialize()
    await client.resume_or_load("mysession")

    load_req = [r for r in transport.requests if r["method"] == "session/load"][0]
    params = load_req["params"]
    assert params["sessionId"] == "mysession"
    assert params["cwd"] == "/tmp/test"
    assert params["mcpServers"] == []


@pytest.mark.anyio
async def test_stop_reason_failure() -> None:
    """A non-end_turn stop reason yields a failed AcpUpdate."""
    transport = FakeAcpTransport()
    transport.queue_response(
        "initialize", {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}}
    )
    transport.queue_response("session/load", {})
    transport.queue_response("session/prompt", {"stopReason": "refusal"})
    client = AcpClient(command="fake", args=[], transport=transport)
    await client.initialize()
    await client.resume_or_load("sid")

    events = [u async for u in client.prompt("sid", "/compact")]
    assert len(events) == 1
    assert events[0].stop_reason == "refusal"
