from __future__ import annotations

import pytest

from takopi.compact import COMPACT_NONE, CompactUnsupportedError
from takopi.model import ResumeToken
from takopi.runners.mock import ScriptRunner


def test_runner_default_compact_support_is_none() -> None:
    runner = ScriptRunner([], engine="mock", resume_value="sid")
    assert runner.compact_support() == COMPACT_NONE


@pytest.mark.anyio
async def test_runner_default_compact_raises() -> None:
    runner = ScriptRunner([], engine="mock", resume_value="sid")
    with pytest.raises(CompactUnsupportedError):
        async for _ in runner.compact(ResumeToken(engine="mock", value="sid")):
            pass
