"""Geometry helpers used across multiple systems."""
from __future__ import annotations
import math

def angle_diff(a: float, b: float) -> float:
    """Signed shortest angle from a to b, in radians. Result in (-pi, pi]."""
    d = (b - a) % math.tau
    if d > math.pi:
        d -= math.tau
    return d


def hexagon_points(radius: float) -> list[tuple[float, float]]:
    return [
        (radius * math.cos(math.radians(60 * i - 30)),
         radius * math.sin(math.radians(60 * i - 30)))
        for i in range(6)
    ]


def circle_overlaps_aabb(cx: float, cy: float, r: float,
                         aabb: tuple[float, float, float, float]) -> bool:
    """Return True if circle (cx, cy, r) overlaps axis-aligned bounding box.

    *aabb* is (min_x, min_y, max_x, max_y).
    """
    min_x, min_y, max_x, max_y = aabb
    nearest_x = max(min_x, min(cx, max_x))
    nearest_y = max(min_y, min(cy, max_y))
    dx = cx - nearest_x
    dy = cy - nearest_y
    return dx * dx + dy * dy <= r * r


def line_intersects_circle(
    x1: float, y1: float, x2: float, y2: float,
    cx: float, cy: float, r: float,
) -> bool:
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - cx, y1 - cy
    a = dx * dx + dy * dy
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c
    if disc < 0 or a < 1e-12:
        return False
    disc_sq = math.sqrt(disc)
    t1 = (-b - disc_sq) / (2 * a)
    t2 = (-b + disc_sq) / (2 * a)
    return (0 < t1 < 1) or (0 < t2 < 1)


def _clip(denom: float, numer: float, te: float, tl: float) -> tuple[bool, float, float]:
    if abs(denom) < 1e-12:
        return numer <= 0, te, tl
    t = numer / denom
    if denom < 0:
        te = max(te, t)
    else:
        tl = min(tl, t)
    return te <= tl, te, tl


def line_intersects_rect(
    x1: float, y1: float, x2: float, y2: float,
    rx: float, ry: float, rw: float, rh: float,
) -> bool:
    """Liang-Barsky line-rect intersection for segment (x1,y1)-(x2,y2)."""

    dx, dy = x2 - x1, y2 - y1
    te, tl = 0.0, 1.0
    ok, te, tl = _clip(-dx, x1 - rx, te, tl)
    if not ok:
        return False
    ok, te, tl = _clip(dx, rx + rw - x1, te, tl)
    if not ok:
        return False
    ok, te, tl = _clip(-dy, y1 - ry, te, tl)
    if not ok:
        return False
    ok, te, tl = _clip(dy, ry + rh - y1, te, tl)
    if not ok:
        return False
    return te < tl and tl > 0 and te < 1
