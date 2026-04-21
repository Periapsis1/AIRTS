"""GPU rendering foundation — wraps pygame._sdl2.video Window + Renderer.

This module is the foundation for the planned GPU migration. It exposes a
`GpuContext` that owns an SDL2 window and hardware-accelerated renderer,
plus helpers for uploading CPU surfaces to textures and creating GPU-side
render targets.

Status: Phase 1 (foundation). Not yet used by screens. The app runs on the
existing CPU pipeline unless `display_config.renderer_mode == "gpu"` is
set, in which case the compat layer in `config/display.py` wires this
context up to a scratch-surface upload flow so screens keep working
unchanged while we incrementally migrate hot paths.

API summary
-----------
    ctx = GpuContext(size=(1920, 1080), title="AIRTS")
    ctx.clear((0, 0, 0))
    tex = ctx.texture_from_surface(surface)
    ctx.renderer.blit(tex, dst_rect)   # or tex.draw(dstrect=...)
    ctx.present()

    # For render targets (draw into a texture via renderer primitives):
    target = ctx.make_target_texture(size)
    ctx.push_target(target)
    ctx.renderer.draw_line((0, 0), (100, 0))
    ctx.pop_target()  # restore default target (the window backbuffer)

    # For compat: streaming-updated texture backed by a CPU surface.
    tex = ctx.streaming_texture(size)
    tex.update(my_cpu_surface)   # upload dirty pixels

Design notes
------------
* ``pygame._sdl2.video`` is part of pygame 2. It is marked "experimental"
  but has been stable for major-feature use since 2.1. We pin to the
  current pygame version in ``requirements.txt``.
* The renderer's built-in primitives are limited (lines, points, rects).
  Anything procedural (circles, polygons, thick lines) is either
  pre-rendered on a CPU Surface and uploaded as a Texture, or drawn via
  many draw_line calls. The compat flow in Phase 1/2 keeps procedural
  CPU drawing intact and only moves the final composite onto the GPU.
"""
from __future__ import annotations

from typing import Optional

import pygame
from pygame._sdl2 import video as _sdl2_video


class GpuContext:
    """Wraps an SDL2 Window + Renderer pair with a small helper surface.

    Lifecycle: construct once at app startup, keep for the process lifetime.
    `pygame.init()` must have been called before constructing.
    """

    def __init__(
        self,
        size: tuple[int, int],
        title: str = "AIRTS",
        vsync: bool = True,
        accelerated: bool = True,
        borderless: bool = False,
    ) -> None:
        # Establish a pygame display format so Surface.convert() /
        # pygame.image.load(...).convert() keep working. The SDL2 Window
        # below is separate from pygame's display window and doesn't set
        # a pixel format on its own. A 1x1 hidden window is enough for
        # pygame to pick a default format; it's never visible to the user.
        if not pygame.display.get_init():
            pygame.display.init()
        hidden_flag = getattr(pygame, "HIDDEN", 0)
        pygame.display.set_mode((1, 1), hidden_flag)

        self.window = _sdl2_video.Window(
            title,
            size=size,
            borderless=borderless,
        )
        # Prefer hardware-accelerated rendering, but fall back to software
        # when no GPU driver is available (e.g. the "dummy" video driver
        # used for headless tests).
        try:
            self.renderer = _sdl2_video.Renderer(
                self.window,
                accelerated=1 if accelerated else 0,
                vsync=vsync,
            )
        except Exception:
            self.renderer = _sdl2_video.Renderer(
                self.window,
                accelerated=0,
                vsync=0,
            )
        self.size = size
        # Stack of render targets so callers can temporarily redirect draws
        # into a target texture and then restore the default (window).
        self._target_stack: list[Optional[_sdl2_video.Texture]] = []

    # -- frame lifecycle ----------------------------------------------------

    def clear(self, color: tuple[int, int, int] = (0, 0, 0)) -> None:
        """Clear the current render target to *color*."""
        # Renderer.draw_color demands an RGBA 4-tuple.
        if len(color) == 3:
            self.renderer.draw_color = (color[0], color[1], color[2], 255)
        else:
            self.renderer.draw_color = color
        self.renderer.clear()

    def present(self) -> None:
        """Push the backbuffer to the window. Equivalent of display.flip()."""
        self.renderer.present()

    # -- texture helpers ----------------------------------------------------

    def texture_from_surface(self, surface: pygame.Surface) -> _sdl2_video.Texture:
        """Upload *surface* to GPU as a static Texture.

        Good for assets that don't change per frame (sprites, pre-rendered
        glyphs). The texture is independent of the source surface — later
        mutations to `surface` do not affect the texture.
        """
        return _sdl2_video.Texture.from_surface(self.renderer, surface)

    def streaming_texture(
        self, size: tuple[int, int],
    ) -> _sdl2_video.Texture:
        """Create a streaming Texture sized *size*.

        Streaming textures are intended for per-frame updates via
        ``tex.update(surface_or_buffer)`` — the SDL2 driver reserves a
        region that can be memcpy'd into cheaply. Use for "render on CPU
        surface, show on GPU" compat flow.
        """
        return _sdl2_video.Texture(
            self.renderer, size,
            streaming=True,
        )

    def make_target_texture(
        self, size: tuple[int, int],
    ) -> _sdl2_video.Texture:
        """Create a Texture that can be used as a render target.

        Calls ``ctx.push_target(tex)`` temporarily to redirect renderer
        primitives (draw_line, fill_rect, blit) into the texture's pixels
        instead of the window backbuffer.
        """
        return _sdl2_video.Texture(
            self.renderer, size,
            target=True,
        )

    # -- target stack -------------------------------------------------------

    def push_target(
        self, texture: Optional[_sdl2_video.Texture],
    ) -> None:
        """Redirect subsequent renderer draws into *texture*.

        Pass ``None`` to redirect back to the window backbuffer. Use
        ``pop_target()`` to restore the previous target.
        """
        self._target_stack.append(self.renderer.target)
        self.renderer.target = texture

    def pop_target(self) -> None:
        """Restore the previous render target. Pairs with ``push_target``."""
        if not self._target_stack:
            return
        self.renderer.target = self._target_stack.pop()


class GpuCompatScreen:
    """A CPU scratch Surface that doubles as the "screen" for legacy code.

    Phase 1 compatibility layer: legacy screens still call
    ``screen.blit(...)``, ``pygame.draw.*(screen, ...)``, etc. We hand them
    a regular ``pygame.Surface`` so that works unchanged. At flip time we
    upload this surface's pixels into a streaming texture and draw it to
    the window via the GPU renderer.

    Cost: one full-window memcpy + SDL texture upload per flip (roughly
    2 ms for 1080p). Phase 2+ migrations can bypass this surface for
    performance-critical paths by drawing directly with the renderer.

    Usage:
        compat = GpuCompatScreen(ctx)
        screens_get_compat.screen   # pygame.Surface — legacy API works
        # at end of frame:
        compat.present()             # replaces pygame.display.flip()
    """

    def __init__(self, ctx: GpuContext) -> None:
        self._ctx = ctx
        self.surface = pygame.Surface(ctx.size)
        # Keep a streaming texture for cheap repeated updates.
        self._tex = ctx.streaming_texture(ctx.size)

    def present(self) -> None:
        """Upload the scratch surface to the GPU and present the frame."""
        # update(surface) copies the surface pixels into the texture's
        # locked region — a single driver-optimized memcpy.
        self._tex.update(self.surface)
        self._ctx.clear((0, 0, 0))
        self._tex.draw()
        self._ctx.present()


__all__ = ["GpuContext", "GpuCompatScreen"]
