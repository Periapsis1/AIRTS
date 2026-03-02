"""Numpy-vectorized batch operations for hot-path systems.

Replaces per-unit Python loops with batched C-level numpy operations for:
- Facing target selection (N×N distance matrix)
- Combat targeting for FREE_FIRE units
- LOS checks (line-segment vs circle/rect obstacles)
- Obstacle collision push resolution
"""
from __future__ import annotations

import math
import numpy as np

# Fire-mode constants (mirrored from entities.unit to avoid circular import)
_HOLD = 0
_TARGET = 1
_FREE = 2

_FIRE_MODE_MAP = {
    "hold_fire": _HOLD,
    "target_fire": _TARGET,
    "free_fire": _FREE,
}


def build_unit_arrays(units) -> dict[str, np.ndarray]:
    """Extract unit data into contiguous numpy arrays (built once per step).

    *units* is a list of alive, non-building Unit objects.
    Returns a dict of arrays all of length N (the number of units).
    """
    n = len(units)
    if n == 0:
        return {
            "x": np.empty(0, dtype=np.float64),
            "y": np.empty(0, dtype=np.float64),
            "team": np.empty(0, dtype=np.int32),
            "alive": np.empty(0, dtype=bool),
            "hp": np.empty(0, dtype=np.float64),
            "max_hp": np.empty(0, dtype=np.float64),
            "los": np.empty(0, dtype=np.float64),
            "range": np.empty(0, dtype=np.float64),
            "fov": np.empty(0, dtype=np.float64),
            "facing": np.empty(0, dtype=np.float64),
            "can_attack": np.empty(0, dtype=bool),
            "cooldown": np.empty(0, dtype=np.float64),
            "is_healer": np.empty(0, dtype=bool),
            "has_preferred": np.empty(0, dtype=bool),
            "fire_mode": np.empty(0, dtype=np.int8),
            "radius": np.empty(0, dtype=np.float64),
        }

    x = np.empty(n, dtype=np.float64)
    y = np.empty(n, dtype=np.float64)
    team = np.empty(n, dtype=np.int32)
    alive = np.empty(n, dtype=bool)
    hp = np.empty(n, dtype=np.float64)
    max_hp = np.empty(n, dtype=np.float64)
    los = np.empty(n, dtype=np.float64)
    rng = np.empty(n, dtype=np.float64)
    fov = np.empty(n, dtype=np.float64)
    facing = np.empty(n, dtype=np.float64)
    can_attack = np.empty(n, dtype=bool)
    cooldown = np.empty(n, dtype=np.float64)
    is_healer = np.empty(n, dtype=bool)
    has_preferred = np.empty(n, dtype=bool)
    fire_mode = np.empty(n, dtype=np.int8)
    radius = np.empty(n, dtype=np.float64)

    for i, u in enumerate(units):
        x[i] = u.x
        y[i] = u.y
        team[i] = u.team
        alive[i] = u.alive
        hp[i] = u.hp
        max_hp[i] = u.max_hp
        los[i] = u.line_of_sight
        rng[i] = u.attack_range
        fov[i] = u.fov
        facing[i] = u.facing_angle
        can_attack[i] = u.can_attack
        cooldown[i] = u.laser_cooldown
        is_healer[i] = u.weapon is not None and u.weapon.hits_only_friendly
        has_preferred[i] = u.attack_target is not None and u.attack_target.alive
        fire_mode[i] = _FIRE_MODE_MAP.get(u.fire_mode, _FREE)
        radius[i] = u.radius

    return {
        "x": x, "y": y, "team": team, "alive": alive,
        "hp": hp, "max_hp": max_hp, "los": los, "range": rng,
        "fov": fov, "facing": facing, "can_attack": can_attack,
        "cooldown": cooldown, "is_healer": is_healer,
        "has_preferred": has_preferred, "fire_mode": fire_mode,
        "radius": radius,
    }


def build_obstacle_arrays(circle_obs, rect_obs):
    """Convert pre-extracted obstacle tuples to numpy arrays.

    circle_obs: iterable of (cx, cy, radius)
    rect_obs:   iterable of (rx, ry, rw, rh)

    Returns (circle_arr: float64[K,3], rect_arr: float64[M,4]).
    """
    if circle_obs:
        circle_arr = np.array(circle_obs, dtype=np.float64)
        if circle_arr.ndim == 1:
            circle_arr = circle_arr.reshape(-1, 3)
    else:
        circle_arr = np.empty((0, 3), dtype=np.float64)

    if rect_obs:
        rect_arr = np.array(rect_obs, dtype=np.float64)
        if rect_arr.ndim == 1:
            rect_arr = rect_arr.reshape(-1, 4)
    else:
        rect_arr = np.empty((0, 4), dtype=np.float64)

    return circle_arr, rect_arr


# ---------------------------------------------------------------------------
# Batch facing targets
# ---------------------------------------------------------------------------

def batch_facing_targets(arrays: dict) -> np.ndarray:
    """For each unit find closest relevant target within LOS.

    Returns float64[N, 2] of target (x, y) positions; NaN = no target.
    """
    n = len(arrays["x"])
    result = np.full((n, 2), np.nan, dtype=np.float64)
    if n == 0:
        return result

    x = arrays["x"]
    y = arrays["y"]
    team = arrays["team"]
    alive = arrays["alive"]
    hp = arrays["hp"]
    max_hp = arrays["max_hp"]
    los = arrays["los"]
    is_healer = arrays["is_healer"]

    # N×N distance matrix
    dx = x[:, None] - x[None, :]  # (N, N)
    dy = y[:, None] - y[None, :]  # (N, N)
    dist_sq = dx * dx + dy * dy

    los_sq = los * los  # (N,)

    # Base validity: target alive, not self, within LOS
    valid = alive[None, :].repeat(n, axis=0)  # (N, N) - target alive
    np.fill_diagonal(valid, False)  # not self
    valid &= dist_sq <= los_sq[:, None]  # within LOS range

    # Split: healers want hurt allies, attackers want enemies
    healer_mask = is_healer[:, None]  # (N, 1)

    # For healers: same team AND hurt
    same_team = team[:, None] == team[None, :]
    hurt = hp[None, :] < max_hp[None, :]
    healer_valid = valid & healer_mask & same_team & hurt

    # For attackers: different team
    diff_team = ~same_team
    attacker_valid = valid & ~healer_mask & diff_team

    combined_valid = healer_valid | attacker_valid

    # Mask invalid entries with inf
    dist_masked = np.where(combined_valid, dist_sq, np.inf)

    # Find closest valid target per unit
    best_idx = np.argmin(dist_masked, axis=1)

    # Check that the best is actually valid (not inf)
    has_target = dist_masked[np.arange(n), best_idx] < np.inf

    result[has_target, 0] = x[best_idx[has_target]]
    result[has_target, 1] = y[best_idx[has_target]]

    return result


# ---------------------------------------------------------------------------
# Batch LOS checks
# ---------------------------------------------------------------------------

def _batch_line_circle(starts: np.ndarray, ends: np.ndarray,
                       circles: np.ndarray) -> np.ndarray:
    """Check L line segments against K circle obstacles.

    starts: (L, 2), ends: (L, 2), circles: (K, 3) — (cx, cy, r)
    Returns: bool[L] — True if ANY circle blocks that line.
    """
    L = starts.shape[0]
    K = circles.shape[0]
    if L == 0 or K == 0:
        return np.zeros(L, dtype=bool)

    # (L, 1, 2) - (1, K, 2) broadcasting
    cx = circles[:, 0]  # (K,)
    cy = circles[:, 1]  # (K,)
    cr = circles[:, 2]  # (K,)

    # Direction vectors
    d_x = ends[:, 0] - starts[:, 0]  # (L,)
    d_y = ends[:, 1] - starts[:, 1]  # (L,)

    # f = start - circle_center
    f_x = starts[:, 0, None] - cx[None, :]  # (L, K)
    f_y = starts[:, 1, None] - cy[None, :]  # (L, K)

    a = (d_x * d_x + d_y * d_y)[:, None]  # (L, 1)
    b = 2.0 * (f_x * d_x[:, None] + f_y * d_y[:, None])  # (L, K)
    c = f_x * f_x + f_y * f_y - cr[None, :] ** 2  # (L, K)

    disc = b * b - 4.0 * a * c  # (L, K)

    # Only check where discriminant >= 0 and segment has length
    has_hit = disc >= 0
    a_safe = np.where(a > 1e-12, a, 1.0)  # avoid /0

    sqrt_disc = np.sqrt(np.maximum(disc, 0.0))
    t1 = (-b - sqrt_disc) / (2.0 * a_safe)  # (L, K)
    t2 = (-b + sqrt_disc) / (2.0 * a_safe)  # (L, K)

    # Intersection if t1 or t2 in (0, 1)
    hit = has_hit & (a > 1e-12) & (
        ((t1 > 0) & (t1 < 1)) | ((t2 > 0) & (t2 < 1))
    )

    return np.any(hit, axis=1)  # (L,)


def _batch_line_rect(starts: np.ndarray, ends: np.ndarray,
                     rects: np.ndarray) -> np.ndarray:
    """Check L line segments against M rect obstacles (Liang-Barsky).

    starts: (L, 2), ends: (L, 2), rects: (M, 4) — (rx, ry, rw, rh)
    Returns: bool[L] — True if ANY rect blocks that line.
    """
    L = starts.shape[0]
    M = rects.shape[0]
    if L == 0 or M == 0:
        return np.zeros(L, dtype=bool)

    dx = ends[:, 0] - starts[:, 0]  # (L,)
    dy = ends[:, 1] - starts[:, 1]  # (L,)

    rx = rects[:, 0]  # (M,)
    ry = rects[:, 1]  # (M,)
    rw = rects[:, 2]  # (M,)
    rh = rects[:, 3]  # (M,)

    # Expand to (L, M)
    sx = starts[:, 0, None]  # (L, 1)
    sy = starts[:, 1, None]  # (L, 1)
    dx_ = dx[:, None]  # (L, 1)
    dy_ = dy[:, None]  # (L, 1)

    # Four edges: p, q arrays shape (L, M, 4)
    # Edge 0: left   (-dx, x1 - rx)
    # Edge 1: right  ( dx, rx+rw - x1)
    # Edge 2: bottom (-dy, y1 - ry)
    # Edge 3: top    ( dy, ry+rh - y1)
    p = np.stack([
        -dx_, dx_, -dy_, dy_
    ], axis=-1)  # (L, M, 4) — broadcast M dim via rx

    # Need to tile over M
    p = np.broadcast_to(
        np.stack([-dx_, dx_, -dy_, dy_], axis=-1),
        (L, M, 4)
    ).copy()

    q = np.stack([
        sx - rx[None, :],
        (rx + rw)[None, :] - sx,
        sy - ry[None, :],
        (ry + rh)[None, :] - sy,
    ], axis=-1)  # (L, M, 4)

    # Liang-Barsky: for each edge, compute te/tl updates
    te = np.zeros((L, M), dtype=np.float64)
    tl = np.ones((L, M), dtype=np.float64)
    ok = np.ones((L, M), dtype=bool)

    for edge in range(4):
        pe = p[:, :, edge]  # (L, M)
        qe = q[:, :, edge]  # (L, M)

        parallel = np.abs(pe) < 1e-12
        # Parallel and outside → reject
        ok &= ~(parallel & (qe < 0))

        # Non-parallel: compute t
        t = np.where(~parallel, qe / np.where(parallel, 1.0, pe), 0.0)

        # p < 0 → entering: te = max(te, t)
        entering = (~parallel) & (pe < 0)
        te = np.where(entering, np.maximum(te, t), te)

        # p > 0 → leaving: tl = min(tl, t)
        leaving = (~parallel) & (pe > 0)
        tl = np.where(leaving, np.minimum(tl, t), tl)

        ok &= te <= tl

    # Valid intersection: ok and segment overlap
    hit = ok & (tl > 0) & (te < 1) & (te < tl)

    return np.any(hit, axis=1)  # (L,)


def batch_los_blocked(starts: np.ndarray, ends: np.ndarray,
                      circle_obs_np: np.ndarray,
                      rect_obs_np: np.ndarray) -> np.ndarray:
    """Check L line segments against all obstacles.

    starts: (L, 2), ends: (L, 2)
    Returns: bool[L] — True if ANY obstacle blocks that line.
    """
    L = starts.shape[0]
    if L == 0:
        return np.empty(0, dtype=bool)

    blocked = np.zeros(L, dtype=bool)

    if circle_obs_np.shape[0] > 0:
        blocked |= _batch_line_circle(starts, ends, circle_obs_np)

    if rect_obs_np.shape[0] > 0:
        blocked |= _batch_line_rect(starts, ends, rect_obs_np)

    return blocked


# ---------------------------------------------------------------------------
# Batch combat targeting
# ---------------------------------------------------------------------------

def batch_combat_targeting(arrays: dict, circle_obs_np: np.ndarray,
                           rect_obs_np: np.ndarray) -> np.ndarray:
    """For FREE_FIRE units off cooldown without a preferred target, find closest enemy.

    Returns int32[N] — target index into units list, -1 = no target.
    """
    n = len(arrays["x"])
    result = np.full(n, -1, dtype=np.int32)
    if n == 0:
        return result

    x = arrays["x"]
    y = arrays["y"]
    team = arrays["team"]
    alive = arrays["alive"]
    can_attack = arrays["can_attack"]
    cooldown = arrays["cooldown"]
    fire_mode = arrays["fire_mode"]
    has_preferred = arrays["has_preferred"]
    rng = arrays["range"]
    fov = arrays["fov"]
    facing = arrays["facing"]
    is_healer = arrays["is_healer"]

    # Eligible attackers: alive, can_attack, off cooldown, FREE_FIRE, no preferred, not healer
    eligible = (
        alive & can_attack & (cooldown <= 0) &
        (fire_mode == _FREE) & ~has_preferred & ~is_healer
    )

    elig_idx = np.nonzero(eligible)[0]
    if len(elig_idx) == 0:
        return result

    # Enemy mask: alive and different team
    enemy_mask = alive.copy()  # potential targets must be alive

    # For each eligible attacker, compute distances to all units
    ex = x[elig_idx]  # (E,)
    ey = y[elig_idx]
    e_rng = rng[elig_idx]
    e_fov = fov[elig_idx]
    e_facing = facing[elig_idx]
    e_team = team[elig_idx]

    # Distance from each eligible to all units: (E, N)
    dx = x[None, :] - ex[:, None]  # (E, N)
    dy = y[None, :] - ey[:, None]
    dist = np.sqrt(dx * dx + dy * dy)

    # Valid targets: alive, different team, not self, within range
    valid = alive[None, :].repeat(len(elig_idx), axis=0)  # (E, N)
    valid &= team[None, :] != e_team[:, None]  # different team
    valid &= dist <= e_rng[:, None]  # within range

    # Self-exclusion (eligible attacker index vs all)
    for local_i, global_i in enumerate(elig_idx):
        valid[local_i, global_i] = False

    # FOV check: |angle_diff(facing, to_target)| <= fov/2
    angle_to = np.arctan2(dy, dx)  # (E, N)
    diff = (angle_to - e_facing[:, None]) % math.tau
    diff = np.where(diff > math.pi, diff - math.tau, diff)
    in_fov = np.abs(diff) <= (e_fov[:, None] / 2.0)
    valid &= in_fov

    # Mask invalid with inf before picking candidates
    dist_masked = np.where(valid, dist, np.inf)

    # For LOS checks, we only check the closest candidate per attacker
    # (optimization: check top candidate, if blocked try next, etc.)
    # Simple approach: check closest, use it if LOS clear
    best_idx = np.argmin(dist_masked, axis=1)  # (E,)
    has_candidate = dist_masked[np.arange(len(elig_idx)), best_idx] < np.inf

    if not np.any(has_candidate):
        return result

    # Gather starts/ends for LOS check
    cand_local = np.nonzero(has_candidate)[0]
    cand_global_attacker = elig_idx[cand_local]
    cand_global_target = best_idx[cand_local]

    starts = np.column_stack([x[cand_global_attacker], y[cand_global_attacker]])
    ends = np.column_stack([x[cand_global_target], y[cand_global_target]])

    blocked = batch_los_blocked(starts, ends, circle_obs_np, rect_obs_np)

    # Write results for unblocked candidates
    clear = ~blocked
    for local_i, is_clear in enumerate(clear):
        if is_clear:
            result[cand_global_attacker[local_i]] = cand_global_target[local_i]

    return result


# ---------------------------------------------------------------------------
# Batch obstacle push
# ---------------------------------------------------------------------------

def batch_obstacle_push(positions: np.ndarray, radii: np.ndarray,
                        circle_obs_np: np.ndarray,
                        rect_obs_np: np.ndarray) -> np.ndarray:
    """Vectorized unit-vs-obstacle collision resolution.

    positions: float64[N, 2] — (x, y) per unit
    radii:     float64[N]    — collision radius per unit
    circle_obs_np: float64[K, 3] — (cx, cy, r)
    rect_obs_np:   float64[M, 4] — (rx, ry, rw, rh)

    Returns: float64[N, 2] — corrected positions.
    """
    N = positions.shape[0]
    if N == 0:
        return positions.copy()

    pos = positions.copy()  # (N, 2)
    ur = radii  # (N,)

    # -- Circle obstacles --
    K = circle_obs_np.shape[0]
    if K > 0:
        ox = circle_obs_np[:, 0]  # (K,)
        oy = circle_obs_np[:, 1]  # (K,)
        orad = circle_obs_np[:, 2]  # (K,)

        # (N, K) distances
        dx = pos[:, 0, None] - ox[None, :]  # (N, K)
        dy = pos[:, 1, None] - oy[None, :]  # (N, K)
        dist_sq = dx * dx + dy * dy
        min_dist = ur[:, None] + orad[None, :]  # (N, K)
        min_dist_sq = min_dist * min_dist

        overlapping = dist_sq < min_dist_sq
        if np.any(overlapping):
            dist = np.sqrt(np.maximum(dist_sq, 1e-24))  # avoid /0
            push = np.maximum(min_dist - dist, 0.0)  # (N, K)
            nx = dx / dist  # (N, K)
            ny = dy / dist

            # Only apply where overlapping
            push_x = np.where(overlapping, nx * push, 0.0)
            push_y = np.where(overlapping, ny * push, 0.0)

            # Sum pushes from all circles
            pos[:, 0] += push_x.sum(axis=1)
            pos[:, 1] += push_y.sum(axis=1)

    # -- Rect obstacles --
    M = rect_obs_np.shape[0]
    if M > 0:
        rx = rect_obs_np[:, 0]  # (M,)
        ry = rect_obs_np[:, 1]
        rw = rect_obs_np[:, 2]
        rh = rect_obs_np[:, 3]

        # Closest point on rect to each unit: (N, M)
        ux = pos[:, 0, None]  # (N, 1)
        uy = pos[:, 1, None]

        cpx = np.clip(ux, rx[None, :], (rx + rw)[None, :])  # (N, M)
        cpy = np.clip(uy, ry[None, :], (ry + rh)[None, :])

        dx = ux - cpx  # (N, M)
        dy = uy - cpy
        dist_sq = dx * dx + dy * dy
        ur_sq = (ur * ur)[:, None]  # (N, 1)

        overlapping = dist_sq < ur_sq
        if np.any(overlapping):
            dist = np.sqrt(np.maximum(dist_sq, 1e-24))
            push = np.maximum(ur[:, None] - dist, 0.0)
            nx = dx / dist
            ny = dy / dist

            push_x = np.where(overlapping, nx * push, 0.0)
            push_y = np.where(overlapping, ny * push, 0.0)

            pos[:, 0] += push_x.sum(axis=1)
            pos[:, 1] += push_y.sum(axis=1)

    return pos
