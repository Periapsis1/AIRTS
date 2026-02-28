from __future__ import annotations
import math
import random
import pygame
import sys
from typing import Sequence


SELECTED_COLOR = (0, 255, 100)
DEFAULT_COLOR = (255, 255, 255)
SELECTION_RECT_COLOR = (0, 200, 255)
SELECTION_FILL_COLOR = (0, 200, 255, 40)

TEAM1_COLOR = (80, 140, 255)
TEAM1_SELECTED_COLOR = (150, 220, 255)
TEAM2_COLOR = (255, 80, 80)
PATH_COLOR_TEAM1 = (80, 140, 255, 100)
PATH_DOT_COLOR = (255, 255, 255, 160)

OBSTACLE_COLOR = (120, 120, 120)
OBSTACLE_OUTLINE = (160, 160, 160)
UNIT_PUSH_FORCE = 200.0
OBSTACLE_PUSH_FORCE = 300.0
GOAL_ARRIVAL_MARGIN = 10.0

COMMAND_PATH_COLOR = (255, 200, 60)
COMMAND_DOT_COLOR = (255, 255, 100)
PATH_SAMPLE_MIN_DIST = 4.0

UNIT_HP = 100
UNIT_LASER_RANGE = 100.0
UNIT_LASER_DAMAGE = 10
UNIT_LASER_COOLDOWN = 2.0
UNIT_LASER_COLOR_T1 = (120, 180, 255)
UNIT_LASER_COLOR_T2 = (255, 120, 120)

CC_HP = 1000
CC_SPAWN_INTERVAL = 5.0
CC_RADIUS = 30.0
CC_LASER_RANGE = 150.0
CC_LASER_DAMAGE = 20
CC_LASER_COOLDOWN = 1.0
CC_LASER_COLOR_T1 = (180, 220, 255)
CC_LASER_COLOR_T2 = (255, 180, 180)

CC_HEAL_RADIUS = 80.0
CC_HEAL_RATE = 5
CC_HEAL_COLOR_T1 = (60, 180, 100, 30)
CC_HEAL_COLOR_T2 = (180, 60, 60, 30)
CC_HEAL_RING_T1 = (60, 180, 100, 80)
CC_HEAL_RING_T2 = (180, 60, 60, 80)

HEALTH_BAR_WIDTH = 24
HEALTH_BAR_HEIGHT = 3
HEALTH_BAR_OFFSET = 4
HEALTH_BAR_BG = (60, 0, 0)
HEALTH_BAR_FG = (0, 220, 0)
HEALTH_BAR_LOW = (220, 0, 0)

LASER_FLASH_DURATION = 0.15

# shapes for different units. Drawn over the circle, border same as unit's, filled with background color. Assumes center of unit is (0, 0) and radius is 16. Last point connects to first. Points run counterclockwise (visually in terms of pygame coordinates)
MEDIC_SYMBOL = ((-4, -12), (4, -12), (4, -4), (12, -4), (12, 4), (4, 4), (4, 12), (-4, 12), (-4, 4), (-12, 4), (-12, -4), (-4, -4))
TANK_SYMBOL = ((-4, -12), (4, -12), (12, -4), (12, 4), (4, 12), (-4, 12), (-12, 4), (-12, -4))
SNIPER_SYMBOL = ((-4, -12), (0, -4), (4, -12), (12, -4), (4, 0), (12, 4), (4, 12), (0, 4), (-4, 12), (-12, 4), (-4, 0), (-12, -4))

UNIT_TYPES = {
    "soldier": {
        "hp": 100, "speed": 80, "radius": 10,
        "damage": 10, "range": 100, "cooldown": 2.0,
        "symbol": None, "can_attack": True,
    },
    "medic": {
        "hp": 100, "speed": 80, "radius": 10,
        "damage": 0, "range": 0, "cooldown": 0,
        "symbol": MEDIC_SYMBOL, "can_attack": False,
        "heal_rate": 10, "heal_range": 80, "heal_targets": 5,
    },
    "tank": {
        "hp": 500, "speed": 40, "radius": 14,
        "damage": 10, "range": 100, "cooldown": 2.0,
        "symbol": TANK_SYMBOL, "can_attack": True,
    },
    "sniper": {
        "hp": 50, "speed": 80, "radius": 10,
        "damage": 30, "range": 300, "cooldown": 6.0,
        "symbol": SNIPER_SYMBOL, "can_attack": True,
    },
}

MEDIC_HEAL_COLOR = (100, 255, 150)

GUI_BG = (30, 30, 40)
GUI_BORDER = (80, 80, 100)
GUI_BTN_SIZE = 50
GUI_BTN_GAP = 8
GUI_BTN_SELECTED = (60, 200, 120)
GUI_BTN_HOVER = (60, 60, 80)
GUI_BTN_NORMAL = (45, 45, 55)
GUI_TEXT_COLOR = (200, 200, 200)
GUI_PANEL_HEIGHT = 70



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hexagon_points(radius: float) -> list[tuple[float, float]]:
    return [
        (radius * math.cos(math.radians(60 * i - 30)),
         radius * math.sin(math.radians(60 * i - 30)))
        for i in range(6)
    ]


def _line_intersects_circle(x1: float, y1: float, x2: float, y2: float,
                            cx: float, cy: float, r: float) -> bool:
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - cx, y1 - cy
    a = dx * dx + dy * dy
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c
    if disc < 0 or a < 1e-12:
        return False
    disc_sq = math.sqrt(disc)
    t1 = (-b - disc_sq) / (2 * a)
    t2 = (-b + disc_sq) / (2 * a)
    return (0 < t1 < 1) or (0 < t2 < 1)


def _line_intersects_rect(x1: float, y1: float, x2: float, y2: float,
                          rx: float, ry: float, rw: float, rh: float) -> bool:
    def _clip(denom: float, numer: float, te: float, tl: float) -> tuple[bool, float, float]:
        if abs(denom) < 1e-12:
            return numer <= 0, te, tl
        t = numer / denom
        if denom < 0:
            te = max(te, t)
        else:
            tl = min(tl, t)
        return te <= tl, te, tl

    dx, dy = x2 - x1, y2 - y1
    te, tl = 0.0, 1.0
    ok, te, tl = _clip(-dx, x1 - rx, te, tl)
    if not ok:
        return False
    ok, te, tl = _clip(dx, rx + rw - x1, te, tl)
    if not ok:
        return False
    ok, te, tl = _clip(-dy, y1 - ry, te, tl)
    if not ok:
        return False
    ok, te, tl = _clip(dy, ry + rh - y1, te, tl)
    if not ok:
        return False
    return te < tl and tl > 0 and te < 1


# ---------------------------------------------------------------------------
# Entity base
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Shape entities
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Damageable mixin
# ---------------------------------------------------------------------------

class Damageable:
    hp: float
    max_hp: float
    alive: bool

    def take_damage(self, amount: float):
        self.hp = max(0.0, self.hp - amount)
        if self.hp <= 0:
            self.alive = False

    def draw_health_bar(self, surface: pygame.Surface, cx: float, cy: float, offset_y: float, bar_w: float = HEALTH_BAR_WIDTH):
        if self.hp >= self.max_hp:
            return
        ratio = self.hp / self.max_hp
        bx = cx - bar_w / 2
        by = cy - offset_y
        pygame.draw.rect(surface, HEALTH_BAR_BG, (bx, by, bar_w, HEALTH_BAR_HEIGHT))
        fg = HEALTH_BAR_FG if ratio > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(surface, fg, (bx, by, bar_w * ratio, HEALTH_BAR_HEIGHT))


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------

class Unit(CircleEntity, Damageable):
    WANDER_INTERVAL = (1.0, 3.0)

    def __init__(self, x: float = 0, y: float = 0, team: int = 1,
                 unit_type: str = "soldier"):
        stats = UNIT_TYPES[unit_type]
        super().__init__(x, y, stats["radius"])
        self.unit_type = unit_type
        self.team = team
        self.speed = stats["speed"]
        self.target: tuple[float, float] | None = None
        self.color = TEAM1_COLOR if team == 1 else TEAM2_COLOR
        self._base_color = self.color

        self.max_hp = stats["hp"]
        self.hp = float(stats["hp"])
        self.can_attack: bool = stats["can_attack"]
        self.attack_damage: float = stats["damage"]
        self.attack_range: float = stats["range"]
        self.attack_cooldown_max: float = stats["cooldown"]
        self.laser_cooldown = 0.0

        self._symbol: tuple | None = stats["symbol"]
        self._heal_rate: float = stats.get("heal_rate", 0)
        self._heal_range: float = stats.get("heal_range", 0)
        self._heal_targets: int = stats.get("heal_targets", 0)
        self._heal_cooldown = 0.0

        self._wander_timer = random.uniform(*self.WANDER_INTERVAL)
        self._bounds: tuple[int, int] = (800, 600)

    @property
    def selectable(self) -> bool:
        return self.team == 1

    def set_selected(self, value: bool):
        if not self.selectable:
            return
        self.selected = value
        self.color = TEAM1_SELECTED_COLOR if value else self._base_color

    def command_move(self, tx: float, ty: float):
        self.target = (tx, ty)

    def update(self, dt: float):
        self.laser_cooldown = max(0.0, self.laser_cooldown - dt)

        if self.team == 2:
            self._wander(dt)

        if self.target is None:
            return

        dx = self.target[0] - self.x
        dy = self.target[1] - self.y
        dist = math.hypot(dx, dy)
        arrival = self.radius + GOAL_ARRIVAL_MARGIN
        if dist <= arrival:
            self.target = None
            return

        step = self.speed * dt
        if step >= dist:
            self.target = None
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step

    def _wander(self, dt: float):
        if self.target is not None:
            return
        self._wander_timer -= dt
        if self._wander_timer <= 0:
            margin = self.radius
            bw, bh = self._bounds
            self.target = (
                random.uniform(margin, bw - margin),
                random.uniform(margin, bh - margin),
            )
            self._wander_timer = random.uniform(*self.WANDER_INTERVAL)

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

        if self.unit_type == "medic":
            pygame.draw.circle(surface, MEDIC_HEAL_COLOR, (int(self.x), int(self.y)),
                               int(self._heal_range), 1)

        self.draw_health_bar(surface, self.x, self.y, self.radius + HEALTH_BAR_OFFSET)


# ---------------------------------------------------------------------------
# Command Center
# ---------------------------------------------------------------------------

class CommandCenter(PolygonEntity, Damageable):
    def __init__(self, x: float = 0, y: float = 0, team: int = 1):
        hex_pts = _hexagon_points(CC_RADIUS)
        super().__init__(x, y, hex_pts)
        self.team = team
        self.color = TEAM1_COLOR if team == 1 else TEAM2_COLOR
        self._base_color = self.color

        self.max_hp = CC_HP
        self.hp = CC_HP
        self.laser_cooldown = 0.0

        self._spawn_timer = 0.0
        self._bounds: tuple[int, int] = (800, 600)
        self.rally_point: tuple[float, float] | None = None
        self.spawn_type: str = "soldier"

    @property
    def selectable(self) -> bool:
        return self.team == 1

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
        self._spawn_timer += dt

    def spawn_ready(self) -> bool:
        return self._spawn_timer >= CC_SPAWN_INTERVAL

    def reset_spawn(self):
        self._spawn_timer = 0.0

    def spawn_unit(self) -> Unit:
        stype = self.spawn_type if self.team == 1 else random.choice(list(UNIT_TYPES.keys()))
        angle = random.uniform(0, math.tau)
        dist = CC_RADIUS + 15
        ux = self.x + math.cos(angle) * dist
        uy = self.y + math.sin(angle) * dist
        u = Unit(ux, uy, team=self.team, unit_type=stype)
        u._bounds = self._bounds
        if self.rally_point is not None:
            u.command_move(*self.rally_point)
        return u

    def draw(self, surface: pygame.Surface):
        translated = [(self.x + px, self.y + py) for px, py in self.points]
        pygame.draw.polygon(surface, self.color, translated)
        outline = TEAM1_SELECTED_COLOR if self.team == 1 else (255, 140, 140)
        pygame.draw.polygon(surface, outline, translated, 2)

        if self.selected:
            pygame.draw.polygon(surface, SELECTED_COLOR, translated, 2)

        # healing field aura
        heal_surf = pygame.Surface((int(CC_HEAL_RADIUS * 2), int(CC_HEAL_RADIUS * 2)), pygame.SRCALPHA)
        fill_c = CC_HEAL_COLOR_T1 if self.team == 1 else CC_HEAL_COLOR_T2
        ring_c = CC_HEAL_RING_T1 if self.team == 1 else CC_HEAL_RING_T2
        pygame.draw.circle(heal_surf, fill_c, (int(CC_HEAL_RADIUS), int(CC_HEAL_RADIUS)), int(CC_HEAL_RADIUS))
        pygame.draw.circle(heal_surf, ring_c, (int(CC_HEAL_RADIUS), int(CC_HEAL_RADIUS)), int(CC_HEAL_RADIUS), 1)
        surface.blit(heal_surf, (self.x - CC_HEAL_RADIUS, self.y - CC_HEAL_RADIUS))

        # spawn progress arc
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
            # flag pole + flag
            pygame.draw.line(surface, DEFAULT_COLOR, (rx, ry), (rx, ry - 14), 1)
            flag_pts = [(rx, ry - 14), (rx + 8, ry - 10), (rx, ry - 6)]
            pygame.draw.polygon(surface, self._base_color, flag_pts)
            pygame.draw.circle(surface, self._base_color, (int(rx), int(ry)), 3, 1)


# ---------------------------------------------------------------------------
# Laser flash effect (ephemeral)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

class Game:
    def __init__(self, width: int = 800, height: int = 600, title: str = "AIRTS"):
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        self.running = False
        self.fps = 60
        self.entities: list[Entity] = []
        self.laser_flashes: list[LaserFlash] = []
        self._spawn_world()

        self._dragging = False
        self._drag_start: tuple[int, int] = (0, 0)
        self._drag_end: tuple[int, int] = (0, 0)
        self._selection_surface = pygame.Surface((width, height), pygame.SRCALPHA)

        self._rdragging = False
        self._rpath: list[tuple[float, float]] = []

    # -- world setup --------------------------------------------------------

    def _spawn_world(self):
        self._spawn_obstacles()
        self._spawn_command_centers()

    def _spawn_obstacles(self):
        for _ in range(random.randint(4, 8)):
            if random.random() < 0.5:
                w = random.uniform(30, 80)
                h = random.uniform(30, 80)
                obs = RectEntity(
                    x=random.uniform(200, self.width - 200 - w),
                    y=random.uniform(60, self.height - 60 - h),
                    width=w, height=h,
                )
            else:
                r = random.uniform(15, 40)
                obs = CircleEntity(
                    x=random.uniform(200 + r, self.width - 200 - r),
                    y=random.uniform(60 + r, self.height - 60 - r),
                    radius=r,
                )
            obs.obstacle = True
            obs.color = OBSTACLE_COLOR
            self.entities.append(obs)

    def _spawn_command_centers(self):
        cc1 = CommandCenter(80, self.height // 2, team=1)
        cc1._bounds = (self.width, self.height)
        cc1._spawn_timer = CC_SPAWN_INTERVAL
        self.entities.append(cc1)

        cc2 = CommandCenter(self.width - 80, self.height // 2, team=2)
        cc2._bounds = (self.width, self.height)
        cc2._spawn_timer = CC_SPAWN_INTERVAL
        self.entities.append(cc2)

    # -- selection ----------------------------------------------------------

    def _selection_center(self) -> tuple[float, float]:
        return (float(self._drag_start[0]), float(self._drag_start[1]))

    def _selection_radius(self) -> float:
        cx, cy = self._selection_center()
        return math.hypot(self._drag_end[0] - cx, self._drag_end[1] - cy)

    def _entity_in_selection_circle(self, entity: Entity) -> bool:
        cx, cy = self._selection_center()
        sr = self._selection_radius()
        ex, ey = entity.center()
        er = entity.collision_radius()
        return math.hypot(ex - cx, ey - cy) <= sr + er

    def _click_select(self, mx: float, my: float, additive: bool):
        best: Entity | None = None
        best_dist = float("inf")
        for entity in self.entities:
            if not getattr(entity, "selectable", False):
                continue
            ex, ey = entity.center()
            er = entity.collision_radius()
            d = math.hypot(ex - mx, ey - my)
            if d <= er and d < best_dist:
                best_dist = d
                best = entity
        if not additive:
            for entity in self.entities:
                if getattr(entity, "selectable", False):
                    entity.set_selected(False)
        if best is not None:
            best.set_selected(True)

    def _apply_selection(self, additive: bool = False):
        if not additive:
            for entity in self.entities:
                if getattr(entity, "selectable", False):
                    entity.set_selected(False)
        for entity in self.entities:
            selectable = getattr(entity, "selectable", False)
            if selectable and self._entity_in_selection_circle(entity):
                entity.set_selected(True)

    # -- events -------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._handle_gui_click(event.pos[0], event.pos[1]):
                    continue
                self._dragging = True
                self._drag_start = event.pos
                self._drag_end = event.pos

            elif event.type == pygame.MOUSEMOTION:
                if self._dragging:
                    self._drag_end = event.pos
                if self._rdragging:
                    pos = (float(event.pos[0]), float(event.pos[1]))
                    if self._rpath:
                        last = self._rpath[-1]
                        if math.hypot(pos[0] - last[0], pos[1] - last[1]) >= PATH_SAMPLE_MIN_DIST:
                            self._rpath.append(pos)
                    else:
                        self._rpath.append(pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._dragging:
                self._drag_end = event.pos
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                if self._selection_radius() < 5:
                    self._click_select(
                        float(event.pos[0]), float(event.pos[1]), additive=bool(shift)
                    )
                else:
                    self._apply_selection(additive=bool(shift))
                self._dragging = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self._rdragging = True
                self._rpath = [(float(event.pos[0]), float(event.pos[1]))]

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3 and self._rdragging:
                self._rdragging = False
                self._assign_path_goals()
                self._set_rally_points()
                self._rpath = []

    # -- right-click path ---------------------------------------------------

    def _path_total_length(self) -> float:
        total = 0.0
        for i in range(1, len(self._rpath)):
            ax, ay = self._rpath[i - 1]
            bx, by = self._rpath[i]
            total += math.hypot(bx - ax, by - ay)
        return total

    def _resample_path(self, n: int) -> list[tuple[float, float]]:
        if n <= 0 or len(self._rpath) < 2:
            return list(self._rpath[:n])

        total = self._path_total_length()
        if total < 1e-6:
            return [self._rpath[0]] * n

        if n == 1:
            return [self._rpath[len(self._rpath) // 2]]

        spacing = total / (n - 1)
        points: list[tuple[float, float]] = [self._rpath[0]]
        accumulated = 0.0
        seg = 1
        seg_start = self._rpath[0]

        for i in range(1, n - 1):
            target_dist = i * spacing
            while seg < len(self._rpath):
                sx, sy = seg_start
                ex, ey = self._rpath[seg]
                seg_len = math.hypot(ex - sx, ey - sy)
                if accumulated + seg_len >= target_dist:
                    frac = (target_dist - accumulated) / seg_len if seg_len > 0 else 0
                    px = sx + (ex - sx) * frac
                    py = sy + (ey - sy) * frac
                    points.append((px, py))
                    break
                accumulated += seg_len
                seg_start = self._rpath[seg]
                seg += 1
            else:
                points.append(self._rpath[-1])

        points.append(self._rpath[-1])
        return points

    def _set_rally_points(self):
        if not self._rpath:
            return
        rally = self._rpath[-1]
        for entity in self.entities:
            if isinstance(entity, CommandCenter) and entity.selected:
                entity.rally_point = rally

    def _assign_path_goals(self):
        selected = [e for e in self.entities if isinstance(e, Unit) and e.selected]
        if not selected or len(self._rpath) < 2:
            if selected and len(self._rpath) == 1:
                px, py = self._rpath[0]
                for u in selected:
                    u.command_move(px, py)
            return

        goals = self._resample_path(len(selected))
        assigned: set[int] = set()

        for gx, gy in goals:
            best_idx = -1
            best_dist = float("inf")
            for i, unit in enumerate(selected):
                if i in assigned:
                    continue
                d = math.hypot(unit.x - gx, unit.y - gy)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            if best_idx >= 0:
                selected[best_idx].command_move(gx, gy)
                assigned.add(best_idx)

    # -- queries ------------------------------------------------------------

    def _get_units(self) -> list[Unit]:
        return [e for e in self.entities if isinstance(e, Unit)]

    def _get_command_centers(self) -> list[CommandCenter]:
        return [e for e in self.entities if isinstance(e, CommandCenter)]

    def _get_obstacles(self) -> list[Entity]:
        return [e for e in self.entities if e.obstacle]

    # -- line of sight ------------------------------------------------------

    def _has_los(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """True if the line from (x1,y1)->(x2,y2) is not blocked by any obstacle."""
        for obs in self._get_obstacles():
            if isinstance(obs, CircleEntity):
                if _line_intersects_circle(x1, y1, x2, y2, obs.x, obs.y, obs.radius):
                    return False
            elif isinstance(obs, RectEntity):
                if _line_intersects_rect(x1, y1, x2, y2, obs.x, obs.y, obs.width, obs.height):
                    return False
        return True

    # -- combat -------------------------------------------------------------

    def _combat_step(self, dt: float):
        units = self._get_units()
        ccs = self._get_command_centers()
        combatants: list[Unit | CommandCenter] = units + ccs  # type: ignore[operator]

        for i in range(len(combatants)):
            a = combatants[i]
            if not a.alive or a.laser_cooldown > 0:
                continue

            if isinstance(a, Unit) and not a.can_attack:
                continue

            a_team = a.team
            ax, ay = (a.x, a.y)
            if isinstance(a, Unit):
                a_range = a.attack_range
                a_dmg = a.attack_damage
                a_cd = a.attack_cooldown_max
            else:
                a_range = CC_LASER_RANGE
                a_dmg = CC_LASER_DAMAGE
                a_cd = CC_LASER_COOLDOWN

            best_target: Unit | CommandCenter | None = None
            best_dist = float("inf")

            for j in range(len(combatants)):
                if i == j:
                    continue
                b = combatants[j]
                if not b.alive or b.team == a_team:
                    continue
                bx, by = (b.x, b.y)
                d = math.hypot(bx - ax, by - ay)
                if d <= a_range and d < best_dist:
                    if self._has_los(ax, ay, bx, by):
                        best_dist = d
                        best_target = b

            if best_target is not None:
                best_target.take_damage(a_dmg)
                a.laser_cooldown = a_cd
                lc = (UNIT_LASER_COLOR_T1 if isinstance(a, Unit) and a_team == 1
                       else UNIT_LASER_COLOR_T2 if isinstance(a, Unit)
                       else CC_LASER_COLOR_T1 if a_team == 1
                       else CC_LASER_COLOR_T2)
                w = 1 if isinstance(a, Unit) else 2
                self.laser_flashes.append(
                    LaserFlash(ax, ay, best_target.x, best_target.y, lc, w)
                )

        self._medic_heal_step(dt)

    def _medic_heal_step(self, dt: float):
        units = self._get_units()
        for medic in units:
            if medic.unit_type != "medic" or not medic.alive:
                continue
            heal_amount = medic._heal_rate * dt
            candidates: list[tuple[float, Unit]] = []
            for u in units:
                if u is medic or u.team != medic.team or not u.alive:
                    continue
                if u.hp >= u.max_hp:
                    continue
                d = math.hypot(u.x - medic.x, u.y - medic.y)
                if d <= medic._heal_range:
                    candidates.append((d, u))
            candidates.sort(key=lambda t: t[0])
            for _, target in candidates[:medic._heal_targets]:
                target.hp = min(target.max_hp, target.hp + heal_amount)

    # -- spawning -----------------------------------------------------------

    def _heal_step(self, dt: float):
        for cc in self._get_command_centers():
            if not cc.alive:
                continue
            heal_amount = CC_HEAL_RATE * dt
            for unit in self._get_units():
                if unit.team != cc.team or not unit.alive:
                    continue
                if unit.hp >= unit.max_hp:
                    continue
                d = math.hypot(unit.x - cc.x, unit.y - cc.y)
                if d <= CC_HEAL_RADIUS:
                    unit.hp = min(unit.max_hp, unit.hp + heal_amount)

    def _spawn_step(self):
        for cc in self._get_command_centers():
            if cc.alive and cc.spawn_ready():
                u = cc.spawn_unit()
                self.entities.append(u)
                cc.reset_spawn()

    # -- death cleanup ------------------------------------------------------

    def _cleanup_dead(self):
        self.entities = [e for e in self.entities if e.alive]

    # -- physics ------------------------------------------------------------

    def _resolve_unit_collisions(self, dt: float):
        units = self._get_units()
        for i in range(len(units)):
            for j in range(i + 1, len(units)):
                a, b = units[i], units[j]
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.hypot(dx, dy)
                min_dist = a.radius + b.radius
                if dist < min_dist and dist > 0:
                    overlap = min_dist - dist
                    nx = dx / dist
                    ny = dy / dist
                    push = overlap * 0.5 + UNIT_PUSH_FORCE * dt
                    a.x -= nx * push * 0.5
                    a.y -= ny * push * 0.5
                    b.x += nx * push * 0.5
                    b.y += ny * push * 0.5
                elif dist == 0:
                    angle = random.uniform(0, math.tau)
                    nudge = UNIT_PUSH_FORCE * dt
                    a.x += math.cos(angle) * nudge
                    a.y += math.sin(angle) * nudge

    def _resolve_obstacle_collisions(self, dt: float):
        units = self._get_units()
        obstacles = self._get_obstacles()
        for unit in units:
            for obs in obstacles:
                if isinstance(obs, CircleEntity):
                    self._push_unit_from_circle_obstacle(unit, obs, dt)
                elif isinstance(obs, RectEntity):
                    self._push_unit_from_rect_obstacle(unit, obs, dt)

    def _resolve_structure_collisions(self, dt: float):
        units = self._get_units()
        for unit in units:
            for cc in self._get_command_centers():
                dx = unit.x - cc.x
                dy = unit.y - cc.y
                dist = math.hypot(dx, dy)
                min_dist = unit.radius + CC_RADIUS
                if dist < min_dist and dist > 0:
                    nx = dx / dist
                    ny = dy / dist
                    push = (min_dist - dist) + OBSTACLE_PUSH_FORCE * dt
                    unit.x += nx * push
                    unit.y += ny * push
                elif dist == 0:
                    angle = random.uniform(0, math.tau)
                    unit.x += math.cos(angle) * OBSTACLE_PUSH_FORCE * dt
                    unit.y += math.sin(angle) * OBSTACLE_PUSH_FORCE * dt

    def _push_unit_from_circle_obstacle(self, unit: Unit, obs: CircleEntity, dt: float):
        dx = unit.x - obs.x
        dy = unit.y - obs.y
        dist = math.hypot(dx, dy)
        min_dist = unit.radius + obs.radius
        if dist < min_dist and dist > 0:
            nx = dx / dist
            ny = dy / dist
            push = (min_dist - dist) + OBSTACLE_PUSH_FORCE * dt
            unit.x += nx * push
            unit.y += ny * push
        elif dist == 0:
            angle = random.uniform(0, math.tau)
            unit.x += math.cos(angle) * OBSTACLE_PUSH_FORCE * dt
            unit.y += math.sin(angle) * OBSTACLE_PUSH_FORCE * dt

    def _push_unit_from_rect_obstacle(self, unit: Unit, obs: RectEntity, dt: float):
        cx = max(obs.x, min(unit.x, obs.x + obs.width))
        cy = max(obs.y, min(unit.y, obs.y + obs.height))
        dx = unit.x - cx
        dy = unit.y - cy
        dist = math.hypot(dx, dy)
        if dist < unit.radius:
            if dist > 0:
                nx = dx / dist
                ny = dy / dist
            else:
                angle = random.uniform(0, math.tau)
                nx = math.cos(angle)
                ny = math.sin(angle)
            push = (unit.radius - dist) + OBSTACLE_PUSH_FORCE * dt
            unit.x += nx * push
            unit.y += ny * push

    def _clamp_units_to_bounds(self):
        for entity in self.entities:
            if isinstance(entity, Unit):
                r = entity.radius
                entity.x = max(r, min(entity.x, self.width - r))
                entity.y = max(r, min(entity.y, self.height - r))

    # -- main step ----------------------------------------------------------

    def step(self, dt: float):
        for entity in self.entities:
            entity.update(dt)
        self._combat_step(dt)
        self._heal_step(dt)
        self._spawn_step()
        self._cleanup_dead()
        self._resolve_unit_collisions(dt)
        self._resolve_obstacle_collisions(dt)
        self._resolve_structure_collisions(dt)
        self._clamp_units_to_bounds()

        self.laser_flashes = [lf for lf in self.laser_flashes if lf.update(dt)]

    # -- render -------------------------------------------------------------

    def render(self):
        self.screen.fill((0, 0, 0))
        for entity in self.entities:
            entity.draw(self.screen)

        for lf in self.laser_flashes:
            lf.draw(self.screen)

        if self._dragging:
            sr = self._selection_radius()
            if sr >= 5:
                cx, cy = self._selection_center()
                self._selection_surface.fill((0, 0, 0, 0))
                pygame.draw.circle(self._selection_surface, SELECTION_FILL_COLOR,
                                   (int(cx), int(cy)), int(sr))
                pygame.draw.circle(self._selection_surface, SELECTION_RECT_COLOR,
                                   (int(cx), int(cy)), int(sr), 1)
                self.screen.blit(self._selection_surface, (0, 0))

        if self._rdragging and len(self._rpath) >= 2:
            pygame.draw.lines(self.screen, COMMAND_PATH_COLOR, False, self._rpath, 2)
            selected_count = sum(
                1 for e in self.entities if isinstance(e, Unit) and e.selected
            )
            if selected_count > 0:
                preview = self._resample_path(selected_count)
                for px, py in preview:
                    pygame.draw.circle(self.screen, COMMAND_DOT_COLOR, (int(px), int(py)), 4, 1)

        self._draw_cc_gui()

        pygame.display.flip()

    def _get_selected_cc(self) -> CommandCenter | None:
        for e in self.entities:
            if isinstance(e, CommandCenter) and e.selected:
                return e
        return None

    def _gui_button_rects(self) -> list[tuple[pygame.Rect, str]]:
        types = list(UNIT_TYPES.keys())
        total_w = len(types) * GUI_BTN_SIZE + (len(types) - 1) * GUI_BTN_GAP
        start_x = (self.width - total_w) // 2
        y = self.height - GUI_PANEL_HEIGHT + (GUI_PANEL_HEIGHT - GUI_BTN_SIZE) // 2
        rects = []
        for i, utype in enumerate(types):
            bx = start_x + i * (GUI_BTN_SIZE + GUI_BTN_GAP)
            rects.append((pygame.Rect(bx, y, GUI_BTN_SIZE, GUI_BTN_SIZE), utype))
        return rects

    def _draw_cc_gui(self):
        cc = self._get_selected_cc()
        if cc is None:
            return

        panel_rect = pygame.Rect(0, self.height - GUI_PANEL_HEIGHT, self.width, GUI_PANEL_HEIGHT)
        pygame.draw.rect(self.screen, GUI_BG, panel_rect)
        pygame.draw.line(self.screen, GUI_BORDER, (0, panel_rect.top), (self.width, panel_rect.top), 1)

        mx, my = pygame.mouse.get_pos()
        font = pygame.font.SysFont(None, 18)

        for btn_rect, utype in self._gui_button_rects():
            is_selected = cc.spawn_type == utype
            is_hover = btn_rect.collidepoint(mx, my)

            if is_selected:
                bg = GUI_BTN_SELECTED
            elif is_hover:
                bg = GUI_BTN_HOVER
            else:
                bg = GUI_BTN_NORMAL

            pygame.draw.rect(self.screen, bg, btn_rect, border_radius=4)
            pygame.draw.rect(self.screen, GUI_BORDER, btn_rect, 1, border_radius=4)

            stats = UNIT_TYPES[utype]
            symbol = stats["symbol"]
            cx = btn_rect.centerx
            cy = btn_rect.centery - 4
            if symbol is not None:
                scale = 1.2
                pts = [(cx + px * scale, cy + py * scale) for px, py in symbol]
                pygame.draw.polygon(self.screen, TEAM1_COLOR, pts)
                pygame.draw.polygon(self.screen, TEAM1_SELECTED_COLOR, pts, 1)
            else:
                pygame.draw.circle(self.screen, TEAM1_COLOR, (cx, cy), 8)
                pygame.draw.circle(self.screen, TEAM1_SELECTED_COLOR, (cx, cy), 8, 1)

            label = font.render(utype.upper(), True, GUI_TEXT_COLOR)
            lx = btn_rect.centerx - label.get_width() // 2
            ly = btn_rect.bottom - label.get_height() - 2
            self.screen.blit(label, (lx, ly))

    def _handle_gui_click(self, mx: int, my: int) -> bool:
        cc = self._get_selected_cc()
        if cc is None:
            return False
        for btn_rect, utype in self._gui_button_rects():
            if btn_rect.collidepoint(mx, my):
                cc.spawn_type = utype
                return True
        return False

    def run(self):
        self.running = True
        while self.running:
            dt = self.clock.tick(self.fps) / 1000.0
            self.handle_events()
            self.step(dt)
            self.render()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = Game()
    game.run()
