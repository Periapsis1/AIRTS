# AIRTS Performance Optimizations

## 3. Nearest-enemy O(N^2) distance matrix (tgt_nearest_enemy — 0.03ms avg, scales badly)

`game.py:640` creates `(N, M, 2)` float64 arrays. At 200v200 = 640KB allocation every
15 ticks. Replace with per-unit QuadField `get_enemy_units_exact()` queries within LOS
range — O(K) per unit where K is nearby enemies, not all enemies.

**Status: TODO**

## 4. Pass QuadField to capture_step (capture — 0.10ms)

`systems/capturing.py` is called with `grid=None`, so it falls back to iterating ALL
units per metal spot. Fix: pass `self._quadfield` as the `grid` argument. The function
already supports spatial queries via `grid.query_radius()` — but QuadField uses
`get_units_exact()`, so either add a `query_radius` adapter or call `get_units_exact`
directly. Trivial change.

**Status: DONE** — Pass `self._quadfield` as `grid` arg; changed `query_radius` to `get_units_exact`.

## 5. Eliminate redundant combatants list in combat_step (combat — 0.10ms)

`systems/combat.py:115` rebuilds `combatants = [u for u in units if u.alive]` every tick.
`alive_units` is already built in `game.py`. Pass it directly to `combat_step()` instead
of `self.units` to skip the redundant filter.

**Status: DONE** — Pass `alive_units` to `combat_step()`; removed redundant list comprehension.

## 6. Multiple list rebuilds every tick (cleanup — 0.03ms + spread overhead)

`alive_units`, `combatants`, `mobile_units`, plus 4 filtered lists in cleanup
(`game.py:753-758`) are rebuilt from scratch via list comprehensions each tick. Maintain
these incrementally — remove dead units at kill time (in `take_damage` or cleanup) using
a dirty flag rather than re-filtering every list every tick.

**Status: TODO**

## 7. Vectorize collision loop entirely (tgt_populate — 0.36ms, still #1 bottleneck)

The collision loop is still pure Python: per-unit QuadField query + per-pair sqrt. Replace
with numpy batch: extract candidate pairs from QuadField into `pair_i`/`pair_j` arrays,
then call `batch_unit_collisions()` (already exists in `core/vectorized.py`). This moves
all sqrt/division/push math into numpy C code.

**Status: TODO**

## 8. Physics array rebuild every tick (phys_array_build — 0.006ms, scales with N)

`game.py:781-786` builds numpy arrays from Python lists every tick even when positions
haven't changed much. Pre-allocate persistent arrays sized to max units, update only
changed indices. Avoids N Python->numpy conversions per tick.

**Status: TODO**

## 9. Batch entity_update simple fields (entity_update overhead)

Every entity does `self.pos = (self.x, self.y)` (tuple alloc, dead code — nothing reads
`unit.pos`), `max(0, laser_cooldown - dt)`, and an empty abilities loop. Remove dead
`pos` assignment. Batch `laser_cooldown` decrement across all units with numpy. Skip
ability loop for units with no abilities (most units).

**Status: TODO**
