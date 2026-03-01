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

There are five unit types, each with different stats and roles:

| Type            | HP  | Speed | Radius | Damage | Range | Cooldown | Special                                    |
|-----------------|-----|-------|--------|--------|-------|----------|--------------------------------------------|
| Soldier         | 100 | 40    | 5      | 10     | 50    | 2.0 s    | Basic all-rounder                          |
| Medic           | 100 | 40    | 5      | 0      | 0     | —        | Heals 2 nearest allies at 5 HP/s within 40 px |
| Tank            | 300 | 20    | 7      | 5      | 50    | 2.0 s    | High HP, larger radius, low damage         |
| Sniper          | 50  | 40    | 5      | 30     | 150   | 6.0 s    | Long range, high damage, fragile           |
| Machine Gunner  | 70  | 40    | 5      | 1      | 50    | 0.2 s    | Very fast fire rate, low per-shot damage   |

### Medic Details

- Cannot attack (damage = 0, `can_attack = False`).
- Heals up to **2** friendly units simultaneously within **40 px** at **5 HP/s** each.
- Prioritizes the closest wounded allies.

## Combat

### Laser Attacks

All combat is resolved through laser attacks. When a unit or CC fires:
1. The attacker checks for enemies within its attack range.
2. A **line-of-sight (LOS)** check ensures no obstacles block the shot (using line-circle and line-rect intersection tests).
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
| HP              | 200    |
| Spawn boost     | 1.05x per extractor (multiplicative) |

Each extractor owned by a CC multiplies the CC's spawn timer rate by **1.05**. With 3 extractors, the timer advances at `1.05^3 ≈ 1.157x` speed.

When a metal extractor is destroyed, the metal spot is released and becomes capturable again.

## Map Layout

The `DefaultMapGenerator` creates maps with:
- **Two Command Centers** placed symmetrically: Team 1 at `(80, height/2)`, Team 2 at `(width-80, height/2)`.
- **2–4 metal spot pairs** placed randomly in the left half of the map, then mirrored to the right half (point symmetry around the map center).
- **4–8 random obstacles** (mix of rectangles and circles) scattered across the map.

Default map size is **800 x 600** pixels.

## Player Controls (Human Teams)

### Selection
- **Left-click** a unit or CC to select it (deselects others).
- **Left-click + drag** to draw a circle selection. All units inside are selected. If only a CC is enclosed, it is selected instead.
- **Shift + click/drag** adds to the current selection without deselecting.

### Movement & Commands
- **Right-click** to move selected units to that point.
- **Right-click + drag** to draw a path. Selected units are distributed evenly along the path.
- When a CC is selected, right-click sets a **rally point** — newly spawned units will automatically move there.

### Spawn Type Selection
- When a CC is selected, a GUI panel appears at the bottom of the screen with buttons for each unit type.
- Click a button to change which unit type the CC will spawn next.

### Other
- **Escape** quits the game.
