"""Minimal ACP (Agent Client Protocol) JSON-RPC stdio client.

Used only for ``/compact`` on ACP-capable runners (grok, omp). The client
communicates over JSON-RPC 2.0, using stdio in production and an in-memory
transport pair (:class:`FakeAcpTransport`) in tests.

Protocol flow for compact::

    initialize -> session/load or session/resume -> require advertised compact
    -> session/prompt with /compact text -> map updates to Takopi events

``session/new`` is never used in the compact path.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..logging import get_logger

logger = get_logger(__name__)


class AcpCommandUnavailableError(RuntimeError):
    """Raised when the ACP agent does not advertise a required command."""


@dataclass(slots=True)
class AcpUpdate:
    """A decoded ACP session update, ready for translation to Takopi events."""

    kind: str  # "message" | "thought" | "tool" | "plan" | "stop"
    text: str = ""
    stop_reason: str | None = None


class FakeAcpTransport:
    """In-memory transport for testing without a real subprocess.

    Records all outgoing JSON-RPC requests and allows tests to queue
    responses and emit notifications.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses: dict[str, Any] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._id_counter = itertools.count(1)

    def queue_response(self, method: str, result: Any) -> None:
        self._responses[method] = result

    def emit_notification(self, method: str, params: dict[str, Any]) -> None:
        self._notifications.put_nowait({"method": method, "params": params})

    async def send_request(self, request: dict[str, Any]) -> Any:
        self.requests.append(request)
        method = request["method"]
        if method in self._responses:
            return self._responses.pop(method)
        return {}

    async def read_notification(self) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._notifications.get(), timeout=5.0)
        except TimeoutError:
            return None


@dataclass
class AcpClient:
    command: str
    args: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    transport: Any = None  # FakeAcpTransport for tests; None uses subprocess
    _id_counter: itertools.count[int] = field(
        default_factory=lambda: itertools.count(1), init=False, repr=False
    )
    _available_commands: set[str] = field(default_factory=set, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)

    async def initialize(self) -> None:
        from .. import __version__ as _ver

        result = await self._request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientInfo": {"name": "takopi", "version": _ver},
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
        self._init_result = result
        self._initialized = True

    async def resume_or_load(self, session_id: str) -> None:
        caps = (
            self._init_result.get("agentCapabilities", {}) if self._init_result else {}
        )
        if caps.get("loadSession"):
            await self._request("session/load", {"sessionId": session_id})
        else:
            session_caps = caps.get("sessionCapabilities", {})
            if session_caps.get("resume") is not None:
                await self._request("session/resume", {"sessionId": session_id})
            else:
                raise AcpCommandUnavailableError(
                    "ACP agent cannot load/resume sessions"
                )

    async def wait_for_available_commands(self) -> set[str]:
        """Block until ``available_commands_update`` arrives; return names."""
        while True:
            notification = await self._read_notification()
            if notification is None:
                raise AcpCommandUnavailableError(
                    "ACP agent did not send available_commands_update"
                )
            if notification["method"] == "available_commands_update":
                commands = notification["params"].get("availableCommands", [])
                self._available_commands = {
                    cmd.get("name", "") for cmd in commands if cmd.get("name")
                }
                return self._available_commands

    async def require_command(self, name: str) -> None:
        if name not in self._available_commands:
            raise AcpCommandUnavailableError(f"ACP agent did not advertise '{name}'")

    async def prompt(self, session_id: str, text: str) -> AsyncIterator[AcpUpdate]:
        result = await self._request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        )
        # Drain notifications until we get the prompt result.
        # For v1 simplicity, the result is the stop reason.
        stop_reason = result.get("stopReason") if isinstance(result, dict) else None
        yield AcpUpdate(kind="stop", stop_reason=stop_reason)

    # --- internals ---

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        request = {
            "jsonrpc": "2.0",
            "id": next(self._id_counter),
            "method": method,
            "params": params,
        }
        transport = self._resolve_transport()
        return await transport.send_request(request)

    async def _read_notification(self) -> dict[str, Any] | None:
        transport = self._resolve_transport()
        return await transport.read_notification()

    def _resolve_transport(self) -> Any:
        if self.transport is not None:
            return self.transport
        raise RuntimeError("Subprocess ACP transport not yet implemented")


class AcpCompactMixin:
    """Compact via ACP ``session/prompt`` after capability-gating."""

    compact_accepts_instructions: bool = True
    _acp_transport: Any = None  # injected for tests; None in production

    def compact_support(self) -> Any:
        from ..compact import CompactSupport

        return CompactSupport(
            mode="acp",
            accepts_instructions=self.compact_accepts_instructions,
            true_compaction=True,
            note="ACP compact requires advertised compact command",
        )

    async def compact(
        self,
        resume: Any,
        instructions: str | None = None,
    ) -> Any:
        from ..events import EventFactory
        from ..compact import compact_prompt

        engine = self.engine
        factory = EventFactory(engine)
        yield factory.started(
            resume,
            title=f"{engine} compact",
            meta={"compact": {"mode": "acp", "true_compaction": True}},
        )
        try:
            client = self.create_acp_client()
            await client.initialize()
            await client.resume_or_load(resume.value)
            await client.wait_for_available_commands()
            await client.require_command("compact")
            async for _update in client.prompt(
                resume.value, compact_prompt(instructions)
            ):
                pass
            yield factory.completed_ok(
                answer=f"{engine} compaction completed.",
                resume=resume,
            )
        except Exception as exc:  # noqa: BLE001
            yield factory.completed(
                ok=False,
                answer="",
                resume=resume,
                error=str(exc),
            )

    def create_acp_client(self) -> AcpClient:
        """Create an AcpClient. Override in concrete runners."""
        return AcpClient(
            command="",
            args=[],
            transport=self._acp_transport,
        )
