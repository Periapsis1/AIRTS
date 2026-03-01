"""Selection system: circle-drag and click-to-select."""
from __future__ import annotations
import math
from entities.base import Entity
from entities.command_center import CommandCenter
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
    for entity in entities:
        if not getattr(entity, "selectable", False):
            continue
        ex, ey = entity.center()
        er = entity.collision_radius()
        d = math.hypot(ex - mx, ey - my)
        if d <= er and d < best_dist:
            best_dist = d
            best = entity
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

    entities_to_select = []
    cc = None
    for entity in entities:
        selectable = getattr(entity, "selectable", False)
        
        if selectable and isinstance(entity, CommandCenter):
            cc = entity
        elif selectable and entity_in_circle(entity, cx, cy, sr):
            entities_to_select.append(entity)

    # only select the command center if no other entities are selected
    if cc is not None and len(entities_to_select) == 0:
        cc.set_selected(True)
    else:  # select the entities inside the circle
        for entity in entities_to_select:
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
