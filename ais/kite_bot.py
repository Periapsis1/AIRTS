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
        self._current_build = BUILD_ORDER[0]
        self.set_build(self._current_build)

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        own = self.get_own_mobile_units()
        enemies = self.get_enemy_units()

        # --- Build order tracking ---
        unit_count = len(own)
        if unit_count > self._last_unit_count:
            self._build_idx = (self._build_idx + 1) % len(BUILD_ORDER)
            next_build = BUILD_ORDER[self._build_idx]
            if next_build != self._current_build:
                self.set_build(next_build)
                self._current_build = next_build
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
                    self.move_unit(u, rally[0], rally[1])

        # --- Execute current state ---
        if self._state == "RALLY":
            for u in own:
                self.move_unit(u, rally[0], rally[1])
            if enemies:
                for u in snipers:
                    self.attack_unit(u, self._closest(u, enemies))

        elif self._state == "PUSH":
            for sniper in snipers:
                if not enemies:
                    continue
                self._sniper_kite(sniper, enemies)

    def _sniper_kite(self, sniper, enemies):
        """Cooldown-driven kiting: close in to fire, back off while reloading."""
        sniper_range = sniper.attack_range  # 150

        # Prefer enemies we outrange
        outranged = [e for e in enemies if sniper_range > e.attack_range]
        target_pool = outranged if outranged else enemies
        nearest = self._closest(sniper, target_pool)

        dist = hypot(nearest.x - sniper.x, nearest.y - sniper.y)
        enemy_range = nearest.attack_range

        # Desired firing distance: just inside our own range
        fire_dist = sniper_range - 10  # 140

        self.attack_unit(sniper, nearest)

        if sniper.laser_cooldown <= 0:
            # Ready to fire — close to firing distance, then hold
            if dist > sniper_range:
                # Out of range — approach
                self.move_unit(sniper, nearest.x, nearest.y)
            # else: in range — don't move, let combat system fire
        else:
            # On cooldown — kite away to stay safe
            if dist < enemy_range + 15 and dist > 0:
                # Within enemy threat range — back off aggressively
                away_x = sniper.x - (nearest.x - sniper.x) / dist * 40
                away_y = sniper.y - (nearest.y - sniper.y) / dist * 40
                self.move_unit(sniper, away_x, away_y)
            elif dist < fire_dist and dist > 0:
                # Closer than we need to be — drift back
                away_x = sniper.x - (nearest.x - sniper.x) / dist * 20
                away_y = sniper.y - (nearest.y - sniper.y) / dist * 20
                self.move_unit(sniper, away_x, away_y)

    def _rally_point(self, cc):
        """60px from CC toward own side (team 1 left, team 2 right)."""
        direction = -1 if self._team == 1 else 1
        return (cc.x + direction * 60, cc.y)

    @staticmethod
    def _closest(unit, targets):
        return min(targets, key=lambda t: (t.x - unit.x) ** 2 + (t.y - unit.y) ** 2)
