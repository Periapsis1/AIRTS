"""Serializable command system for multiplayer-ready input routing."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GameCommand:
    """A single player action that can be serialized and replayed."""

    type: str          # "move", "attack", "stop", "set_rally", "set_spawn_type"
    team: int          # issuing team
    tick: int          # game tick when issued
    data: dict[str, Any] = field(default_factory=dict)

    def serialize(self) -> str:
        return json.dumps({
            "type": self.type,
            "team": self.team,
            "tick": self.tick,
            "data": self.data,
        })

    @staticmethod
    def deserialize(raw: str) -> GameCommand:
        d = json.loads(raw)
        return GameCommand(
            type=d["type"],
            team=d["team"],
            tick=d["tick"],
            data=d["data"],
        )


class CommandQueue:
    """Collects commands and drains them per-tick for execution."""

    def __init__(self):
        self._pending: list[GameCommand] = []

    def enqueue(self, cmd: GameCommand) -> None:
        self._pending.append(cmd)

    def drain(self, tick: int) -> list[GameCommand]:
        """Return and remove all commands for *tick* (or earlier)."""
        ready = [c for c in self._pending if c.tick <= tick]
        self._pending = [c for c in self._pending if c.tick > tick]
        return ready
