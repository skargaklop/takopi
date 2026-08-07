from __future__ import annotations

import pytest

from takopi.compact import CompactSupport
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
from takopi.runners.opencode import OpenCodeRunner


def test_opencode_compact_support_is_native_api() -> None:
    runner = OpenCodeRunner()
    support = runner.compact_support()
    assert isinstance(support, CompactSupport)
    assert support.mode == "native_api"
    assert support.accepts_instructions is False
    assert support.true_compaction is True


@pytest.mark.anyio
async def test_opencode_compact_posts_to_session_endpoint() -> None:
    """Compact delegates to the server API endpoint."""
    requests: list[tuple[str, str]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        async def post(self, url: str, json: dict | None = None) -> FakeResponse:
            requests.append(("POST", url))
            return FakeResponse()

        async def close(self) -> None:
            pass

    client = FakeClient()
    runner = OpenCodeRunner(
        compact_api_base_url="http://fake",
        compact_http_client=client,
        compact_wait=True,
    )
    resume = ResumeToken(engine="opencode", value="ses_abc")

    events = [evt async for evt in runner.compact(resume, None)]

    assert requests == [
        ("POST", "/api/session/ses_abc/compact"),
        ("POST", "/api/session/ses_abc/wait"),
    ]
    first = events[0]
    assert isinstance(first, StartedEvent)
    final = events[-1]
    assert isinstance(final, CompletedEvent)
    assert final.resume == first.resume
    assert final.ok is True


@pytest.mark.anyio
async def test_opencode_compact_without_wait() -> None:
    requests: list[tuple[str, str]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        async def post(self, url: str, json: dict | None = None) -> FakeResponse:
            requests.append(("POST", url))
            return FakeResponse()

        async def close(self) -> None:
            pass

    client = FakeClient()
    runner = OpenCodeRunner(
        compact_api_base_url="http://fake",
        compact_http_client=client,
        compact_wait=False,
    )
    resume = ResumeToken(engine="opencode", value="ses_xyz")

    events = [evt async for evt in runner.compact(resume, None)]

    assert requests == [("POST", "/api/session/ses_xyz/compact")]
    final = events[-1]
    assert isinstance(final, CompletedEvent)
    assert final.ok is True


@pytest.mark.anyio
async def test_opencode_compact_error_emits_failed_completed() -> None:
    class FakeClient:
        async def post(self, url: str, json: dict | None = None) -> object:
            raise RuntimeError("server unavailable")

        async def close(self) -> None:
            pass

    runner = OpenCodeRunner(
        compact_api_base_url="http://fake",
        compact_http_client=FakeClient(),
        compact_wait=False,
    )
    resume = ResumeToken(engine="opencode", value="ses_err")

    events = [evt async for evt in runner.compact(resume, None)]

    final = events[-1]
    assert isinstance(final, CompletedEvent)
    assert final.ok is False
    assert final.resume == resume
