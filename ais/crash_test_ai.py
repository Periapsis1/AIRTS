"""Crash test AI — raises an exception on the first step to test crash handling."""
from __future__ import annotations
from systems.ai.base import BaseAI


class CrashTestAI(BaseAI):
    """Deliberately crashes on the first game step to verify crash handling."""

    ai_id = "crash_test"
    ai_name = "Crash Test AI"
    deprecated = True

    def on_start(self) -> None:
        self.set_build("soldier")

    def on_step(self, iteration: int) -> None:
        if iteration == 0:
            raise RuntimeError(
                "CrashTestAI: intentional crash to verify crash handling"
            )
