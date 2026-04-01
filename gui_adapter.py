"""Adapter that converts visual state dicts into proxy objects for gui.py.

gui.py was written against real entity objects (CommandCenter, MetalExtractor, Unit).
This module wraps the compact visual dicts sent over the network into proxy objects
that expose the same attributes gui.py reads, so ClientGameScreen can reuse the HUD.
"""
from __future__ import annotations

from types import SimpleNamespace
from config.unit_types import UNIT_TYPES


class _EntityProxy(SimpleNamespace):
    """Lightweight proxy that quacks like an entity for gui.py."""
    _is_command_center: bool = False
    _is_metal_extractor: bool = False
    _is_metal_spot: bool = False
    _is_unit: bool = False


def _make_proxy(d: dict, selected_ids: set[int]) -> _EntityProxy:
    """Convert a single visual dict to a proxy object."""
    t = d.get("t", "")
    ut = d.get("ut", "")
    eid = d.get("id", 0)
    mhp = d.get("mhp", 0)
    if mhp == 0:
        # Fallback: look up from UNIT_TYPES
        stats = UNIT_TYPES.get(ut, {})
        mhp = stats.get("hp", 100)

    p = _EntityProxy(
        entity_id=eid,
        unit_type=ut,
        x=d.get("x", 0),
        y=d.get("y", 0),
        hp=d.get("hp", 0),
        max_hp=mhp,
        team=d.get("tm", 0),
        player_id=d.get("pid", d.get("tm", 0)),
        radius=d.get("r", 5),
        color=tuple(d.get("c", [200, 200, 200])),
        _base_color=tuple(d.get("c", [200, 200, 200])),
        selected=eid in selected_ids,
        selectable=True,
        is_building=(t in ("CC", "ME")),
        speed=UNIT_TYPES.get(ut, {}).get("speed", 0),
        alive=True,
        facing_angle=d.get("fa", 0.0),
        is_t2=d.get("t2", False),
        abilities=[],  # populated below from "abs" field
    )

    # Build ability proxies from serialized ability data
    for ab in d.get("abs", []):
        ab_proxy = SimpleNamespace(
            name=ab.get("n", ""),
            active=ab.get("a", False),
        )
        if "s" in ab:
            ab_proxy.stacks = ab["s"]
            ab_proxy.max_stacks = ab.get("ms", 0)
        if "tm" in ab:
            ab_proxy.timer = ab["tm"]
        p.abilities.append(ab_proxy)

    # Weapon proxy
    wpn_data = UNIT_TYPES.get(ut, {}).get("weapon")
    if wpn_data:
        p.weapon = SimpleNamespace(
            name=wpn_data.get("name", ""),
            damage=wpn_data.get("damage", 0),
            range=wpn_data.get("range", 0),
            cooldown=wpn_data.get("cooldown", 0),
            charge_time=wpn_data.get("charge_time", 0),
        )
    else:
        p.weapon = None

    if t == "CC":
        p._is_command_center = True
        p._is_unit = True
        p.points = [tuple(pt) for pt in d.get("pts", [])]
        p.spawn_type = d.get("st", "soldier")
        p._spawn_timer = d.get("spt", 0.0) * 10.0  # denormalize: spt is 0-1, CC_SPAWN_INTERVAL=10
        p.metal_extractors = []  # bonus is pre-computed
        p._bonus_percent = d.get("bp", 0)

        def get_total_bonus_percent(self=p):
            return self._bonus_percent
        p.get_total_bonus_percent = get_total_bonus_percent

    elif t == "ME":
        p._is_metal_extractor = True
        p._is_unit = True
        p.rotation = d.get("rot", 0.0)
        p.upgrade_state = d.get("us", "base")
        p.upgrade_timer = 0.0
        utt = d.get("utt", 0.0)
        if p.upgrade_state.startswith("upgrading") and utt < 1.0:
            from config.settings import WATCH_TOWER_UPGRADE_DURATION, RESEARCH_LAB_UPGRADE_DURATION
            _dur = WATCH_TOWER_UPGRADE_DURATION if p.upgrade_state == "upgrading_tower" else RESEARCH_LAB_UPGRADE_DURATION
            p.upgrade_timer = (1.0 - utt) * _dur
        p.researched_unit_type = d.get("rut", "") or None
        p.is_fully_reinforced = d.get("ifr", False)
        _meb = d.get("meb", 0)

        if p.upgrade_state == "watch_tower":
            from config.settings import (WATCH_TOWER_LASER_DAMAGE,
                                         WATCH_TOWER_LASER_RANGE,
                                         WATCH_TOWER_LASER_COOLDOWN)
            p.weapon = SimpleNamespace(
                name="Laser",
                damage=WATCH_TOWER_LASER_DAMAGE,
                range=WATCH_TOWER_LASER_RANGE,
                cooldown=WATCH_TOWER_LASER_COOLDOWN,
                charge_time=0,
            )

        def get_spawn_bonus(self=p, _b=_meb):
            return _b / 100.0
        p.get_spawn_bonus = get_spawn_bonus

    elif t == "MS":
        p._is_metal_spot = True
        p.owner = d.get("ow")

    elif t == "U":
        p._is_unit = True

    return p


def wrap_entities(
    visual_dicts: list[dict],
    selected_ids: set[int],
) -> list[_EntityProxy]:
    """Convert a list of visual dicts to proxy objects usable by gui.py."""
    return [_make_proxy(d, selected_ids) for d in visual_dicts]
