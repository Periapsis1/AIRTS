# AIRTS Performance Optimizations

## Baseline (60v60 null AI, 10min)

| Subsystem | Original | Current | Change |
|-----------|----------|---------|--------|
| step_ms | 0.465 | 0.256 | -45% |
| tgt_populate | 0.198 | 0.008 | -96% |
| capture | 0.021 | 0.011 | -48% |
| tgt_qf_sync | 0.079 | 0.077 | ~same |
| entity_update | 0.045 | 0.043 | ~same |
| combat | 0.029 | 0.028 | ~same |
| physics | 0.032 | 0.031 | ~same |
| bookkeeping | 0.029 | 0.027 | ~same |
| tgt_nearest_enemy | 0.013 | 0.012 | ~same |
| cleanup | 0.011 | 0.011 | ~same |

---

## Completed

### 4. Pass QuadField to capture_step (capture — 0.021ms → 0.011ms)

Pass `self._quadfield` as `grid` arg to `capture_step()`; changed `query_radius` to
`get_units_exact`. Now only checks units near each metal spot instead of all units.

### 5. Eliminate redundant combatants list in combat_step

Pass `alive_units` to `combat_step()` instead of `self.units`; removed redundant
`combatants = [u for u in units if u.alive]` list comprehension.

### 7. Cython collision pass (tgt_populate — 0.198ms → 0.008ms, 25x speedup)

Replaced Python QuadField query + per-pair math loop with `core/fast_collisions.pyx`.
Single Cython function builds its own spatial hash via counting sort (pure C, no Python
dicts) and resolves all collisions in one pass. Only Python crossing is reading/writing
unit attributes at boundaries. Build: `python setup_cython.py build_ext --inplace`.

### 7b. Rejected approaches

- **Numpy batch** (pair extraction → `batch_unit_collisions`): Array construction +
  `np.add.at` scatter overhead exceeded savings at 120 units. +47% regression.
- **Cython resolve only** (pair extraction in Python, math in Cython): Setup overhead
  (dict building, pair list → numpy) still dominated. No improvement.

---

## TODO — Current bottlenecks (ordered by avg ms)

### 10. Cythonize tgt_qf_sync (0.077ms — #1 bottleneck)

`game.py:625` calls `qf.moved_unit(u)` for every alive unit every tick. The method does
`get_quads` (Python int math + list append) then set diff for cell updates. ~95% of calls
early-out (unit hasn't crossed a cell boundary), but the Python method call overhead per
unit still adds up at 120 units.

**Options:**
- Cythonize `moved_unit` + `get_quads` as a standalone function operating on flat arrays
- Or: reduce sync frequency (every 2-3 ticks) since combat/capture don't need
  frame-perfect positions — QuadField is only used for those systems now, not collisions

**Status: TODO**

### 11. Batch entity_update (0.043ms — #2 bottleneck)

`game.py:710` calls `entity.update(dt)` for every entity. For units, `update()` does:
- `self.pos = (self.x, self.y)` — dead code, nothing reads `unit.pos` → **remove**
- `max(0, laser_cooldown - dt)` — could batch with numpy across all units
- Empty `abilities` loop for most units → skip when `len(abilities) == 0`
- `_update_follow()` — early-outs for most units (no follow target)
- `_update_movement(dt)` — movement + steering, the real work

The `pos` removal and abilities skip are free wins. Batching cooldown and movement would
require more effort but movement includes per-unit obstacle steering which is hard to
vectorize.

**Status: TODO**

### 12. Physics subsystem overhead (0.031ms)

`phys_array_build` (0.002ms) rebuilds numpy arrays from Python lists every tick. The
obstacle push is already vectorized. Pre-allocating persistent arrays and updating only
changed indices would save the rebuild cost but gains are small.

**Status: TODO (low priority)**

### 13. Combat step (0.028ms)

Already receiving `alive_units`. The per-unit loop does LOS checks, FOV checks, and
distance calculations. Could benefit from the same Cython treatment as collisions:
extract unit data into C arrays, do all targeting math in C, write back results.
Harder than collisions because of the weapon/ability/chain-lightning complexity.

**Status: TODO (medium effort)**

### 14. Bookkeeping overhead (0.027ms)

Includes laser flash updates, replay recording, win condition checks, stats sampling.
Mostly irreducible overhead. Laser flash list filtering could use in-place removal
instead of list comprehension rebuild.

**Status: TODO (low priority)**

### 15. Cleanup list rebuilds (0.011ms)

`game.py:774-779` rebuilds 6 lists via comprehension every tick. Could use a dirty flag
(set when a unit dies) to skip rebuilds on ticks with no deaths. Most ticks have zero
deaths, so this would skip the work ~95% of the time.

**Status: TODO**

### 16. tgt_nearest_enemy scaling (0.012ms now, O(N²) at scale)

Currently vectorized with numpy every 15 ticks. At 60v60 this is fine, but the
`(N, M, 2)` distance matrix will dominate at 200v200+. Could replace with QuadField
`get_enemy_units_exact()` queries within LOS range — O(K) per unit where K is nearby
enemies instead of all enemies.

**Status: TODO (only matters at higher unit counts)**

---

## Build notes — Cython extensions

The game runs fine without Cython (falls back to pure Python), but building the
extensions gives a significant speedup on the collision system.

### Requirements

- **Python packages:** `cython` in the project venv
- **C compiler:**
  - Windows: MSVC (install "Desktop development with C++" via Visual Studio Installer)
  - Linux: `gcc` / `build-essential`
  - macOS: Xcode command-line tools (`xcode-select --install`)

### Build

```bash
# Install Cython (one-time)
./venv/Scripts/pip install cython   # Windows
# or: ./venv/bin/pip install cython  # Linux/macOS

# Build extensions in-place
./venv/Scripts/python setup_cython.py build_ext --inplace   # Windows
# or: ./venv/bin/python setup_cython.py build_ext --inplace  # Linux/macOS
```

This compiles `core/fast_collisions.pyx` → `.pyd` (Windows) or `.so` (Linux/macOS)
into the `core/` directory. The game auto-detects the extension at import time.

### Rebuild

Re-run the build command after editing any `.pyx` file. If the old `.pyd`/`.so` is
locked (game still running), close the game first.

### What's excluded from git

`.gitignore` excludes build artifacts: `*.pyd`, `*.so`, `core/*.c`, `build/`.
Only the `.pyx` source and `setup_cython.py` are tracked.
