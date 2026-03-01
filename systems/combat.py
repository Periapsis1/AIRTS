"""Combat system: laser attacks, medic healing, command-center aura healing."""
from __future__ import annotations
import math
from entities.base import Entity
from entities.shapes import CircleEntity, RectEntity
from entities.unit import Unit, HOLD_FIRE, TARGET_FIRE, FREE_FIRE
from entities.command_center import CommandCenter
from entities.metal_extractor import MetalExtractor
from entities.laser import LaserFlash
from core.helpers import line_intersects_circle, line_intersects_rect
from config.settings import (
    CC_LASER_RANGE, CC_LASER_DAMAGE, CC_LASER_COOLDOWN,
    UNIT_LASER_COLOR_T1, UNIT_LASER_COLOR_T2,
    CC_LASER_COLOR_T1, CC_LASER_COLOR_T2,
    CC_HEAL_RADIUS, CC_HEAL_RATE,
)


def has_los(x1: float, y1: float, x2: float, y2: float,
            obstacles: list[Entity]) -> bool:
    for obs in obstacles:
        if isinstance(obs, CircleEntity):
            if line_intersects_circle(x1, y1, x2, y2, obs.x, obs.y, obs.radius):
                return False
        elif isinstance(obs, RectEntity):
            if line_intersects_rect(x1, y1, x2, y2, obs.x, obs.y, obs.width, obs.height):
                return False
    return True


def _pick_unit_target(
    a: Unit,
    ax: float, ay: float,
    a_range: float,
    combatants: list,
    own_idx: int,
    obstacles: list[Entity],
) -> Entity | None:
    """Select a target respecting the unit's fire_mode and attack_target."""
    if a.fire_mode == HOLD_FIRE:
        return None

    preferred = a.attack_target
    if preferred is not None and not preferred.alive:
        a.attack_target = None
        preferred = None

    if a.fire_mode == TARGET_FIRE:
        if preferred is None:
            return None
        d = math.hypot(preferred.x - ax, preferred.y - ay)
        if d <= a_range and has_los(ax, ay, preferred.x, preferred.y, obstacles):
            return preferred
        return None

    # FREE_FIRE: prefer attack_target, else closest enemy
    if preferred is not None:
        d = math.hypot(preferred.x - ax, preferred.y - ay)
        if d <= a_range and has_los(ax, ay, preferred.x, preferred.y, obstacles):
            return preferred

    best: Entity | None = None
    best_dist = float("inf")
    for j, b in enumerate(combatants):
        if j == own_idx or not b.alive or b.team == a.team:
            continue
        d = math.hypot(b.x - ax, b.y - ay)
        if d <= a_range and d < best_dist:
            if has_los(ax, ay, b.x, b.y, obstacles):
                best_dist = d
                best = b
    return best


def combat_step(
    units: list[Unit],
    command_centers: list[CommandCenter],
    metal_extractors: list[MetalExtractor],
    obstacles: list[Entity],
    laser_flashes: list[LaserFlash],
    dt: float,
    stats=None,
):
    combatants: list = units + command_centers + metal_extractors  # type: ignore[operator]

    for i, a in enumerate(combatants):
        if isinstance(a, MetalExtractor):
            continue
        if not a.alive or a.laser_cooldown > 0:
            continue
        if isinstance(a, Unit) and not a.can_attack:
            continue

        a_team = a.team
        ax, ay = a.x, a.y

        if isinstance(a, Unit):
            a_range = a.attack_range
            a_dmg = a.attack_damage
            a_cd = a.attack_cooldown_max
            best_target = _pick_unit_target(a, ax, ay, a_range, combatants, i, obstacles)
        else:
            a_range = CC_LASER_RANGE
            a_dmg = CC_LASER_DAMAGE
            a_cd = CC_LASER_COOLDOWN
            best_target = None
            best_dist = float("inf")
            for j, b in enumerate(combatants):
                if j == i or not b.alive or b.team == a_team:
                    continue
                d = math.hypot(b.x - ax, b.y - ay)
                if d <= a_range and d < best_dist:
                    if has_los(ax, ay, b.x, b.y, obstacles):
                        best_dist = d
                        best_target = b

        if best_target is not None:
            was_alive = best_target.alive
            best_target.take_damage(a_dmg)
            if stats is not None:
                target_team = best_target.team if hasattr(best_target, "team") else 0
                if target_team:
                    stats.record_damage(a_team, target_team, a_dmg)
                    if was_alive and not best_target.alive:
                        stats.record_kill(a_team, target_team)
            a.laser_cooldown = a_cd
            lc = (UNIT_LASER_COLOR_T1 if isinstance(a, Unit) and a_team == 1
                  else UNIT_LASER_COLOR_T2 if isinstance(a, Unit)
                  else CC_LASER_COLOR_T1 if a_team == 1
                  else CC_LASER_COLOR_T2)
            w = 1 if isinstance(a, Unit) else 2
            laser_flashes.append(
                LaserFlash(ax, ay, best_target.x, best_target.y, lc, w)
            )


def medic_heal_step(units: list[Unit], dt: float, stats=None):
    for medic in units:
        if medic.unit_type != "medic" or not medic.alive:
            continue
        heal_amount = medic.heal_rate * dt
        candidates: list[tuple[float, Unit]] = []
        for u in units:
            if u is medic or u.team != medic.team or not u.alive:
                continue
            if u.hp >= u.max_hp:
                continue
            d = math.hypot(u.x - medic.x, u.y - medic.y)
            if d <= medic.heal_range:
                candidates.append((d, u))
        candidates.sort(key=lambda t: t[0])
        for _, target in candidates[:medic.heal_targets]:
            old_hp = target.hp
            target.hp = min(target.max_hp, target.hp + heal_amount)
            if stats is not None:
                stats.record_healing(medic.team, target.hp - old_hp)


def cc_heal_step(
    command_centers: list[CommandCenter],
    units: list[Unit],
    dt: float,
    stats=None,
):
    for cc in command_centers:
        if not cc.alive:
            continue
        heal_amount = CC_HEAL_RATE * dt
        for unit in units:
            if unit.team != cc.team or not unit.alive:
                continue
            if unit.hp >= unit.max_hp:
                continue
            d = math.hypot(unit.x - cc.x, unit.y - cc.y)
            if d <= CC_HEAL_RADIUS:
                old_hp = unit.hp
                unit.hp = min(unit.max_hp, unit.hp + heal_amount)
                if stats is not None:
                    stats.record_healing(cc.team, unit.hp - old_hp)
