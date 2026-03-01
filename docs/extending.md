# Extending AIRTS

## Adding a New Unit Type

All unit types are defined in `config/unit_types.py` in the `UNIT_TYPES` dictionary. To add a new type, add an entry with the required keys:

### Required Keys

| Key | Type | Description |
|-----|------|-------------|
| `hp` | `int` | Starting and maximum hit points |
| `speed` | `int/float` | Movement speed in pixels per second |
| `radius` | `int/float` | Collision circle radius |
| `damage` | `int/float` | Damage per attack |
| `range` | `int/float` | Attack range in pixels (0 = cannot attack by range) |
| `cooldown` | `float` | Seconds between attacks |
| `symbol` | `tuple \| None` | Polygon points for the unit icon, or `None` for a plain circle |
| `can_attack` | `bool` | Whether the unit participates in combat |

### Optional Keys

| Key | Type | Description |
|-----|------|-------------|
| `heal_rate` | `float` | HP healed per second per target (consumed by `medic_heal_step`) |
| `heal_range` | `float` | Radius within which the unit can heal allies |
| `heal_targets` | `int` | Max number of allies healed simultaneously |

### Symbol Format

Symbols are tuples of `(x, y)` coordinate pairs defined relative to a **16-pixel reference radius**. They are scaled at draw time to the unit's actual radius. For example:

```python
# A simple diamond shape
DIAMOND_SYMBOL = (
    (0, -12), (12, 0), (0, 12), (-12, 0),
)
```

Set `symbol` to `None` for units that should be drawn as plain circles (like soldiers).

### Example: Adding a Scout Unit

```python
# In config/unit_types.py

SCOUT_SYMBOL = (
    (0, -14), (8, -4), (4, 12), (-4, 12), (-8, -4),
)

UNIT_TYPES = {
    # ... existing types ...
    "scout": {
        "hp": 40, "speed": 80, "radius": 4,
        "damage": 5, "range": 30, "cooldown": 1.5,
        "symbol": SCOUT_SYMBOL, "can_attack": True,
    },
}
```

Once added, the unit type automatically:
- Appears in the GUI spawn panel.
- Becomes available via `set_build("scout")` in AI controllers.
- Works with all existing systems (combat, physics, selection).

No other code changes are needed.

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

Wire it into `main.py`:

```python
from my_map import MyMapGenerator

game = Game(
    map_generator=MyMapGenerator(),
    team_ai={2: WanderAI()},
)
```

### Important Notes

- You **must** place at least one `CommandCenter` per team.
- Set `cc._bounds = (width, height)` so spawned units know the map size.
- Set `cc._spawn_timer = CC_SPAWN_INTERVAL` for an immediate first spawn.
- Mark obstacles with `entity.obstacle = True` so LOS checks and collision systems recognize them.
- Metal spots should be placed symmetrically for fair gameplay.

## Adding a New Game System

Game systems are standalone modules in `systems/` that operate on the entity list each frame. To add one:

### 1. Create the module

```python
# systems/my_system.py
from __future__ import annotations
from entities.unit import Unit


def my_system_step(units: list[Unit], dt: float):
    """Example: apply poison damage to all units."""
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

The execution order matters — place your system call at the point where it makes sense relative to combat, physics, and spawning. See [architecture.md](architecture.md) for the full order.

## Modifying Constants

Key values in `config/settings.py` you can tweak:

| Constant | Default | What It Affects |
|----------|---------|-----------------|
| `CC_HP` | 1000 | How long games last |
| `CC_SPAWN_INTERVAL` | 10.0 | Unit production rate |
| `CC_LASER_DAMAGE` | 20 | How dangerous CC defenses are |
| `CC_HEAL_RATE` | 5 | Strength of CC healing aura |
| `METAL_SPOT_CAPTURE_RATE` | 0.05 | Speed of metal spot capture |
| `METAL_EXTRACTOR_BOOST_FACTOR` | 1.05 | Economic value of extractors |
| `METAL_EXTRACTOR_HP` | 200 | How easy extractors are to destroy |
| `UNIT_PUSH_FORCE` | 200.0 | How strongly units push apart |
| `OBSTACLE_PUSH_FORCE` | 300.0 | How strongly obstacles repel units |

Individual unit stats are in `config/unit_types.py` — see the `UNIT_TYPES` dict.
