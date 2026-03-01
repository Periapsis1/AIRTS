from __future__ import annotations
from config.settings import METAL_EXTRACTOR_RADIUS, TEAM1_COLOR, TEAM2_COLOR, METAL_EXTRACTOR_HP, HEALTH_BAR_OFFSET
from entities.shapes import CircleEntity
from entities.base import Damageable
from entities.metal_spot import MetalSpot
import pygame
import math
import numpy as np

class MetalExtractor(CircleEntity, Damageable):
    def __init__(self, *, metal_spot: MetalSpot, team: int = 1):
        super().__init__(metal_spot.x, metal_spot.y, METAL_EXTRACTOR_RADIUS)
        self.team = team
        self.metal_spot = metal_spot
        self.color = TEAM1_COLOR if team == 1 else TEAM2_COLOR
        self._base_color = self.color
        self.rotation = 0.0
        self.rotation_speed = 10.0
        self.hp = METAL_EXTRACTOR_HP
        self.max_hp = METAL_EXTRACTOR_HP

    def update(self, dt: float):
        self.rotation = (self.rotation + dt * self.rotation_speed) % (math.tau)

    def on_destroy(self):
        self.metal_spot.release()
        self.metal_spot = None


    def draw(self, surface: pygame.Surface):
        # draw a rotating equilateral triangle centered at (x, y) color is black bc metal spot is already the team color
        r = self.radius
        s = r * math.sqrt(3) / 2
        static_points = [
            complex(0, r),
            complex(-s, -r / 2),
            complex(s, -r / 2),
        ]
        rotated_points = [p * complex(math.cos(self.rotation), math.sin(self.rotation)) for p in static_points]
        points = [(p.real + self.x, p.imag + self.y) for p in rotated_points]

        pygame.draw.polygon(surface, (0, 0, 0), points, 1)

        self.draw_health_bar(surface, self.x, self.y, self.radius + HEALTH_BAR_OFFSET)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "team": self.team,
            "rotation": self.rotation,
            "rotation_speed": self.rotation_speed,
            "hp": self.hp,
            "metal_spot_id": self.metal_spot.entity_id if self.metal_spot else None,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MetalExtractor:
        # Bypass __init__ since it requires a MetalSpot argument
        me = object.__new__(cls)
        # Entity base fields
        me.entity_id = data["entity_id"]
        me.x = data["x"]
        me.y = data["y"]
        me.color = tuple(data["color"])
        me.selected = data["selected"]
        me.obstacle = data["obstacle"]
        me.alive = data["alive"]
        # CircleEntity fields
        me.radius = data["radius"]
        # MetalExtractor fields
        me.team = data["team"]
        me.rotation = data["rotation"]
        me.rotation_speed = data["rotation_speed"]
        me.hp = data["hp"]
        me.max_hp = METAL_EXTRACTOR_HP
        me._base_color = tuple(data["color"])
        # cross-reference resolved later by Game.load_state()
        me.metal_spot = None
        return me