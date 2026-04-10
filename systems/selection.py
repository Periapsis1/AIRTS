"""Selection system: circle-drag, rectangle-drag, and click-to-select."""
from __future__ import annotations
import math
from entities.base import Entity
from entities.unit import Unit


def entity_in_rect(
    entity: Entity,
    x1: float, y1: float, x2: float, y2: float,
) -> bool:
    """Check if an entity's circle overlaps an axis-aligned rectangle."""
    ex, ey = entity.center()
    er = entity.collision_radius()
    rx = min(x1, x2)
    ry = min(y1, y2)
    rw = abs(x2 - x1)
    rh = abs(y2 - y1)
    # Closest point on rect to circle center
    closest_x = max(rx, min(ex, rx + rw))
    closest_y = max(ry, min(ey, ry + rh))
    return math.hypot(ex - closest_x, ey - closest_y) <= er


def apply_rect_selection(
    entities: list[Entity],
    x1: float, y1: float, x2: float, y2: float,
    additive: bool,
    own_player_ids: set[int] | None = None,
):
    """Select entities within an axis-aligned rectangle.

    If *own_player_ids* is given and any matching army unit is inside,
    only own units are selected.
    """
    if not additive:
        _deselect_all(entities)

    army_units: list[Entity] = []
    own_army: list[Entity] = []
    buildings: list[Entity] = []
    for entity in entities:
        if not getattr(entity, "selectable", False):
            continue
        if not entity_in_rect(entity, x1, y1, x2, y2):
            continue
        if getattr(entity, "is_building", False):
            buildings.append(entity)
        else:
            army_units.append(entity)
            if own_player_ids and hasattr(entity, "player_id"):
                if entity.player_id in own_player_ids:
                    own_army.append(entity)

    # Prefer own army > all army > buildings
    if own_army:
        targets = own_army
    elif army_units:
        targets = army_units
    else:
        targets = buildings

    for entity in targets:
        entity.set_selected(True)


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
    own_player_ids: set[int] | None = None,
):
    if not additive:
        _deselect_all(entities)

    army_units: list[Entity] = []
    own_army: list[Entity] = []
    buildings: list[Entity] = []
    for entity in entities:
        if not getattr(entity, "selectable", False):
            continue
        if not entity_in_circle(entity, cx, cy, sr):
            continue
        if getattr(entity, "is_building", False):
            buildings.append(entity)
        else:
            army_units.append(entity)
            if own_player_ids and hasattr(entity, "player_id"):
                if entity.player_id in own_player_ids:
                    own_army.append(entity)

    # Prefer own army > all army > buildings
    if own_army:
        targets = own_army
    elif army_units:
        targets = army_units
    else:
        targets = buildings
    for entity in targets:
        entity.set_selected(True)


def select_all_of_type(entities: list[Entity], mx: float, my: float,
                       viewport_rect=None):
    """Double-click: select all units of the same type as the one under cursor.

    If *viewport_rect* is supplied (a pygame.Rect in world coordinates),
    only units within the visible camera view are selected.
    """
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
            if viewport_rect is not None:
                ex, ey = entity.center()
                if not viewport_rect.collidepoint(ex, ey):
                    continue
            entity.set_selected(True)


def _deselect_all(entities: list[Entity]):
    for entity in entities:
        if getattr(entity, "selectable", False):
            entity.set_selected(False)
