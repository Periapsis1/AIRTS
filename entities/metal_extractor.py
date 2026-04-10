from __future__ import annotations
from config.settings import (
    HEALTH_BAR_OFFSET,
    METAL_EXTRACTOR_SPAWN_BONUS,
    REINFORCE_BONUS_MULTIPLIER,
    METAL_SPOT_CAPTURE_RADIUS,
    SELECTED_COLOR,
    TEAM_COLORS, PLAYER_COLORS,
    OUTPOST_UPGRADE_DURATION,
    RESEARCH_LAB_UPGRADE_DURATION,
    T2_SPAWN_BONUS,
    OUTPOST_HEAL_PER_SEC,
    OUTPOST_LASER_RANGE,
    OUTPOST_LASER_DAMAGE,
    OUTPOST_LASER_COOLDOWN,
    OUTPOST_HP_BONUS,
    OUTPOST_LOS,
    RESEARCH_LAB_HP_BONUS,
)
from entities.unit import Unit
from entities.metal_spot import MetalSpot
from entities.weapon import Weapon
from systems.abilities import Reinforce, ability_from_dict
import pygame
import math


class MetalExtractor(Unit):
    def __init__(self, *, metal_spot: MetalSpot | None = None, team: int = 1,
                 x: float = 0, y: float = 0, player_id: int | None = None):
        if metal_spot is not None:
            x, y = metal_spot.x, metal_spot.y
        super().__init__(x, y, team, unit_type="metal_extractor",
                         player_id=player_id if player_id is not None else team)
        self.metal_spot = metal_spot
        self.rotation: float = 0.0
        self.rotation_speed: float = 10.0
        self.abilities = [Reinforce()]

        # T2 upgrade state
        self.upgrade_state: str = "base"  # base | choosing_research | upgrading_outpost | upgrading_lab | outpost | research_lab
        self.upgrade_timer: float = 0.0
        self.researched_unit_type: str | None = None  # locked in before upgrade begins

        # Overclock buff state — engineers add to `_pending` each tick; the
        # extractor flushes pending → bonus during its own update so multiple
        # engineers stack additively regardless of entity update order.
        self._overclock_bonus: float = 0.0
        self._overclock_bonus_pending: float = 0.0

    @property
    def is_fully_reinforced(self) -> bool:
        return any(isinstance(a, Reinforce) and a.active for a in self.abilities)

    def get_spawn_bonus(self) -> float:
        """Return additive spawn bonus (e.g. 0.08 or 0.16 if reinforced)."""
        if self.upgrade_state in ("upgrading_outpost", "upgrading_lab", "choosing_research"):
            return 0.0
        if self.upgrade_state in ("outpost", "research_lab"):
            base = T2_SPAWN_BONUS
        else:
            base = METAL_EXTRACTOR_SPAWN_BONUS
            for ability in self.abilities:
                if isinstance(ability, Reinforce) and ability.active:
                    base *= REINFORCE_BONUS_MULTIPLIER
        base += self._overclock_bonus
        return base

    def start_upgrade(self, path: str):
        """Begin the upgrade. path is 'outpost' or 'lab'."""
        self.upgrade_state = f"upgrading_{path}"
        if path == "outpost":
            self.upgrade_timer = OUTPOST_UPGRADE_DURATION
        else:
            self.upgrade_timer = RESEARCH_LAB_UPGRADE_DURATION

    def _finish_outpost(self):
        self.upgrade_state = "outpost"
        self.upgrade_timer = 0.0
        self.max_hp += OUTPOST_HP_BONUS
        self.hp += OUTPOST_HP_BONUS
        color = TEAM_COLORS.get(self.team, PLAYER_COLORS[0])
        self.weapon = Weapon(
            name="Laser",
            damage=OUTPOST_LASER_DAMAGE,
            range=OUTPOST_LASER_RANGE,
            cooldown=OUTPOST_LASER_COOLDOWN,
            laser_color=color,
        )
        self.can_attack = True
        self.attack_damage = self.weapon.damage
        self.attack_range = self.weapon.range
        self.attack_range_sq = self.attack_range ** 2
        self.attack_cooldown_max = self.weapon.cooldown
        self.fov = math.tau  # 360 degrees
        self.line_of_sight = OUTPOST_LOS

    def _finish_research_lab(self):
        self.upgrade_state = "research_lab"
        self.upgrade_timer = 0.0
        self.max_hp += RESEARCH_LAB_HP_BONUS
        self.hp += RESEARCH_LAB_HP_BONUS

    def update(self, dt: float):
        super().update(dt)
        self.rotation = (self.rotation + dt * self.rotation_speed) % math.tau
        for ability in self.abilities:
            ability.update(self, dt)

        # Flush the pending overclock contributions accumulated since the last
        # update into the live bonus, then reset the accumulator so engineers
        # can re-stack their bonuses for the next tick. When no engineer is in
        # range, pending stays 0 and the bonus fades on its own.
        self._overclock_bonus = self._overclock_bonus_pending
        self._overclock_bonus_pending = 0.0

        # Upgrade timer countdown
        if self.upgrade_state.startswith("upgrading"):
            self.upgrade_timer -= dt
            if self.upgrade_timer <= 0:
                if self.upgrade_state == "upgrading_outpost":
                    self._finish_outpost()
                elif self.upgrade_state == "upgrading_lab":
                    self._finish_research_lab()

        # Outpost passive heal
        if self.upgrade_state == "outpost" and self.hp < self.max_hp:
            self.hp = min(self.max_hp, self.hp + OUTPOST_HEAL_PER_SEC * dt)

    def on_destroy(self):
        if self.metal_spot is not None:
            self.metal_spot.release()
            self.metal_spot = None

    # -- drawing ---------------------------------------------------------------

    def draw(self, surface: pygame.Surface):
        if self.upgrade_state == "outpost":
            self._draw_outpost(surface)
        elif self.upgrade_state == "research_lab":
            self._draw_research_lab(surface)
        else:
            self._draw_base(surface)

        # Draw plating arcs for Reinforce ability
        for ability in self.abilities:
            if isinstance(ability, Reinforce) and ability.stacks > 0:
                self._draw_plating_arcs(surface, ability.stacks)

        # Upgrade progress arc
        if self.upgrade_state.startswith("upgrading"):
            self._draw_upgrade_progress(surface)

        if self.selected:
            pygame.draw.circle(surface, SELECTED_COLOR, (self.x, self.y), self.radius + 2, 1)
            if self.upgrade_state == "outpost":
                from config.settings import RANGE_COLOR
                self._draw_fov_arc(surface, RANGE_COLOR)

        self.draw_health_bar(surface, self.x, self.y, self.radius + HEALTH_BAR_OFFSET)

    def _draw_base(self, surface: pygame.Surface):
        """Draw the base rotating equilateral triangle."""
        r = self.radius
        s = r * math.sqrt(3) / 2
        static_points = [
            complex(0, r),
            complex(-s, -r / 2),
            complex(s, -r / 2),
        ]
        rotated_points = [p * complex(math.cos(self.rotation), math.sin(self.rotation)) for p in static_points]
        points = [(p.real + self.x, p.imag + self.y) for p in rotated_points]
        pygame.draw.polygon(surface, self._base_color, points)
        pygame.draw.polygon(surface, (0, 0, 0), points, 1)

    def _draw_outpost(self, surface: pygame.Surface):
        """Draw a square for the Outpost."""
        r = self.radius
        rot = complex(math.cos(self.rotation), math.sin(self.rotation))
        static_points = [complex(-r, -r), complex(r, -r), complex(r, r), complex(-r, r)]
        rotated = [p * rot for p in static_points]
        points = [(p.real + self.x, p.imag + self.y) for p in rotated]
        pygame.draw.polygon(surface, self._base_color, points)
        pygame.draw.polygon(surface, (0, 0, 0), points, 1)

    def _draw_research_lab(self, surface: pygame.Surface):
        """Draw a hexagon for the research lab with a green glow when active."""
        # Green glow aura when researching a T2 unit
        if self.researched_unit_type:
            glow_rx = int(self.radius * 2.0)
            glow_ry = int(self.radius * 2.8)
            glow_surf = pygame.Surface((glow_rx * 2, glow_ry * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(glow_surf, (60, 220, 80, 45),
                                (0, 0, glow_rx * 2, glow_ry * 2))
            surface.blit(glow_surf,
                         (self.x - glow_rx, self.y - glow_ry))

        r = self.radius
        rot = complex(math.cos(self.rotation), math.sin(self.rotation))
        static_points = [complex(r * math.cos(math.tau * i / 6), r * math.sin(math.tau * i / 6)) for i in range(6)]
        rotated = [p * rot for p in static_points]
        points = [(p.real + self.x, p.imag + self.y) for p in rotated]
        pygame.draw.polygon(surface, self._base_color, points)
        pygame.draw.polygon(surface, (0, 0, 0), points, 1)

    def _draw_upgrade_progress(self, surface: pygame.Surface):
        """Draw a progress arc around the extractor during upgrade."""
        duration = OUTPOST_UPGRADE_DURATION if self.upgrade_state == "upgrading_outpost" else RESEARCH_LAB_UPGRADE_DURATION
        progress = 1.0 - max(0.0, self.upgrade_timer / duration)
        if progress <= 0:
            return
        arc_r = METAL_SPOT_CAPTURE_RADIUS + 2
        rect = pygame.Rect(self.x - arc_r, self.y - arc_r, arc_r * 2, arc_r * 2)
        start_angle = math.pi / 2
        end_angle = start_angle + progress * math.tau
        color = (200, 200, 60)
        pygame.draw.arc(surface, color, rect, start_angle, end_angle, 2)

    def _draw_plating_arcs(self, surface: pygame.Surface, stacks: int):
        """Draw cardinal plating arcs on the capture radius boundary."""
        arc_color = TEAM_COLORS.get(self.team, PLAYER_COLORS[0])
        arc_r = METAL_SPOT_CAPTURE_RADIUS
        rect = pygame.Rect(
            self.x - arc_r, self.y - arc_r,
            arc_r * 2, arc_r * 2,
        )
        arc_span = math.radians(87.5)
        half_span = arc_span / 2
        cardinal_angles = [
            math.radians(90),    # N
            math.radians(0),     # E
            math.radians(270),   # S
            math.radians(180),   # W
        ]
        for i in range(min(stacks, 4)):
            center = cardinal_angles[i]
            start = center - half_span
            end = center + half_span
            pygame.draw.arc(surface, arc_color, rect, start, end, 2)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "rotation": self.rotation,
            "rotation_speed": self.rotation_speed,
            "metal_spot_id": self.metal_spot.entity_id if self.metal_spot else None,
            "max_hp": self.max_hp,
            "abilities": [a.to_dict() for a in self.abilities],
            "upgrade_state": self.upgrade_state,
            "upgrade_timer": self.upgrade_timer,
            "researched_unit_type": self.researched_unit_type,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MetalExtractor:
        me = cls(team=data["team"], x=data["x"], y=data["y"],
                 player_id=data.get("player_id", data.get("team", 1)))
        me.entity_id = data["entity_id"]
        me.color = tuple(data["color"])
        me.selected = data["selected"]
        me.obstacle = data["obstacle"]
        me.alive = data["alive"]
        me.hp = data["hp"]
        me.max_hp = data.get("max_hp", me.max_hp)
        me.laser_cooldown = data.get("laser_cooldown", 0.0)
        me.facing_angle = data.get("facing_angle", 0.0)
        me.line_of_sight = data.get("line_of_sight", me.line_of_sight)
        me.fire_mode = data.get("fire_mode", me.fire_mode)
        me.selectable = data.get("selectable", False)
        me._bounds = tuple(data.get("_bounds", (800, 600)))
        me.target = tuple(data["target"]) if data.get("target") else None
        me._stop_dist = data.get("_stop_dist", 0.0)
        me._follow_dist = data.get("_follow_dist", 0.0)
        me._follow_entity = None
        me.attack_target = None
        me.rotation = data["rotation"]
        me.rotation_speed = data["rotation_speed"]
        # Restore abilities from save data, or keep defaults for old replays
        if "abilities" in data:
            me.abilities = [ability_from_dict(a) for a in data["abilities"]]
        # T2 upgrade state
        me.upgrade_state = data.get("upgrade_state", "base")
        me.upgrade_timer = data.get("upgrade_timer", 0.0)
        me.researched_unit_type = data.get("researched_unit_type")
        # Restore Outpost weapon if saved in that state
        if me.upgrade_state == "outpost":
            me._finish_outpost()
            # Restore HP from saved data (don't let _finish overwrite)
            me.hp = data["hp"]
            me.max_hp = data.get("max_hp", me.max_hp)
        elif me.upgrade_state == "research_lab":
            # HP already includes the bonus from when it was saved
            pass
        # cross-reference resolved later by Game.load_state()
        me.metal_spot = None
        return me
