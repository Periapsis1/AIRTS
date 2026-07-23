"""Base screen class and screen result type."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import pygame


@dataclass
class ScreenResult:
    """Returned by a screen's run() to tell the app what to do next."""
    next_screen: str  # "main_menu", "game", "guides", etc. or "quit"
    data: dict[str, Any] = field(default_factory=dict)


class BaseScreen(ABC):
    """Abstract base for all menu screens.

    Each screen owns its own event loop via ``run()``.
    """

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        self.screen = screen
        self.clock = clock
        self.width = screen.get_width()
        self.height = screen.get_height()

    @abstractmethod
    def run(self) -> ScreenResult:
        """Run the screen's event loop and return what screen to show next."""
        ...

    @staticmethod
    def present() -> None:
        """Present the current frame.

        In CPU renderer mode this is ``pygame.display.flip()``. In GPU
        mode it uploads the scratch surface to the streaming texture and
        calls ``Renderer.present()``. Screens call ``self.present()``
        instead of ``pygame.display.flip()`` so both paths work.
        """
        from config import display as _display
        _display.present_frame()
