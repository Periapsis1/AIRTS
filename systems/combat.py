"""Combat system: laser attacks, heal-laser healing."""
from __future__ import annotations
import math
from entities.base import Entity
from entities.shapes import CircleEntity, RectEntity
from entities.unit import Unit, HOLD_FIRE, TARGET_FIRE, FREE_FIRE
from entities.command_center import CommandCenter
from entities.laser import LaserFlash
from core.helpers import line_intersects_circle, line_intersects_rect, angle_diff, circle_overlaps_aabb


def _has_los(x1: float, y1: float, x2: float, y2: float,
             circle_obs, rect_obs) -> bool:
    """LOS check using pre-extracted obstacle tuples (no isinstance)."""
    for cx, cy, r in circle_obs:
        if line_intersects_circle(x1, y1, x2, y2, cx, cy, r):
            return False
    for rx, ry, rw, rh in rect_obs:
        if line_intersects_rect(x1, y1, x2, y2, rx, ry, rw, rh):
            return False
    return True


def _in_fov(unit: Unit, tx: float, ty: float) -> bool:
    """Return True if (tx, ty) is within the unit's field of view."""
    to_target = math.atan2(ty - unit.y, tx - unit.x)
    return abs(angle_diff(unit.facing_angle, to_target)) <= unit.fov / 2


def _pick_unit_target(
    a: Unit,
    ax: float, ay: float,
    a_range: float,
    combatants: list,
    own_idx: int,
    circle_obs, rect_obs,
    grid=None,
    team_aabb=None,
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
        if d <= a_range and _in_fov(a, preferred.x, preferred.y) and _has_los(ax, ay, preferred.x, preferred.y, circle_obs, rect_obs):
            return preferred
        return None

    # FREE_FIRE: prefer attack_target, else closest enemy
    if preferred is not None:
        d = math.hypot(preferred.x - ax, preferred.y - ay)
        if d <= a_range and _in_fov(a, preferred.x, preferred.y) and _has_los(ax, ay, preferred.x, preferred.y, circle_obs, rect_obs):
            return preferred

    # Early-exit: no enemy team units could be within range
    if team_aabb is not None:
        enemy_team = 2 if a.team == 1 else 1
        enemy_bb = team_aabb.get(enemy_team)
        if enemy_bb is None or not circle_overlaps_aabb(ax, ay, a_range, enemy_bb):
            return None

    best: Entity | None = None
    best_dist_sq = float("inf")
    range_sq = a_range * a_range
    candidates = grid.query_radius(ax, ay, a_range) if grid is not None else combatants
    for b in candidates:
        if b is a or not b.alive or b.team == a.team:
            continue
        dx = b.x - ax
        dy = b.y - ay
        d_sq = dx * dx + dy * dy
        if d_sq <= range_sq and d_sq < best_dist_sq:
            if not _in_fov(a, b.x, b.y):
                continue
            if _has_los(ax, ay, b.x, b.y, circle_obs, rect_obs):
                best_dist_sq = d_sq
                best = b
    return best


def _pick_friendly_target(
    a: Unit, ax: float, ay: float, a_range: float,
    units: list[Unit], circle_obs, rect_obs,
    grid=None,
) -> Unit | None:
    """Pick closest friendly unit that needs healing within range + LOS."""
    best: Unit | None = None
    best_dist_sq = float("inf")
    range_sq = a_range * a_range
    candidates = grid.query_radius(ax, ay, a_range) if grid is not None else units
    for u in candidates:
        if u is a or not u.alive or u.team != a.team:
            continue
        if isinstance(u, CommandCenter):
            continue
        if u.hp >= u.max_hp:
            continue
        dx = u.x - ax
        dy = u.y - ay
        d_sq = dx * dx + dy * dy
        if d_sq <= range_sq and d_sq < best_dist_sq:
            if not _in_fov(a, u.x, u.y):
                continue
            if _has_los(ax, ay, u.x, u.y, circle_obs, rect_obs):
                best_dist_sq = d_sq
                best = u
    return best


def combat_step(
    units: list[Unit],
    obstacles: list[Entity],
    laser_flashes: list[LaserFlash],
    dt: float,
    stats=None,
    grid=None,
    circle_obs=None,
    rect_obs=None,
    team_aabb=None,
):
    # Use pre-extracted obstacle geometry if provided, else extract here
    if circle_obs is None:
        circle_obs = tuple(
            (obs.x, obs.y, obs.radius)
            for obs in obstacles if isinstance(obs, CircleEntity)
        )
    if rect_obs is None:
        rect_obs = tuple(
            (obs.x, obs.y, obs.width, obs.height)
            for obs in obstacles if isinstance(obs, RectEntity)
        )

    combatants = [u for u in units if u.alive]

    for i, a in enumerate(combatants):
        if not a.alive or a.laser_cooldown > 0:
            continue
        if not a.can_attack:
            continue

        wpn = a.weapon
        if wpn is None:
            continue

        ax, ay = a.x, a.y
        a_range = wpn.range
        a_dmg = wpn.damage
        a_cd = wpn.cooldown

        if wpn.hits_only_friendly:
            best_target = _pick_friendly_target(a, ax, ay, a_range, combatants, circle_obs, rect_obs, grid)
        else:
            best_target = _pick_unit_target(a, ax, ay, a_range, combatants, i, circle_obs, rect_obs, grid, team_aabb)

        if best_target is not None:
            if a_dmg < 0:
                # Healing weapon
                heal_amt = abs(a_dmg)
                old_hp = best_target.hp
                best_target.hp = min(best_target.max_hp, best_target.hp + heal_amt)
                actual = best_target.hp - old_hp
                if stats is not None and actual > 0:
                    stats.record_healing(a.team, actual)
            else:
                # Damage weapon
                was_alive = best_target.alive
                best_target.take_damage(a_dmg)
                if stats is not None:
                    target_team = best_target.team if hasattr(best_target, "team") else 0
                    if target_team:
                        stats.record_damage(a.team, target_team, a_dmg)
                        if was_alive and not best_target.alive:
                            stats.record_kill(a.team, target_team)

            a.laser_cooldown = a_cd
            lc = wpn.laser_color
            w = wpn.laser_width
            laser_flashes.append(
                LaserFlash(ax, ay, best_target.x, best_target.y, lc, w,
                           source=a, target=best_target)
            )
