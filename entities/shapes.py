from __future__ import annotations
from typing import Sequence
import pygame
from entities.base import Entity
from config.settings import OBSTACLE_OUTLINE


class RectEntity(Entity):
    def __init__(self, x: float = 0, y: float = 0, width: float = 32, height: float = 32):
        super().__init__(x, y)
        self.width = width
        self.height = height

    def get_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.width, self.height)

    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)

    def collision_radius(self) -> float:
        return max(self.width, self.height) / 2.0

    def draw(self, surface: pygame.Surface):
        pygame.draw.rect(surface, self.color, (self.x, self.y, self.width, self.height))
        if self.obstacle:
            pygame.draw.rect(surface, OBSTACLE_OUTLINE, (self.x, self.y, self.width, self.height), 1)


class CircleEntity(Entity):
    def __init__(self, x: float = 0, y: float = 0, radius: float = 16):
        super().__init__(x, y)
        self.radius = radius

    def get_rect(self) -> pygame.Rect:
        r = self.radius
        return pygame.Rect(self.x - r, self.y - r, r * 2, r * 2)

    def center(self) -> tuple[float, float]:
        return (self.x, self.y)

    def collision_radius(self) -> float:
        return self.radius

    def draw(self, surface: pygame.Surface):
        pygame.draw.circle(surface, self.color, (self.x, self.y), self.radius)
        if self.obstacle:
            pygame.draw.circle(surface, OBSTACLE_OUTLINE, (self.x, self.y), self.radius, 1)


class PolygonEntity(Entity):
    """Entity drawn as an arbitrary closed polygon. Points are relative to (x, y)."""

    def __init__(self, x: float = 0, y: float = 0, points: Sequence[tuple[float, float]] | None = None):
        super().__init__(x, y)
        self.points = list(points) if points else [(-16, -16), (16, -16), (0, 16)]

    def get_rect(self) -> pygame.Rect:
        translated = [(self.x + px, self.y + py) for px, py in self.points]
        xs = [p[0] for p in translated]
        ys = [p[1] for p in translated]
        left, top = min(xs), min(ys)
        return pygame.Rect(left, top, max(xs) - left, max(ys) - top)

    def draw(self, surface: pygame.Surface):
        translated = [(self.x + px, self.y + py) for px, py in self.points]
        pygame.draw.polygon(surface, self.color, translated)


class SpriteEntity(Entity):
    def __init__(self, x: float = 0, y: float = 0, image_path: str = ""):
        super().__init__(x, y)
        self._source_image: pygame.Surface | None = None
        self.image: pygame.Surface | None = None
        self.scale = 1.0
        self.angle = 0.0
        if image_path:
            self.load(image_path)

    def load(self, path: str):
        self._source_image = pygame.image.load(path).convert_alpha()
        self._rebuild()

    def _rebuild(self):
        if self._source_image is None:
            return
        img = self._source_image
        if self.scale != 1.0:
            w = int(img.get_width() * self.scale)
            h = int(img.get_height() * self.scale)
            img = pygame.transform.smoothscale(img, (w, h))
        if self.angle != 0.0:
            img = pygame.transform.rotate(img, self.angle)
        self.image = img

    def get_rect(self) -> pygame.Rect:
        if self.image is not None:
            return self.image.get_rect(center=(self.x, self.y))
        return pygame.Rect(self.x, self.y, 0, 0)

    def draw(self, surface: pygame.Surface):
        if self.image is None:
            return
        rect = self.image.get_rect(center=(self.x, self.y))
        surface.blit(self.image, rect)
