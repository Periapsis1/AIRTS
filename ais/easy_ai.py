"""Easy AI — soldiers + medics with a simple chase strategy and defensive fallback."""
from __future__ import annotations
import math
from systems.ai.base import BaseAI


class EasyAI(BaseAI):
    ai_id = "easy"
    ai_name = "Easy AI"

    def on_start(self) -> None:
        self.set_build("soldier")
        self._soldiers_built = 0
        self._medics_built = 0
        self._has_sniper = False
        self._last_unit_count = 0

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        own = self.get_own_mobile_units()
        enemies = self.get_enemy_units()

        soldiers = [u for u in own if u.unit_type == "soldier"]
        medics = [u for u in own if u.unit_type == "medic"]
        snipers = [u for u in own if u.unit_type == "sniper"]

        # --- Detect new spawns to track build counts ---
        current_count = len(own)
        if current_count > self._last_unit_count:
            new = current_count - self._last_unit_count
            # Attribute new units to whatever we were building
            if cc.spawn_type == "soldier":
                self._soldiers_built += new
            elif cc.spawn_type == "medic":
                self._medics_built += new
        self._last_unit_count = current_count

        # --- Determine mode ---
        enemy_count = len(enemies)
        own_count = len(own)
        defensive = enemy_count > 0 and own_count <= enemy_count * 0.5

        # --- Build order ---
        self._has_sniper = len(snipers) > 0

        if defensive and not self._has_sniper:
            # Need a sniper for defense
            self.set_build("sniper")
        elif len(soldiers) > 0 and len(medics) < len(soldiers) // 3:
            # Under the 1:3 medic-to-soldier ratio
            self.set_build("medic")
        else:
            self.set_build("soldier")

        # --- Commands ---
        if defensive:
            # Defensive mode: gather at base until 10+ soldiers
            for u in soldiers + medics:
                if u.target is None:
                    self.move_unit(u, cc.x, cc.y)

            # Sniper targets nearest enemy
            if snipers and enemies:
                nearest = min(enemies, key=lambda e: _dist2(snipers[0], e))
                self.attack_unit(snipers[0], nearest)
                self.move_unit(snipers[0], nearest.x, nearest.y)

            # Break out of defensive mode once we have 10 soldiers
            if len(soldiers) >= 10:
                return  # will re-evaluate next tick as non-defensive

        elif len(soldiers) >= 3 and enemies:
            # Aggressive mode: chase nearest enemy
            for u in soldiers + snipers:
                if u.target is not None:
                    continue
                nearest = min(enemies, key=lambda e: _dist2(u, e))
                self.move_unit(u, nearest.x, nearest.y)

            # Medics follow the pack (move toward average soldier position)
            if soldiers and medics:
                avg_x = sum(s.x for s in soldiers) / len(soldiers)
                avg_y = sum(s.y for s in soldiers) / len(soldiers)
                for m in medics:
                    if m.target is None:
                        self.move_unit(m, avg_x, avg_y)


def _dist2(a, b) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2
