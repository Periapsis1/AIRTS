"""Selection system: circle-drag and click-to-select."""
from __future__ import annotations
import math
from entities.base import Entity
from entities.unit import Unit


def entity_in_circle(
    entity: Entity,
    cx: float, cy: float, sr: float,
) -> bool:
    ex, ey = entity.center()
    er = entity.collision_radius()
    return math.hypot(ex - cx, ey - cy) <= sr + er


def click_select(
    entities: list[Entity],
    mx: float, my: float,
    additive: bool,
):
    best: Entity | None = None
    best_dist = float("inf")
    best_is_building = True
    for entity in entities:
        if not getattr(entity, "selectable", False):
            continue
        ex, ey = entity.center()
        er = entity.collision_radius()
        d = math.hypot(ex - mx, ey - my)
        if d > er:
            continue
        is_building = getattr(entity, "is_building", False)
        # Army units always take priority over buildings
        if best is None:
            best = entity
            best_dist = d
            best_is_building = is_building
        elif not is_building and best_is_building:
            # current is army, best was building → replace
            best = entity
            best_dist = d
            best_is_building = False
        elif is_building and not best_is_building:
            # current is building, best is army → skip
            pass
        elif d < best_dist:
            # same category, closer wins
            best = entity
            best_dist = d
    if not additive:
        _deselect_all(entities)
    if best is not None:
        best.set_selected(True)


def apply_circle_selection(
    entities: list[Entity],
    cx: float, cy: float, sr: float,
    additive: bool,
):
    if not additive:
        _deselect_all(entities)

    army_units = []
    buildings = []
    for entity in entities:
        if not getattr(entity, "selectable", False):
            continue
        if not entity_in_circle(entity, cx, cy, sr):
            continue
        if getattr(entity, "is_building", False):
            buildings.append(entity)
        else:
            army_units.append(entity)

    # Army units take priority; fall back to buildings if none
    targets = army_units if army_units else buildings
    for entity in targets:
        entity.set_selected(True)


def select_all_of_type(entities: list[Entity], mx: float, my: float):
    """Double-click: select all units of the same type as the one under cursor."""
    # Find the unit under the cursor
    best: Unit | None = None
    best_dist = float("inf")
    for entity in entities:
        if not isinstance(entity, Unit) or not getattr(entity, "selectable", False):
            continue
        ex, ey = entity.center()
        er = entity.collision_radius()
        d = math.hypot(ex - mx, ey - my)
        if d <= er and d < best_dist:
            best_dist = d
            best = entity
    if best is None:
        return
    _deselect_all(entities)
    target_type = best.unit_type
    target_team = best.team
    for entity in entities:
        if (isinstance(entity, Unit)
                and getattr(entity, "selectable", False)
                and entity.unit_type == target_type
                and entity.team == target_team):
            entity.set_selected(True)


def _deselect_all(entities: list[Entity]):
    for entity in entities:
        if getattr(entity, "selectable", False):
            entity.set_selected(False)
