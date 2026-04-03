"""
Base AI controller.

Subclass and override ``on_start`` / ``on_step`` to implement custom behavior.
Use the built-in helper methods to query world state and issue unit commands.
"""
from __future__ import annotations
import math
from abc import ABC, abstractmethod
from entities.base import Entity
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from config.unit_types import UNIT_TYPES, get_spawnable_types
from systems.commands import GameCommand


class BaseAI(ABC):
    """
    Interface for team AI controllers.

    The Game calls ``_bind()`` once, then ``on_start()`` once, then
    ``on_step(iteration)`` every frame.

    Subclasses should set ``ai_id`` (unique slug) and ``ai_name``
    (human-readable) as class attributes so the AI registry can
    discover and display them.
    """

    ai_id: str = ""
    ai_name: str = ""

    def __init__(self):
        self._player_id: int = 0
        self._team: int = 0
        self._game = None  # set by Game._bind_ai — avoids circular import
        self._stats = None  # set by Game via _bind()
        self._command_queue = None  # set by Game via _bind()

    # -- lifecycle (called by Game) -----------------------------------------

    def _bind(self, player_id: int, team_id: int, game, stats=None, command_queue=None):
        self._player_id = player_id
        self._team = team_id
        self._game = game
        self._stats = stats
        self._command_queue = command_queue

    @abstractmethod
    def on_start(self) -> None:
        """Called once after the world is generated but before the first step."""
        ...

    @abstractmethod
    def on_step(self, iteration: int) -> None:
        """Called every frame with the current iteration count (0-based)."""
        ...

    # -- world queries ------------------------------------------------------

    @property
    def _entities(self) -> list[Entity]:
        return self._game.entities

    @property
    def _units(self) -> list[Unit]:
        return self._game.units

    @property
    def bounds(self) -> tuple[int, int]:
        return (self._game.width, self._game.height)

    def get_entities(self) -> list[Entity]:
        return sorted(
            [e for e in self._entities],
            key=lambda e: e.entity_id,
        )

    def get_units(self) -> list[Unit]:
        return sorted(
            [u for u in self._units if u.alive],
            key=lambda u: u.entity_id,
        )

    def get_own_units(self) -> list[Unit]:
        return sorted(
            [u for u in self._units if u.alive and u.player_id == self._player_id],
            key=lambda u: u.entity_id,
        )

    def get_ally_units(self) -> list[Unit]:
        """Return living units on the same alliance team but controlled by a different player."""
        return sorted(
            [u for u in self._units if u.alive and u.team == self._team
             and u.player_id != self._player_id],
            key=lambda u: u.entity_id,
        )

    @property
    def _fog_visible_ids(self) -> set[int] | None:
        """Visible enemy entity IDs for this team, or *None* when fog is off."""
        if not self._game._fog_of_war:
            return None
        return self._game._visible_enemies_per_team.get(self._team, set())

    def get_enemy_units(self) -> list[Unit]:
        vis = self._fog_visible_ids
        return sorted(
            [u for u in self._units if u.alive and u.team != self._team
             and (vis is None or u.entity_id in vis)],
            key=lambda u: u.entity_id,
        )

    def get_enemy_ccs(self) -> list[CommandCenter]:
        """Return living command centers belonging to other teams (fog-filtered)."""
        vis = self._fog_visible_ids
        return [e for e in self._entities
                if isinstance(e, CommandCenter) and e.alive and e.team != self._team
                and (vis is None or e.entity_id in vis)]

    def get_enemy_direction(self) -> tuple[float, float]:
        """Unit vector from own CC toward average enemy CC position.

        Uses visible enemy CCs; falls back to ghost CC positions when fog
        hides all enemy CCs so the AI still has a rough heading.
        """
        cc = self.get_cc()
        if cc is None:
            return (1.0, 0.0)
        enemy_ccs = self.get_enemy_ccs()
        if not enemy_ccs:
            # Fall back to ghost building positions if fog hides all enemy CCs
            if self._game._fog_of_war:
                vis_state = self._game._team_vision.get(self._team)
                if vis_state:
                    ghost_ccs = [g for g in vis_state.building_ghosts.values()
                                 if g.unit_type == "command_center"]
                    if ghost_ccs:
                        avg_x = sum(g.x for g in ghost_ccs) / len(ghost_ccs)
                        avg_y = sum(g.y for g in ghost_ccs) / len(ghost_ccs)
                        dx, dy = avg_x - cc.x, avg_y - cc.y
                        dist = math.hypot(dx, dy) or 1.0
                        return (dx / dist, dy / dist)
            return (1.0, 0.0)
        avg_x = sum(ec.x for ec in enemy_ccs) / len(enemy_ccs)
        avg_y = sum(ec.y for ec in enemy_ccs) / len(enemy_ccs)
        dx, dy = avg_x - cc.x, avg_y - cc.y
        dist = math.hypot(dx, dy) or 1.0
        return (dx / dist, dy / dist)

    def is_on_own_side(self, entity) -> bool:
        """True if entity is closer to own CC than to any enemy CC."""
        cc = self.get_cc()
        if cc is None:
            return True
        own_dist_sq = (entity.x - cc.x) ** 2 + (entity.y - cc.y) ** 2
        for ec in self.get_enemy_ccs():
            if (entity.x - ec.x) ** 2 + (entity.y - ec.y) ** 2 < own_dist_sq:
                return False
        return True

    def get_mobile_units(self) -> list[Unit]:
        return sorted(
            [u for u in self._units if u.alive and not u.is_building],
            key=lambda u: u.entity_id,
        )

    def get_own_mobile_units(self) -> list[Unit]:
        return sorted(
            [u for u in self._units if u.alive and u.player_id == self._player_id
             and not u.is_building],
            key=lambda u: u.entity_id,
        )

    def get_obstacles(self) -> list[Entity]:
        return sorted(
            [e for e in self._entities if e.obstacle],
            key=lambda e: e.entity_id,
        )

    def get_metal_spots(self) -> list[MetalSpot]:
        return sorted(
            [e for e in self._entities if isinstance(e, MetalSpot)],
            key=lambda e: e.entity_id,
        )

    def get_metal_extractors(self) -> list[MetalExtractor]:
        vis = self._fog_visible_ids
        return sorted(
            [e for e in self._entities if isinstance(e, MetalExtractor) and e.alive
             and (e.team == self._team or vis is None or e.entity_id in vis)],
            key=lambda e: e.entity_id,
        )

    def get_own_metal_extractors(self) -> list[MetalExtractor]:
        return sorted(
            [e for e in self._entities if isinstance(e, MetalExtractor) and e.alive and e.team == self._team],
            key=lambda e: e.entity_id,
        )

    def get_cc(self) -> CommandCenter | None:
        for e in self._entities:
            if isinstance(e, CommandCenter) and e.alive and e.player_id == self._player_id:
                return e
        return None

    # -- action tracking ----------------------------------------------------

    def _record_action(self):
        if self._stats is not None:
            self._stats.record_action(self._team)

    def move_unit(self, unit, x: float, y: float):
        tick = self._game._iteration if self._game else 0
        self._command_queue.enqueue(GameCommand(
            type="move",
            player_id=self._player_id,
            tick=tick,
            data={"unit_ids": [unit.entity_id], "targets": [(x, y)]},
        ))
        self._record_action()

    def attack_unit(self, unit, target):
        tick = self._game._iteration if self._game else 0
        self._command_queue.enqueue(GameCommand(
            type="attack",
            player_id=self._player_id,
            tick=tick,
            data={"unit_id": unit.entity_id, "target_id": target.entity_id},
        ))
        self._record_action()

    def stop(self, unit_ids: list[int]):
        tick = self._game._iteration if self._game else 0
        self._command_queue.enqueue(GameCommand(
            type="stop",
            player_id=self._player_id,
            tick=tick,
            data={"unit_ids": unit_ids},
        ))
        self._record_action()

    def set_rally(self, cc_id: int, pos: tuple[float, float]):
        tick = self._game._iteration if self._game else 0
        self._command_queue.enqueue(GameCommand(
            type="set_rally",
            player_id=self._player_id,
            tick=tick,
            data={"position": list(pos)},
        ))
        self._record_action()

    # -- build control ------------------------------------------------------

    def set_build(self, unit_type: str):
        if unit_type not in get_spawnable_types():
            raise ValueError(f"Unknown or non-spawnable unit type: {unit_type!r}")
        cc = self.get_cc()
        if cc is not None:
            tick = self._game._iteration if self._game else 0
            self._command_queue.enqueue(GameCommand(
                type="set_spawn_type",
                player_id=self._player_id,
                tick=tick,
                data={"unit_type": unit_type},
            ))
            self._record_action()
