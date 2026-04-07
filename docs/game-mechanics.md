# Game Mechanics

## Objective

Destroy the enemy team's **Command Center** (CC). Each team starts with one CC; the game ends when a CC reaches 0 HP.

## Command Centers

| Property           | Value                      |
|--------------------|----------------------------|
| HP                 | 1000                       |
| Spawn interval     | 10 seconds (base)          |
| Spawn radius       | 50 px around the CC        |
| Healing aura radius| 40 px                      |
| Healing aura rate  | 5 HP/s to nearby friendly units |
| Defensive laser range | 75 px                   |
| Defensive laser damage | 20                      |
| Defensive laser cooldown | 1.0 s                 |
| Default spawn type | Soldier                    |

Command Centers are hexagonal structures placed symmetrically on opposite sides of the map. They automatically:
- **Spawn units** of the selected type every 10 seconds (boosted by metal extractors).
- **Heal nearby friendly units** within 40 px at 5 HP/s.
- **Fire a defensive laser** at the closest enemy within 75 px, dealing 20 damage with a 1-second cooldown.
- **Send newly spawned units to a rally point**, if one is set.

CCs start with a full spawn timer so the first unit spawns immediately.

## Units

There are eight unit types plus T2 variants of each:

### Tier 1 Units

| Type            | HP  | Speed | Radius | Damage | Range | Cooldown | Special                                           |
|-----------------|-----|-------|--------|--------|-------|----------|---------------------------------------------------|
| Soldier         | 100 | 40    | 5      | 10     | 50    | 1.5 s    | Basic all-rounder                                 |
| Medic           | 50  | 40    | 5      | —      | 50    | 0.3 s    | Heals nearby allies with a heal laser             |
| Tank            | 250 | 20    | 7      | 7      | 50    | 2.0 s    | High HP, larger radius; **ReactiveArmor** passive |
| Sniper          | 50  | 30    | 5      | 35     | 140   | 6.0 s    | Long range, high damage, fragile; **Focus** passive |
| Machine Gunner  | 70  | 40    | 5      | 1      | 50    | 0.1 s    | Very fast fire rate, low per-shot damage          |
| Scout           | 15  | 90    | 4      | 4      | 15    | 0.5 s    | Spawns 3 per spawn cycle; fast but fragile        |
| Shockwave       | 70  | 30    | 5      | 7      | 60    | 3.0 s    | Chain laser — bounces to nearby enemies (70 px)   |
| Artillery       | 50  | 20    | 10     | 100    | 160   | 6.0 s    | Massive splash (40 px radius); **friendly fire**; charge time 2 s |

### Tier 2 Units

T2 units are upgraded variants unlocked by building a **Research Lab** from a captured metal extractor. All T2 variants are suffixed `_t2` (e.g. `"soldier_t2"`).

| Type               | HP  | Speed | Damage | Range | Cooldown | Key changes vs T1                                       |
|--------------------|-----|-------|--------|-------|----------|---------------------------------------------------------|
| `soldier_t2`       | 125 | 42    | 15     | 55    | 1.4 s    | More HP, damage, and range                              |
| `medic_t2`         | 75  | 60    | —      | 70    | 0.2 s    | Faster and longer-ranged healer                         |
| `tank_t2`          | 400 | 20    | 7      | 50    | 2.0 s    | More HP; **ElectricArmor** passive                      |
| `sniper_t2`        | 65  | 35    | 45     | 150   | 5.0 s    | More HP and damage, faster fire                         |
| `machine_gunner_t2`| 80  | 30    | 3      | 75    | 0.1 s    | More HP, longer range, higher damage per shot           |
| `scout_t2`         | 12  | 110   | 5      | 30    | 0.3 s    | Spawns 6 per cycle; even faster                         |
| `shockwave_t2`     | 50  | 30    | 15     | 90    | 3.0 s    | Higher damage and range; shorter chain range (50 px)    |
| `artillery_t2`     | 120 | 15    | 100    | 180   | 6.0 s    | More HP, longer range; massive splash (75 px); charge 3 s |

### Medic Details

- Fires a **heal laser** (`hits_only_friendly = True`) that heals nearby allies instead of damaging them.
- Damage value is negative (−1 per tick at 0.3 s cooldown = effectively heals ~3.3 HP/s per shot).
- Prioritizes the closest wounded allies within 50 px.

### Scout Details

- Spawns **3 units** per CC spawn cycle (T2: **6 units**).
- Very short attack range (15 px / 30 px T2) — effective at swarming, not dueling.

### Shockwave / Chain Laser

- On each attack, the laser **chains** to additional enemies within the chain range (70 px / 50 px T2).
- Chain delay between bounces: 0.2 s (T2: 0.1 s).

### Artillery Details

- Has a **charge time** of 2 s (T2: 3 s) before each shot fires.
- **Splash damage** hits all units (friend and foe) within the blast radius.
- Very narrow field of view (15°) and slow turn rate (45°/s) — requires facing the target.

## Combat

### Laser Attacks

All combat is resolved through laser attacks. When a unit or CC fires:
1. The attacker checks for enemies within its attack range.
2. A **line-of-sight (LOS)** check ensures no obstacles block the shot.
3. If a valid target is found, the target takes damage immediately and a laser flash visual is spawned.
4. The attacker enters cooldown and cannot fire again until the cooldown elapses.

### Fire Modes

Units have three fire modes that control targeting behavior:

| Mode          | Constant       | Behavior                                                            |
|---------------|----------------|---------------------------------------------------------------------|
| **Free Fire** | `FREE_FIRE`    | Prefer the assigned `attack_target`; otherwise shoot the closest enemy in range. This is the default. |
| **Target Fire** | `TARGET_FIRE` | Only fire at the assigned `attack_target`. Do nothing if no target is assigned or it's out of range. |
| **Hold Fire** | `HOLD_FIRE`    | Never fire, regardless of nearby enemies.                           |

Fire mode constants are imported from `entities.unit`:
```python
from entities.unit import HOLD_FIRE, TARGET_FIRE, FREE_FIRE
```

### CC Defensive Laser

Command Centers always fire at the closest enemy within range (75 px). They do not use fire modes — they behave like permanent Free Fire.

## Passive Abilities

Certain unit types carry passive abilities that activate automatically.

| Ability         | Unit         | Effect                                                                                     |
|-----------------|--------------|--------------------------------------------------------------------------------------------|
| **ReactiveArmor** | Tank (T1)  | Gains a charge every 5 s (max 2). Each charge reduces incoming damage by 50%. Loses all charges when hit. |
| **ElectricArmor** | Tank T2    | Gains a stack every 1 s (max 8). Each stack: 60% damage reduction, +1 HP/s regen, +20% speed. Loses one stack per hit. |
| **Focus**         | Sniper (T1) | After firing, speed drops to 25% and gradually recovers over 3 seconds.                  |
| **Reinforce**     | Metal Extractor | Builds plating stacks over time (4 stacks, 15 s each). At full stacks, gains +100 HP and doubles spawn bonus. |

## Metal Spots & Extractors

Metal spots are neutral resource nodes scattered symmetrically across the map. Capturing them boosts your CC's spawn rate.

### Capture Mechanics

1. Metal spots have a **capture radius** of **15 px**.
2. The capture progress is a float from **-1.0** (Team 2) to **+1.0** (Team 1).
3. Each frame, progress changes by `(team1_units - team2_units) * 0.05 * dt`, where the count only includes units within the capture radius.
4. When progress reaches +1.0 or -1.0, a **Metal Extractor** is built on the spot for that team.
5. Once claimed, a spot cannot be re-contested (the extractor must be destroyed first).

### Metal Extractor Stats

| Property        | Value  |
|-----------------|--------|
| HP              | 150    |
| Spawn boost     | +8% additive per extractor |

Each extractor owned by a CC adds an 8% multiplicative boost to the CC's spawn timer rate. Metal extractors are **selectable** — clicking one shows its health bar and info.

### T2 Extractor Upgrades

A captured metal extractor can be upgraded (when T2 is enabled) into one of two structures:

| Structure        | Effect                                                   |
|------------------|----------------------------------------------------------|
| **Outpost**      | Fires a defensive laser (75 px range, 15 dmg, 2 s CD); heals self at 1 HP/s; extended line of sight; +20% spawn bonus |
| **Research Lab** | Enables T2 unit spawns from the CC; +20% spawn bonus; +100 CC max HP |

Upgrades take 60 seconds to complete during which the extractor provides no spawn bonus.

## Map Layout

The `DefaultMapGenerator` creates maps with:
- **Two Command Centers** placed symmetrically: Team 1 at `(80, height/2)`, Team 2 at `(width-80, height/2)`.
- **2–4 metal spot pairs** placed randomly in the left half of the map, then mirrored to the right half (point symmetry around the map center).
- **4–8 random obstacles** (mix of rectangles and circles) scattered across the map.

Default map size is **800 x 600** pixels.

## Player Controls (Human Teams)

### Selection
- **Left-click** a unit, CC, or metal extractor to select it (deselects others).
- **Left-click + drag** to draw a circle selection. All units inside are selected. If only a CC is enclosed, it is selected instead.
- **Shift + click/drag** adds to the current selection without deselecting.

### Movement & Commands
- **Right-click** to move selected units to that point.
- **Right-click + drag** to draw a path. Selected units are distributed evenly along the path.
- When a CC is selected, right-click sets a **rally point** — newly spawned units will automatically move there.

### Spawn Type Selection
- When a CC is selected, a GUI panel appears at the bottom of the screen with buttons for each unit type.
- Click a button to change which unit type the CC will spawn next.

### Camera
- **Edge pan** — move the mouse to the screen edge to pan the camera.
- **Scroll wheel** — zoom in/out.

### Other
- **Escape** quits the game.
