"""Tiled space background builder with randomised tile orientations."""
from __future__ import annotations

import os
import glob
import random
import pygame

from core.paths import asset_path

_TILE_DIR = asset_path("sprites", "background_tiles", "blue")


def _load_tile() -> pygame.Surface:
    """Load a random tile at full size, dimmed to 70% brightness."""
    tiles = glob.glob(os.path.join(_TILE_DIR, "*.png"))
    if not tiles:
        fallback = pygame.Surface((64, 64))
        fallback.fill((7, 7, 14))
        return fallback
    img = pygame.image.load(random.choice(tiles)).convert()
    # Dim to 70% brightness
    img.fill((179, 179, 179), special_flags=pygame.BLEND_RGB_MULT)
    return img


def build_background(width: int, height: int) -> tuple[pygame.Surface, pygame.Surface]:
    """Return *(tiled_bg, single_tile)*."""
    tile = _load_tile()
    tw, th = tile.get_size()

    bg = pygame.Surface((width, height))
    for y in range(0, height, th):
        for x in range(0, width, tw):
            bg.blit(tile, (x, y))
    return bg, tile


_scaled_cache: tuple[int, int, pygame.Surface] | None = None


def blit_screen_background(
    screen: pygame.Surface,
    game_area: pygame.Rect,
    camera,
    tile: pygame.Surface,
) -> None:
    """Tile the background across *game_area* in screen space (beyond-map fill)."""
    global _scaled_cache
    tw, th = tile.get_size()
    stw = max(1, int(tw * camera.zoom))
    sth = max(1, int(th * camera.zoom))

    # Cache the scaled tile — only recompute when dimensions change
    if _scaled_cache is None or _scaled_cache[0] != stw or _scaled_cache[1] != sth:
        _scaled_cache = (stw, sth, pygame.transform.smoothscale(tile, (stw, sth)))
    scaled = _scaled_cache[2]

    sx0, sy0 = camera.world_to_screen(0, 0)
    sx0 = int(sx0) + game_area.x
    sy0 = int(sy0) + game_area.y

    start_x = sx0 - ((sx0 - game_area.x) // stw + 1) * stw
    start_y = sy0 - ((sy0 - game_area.y) // sth + 1) * sth

    clip_save = screen.get_clip()
    screen.set_clip(game_area)
    y = start_y
    while y < game_area.bottom:
        x = start_x
        while x < game_area.right:
            screen.blit(scaled, (x, y))
            x += stw
        y += sth
    screen.set_clip(clip_save)
