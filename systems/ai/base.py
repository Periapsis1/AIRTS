"""
Base AI controller.

Subclass and override ``on_start`` / ``on_step`` to implement custom behavior.
Use the built-in helper methods to query world state and issue unit commands.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from entities.base import Entity
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from config.unit_types import UNIT_TYPES


class BaseAI(ABC):
    """
    Interface for team AI controllers.

    The Game calls ``_bind()`` once, then ``on_start()`` once, then
    ``on_step(iteration)`` every frame.
    """

    def __init__(self):
        self._team: int = 0
        self._game = None  # set by Game._bind_ai — avoids circular import

    # -- lifecycle (called by Game) -----------------------------------------

    def _bind(self, team: int, game):
        self._team = team
        self._game = game

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
    def bounds(self) -> tuple[int, int]:
        return (self._game.width, self._game.height)

    def get_entities(self) -> set[Entity]:
        return set(self._entities)

    def get_units(self) -> set[Unit]:
        return {e for e in self._entities if isinstance(e, Unit) and e.alive}

    def get_own_units(self) -> set[Unit]:
        return {e for e in self._entities
                if isinstance(e, Unit) and e.alive and e.team == self._team}

    def get_enemy_units(self) -> set[Unit]:
        return {e for e in self._entities
                if isinstance(e, Unit) and e.alive and e.team != self._team}

    def get_obstacles(self) -> set[Entity]:
        return {e for e in self._entities if e.obstacle}

    def get_metal_spots(self) -> set[MetalSpot]:
        return {e for e in self._entities if isinstance(e, MetalSpot)}

    def get_metal_extractors(self) -> set[MetalExtractor]:
        return {e for e in self._entities
                if isinstance(e, MetalExtractor) and e.alive}

    def get_own_metal_extractors(self) -> set[MetalExtractor]:
        return {e for e in self._entities
                if isinstance(e, MetalExtractor) and e.alive and e.team == self._team}

    def get_cc(self) -> CommandCenter | None:
        for e in self._entities:
            if isinstance(e, CommandCenter) and e.alive and e.team == self._team:
                return e
        return None

    # -- build control ------------------------------------------------------

    def set_build(self, unit_type: str):
        if unit_type not in UNIT_TYPES:
            raise ValueError(f"Unknown unit type: {unit_type!r}")
        cc = self.get_cc()
        if cc is not None:
            cc.spawn_type = unit_type
