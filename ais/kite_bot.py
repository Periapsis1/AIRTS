from math import hypot

from systems.ai.base import BaseAI

BUILD_ORDER = ["sniper"]


class KiteBot(BaseAI):
    ai_id = "kite_bot"
    ai_name = "KiteBot"

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

        snipers = own  # all units are snipers

        # --- Rally point (60px from CC toward own side) ---
        rally = self._rally_point(cc)

        # --- State transitions (push at 2 snipers) ---
        sniper_count = len(snipers)

        if self._state == "RALLY":
            if sniper_count >= 2:
                self._state = "PUSH"
        elif self._state == "PUSH":
            enemy_near_cc = any(
                hypot(e.x - cc.x, e.y - cc.y) < 100 for e in enemies
            )
            if sniper_count < 2 or enemy_near_cc:
                self._state = "RALLY"
                for u in own:
                    u.move(rally[0], rally[1])

        # --- Execute current state ---
        if self._state == "RALLY":
            for u in own:
                u.move(rally[0], rally[1])
            if enemies:
                for u in snipers:
                    u.attack_target = self._closest(u, enemies)

        elif self._state == "PUSH":
            for sniper in snipers:
                if not enemies:
                    continue
                self._sniper_kite(sniper, enemies)

    def _sniper_kite(self, sniper, enemies):
        """Snipers independently kite: engage enemies they outrange, stay outside enemy range."""
        sniper_range = sniper.attack_range  # 150

        # Prefer enemies we outrange
        outranged = [e for e in enemies if sniper_range > e.attack_range]
        target_pool = outranged if outranged else enemies
        nearest = self._closest(sniper, target_pool)

        dist = hypot(nearest.x - sniper.x, nearest.y - sniper.y)
        enemy_range = nearest.attack_range

        if dist < enemy_range + 10:
            # Too close — back away from enemy
            if dist > 0:
                away_x = sniper.x - (nearest.x - sniper.x) / dist * 30
                away_y = sniper.y - (nearest.y - sniper.y) / dist * 30
                sniper.move(away_x, away_y)
        elif dist > sniper_range:
            # Too far — move into our attack range
            sniper.move(nearest.x, nearest.y)
        else:
            # In our range but outside theirs — hold and fire
            if sniper.laser_cooldown > 0:
                # Kite backward while on cooldown to maintain safe distance
                if dist > 0:
                    away_x = sniper.x - (nearest.x - sniper.x) / dist * 15
                    away_y = sniper.y - (nearest.y - sniper.y) / dist * 15
                    sniper.move(away_x, away_y)
            else:
                sniper.stop()

        sniper.attack_target = nearest

    def _rally_point(self, cc):
        """60px from CC toward own side (team 1 left, team 2 right)."""
        direction = -1 if self._team == 1 else 1
        return (cc.x + direction * 60, cc.y)

    @staticmethod
    def _closest(unit, targets):
        return min(targets, key=lambda t: (t.x - unit.x) ** 2 + (t.y - unit.y) ** 2)
