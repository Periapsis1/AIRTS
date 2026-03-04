from math import hypot

from systems.ai.base import BaseAI

BUILD_ORDER = ["sniper", "soldier", "soldier", "medic", "medic", "medic"]


class TerrorBot(BaseAI):
    ai_id = "terror_bot"
    ai_name = "TerrorBot"

    def on_start(self) -> None:
        self._build_idx = 0
        self._last_unit_count = 0
        self._state = "RALLY"
        self._last_scout_cycle = -5  # allow immediate first scout
        self.set_build(BUILD_ORDER[self._build_idx])

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        own = self.get_own_mobile_units()
        enemies = self.get_enemy_units()
        metal_spots = self.get_metal_spots()

        # --- Categorize units ---
        soldiers = [u for u in own if u.unit_type == "soldier"]
        snipers = [u for u in own if u.unit_type == "sniper"]
        medics = [u for u in own if u.unit_type == "medic"]
        scouts = [u for u in own if u.unit_type == "scout"]

        # --- Build order with scout priority (max 1 scout per 5 cycles) ---
        unit_count = len(own)
        if unit_count > self._last_unit_count:
            self._build_idx = (self._build_idx + 1) % len(BUILD_ORDER)
        self._last_unit_count = unit_count

        if not scouts and (iteration - self._last_scout_cycle) >= 5:
            self.set_build("scout")
            self._last_scout_cycle = iteration
        else:
            self.set_build(BUILD_ORDER[self._build_idx])

        # --- Scout behavior: spread across non-owned metal spots ---
        unclaimed = [s for s in metal_spots if s.owner != self._team]
        scout_targets = unclaimed if unclaimed else metal_spots
        # Sort by distance to CC so closest spots get covered first
        scout_targets.sort(key=lambda s: (s.x - cc.x) ** 2 + (s.y - cc.y) ** 2)
        for i, scout in enumerate(scouts):
            if scout_targets:
                spot = scout_targets[i % len(scout_targets)]
                scout.move(spot.x, spot.y)
            if enemies:
                scout.attack_target = self._closest(scout, enemies)

        # --- Rally point: nearest metal spot not ours ---
        rally = self._rally_point(cc, metal_spots)

        # --- State transitions ---
        sniper_count = len(snipers)
        combat_units = soldiers + snipers

        if self._state == "RALLY":
            if sniper_count >= 3:
                self._state = "PUSH"
        elif self._state == "PUSH":
            enemy_near_cc = any(
                hypot(e.x - cc.x, e.y - cc.y) < 100 for e in enemies
            )
            if sniper_count < 3 or enemy_near_cc:
                self._state = "RALLY"
                for u in combat_units + medics:
                    u.move(rally[0], rally[1])

        # --- Execute current state (excludes scouts, they act independently) ---
        if self._state == "RALLY":
            for u in combat_units + medics:
                u.move(rally[0], rally[1])
            if enemies:
                for u in combat_units:
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

    def _rally_point(self, cc, metal_spots):
        """Rally at nearest metal spot not owned by us. Fallback to CC offset."""
        unclaimed = [s for s in metal_spots if s.owner != self._team]
        if unclaimed:
            nearest = min(unclaimed, key=lambda s: (s.x - cc.x) ** 2 + (s.y - cc.y) ** 2)
            return (nearest.x, nearest.y)
        # All spots ours — fall back to behind base
        direction = -1 if self._team == 1 else 1
        return (cc.x + direction * 60, cc.y)

    @staticmethod
    def _closest(unit, targets):
        return min(targets, key=lambda t: (t.x - unit.x) ** 2 + (t.y - unit.y) ** 2)
