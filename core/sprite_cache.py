"""Pre-rendered unit sprite cache — eliminates per-frame float rasterization jitter."""
from __future__ import annotations

import pygame
from config.unit_types import UNIT_TYPES

_cache: dict[tuple, pygame.Surface] = {}


def get_unit_sprite(unit_type: str, color: tuple, radius: int) -> pygame.Surface:
    """Return a cached SRCALPHA surface with the unit circle + symbol drawn at integer coords."""
    key = (unit_type, tuple(color[:3]), radius)
    surf = _cache.get(key)
    if surf is None:
        surf = _render(unit_type, color, radius)
        _cache[key] = surf
    return surf


def _render(unit_type: str, color: tuple, radius: int) -> pygame.Surface:
    pad = 2  # extra pixels for outline
    size = radius * 2 + pad * 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size // 2

    # Circle body — hollow ring for detector-style units, solid disc otherwise.
    stats = UNIT_TYPES.get(unit_type, {})
    if stats.get("hollow"):
        pygame.draw.circle(surf, color, (cx, cy), radius, max(1, radius // 2))
    else:
        pygame.draw.circle(surf, color, (cx, cy), radius)

    # Symbol (if any)
    symbol = stats.get("symbol")
    if symbol:
        scale = radius / 16.0
        pts = [(int(round(cx + px * scale)), int(round(cy + py * scale)))
               for px, py in symbol]
        pygame.draw.polygon(surf, (0, 0, 0), pts)
        pygame.draw.polygon(surf, color, pts, 1)

    return surf


def clear() -> None:
    """Drop all cached sprites (e.g. on settings change)."""
    _cache.clear()
