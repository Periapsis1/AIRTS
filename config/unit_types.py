"""Data-driven unit type definitions.

To add a new unit type, add an entry to UNIT_TYPES.  Every entry must include
the base keys (hp, speed, radius, damage, range, cooldown, symbol, can_attack).
Optional keys are consumed by specific systems (e.g. heal_rate by the medic
heal system).

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

SCOUT_SYMBOL = (
    (0, -12), (8, 4), (-8, 4),
)

# -- type registry -----------------------------------------------------------

UNIT_TYPES = {
    "soldier": {
        "hp": 100, "speed": 40, "radius": 5,
        "damage": 10, "range": 50, "cooldown": 2.0,
        "symbol": None, "can_attack": True,
    },
    "medic": {
        "hp": 100, "speed": 40, "radius": 5,
        "damage": 0, "range": 0, "cooldown": 0,
        "symbol": MEDIC_SYMBOL, "can_attack": False,
        "heal_rate": 5, "heal_range": 40, "heal_targets": 2,
    },
    "tank": {
        "hp": 300, "speed": 20, "radius": 7,
        "damage": 5, "range": 50, "cooldown": 2.0,
        "symbol": TANK_SYMBOL, "can_attack": True,
    },
    "sniper": {
        "hp": 50, "speed": 35, "radius": 5,
        "damage": 30, "range": 150, "cooldown": 6.0,
        "symbol": SNIPER_SYMBOL, "can_attack": True,
    },
    "machine_gunner": {
        "hp": 70, "speed": 40, "radius": 5,
        "damage": 1, "range": 50, "cooldown": 0.2,
        "symbol": MACHINE_GUNNER_SYMBOL, "can_attack": True,
    },
    "scout": {
        "hp": 10, "speed": 100, "radius": 4,
        "damage": 3, "range": 15, "cooldown": 0.5,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
        "spawn_count": 3,
    },
}
