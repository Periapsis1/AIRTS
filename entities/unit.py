from __future__ import annotations
import math
import pygame
from entities.shapes import CircleEntity
from entities.base import Entity, Damageable
from entities.weapon import Weapon
from config.settings import (
    PLAYER_COLORS, TEAM1_SELECTED_COLOR,
    SELECTED_COLOR, HEALTH_BAR_OFFSET, MEDIC_HEAL_COLOR,
    RANGE_COLOR, HEAL_LASER_COLOR,
    OVERCLOCK_REGEN, OVERCLOCK_BONUS, OVERCLOCK_REGEN_T2, OVERCLOCK_BONUS_T2,
)
from config.unit_types import UNIT_TYPES
from core.helpers import angle_diff
from systems.abilities import (
    ReactiveArmor, ElectricArmor, Focus, CombatStim, Overclock, ability_from_dict,
)

# fire-mode constants
HOLD_FIRE = "hold_fire"
TARGET_FIRE = "target_fire"
FREE_FIRE = "free_fire"

# Command line colors
_MOVE_CMD_COLOR = (0, 140, 40)     # dark green for move commands
_ATTACK_CMD_COLOR = (180, 30, 30)  # dark red for attack commands
_FIGHT_CMD_COLOR = (180, 50, 180)  # pinkish purple for fight commands
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

    def __init__(self, x: float = 0, y: float = 0, team: int = 1,
                 unit_type: str = "soldier", player_id: int = 1):
        stats = UNIT_TYPES[unit_type]
        super().__init__(x, y, stats["radius"])
        self.unit_type = unit_type
        self.team = team
        self.player_id = player_id
        self.is_t2: bool = stats.get("is_t2", False)
        self.speed: float = stats["speed"]
        self.color = PLAYER_COLORS[(player_id - 1) % len(PLAYER_COLORS)]
        self._base_color = self.color

        self.max_hp: float = stats["hp"]
        self.hp: float = float(stats["hp"])
        self.can_attack: bool = stats["can_attack"]

        wdata = stats.get("weapon")
        if wdata:
            laser_color = wdata.get("laser_color", PLAYER_COLORS[(player_id - 1) % len(PLAYER_COLORS)])
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
                splash_radius=wdata.get("splash_radius", 0.0),
                splash_damage_max=wdata.get("splash_damage_max", 0.0),
                splash_damage_min=wdata.get("splash_damage_min", 0.0),
                laser_flash_duration=wdata.get("laser_flash_duration", 0.0),
                charge_time=wdata.get("charge_time", 0.0),
                friendly_fire=wdata.get("friendly_fire", False),
            )
        else:
            self.weapon = None

        self.attack_damage: float = self.weapon.damage if self.weapon else 0
        self.attack_range: float = self.weapon.range if self.weapon else 0
        self.attack_range_sq: float = self.attack_range * self.attack_range
        self.attack_cooldown_max: float = self.weapon.cooldown if self.weapon else 0
        self.laser_cooldown: float = 0.0
        self.diameter: float = self.radius * 2.0
        self.diameter_sq: float = self.diameter * self.diameter

        self._symbol: tuple | None = stats["symbol"]
        self.is_building: bool = stats.get("is_building", False)

        self.facing_angle: float = 0.0                                    # radians, 0 = right (+x)
        self.fov: float = math.radians(stats.get("fov", 90))             # stored in radians
        self._fov_half_cos: float = math.cos(self.fov / 2)               # precomputed for dot-product FOV check
        self.turn_rate: float = math.radians(stats.get("turn_rate", 180)) # rad/s
        self.line_of_sight: float = float(stats.get("los", 100))         # pixels

        self._bounds: tuple[int, int] = (800, 600)

        # -- command state ---------------------------------------------------
        self.target: tuple[float, float] | None = None
        self._stop_dist: float = 0.0
        self.fight_move: bool = False  # fight command: pause movement when enemy in range
        self.attack_move: bool = False  # attack-move: like fight but red arrow + artillery ground fire
        self.attack_ground_pos: tuple[float, float] | None = None  # artillery ground target

        self._follow_entity: Entity | None = None
        self._follow_dist: float = 0.0

        self.attack_target: Entity | None = None
        self.fire_mode: str = FREE_FIRE
        self.command_queue: list[dict] = []  # queued commands (shift+click)

        self.selectable: bool = False
        self._facing_target: Entity | None = None   # entity ref, set by combat system

        # -- charge state (artillery etc.) -------------------------------------
        self._charge_pos: tuple[float, float] | None = None  # locked world position
        self._charge_timer: float = 0.0                      # seconds remaining

        # -- targeting data (populated every 15 ticks by Game) -------------------
        self.nearest_enemy: Unit | None = None       # vectorized nearest enemy
        self.nearest_ally: Unit | None = None        # vectorized nearest ally

        # -- quadfield cell tracking (managed by QuadField) ---------------------
        self._quad_cells: list[int] = []
        self._temp_num: int = 0
        self._tick: int = 0

        # -- abilities ----------------------------------------------------------
        self.abilities: list = []
        if unit_type == "tank":
            self.abilities = [ReactiveArmor()]
        elif unit_type == "tank_t2":
            self.abilities = [ElectricArmor()]
        elif unit_type in ("sniper", "sniper_t2"):
            self.abilities = [Focus()]
        elif unit_type == "soldier_t2":
            self.abilities = [CombatStim()]
        elif unit_type == "engineer":
            self.abilities = [Overclock(regen=OVERCLOCK_REGEN, bonus=OVERCLOCK_BONUS)]
        elif unit_type == "engineer_t2":
            self.abilities = [Overclock(regen=OVERCLOCK_REGEN_T2, bonus=OVERCLOCK_BONUS_T2)]

    # -- damage -------------------------------------------------------------

    def take_damage(self, amount: float):
        for ability in self.abilities:
            amount = ability.modify_damage(amount, self)
        super().take_damage(amount)

    def on_death(self) -> dict | None:
        """Return a death-event dict for client visuals (or None to skip).

        Called by the game's cleanup pass when this unit's `alive` flips to
        False. Server-side gameplay cleanup belongs in `on_destroy` (called
        earlier from `take_damage`); this hook only emits visual data.
        """
        return {
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "c": list(self._base_color[:3]),
            "r": float(self.radius),
        }

    # -- commands -----------------------------------------------------------

    def move(self, x: float, y: float, stop_dist: float = 0.0):
        self.target = (x, y)
        self._stop_dist = stop_dist
        self._follow_entity = None
        self.fight_move = False
        self.attack_move = False
        self.attack_ground_pos = None

    def fight(self, x: float, y: float):
        """Move toward (x, y) but stop whenever an enemy is within weapon range."""
        self.target = (x, y)
        self._stop_dist = 0.0
        self._follow_entity = None
        self.fight_move = True
        self.attack_move = False
        self.attack_ground_pos = None

    def attack_move_to(self, x: float, y: float):
        """Move toward (x, y), stopping to fight enemies in range. Red arrow."""
        self.target = (x, y)
        self._stop_dist = 0.0
        self._follow_entity = None
        self.fight_move = True  # reuse fight pause logic
        self.attack_move = True

    def attack_unit_cmd(self, target: Entity):
        """Follow and focus-fire a specific target."""
        self.attack_target = target
        self._follow_entity = target
        self._follow_dist = self.attack_range * 0.9
        self.target = None
        self.fight_move = False
        self.attack_move = False
        self.attack_ground_pos = None
        self.fire_mode = TARGET_FIRE

    def follow(self, target: Entity, distance: float):
        self._follow_entity = target
        self._follow_dist = distance
        self.target = None

    def attack(self, target: Entity):
        self.attack_target = target

    def stop(self):
        self.target = None
        self._follow_entity = None
        self.fight_move = False
        self.attack_move = False
        self.attack_ground_pos = None
        self.command_queue.clear()

    def has_active_command(self) -> bool:
        """Return True if the unit is currently executing a command."""
        if self.target is not None:
            return True
        if self._follow_entity is not None:
            return True
        if self.attack_target is not None and self.attack_target.alive:
            return True
        return False

    def _dequeue_next(self) -> None:
        """Pop and execute the next queued command."""
        while self.command_queue:
            cmd = self.command_queue.pop(0)
            cmd_type = cmd.get("type")
            if cmd_type == "move":
                self.move(cmd["x"], cmd["y"])
                return
            elif cmd_type == "fight":
                self.fight(cmd["x"], cmd["y"])
                return
            elif cmd_type == "attack_move":
                self.attack_move_to(cmd["x"], cmd["y"])
                if self.weapon and self.weapon.charge_time > 0:
                    self.attack_ground_pos = (cmd["x"], cmd["y"])
                return
            elif cmd_type == "attack":
                ref = cmd.get("_target_ref")
                if ref is not None and ref.alive:
                    self.attack_unit_cmd(ref)
                    return
                # Target dead — skip to next

    # -- selection ----------------------------------------------------------

    def set_selected(self, value: bool):
        if not self.selectable:
            return
        self.selected = value
        self.color = TEAM1_SELECTED_COLOR if value else self._base_color

    # -- update -------------------------------------------------------------

    def update(self, dt: float):
        self.laser_cooldown = max(0.0, self.laser_cooldown - dt)

        if self.abilities:
            for ability in self.abilities:
                ability.update(self, dt)

        if self.attack_target is not None and not self.attack_target.alive:
            self.attack_target = None

        # Dequeue next command if idle
        if not self.has_active_command() and self.command_queue:
            self._dequeue_next()

        if not self.is_building:
            # Facing is now batched in game.py via batch_facing_update()
            self._update_follow()
            self._update_movement(dt)
            self._tick += 1

    def _update_facing(self, dt: float):
        # Priority: attack_target > cached nearest enemy/ally > movement target > hold

        if self.weapon.hits_only_friendly:
            if self.nearest_ally is not None and self.nearest_ally:
                target_pos = (self.nearest_ally.x, self.nearest_ally.y)
            else:
                return
        else:
            if self.nearest_enemy is not None and self.nearest_enemy.alive:
                target_pos = (self.nearest_enemy.x, self.nearest_enemy.y)
            else:
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
        if self._charge_pos is not None:
            return  # locked in place while charging
        if self.target is None:
            return

        # Fight command: pause movement while an enemy is within weapon range
        if self.fight_move and self.nearest_enemy is not None and self.nearest_enemy.alive:
            d_sq = (self.nearest_enemy.x - self.x) ** 2 + (self.nearest_enemy.y - self.y) ** 2
            if d_sq <= self.attack_range_sq:
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
        ix, iy = int(round(self.x)), int(round(self.y))
        half_fov = self.fov / 2
        # Full circle (or nearly): fall back to simple circle
        if self.fov >= math.tau - 0.01:
            temp = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp, color, (r, r), r, 1)
            surface.blit(temp, (ix - r, iy - r))
            return

        # Build a polygon: center -> arc points -> center
        start = self.facing_angle - half_fov
        steps = max(int(math.degrees(self.fov) / 3), 8)
        points = [(ix, iy)]
        for i in range(steps + 1):
            a = start + self.fov * i / steps
            points.append((int(round(ix + r * math.cos(a))),
                           int(round(iy + r * math.sin(a)))))
        points.append((ix, iy))

        temp_size = r * 2 + 4
        temp = pygame.Surface((temp_size, temp_size), pygame.SRCALPHA)
        ox = temp_size // 2 - ix
        oy = temp_size // 2 - iy
        shifted = [(px + ox, py + oy) for px, py in points]
        pygame.draw.lines(temp, color, False, shifted, 1)
        surface.blit(temp, (ix - temp_size // 2, iy - temp_size // 2))

    def draw(self, surface: pygame.Surface):
        from core.sprite_cache import get_unit_sprite
        sprite = get_unit_sprite(self.unit_type, self.color, self.radius)
        ix, iy = int(round(self.x)), int(round(self.y))
        hw, hh = sprite.get_width() // 2, sprite.get_height() // 2
        surface.blit(sprite, (ix - hw, iy - hh))

        if self.selected:
            pygame.draw.circle(surface, SELECTED_COLOR, (ix, iy), self.radius + 2, 1)

            if self.attack_target is not None and self.attack_target.alive:
                _draw_command_line(surface, ix, iy,
                                  int(round(self.attack_target.x)),
                                  int(round(self.attack_target.y)),
                                  _ATTACK_CMD_COLOR)
            elif self.target is not None:
                if self.attack_move:
                    color = _ATTACK_CMD_COLOR
                elif self.fight_move:
                    color = _FIGHT_CMD_COLOR
                else:
                    color = _MOVE_CMD_COLOR
                _draw_command_line(surface, ix, iy,
                                  int(round(self.target[0])),
                                  int(round(self.target[1])),
                                  color)

            # Draw queued command waypoints
            if self.command_queue:
                # Chain from current command endpoint
                if self.attack_target is not None and self.attack_target.alive:
                    px, py = int(round(self.attack_target.x)), int(round(self.attack_target.y))
                elif self.target is not None:
                    px, py = int(round(self.target[0])), int(round(self.target[1]))
                else:
                    px, py = ix, iy
                for qcmd in self.command_queue:
                    qtype = qcmd.get("type", "move")
                    if qtype == "attack":
                        ref = qcmd.get("_target_ref")
                        if ref is not None and ref.alive:
                            qx, qy = int(round(ref.x)), int(round(ref.y))
                        else:
                            continue
                        qcolor = _ATTACK_CMD_COLOR
                    else:
                        if "x" not in qcmd:
                            continue
                        qx, qy = int(round(qcmd["x"])), int(round(qcmd["y"]))
                        if qtype == "attack_move":
                            qcolor = _ATTACK_CMD_COLOR
                        elif qtype == "fight":
                            qcolor = _FIGHT_CMD_COLOR
                        else:
                            qcolor = _MOVE_CMD_COLOR
                    _draw_command_line(surface, px, py, qx, qy, qcolor)
                    pygame.draw.circle(surface, qcolor, (qx, qy), 3, 1)
                    px, py = qx, qy

        for ability in self.abilities:
            ability.draw(self, surface)

        self.draw_health_bar(surface, ix, iy, self.radius + HEALTH_BAR_OFFSET)

    def draw_fov(self, surface: pygame.Surface):
        """Draw FOV/range arc. Called in a pre-pass so arcs render behind units."""
        # Allied units: only show FOV arc when selected; enemies: always
        if not self.selectable or self.selected:
            if self.weapon and self.weapon.hits_only_friendly:
                self._draw_fov_arc(surface, MEDIC_HEAL_COLOR)
            else:
                self._draw_fov_arc(surface, RANGE_COLOR)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "team": self.team,
            "player_id": self.player_id,
            "unit_type": self.unit_type,
            "hp": self.hp,
            "laser_cooldown": self.laser_cooldown,
            "facing_angle": self.facing_angle,
            "line_of_sight": self.line_of_sight,
            "is_building": self.is_building,
            "target": list(self.target) if self.target else None,
            "_stop_dist": self._stop_dist,
            "fight_move": self.fight_move,
            "attack_move": self.attack_move,
            "attack_ground_pos": list(self.attack_ground_pos) if self.attack_ground_pos else None,
            "fire_mode": self.fire_mode,
            "selectable": self.selectable,
            "_bounds": list(self._bounds),
            "_follow_entity_id": self._follow_entity.entity_id if self._follow_entity else None,
            "_follow_dist": self._follow_dist,
            "attack_target_id": self.attack_target.entity_id if self.attack_target else None,
            "abilities": [a.to_dict() for a in self.abilities],
            "_charge_pos": list(self._charge_pos) if self._charge_pos else None,
            "_charge_timer": self._charge_timer,
            "is_t2": self.is_t2,
            "command_queue": [
                {k: v for k, v in entry.items() if k != "_target_ref"}
                for entry in self.command_queue
            ],
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Unit:
        u = cls(data["x"], data["y"], data["team"], data["unit_type"],
                player_id=data.get("player_id", data.get("team", 1)))
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
        u.fight_move = data.get("fight_move", False)
        u.attack_move = data.get("attack_move", False)
        agp = data.get("attack_ground_pos")
        u.attack_ground_pos = tuple(agp) if agp else None
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
        cp = data.get("_charge_pos")
        u._charge_pos = tuple(cp) if cp else None
        u._charge_timer = data.get("_charge_timer", 0.0)
        u.is_t2 = data.get("is_t2", False)
        u.command_queue = data.get("command_queue", [])
        # cross-references resolved later by Game.load_state()
        u._follow_entity = None
        u.attack_target = None
        return u
