from __future__ import annotations
import pygame
from config.settings import LASER_FLASH_DURATION


class LaserFlash:
    __slots__ = ("x1", "y1", "x2", "y2", "color", "ttl", "width")

    def __init__(self, x1: float, y1: float, x2: float, y2: float,
                 color: tuple, width: int = 1):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.color = color
        self.ttl = LASER_FLASH_DURATION
        self.width = width

    def update(self, dt: float) -> bool:
        self.ttl -= dt
        return self.ttl > 0

    def draw(self, surface: pygame.Surface):
        alpha = max(0, min(255, int(255 * (self.ttl / LASER_FLASH_DURATION))))
        c = (*self.color[:3], alpha)
        temp = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pygame.draw.line(temp, c, (self.x1, self.y1), (self.x2, self.y2), self.width)
        surface.blit(temp, (0, 0))
