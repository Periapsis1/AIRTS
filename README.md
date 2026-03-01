# AIRTS

A modular RTS game built with Pygame — designed as a platform for writing AI controllers that compete against humans or other AIs. Built for the 2026 BlueOrange "AI Jam" event.

## Setup

```bash
git clone <repo-url>
cd AIRTS

python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
pip install -r requirements.txt

python main.py
```

Requires **Python 3.10+**, **Pygame 2.6+**, and **NumPy 2.4+**.

## Game Modes

Configure the `team_ai` parameter when creating a game:

| Mode | Config | Description |
|---|---|---|
| Human vs AI | `team_ai={2: WanderAI()}` | You control Team 1, AI controls Team 2 |
| AI vs Human | `team_ai={1: MyAI()}` | AI controls Team 1, you control Team 2 |
| AI vs AI | `team_ai={1: MyAI(), 2: WanderAI()}` | Watch two AIs battle (spectator mode) |

At least one team must have an AI controller — Human-vs-Human is not supported.

## Project Structure

```
AIRTS/
├── main.py                     Entry point
├── app.py                      Screen routing and pygame lifecycle
├── game.py                     Game loop, event handling, rendering
├── gui.py                      CC spawn-type selection panel
├── config/
│   ├── settings.py             Tuning constants (HP, damage, colors, physics)
│   └── unit_types.py           Data-driven unit type registry
├── core/
│   └── helpers.py              Geometry helpers (LOS, hexagon points)
├── entities/
│   ├── base.py                 Entity base class + Damageable mixin
│   ├── shapes.py               Rect, Circle, Polygon, Sprite entities
│   ├── unit.py                 Unit class (commands, fire modes, movement)
│   ├── command_center.py       CommandCenter (spawning, healing, rally points)
│   ├── metal_spot.py           Capturable resource node
│   ├── metal_extractor.py      Built on captured metal spots
│   └── laser.py                Laser visual effect
├── systems/
│   ├── ai/                     AI controllers
│   │   ├── base.py             BaseAI abstract class
│   │   ├── wander.py           Built-in WanderAI
│   │   └── registry.py         Auto-discovers AIs from ais/ and systems/ai/
│   ├── commands.py             Command serialization layer (multiplayer-ready)
│   ├── combat.py               Laser attacks, medic healing, CC aura
│   ├── physics.py              Collision resolution, bounds clamping
│   ├── spawning.py             Unit spawning from command centers
│   ├── capturing.py            Metal spot capture logic
│   ├── selection.py            Click and drag selection
│   ├── map_generator.py        Map generation
│   ├── replay.py               Replay recording
│   ├── stats.py                Game statistics tracking
│   └── crash_handler.py        Crash log handler
├── screens/                    Menu screens (main menu, lobby, results, etc.)
├── ui/                         Reusable UI widgets and theming
└── ais/                        Drop your AI files here (auto-discovered)
    └── example_ai.py           Reference AI implementation
```

## Documentation

| Topic | Link |
|---|---|
| Write an AI controller | [docs/ai-guide.md](docs/ai-guide.md) |
| Understand the game rules | [docs/game-mechanics.md](docs/game-mechanics.md) |
| Understand the codebase internals | [docs/architecture.md](docs/architecture.md) |
| Add new units, maps, or systems | [docs/extending.md](docs/extending.md) |

## Quick Start: Writing an AI

Create a file in the `ais/` folder — it will be auto-discovered at startup:

```python
# ais/my_ai.py
from systems.ai.base import BaseAI

class MyAI(BaseAI):
    ai_id = "my_ai"
    ai_name = "My Custom AI"

    def on_start(self) -> None:
        self.set_build("soldier")

    def on_step(self, iteration: int) -> None:
        for unit in self.get_own_units():
            if unit.target is None:
                bw, _ = self.bounds
                cc = self.get_cc()
                if cc:
                    self.move_unit(unit, bw - cc.x, cc.y)
```

See [docs/ai-guide.md](docs/ai-guide.md) for the full API reference, unit stats, fire modes, and example strategies.
