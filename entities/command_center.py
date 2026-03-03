from __future__ import annotations
import math
import random
import pygame
from entities.unit import Unit
from entities.weapon import Weapon
from core.helpers import hexagon_points
from config.settings import (
    TEAM1_COLOR, TEAM2_COLOR, TEAM1_SELECTED_COLOR, SELECTED_COLOR, DEFAULT_COLOR,
    CC_HP, CC_SPAWN_INTERVAL, CC_RADIUS, HEALTH_BAR_OFFSET,
    CC_HEAL_RADIUS, CC_HEAL_COLOR_T1, CC_HEAL_COLOR_T2,
    CC_HEAL_RING_T1, CC_HEAL_RING_T2,
    CC_LASER_DAMAGE, CC_LASER_RANGE, CC_LASER_COOLDOWN,
    CC_LASER_COLOR_T1, CC_LASER_COLOR_T2,
    RANGE_COLOR,
)


class CommandCenter(Unit):
    def __init__(self, x: float = 0, y: float = 0, team: int = 1):
        super().__init__(x, y, team, unit_type="command_center")

        # CC-specific weapon (team-dependent laser color, not from config)
        self.weapon = Weapon(
            name="Laser",
            damage=CC_LASER_DAMAGE,
            range=CC_LASER_RANGE,
            cooldown=CC_LASER_COOLDOWN,
            laser_color=CC_LASER_COLOR_T1 if team == 1 else CC_LASER_COLOR_T2,
            laser_width=2,
        )
        self.attack_damage = self.weapon.damage
        self.attack_range = self.weapon.range
        self.attack_cooldown_max = self.weapon.cooldown

        # Hexagon points for drawing (visual only; collision uses radius)
        self.points = hexagon_points(CC_RADIUS)

        # CC-specific state
        self._spawn_timer: float = 0.0
        self._bounds: tuple[int, int] = (800, 600)
        self.rally_point: tuple[float, float] | None = None
        self.spawn_type: str = "soldier"
        self.metal_extractors: list = []

    def update(self, dt: float):
        super().update(dt)  # laser cooldown, no movement (is_building)
        self.metal_extractors = [me for me in self.metal_extractors if me.alive]
        bonus = sum(me.get_spawn_bonus() for me in self.metal_extractors)
        self._spawn_timer += dt * (1.0 + bonus)

    def get_total_bonus_percent(self) -> int:
        """Return total spawn bonus as an integer percentage (e.g. 32 for +32%)."""
        bonus = sum(me.get_spawn_bonus() for me in self.metal_extractors)
        return round(bonus * 100)

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

    def draw_scaled(self, surface: pygame.Surface, scale: float):
        """Draw the CC hexagon at a given scale factor (0..1). No spawn arc or rally flag."""
        scaled_pts = [(self.x + px * scale, self.y + py * scale) for px, py in self.points]
        pygame.draw.polygon(surface, self.color, scaled_pts)
        outline = TEAM1_SELECTED_COLOR if self.team == 1 else (255, 140, 140)
        pygame.draw.polygon(surface, outline, scaled_pts, 2)

        # Health bar only if visible
        if scale > 0.1:
            self.draw_health_bar(surface, self.x, self.y, (CC_RADIUS * scale) + HEALTH_BAR_OFFSET, bar_w=int(40 * scale))

    def draw(self, surface: pygame.Surface):
        translated = [(self.x + px, self.y + py) for px, py in self.points]
        pygame.draw.polygon(surface, self.color, translated)
        outline = TEAM1_SELECTED_COLOR if self.team == 1 else (255, 140, 140)
        pygame.draw.polygon(surface, outline, translated, 2)

        if self.selected:
            pygame.draw.polygon(surface, SELECTED_COLOR, translated, 2)

        # Allied CC: only show heal radius and FOV when selected; enemies: always
        if not self.selectable or self.selected:
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

        # FOV/range arc (inherited from Unit) — allied: selected only
        if not self.selectable or self.selected:
            self._draw_fov_arc(surface, RANGE_COLOR)

        self.draw_health_bar(surface, self.x, self.y, CC_RADIUS + HEALTH_BAR_OFFSET, bar_w=40)

        if self.rally_point is not None:
            rx, ry = self.rally_point
            pygame.draw.line(surface, self._base_color, (self.x, self.y), (rx, ry), 1)
            pygame.draw.line(surface, DEFAULT_COLOR, (rx, ry), (rx, ry - 14), 1)
            flag_pts = [(rx, ry - 14), (rx + 8, ry - 10), (rx, ry - 6)]
            pygame.draw.polygon(surface, self._base_color, flag_pts)
            pygame.draw.circle(surface, self._base_color, (int(rx), int(ry)), 3, 1)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "_spawn_timer": self._spawn_timer,
            "spawn_type": self.spawn_type,
            "rally_point": list(self.rally_point) if self.rally_point else None,
            "metal_extractor_ids": [me.entity_id for me in self.metal_extractors if me.alive],
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CommandCenter:
        cc = cls(data["x"], data["y"], data["team"])
        cc.entity_id = data["entity_id"]
        cc.color = tuple(data["color"])
        cc.selected = data["selected"]
        cc.obstacle = data["obstacle"]
        cc.alive = data["alive"]
        cc.hp = data["hp"]
        cc.laser_cooldown = data["laser_cooldown"]
        cc.facing_angle = data.get("facing_angle", 0.0)
        cc.line_of_sight = data.get("line_of_sight", cc.line_of_sight)
        cc.fire_mode = data.get("fire_mode", cc.fire_mode)
        cc.selectable = data.get("selectable", False)
        cc._bounds = tuple(data["_bounds"])
        cc._spawn_timer = data["_spawn_timer"]
        cc.spawn_type = data["spawn_type"]
        cc.rally_point = tuple(data["rally_point"]) if data.get("rally_point") else None
        cc.target = tuple(data["target"]) if data.get("target") else None
        cc._stop_dist = data.get("_stop_dist", 0.0)
        cc._follow_dist = data.get("_follow_dist", 0.0)
        cc._follow_entity = None
        cc.attack_target = None
        # cross-references resolved later by Game.load_state()
        cc.metal_extractors = []
        return cc
