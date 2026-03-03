from __future__ import annotations
import math
import pygame
from entities.shapes import CircleEntity
from entities.base import Entity, Damageable
from entities.weapon import Weapon
from config.settings import (
    TEAM1_COLOR, TEAM2_COLOR, TEAM1_SELECTED_COLOR,
    SELECTED_COLOR, HEALTH_BAR_OFFSET, MEDIC_HEAL_COLOR,
    RANGE_COLOR, UNIT_LASER_COLOR_T1, UNIT_LASER_COLOR_T2,
    HEAL_LASER_COLOR,
)
from config.unit_types import UNIT_TYPES
from core.helpers import angle_diff
from systems.abilities import ReactiveArmor, Focus, ability_from_dict

# fire-mode constants
HOLD_FIRE = "hold_fire"
TARGET_FIRE = "target_fire"
FREE_FIRE = "free_fire"

# Command line colors
_MOVE_CMD_COLOR = (0, 140, 40)     # dark green for move commands
_ATTACK_CMD_COLOR = (180, 30, 30)  # dark red for attack commands
_ARROW_SIZE = 6


def _draw_command_line(surface: pygame.Surface, x1: float, y1: float,
                       x2: float, y2: float, color: tuple):
    """Draw a command line from (x1,y1) to (x2,y2) with an arrowhead."""
    pygame.draw.line(surface, color, (x1, y1), (x2, y2), 1)
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 1:
        return
    ux, uy = dx / dist, dy / dist
    px, py = -uy, ux
    s = _ARROW_SIZE
    wing1 = (x2 - ux * s + px * s * 0.5, y2 - uy * s + py * s * 0.5)
    wing2 = (x2 - ux * s - px * s * 0.5, y2 - uy * s - py * s * 0.5)
    pygame.draw.polygon(surface, color, [(x2, y2), wing1, wing2])


class Unit(CircleEntity, Damageable):
    _steer_obstacles: tuple = ()  # set by Game; tuples of (x, y, radius)
    _spatial_grid = None          # set by Game; SpatialGrid for nearby-unit queries

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

        wdata = stats.get("weapon")
        if wdata:
            laser_color = wdata.get("laser_color",
                                    UNIT_LASER_COLOR_T1 if team == 1 else UNIT_LASER_COLOR_T2)
            if wdata.get("hits_only_friendly", False):
                laser_color = HEAL_LASER_COLOR
            self.weapon = Weapon(
                name=wdata["name"],
                damage=wdata["damage"],
                range=wdata["range"],
                cooldown=wdata["cooldown"],
                laser_color=laser_color,
                laser_width=wdata.get("laser_width", 1),
                hits_only_friendly=wdata.get("hits_only_friendly", False),
                sound=wdata.get("sound", "fast_laser"),
                chain_range=wdata.get("chain_range", 0.0),
                chain_delay=wdata.get("chain_delay", 0.0),
            )
        else:
            self.weapon = None

        self.attack_damage: float = self.weapon.damage if self.weapon else 0
        self.attack_range: float = self.weapon.range if self.weapon else 0
        self.attack_cooldown_max: float = self.weapon.cooldown if self.weapon else 0
        self.laser_cooldown: float = 0.0

        self._symbol: tuple | None = stats["symbol"]
        self.is_building: bool = stats.get("is_building", False)

        self.facing_angle: float = 0.0                                    # radians, 0 = right (+x)
        self.fov: float = math.radians(stats.get("fov", 90))             # stored in radians
        self.turn_rate: float = math.radians(stats.get("turn_rate", 180)) # rad/s
        self.line_of_sight: float = float(stats.get("los", 100))         # pixels

        self._bounds: tuple[int, int] = (800, 600)

        # -- command state ---------------------------------------------------
        self.target: tuple[float, float] | None = None
        self._stop_dist: float = 0.0

        self._follow_entity: Entity | None = None
        self._follow_dist: float = 0.0

        self.attack_target: Entity | None = None
        self.fire_mode: str = FREE_FIRE

        self.selectable: bool = False
        self._facing_target: tuple[float, float] | None = None  # set by batch_facing_targets

        # -- abilities ----------------------------------------------------------
        self.abilities: list = []
        if unit_type == "tank":
            self.abilities = [ReactiveArmor()]
        elif unit_type == "sniper":
            self.abilities = [Focus()]

    # -- damage -------------------------------------------------------------

    def take_damage(self, amount: float):
        for ability in self.abilities:
            amount = ability.modify_damage(amount, self)
        super().take_damage(amount)

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

        for ability in self.abilities:
            ability.update(self, dt)

        if self.attack_target is not None and not self.attack_target.alive:
            self.attack_target = None

        if not self.is_building:
            self._update_facing(dt)
            self._update_follow()
            self._update_movement(dt)

    def _update_facing(self, dt: float):
        # Priority: attack_target > batch-computed nearest > movement target > hold
        target_pos = None
        if self.attack_target is not None and self.attack_target.alive:
            target_pos = (self.attack_target.x, self.attack_target.y)
        else:
            # Use pre-computed batch result (set by game.py via batch_facing_targets)
            target_pos = self._facing_target
            # Fall back to movement target
            if target_pos is None and self.target is not None:
                target_pos = self.target

        if target_pos is None:
            return

        desired = math.atan2(target_pos[1] - self.y, target_pos[0] - self.x)
        diff = angle_diff(self.facing_angle, desired)
        max_turn = self.turn_rate * dt
        if abs(diff) <= max_turn:
            self.facing_angle = desired
        else:
            self.facing_angle += max_turn if diff > 0 else -max_turn
        # Normalize to [0, tau)
        self.facing_angle %= math.tau

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
        nx = dx / dist
        ny = dy / dist

        # Steer around obstacles in our path
        sx, sy, steered = self._steer(nx, ny, min(dist, 100.0))

        if step >= dist and not steered:
            self.x = self.target[0]
            self.y = self.target[1]
            self.target = None
        else:
            self.x += sx * step
            self.y += sy * step

    def _steer(self, dir_x: float, dir_y: float, lookahead: float):
        """Adjust movement direction to steer around obstacles ahead.

        Returns (steer_x, steer_y, was_steered).
        """
        avoid_x = 0.0
        avoid_y = 0.0

        for ox, oy, orad in self._steer_obstacles:
            # Vector from unit to obstacle center
            to_x = ox - self.x
            to_y = oy - self.y

            # How far ahead along our movement direction?
            ahead = to_x * dir_x + to_y * dir_y
            if ahead <= 0 or ahead > lookahead + orad:
                continue

            # Signed perpendicular distance (positive = obstacle to right)
            cross = to_x * dir_y - to_y * dir_x
            clearance = orad + self.radius + 4
            if abs(cross) >= clearance:
                continue

            # Stronger steering when obstacle is more directly in our path
            strength = (clearance - abs(cross)) / clearance

            # Steer away from obstacle center (toward the nearer edge)
            if cross >= 0:
                # Obstacle to our right — steer left
                avoid_x -= dir_y * strength
                avoid_y += dir_x * strength
            else:
                # Obstacle to our left — steer right
                avoid_x += dir_y * strength
                avoid_y -= dir_x * strength

        if avoid_x == 0.0 and avoid_y == 0.0:
            return dir_x, dir_y, False

        rx = dir_x + avoid_x
        ry = dir_y + avoid_y
        rl = math.hypot(rx, ry)
        if rl > 0:
            return rx / rl, ry / rl, True
        return dir_x, dir_y, False

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

    def _draw_fov_arc(self, surface: pygame.Surface, color):
        r = int(self.attack_range)
        if r <= 0:
            return
        half_fov = self.fov / 2
        # Full circle (or nearly): fall back to simple circle
        if self.fov >= math.tau - 0.01:
            temp = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp, color, (r, r), r, 1)
            surface.blit(temp, (int(self.x) - r, int(self.y) - r))
            return

        # Build a polygon: center -> arc points -> center
        cx, cy = self.x, self.y
        start = self.facing_angle - half_fov
        steps = max(int(math.degrees(self.fov) / 3), 8)
        points = [(cx, cy)]
        for i in range(steps + 1):
            a = start + self.fov * i / steps
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        points.append((cx, cy))

        temp_size = r * 2 + 4
        temp = pygame.Surface((temp_size, temp_size), pygame.SRCALPHA)
        ox = temp_size // 2 - cx
        oy = temp_size // 2 - cy
        shifted = [(px + ox, py + oy) for px, py in points]
        pygame.draw.lines(temp, color, False, shifted, 1)
        surface.blit(temp, (cx - temp_size // 2, cy - temp_size // 2))

    def draw(self, surface: pygame.Surface):
        pygame.draw.circle(surface, self.color, (self.x, self.y), self.radius)
        self._draw_symbol(surface)

        if self.selected:
            pygame.draw.circle(surface, SELECTED_COLOR, (self.x, self.y), self.radius + 2, 1)

            if self.attack_target is not None and self.attack_target.alive:
                _draw_command_line(surface, self.x, self.y,
                                  self.attack_target.x, self.attack_target.y,
                                  _ATTACK_CMD_COLOR)
            elif self.target is not None:
                _draw_command_line(surface, self.x, self.y,
                                  self.target[0], self.target[1],
                                  _MOVE_CMD_COLOR)

        # Allied units: only show FOV arc when selected; enemies: always
        if not self.selectable or self.selected:
            if self.weapon and self.weapon.hits_only_friendly:
                self._draw_fov_arc(surface, MEDIC_HEAL_COLOR)
            else:
                self._draw_fov_arc(surface, RANGE_COLOR)

        for ability in self.abilities:
            ability.draw(self, surface)

        self.draw_health_bar(surface, self.x, self.y, self.radius + HEALTH_BAR_OFFSET)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "team": self.team,
            "unit_type": self.unit_type,
            "hp": self.hp,
            "laser_cooldown": self.laser_cooldown,
            "facing_angle": self.facing_angle,
            "line_of_sight": self.line_of_sight,
            "is_building": self.is_building,
            "target": list(self.target) if self.target else None,
            "_stop_dist": self._stop_dist,
            "fire_mode": self.fire_mode,
            "selectable": self.selectable,
            "_bounds": list(self._bounds),
            "_follow_entity_id": self._follow_entity.entity_id if self._follow_entity else None,
            "_follow_dist": self._follow_dist,
            "attack_target_id": self.attack_target.entity_id if self.attack_target else None,
            "abilities": [a.to_dict() for a in self.abilities],
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
        u.facing_angle = data.get("facing_angle", 0.0)
        u.line_of_sight = data.get("line_of_sight", u.line_of_sight)
        u.laser_cooldown = data["laser_cooldown"]
        u.target = tuple(data["target"]) if data["target"] else None
        u._stop_dist = data["_stop_dist"]
        u.fire_mode = data["fire_mode"]
        u.selectable = data["selectable"]
        u._bounds = tuple(data["_bounds"])
        u._follow_dist = data["_follow_dist"]
        if "abilities" in data:
            u.abilities = [ability_from_dict(a) for a in data["abilities"]]
            for ab in u.abilities:
                if isinstance(ab, Focus) and ab.timer > 0 and ab._base_speed > 0:
                    t = ab.timer / Focus.DURATION
                    u.speed = ab._base_speed * (Focus.MIN_MULT + (1.0 - Focus.MIN_MULT) * (1.0 - t))
        # cross-references resolved later by Game.load_state()
        u._follow_entity = None
        u.attack_target = None
        return u
