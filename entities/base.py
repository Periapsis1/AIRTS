from __future__ import annotations
import pygame
from config.settings import (
    DEFAULT_COLOR, SELECTED_COLOR,
    HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT, HEALTH_BAR_BG, HEALTH_BAR_FG, HEALTH_BAR_LOW,
)


class Entity:
    def __init__(self, x: float = 0, y: float = 0):
        self.x = x
        self.y = y
        self.color = DEFAULT_COLOR
        self.selected = False
        self.obstacle = False
        self.alive = True

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface):
        pass

    def get_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, 0, 0)

    def collision_radius(self) -> float:
        r = self.get_rect()
        return max(r.width, r.height) / 2.0

    def center(self) -> tuple[float, float]:
        r = self.get_rect()
        return (r.centerx, r.centery)

    def set_selected(self, value: bool):
        self.selected = value
        self.color = SELECTED_COLOR if value else DEFAULT_COLOR


class Damageable:
    """Mixin for entities that have health."""
    hp: float
    max_hp: float
    alive: bool

    def take_damage(self, amount: float):
        self.hp = max(0.0, self.hp - amount)
        if self.hp <= 0:
            self.alive = False

    def draw_health_bar(
        self, surface: pygame.Surface,
        cx: float, cy: float, offset_y: float,
        bar_w: float = HEALTH_BAR_WIDTH,
    ):
        if self.hp >= self.max_hp:
            return
        ratio = self.hp / self.max_hp
        bx = cx - bar_w / 2
        by = cy - offset_y
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, HEALTH_BAR_HEIGHT))
        fg = HEALTH_BAR_FG if ratio > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(surface, fg, (bx, by, bar_w * ratio, HEALTH_BAR_HEIGHT))
