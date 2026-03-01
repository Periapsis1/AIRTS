from __future__ import annotations
import math
import pygame
from entities.shapes import CircleEntity
from entities.base import Entity, Damageable
from config.settings import (
    TEAM1_COLOR, TEAM2_COLOR, TEAM1_SELECTED_COLOR,
    SELECTED_COLOR, HEALTH_BAR_OFFSET, MEDIC_HEAL_COLOR,
    RANGE_COLOR,
)
from config.unit_types import UNIT_TYPES

# fire-mode constants
HOLD_FIRE = "hold_fire"
TARGET_FIRE = "target_fire"
FREE_FIRE = "free_fire"


class Unit(CircleEntity, Damageable):

    def __init__(self, x: float = 0, y: float = 0, team: int = 1,
                 unit_type: str = "soldier"):
        stats = UNIT_TYPES[unit_type]
        super().__init__(x, y, stats["radius"])
        self.unit_type = unit_type
        self.team = team
        self.speed: float = stats["speed"]
        self.color = TEAM1_COLOR if team == 1 else TEAM2_COLOR
        self._base_color = self.color

        self.max_hp: float = stats["hp"]
        self.hp: float = float(stats["hp"])
        self.can_attack: bool = stats["can_attack"]
        self.attack_damage: float = stats["damage"]
        self.attack_range: float = stats["range"]
        self.attack_cooldown_max: float = stats["cooldown"]
        self.laser_cooldown: float = 0.0

        self._symbol: tuple | None = stats["symbol"]
        self.heal_rate: float = stats.get("heal_rate", 0)
        self.heal_range: float = stats.get("heal_range", 0)
        self.heal_targets: int = stats.get("heal_targets", 0)

        self._bounds: tuple[int, int] = (800, 600)

        # -- command state ---------------------------------------------------
        self.target: tuple[float, float] | None = None
        self._stop_dist: float = 0.0

        self._follow_entity: Entity | None = None
        self._follow_dist: float = 0.0

        self.attack_target: Entity | None = None
        self.fire_mode: str = FREE_FIRE

        self.selectable: bool = False

    # -- commands -----------------------------------------------------------

    def move(self, x: float, y: float, stop_dist: float = 0.0):
        self.target = (x, y)
        self._stop_dist = stop_dist
        self._follow_entity = None

    def follow(self, target: Entity, distance: float):
        self._follow_entity = target
        self._follow_dist = distance
        self.target = None

    def attack(self, target: Entity):
        self.attack_target = target

    def stop(self):
        self.target = None
        self._follow_entity = None

    # -- selection ----------------------------------------------------------

    def set_selected(self, value: bool):
        if not self.selectable:
            return
        self.selected = value
        self.color = TEAM1_SELECTED_COLOR if value else self._base_color

    # -- update -------------------------------------------------------------

    def update(self, dt: float):
        self.laser_cooldown = max(0.0, self.laser_cooldown - dt)

        if self.attack_target is not None and not self.attack_target.alive:
            self.attack_target = None

        self._update_follow()
        self._update_movement(dt)

    def _update_follow(self):
        ft = self._follow_entity
        if ft is None:
            return
        if not ft.alive:
            self._follow_entity = None
            return
        d = math.hypot(ft.x - self.x, ft.y - self.y)
        if d > self._follow_dist:
            self.target = (ft.x, ft.y)
            self._stop_dist = self._follow_dist
        else:
            self.target = None

    def _update_movement(self, dt: float):
        if self.target is None:
            return

        dx = self.target[0] - self.x
        dy = self.target[1] - self.y
        dist = math.hypot(dx, dy)

        if dist <= self._stop_dist:
            self.target = None
            return

        step = self.speed * dt
        if step >= dist:
            self.x = self.target[0]
            self.y = self.target[1]
            self.target = None
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step

    # -- drawing ------------------------------------------------------------

    def _draw_symbol(self, surface: pygame.Surface):
        if self._symbol is None:
            return
        scale = self.radius / 16.0
        translated = [
            (self.x + px * scale, self.y + py * scale) for px, py in self._symbol
        ]
        pygame.draw.polygon(surface, (0, 0, 0), translated)
        pygame.draw.polygon(surface, self._base_color, translated, 1)

    def draw(self, surface: pygame.Surface):
        if self.target is not None:
            pygame.draw.line(surface, self._base_color, (self.x, self.y), self.target, 1)
            tx, ty = self.target
            pygame.draw.circle(surface, self._base_color, (int(tx), int(ty)), 3, 1)

        pygame.draw.circle(surface, self.color, (self.x, self.y), self.radius)
        self._draw_symbol(surface)
        if self.selected:
            pygame.draw.circle(surface, SELECTED_COLOR, (self.x, self.y), self.radius + 2, 1)

        temp = pygame.Surface((int(self.attack_range * 2), int(self.attack_range * 2)), pygame.SRCALPHA)
        if self.unit_type == "medic":
            pygame.draw.circle(temp, MEDIC_HEAL_COLOR, (self.heal_range, self.heal_range),
                               int(self.heal_range), 1)

        pygame.draw.circle(temp, RANGE_COLOR, (self.attack_range, self.attack_range), int(self.attack_range), 1)
        surface.blit(temp, (int(self.x) - self.attack_range, int(self.y) - self.attack_range))
        self.draw_health_bar(surface, self.x, self.y, self.radius + HEALTH_BAR_OFFSET)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "team": self.team,
            "unit_type": self.unit_type,
            "hp": self.hp,
            "laser_cooldown": self.laser_cooldown,
            "target": list(self.target) if self.target else None,
            "_stop_dist": self._stop_dist,
            "fire_mode": self.fire_mode,
            "selectable": self.selectable,
            "_bounds": list(self._bounds),
            "_follow_entity_id": self._follow_entity.entity_id if self._follow_entity else None,
            "_follow_dist": self._follow_dist,
            "attack_target_id": self.attack_target.entity_id if self.attack_target else None,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Unit:
        u = cls(data["x"], data["y"], data["team"], data["unit_type"])
        u.entity_id = data["entity_id"]
        u.color = tuple(data["color"])
        u.selected = data["selected"]
        u.obstacle = data["obstacle"]
        u.alive = data["alive"]
        u.hp = data["hp"]
        u.laser_cooldown = data["laser_cooldown"]
        u.target = tuple(data["target"]) if data["target"] else None
        u._stop_dist = data["_stop_dist"]
        u.fire_mode = data["fire_mode"]
        u.selectable = data["selectable"]
        u._bounds = tuple(data["_bounds"])
        u._follow_dist = data["_follow_dist"]
        # cross-references resolved later by Game.load_state()
        u._follow_entity = None
        u.attack_target = None
        return u
