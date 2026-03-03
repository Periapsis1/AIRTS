"""
Map generators.

Each generator populates a list of entities for a given map size.
Swap generators to create different map layouts.
"""
from __future__ import annotations
import random
import math
from entities.base import Entity
from entities.shapes import RectEntity, CircleEntity
from entities.command_center import CommandCenter
from entities.metal_spot import MetalSpot
from config.settings import OBSTACLE_COLOR, CC_SPAWN_INTERVAL, METAL_SPOT_RADIUS, CC_OBSTACLE_EXCLUSION


class BaseMapGenerator:
    """Interface for map generators."""

    def generate(self, width: int, height: int) -> list[Entity]:
        raise NotImplementedError


class DefaultMapGenerator(BaseMapGenerator):
    """Random obstacles in the center band, one command center per side."""

    def __init__(self, obstacle_count: tuple[int, int] = (4, 8)):
        self._obs_range = obstacle_count

    def generate(self, width: int, height: int) -> list[Entity]:
        entities: list[Entity] = []
        self._place_command_centers(entities, width, height)
        self._place_metal_spots(entities, width, height)
        self._place_obstacles(entities, width, height)
        return entities

    def _random_point_in_rectangle(self, x1: int, y1: int, x2: int, y2: int) -> tuple[float, float]:
        return random.uniform(x1, x2), random.uniform(y1, y2)

    def _find_obstacle_position(self,
        x1: int, y1: int, x2: int, y2: int,
        obs_width: int, obs_height: int,
        obs_type: str,
        entities: list[Entity]
    ) -> tuple[float, float]:
        command_centers = [e for e in entities if isinstance(e, CommandCenter)]
        while True:
            x, y = self._random_point_in_rectangle(x1, y1, x2, y2)

            # Enforce exclusion zone around command centers
            if obs_type == "rect":
                cx, cy = x + obs_width / 2, y + obs_height / 2
            else:
                cx, cy = x, y
            if any(math.hypot(cx - cc.x, cy - cc.y) < CC_OBSTACLE_EXCLUSION for cc in command_centers):
                continue

            if obs_type == "rect":
                if not any(e.get_rect().colliderect(x, y, obs_width, obs_height) for e in entities):
                    return x, y
            elif obs_type == "circle":
                if not any(math.hypot(x - e.x, y - e.y) < e.collision_radius() for e in entities):
                    return x, y
            else:
                raise ValueError(f"Invalid obstacle type: {obs_type}")


    def _place_obstacles(self, entities: list[Entity], width: int, height: int):
        for _ in range(random.randint(*self._obs_range)):
            if random.random() < 0.5:
                w = random.uniform(30, 80)
                h = random.uniform(30, 80)
                x, y = self._find_obstacle_position(0, 0, width, height, w, h, "rect", entities)
                obs = RectEntity(
                    x=x,
                    y=y,
                    width=w, height=h,
                )
            else:
                r = random.uniform(15, 40)
                x, y = self._find_obstacle_position(0, 0, width, height, r, r, "circle", entities)
                obs = CircleEntity(
                    x=x,
                    y=y,
                    radius=r,
                )
            obs.obstacle = True
            obs.color = OBSTACLE_COLOR
            entities.append(obs)

    def _place_command_centers(self, entities: list[Entity], width: int, height: int):
        cc1 = CommandCenter(80, height // 2, team=1)
        cc1._bounds = (width, height)
        cc1._spawn_timer = CC_SPAWN_INTERVAL
        entities.append(cc1)

        cc2 = CommandCenter(width - 80, height // 2, team=2)
        cc2._bounds = (width, height)
        cc2._spawn_timer = CC_SPAWN_INTERVAL
        entities.append(cc2)

    def _place_metal_spots(self, entities: list[Entity], width: int, height: int):
        for _ in range(random.randint(2, 4)):
            x = random.uniform(200 + METAL_SPOT_RADIUS, width // 2 - METAL_SPOT_RADIUS)
            y = random.uniform(60 + METAL_SPOT_RADIUS, height // 2 - METAL_SPOT_RADIUS)
            metal_spot = MetalSpot(x, y)
            metal_spot_2 = MetalSpot(width - x, height - y)
            entities.append(metal_spot)
            entities.append(metal_spot_2)
