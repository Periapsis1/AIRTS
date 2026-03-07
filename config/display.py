"""Display mode settings — windowed fullscreen (borderless) or 1280x720 windowed."""
from __future__ import annotations
import json
import os
import pygame

_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "display_settings.json")

display_mode: str = "windowed_fullscreen"


def load_settings() -> None:
    """Load display settings from disk."""
    global display_mode
    try:
        with open(_SETTINGS_PATH, "r") as f:
            data = json.load(f)
        mode = data.get("display_mode", "windowed_fullscreen")
        if mode in ("windowed_fullscreen", "windowed"):
            display_mode = mode
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def save_settings() -> None:
    """Persist display settings to disk."""
    try:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump({"display_mode": display_mode}, f, indent=2)
    except OSError:
        pass


def set_mode(mode: str) -> None:
    """Update display mode and save."""
    global display_mode
    if mode in ("windowed_fullscreen", "windowed"):
        display_mode = mode
        save_settings()


def create_display() -> pygame.Surface:
    """Create and return the pygame display surface for the current mode."""
    if display_mode == "windowed_fullscreen":
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        surface = pygame.display.set_mode((0, 0), pygame.NOFRAME)
        # Reset so windowed mode gets default centering
        os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
        return surface
    else:
        os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
        return pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
