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
│   ├── helpers.py              Geometry helpers (hexagon, line-circle/rect, circle-AABB)
│   └── vectorized.py           NumPy-accelerated obstacle push
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
    ├── commands.py             GameCommand + CommandQueue (serializable command layer)
    ├── combat.py               Laser attacks, medic healing, CC aura healing
    ├── physics.py              Collision resolution and bounds clamping
    ├── spawning.py             Unit spawning from Command Centers
    ├── capturing.py            Metal spot capture logic
    ├── selection.py            Click and circle-drag selection
    ├── replay.py               Replay recording (state snapshots)
    ├── stats.py                Game statistics tracking
    ├── crash_handler.py        Crash log handler
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

Processes the Pygame event queue. All player actions are routed through the **command system** (`systems/commands.py`) rather than mutating state directly:
- **Escape / window close** → stop the game.
- **Left mouse** → selection (click or circle-drag). Shift adds to selection. GUI clicks for the CC panel enqueue a `set_spawn_type` command.
- **Right mouse** → movement path drawing. On release, enqueues `move` commands for selected units and `set_rally` commands for selected CCs.

In AI-only mode (no human teams), only quit/escape events are processed.

### `step(dt)`

The simulation tick runs systems in this exact order:

```
1.  Drain commands       command_queue.drain(iteration) → _apply_command() for each
2.  Grid build           Insert alive units into spatial grid; also computes
                         team AABBs, alive_mobile_units list, team_any_hurt flags
3.  Facing precompute    Pre-compute nearest enemy/heal target per unit (grid queries)
                         with AABB early-exits to skip cross-team scans
4.  Entity update        for entity in entities: entity.update(dt)
5.  Filtering            Build units, ccs, obstacles, metal_extractors lists
6.  AI step              for ai in team_ai.values(): ai.on_step(iteration)
7.  Capture step         capture_step(...)
8.  Combat step          combat_step(...) + cc_heal_step(...)
                         (uses pre-extracted obstacle tuples + team AABBs)
9.  Spawn step           spawn_step(...)
10. Prune dead           entities = [e for e in entities if e.alive]
11. Physics              resolve_unit_collisions, batch_obstacle_push,
                         clamp_units_to_bounds (skipped via cooldown when idle)
12. Laser flash update   laser_flashes = [lf for lf if lf.update(dt)]
13. Increment iteration
```

Key implications:
- Human commands (enqueued between frames during `handle_events`) are applied in step 1, before entity update, so they take effect immediately.
- AI commands (enqueued during step 6) are applied at step 1 of the *next* tick. This one-tick delay matches the original behavior since `entity.update()` already ran before the AI step.
- Dead entities are pruned after combat and spawning but before physics. Newly spawned units participate in physics immediately.
- Physics runs after combat, so units pushed by collisions won't affect the current frame's attack range calculations.
- **Physics cooldown:** Physics is skipped entirely when no units are moving and no recent spawns occurred, reducing idle-tick cost to near zero. A cooldown timer (60 ticks after spawn, 10 ticks after movement stops) ensures settling completes before skipping.

### Command System

All player actions — human and AI — flow through a serializable command layer (`systems/commands.py`). This makes the game multiplayer-ready: commands can be sent over a network and applied identically on both clients.

There are five command types:

| Command | Source | Effect |
|---|---|---|
| `move` | Human right-click, `BaseAI.move_unit()` | Sets unit move targets |
| `attack` | `BaseAI.attack_unit()` | Assigns an attack target |
| `stop` | Future use | Clears unit movement |
| `set_rally` | Human right-click on CC | Sets CC rally point |
| `set_spawn_type` | GUI click, `BaseAI.set_build()` | Changes CC spawn type |

Selection (click, circle-drag, double-click) is local/visual only and does not go through the command system.

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

Two functions:
- **`combat_step()`** — Iterates all alive units. Each checks for enemies in range (with team AABB early-exit to skip grid queries when teams are far apart), performs LOS checks against pre-extracted obstacle tuples, and fires if able. Creates `LaserFlash` visuals for each shot. Units respect their `fire_mode`. Medic units use `hits_only_friendly` weapons to heal the closest wounded ally.
- **`cc_heal_step()`** — Each living CC heals all friendly units within `CC_HEAL_RADIUS` (40 px) at `CC_HEAL_RATE * dt` (5 HP/s).

### Physics (`systems/physics.py` + `core/vectorized.py`)

- **`resolve_unit_collisions()`** — Pushes overlapping units apart (uses spatial grid for O(N) pair finding).
- **`batch_obstacle_push()`** — NumPy-vectorized push of all mobile units out of circle and rect obstacles in a single batch.
- **`clamp_units_to_bounds()`** — Keeps units within the map boundaries.

Physics runs under a **cooldown system**: it activates for 60 ticks after new units spawn and 10 ticks after any unit movement, then skips entirely (just clamping bounds) when the world is idle.

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
   - Calls `ai._bind(team_id, game, stats, command_queue)` which stores the team number, a reference to the Game instance, the stats tracker, and the shared `CommandQueue`.
   - Calls `ai.on_start()` for initial setup.

After this, `ai.on_step(iteration)` is called every frame during `step()`. All AI actions (`move_unit`, `attack_unit`, `set_build`) enqueue commands to the shared `CommandQueue` rather than mutating state directly.

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
