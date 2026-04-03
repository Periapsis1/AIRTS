"""Server-side fog of war visibility system.

Computes per-team line-of-sight, filters entities for network broadcast,
and tracks ghost buildings (last-known positions of enemy structures).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GhostBuilding:
    """Snapshot of an enemy building last seen by a team."""
    entity_id: int
    x: float
    y: float
    unit_type: str          # "command_center" or "metal_extractor"
    team: int               # building's owning team (for color)
    color: tuple            # last-known _base_color
    radius: float
    points: list | None     # CC hexagon offsets (None for ME)


@dataclass
class TeamVisionState:
    """Per-team visibility snapshot, recomputed each broadcast tick."""
    team_id: int
    los_circles: list[tuple[int, int, int]] = field(default_factory=list)
    visible_entity_ids: set[int] = field(default_factory=set)
    building_ghosts: dict[int, GhostBuilding] = field(default_factory=dict)
    metal_spot_memory: dict[int, int | None] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# LOS helpers (mirrors Game._is_visible / _collect_los_circles logic)
# ---------------------------------------------------------------------------

def _is_visible(px: float, py: float,
                los_circles: list[tuple[int, int, int]]) -> bool:
    """Return True if point (px, py) falls inside any LOS circle."""
    for cx, cy, r in los_circles:
        dx = px - cx
        dy = py - cy
        if dx * dx + dy * dy <= r * r:
            return True
    return False


def collect_team_los(team_id: int, entities: list) -> list[tuple[int, int, int]]:
    """Gather (x, y, radius) LOS circles from all alive entities on *team_id*."""
    circles: list[tuple[int, int, int]] = []
    for e in entities:
        if not e.alive:
            continue
        if not hasattr(e, "line_of_sight") or not hasattr(e, "team"):
            continue
        if e.team != team_id:
            continue
        r = int(e.line_of_sight)
        if r > 0:
            circles.append((int(e.x), int(e.y), r))
    return circles


# ---------------------------------------------------------------------------
# Visibility computation
# ---------------------------------------------------------------------------

def compute_team_visibility(
    team_id: int,
    los_circles: list[tuple[int, int, int]],
    entities: list,
    metal_spots: list,
    prev_state: TeamVisionState | None = None,
) -> TeamVisionState:
    """Determine which entities are visible to *team_id* and update ghosts.

    Parameters
    ----------
    team_id : int
        The team whose vision we are computing.
    los_circles : list
        LOS circles for this team (from *collect_team_los*).
    entities : list
        All alive game entities (units, buildings, shapes).
    metal_spots : list
        All MetalSpot entities (always sent, but capture info gated by LOS).
    prev_state : TeamVisionState | None
        Previous tick's state (carries forward ghost data).  If *None* a
        fresh state is created.

    Returns
    -------
    TeamVisionState
        Updated vision state including visible IDs and ghosts.
    """
    state = TeamVisionState(team_id=team_id)

    # Carry forward persistent ghost data from previous state
    if prev_state is not None:
        state.building_ghosts = dict(prev_state.building_ghosts)
        state.metal_spot_memory = dict(prev_state.metal_spot_memory)

    state.los_circles = los_circles

    # --- Classify entities ---------------------------------------------------
    from entities.command_center import CommandCenter
    from entities.metal_extractor import MetalExtractor
    from entities.metal_spot import MetalSpot as MetalSpotClass

    for e in entities:
        if not e.alive:
            continue

        # Skip entities without a team (map geometry, etc.)
        if not hasattr(e, "team"):
            # MetalSpots: mark as visible when in LOS (so broadcast sends
            # full capture data); those not in LOS are sent with stripped
            # capture info by broadcast_state separately.
            if isinstance(e, MetalSpotClass):
                if _is_visible(e.x, e.y, los_circles):
                    state.visible_entity_ids.add(e.entity_id)
                continue
            state.visible_entity_ids.add(e.entity_id)
            continue

        is_own_team = e.team == team_id
        is_building = isinstance(e, (CommandCenter, MetalExtractor))

        if is_own_team:
            # Own-team entities are always visible
            state.visible_entity_ids.add(e.entity_id)
            # Also snapshot own buildings for completeness (not really needed)
            continue

        # Enemy entity — check LOS
        if _is_visible(e.x, e.y, los_circles):
            state.visible_entity_ids.add(e.entity_id)
            # Update ghost snapshot while building is visible
            if is_building:
                state.building_ghosts[e.entity_id] = GhostBuilding(
                    entity_id=e.entity_id,
                    x=e.x,
                    y=e.y,
                    unit_type=e.unit_type,
                    team=e.team,
                    color=tuple(e._base_color),
                    radius=e.radius,
                    points=list(e.points) if hasattr(e, "points") else None,
                )
        else:
            # Not visible — if it's a building with a ghost, the ghost persists
            # (ghost data already carried forward from prev_state above).
            # If the building was destroyed while ghosted, we clean up below.
            if is_building and e.entity_id in state.building_ghosts:
                # Ghost persists (no action needed, already in dict)
                pass

    # --- Clean up ghosts for destroyed buildings -----------------------------
    alive_ids = {e.entity_id for e in entities if e.alive}
    ghost_ids_to_check = list(state.building_ghosts.keys())
    for gid in ghost_ids_to_check:
        ghost = state.building_ghosts[gid]
        if gid not in alive_ids:
            # Building is dead.  If the ghost position is currently in LOS,
            # the team can see it's gone — remove the ghost.
            if _is_visible(ghost.x, ghost.y, los_circles):
                del state.building_ghosts[gid]
            # If NOT in LOS, ghost persists until re-scouted.

    # --- MetalSpot memory (capture progress / owner gating) ------------------
    for ms in metal_spots:
        if _is_visible(ms.x, ms.y, los_circles):
            # Update last-known owner
            state.metal_spot_memory[ms.entity_id] = ms.owner
        # else: keep stale value (or None if never scouted)

    return state


# ---------------------------------------------------------------------------
# Visible-enemies helper (for targeting / AI)
# ---------------------------------------------------------------------------

def get_visible_enemy_ids(
    team_id: int,
    los_circles: list[tuple[int, int, int]],
    alive_units: list,
) -> set[int]:
    """Return entity_ids of enemy units visible to *team_id*.

    This is used by the targeting system and AI to restrict which enemies
    can be acquired as targets.
    """
    vis: set[int] = set()
    for u in alive_units:
        if u.team == team_id:
            continue
        if _is_visible(u.x, u.y, los_circles):
            vis.add(u.entity_id)
    return vis
