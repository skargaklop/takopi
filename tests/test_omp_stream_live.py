"""Opt-in live OMP JSONL stream smoke test.

Requires ``TAKOPI_OMP_LIVE=1``, the ``omp`` CLI on PATH, and a configured
OMP provider. Deselect with ``-m \"not live_omp\"`` when desired.

Validates that a real OMP stream:

1. decodes without msgspec errors (float ``delayMs``, forward-compatible
   unknown event tags);
2. produces at least one ``StartedEvent`` and a terminal ``CompletedEvent``
   when translated through :class:`OmpRunner`;
3. preserves the full session id in the ``StartedEvent`` (OMP opts out of
   Pi's abbreviated-id behavior).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest
import anyio

omp = shutil.which("omp")

pytestmark = pytest.mark.live_omp


@pytest.mark.skipif(
    omp is None or os.environ.get("TAKOPI_OMP_LIVE") != "1",
    reason="requires TAKOPI_OMP_LIVE=1 and the omp CLI on PATH",
)
@pytest.mark.anyio
async def test_omp_live_stream_decodes_and_preserves_session_id() -> None:
    from takopi.model import CompletedEvent, ResumeToken, StartedEvent
    from takopi.runners.omp import ENGINE, OmpRunner

    runner = OmpRunner(
        extra_args=[],
        model=os.environ.get("TAKOPI_OMP_LIVE_MODEL"),
        provider=os.environ.get("TAKOPI_OMP_LIVE_PROVIDER"),
    )
    # Single-line prompt: goes as a CLI arg, no stdin needed.
    prompt = f"Reply with exactly the word: pong-{uuid.uuid4().hex[:6]}"
    resume: ResumeToken | None = None
    state = runner.new_state(prompt, resume)
    args = runner.build_args(prompt, resume, state=state)

    from takopi.utils.subprocess import manage_subprocess

    events: list = []
    found_session: ResumeToken | None = None
    timeout_s = float(os.environ.get("TAKOPI_OMP_LIVE_TIMEOUT_S", "120"))
    with anyio.fail_after(timeout_s):
        async with manage_subprocess(
            [runner.command(), *args],
            cwd=os.getcwd(),
            env={**os.environ, "PYTHONUTF8": "1"},
            stdin=subprocess.DEVNULL,
        ) as proc:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                if not raw.strip():
                    continue
                try:
                    decoded = runner.decode_jsonl(line=raw.rstrip())
                except Exception:  # noqa: BLE001
                    # Mirrors the production runner: malformed lines are
                    # line-local and logged; the stream continues.
                    continue
                promoted = runner.translate(
                    decoded,
                    state=state,
                    resume=resume,
                    found_session=found_session,
                )
                for ev in promoted:
                    if found_session is None and isinstance(ev, StartedEvent):
                        found_session = ev.resume
                    events.append(ev)

    assert any(isinstance(e, StartedEvent) for e in events), (
        "no StartedEvent emitted from live OMP stream"
    )
    completed = [e for e in events if isinstance(e, CompletedEvent)]
    assert completed, "no CompletedEvent emitted from live OMP stream"
    assert completed[-1].ok, f"live OMP run did not complete cleanly: {completed[-1]}"

    # Session-id preservation: OMP must surface the full UUID, not an
    # abbreviated prefix.
    started = next(e for e in events if isinstance(e, StartedEvent))
    assert started.resume is not None
    assert started.resume.engine == ENGINE
    sid = started.resume.value
    assert len(sid) >= 32, f"OMP session id looks abbreviated: {sid!r}"
