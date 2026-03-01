"""Simple AI: units wander to random locations when idle, random spawn type."""
from __future__ import annotations
import random
from config.unit_types import UNIT_TYPES
from config.settings import FIXED_DT
from systems.ai.base import BaseAI


class WanderAI(BaseAI):
    """Units wander to random locations when idle. Spawns random unit types."""

    ai_id = "wander"
    ai_name = "Wander AI"

    INTERVAL = (1.0, 3.0)

    def __init__(self):
        super().__init__()
        self._timers: dict[int, float] = {}

    def on_start(self) -> None:
        self.set_build(random.choice(list(UNIT_TYPES.keys())))

    def on_step(self, iteration: int) -> None:
        bw, bh = self.bounds
        for u in self.get_own_units():
            uid = u.entity_id
            if u.target is not None:
                continue
            timer = self._timers.get(uid, random.uniform(*self.INTERVAL))
            timer -= FIXED_DT
            if timer <= 0:
                margin = u.radius
                self.move_unit(
                    u,
                    random.uniform(margin, bw - margin),
                    random.uniform(margin, bh - margin),
                )
                timer = random.uniform(*self.INTERVAL)
            self._timers[uid] = timer

        if random.random() < 0.01:
            self.set_build(random.choice(list(UNIT_TYPES.keys())))
