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

ARTILLERY_SYMBOL = (
    (0, -12),
    (4.755, -3.881),
    (11.417, -3.804),
    (6.18, 1.902),
    (7.608, 9.511),
    (0, 5),
    (-7.608, 9.511),
    (-6.18, 1.902),
    (-11.417, -3.804),
    (-4.755, -3.881),
)

# -- type registry -----------------------------------------------------------

UNIT_TYPES = {
    "soldier": {
        "hp": 100, "speed": 40, "radius": 5,
        "symbol": None, "can_attack": True,
        "fov": 90, "turn_rate": 90, "los": 90,
        "weapon": {"name": "Laser", "damage": 10, "range": 50, "cooldown": 1.5},
    },
    "medic": {
        "hp": 50, "speed": 40, "radius": 5,
        "symbol": MEDIC_SYMBOL, "can_attack": True,
        "fov": 30, "turn_rate": 90, "los": 80,
        "weapon": {
            "name": "HealLaser", "damage": -1, "range": 50, "cooldown": 0.3,
            "hits_only_friendly": True,
        },
    },
    "tank": {
        "hp": 250, "speed": 20, "radius": 7,
        "symbol": TANK_SYMBOL, "can_attack": True,
        "fov": 150, "turn_rate": 50, "los": 60,
        "weapon": {"name": "Laser", "damage": 8, "range": 45, "cooldown": 2.0},
    },
    "sniper": {
        "hp": 50, "speed": 30, "radius": 5,
        "symbol": SNIPER_SYMBOL, "can_attack": True,
        "fov": 45, "turn_rate": 90, "los": 125,
        "weapon": {"name": "Heavy Laser", "damage": 35, "range": 140, "cooldown": 6.0,
                   "laser_width": 3, "sound": "laser"},
    },
    "machine_gunner": {
        "hp": 70, "speed": 40, "radius": 5,
        "symbol": MACHINE_GUNNER_SYMBOL, "can_attack": True,
        "fov": 180, "turn_rate": 25, "los": 90,
        "weapon": {"name": "Laser", "damage": 4, "range": 50, "cooldown": 0.4, "laser_flash_duration": 0.1},
    },
    "scout": {
        "hp": 15, "speed": 90, "radius": 4,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
        "fov": 40, "turn_rate": 120, "los": 120,
        "spawn_count": 3,
        "weapon": {"name": "Laser", "damage": 3, "range": 40, "cooldown": 0.5,
                   "laser_flash_duration": 0.1},
    },
    "shockwave": {
        "hp": 70, "speed": 30, "radius": 5,
        "symbol": SHOCKWAVE_SYMBOL, "can_attack": True,
        "fov": 360, "turn_rate": 180, "los": 80,
        "weapon": {
            "name": "ChainLaser", "damage": 8, "range": 60, "cooldown": 3.5,
            "chain_range": 60.0, "chain_delay": 0.15,
            "laser_flash_duration": 0.5,
        },
    },
    "artillery": {
        "hp": 50, "speed": 20, "radius": 7,
        "symbol": ARTILLERY_SYMBOL, "can_attack": True,
        "fov": 15, "turn_rate": 10, "los": 150,
        "weapon": {
            "name": "ArtilleryCannon", "damage": 50, "range": 160, "cooldown": 6.0,
            "splash_radius": 40, "splash_damage_max": 40, "splash_damage_min": 1,
            "charge_time": 2.5,
            "friendly_fire": True,
            "sound": "artillery",
            "laser_width": 6,
            "laser_flash_duration": 2.5,
        }
    },
    "command_center": {
        "hp": 1000, "speed": 0, "radius": 10,
        "symbol": None, "can_attack": True,
        "fov": 360, "turn_rate": 180, "los": 200,
        "is_building": True,
        "weapon": {"name": "Laser", "damage": 15, "range": 80, "cooldown": 1.5},
    },
    "metal_extractor": {
        "hp": 150, "speed": 0, "radius": 5,
        "symbol": None, "can_attack": False,
        "fov": 360, "turn_rate": 0, "los": 50,
        "is_building": True,
    },

    # -- T2 unit types --------------------------------------------------------
    # Full definitions — edit these directly to differentiate T2 from T1.
    "soldier_t2": {
        "hp": 125, "speed": 40, "radius": 6,
        "symbol": None, "can_attack": True,
        "fov": 90, "turn_rate": 90, "los": 100,
        "weapon": {"name": "Laser", "damage": 12, "range": 60, "cooldown": 1.5},
        "is_t2": True,
    },
    "medic_t2": {
        "hp": 75, "speed": 60, "radius": 6,
        "symbol": MEDIC_SYMBOL, "can_attack": True,
        "fov": 30, "turn_rate": 90, "los": 90,
        "weapon": {
            "name": "HealLaser", "damage": -1, "range": 70, "cooldown": 0.2,
            "hits_only_friendly": True,
        },
        "is_t2": True,
    },
    "tank_t2": {
        "hp": 350, "speed": 20, "radius": 9,
        "symbol": TANK_SYMBOL, "can_attack": True,
        "fov": 150, "turn_rate": 50, "los": 80,
        "weapon": {"name": "Laser", "damage": 10, "range": 50, "cooldown": 2.0},
        "is_t2": True,
    },
    "sniper_t2": {
        "hp": 65, "speed": 35, "radius": 6,
        "symbol": SNIPER_SYMBOL, "can_attack": True,
        "fov": 45, "turn_rate": 90, "los": 135,
        "weapon": {"name": "Heavy Laser", "damage": 45, "range": 150, "cooldown": 5.0,
                   "laser_width": 3, "sound": "laser"},
        "is_t2": True,
    },
    "machine_gunner_t2": {
        "hp": 80, "speed": 30, "radius": 6,
        "symbol": MACHINE_GUNNER_SYMBOL, "can_attack": True,
        "fov": 180, "turn_rate": 25, "los": 100,
        "weapon": {"name": "Laser", "damage": 12, "range": 75, "cooldown": 0.4, "laser_flash_duration": 0.1},
        "is_t2": True,
    },
    "scout_t2": {
        "hp": 12, "speed": 110, "radius": 4,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
        "fov": 30, "turn_rate": 150, "los": 120,
        "spawn_count": 5,
        "weapon": {"name": "Laser", "damage": 5, "range": 50, "cooldown": 0.5,
                   "laser_flash_duration": 0.1},
        "is_t2": True,
    },
    "shockwave_t2": {
        "hp": 50, "speed": 30, "radius": 6,
        "symbol": SHOCKWAVE_SYMBOL, "can_attack": True,
        "fov": 360, "turn_rate": 180, "los": 100,
        "weapon": {
            "name": "ChainLaser", "damage": 15, "range": 90, "cooldown": 3.0,
            "chain_range": 50.0, "chain_delay": 0.1,
        },
        "is_t2": True,
    },
    "artillery_t2": {
        "hp": 120, "speed": 15, "radius": 9,
        "symbol": ARTILLERY_SYMBOL, "can_attack": True,
        "fov": 15, "turn_rate": 25, "los": 180,
        "weapon": {
            "name": "ArtilleryCannon", "damage": 70, "range": 180, "cooldown": 6.0,
            "splash_radius": 75, "splash_damage_max": 70, "splash_damage_min": 1,
            "charge_time": 3.0,
            "friendly_fire": True,
            "sound": "artillery",
            "laser_width": 6,
            "laser_flash_duration": 2.5,
        },
        "is_t2": True,
    },
}


def get_spawnable_types() -> dict:
    """Return only unit types that can be spawned by the player (excludes buildings and T2)."""
    return {k: v for k, v in UNIT_TYPES.items()
            if not v.get("is_building", False) and not v.get("is_t2", False)}


# -- T2 helpers ---------------------------------------------------------------

T2_NAMES: dict[str, str] = {
    "soldier": "Marine",
    "medic": "Priest",
    "tank": "Heavy Tank",
    "sniper": "Marksman",
    "machine_gunner": "Plasma Beamer",
    "scout": "Drone Swarm",
    "shockwave": "Disruptor",
    "artillery": "Mortar",
}


def get_t2_name(unit_type: str) -> str:
    """Return the T2 display name for a base unit type."""
    base = unit_type.removesuffix("_t2")
    return T2_NAMES.get(base, base.replace("_", " ").title() + " T2")


def get_t2_type(unit_type: str) -> str:
    """Return the T2 type key for a base unit type (e.g. 'soldier' -> 'soldier_t2')."""
    return unit_type + "_t2"
