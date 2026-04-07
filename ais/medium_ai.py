"""Medium AI — scout economy, tank/sniper/medic combat comp with kiting."""
from __future__ import annotations
import math
from systems.ai.base import BaseAI
from entities.unit import Unit


class MediumAI(BaseAI):
    ai_id = "medium"
    ai_name = "Medium AI"
    deprecated = True

    # Desired combat comp ratio: tank:sniper:medic = 1:1:2
    _COMP_CYCLE = ["tank", "sniper", "medic", "medic"]

    _SCOUT_INTERVAL = 4  # build scouts at most once every 4 cycles

    def on_start(self) -> None:
        self.set_build("scout")
        self._current_build: str = "scout"
        self._cycles_since_scout: int = 0  # counts non-scout build cycles
        self._last_unit_count: int = 0

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        own = self.get_own_mobile_units()
        enemies = self.get_enemy_units()
        bw, bh = self.bounds

        scouts = [u for u in own if u.unit_type == "scout"]
        tanks = [u for u in own if u.unit_type == "tank"]
        snipers = [u for u in own if u.unit_type == "sniper"]
        medics = [u for u in own if u.unit_type == "medic"]

        # Track spawn cycles for scout limiter
        current_count = len(own)
        if current_count > self._last_unit_count:
            if self._current_build == "scout":
                self._cycles_since_scout = 0
            else:
                self._cycles_since_scout += 1
        self._last_unit_count = current_count

        self._update_build(scouts, tanks, snipers, medics)
        self._command_scouts(scouts, enemies, cc, bw, bh)
        self._command_tanks(tanks, enemies, cc)
        self._command_medics(medics, tanks, cc)
        self._command_snipers(snipers, enemies, tanks, cc)

    # -- build order --------------------------------------------------------

    def _set_build_once(self, unit_type: str) -> None:
        """Only enqueue a set_build command when the type actually changes."""
        if self._current_build != unit_type:
            self.set_build(unit_type)
            self._current_build = unit_type

    def _update_build(self, scouts, tanks, snipers, medics) -> None:
        # Replenish scouts if none alive, but only once every N cycles
        if not scouts and self._cycles_since_scout >= self._SCOUT_INTERVAL:
            self._set_build_once("scout")
            return

        # Otherwise maintain combat comp ratio 1:1:2
        counts = {"tank": len(tanks), "sniper": len(snipers), "medic": len(medics)}
        desired = {"tank": 1, "sniper": 1, "medic": 2}

        # Find which type is furthest below its ratio share
        worst_type = None
        worst_ratio = float("inf")
        for utype in self._COMP_CYCLE:
            if utype in desired:
                ratio = counts[utype] / desired[utype]
                if ratio < worst_ratio:
                    worst_ratio = ratio
                    worst_type = utype

        if worst_type:
            self._set_build_once(worst_type)

    # -- helpers ------------------------------------------------------------

    def _on_our_side(self, entity) -> bool:
        return self.is_on_own_side(entity)

    # -- scout behavior -----------------------------------------------------

    def _command_scouts(self, scouts, enemies, cc, bw, bh):
        if not scouts:
            return

        # Threats scouts should avoid: all enemy units except buildings
        threats = [e for e in enemies if not e.is_building]

        spots = self.get_metal_spots()
        all_extractors = self.get_metal_extractors()
        enemy_extractors = [e for e in all_extractors if e.team != self._team]

        # Spots with no extractor built
        extractor_spot_ids = set()
        for ext in all_extractors:
            if ext.metal_spot is not None:
                extractor_spot_ids.add(ext.metal_spot.entity_id)
        contestable = [s for s in spots if s.entity_id not in extractor_spot_ids]

        if contestable:
            for i, scout in enumerate(scouts):
                target = contestable[i % len(contestable)]
                if _dist(scout, target) > 10:
                    self._scout_move(scout, target.x, target.y, threats, bw, bh)
        elif enemy_extractors:
            for scout in scouts:
                target = _closest(scout, enemy_extractors)
                self._scout_move(scout, target.x, target.y, threats, bw, bh)
                self.attack_unit(scout, target)
        else:
            enemy_scouts = [e for e in enemies if e.unit_type == "scout"]
            if enemy_scouts:
                for scout in scouts:
                    target = _closest(scout, enemy_scouts)
                    self.move_unit(scout, target.x, target.y)
                    self.attack_unit(scout, target)
            else:
                for scout in scouts:
                    if _dist(scout, cc) > 80:
                        self.move_unit(scout, cc.x, cc.y)

    def _scout_move(self, scout, goal_x, goal_y, threats, bw, bh):
        """Move scout toward goal while steering away from dangerous enemies."""
        # Direction toward goal
        dx = goal_x - scout.x
        dy = goal_y - scout.y
        goal_dist = math.hypot(dx, dy)
        if goal_dist < 1:
            return
        dir_x = dx / goal_dist
        dir_y = dy / goal_dist

        # Accumulate avoidance from nearby threats
        avoid_x = 0.0
        avoid_y = 0.0
        avoid_radius = 100.0  # start avoiding at this distance

        for t in threats:
            tx = scout.x - t.x
            ty = scout.y - t.y
            td = math.hypot(tx, ty)
            if td < avoid_radius and td > 0:
                # Stronger push the closer the threat
                strength = (avoid_radius - td) / avoid_radius
                avoid_x += (tx / td) * strength
                avoid_y += (ty / td) * strength

        if avoid_x != 0.0 or avoid_y != 0.0:
            # Blend: goal direction + avoidance (avoidance weighted heavier)
            mx = dir_x + avoid_x * 2.0
            my = dir_y + avoid_y * 2.0
            ml = math.hypot(mx, my) or 1.0
            mx /= ml
            my /= ml
        else:
            mx, my = dir_x, dir_y

        # Project a move point ~60px ahead in the blended direction
        step = min(60.0, goal_dist)
        dest_x = max(5.0, min(bw - 5.0, scout.x + mx * step))
        dest_y = max(5.0, min(bh - 5.0, scout.y + my * step))
        self.move_unit(scout, dest_x, dest_y)

    # -- tank behavior ------------------------------------------------------

    def _command_tanks(self, tanks, enemies, cc):
        if not tanks:
            return

        # Prioritize enemy snipers on our side of the map
        enemy_snipers_our_side = [
            e for e in enemies
            if e.unit_type == "sniper" and self._on_our_side(e)
        ]

        pushing = len(tanks) >= 4 or enemy_snipers_our_side

        for tank in tanks:
            if enemy_snipers_our_side:
                target = _closest(tank, enemy_snipers_our_side)
                self._tank_engage(tank, target)
            elif pushing and enemies:
                target = _closest(tank, enemies)
                self._tank_engage(tank, target)
            else:
                # Rally at CC until we have 4+ tanks
                if _dist(tank, cc) > 60:
                    self.move_unit(tank, cc.x, cc.y)

    def _tank_engage(self, tank, target):
        """Move tank to ~80% of its attack range from the target, not point-blank."""
        tank_range = tank.attack_range  # 50
        desired_dist = tank_range * 0.8  # 40
        dist = _dist(tank, target)

        self.attack_unit(tank, target)

        if dist > tank_range:
            # Out of range — close in toward the desired distance
            # Aim for a point desired_dist away from the target
            dx = tank.x - target.x
            dy = tank.y - target.y
            d = math.hypot(dx, dy) or 1.0
            goal_x = target.x + (dx / d) * desired_dist
            goal_y = target.y + (dy / d) * desired_dist
            self.move_unit(tank, goal_x, goal_y)
        elif dist < desired_dist - 5:
            # Too close — back off slightly
            dx = tank.x - target.x
            dy = tank.y - target.y
            d = math.hypot(dx, dy) or 1.0
            self.move_unit(tank, tank.x + (dx / d) * 10, tank.y + (dy / d) * 10)

    # -- medic behavior -----------------------------------------------------

    def _command_medics(self, medics, tanks, cc):
        if not medics:
            return

        if not tanks:
            # No tanks — stay near CC
            for m in medics:
                if _dist(m, cc) > 60:
                    self.move_unit(m, cc.x, cc.y)
            return

        for i, medic in enumerate(medics):
            tank = tanks[i % len(tanks)]

            # Position between the tank and our base, ~30px behind the tank
            dx = cc.x - tank.x
            dy = cc.y - tank.y
            d = math.hypot(dx, dy)
            if d > 1:
                follow_x = tank.x + (dx / d) * 30.0
                follow_y = tank.y + (dy / d) * 30.0
            else:
                follow_x = tank.x
                follow_y = tank.y

            if math.hypot(medic.x - follow_x, medic.y - follow_y) > 15:
                self.move_unit(medic, follow_x, follow_y)

    # -- sniper behavior ----------------------------------------------------

    def _command_snipers(self, snipers, enemies, tanks, cc):
        if not snipers or not enemies:
            return

        enemy_snipers = [e for e in enemies if e.unit_type == "sniper"]
        enemies_our_side = [e for e in enemies if self._on_our_side(e)]
        enemy_extractors = [e for e in self.get_metal_extractors()
                            if e.team != self._team]

        # Sniper vs sniper focus fire: pair up 2 of ours onto 1 of theirs
        paired: set[int] = set()
        if len(snipers) >= 2 and enemy_snipers:
            focus_target = _closest(snipers[0], enemy_snipers)
            for s in snipers[:2]:
                self._sniper_kite(s, focus_target, enemies, cc)
                paired.add(id(s))

        # Remaining snipers: individual priorities
        for sniper in snipers:
            if id(sniper) in paired:
                continue

            # If ANY enemy is within sniper range + buffer, kite it regardless
            # of other priorities — survival trumps everything
            nearby_enemy = _closest_within(sniper, enemies, sniper.attack_range + 30)
            if nearby_enemy is not None:
                self._sniper_kite(sniper, nearby_enemy, enemies, cc)
            elif enemies_our_side:
                target = _closest(sniper, enemies_our_side)
                self._sniper_kite(sniper, target, enemies, cc)
            elif enemy_extractors:
                target = _closest(sniper, enemy_extractors)
                self.move_unit(sniper, target.x, target.y)
                self.attack_unit(sniper, target)
            elif tanks:
                # Only follow tanks when no threats exist
                tank = tanks[0]
                if _dist(sniper, tank) > 100:
                    self.move_unit(sniper, tank.x, tank.y)

    def _sniper_kite(self, sniper, target, all_enemies, cc):
        """Cooldown-driven kiting: survival first, close in to fire, back off while reloading."""
        sniper_range = sniper.attack_range  # 150
        dist = _dist(sniper, target)

        self.attack_unit(sniper, target)

        # Survival check: is any enemy threat dangerously close?
        for e in all_enemies:
            if e is target:
                continue
            d = _dist(sniper, e)
            if d < e.attack_range + 10 and d > 0:
                # Threat in range — flee toward base
                dx = sniper.x - e.x
                dy = sniper.y - e.y
                flee_d = math.hypot(dx, dy) or 1.0
                base_dx = cc.x - sniper.x
                base_dy = cc.y - sniper.y
                base_d = math.hypot(base_dx, base_dy) or 1.0
                flee_x = sniper.x + (dx / flee_d) * 24 + (base_dx / base_d) * 16
                flee_y = sniper.y + (dy / flee_d) * 24 + (base_dy / base_d) * 16
                self.move_unit(sniper, flee_x, flee_y)
                return

        if sniper.laser_cooldown <= 0:
            # Ready to fire — close to within range, then hold
            if dist > sniper_range:
                self.move_unit(sniper, target.x, target.y)
            # else: in range — don't move, let combat system fire
        else:
            # On cooldown — kite away
            enemy_range = target.attack_range if hasattr(target, 'attack_range') else 0
            if dist < enemy_range + 15 and dist > 0:
                # Within enemy threat range — back off aggressively
                dx = sniper.x - target.x
                dy = sniper.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(sniper, sniper.x + (dx / d) * 40, sniper.y + (dy / d) * 40)
            elif dist < sniper_range - 10 and dist > 0:
                # Closer than we need to be — drift back
                dx = sniper.x - target.x
                dy = sniper.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(sniper, sniper.x + (dx / d) * 20, sniper.y + (dy / d) * 20)


# -- module-level helpers ---------------------------------------------------

def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _dist2(a, b) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2


def _closest(unit, targets):
    return min(targets, key=lambda t: _dist2(unit, t))


def _closest_within(unit, targets, max_dist) -> object | None:
    """Return the closest target within max_dist, or None."""
    max_dist_sq = max_dist * max_dist
    best = None
    best_d = max_dist_sq
    for t in targets:
        d = _dist2(unit, t)
        if d <= best_d:
            best_d = d
            best = t
    return best
