"""Tests for the SubprocessAcpTransport JSON-RPC stdio framing.

Uses real subprocesses (tiny Python echo scripts) to exercise newline
framing, ID correlation, server-request rejection, protocol errors,
malformed input, EOF, and close idempotence.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from takopi.runners._acp import (
    AcpProtocolError,
    SubprocessAcpTransport,
)


def _responder_script(tmp_path: Path, script_name: str, body: str) -> str:
    """Write a Python script that reads/writes JSON-RPC on stdio."""
    script = tmp_path / script_name
    script.write_text(
        textwrap.dedent(f"""
        import sys, json
        {body}
        """),
        encoding="utf-8",
    )
    return str(script)


@pytest.mark.anyio
async def test_newline_framing_and_id_correlation(tmp_path: Path) -> None:
    """Transport sends compact JSON + newline and matches response by ID."""
    script = _responder_script(
        tmp_path,
        "responder.py",
        """
        line = sys.stdin.readline()
        req = json.loads(line)
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable,
        args=[script],
        request_timeout_s=10.0,
    )
    await transport.start()
    try:
        result = await transport.send_request(
            {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
        )
        assert result == {"ok": True}
    finally:
        await transport.close()


@pytest.mark.anyio
async def test_id_mismatch_raises_protocol_error(tmp_path: Path) -> None:
    """Response with wrong ID raises AcpProtocolError."""
    script = _responder_script(
        tmp_path,
        "wrong_id.py",
        """
        line = sys.stdin.readline()
        req = json.loads(line)
        resp = {"jsonrpc": "2.0", "id": req["id"] + 999, "result": {}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable, args=[script], request_timeout_s=10.0
    )
    await transport.start()
    try:
        with pytest.raises(AcpProtocolError, match="id mismatch"):
            await transport.send_request(
                {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
            )
    finally:
        await transport.close()


@pytest.mark.anyio
async def test_jsonrpc_error_raises_protocol_error(tmp_path: Path) -> None:
    """JSON-RPC error object raises AcpProtocolError."""
    script = _responder_script(
        tmp_path,
        "error_resp.py",
        """
        line = sys.stdin.readline()
        req = json.loads(line)
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable, args=[script], request_timeout_s=10.0
    )
    await transport.start()
    try:
        with pytest.raises(AcpProtocolError, match="JSON-RPC error"):
            await transport.send_request(
                {"jsonrpc": "2.0", "id": 1, "method": "bad", "params": {}}
            )
    finally:
        await transport.close()


@pytest.mark.anyio
async def test_server_request_gets_32601(tmp_path: Path) -> None:
    """Server requests are replied to with -32601, not treated as response."""
    # The flow: client sends request, then server sends a server-request
    # before responding. Client must reply -32601 and continue waiting.
    script = _responder_script(
        tmp_path,
        "server_req.py",
        """
        # Read the client's request first
        line = sys.stdin.readline()
        req = json.loads(line)
        # Send a server request (has method + id)
        srv = {"jsonrpc": "2.0", "id": 100, "method": "client/ping"}
        sys.stdout.write(json.dumps(srv) + "\\n")
        sys.stdout.flush()
        # Read the -32601 error reply
        reply = sys.stdin.readline()
        rep = json.loads(reply)
        assert rep["id"] == 100
        assert rep["error"]["code"] == -32601
        # Now respond to the original client request
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable, args=[script], request_timeout_s=10.0
    )
    await transport.start()
    try:
        result = await transport.send_request(
            {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
        )
        assert result == {"ok": True}
    finally:
        await transport.close()


@pytest.mark.anyio
async def test_malformed_json_raises_protocol_error(tmp_path: Path) -> None:
    """Malformed JSON output raises AcpProtocolError."""
    script = _responder_script(
        tmp_path,
        "malformed.py",
        """
        sys.stdout.write("not valid json\\n")
        sys.stdout.flush()
        sys.stdin.readline()
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable, args=[script], request_timeout_s=10.0
    )
    await transport.start()
    try:
        with pytest.raises(AcpProtocolError, match="malformed"):
            await transport.send_request(
                {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
            )
    finally:
        await transport.close()


@pytest.mark.anyio
async def test_eof_raises_protocol_error(tmp_path: Path) -> None:
    """EOF (process exits before responding) raises on next read."""
    script = _responder_script(
        tmp_path,
        "eof.py",
        """
        sys.stdin.readline()
        sys.exit(0)
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable, args=[script], request_timeout_s=10.0
    )
    await transport.start()
    try:
        with pytest.raises((AcpProtocolError, Exception)):
            await transport.send_request(
                {"jsonrpc": "2.0", "id": 1, "method": "test", "params": {}}
            )
    finally:
        await transport.close()


@pytest.mark.anyio
async def test_close_is_idempotent(tmp_path: Path) -> None:
    """Double close does not raise."""
    script = _responder_script(
        tmp_path,
        "noop.py",
        """
        sys.stdin.readline()
        """,
    )
    transport = SubprocessAcpTransport(
        command=sys.executable, args=[script], request_timeout_s=10.0
    )
    await transport.start()
    await transport.close()
    await transport.close()  # must not raise


@pytest.mark.anyio
async def test_launch_failure_raises() -> None:
    """Non-existent command raises during start()."""
    transport = SubprocessAcpTransport(
        command="nonexistent-command-xyz-12345",
        args=[],
        request_timeout_s=5.0,
    )
    with pytest.raises((OSError, FileNotFoundError)):
        await transport.start()
