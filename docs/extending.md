# Extending AIRTS

## Adding a New Unit Type

All unit types are defined in `config/unit_types.py` in the `UNIT_TYPES` dictionary. To add a new type, add an entry with the required keys.

### Required Keys

| Key | Type | Description |
|-----|------|-------------|
| `hp` | `int` | Starting and maximum hit points |
| `speed` | `int/float` | Movement speed in pixels per second |
| `radius` | `int/float` | Collision circle radius |
| `symbol` | `tuple \| None` | Polygon points for the unit icon, or `None` for a plain circle |
| `can_attack` | `bool` | Whether the unit participates in combat |
| `fov` | `float` | Field of view in degrees (e.g. 90 = quarter circle in front) |
| `turn_rate` | `float` | Degrees per second the unit can rotate |
| `los` | `float` | Line-of-sight range in pixels (for target detection) |
| `weapon` | `dict` | Combat stats — see **Weapon Keys** below |

### Weapon Keys

All combat stats live in the `weapon` sub-dict:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | `str` | Yes | Display name (e.g. `"Laser"`, `"Heavy Laser"`) |
| `damage` | `float` | Yes | Damage per shot (negative = heals) |
| `range` | `float` | Yes | Attack range in pixels |
| `cooldown` | `float` | Yes | Seconds between shots |
| `hits_only_friendly` | `bool` | No | If `True`, only fires at allies (used for medic heal laser) |
| `chain_range` | `float` | No | Bounce range for chain lasers (shockwave) |
| `chain_delay` | `float` | No | Seconds between chain bounces |
| `splash_radius` | `float` | No | Blast radius for area-of-effect weapons (artillery) |
| `splash_damage_max` | `float` | No | Max splash damage at the center |
| `splash_damage_min` | `float` | No | Min splash damage at the edge |
| `friendly_fire` | `bool` | No | If `True`, splash hits friendlies too |
| `charge_time` | `float` | No | Seconds of charge before the shot fires (artillery) |
| `laser_width` | `int` | No | Visual width of the laser beam in pixels |
| `laser_flash_duration` | `float` | No | Override for the laser flash lifetime |
| `sound` | `str` | No | Sound effect key to play on fire |

### Optional Unit Keys

| Key | Type | Description |
|-----|------|-------------|
| `spawn_count` | `int` | Units spawned per CC cycle (default: 1). Scout uses 3. |
| `is_t2` | `bool` | Mark as a Tier 2 unit. T2 types are excluded from `get_spawnable_types()` and unlocked via Research Lab. |
| `is_building` | `bool` | Mark as a non-mobile structure (CC, extractor). Excluded from `get_spawnable_types()`. |

### Symbol Format

Symbols are tuples of `(x, y)` coordinate pairs defined relative to a **16-pixel reference radius**. They are scaled at draw time to the unit's actual radius. For example:

```python
# A simple diamond shape
DIAMOND_SYMBOL = (
    (0, -12), (12, 0), (0, 12), (-12, 0),
)
```

Set `symbol` to `None` for units drawn as plain circles (like soldiers).

### Example: Adding a Scout Unit

```python
# In config/unit_types.py

SCOUT_SYMBOL = (
    (0, -14), (8, -4), (4, 12), (-4, 12), (-8, -4),
)

UNIT_TYPES = {
    # ... existing types ...
    "flamethrower": {
        "hp": 80, "speed": 35, "radius": 5,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
        "fov": 120, "turn_rate": 180, "los": 80,
        "weapon": {
            "name": "Flame", "damage": 3, "range": 40, "cooldown": 0.2,
            "splash_radius": 15, "splash_damage_max": 3, "splash_damage_min": 1,
            "friendly_fire": False,
        },
    },
}
```

Once added, the unit type automatically:
- Appears in the GUI spawn panel.
- Becomes available via `set_build("flamethrower")` in AI controllers.
- Works with all existing systems (combat, physics, selection).

No other code changes are needed.

### Adding a T2 Variant

Add a second entry with `_t2` suffix and `"is_t2": True`:

```python
UNIT_TYPES = {
    # ...
    "flamethrower_t2": {
        "hp": 120, "speed": 40, "radius": 5,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
        "fov": 150, "turn_rate": 180, "los": 100,
        "weapon": {
            "name": "Inferno", "damage": 5, "range": 50, "cooldown": 0.15,
            "splash_radius": 25, "splash_damage_max": 5, "splash_damage_min": 2,
            "friendly_fire": False,
        },
        "is_t2": True,
    },
}
```

Register the display name in `T2_NAMES` at the bottom of the file:

```python
T2_NAMES["flamethrower"] = "Inferno Trooper"
```

## Creating a Custom Map Generator

Map generators produce the initial entity list for a game. To create one, subclass `BaseMapGenerator` and implement `generate()`:

```python
# my_map.py
from systems.map_generator import BaseMapGenerator
from entities.base import Entity
from entities.command_center import CommandCenter
from entities.metal_spot import MetalSpot
from entities.shapes import RectEntity
from config.settings import OBSTACLE_COLOR, CC_SPAWN_INTERVAL


class MyMapGenerator(BaseMapGenerator):
    def generate(self, width: int, height: int) -> list[Entity]:
        entities: list[Entity] = []

        # Place Command Centers (required — one per team)
        cc1 = CommandCenter(100, height // 2, team=1)
        cc1._bounds = (width, height)
        cc1._spawn_timer = CC_SPAWN_INTERVAL  # Start with a full timer
        entities.append(cc1)

        cc2 = CommandCenter(width - 100, height // 2, team=2)
        cc2._bounds = (width, height)
        cc2._spawn_timer = CC_SPAWN_INTERVAL
        entities.append(cc2)

        # Place metal spots (optional)
        entities.append(MetalSpot(width // 2, height // 3))
        entities.append(MetalSpot(width // 2, 2 * height // 3))

        # Place obstacles (optional)
        wall = RectEntity(width // 2 - 5, height // 4, 10, height // 2)
        wall.obstacle = True
        wall.color = OBSTACLE_COLOR
        entities.append(wall)

        return entities
```

Wire it into `main.py` or pass it to `Game(map_generator=MyMapGenerator())`.

### Important Notes

- You **must** place at least one `CommandCenter` per team.
- Set `cc._bounds = (width, height)` so spawned units know the map size.
- Set `cc._spawn_timer = CC_SPAWN_INTERVAL` for an immediate first spawn.
- Mark obstacles with `entity.obstacle = True` so LOS checks and collision systems recognize them.
- Metal spots should be placed symmetrically for fair gameplay.

## Adding a Passive Ability

Passive abilities are subclasses of `PassiveAbility` in `systems/abilities.py`. They attach to entities and fire hooks during the game loop.

### 1. Subclass `PassiveAbility`

```python
# In systems/abilities.py

class Poison(PassiveAbility):
    name = "poison"
    description = "Poisons the attacker when hit — deals 1 HP/s for 5 seconds."

    DURATION = 5.0
    RATE = 1.0

    def __init__(self):
        super().__init__()
        self.timer: float = 0.0
        self._poisoned_entities: list = []

    def modify_damage(self, amount: float, entity) -> float:
        # When this unit is hit, apply poison back to the attacker
        # (actual implementation would need attacker reference)
        return amount

    def update(self, entity, dt: float) -> None:
        # Apply ongoing poison damage to tracked entities
        pass
```

### 2. Register in `ABILITY_REGISTRY`

```python
ABILITY_REGISTRY["poison"] = Poison
```

### 3. Assign to a Unit Type

Abilities are assigned when units are created in `entities/unit.py` based on `unit_type`. Add a branch there:

```python
if unit_type == "my_poisonous_unit":
    unit.abilities.append(Poison())
```

## Adding a New Game System

Game systems are standalone modules in `systems/` that operate on the entity list each frame.

### 1. Create the module

```python
# systems/my_system.py
from __future__ import annotations
from entities.unit import Unit


def my_system_step(units: list[Unit], dt: float):
    """Example: apply burning damage to all units with fire stacks."""
    for unit in units:
        if not unit.alive:
            continue
        # Your logic here
        pass
```

### 2. Wire it into `Game.step()`

In `game.py`, import your function and call it at the appropriate point in the `step()` method:

```python
from systems.my_system import my_system_step

# Inside Game.step():
def step(self, dt: float):
    # ... existing systems ...
    my_system_step(units, dt)
    # ... rest of step ...
```

The execution order matters — place your system call at the right point relative to combat, physics, and spawning. See [architecture.md](architecture.md) for the full order.

## Modifying Constants

Key values in `config/settings.py` you can tweak:

| Constant | Default | What It Affects |
|----------|---------|-----------------|
| `CC_HP` | 1000 | How long games last |
| `CC_SPAWN_INTERVAL` | 10.0 | Unit production rate |
| `CC_LASER_DAMAGE` | 20 | How dangerous CC defenses are |
| `CC_HEAL_RATE` | 5 | Strength of CC healing aura |
| `METAL_SPOT_CAPTURE_RATE` | 0.05 | Speed of metal spot capture |
| `METAL_EXTRACTOR_SPAWN_BONUS` | 0.08 | Economic value of extractors (8% per extractor) |
| `REACTIVE_ARMOR_INTERVAL` | 5.0 | How fast tanks regenerate armor charges |
| `ELECTRIC_ARMOR_INTERVAL` | 1.0 | How fast T2 tanks gain electric stacks |
| `T2_UPGRADE_DURATION` | 60.0 | Construction time for Outpost / Research Lab |
| `UNIT_PUSH_FORCE` | 200.0 | How strongly units push apart |
| `OBSTACLE_PUSH_FORCE` | 300.0 | How strongly obstacles repel units |

Individual unit stats are in `config/unit_types.py` — see the `UNIT_TYPES` dict.
