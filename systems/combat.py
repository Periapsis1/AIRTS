"""Combat system: laser attacks, heal-laser healing."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
import numpy as np
from entities.base import Entity
from entities.shapes import CircleEntity, RectEntity
from entities.unit import Unit, HOLD_FIRE, TARGET_FIRE, FREE_FIRE
from entities.weapon import Weapon
from entities.command_center import CommandCenter
from entities.laser import LaserFlash
from core.helpers import line_intersects_circle, line_intersects_rect, angle_diff
import config.audio as audio


@dataclass
class TargetingData:
    alive_t1: list[Unit]
    alive_t2: list[Unit]
    t1_sorted_enemy_idx: np.ndarray      # (N1, N2) sorted indices into alive_t2
    t1_sorted_enemy_dist_sq: np.ndarray  # (N1, N2) sorted squared distances
    t2_sorted_enemy_idx: np.ndarray      # (N2, N1) sorted indices into alive_t1
    t2_sorted_enemy_dist_sq: np.ndarray
    t1_sorted_ally_idx: np.ndarray       # (N1, N1) for healers
    t1_sorted_ally_dist_sq: np.ndarray
    t2_sorted_ally_idx: np.ndarray
    t2_sorted_ally_dist_sq: np.ndarray
    t1_index: dict[int, int]  # id(unit) -> index in alive_t1
    t2_index: dict[int, int]  # id(unit) -> index in alive_t2


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
    circle_obs, rect_obs,
) -> Entity | None:
    """Select a target respecting the unit's fire_mode and attack_target.

    Uses pre-clipped enemies_in_range list on the unit.
    """
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

    # Walk pre-clipped enemies_in_range (already sorted nearest-first, within weapon range)
    for b in a.enemies_in_range:
        if not b.alive:
            continue
        if not _in_fov(a, b.x, b.y):
            continue
        if _has_los(ax, ay, b.x, b.y, circle_obs, rect_obs):
            return b
    return None


def _pick_friendly_target(
    a: Unit, ax: float, ay: float,
    circle_obs, rect_obs,
) -> Unit | None:
    """Pick closest friendly unit that needs healing within range + LOS.

    Uses pre-clipped allies_in_range list on the unit.
    """
    for u in a.allies_in_range:
        if not u.alive:
            continue
        if isinstance(u, CommandCenter):
            continue
        if u.hp >= u.max_hp:
            continue
        if not _in_fov(a, u.x, u.y):
            continue
        if _has_los(ax, ay, u.x, u.y, circle_obs, rect_obs):
            return u
    return None


def _find_rotation_target(
    a: Unit,
    ax: float, ay: float,
    targeting: TargetingData,
    circle_obs, rect_obs,
) -> Entity | None:
    """Find nearest enemy/ally within LOS range for facing, even outside weapon range."""
    los_sq = a.line_of_sight * a.line_of_sight
    healer = a.weapon is not None and a.weapon.hits_only_friendly

    if healer:
        # Look for wounded allies
        if a.team == 1:
            my_idx = targeting.t1_index.get(id(a))
            if my_idx is None:
                return None
            sorted_idx = targeting.t1_sorted_ally_idx
            sorted_dsq = targeting.t1_sorted_ally_dist_sq
            search_list = targeting.alive_t1
        else:
            my_idx = targeting.t2_index.get(id(a))
            if my_idx is None:
                return None
            sorted_idx = targeting.t2_sorted_ally_idx
            sorted_dsq = targeting.t2_sorted_ally_dist_sq
            search_list = targeting.alive_t2
        if sorted_idx.size == 0:
            return None
        row_idx = sorted_idx[my_idx]
        row_dsq = sorted_dsq[my_idx]
        for j in range(len(row_idx)):
            d_sq = row_dsq[j]
            if d_sq > los_sq:
                break
            u = search_list[row_idx[j]]
            if not u.alive or u.hp >= u.max_hp:
                continue
            if isinstance(u, CommandCenter):
                continue
            return u
    else:
        # Look for enemies
        if a.team == 1:
            my_idx = targeting.t1_index.get(id(a))
            if my_idx is None:
                return None
            sorted_idx = targeting.t1_sorted_enemy_idx
            sorted_dsq = targeting.t1_sorted_enemy_dist_sq
            search_list = targeting.alive_t2
        else:
            my_idx = targeting.t2_index.get(id(a))
            if my_idx is None:
                return None
            sorted_idx = targeting.t2_sorted_enemy_idx
            sorted_dsq = targeting.t2_sorted_enemy_dist_sq
            search_list = targeting.alive_t1
        if sorted_idx.size == 0:
            return None
        row = sorted_idx[my_idx]
        row_d = sorted_dsq[my_idx]
        for j in range(len(row)):
            d_sq = row_d[j]
            if d_sq > los_sq:
                break
            b = search_list[row[j]]
            if not b.alive:
                continue
            return b
    return None


def combat_step(
    units: list[Unit],
    obstacles: list[Entity],
    laser_flashes: list[LaserFlash],
    dt: float,
    targeting: TargetingData | None = None,
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

    combatants = [u for u in units if u.alive]

    for a in combatants:
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
            if wpn.hits_only_friendly:
                if a.allies_in_range:
                    best_target = _pick_friendly_target(a, ax, ay, circle_obs, rect_obs)
            else:
                if a.enemies_in_range:
                    best_target = _pick_unit_target(a, ax, ay, a_range, circle_obs, rect_obs)

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
            # No shot — find a rotation target for facing
            if targeting and not a.is_building:
                if a.attack_target is None or not a.attack_target.alive:
                    a._facing_target = _find_rotation_target(a, ax, ay, targeting, circle_obs, rect_obs)

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

            # Brute-force: iterate enemy team list
            if targeting:
                enemies = targeting.alive_t2 if chain.team == 1 else targeting.alive_t1
            else:
                enemies = combatants
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
