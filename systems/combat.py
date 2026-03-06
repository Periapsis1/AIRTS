"""Combat system: laser attacks, heal-laser healing."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from entities.base import Entity
from entities.shapes import CircleEntity, RectEntity
from entities.unit import Unit, HOLD_FIRE, TARGET_FIRE, FREE_FIRE
from entities.weapon import Weapon
from entities.command_center import CommandCenter
from entities.laser import LaserFlash
from core.helpers import line_intersects_circle, line_intersects_rect, angle_diff
import config.audio as audio

if TYPE_CHECKING:
    from core.quadfield import QuadField


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


def _find_rotation_target(
    a: Unit,
    ax: float, ay: float,
    quadfield: QuadField,
    circle_obs, rect_obs,
) -> Entity | None:
    """Find nearest enemy/ally within LOS range for facing, even outside weapon range."""
    los = a.line_of_sight
    healer = a.weapon is not None and a.weapon.hits_only_friendly

    if healer:
        # Look for wounded allies within LOS
        allies = quadfield.get_team_units_exact(ax, ay, los, a.team)
        best = None
        best_dsq = float("inf")
        for u in allies:
            if u is a:
                continue
            if u.hp >= u.max_hp:
                continue
            if isinstance(u, CommandCenter):
                continue
            dx = u.x - ax
            dy = u.y - ay
            dsq = dx * dx + dy * dy
            if dsq < best_dsq:
                best_dsq = dsq
                best = u
        return best
    else:
        # Look for nearest enemy within LOS
        enemies = quadfield.get_enemy_units_exact(ax, ay, los, a.team)
        best = None
        best_dsq = float("inf")
        for b in enemies:
            dx = b.x - ax
            dy = b.y - ay
            dsq = dx * dx + dy * dy
            if dsq < best_dsq:
                best_dsq = dsq
                best = b
        return best


def combat_step(
    units: list[Unit],
    obstacles: list[Entity],
    laser_flashes: list[LaserFlash],
    dt: float,
    quadfield: QuadField | None = None,
    stats=None,
    circle_obs=None,
    rect_obs=None,
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

    for a in units:
        if not a.alive:
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

        best_target = None

        if a.laser_cooldown <= 0:
            if a.fire_mode == HOLD_FIRE:
                pass
            elif wpn.hits_only_friendly:
                # Healer: check nearest_ally for range, damage, FOV, LOS
                ally = a.nearest_ally
                if ally is not None and ally.alive and not isinstance(ally, CommandCenter):
                    if ally.hp < ally.max_hp:
                        d = math.hypot(ally.x - ax, ally.y - ay)
                        if d <= a_range and _in_fov(a, ally.x, ally.y) and _has_los(ax, ay, ally.x, ally.y, circle_obs, rect_obs):
                            best_target = ally
            else:
                # Attacker: honour attack_target first, then nearest_enemy
                preferred = a.attack_target
                if preferred is not None and not preferred.alive:
                    a.attack_target = None
                    preferred = None

                if a.fire_mode == TARGET_FIRE:
                    if preferred is not None:
                        d = math.hypot(preferred.x - ax, preferred.y - ay)
                        if d <= a_range and _in_fov(a, preferred.x, preferred.y) and _has_los(ax, ay, preferred.x, preferred.y, circle_obs, rect_obs):
                            best_target = preferred
                else:
                    # FREE_FIRE: prefer manual target, fall back to nearest_enemy
                    if preferred is not None:
                        d = math.hypot(preferred.x - ax, preferred.y - ay)
                        if d <= a_range and _in_fov(a, preferred.x, preferred.y) and _has_los(ax, ay, preferred.x, preferred.y, circle_obs, rect_obs):
                            best_target = preferred

                    if best_target is None:
                        enemy = a.nearest_enemy
                        if enemy is not None and enemy.alive:
                            d = math.hypot(enemy.x - ax, enemy.y - ay)
                            if d <= a_range and _in_fov(a, enemy.x, enemy.y) and _has_los(ax, ay, enemy.x, enemy.y, circle_obs, rect_obs):
                                best_target = enemy

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
        else:
            if a.nearest_enemy is not None:
                a._facing_target = a.nearest_enemy

    # -- process pending chains ----------------------------------------------
    if pending_chains is not None:
        # Brute-force over enemy team list (chain originates from last_target position)
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

            # Use quadfield for spatial query, fall back to brute-force
            if quadfield is not None:
                enemies = quadfield.get_enemy_units_exact(ox, oy, chain.weapon.chain_range, chain.team)
            else:
                enemies = units
            for b in enemies:
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
