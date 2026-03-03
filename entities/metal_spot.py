from __future__ import annotations
from config.settings import (
    METAL_SPOT_COLOR, METAL_SPOT_RADIUS, METAL_SPOT_CAPTURE_RATE, METAL_SPOT_CAPTURE_RADIUS, METAL_SPOT_CAPTURE_ARC_WIDTH, METAL_SPOT_CAPTURE_ARC_COLOR_T1, METAL_SPOT_CAPTURE_ARC_COLOR_T2, METAL_SPOT_CAPTURE_RANGE_COLOR,
    TEAM1_COLOR, TEAM2_COLOR,
)
from entities.shapes import CircleEntity
from entities.base import Damageable
import pygame
from datetime import datetime
import math

class MetalSpot(CircleEntity, Damageable):
    def __init__(self, x: float = 0, y: float = 0):
        super().__init__(x, y, METAL_SPOT_RADIUS)
        self.color = METAL_SPOT_COLOR
        self.owner: int | None = None
        self.capture_progress: float = 0.0  # -1.0 to 1.0 representing the capture progress for each team

    def update_progress(self, unit_difference: float, dt: float):
        # unit_difference is team 1 units - team 2 units (scouts count as 0.3)
        if self.owner is not None:
            return

        if unit_difference != 0:
            self.capture_progress += unit_difference * METAL_SPOT_CAPTURE_RATE * dt
        elif self.capture_progress != 0:
            # Decay at 1% per second when no one is capturing
            decay = 0.01 * dt
            if self.capture_progress > 0:
                self.capture_progress = max(0.0, self.capture_progress - decay)
            else:
                self.capture_progress = min(0.0, self.capture_progress + decay)
        self.capture_progress = min(1.0, max(-1.0, self.capture_progress))

    def claim(self, team: int):
        self.owner = team
        self.capture_progress = 0.0

    def release(self):
        self.owner = None

    def draw(self, surface: pygame.Surface):
        # draw the range circle on a temporary surface to respect alpha
        r = int(METAL_SPOT_CAPTURE_RADIUS)
        size = r * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(temp, METAL_SPOT_CAPTURE_RANGE_COLOR, (r, r), r)
        surface.blit(temp, (int(self.x) - r, int(self.y) - r))

        # draw the base circle
        if self.owner is None:
            color = self.color
        elif self.owner == 1:
            color = TEAM1_COLOR
        else:
            color = TEAM2_COLOR
        pygame.draw.circle(surface, color, self.center(), self.radius)

        if self.owner is not None:
            return

        # draw the capture progress pie chart
        progress_color = METAL_SPOT_CAPTURE_ARC_COLOR_T1 if self.capture_progress > 0 else METAL_SPOT_CAPTURE_ARC_COLOR_T2
        arc_r = METAL_SPOT_CAPTURE_RADIUS + METAL_SPOT_CAPTURE_ARC_WIDTH
        start_angle = math.pi / 2
        end_angle = start_angle + self.capture_progress * math.tau
        if self.capture_progress > 0:
            a = start_angle
            b = end_angle
        else:
            a = end_angle
            b = start_angle
        rect = pygame.Rect(int(self.x - arc_r), int(self.y - arc_r), int(arc_r * 2), int(arc_r * 2))
        pygame.draw.arc(surface, progress_color, rect, a, b, int(METAL_SPOT_CAPTURE_ARC_WIDTH))

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "owner": self.owner,
            "capture_progress": self.capture_progress,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MetalSpot:
        ms = cls(data["x"], data["y"])
        ms.entity_id = data["entity_id"]
        ms.color = tuple(data["color"])
        ms.selected = data["selected"]
        ms.obstacle = data["obstacle"]
        ms.alive = data["alive"]
        ms.owner = data["owner"]
        ms.capture_progress = data["capture_progress"]
        return ms