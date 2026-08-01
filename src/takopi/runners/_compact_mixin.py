"""Mixin for runners that compact via ``/compact`` slash prompt.

Runners like ``claude``, ``pi``, and ``codex`` support ``/compact`` as a
native slash command. This mixin delegates ``compact()`` to ``run()``,
optionally passing instructions as part of the prompt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..compact import CompactSupport, compact_prompt
from ..model import ResumeToken, TakopiEvent


class SlashCompactMixin:
    """Delegate compaction to ``run("/compact [instructions]", resume)``."""

    compact_accepts_instructions: bool = True
    compact_true_compaction: bool = True

    def compact_support(self) -> CompactSupport:
        return CompactSupport(
            mode="slash_prompt",
            accepts_instructions=self.compact_accepts_instructions,
            true_compaction=self.compact_true_compaction,
        )

    async def compact(
        self,
        resume: ResumeToken,
        instructions: str | None = None,
    ) -> AsyncIterator[TakopiEvent]:
        if instructions and not self.compact_accepts_instructions:
            instructions = None
        async for event in self.run(compact_prompt(instructions), resume):
            yield event
