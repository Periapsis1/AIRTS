"""Unit spawning from command centers."""
from __future__ import annotations
from entities.base import Entity
from entities.command_center import CommandCenter
from config.unit_types import UNIT_TYPES


def spawn_step(
    entities: list[Entity],
    command_centers: list[CommandCenter],
    human_teams: set[int],
    stats=None,
    tick: int = 0,
):
    """Spawn units from any command center whose timer is ready.

    Newly spawned units belonging to a human team get ``selectable = True``.
    Unit types with ``spawn_count`` produce multiple units per spawn cycle.
    """
    for cc in command_centers:
        if not cc.alive or not cc.spawn_ready():
            continue
        type_def = UNIT_TYPES.get(cc.spawn_type, {})
        count = type_def.get("spawn_count", 1)
        for _ in range(count):
            u = cc.spawn_unit()
            u.selectable = u.team in human_teams
            entities.append(u)
            if stats is not None:
                stats.record_spawn(u.team, u.unit_type, tick)
        cc.reset_spawn()
