from math import hypot

from systems.ai.base import BaseAI

BUILD_ORDER = ["sniper", "soldier", "soldier", "medic", "medic", "medic"]


class CowardBot(BaseAI):
    ai_id = "coward_bot"
    ai_name = "CowardBot"

    def on_start(self) -> None:
        self._build_idx = 0
        self._last_unit_count = 0
        self._state = "RALLY"
        self.set_build(BUILD_ORDER[self._build_idx])

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        own = self.get_own_units()
        enemies = self.get_enemy_units()

        # --- Build order tracking ---
        unit_count = len(own)
        if unit_count > self._last_unit_count:
            self._build_idx = (self._build_idx + 1) % len(BUILD_ORDER)
            self.set_build(BUILD_ORDER[self._build_idx])
        self._last_unit_count = unit_count

        # --- Categorize units ---
        soldiers = [u for u in own if u.unit_type == "soldier"]
        snipers = [u for u in own if u.unit_type == "sniper"]
        medics = [u for u in own if u.unit_type == "medic"]

        # --- Rally point (60px from CC toward own side) ---
        rally = self._rally_point(cc)

        # --- State transitions ---
        sniper_count = len(snipers)

        if self._state == "RALLY":
            if sniper_count >= 3:
                self._state = "PUSH"
        elif self._state == "PUSH":
            enemy_near_cc = any(
                hypot(e.x - cc.x, e.y - cc.y) < 100 for e in enemies
            )
            if sniper_count < 3 or enemy_near_cc:
                self._state = "RALLY"
                for u in own:
                    u.move(rally[0], rally[1])

        # --- Execute current state ---
        if self._state == "RALLY":
            for u in own:
                u.move(rally[0], rally[1])
            # Defensive targeting for combat units
            if enemies:
                for u in soldiers + snipers:
                    u.attack_target = self._closest(u, enemies)

        elif self._state == "PUSH":
            # Soldiers: kite (back up on cooldown, advance when out of range)
            for soldier in soldiers:
                if not enemies:
                    continue
                nearest = self._closest(soldier, enemies)
                dist = hypot(nearest.x - soldier.x, nearest.y - soldier.y)
                if soldier.laser_cooldown > 0 and dist < soldier.attack_range:
                    if dist > 0:
                        retreat_x = soldier.x - (nearest.x - soldier.x) / dist * 20
                        retreat_y = soldier.y - (nearest.y - soldier.y) / dist * 20
                        soldier.move(retreat_x, retreat_y)
                elif dist > soldier.attack_range:
                    soldier.move(nearest.x, nearest.y)
                else:
                    soldier.stop()
                soldier.attack_target = nearest

            # Medics: follow nearest damaged soldier, or nearest soldier
            for medic in medics:
                damaged = [s for s in soldiers if s.hp < s.max_hp]
                if damaged:
                    target = self._closest(medic, damaged)
                elif soldiers:
                    target = self._closest(medic, soldiers)
                else:
                    continue
                medic.follow(target, 15)

            # Snipers: trail behind soldiers at distance, target nearest enemy
            for sniper in snipers:
                if soldiers:
                    nearest_soldier = self._closest(sniper, soldiers)
                    sniper.follow(nearest_soldier, 60)
                if enemies:
                    sniper.attack_target = self._closest(sniper, enemies)

    def _rally_point(self, cc):
        """60px from CC toward own side (team 1 left, team 2 right)."""
        direction = -1 if self._team == 1 else 1
        return (cc.x + direction * 60, cc.y)

    @staticmethod
    def _closest(unit, targets):
        return min(targets, key=lambda t: (t.x - unit.x) ** 2 + (t.y - unit.y) ** 2)
