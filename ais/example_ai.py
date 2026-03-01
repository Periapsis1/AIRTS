"""Example user AI — drop files like this into the ais/ folder."""
from __future__ import annotations
import random
from config.unit_types import UNIT_TYPES
from systems.ai.base import BaseAI


class ExampleAI(BaseAI):
    """A simple example AI that demonstrates the user AI interface.

    Units attack the nearest enemy; spawns random unit types.
    """

    ai_id = "example"
    ai_name = "Example AI"

    def on_start(self) -> None:
        self.set_build("soldier")

    def on_step(self, iteration: int) -> None:
        enemies = self.get_enemy_units()
        for u in self.get_own_units():
            if u.target is not None:
                continue
            if enemies:
                closest = min(enemies, key=lambda e: (e.x - u.x)**2 + (e.y - u.y)**2)
                u.move(closest.x, closest.y)

        if random.random() < 0.01:
            self.set_build(random.choice(list(UNIT_TYPES.keys())))
