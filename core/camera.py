"""Camera — zoom & pan for the world viewport."""
from __future__ import annotations
import pygame


class Camera:
    """Tracks a viewport into a world-sized surface.

    *viewport_w/h*: pixel size of the on-screen destination area.
    *world_w/h*: pixel size of the full world surface.
    """

    def __init__(self, viewport_w: int, viewport_h: int,
                 world_w: int, world_h: int, max_zoom: float = 3.0):
        self.viewport_w = viewport_w
        self.viewport_h = viewport_h
        self.world_w = world_w
        self.world_h = world_h

        # Zoom limits — ensure full map visible; allow < 1.0 when viewport > world
        self.min_zoom = min(viewport_w / world_w, viewport_h / world_h)
        if self.min_zoom > 1.0:
            self.min_zoom = 1.0
        self.max_zoom = max_zoom

        # Start fully zoomed out (whole map visible)
        self.zoom = self.min_zoom if self.min_zoom < 1.0 else 1.0
        # Center of the viewport in world coordinates
        self.cx = world_w / 2.0
        self.cy = world_h / 2.0
        self._clamp()

        # Reusable scale buffer — avoids the ~viewport-sized per-frame surface
        # allocation that `pygame.transform.scale` does implicitly when no
        # dest_surface is passed. Re-created only when the scaled dimensions
        # change (zoom change, or edge panning that clips the viewport).
        self._scale_buffer: pygame.Surface | None = None

    # -- mutators -----------------------------------------------------------

    def pan(self, dx_screen: float, dy_screen: float) -> None:
        """Pan by a screen-space delta (e.g. from mouse drag)."""
        self.cx -= dx_screen / self.zoom
        self.cy -= dy_screen / self.zoom
        self._clamp()

    def zoom_at(self, screen_x: float, screen_y: float, factor: float) -> None:
        """Zoom by *factor* anchored on the screen point (*screen_x*, *screen_y*).

        The world point under the cursor stays fixed after zooming.
        """
        # World point under cursor before zoom
        wx, wy = self.screen_to_world(screen_x, screen_y)

        new_zoom = self.zoom * factor
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))
        self.zoom = new_zoom

        # Adjust center so (wx, wy) stays at (screen_x, screen_y)
        self.cx = wx + (self.viewport_w / 2.0 - screen_x) / self.zoom
        self.cy = wy + (self.viewport_h / 2.0 - screen_y) / self.zoom
        self._clamp()

    def center_on(self, wx: float, wy: float) -> None:
        """Center the viewport on a world coordinate."""
        self.cx = wx
        self.cy = wy
        self._clamp()

    def reset(self) -> None:
        """Reset camera to default position (centered, fully zoomed out)."""
        self.zoom = self.min_zoom if self.min_zoom < 1.0 else 1.0
        self.cx = self.world_w / 2.0
        self.cy = self.world_h / 2.0
        self._clamp()

    # -- coordinate transforms ----------------------------------------------

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        """Convert a screen (viewport-relative) coordinate to world space."""
        wx = self.cx - self.viewport_w / (2.0 * self.zoom) + sx / self.zoom
        wy = self.cy - self.viewport_h / (2.0 * self.zoom) + sy / self.zoom
        return wx, wy

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        """Convert a world coordinate to screen (viewport-relative) space."""
        sx = (wx - self.cx) * self.zoom + self.viewport_w / 2.0
        sy = (wy - self.cy) * self.zoom + self.viewport_h / 2.0
        return sx, sy

    def get_world_viewport_rect(self) -> pygame.Rect:
        """Return the visible world rectangle."""
        half_w = self.viewport_w / (2.0 * self.zoom)
        half_h = self.viewport_h / (2.0 * self.zoom)
        x = self.cx - half_w
        y = self.cy - half_h
        return pygame.Rect(int(x), int(y), int(half_w * 2), int(half_h * 2))

    # -- projection ---------------------------------------------------------

    def apply(self, world_surface: pygame.Surface,
              target_surface: pygame.Surface,
              dest: tuple[int, int] = (0, 0)) -> None:
        """Extract the visible viewport from *world_surface*, scale it, and
        blit to *target_surface* at *dest*.

        At zoom == 1.0 (the most common case) the scale step is a no-op pixel
        copy — skip it and blit the subsurface directly.
        """
        vp = self.get_world_viewport_rect()
        clipped = vp.clip(world_surface.get_rect())
        if clipped.w <= 0 or clipped.h <= 0:
            return
        sub = world_surface.subsurface(clipped)
        if self.zoom == 1.0:
            target_surface.blit(sub, (dest[0] + clipped.x - vp.x,
                                      dest[1] + clipped.y - vp.y))
            return
        scaled_w = int(clipped.w * self.zoom)
        scaled_h = int(clipped.h * self.zoom)
        if scaled_w <= 0 or scaled_h <= 0:
            return
        buf = self._scale_buffer
        if buf is None or buf.get_size() != (scaled_w, scaled_h):
            buf = pygame.Surface((scaled_w, scaled_h))
            self._scale_buffer = buf
        pygame.transform.scale(sub, (scaled_w, scaled_h), buf)
        offset_x = int((clipped.x - vp.x) * self.zoom)
        offset_y = int((clipped.y - vp.y) * self.zoom)
        target_surface.blit(buf, (dest[0] + offset_x, dest[1] + offset_y))

    # -- internal -----------------------------------------------------------

    def _clamp(self) -> None:
        """Allow panning so the world edge can reach the viewport center,
        creating dead space beyond the map border."""
        # cx=0 puts the left world edge at screen center;
        # cx=world_w puts the right world edge at screen center.
        self.cx = max(0, min(self.world_w, self.cx))
        self.cy = max(0, min(self.world_h, self.cy))
