"""Data-driven unit type definitions.

To add a new unit type, add an entry to UNIT_TYPES.  Every entry must include
the base keys (hp, speed, radius, symbol, can_attack).  Combat stats live under
the ``weapon`` sub-dict and are used to construct a ``Weapon`` dataclass at
unit creation time.

Symbols are tuples of (x, y) offsets assuming a 16-px reference radius.
They are scaled at draw-time to the unit's actual radius.
"""

# -- symbols (reference radius = 16) ----------------------------------------

MEDIC_SYMBOL = (
    (-4, -12), (4, -12), (4, -4), (12, -4), (12, 4), (4, 4),
    (4, 12), (-4, 12), (-4, 4), (-12, 4), (-12, -4), (-4, -4),
)

TANK_SYMBOL = (
    (-4, -12), (4, -12), (12, -4), (12, 4),
    (4, 12), (-4, 12), (-12, 4), (-12, -4),
)

SNIPER_SYMBOL = (
    (-4, -12), (0, -4), (4, -12), (12, -4), (4, 0), (12, 4),
    (4, 12), (0, 4), (-4, 12), (-12, 4), (-4, 0), (-12, -4),
)

MACHINE_GUNNER_SYMBOL = (
    (-10, -10), (10, -10), (10, 10), (-10, 10),
)

SHOCKWAVE_SYMBOL = (
    (0, -12), (12, 0), (0, 12), (-12, 0),
)

SCOUT_SYMBOL = (
    (0, -12), (8, 4), (-8, 4),
)

# -- type registry -----------------------------------------------------------

UNIT_TYPES = {
    "soldier": {
        "hp": 100, "speed": 40, "radius": 5,
        "symbol": None, "can_attack": True,
        "fov": 90, "turn_rate": 180, "los": 100,
        "weapon": {"name": "Laser", "damage": 10, "range": 50, "cooldown": 1.5},
    },
    "medic": {
        "hp": 50, "speed": 40, "radius": 5,
        "symbol": MEDIC_SYMBOL, "can_attack": True,
        "fov": 30, "turn_rate": 180, "los": 80,
        "weapon": {
            "name": "HealLaser", "damage": -1, "range": 50, "cooldown": 0.3,
            "hits_only_friendly": True,
        },
    },
    "tank": {
        "hp": 250, "speed": 20, "radius": 7,
        "symbol": TANK_SYMBOL, "can_attack": True,
        "fov": 150, "turn_rate": 180, "los": 100,
        "weapon": {"name": "Laser", "damage": 7, "range": 50, "cooldown": 2.0},
    },
    "sniper": {
        "hp": 50, "speed": 30, "radius": 5,
        "symbol": SNIPER_SYMBOL, "can_attack": True,
        "fov": 45, "turn_rate": 180, "los": 200,
        "weapon": {"name": "Heavy Laser", "damage": 35, "range": 140, "cooldown": 6.0,
                   "laser_width": 3, "sound": "laser"},
    },
    "machine_gunner": {
        "hp": 70, "speed": 40, "radius": 5,
        "symbol": MACHINE_GUNNER_SYMBOL, "can_attack": True,
        "fov": 180, "turn_rate": 180, "los": 100,
        "weapon": {"name": "Laser", "damage": 1, "range": 50, "cooldown": 0.1},
    },
    "scout": {
        "hp": 15, "speed": 90, "radius": 4,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
        "fov": 180, "turn_rate": 180, "los": 150,
        "spawn_count": 3,
        "weapon": {"name": "Laser", "damage": 4, "range": 15, "cooldown": 0.5},
    },
    "shockwave": {
        "hp": 70, "speed": 30, "radius": 5,
        "symbol": SHOCKWAVE_SYMBOL, "can_attack": True,
        "fov": 360, "turn_rate": 180, "los": 100,
        "weapon": {
            "name": "ChainLaser", "damage": 5, "range": 60, "cooldown": 3.0,
            "chain_range": 70.0, "chain_delay": 0.2,
        },
    },
    "command_center": {
        "hp": 1000, "speed": 0, "radius": 10,
        "symbol": None, "can_attack": True,
        "fov": 360, "turn_rate": 180, "los": 200,
        "is_building": True,
    },
    "metal_extractor": {
        "hp": 150, "speed": 0, "radius": 5,
        "symbol": None, "can_attack": False,
        "fov": 360, "turn_rate": 0, "los": 50,
        "is_building": True,
    },
}


def get_spawnable_types() -> dict:
    """Return only unit types that can be spawned (excludes buildings)."""
    return {k: v for k, v in UNIT_TYPES.items() if not v.get("is_building", False)}
