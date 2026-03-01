# Architecture

## Project Structure

```
AIRTS/
├── main.py                     Entry point — launches App
├── app.py                      Application controller — pygame lifecycle, screen routing
├── game.py                     Game loop, event handling, system wiring, rendering
├── gui.py                      CC spawn-type selection GUI panel
├── requirements.txt            Python dependencies (pygame, numpy)
├── ais/                        User AI folder (auto-discovered at startup)
│   ├── __init__.py
│   └── example_ai.py           Example user AI for reference
├── config/
│   ├── settings.py             All tuning constants (HP, damage, colors, physics)
│   └── unit_types.py           Data-driven unit type registry
├── core/
│   └── helpers.py              Geometry helpers (hexagon, line-circle/rect intersection)
├── entities/
│   ├── base.py                 Entity base class + Damageable mixin
│   ├── shapes.py               RectEntity, CircleEntity, PolygonEntity, SpriteEntity
│   ├── unit.py                 Unit class (commands, fire modes, movement)
│   ├── command_center.py       CommandCenter (spawning, healing aura, rally points)
│   ├── metal_spot.py           MetalSpot (capturable resource node)
│   ├── metal_extractor.py      MetalExtractor (built on captured spots)
│   └── laser.py                LaserFlash visual effect
├── screens/                    Menu screen classes (per-screen event loops)
│   ├── base.py                 BaseScreen ABC + ScreenResult dataclass
│   ├── main_menu.py            Title screen with background animation
│   ├── create_lobby.py         Game configuration (mode, AIs, map settings)
│   ├── guides.py               6-topic informational guide viewer
│   ├── unit_overview.py        Interactive unit type browser
│   └── results.py              Victory/Defeat/Draw screen
├── ui/                         Reusable UI widgets and theming
│   ├── theme.py                Menu color/size constants
│   └── widgets.py              Button, BackButton, Dropdown, Slider, ToggleGroup
└── systems/
    ├── ai/
    │   ├── base.py             BaseAI abstract class (ai_id, ai_name attributes)
    │   ├── wander.py           WanderAI built-in implementation
    │   └── registry.py         AIRegistry — auto-discovers AIs from ais/ and systems/ai/
    ├── combat.py               Laser attacks, medic healing, CC aura healing
    ├── physics.py              Collision resolution and bounds clamping
    ├── spawning.py             Unit spawning from Command Centers
    ├── capturing.py            Metal spot capture logic
    ├── selection.py            Click and circle-drag selection
    └── map_generator.py        BaseMapGenerator + DefaultMapGenerator
```

## Application Lifecycle

The `App` class (in `app.py`) owns the pygame lifecycle and routes between screens:

```
App.__init__()
 ├─ pygame.init()
 ├─ Create display (800x600)
 ├─ Create clock
 └─ AIRegistry.discover()     ← scans systems/ai/ and ais/ for BaseAI subclasses

App.run()
 └─ while next_screen != "quit":
     └─ result = _run_screen(prev_result)
         ├─ "main_menu"    → MainMenuScreen
         ├─ "create_lobby" → CreateLobbyScreen (with AI choices)
         ├─ "game"         → _run_game() → Game.run() → ResultsScreen
         ├─ "guides"       → GuidesScreen
         ├─ "unit_overview" → UnitOverviewScreen
         └─ "results"      → ResultsScreen
```

Each screen has its own event loop via `run() -> ScreenResult`. The `ScreenResult` dataclass carries a `next_screen` string and optional `data` dict to decouple screens from each other.

When a game is started, `App._run_game()` resizes the display to match map dimensions, creates a `Game` instance with the lobby settings, and restores 800x600 after the game ends.

### Win Condition

After pruning dead entities in `step()`, the game checks if fewer than 2 teams have a living Command Center. If so, the game ends and `run()` returns a result dict with the winner.

## Game Loop

The `Game.run()` method drives a standard fixed-timestep loop at **60 FPS** and returns a result dict:

```
run() -> {"winner": int, "human_teams": set}
 └─ while running:
     ├─ dt = clock.tick(60) / 1000.0
     ├─ handle_events()     ← input processing
     ├─ step(dt)            ← simulation update
     └─ render()            ← draw everything
```

### `handle_events()`

Processes the Pygame event queue:
- **Escape / window close** → stop the game.
- **Left mouse** → selection (click or circle-drag). Shift adds to selection. GUI clicks for CC panel are intercepted first.
- **Right mouse** → movement path drawing. On release, distributes selected units along the path and sets CC rally points.

In AI-only mode (no human teams), only quit/escape events are processed.

### `step(dt)`

The simulation tick runs systems in this exact order:

```
1.  Entity update        for entity in entities: entity.update(dt)
2.  AI step              for ai in team_ai.values(): ai.on_step(iteration)
3.  Capture step         capture_step(...)
4.  Combat step          combat_step(...)
5.  Medic heal step      medic_heal_step(...)
6.  CC heal step         cc_heal_step(...)
7.  Spawn step           spawn_step(...)
8.  Prune dead           entities = [e for e in entities if e.alive]
9.  Physics              resolve_unit_collisions, resolve_obstacle_collisions,
                         resolve_structure_collisions, clamp_units_to_bounds
10. Laser flash update   laser_flashes = [lf for lf if lf.update(dt)]
11. Increment iteration
```

Key implications:
- AI commands issued in step 2 take effect in the same frame's combat/physics (steps 4–9).
- Dead entities are pruned after combat and spawning but before physics. Newly spawned units participate in physics immediately.
- Physics runs after combat, so units pushed by collisions won't affect the current frame's attack range calculations.

### `render()`

Draws in order:
1. Black background fill.
2. All entities (`entity.draw()`).
3. Laser flash effects.
4. Selection circle overlay (if dragging).
5. Movement path preview (if right-dragging).
6. CC GUI panel (if a human team has a CC selected).
7. `pygame.display.flip()`.

## Entity Class Hierarchy

```
Entity                          (base.py — x, y, color, selected, obstacle, alive)
├── RectEntity                  (shapes.py — adds width, height)
├── CircleEntity                (shapes.py — adds radius)
│   ├── Unit                    (unit.py — also mixes in Damageable)
│   ├── MetalSpot               (metal_spot.py — also mixes in Damageable)
│   └── MetalExtractor          (metal_extractor.py — also mixes in Damageable)
├── PolygonEntity               (shapes.py — adds points list)
│   └── CommandCenter           (command_center.py — also mixes in Damageable)
└── SpriteEntity                (shapes.py — adds image loading/transform)

Damageable                      (base.py — mixin: hp, max_hp, take_damage(), draw_health_bar())
```

`Damageable` is a mixin class that provides `hp`, `max_hp`, `take_damage(amount)`, and `draw_health_bar()`. It is used by `Unit`, `CommandCenter`, `MetalSpot`, and `MetalExtractor`.

## Systems

### Combat (`systems/combat.py`)

Three functions:
- **`combat_step()`** — Iterates all units and CCs. Each checks for enemies in range, performs LOS checks against obstacles, and fires if able. Creates `LaserFlash` visuals for each shot. Units respect their `fire_mode`; CCs always target the closest enemy.
- **`medic_heal_step()`** — Each living medic heals up to `heal_targets` (2) closest wounded allies within `heal_range` (40 px) at `heal_rate * dt` HP per frame.
- **`cc_heal_step()`** — Each living CC heals all friendly units within `CC_HEAL_RADIUS` (40 px) at `CC_HEAL_RATE * dt` (5 HP/s).

### Physics (`systems/physics.py`)

Four functions:
- **`resolve_unit_collisions()`** — Pushes overlapping units apart.
- **`resolve_obstacle_collisions()`** — Pushes units out of circle and rect obstacles.
- **`resolve_structure_collisions()`** — Pushes units out of Command Centers.
- **`clamp_units_to_bounds()`** — Keeps units within the map boundaries.

### Spawning (`systems/spawning.py`)

**`spawn_step()`** — Checks each CC's spawn timer. When ready, calls `cc.spawn_unit()` (which creates a unit at a random angle around the CC), marks the unit as selectable if it belongs to a human team, appends it to the entity list, and resets the timer.

### Capturing (`systems/capturing.py`)

**`capture_step()`** — For each unclaimed metal spot, counts team 1 vs team 2 units within the capture radius and adjusts capture progress. When progress reaches ±1.0, creates a `MetalExtractor` and links it to the capturing team's CC.

### Selection (`systems/selection.py`)

- **`click_select()`** — Finds the closest selectable entity to the click point.
- **`apply_circle_selection()`** — Selects all selectable units inside the drag circle. If only a CC is enclosed (no units), selects the CC instead.
- Both support additive selection via the Shift key.

### Map Generator (`systems/map_generator.py`)

- **`BaseMapGenerator`** — Abstract interface with a single `generate(width, height) -> list[Entity]` method.
- **`DefaultMapGenerator`** — Places two CCs symmetrically, 2–4 mirrored metal spot pairs, and 4–8 random obstacles (circles and rectangles).

## AI Discovery & Binding

### Discovery (`systems/ai/registry.py`)

At startup, `AIRegistry.discover()` scans two directories for Python files containing `BaseAI` subclasses:

1. **`systems/ai/`** — built-in AIs (e.g. `WanderAI`)
2. **`ais/`** — user/jam participant AIs

Each file is imported inside a `try/except`. Classes with a non-empty `ai_id` attribute are registered. Broken files are logged in `registry.errors` but don't crash the app.

### Binding

When a `Game` is constructed:

1. `_apply_selectability()` — Marks entities belonging to human teams as selectable.
2. `_bind_and_start_ais()` — For each entry in `team_ai`:
   - Calls `ai._bind(team_id, game)` which stores the team number and a reference to the Game instance.
   - Calls `ai.on_start()` for initial setup.

After this, `ai.on_step(iteration)` is called every frame during `step()`.

## Configuration

### `config/settings.py`

All tuning constants live here. Key values:

| Constant | Value | Description |
|----------|-------|-------------|
| `CC_HP` | 1000 | Command Center hit points |
| `CC_SPAWN_INTERVAL` | 10.0 | Seconds between spawns |
| `CC_LASER_RANGE` | 75.0 | CC defensive laser range |
| `CC_LASER_DAMAGE` | 20 | CC laser damage per shot |
| `CC_LASER_COOLDOWN` | 1.0 | CC laser cooldown |
| `CC_HEAL_RADIUS` | 40.0 | CC healing aura radius |
| `CC_HEAL_RATE` | 5 | CC healing HP/s |
| `METAL_SPOT_CAPTURE_RADIUS` | 15.0 | Capture zone radius |
| `METAL_SPOT_CAPTURE_RATE` | 0.05 | Progress per unit per second |
| `METAL_EXTRACTOR_HP` | 200 | Extractor hit points |
| `METAL_EXTRACTOR_BOOST_FACTOR` | 1.05 | Spawn speed multiplier per extractor |
| `UNIT_PUSH_FORCE` | 200.0 | Unit-unit collision push |
| `OBSTACLE_PUSH_FORCE` | 300.0 | Obstacle collision push |
| `LASER_FLASH_DURATION` | 0.15 | Laser visual lifetime in seconds |

### `config/unit_types.py`

The `UNIT_TYPES` dictionary defines all unit types. Each entry is a dict with these keys:

**Required:** `hp`, `speed`, `radius`, `damage`, `range`, `cooldown`, `symbol`, `can_attack`

**Optional:** `heal_rate`, `heal_range`, `heal_targets` (used by medics)

See [extending.md](extending.md) for how to add new unit types.
