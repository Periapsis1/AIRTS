"""Unit spawning from command centers."""
from __future__ import annotations
from entities.base import Entity
from entities.command_center import CommandCenter


def spawn_step(
    entities: list[Entity],
    command_centers: list[CommandCenter],
    human_teams: set[int],
):
    """Spawn units from any command center whose timer is ready.

    Newly spawned units belonging to a human team get ``selectable = True``.
    """
    for cc in command_centers:
        if not cc.alive or not cc.spawn_ready():
            continue
        u = cc.spawn_unit()
        u.selectable = u.team in human_teams
        entities.append(u)
        cc.reset_spawn()
