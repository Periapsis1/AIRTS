"""Turtle AI — builds a 50/50 sniper-medic army at base, then rushes the enemy CC at 65 units."""
from __future__ import annotations
import math
from entities.command_center import CommandCenter
from systems.ai.base import BaseAI

_TARGET = {"sniper": 0.50, "medic": 0.25, "shockwave": 0.25}
_RUSH_THRESHOLD = 65   # total army units before rushing
_HOLD_RADIUS = 80       # px from CC that units idle within


class TurtleAI(BaseAI):
    ai_id = "turtle"
    ai_name = "Turtle AI"

    def __init__(self):
        super().__init__()
        self._seen_unit_ids: set[int] = set()
        self._total_built: dict[str, int] = {}
        self._rushing = False

    def on_start(self) -> None:
        self.set_build("sniper")

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        army = self.get_own_mobile_units()
        self._track_new_units(army)

        if iteration % 60 == 0:
            self._update_build()

        if not self._rushing and len(army) >= _RUSH_THRESHOLD:
            self._rushing = True

        ecc = self._enemy_cc()

        if self._rushing and ecc is not None:
            for u in army:
                u.move(ecc.x, ecc.y)
        else:
            for u in army:
                dist = math.hypot(u.x - cc.x, u.y - cc.y)
                if dist > _HOLD_RADIUS or u.target is None:
                    u.move(cc.x, cc.y)

    # -------------------------------------------------------------------------

    def _track_new_units(self, units: list) -> None:
        for u in units:
            if u.entity_id not in self._seen_unit_ids:
                self._seen_unit_ids.add(u.entity_id)
                self._total_built[u.unit_type] = self._total_built.get(u.unit_type, 0) + 1

    def _update_build(self) -> None:
        total = sum(self._total_built.get(t, 0) for t in _TARGET)
        if total == 0:
            self.set_build("sniper")
            return
        counts = {t: self._total_built.get(t, 0) for t in _TARGET}
        build = max(_TARGET, key=lambda t: _TARGET[t] - counts[t] / total)
        self.set_build(build)

    def _enemy_cc(self) -> CommandCenter | None:
        for e in self._entities:
            if isinstance(e, CommandCenter) and e.alive and e.team != self._team:
                return e
        return None
