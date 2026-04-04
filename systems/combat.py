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
from entities.laser import LaserFlash, SplashEffect
from core.helpers import line_intersects_circle, line_intersects_rect

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
    """LOS check using pre-extracted obstacle tuples.

    An AABB pre-filter rejects obstacles whose bounding box does not overlap
    the segment's bounding box before the full geometric test is attempted.
    """
    seg_min_x = x1 if x1 < x2 else x2
    seg_max_x = x2 if x1 < x2 else x1
    seg_min_y = y1 if y1 < y2 else y2
    seg_max_y = y2 if y1 < y2 else y1
    for cx, cy, r in circle_obs:
        if cx + r < seg_min_x or cx - r > seg_max_x:
            continue
        if cy + r < seg_min_y or cy - r > seg_max_y:
            continue
        if line_intersects_circle(x1, y1, x2, y2, cx, cy, r):
            return False
    for rx, ry, rw, rh in rect_obs:
        if rx + rw < seg_min_x or rx > seg_max_x:
            continue
        if ry + rh < seg_min_y or ry > seg_max_y:
            continue
        if line_intersects_rect(x1, y1, x2, y2, rx, ry, rw, rh):
            return False
    return True


def _in_fov(unit: Unit, tx: float, ty: float,
            facing_x: float, facing_y: float) -> bool:
    """Return True if (tx, ty) is within the unit's field of view.

    Uses a dot-product check against the precomputed facing vector instead of
    atan2, avoiding trigonometry on the per-target hot path.
    *facing_x/y* must be (cos(facing_angle), sin(facing_angle)) for the unit.
    """
    dx = tx - unit.x
    dy = ty - unit.y
    d_sq = dx * dx + dy * dy
    if d_sq < 1e-12:
        return True
    inv_d = 1.0 / math.sqrt(d_sq)
    return (dx * facing_x + dy * facing_y) * inv_d >= unit._fov_half_cos


def combat_step(
    units: list[Unit],
    obstacles: list[Entity],
    laser_flashes: list[LaserFlash],
    dt: float,
    quadfield: QuadField | None = None,
    stats=None,
    circle_obs=None,
    rect_obs=None,
    sound_events: list[str] | None = None,
    pending_chains: list[PendingChain] | None = None,
    splash_effects: list[SplashEffect] | None = None,
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
        a_range_sq = a.attack_range_sq                        # #1: avoid sqrt on range checks
        full_fov = a.fov >= math.tau - 0.01                   # #2: 360° units skip FOV check
        if not full_fov:                                       # #4: precompute facing vector
            a_facing_x = math.cos(a.facing_angle)
            a_facing_y = math.sin(a.facing_angle)
        else:
            a_facing_x = a_facing_y = 0.0
        rot_target: Unit | None = None                        # #3: healer rotation candidate

        # -- Active charge: count down and fire at locked world position -------
        if a._charge_pos is not None:
            a._charge_timer -= dt
            if a._charge_timer <= 0:
                tx, ty = a._charge_pos
                a._charge_pos = None
                a.laser_cooldown = a_cd  # cooldown starts after actual firing

                # Direct hit: find enemy whose hitbox contains the impact point
                direct_hit: Unit | None = None
                _cands = quadfield.get_enemy_units_exact(tx, ty, 15, a.team)
                _best_dsq = float("inf")
                for u in _cands:
                    if not u.alive:
                        continue
                    if hasattr(u, "team") and u.team == a.team:
                        continue
                    dx = u.x - tx
                    dy = u.y - ty
                    dsq = dx * dx + dy * dy
                    if dsq <= u.radius * u.radius and dsq < _best_dsq:
                        _best_dsq = dsq
                        direct_hit = u

                if direct_hit is not None:
                    was_alive = direct_hit.alive
                    direct_hit.take_damage(a_dmg)
                    if stats is not None:
                        tt = direct_hit.team if hasattr(direct_hit, "team") else 0
                        if tt:
                            stats.record_damage(a.team, tt, a_dmg)
                            if was_alive and not direct_hit.alive:
                                stats.record_kill(a.team, tt)

                # Splash to all units near impact (excluding direct hit unit)
                if wpn.splash_radius > 0:
                    splash_r_sq = wpn.splash_radius * wpn.splash_radius
                    if wpn.friendly_fire:                          # friendly fire: hit all
                        _scands = quadfield.get_units_exact(tx, ty, wpn.splash_radius)
                    else:
                        _scands = quadfield.get_enemy_units_exact(
                            tx, ty, wpn.splash_radius, a.team)
                    for u in _scands:
                        if u is direct_hit or not u.alive:
                            continue
                        if u is a:
                            continue
                        if not wpn.friendly_fire and hasattr(u, "team") and u.team == a.team:
                            continue
                        dx = u.x - tx
                        dy = u.y - ty
                        dsq = dx * dx + dy * dy
                        if dsq > splash_r_sq:
                            continue
                        t_frac = math.sqrt(dsq) / wpn.splash_radius
                        splash_dmg = wpn.splash_damage_max + t_frac * (
                            wpn.splash_damage_min - wpn.splash_damage_max)
                        was_alive = u.alive
                        u.take_damage(splash_dmg)
                        if stats is not None:
                            ut = u.team if hasattr(u, "team") else 0
                            if ut:
                                stats.record_damage(a.team, ut, splash_dmg)
                                if was_alive and not u.alive:
                                    stats.record_kill(a.team, ut)
                    if splash_effects is not None:
                        splash_effects.append(SplashEffect(tx, ty, wpn.splash_radius))

                if a.abilities:                                    # #8: skip loop for unitless units
                    for ability in a.abilities:
                        ability.on_fire(a)
                lc = wpn.laser_color
                w = wpn.laser_width
                # Beam endpoint is the locked world position (no target tracking)
                laser_flashes.append(
                    LaserFlash(ax, ay, tx, ty, lc, w,
                               source=a, target=None,
                               duration=wpn.laser_flash_duration)
                )
                if sound_events is not None:
                    sound_events.append(wpn.sound)
            continue  # skip normal combat logic while charging or just fired

        # -- Artillery ground-attack: fire at a specific world position ----------
        # While attack_ground_pos is set, skip normal combat entirely so the
        # artillery doesn't fire at other targets while waiting to rotate.
        if wpn.charge_time > 0 and getattr(a, 'attack_ground_pos', None) is not None:
            if a._charge_pos is None and a.laser_cooldown <= 0:
                gx, gy = a.attack_ground_pos
                dx_g = gx - ax
                dy_g = gy - ay
                if (dx_g * dx_g + dy_g * dy_g <= a_range_sq
                        and (full_fov or _in_fov(a, gx, gy, a_facing_x, a_facing_y))):
                    a._charge_pos = a.attack_ground_pos
                    a._charge_timer = wpn.charge_time
                    a.attack_ground_pos = None  # consume; single-shot ground attack
            continue  # always skip normal combat while ground attack is pending

        # -- Normal combat logic ----------------------------------------------
        best_target = None

        if a.laser_cooldown <= 0:
            if a.fire_mode == HOLD_FIRE:
                pass
            elif wpn.hits_only_friendly:
                # Single query at LOS range covers both weapon-range healing and
                # rotation-target tracking (#3), eliminating the second quadfield
                # call that _find_rotation_target previously issued.
                candidates = quadfield.get_team_units_exact(ax, ay, a.line_of_sight, a.team)
                best_hurt: Unit | None = None
                best_hurt_dsq = float("inf")
                rot_target_dsq = float("inf")
                for u in candidates:
                    if u is a or not u.alive or isinstance(u, CommandCenter):
                        continue
                    if u.team != a.team:
                        continue
                    dx, dy = u.x - ax, u.y - ay
                    dsq = dx * dx + dy * dy
                    if dsq < rot_target_dsq:           # track nearest ally for rotation
                        rot_target_dsq = dsq
                        rot_target = u
                    if dsq > a_range_sq or u.hp >= u.max_hp:
                        continue
                    if dsq < best_hurt_dsq:
                        best_hurt_dsq = dsq
                        best_hurt = u
                # Prefer manually assigned attack_target (heal priority) if valid
                preferred_heal = a.attack_target
                if (preferred_heal is not None and preferred_heal.alive
                        and hasattr(preferred_heal, 'team') and preferred_heal.team == a.team
                        and preferred_heal.hp < preferred_heal.max_hp):
                    dx_p, dy_p = preferred_heal.x - ax, preferred_heal.y - ay
                    if (dx_p * dx_p + dy_p * dy_p <= a_range_sq
                            and (full_fov or _in_fov(a, preferred_heal.x, preferred_heal.y, a_facing_x, a_facing_y))
                            and _has_los(ax, ay, preferred_heal.x, preferred_heal.y, circle_obs, rect_obs)):
                        best_hurt = preferred_heal
                if (best_hurt is not None
                        and (full_fov or _in_fov(a, best_hurt.x, best_hurt.y, a_facing_x, a_facing_y))
                        and _has_los(ax, ay, best_hurt.x, best_hurt.y, circle_obs, rect_obs)):
                    best_target = best_hurt
            else:
                # Attacker: honour attack_target first, then nearest_enemy
                preferred = a.attack_target
                if preferred is not None and not preferred.alive:
                    a.attack_target = None
                    preferred = None

                if a.fire_mode == TARGET_FIRE:
                    if preferred is not None:
                        dx = preferred.x - ax
                        dy = preferred.y - ay
                        if (dx * dx + dy * dy <= a_range_sq                       # #1: no sqrt
                                and (full_fov or _in_fov(a, preferred.x, preferred.y, a_facing_x, a_facing_y))  # #2 #4
                                and _has_los(ax, ay, preferred.x, preferred.y, circle_obs, rect_obs)):
                            best_target = preferred
                else:
                    # FREE_FIRE: prefer manual target, fall back to nearest_enemy
                    if preferred is not None:
                        dx = preferred.x - ax
                        dy = preferred.y - ay
                        if (dx * dx + dy * dy <= a_range_sq                       # #1
                                and (full_fov or _in_fov(a, preferred.x, preferred.y, a_facing_x, a_facing_y))  # #2 #4
                                and _has_los(ax, ay, preferred.x, preferred.y, circle_obs, rect_obs)):
                            best_target = preferred

                    if best_target is None:
                        enemy = a.nearest_enemy
                        if enemy is not None and enemy.alive:
                            dx = enemy.x - ax
                            dy = enemy.y - ay
                            if (dx * dx + dy * dy <= a_range_sq                   # #1
                                    and (full_fov or _in_fov(a, enemy.x, enemy.y, a_facing_x, a_facing_y))  # #2 #4
                                    and _has_los(ax, ay, enemy.x, enemy.y, circle_obs, rect_obs)):
                                best_target = enemy

        if best_target is not None:
            if wpn.charge_time > 0:
                # Initiate charge — lock onto target's CURRENT world position
                a._charge_pos = (best_target.x, best_target.y)
                a._charge_timer = wpn.charge_time
                # Cooldown starts only after the shot fires, not now
            elif a_dmg < 0:
                # Healing weapon
                heal_amt = abs(a_dmg)
                old_hp = best_target.hp
                best_target.hp = min(best_target.max_hp, best_target.hp + heal_amt)
                actual = best_target.hp - old_hp
                if stats is not None and actual > 0:
                    stats.record_healing(a.team, actual)

                a.laser_cooldown = a_cd
                if a.abilities:                                    # #8
                    for ability in a.abilities:
                        ability.on_fire(a)
                lc = wpn.laser_color
                w = wpn.laser_width
                laser_flashes.append(
                    LaserFlash(ax, ay, best_target.x, best_target.y, lc, w,
                               source=a, target=best_target,
                               duration=wpn.laser_flash_duration)
                )
                if sound_events is not None:
                    sound_events.append(wpn.sound)
            else:
                # Immediate damage weapon
                was_alive = best_target.alive
                best_target.take_damage(a_dmg)
                if stats is not None:
                    target_team = best_target.team if hasattr(best_target, "team") else 0
                    if target_team:
                        stats.record_damage(a.team, target_team, a_dmg)
                        if was_alive and not best_target.alive:
                            stats.record_kill(a.team, target_team)

                # Splash damage for immediate-fire weapons with splash
                if wpn.splash_radius > 0:
                    tx, ty = best_target.x, best_target.y
                    splash_r_sq = wpn.splash_radius * wpn.splash_radius
                    if wpn.friendly_fire:                          # friendly fire: hit all
                        splash_candidates = quadfield.get_units_exact(tx, ty, wpn.splash_radius)
                    else:
                        splash_candidates = quadfield.get_enemy_units_exact(
                            tx, ty, wpn.splash_radius, a.team)
                    for u in splash_candidates:
                        if u is best_target or not u.alive:
                            continue
                        if u is a:
                            continue
                        if not wpn.friendly_fire and hasattr(u, "team") and u.team == a.team:
                            continue
                        dx = u.x - tx
                        dy = u.y - ty
                        dsq = dx * dx + dy * dy
                        if dsq > splash_r_sq:
                            continue
                        t = math.sqrt(dsq) / wpn.splash_radius
                        splash_dmg = wpn.splash_damage_max + t * (
                            wpn.splash_damage_min - wpn.splash_damage_max)
                        was_alive = u.alive
                        u.take_damage(splash_dmg)
                        if stats is not None:
                            ut = u.team if hasattr(u, "team") else 0
                            if ut:
                                stats.record_damage(a.team, ut, splash_dmg)
                                if was_alive and not u.alive:
                                    stats.record_kill(a.team, ut)
                    if splash_effects is not None:
                        splash_effects.append(SplashEffect(
                            tx, ty, wpn.splash_radius))

                a.laser_cooldown = a_cd
                if a.abilities:                                    # #8
                    for ability in a.abilities:
                        ability.on_fire(a)
                lc = wpn.laser_color
                w = wpn.laser_width
                laser_flashes.append(
                    LaserFlash(ax, ay, best_target.x, best_target.y, lc, w,
                               source=a, target=best_target,
                               duration=wpn.laser_flash_duration)
                )
                if sound_events is not None:
                    sound_events.append(wpn.sound)

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
            if wpn.hits_only_friendly:
                # Healer: prefer attack_target (heal priority), fall back to rotation candidate
                if (a.attack_target is not None and a.attack_target.alive
                        and hasattr(a.attack_target, 'team') and a.attack_target.team == a.team):
                    a._facing_target = a.attack_target
                elif rot_target is not None:
                    a._facing_target = rot_target
            elif a.attack_target is not None and a.attack_target.alive:
                a._facing_target = a.attack_target
            elif a.nearest_enemy is not None:
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

            enemies = quadfield.get_enemy_units_exact(ox, oy, chain.weapon.chain_range, chain.team)
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
                if sound_events is not None:
                    sound_events.append(chain.weapon.sound)

                # Queue next bounce
                chain.hit_set.add(best_next.entity_id)
                chain.last_target = best_next
                chain.delay = chain.weapon.chain_delay
                still_active.append(chain)
            # else: no valid target, chain ends (not re-added)

        pending_chains.clear()
        pending_chains.extend(still_active)
