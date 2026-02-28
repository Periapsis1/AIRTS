from __future__ import annotations
import math
import random
import pygame
from entities.shapes import PolygonEntity
from entities.base import Damageable
from entities.unit import Unit
from entities.metal_extractor import MetalExtractor
from core.helpers import hexagon_points
from config.settings import (
    TEAM1_COLOR, TEAM2_COLOR, TEAM1_SELECTED_COLOR, SELECTED_COLOR, DEFAULT_COLOR,
    CC_HP, CC_SPAWN_INTERVAL, CC_RADIUS, HEALTH_BAR_OFFSET,
    CC_HEAL_RADIUS, CC_HEAL_COLOR_T1, CC_HEAL_COLOR_T2,
    CC_HEAL_RING_T1, CC_HEAL_RING_T2,
    METAL_EXTRACTOR_BOOST_FACTOR,
)


class CommandCenter(PolygonEntity, Damageable):
    def __init__(self, x: float = 0, y: float = 0, team: int = 1):
        hex_pts = hexagon_points(CC_RADIUS)
        super().__init__(x, y, hex_pts)
        self.team = team
        self.color = TEAM1_COLOR if team == 1 else TEAM2_COLOR
        self._base_color = self.color

        self.max_hp: float = CC_HP
        self.hp: float = float(CC_HP)
        self.laser_cooldown: float = 0.0

        self._spawn_timer: float = 0.0
        self._bounds: tuple[int, int] = (800, 600)
        self.rally_point: tuple[float, float] | None = None
        self.spawn_type: str = "soldier"
        self.metal_extractors: list[MetalExtractor] = []

        self.selectable: bool = False

    def set_selected(self, value: bool):
        if not self.selectable:
            return
        self.selected = value
        self.color = TEAM1_SELECTED_COLOR if value else self._base_color

    def collision_radius(self) -> float:
        return CC_RADIUS

    def center(self) -> tuple[float, float]:
        return (self.x, self.y)

    def get_rect(self) -> pygame.Rect:
        r = CC_RADIUS
        return pygame.Rect(self.x - r, self.y - r, r * 2, r * 2)

    def update(self, dt: float):
        self.laser_cooldown = max(0.0, self.laser_cooldown - dt)
        self._spawn_timer += dt * (METAL_EXTRACTOR_BOOST_FACTOR ** len(self.metal_extractors))

    def spawn_ready(self) -> bool:
        return self._spawn_timer >= CC_SPAWN_INTERVAL

    def reset_spawn(self):
        self._spawn_timer = 0.0

    def spawn_unit(self) -> Unit:
        angle = random.uniform(0, math.tau)
        dist = CC_RADIUS + 15
        ux = self.x + math.cos(angle) * dist
        uy = self.y + math.sin(angle) * dist
        u = Unit(ux, uy, team=self.team, unit_type=self.spawn_type)
        u._bounds = self._bounds
        if self.rally_point is not None:
            u.move(*self.rally_point)
        return u

    def draw(self, surface: pygame.Surface):
        translated = [(self.x + px, self.y + py) for px, py in self.points]
        pygame.draw.polygon(surface, self.color, translated)
        outline = TEAM1_SELECTED_COLOR if self.team == 1 else (255, 140, 140)
        pygame.draw.polygon(surface, outline, translated, 2)

        if self.selected:
            pygame.draw.polygon(surface, SELECTED_COLOR, translated, 2)

        heal_surf = pygame.Surface((int(CC_HEAL_RADIUS * 2), int(CC_HEAL_RADIUS * 2)), pygame.SRCALPHA)
        fill_c = CC_HEAL_COLOR_T1 if self.team == 1 else CC_HEAL_COLOR_T2
        ring_c = CC_HEAL_RING_T1 if self.team == 1 else CC_HEAL_RING_T2
        pygame.draw.circle(heal_surf, fill_c, (int(CC_HEAL_RADIUS), int(CC_HEAL_RADIUS)), int(CC_HEAL_RADIUS))
        pygame.draw.circle(heal_surf, ring_c, (int(CC_HEAL_RADIUS), int(CC_HEAL_RADIUS)), int(CC_HEAL_RADIUS), 1)
        surface.blit(heal_surf, (self.x - CC_HEAL_RADIUS, self.y - CC_HEAL_RADIUS))

        progress = min(self._spawn_timer / CC_SPAWN_INTERVAL, 1.0)
        if progress < 1.0:
            arc_r = CC_RADIUS + 5
            start_angle = math.pi / 2
            end_angle = start_angle + progress * math.tau
            rect = pygame.Rect(self.x - arc_r, self.y - arc_r, arc_r * 2, arc_r * 2)
            pygame.draw.arc(surface, SELECTED_COLOR, rect, start_angle, end_angle, 2)
        else:
            arc_r = CC_RADIUS + 5
            pygame.draw.circle(surface, SELECTED_COLOR, (int(self.x), int(self.y)), int(arc_r), 2)

        self.draw_health_bar(surface, self.x, self.y, CC_RADIUS + HEALTH_BAR_OFFSET, bar_w=40)

        if self.rally_point is not None:
            rx, ry = self.rally_point
            pygame.draw.line(surface, self._base_color, (self.x, self.y), (rx, ry), 1)
            pygame.draw.line(surface, DEFAULT_COLOR, (rx, ry), (rx, ry - 14), 1)
            flag_pts = [(rx, ry - 14), (rx + 8, ry - 10), (rx, ry - 6)]
            pygame.draw.polygon(surface, self._base_color, flag_pts)
            pygame.draw.circle(surface, self._base_color, (int(rx), int(ry)), 3, 1)
