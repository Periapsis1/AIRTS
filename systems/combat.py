"""Combat system: laser attacks, heal-laser healing."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from entities.base import Entity
from entities.shapes import CircleEntity, RectEntity
from entities.unit import Unit, HOLD_FIRE, TARGET_FIRE, FREE_FIRE
from entities.weapon import Weapon
from entities.command_center import CommandCenter
from entities.laser import LaserFlash
from core.helpers import line_intersects_circle, line_intersects_rect, angle_diff, circle_overlaps_aabb
import config.audio as audio


@dataclass
class PendingChain:
    source: Unit            # attacker (for color/width/stats)
    weapon: Weapon          # weapon ref (damage, chain_range, colors)
    last_target: Entity     # chain origin point
    hit_set: set[int] = field(default_factory=set)  # entity_ids already hit
    delay: float = 0.0      # countdown; fires when <= 0
    team: int = 1           # attacker's team


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
    sounds=None,
    pending_chains: list[PendingChain] | None = None,
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
            for ability in a.abilities:
                ability.on_fire(a)
            lc = wpn.laser_color
            w = wpn.laser_width
            laser_flashes.append(
                LaserFlash(ax, ay, best_target.x, best_target.y, lc, w,
                           source=a, target=best_target)
            )
            if sounds is not None:
                snd = sounds.get(wpn.sound)
                if snd is not None:
                    snd.set_volume(audio.master_volume)
                    snd.play()

            # Chain initiation
            if pending_chains is not None and wpn.chain_range > 0 and a_dmg > 0:
                pending_chains.append(PendingChain(
                    source=a,
                    weapon=wpn,
                    last_target=best_target,
                    hit_set={a.entity_id, best_target.entity_id},
                    delay=wpn.chain_delay,
                    team=a.team,
                ))

    # -- process pending chains ----------------------------------------------
    if pending_chains is not None:
        still_active: list[PendingChain] = []
        for chain in pending_chains:
            chain.delay -= dt
            if chain.delay > 0:
                still_active.append(chain)
                continue

            # Find nearest valid target within chain_range of last_target
            origin = chain.last_target
            ox, oy = origin.x, origin.y
            best_next: Entity | None = None
            best_dist_sq = float("inf")
            cr_sq = chain.weapon.chain_range ** 2

            candidates = grid.query_radius(ox, oy, chain.weapon.chain_range) if grid is not None else combatants
            for b in candidates:
                if not b.alive or b.entity_id in chain.hit_set:
                    continue
                if not hasattr(b, "team") or b.team == chain.team:
                    continue
                dx = b.x - ox
                dy = b.y - oy
                d_sq = dx * dx + dy * dy
                if d_sq <= cr_sq and d_sq < best_dist_sq:
                    best_dist_sq = d_sq
                    best_next = b

            if best_next is not None:
                # Apply damage
                was_alive = best_next.alive
                best_next.take_damage(chain.weapon.damage)
                if stats is not None:
                    target_team = best_next.team if hasattr(best_next, "team") else 0
                    if target_team:
                        stats.record_damage(chain.team, target_team, chain.weapon.damage)
                        if was_alive and not best_next.alive:
                            stats.record_kill(chain.team, target_team)

                # Create laser flash from last_target to new target
                lc = chain.weapon.laser_color
                w = chain.weapon.laser_width
                laser_flashes.append(
                    LaserFlash(ox, oy, best_next.x, best_next.y, lc, w,
                               source=chain.last_target, target=best_next)
                )
                if sounds is not None:
                    snd = sounds.get(chain.weapon.sound)
                    if snd is not None:
                        snd.set_volume(audio.master_volume)
                        snd.play()

                # Queue next bounce
                chain.hit_set.add(best_next.entity_id)
                chain.last_target = best_next
                chain.delay = chain.weapon.chain_delay
                still_active.append(chain)
            # else: no valid target, chain ends (not re-added)

        pending_chains.clear()
        pending_chains.extend(still_active)
