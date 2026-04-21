"""Display mode settings — windowed fullscreen (borderless) or 1280x720 windowed."""
from __future__ import annotations
import json
import os
import pygame

from core.paths import app_path
_SETTINGS_PATH = app_path("display_settings.json")

display_mode: str = "windowed_fullscreen"
color_mode: str = "player"          # "player" or "team"
selection_mode: str = "rectangle"   # "rectangle" or "circle"
movement_smoothing: bool = True     # client-side movement extrapolation
# "cpu" (default) uses pygame.display.set_mode + screen.blit. "gpu" uses
# pygame._sdl2.video.Renderer; during phases 1-2 of the GPU migration,
# screens still draw to a CPU scratch surface that gets uploaded to a
# streaming texture and presented via the renderer on each flip. Set to
# "gpu" to exercise that path.
renderer_mode: str = "cpu"

# Module-level singletons populated by `create_display()` when
# renderer_mode == "gpu" so other modules can reach the renderer without
# threading it through every constructor.
_gpu_ctx = None           # type: "core.gpu.GpuContext | None"
_gpu_compat = None        # type: "core.gpu.GpuCompatScreen | None"


def gpu_context():
    """Return the active GpuContext (or None when running CPU-mode)."""
    return _gpu_ctx


def gpu_compat_screen():
    """Return the active GpuCompatScreen (or None in CPU mode)."""
    return _gpu_compat


def present_frame() -> None:
    """Abstract over pygame.display.flip() / renderer.present().

    Screens currently call `pygame.display.flip()` directly. Phase-2
    migrations will replace those calls with this function so that the
    frame is presented correctly in both CPU and GPU modes.
    """
    if _gpu_compat is not None:
        _gpu_compat.present()
    else:
        pygame.display.flip()


def load_settings() -> None:
    """Load display settings from disk."""
    global display_mode, color_mode, selection_mode, movement_smoothing
    global renderer_mode
    try:
        with open(_SETTINGS_PATH, "r") as f:
            data = json.load(f)
        mode = data.get("display_mode", "windowed_fullscreen")
        if mode in ("windowed_fullscreen", "windowed"):
            display_mode = mode
        cm = data.get("color_mode", "player")
        if cm in ("player", "team"):
            color_mode = cm
        sm = data.get("selection_mode", "rectangle")
        if sm in ("rectangle", "circle"):
            selection_mode = sm
        movement_smoothing = bool(data.get("movement_smoothing", True))
        rm = data.get("renderer_mode", "cpu")
        if rm in ("cpu", "gpu"):
            renderer_mode = rm
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def save_settings() -> None:
    """Persist display settings to disk."""
    try:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump({
                "display_mode": display_mode,
                "color_mode": color_mode,
                "selection_mode": selection_mode,
                "movement_smoothing": movement_smoothing,
                "renderer_mode": renderer_mode,
            }, f, indent=2)
    except OSError:
        pass


def set_mode(mode: str) -> None:
    """Update display mode and save."""
    global display_mode
    if mode in ("windowed_fullscreen", "windowed"):
        display_mode = mode
        save_settings()


def set_color_mode(mode: str) -> None:
    """Update color mode and save."""
    global color_mode
    if mode in ("player", "team"):
        color_mode = mode
        save_settings()


def set_selection_mode(mode: str) -> None:
    """Update selection mode and save."""
    global selection_mode
    if mode in ("rectangle", "circle"):
        selection_mode = mode
        save_settings()


def set_movement_smoothing(enabled: bool) -> None:
    """Update movement smoothing and save."""
    global movement_smoothing
    movement_smoothing = enabled
    save_settings()


def create_display() -> pygame.Surface:
    """Create and return the pygame display surface for the current mode.

    In ``renderer_mode == "cpu"`` (default) this calls
    ``pygame.display.set_mode(...)`` and returns the resulting Surface —
    the long-standing behaviour.

    In ``renderer_mode == "gpu"`` it creates a ``GpuContext`` (SDL2
    Window + Renderer) plus a ``GpuCompatScreen`` that exposes a CPU
    scratch Surface for legacy drawing code. The returned object is that
    scratch Surface, so caller code can keep using the pygame Surface
    API unchanged. The context + compat screen are stashed as module
    singletons (``gpu_context()`` / ``gpu_compat_screen()``) so other
    modules can reach them, and ``present_frame()`` uploads + flips.
    """
    global _gpu_ctx, _gpu_compat

    if renderer_mode == "gpu":
        from core.gpu import GpuContext, GpuCompatScreen
        # Size mirrors the CPU branch.
        if display_mode == "windowed_fullscreen":
            info = pygame.display.Info()
            size = (info.current_w, info.current_h)
            borderless = True
        else:
            size = (1280, 720)
            borderless = False
        # NOTE: pygame._sdl2.video.Window bypasses the pygame.display
        # module entirely, so we do NOT call pygame.display.set_mode here.
        _gpu_ctx = GpuContext(size=size, title="AIRTS", borderless=borderless)
        _gpu_compat = GpuCompatScreen(_gpu_ctx)
        return _gpu_compat.surface

    # CPU path — unchanged.
    if display_mode == "windowed_fullscreen":
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        surface = pygame.display.set_mode((0, 0), pygame.NOFRAME)
        os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
        return surface
    else:
        os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
        return pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
