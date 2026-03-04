"""Hard Bot 2 — adaptive strategy with reactive builds, per-unit micro, and retreat logic.

Modifications over Hard AI:
1. Sniper tank-shield check: snipers hold ground when a friendly tank is between them and target
2. Base defense mode: rally all units when CC is under threat
3. Shockwave cap of 10: build snipers instead when at cap
"""
from __future__ import annotations
import math
import random
from systems.ai.base import BaseAI


class HardBot2(BaseAI):
    ai_id = "hard_bot_2"
    ai_name = "Hard Bot 2"

    _SCOUT_INTERVAL = 4

    def on_start(self) -> None:
        opener = random.choice(["scout", "shockwave", "sniper"])
        self._opener: str = opener
        self._strategy: str = {
            "scout": "ECO",
            "shockwave": "AGGRESSIVE_ECO",
            "sniper": "AGGRESSIVE",
        }[opener]
        self.set_build(opener)
        self._current_build: str = opener
        self._last_unit_count: int = 0
        self._cycles_since_scout: int = 0
        self._opener_spawned: bool = False
        self._had_medic: bool = False

    def on_step(self, iteration: int) -> None:
        cc = self.get_cc()
        if cc is None:
            return

        own = self.get_own_mobile_units()
        enemies = self.get_enemy_units()
        bw, bh = self.bounds
        mid_x = bw / 2.0

        scouts = [u for u in own if u.unit_type == "scout"]
        tanks = [u for u in own if u.unit_type == "tank"]
        snipers = [u for u in own if u.unit_type == "sniper"]
        medics = [u for u in own if u.unit_type == "medic"]
        shockwaves = [u for u in own if u.unit_type == "shockwave"]
        soldiers = [u for u in own if u.unit_type == "soldier"]
        machine_gunners = [u for u in own if u.unit_type == "machine_gunner"]

        if medics:
            self._had_medic = True

        # Track spawn cycles
        current_count = len(own)
        if current_count > self._last_unit_count:
            if not self._opener_spawned:
                self._opener_spawned = True
            if self._current_build == "scout":
                self._cycles_since_scout = 0
            else:
                self._cycles_since_scout += 1
        self._last_unit_count = current_count

        if self._opener_spawned:
            self._update_build(scouts, tanks, snipers, medics, shockwaves,
                               soldiers, machine_gunners, enemies)

        enemy_mobile = [e for e in enemies if not e.is_building]

        # --- Modification 2: Base Defense Mode ---
        if cc.hp < cc.max_hp * 0.8 and enemy_mobile:
            nearby_threats = [e for e in enemy_mobile if _dist(cc, e) < 100]
            if nearby_threats:
                rally_target = _closest(cc, nearby_threats)
                for u in own:
                    self.attack_unit(u, rally_target)
                return

        self._command_scouts(scouts, enemies, enemy_mobile, cc, bw, bh)
        self._command_shockwaves(shockwaves, enemy_mobile, cc)
        self._command_snipers(snipers, enemies, enemy_mobile, cc, mid_x, tanks)
        self._command_tanks(tanks, enemies, enemy_mobile, cc, mid_x)
        self._command_generic(soldiers, enemy_mobile, cc)
        self._command_generic(machine_gunners, enemy_mobile, cc)
        self._command_medics(medics, own, cc)

    # -- build order -----------------------------------------------------------

    def _set_build_once(self, unit_type: str) -> None:
        if self._current_build != unit_type:
            self.set_build(unit_type)
            self._current_build = unit_type

    def _get_dominant_type(self, enemies) -> str | None:
        mobile = [e for e in enemies if not e.is_building]
        if not mobile:
            return None
        counts: dict[str, int] = {}
        for e in mobile:
            counts[e.unit_type] = counts.get(e.unit_type, 0) + 1
        return max(counts, key=counts.get)

    def _update_build(self, scouts, tanks, snipers, medics, shockwaves,
                      soldiers, machine_gunners, enemies) -> None:
        # Rule 1: Replace dead medic
        if self._had_medic and not medics:
            self._set_build_once("medic")
            return

        # Rule 2: Replenish scouts
        if not scouts and self._cycles_since_scout >= self._SCOUT_INTERVAL:
            self._set_build_once("scout")
            return

        # Rule 3: Medic per 2 tanks
        if tanks and len(medics) < len(tanks) // 2:
            self._set_build_once("medic")
            return

        dominant = self._get_dominant_type(enemies)
        enemy_mobile = [e for e in enemies if not e.is_building]
        enemy_scouts = [e for e in enemy_mobile if e.unit_type == "scout"]

        # Rule 4: Enemy dominant = sniper
        if dominant == "sniper":
            if len(snipers) >= 2 and len(tanks) < len(snipers) // 2:
                self._set_build_once("tank")
            else:
                self._set_build_once("sniper")
            return

        # Rule 5: Enemy scouts > 6 — Modification 3: shockwave cap
        if len(enemy_scouts) > 6:
            if len(shockwaves) >= 10:
                self._set_build_once("sniper")
            else:
                self._set_build_once("shockwave")
            return

        # Rules 6-10: Counter dominant type
        counter = {
            "soldier": "shockwave",
            "tank": "sniper",
            "machine_gunner": "sniper",
            "shockwave": "sniper",
            "medic": "sniper",
        }
        if dominant in counter:
            # Modification 3: shockwave cap in counter dict
            choice = counter[dominant]
            if choice == "shockwave" and len(shockwaves) >= 10:
                choice = "sniper"
            self._set_build_once(choice)
            return

        # Rule 11: Get a medic once we have enough combat units
        effective = (len(scouts) / 3.0 + len(tanks) + len(snipers) +
                     len(shockwaves) + len(soldiers) + len(machine_gunners))
        if effective >= 3 and not medics:
            self._set_build_once("medic")
            return

        # Rule 12: Default
        self._set_build_once("sniper")

    # -- retreat / healing -----------------------------------------------------

    def _should_retreat(self, unit, cc) -> bool:
        threshold = 0.5 if unit.unit_type == "tank" else 0.75
        return unit.hp < unit.max_hp * threshold

    def _retreat_to_cc(self, unit, cc) -> None:
        if _dist(unit, cc) > 30:
            self.move_unit(unit, cc.x, cc.y)

    # -- helpers ---------------------------------------------------------------

    def _on_our_side(self, entity, mid_x: float) -> bool:
        return (entity.x < mid_x) if self._team == 1 else (entity.x > mid_x)

    def _flee_from(self, unit, threat, dist: float) -> None:
        dx = unit.x - threat.x
        dy = unit.y - threat.y
        d = math.hypot(dx, dy) or 1.0
        self.move_unit(unit, unit.x + (dx / d) * dist, unit.y + (dy / d) * dist)

    # -- scout behavior --------------------------------------------------------

    def _scout_move(self, scout, goal_x, goal_y, threats, bw, bh):
        dx = goal_x - scout.x
        dy = goal_y - scout.y
        goal_dist = math.hypot(dx, dy)
        if goal_dist < 1:
            return
        dir_x = dx / goal_dist
        dir_y = dy / goal_dist

        avoid_x = 0.0
        avoid_y = 0.0
        avoid_radius = 100.0
        for t in threats:
            tx = scout.x - t.x
            ty = scout.y - t.y
            td = math.hypot(tx, ty)
            if 0 < td < avoid_radius:
                strength = (avoid_radius - td) / avoid_radius
                avoid_x += (tx / td) * strength
                avoid_y += (ty / td) * strength

        if avoid_x or avoid_y:
            mx = dir_x + avoid_x * 2.0
            my = dir_y + avoid_y * 2.0
            ml = math.hypot(mx, my) or 1.0
            mx /= ml
            my /= ml
        else:
            mx, my = dir_x, dir_y

        step = min(60.0, goal_dist)
        dest_x = max(5.0, min(bw - 5.0, scout.x + mx * step))
        dest_y = max(5.0, min(bh - 5.0, scout.y + my * step))
        self.move_unit(scout, dest_x, dest_y)

    def _command_scouts(self, scouts, enemies, enemy_mobile, cc, bw, bh):
        if not scouts:
            return

        threats = enemy_mobile

        spots = self.get_metal_spots()
        all_extractors = self.get_metal_extractors()
        enemy_extractors = [e for e in all_extractors if e.team != self._team]

        extractor_spot_ids = set()
        for ext in all_extractors:
            if ext.metal_spot is not None:
                extractor_spot_ids.add(ext.metal_spot.entity_id)
        unclaimed = [s for s in spots if s.entity_id not in extractor_spot_ids]

        for scout in scouts:
            if self._should_retreat(scout, cc):
                self._retreat_to_cc(scout, cc)
                continue

            if unclaimed:
                target = _closest(scout, unclaimed)
                if _dist(scout, target) > 10:
                    self._scout_move(scout, target.x, target.y, threats, bw, bh)
            elif enemy_extractors:
                target = _closest(scout, enemy_extractors)
                self._scout_move(scout, target.x, target.y, threats, bw, bh)
                self.attack_unit(scout, target)
            else:
                if _dist(scout, cc) > 80:
                    self.move_unit(scout, cc.x, cc.y)

    # -- shockwave behavior ----------------------------------------------------

    def _shockwave_engage(self, sw, target):
        sw_range = sw.attack_range
        dist = _dist(sw, target)
        self.attack_unit(sw, target)

        if sw.laser_cooldown <= 0:
            if dist > sw_range:
                self.move_unit(sw, target.x, target.y)
        else:
            desired = sw_range * 0.7
            if dist < desired and dist > 0:
                dx = sw.x - target.x
                dy = sw.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(sw, sw.x + (dx / d) * 20, sw.y + (dy / d) * 20)

    def _shockwave_kite(self, sw, target):
        sw_range = sw.attack_range
        dist = _dist(sw, target)
        self.attack_unit(sw, target)

        if sw.laser_cooldown <= 0:
            if dist > sw_range:
                self.move_unit(sw, target.x, target.y)
        else:
            if dist < sw_range and dist > 0:
                dx = sw.x - target.x
                dy = sw.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(sw, sw.x + (dx / d) * 30, sw.y + (dy / d) * 30)

    def _command_shockwaves(self, shockwaves, enemy_mobile, cc):
        if not shockwaves:
            return

        dangerous_types = {"sniper", "shockwave"}

        for sw in shockwaves:
            if self._should_retreat(sw, cc):
                self._retreat_to_cc(sw, cc)
                continue

            # Flee from dangerous units within 150px
            nearby_danger = [
                e for e in enemy_mobile
                if e.unit_type in dangerous_types and _dist(sw, e) < 150
            ]
            if nearby_danger:
                threat = _closest(sw, nearby_danger)
                self._flee_from(sw, threat, 60)
                continue

            # Target non-sniper, non-shockwave enemies
            safe_targets = [
                e for e in enemy_mobile
                if e.unit_type not in dangerous_types
            ]
            if safe_targets:
                target = _closest(sw, safe_targets)
                self._shockwave_engage(sw, target)
            elif enemy_mobile:
                target = _closest(sw, enemy_mobile)
                self._shockwave_kite(sw, target)

    # -- sniper behavior -------------------------------------------------------

    def _sniper_kite(self, sniper, target, all_enemies, cc, tanks):
        sniper_range = sniper.attack_range
        dist = _dist(sniper, target)

        # --- Modification 1: Tank-shield check ---
        if sniper.laser_cooldown <= 0 and _tank_between(sniper, target, tanks):
            self.attack_unit(sniper, target)
            if dist > sniper_range:
                self.move_unit(sniper, target.x, target.y)
            return

        self.attack_unit(sniper, target)

        # Survival check
        for e in all_enemies:
            if e is target:
                continue
            d = _dist(sniper, e)
            if 0 < d < e.attack_range + 10:
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
            if dist > sniper_range:
                self.move_unit(sniper, target.x, target.y)
        else:
            enemy_range = getattr(target, "attack_range", 0)
            if dist < enemy_range + 15 and dist > 0:
                dx = sniper.x - target.x
                dy = sniper.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(sniper, sniper.x + (dx / d) * 40, sniper.y + (dy / d) * 40)
            elif dist < sniper_range - 10 and dist > 0:
                dx = sniper.x - target.x
                dy = sniper.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(sniper, sniper.x + (dx / d) * 20, sniper.y + (dy / d) * 20)

    def _command_snipers(self, snipers, enemies, enemy_mobile, cc, mid_x, tanks):
        if not snipers:
            return

        all_extractors = self.get_metal_extractors()
        extractor_spot_ids = set()
        for ext in all_extractors:
            if ext.metal_spot is not None:
                extractor_spot_ids.add(ext.metal_spot.entity_id)
        spots = self.get_metal_spots()
        unclaimed = [s for s in spots if s.entity_id not in extractor_spot_ids]
        enemy_extractors = [e for e in all_extractors if e.team != self._team]

        non_sniper_mobile = [e for e in enemy_mobile if e.unit_type != "sniper"]

        for sniper in snipers:
            if self._should_retreat(sniper, cc):
                self._retreat_to_cc(sniper, cc)
                continue

            if non_sniper_mobile:
                target = _closest(sniper, non_sniper_mobile)
                self._sniper_kite(sniper, target, enemy_mobile, cc, tanks)
            elif enemy_mobile:
                # Only snipers remain
                target = _closest(sniper, enemy_mobile)
                self._sniper_kite(sniper, target, enemy_mobile, cc, tanks)
            elif unclaimed and enemy_extractors:
                target = _closest(sniper, enemy_extractors)
                self.move_unit(sniper, target.x, target.y)
                self.attack_unit(sniper, target)
            elif enemies:
                target = _closest(sniper, enemies)
                self.move_unit(sniper, target.x, target.y)
                self.attack_unit(sniper, target)

    # -- tank behavior ---------------------------------------------------------

    def _tank_engage(self, tank, target):
        tank_range = tank.attack_range
        desired_dist = tank_range * 0.8
        dist = _dist(tank, target)

        self.attack_unit(tank, target)

        if dist > tank_range:
            dx = tank.x - target.x
            dy = tank.y - target.y
            d = math.hypot(dx, dy) or 1.0
            goal_x = target.x + (dx / d) * desired_dist
            goal_y = target.y + (dy / d) * desired_dist
            self.move_unit(tank, goal_x, goal_y)
        elif dist < desired_dist - 5:
            dx = tank.x - target.x
            dy = tank.y - target.y
            d = math.hypot(dx, dy) or 1.0
            self.move_unit(tank, tank.x + (dx / d) * 10, tank.y + (dy / d) * 10)

    def _command_tanks(self, tanks, enemies, enemy_mobile, cc, mid_x):
        if not tanks:
            return

        enemy_snipers_our_side = [
            e for e in enemy_mobile
            if e.unit_type == "sniper" and self._on_our_side(e, mid_x)
        ]

        for tank in tanks:
            if self._should_retreat(tank, cc):
                self._retreat_to_cc(tank, cc)
                continue

            if enemy_snipers_our_side:
                target = _closest(tank, enemy_snipers_our_side)
                self._tank_engage(tank, target)
            elif enemy_mobile:
                target = _closest(tank, enemy_mobile)
                self._tank_engage(tank, target)
            elif enemies:
                target = _closest(tank, enemies)
                self._tank_engage(tank, target)

    # -- generic kite (soldiers / machine gunners) -----------------------------

    def _generic_kite(self, unit, target):
        unit_range = unit.attack_range
        dist = _dist(unit, target)

        self.attack_unit(unit, target)

        if unit.laser_cooldown <= 0:
            if dist > unit_range:
                self.move_unit(unit, target.x, target.y)
        else:
            desired = unit_range * 0.7
            if dist < desired and dist > 0:
                dx = unit.x - target.x
                dy = unit.y - target.y
                d = math.hypot(dx, dy) or 1.0
                self.move_unit(unit, unit.x + (dx / d) * 15, unit.y + (dy / d) * 15)

    def _command_generic(self, units, enemy_mobile, cc):
        if not units:
            return
        for unit in units:
            if self._should_retreat(unit, cc):
                self._retreat_to_cc(unit, cc)
                continue
            if enemy_mobile:
                target = _closest(unit, enemy_mobile)
                self._generic_kite(unit, target)

    # -- medic behavior --------------------------------------------------------

    def _command_medics(self, medics, own, cc):
        if not medics:
            return

        allies = [u for u in own if u.unit_type != "medic"]

        for medic in medics:
            if not allies:
                if _dist(medic, cc) > 40:
                    self.move_unit(medic, cc.x, cc.y)
                continue

            # Follow most damaged ally
            damaged = [a for a in allies if a.hp < a.max_hp]
            if damaged:
                follow = min(damaged, key=lambda a: a.hp / a.max_hp)
            else:
                follow = allies[0]

            # Position 25px behind ally toward CC
            dx = cc.x - follow.x
            dy = cc.y - follow.y
            d = math.hypot(dx, dy)
            if d > 1:
                pos_x = follow.x + (dx / d) * 25.0
                pos_y = follow.y + (dy / d) * 25.0
            else:
                pos_x = follow.x
                pos_y = follow.y

            if math.hypot(medic.x - pos_x, medic.y - pos_y) > 15:
                self.move_unit(medic, pos_x, pos_y)


# -- module-level helpers ------------------------------------------------------

def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _dist2(a, b) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2


def _closest(unit, targets):
    return min(targets, key=lambda t: _dist2(unit, t))


def _closest_within(unit, targets, max_dist):
    max_dist_sq = max_dist * max_dist
    best = None
    best_d = max_dist_sq
    for t in targets:
        d = _dist2(unit, t)
        if d <= best_d:
            best_d = d
            best = t
    return best


def _tank_between(sniper, target, tanks) -> bool:
    """Return True if any friendly tank is between sniper and target.

    Projects each tank onto the sniper→target line segment and checks
    if the tank is within 20px perpendicular distance and between the
    two endpoints (parameter t in (0, 1)).
    """
    if not tanks:
        return False
    sx, sy = sniper.x, sniper.y
    tx, ty = target.x, target.y
    dx = tx - sx
    dy = ty - sy
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1.0:
        return False
    for tank in tanks:
        # Parameter t: projection of tank onto the sniper→target segment
        t = ((tank.x - sx) * dx + (tank.y - sy) * dy) / seg_len_sq
        if t <= 0.0 or t >= 1.0:
            continue
        # Closest point on segment to the tank
        proj_x = sx + t * dx
        proj_y = sy + t * dy
        perp_dist = math.hypot(tank.x - proj_x, tank.y - proj_y)
        if perp_dist < 20.0:
            return True
    return False
