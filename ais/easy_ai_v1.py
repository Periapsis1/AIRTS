"""Easy AI v1 — squad-based bot with claim/defend/aggro modes.

The bot organizes its units into 5-unit squads (3 soldiers, 1 sniper, 1 medic)
and runs a per-squad mode state machine: base_defense → claiming → defensive →
aggressive, with an emergency override when the base is taking heavy damage.

Decisions are throttled to once every STEP_INTERVAL game ticks (default 30,
~half a second at 60 fps) to give the bot a deliberately sluggish reaction
time. Override STEP_INTERVAL on a subclass to change its APM.

The mode of each squad is recomputed every step from latched state — this
keeps emergency entry/exit and aggressive-wave promotion clean without ever
having to remember a "previous mode" to restore.
"""
from __future__ import annotations
import math
from collections import Counter
from dataclasses import dataclass, field
from systems.ai.base import BaseAI


@dataclass
class _Squad:
    """A 5-unit fire team. Stores entity_ids only — never live unit refs."""
    sid: int
    unit_ids: set[int] = field(default_factory=set)
    target_spot_id: int | None = None        # set while claiming
    in_aggressive_wave: bool = False         # set when promoted to a wave
    has_been_complete: bool = False          # latches on first 5/5

    def alive_units(self, by_id: dict) -> list:
        return [by_id[i] for i in self.unit_ids if i in by_id]


class EasyAIv1(BaseAI):
    ai_id = "easy_v1"
    ai_name = "Easy AI v1"

    # ── tunables (override on a subclass to retune) ──────────────────────────
    STEP_INTERVAL = 30                # ticks between decisions (~0.5s @ 60 fps)
    SQUAD_BUILD_ORDER = ("soldier", "soldier", "sniper", "soldier", "medic")
    SQUAD_SIZE = 5
    CLAIM_COOLDOWN = 7200             # 2 min @ 60 fps
    BASE_DEFENSE_RADIUS = 100         # ring around CC for idle base-defense units
    ENGAGE_RADIUS = 200               # "enemy nearby" threshold
    EMERGENCY_EXIT_RADIUS = 250       # hysteresis to avoid flapping
    LOW_HP_RATIO = 0.30               # base HP threshold for emergency
    INITIAL_AGGRO_THRESHOLD = 3       # X complete squads -> aggressive wave
    WAVE_ALIVE_THRESHOLD = 1          # squad still in wave while it has any units left
    CAPTURE_RADIUS = 15               # = METAL_SPOT_CAPTURE_RADIUS
    DEFENSIVE_IDLE_RADIUS = 30        # how far defenders idle from their anchor
    REISSUE_DIST = 10                 # tolerance for "current target close enough"
    T2_DELAY_TICKS = 18000            # 5 min @ 60 fps before considering T2
    T2_RESEARCH_UNIT = "soldier"      # what the research lab researches (→ marine)

    def __init__(self):
        super().__init__()
        self._squads: list[_Squad] = []
        self._next_squad_id: int = 1
        self._squad_being_built: _Squad | None = None
        self._seen_unit_ids: set[int] = set()
        self._claiming_squad_id: int | None = None
        self._aggro_threshold: int = self.INITIAL_AGGRO_THRESHOLD
        self._aggressive_wave_sids: set[int] = set()
        self._in_emergency: bool = False
        self._last_built_role: str | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        # Seed the CC with the first build order entry so spawning starts
        # immediately; phase 5 will keep it pointed at the right role.
        self._safe_set_build(self.SQUAD_BUILD_ORDER[0])

    def on_step(self, iteration: int) -> None:
        if iteration % self.STEP_INTERVAL != 0:
            return
        cc = self.get_cc()
        if cc is None:
            return

        own_by_id = {u.entity_id: u for u in self.get_own_mobile_units()}
        enemies = self.get_enemy_units()

        self._detect_new_units(own_by_id)
        self._cull_dead_squads(own_by_id)
        self._check_wave_reset(own_by_id)
        self._update_emergency(cc, enemies)
        self._update_cc_build(own_by_id)
        self._update_t2_upgrades(cc)
        self._issue_squad_orders(cc, enemies, own_by_id)

    # ── phase 1: spawn attribution ───────────────────────────────────────────

    def _detect_new_units(self, own_by_id: dict) -> None:
        """Slot newly-spawned units into the squad that needs them most.

        Classifies by ``unit.unit_type`` (T2-aware) rather than by "what
        we last asked the CC to build", which races with the CC's own
        spawn timer. Uses the same least-missing-first priority as
        phase 5 so a reinforcement spawn always lands on the squad with
        the smallest gap, never on a freshly-created empty squad.
        Aggressive squads are skipped — they're committed and shouldn't
        receive dribbled reinforcements.
        """
        for uid in set(own_by_id.keys()) - self._seen_unit_ids:
            u = own_by_id[uid]
            role = self._base_role(u.unit_type)
            candidates = [
                sq for sq in self._squads
                if not sq.in_aggressive_wave
                and self._squad_needs_role(sq, role, own_by_id)
            ]
            if candidates:
                candidates.sort(key=lambda sq: (self._missing_count(sq, own_by_id), sq.sid))
                candidates[0].unit_ids.add(uid)
            else:
                sq = self._new_squad()
                sq.unit_ids.add(uid)
            self._seen_unit_ids.add(uid)

    # ── phase 2: cull dead squads ────────────────────────────────────────────

    def _cull_dead_squads(self, own_by_id: dict) -> None:
        survivors: list[_Squad] = []
        for sq in self._squads:
            # Keep "fresh" squads that have never been assigned a unit yet —
            # they're valid build targets waiting for the next CC spawn.
            if not sq.unit_ids:
                survivors.append(sq)
                continue
            if any(uid in own_by_id for uid in sq.unit_ids):
                survivors.append(sq)
            else:
                # Squad had units but they're all dead — clean up references
                if self._claiming_squad_id == sq.sid:
                    self._claiming_squad_id = None  # cooldown stays — failed attempt counts
                if self._squad_being_built is sq:
                    self._squad_being_built = None
                self._aggressive_wave_sids.discard(sq.sid)
        self._squads = survivors

    # ── phase 3: wave reset ──────────────────────────────────────────────────

    def _check_wave_reset(self, own_by_id: dict) -> None:
        if not self._aggressive_wave_sids:
            return
        any_alive = False
        for sq in self._squads:
            if sq.sid not in self._aggressive_wave_sids:
                continue
            living = len(sq.alive_units(own_by_id))
            if living >= self.WAVE_ALIVE_THRESHOLD:
                any_alive = True
            else:
                # Promote stragglers out of the wave; classifier will demote
                # them to defensive/base_defense automatically.
                sq.in_aggressive_wave = False
        if not any_alive:
            self._aggro_threshold += 1
            self._aggressive_wave_sids.clear()

    # ── phase 4: emergency mode (with hysteresis) ────────────────────────────

    def _update_emergency(self, cc, enemies: list) -> None:
        hp_ratio = cc.hp / cc.max_hp if cc.max_hp > 0 else 1.0
        if not self._in_emergency:
            if hp_ratio < self.LOW_HP_RATIO and self._any_enemy_within(cc.x, cc.y, self.ENGAGE_RADIUS, enemies):
                self._in_emergency = True
        else:
            if hp_ratio >= self.LOW_HP_RATIO or not self._any_enemy_within(
                cc.x, cc.y, self.EMERGENCY_EXIT_RADIUS, enemies
            ):
                self._in_emergency = False

    # ── phase 5: CC build queue (reinforce → new squad) ──────────────────────

    def _update_cc_build(self, own_by_id: dict) -> None:
        # Sort incomplete squads by least-missing-first (the user's spec).
        # Aggressive squads are skipped — they're committed to their attack
        # and reinforcing them would dribble single units across the map
        # one by one straight into the enemy.
        incomplete: list[tuple[int, _Squad]] = []
        for sq in self._squads:
            if sq.in_aggressive_wave:
                continue
            missing = self._missing_count(sq, own_by_id)
            if missing > 0:
                incomplete.append((missing, sq))

        if incomplete:
            incomplete.sort(key=lambda t: (t[0], t[1].sid))
            sq = incomplete[0][1]
            role = self._next_missing_role(sq, own_by_id)
        else:
            sq = self._new_squad()
            role = self.SQUAD_BUILD_ORDER[0]

        self._squad_being_built = sq
        if role is not None:
            self._safe_set_build(role)

    # ── T2 upgrades (only when enable_t2 + ≥5min in) ─────────────────────────

    def _update_t2_upgrades(self, cc) -> None:
        """Issue research-lab + outpost upgrades when T2 conditions are met.

        Strategy:
        1. Wait until 5 minutes have elapsed and the game has T2 enabled.
        2. The first eligible upgrade goes to a research_lab on the
           extractor closest to our CC, with research_type = soldier
           (which the game maps to the Marine T2 unit).
        3. Once a research lab exists (upgrading or already built),
           every other fully-reinforced extractor upgrades to an outpost.
        Extractors that aren't yet reinforced are skipped — the bot will
        retry on a later tick once Reinforce finishes.
        """
        if not getattr(self._game, "enable_t2", False):
            return
        now = self._game._iteration if self._game else 0
        if now < self.T2_DELAY_TICKS:
            return

        own_extractors = self.get_own_metal_extractors()
        if not own_extractors:
            return

        # Any research lab (built or upgrading)?
        has_lab = any(me.upgrade_state in ("upgrading_lab", "research_lab",
                                            "choosing_research")
                      for me in own_extractors)
        # An extractor in 'choosing_research' needs us to pick a unit_type
        # before it actually starts upgrading.
        for me in own_extractors:
            if me.upgrade_state == "choosing_research":
                self.set_research_type(me, self.T2_RESEARCH_UNIT)

        if not has_lab:
            # Pick the closest fully-reinforced base-state extractor for the lab
            candidates = [me for me in own_extractors
                          if me.upgrade_state == "base" and me.is_fully_reinforced]
            if candidates:
                target = min(candidates,
                             key=lambda me: (me.x - cc.x) ** 2 + (me.y - cc.y) ** 2)
                self.upgrade_extractor(target, "research_lab")
            return  # don't start outposts on the same tick we're picking the lab

        # Lab exists/in-progress — upgrade every other reinforced base extractor to an outpost
        for me in own_extractors:
            if me.upgrade_state == "base" and me.is_fully_reinforced:
                self.upgrade_extractor(me, "outpost")

    # ── phase 6: per-squad orders ────────────────────────────────────────────

    def _issue_squad_orders(self, cc, enemies: list, own_by_id: dict) -> None:
        # Promote complete squads to a new aggressive wave (skipped in emergency)
        if not self._in_emergency:
            self._maybe_promote_to_aggro(own_by_id)

        # Precompute defensive anchors + threats once per step
        anchors = self._defensive_anchors(cc)
        defensive_threats = self._enemies_near_any_anchor(anchors, enemies)

        for sq in self._squads:
            mode = self._classify_squad_mode(sq, cc, own_by_id)
            if mode == "base_defense":
                self._order_base_defense(sq, cc, enemies, own_by_id)
            elif mode == "claiming":
                self._order_claiming(sq, own_by_id)
            elif mode == "defensive":
                self._order_defensive(sq, cc, anchors, defensive_threats, own_by_id)
            elif mode == "aggressive":
                self._order_aggressive(sq, cc, enemies, own_by_id)

    # ── mode classifier (single source of truth) ─────────────────────────────

    def _classify_squad_mode(self, sq: _Squad, cc, own_by_id: dict) -> str:
        if self._in_emergency:
            return "base_defense"

        living = sq.alive_units(own_by_id)
        if not living:
            return "base_defense"  # nothing to command anyway

        # Aggressive squads stay committed even after losing units. Without
        # this short-circuit, a reduced squad would demote to base_defense
        # mid-attack, walk back home to be reinforced, walk out again, and
        # bounce — the "running it down" bug.
        if sq.in_aggressive_wave:
            return "aggressive"

        if len(living) < self.SQUAD_SIZE:
            return "base_defense"
        if not any(self._base_role(u.unit_type) == "medic" for u in living):
            return "base_defense"

        # In-progress claim?
        if sq.sid == self._claiming_squad_id and sq.target_spot_id is not None:
            spot = self._spot_by_id(sq.target_spot_id)
            if spot is not None and spot.owner != self._team:
                return "claiming"
            # Captured (or spot vanished) → release and fall through to defensive
            sq.target_spot_id = None
            self._claiming_squad_id = None

        # Latch first-completion (only used to gate legacy logic; the cap
        # is now count-based so any complete squad can claim if under cap).
        sq.has_been_complete = True

        # Count-based macro cap: at game tick T the bot is allowed to have
        # floor(T / CLAIM_COOLDOWN) + 1 extractors. If owned + currently-
        # claiming is under that ceiling, this squad may start a claim.
        # This naturally allows reclaiming if the bot LOSES an extractor —
        # the user-reported bug with the old time-based cooldown.
        if self._can_start_claim() and self._claiming_squad_id is None:
            spots = self.get_unclaimed_moons()
            if spots:
                target = min(spots, key=lambda s: math.hypot(s.x - cc.x, s.y - cc.y))
                sq.target_spot_id = target.entity_id
                self._claiming_squad_id = sq.sid
                return "claiming"

        return "defensive"

    def _target_extractor_count(self) -> int:
        """Allowed number of owned extractors at the current game tick."""
        now = self._game._iteration if self._game else 0
        return now // self.CLAIM_COOLDOWN + 1

    def _can_start_claim(self) -> bool:
        owned = len(self.get_own_metal_extractors())
        claiming = 1 if self._claiming_squad_id is not None else 0
        return owned + claiming < self._target_extractor_count()

    # ── aggressive wave promotion ────────────────────────────────────────────

    def _maybe_promote_to_aggro(self, own_by_id: dict) -> None:
        if self._aggressive_wave_sids:
            return  # wave already in progress
        complete = [sq for sq in self._squads if self._is_squad_complete(sq, own_by_id)
                    and any(self._base_role(u.unit_type) == "medic"
                            for u in sq.alive_units(own_by_id))]
        if len(complete) < self._aggro_threshold:
            return
        for sq in complete:
            sq.in_aggressive_wave = True
            self._aggressive_wave_sids.add(sq.sid)

    # ── order helpers ────────────────────────────────────────────────────────

    def _order_base_defense(self, sq: _Squad, cc, enemies: list, own_by_id: dict) -> None:
        for u in sq.alive_units(own_by_id):
            target = self._nearest_enemy_within(cc.x, cc.y, self.ENGAGE_RADIUS, enemies)
            if target is not None:
                self._maybe_fight(u, target.x, target.y)
            else:
                # Deterministic spread on a ring around CC
                angle = (u.entity_id * 137 % 360) * math.pi / 180.0
                tx = cc.x + 0.6 * self.BASE_DEFENSE_RADIUS * math.cos(angle)
                ty = cc.y + 0.6 * self.BASE_DEFENSE_RADIUS * math.sin(angle)
                self._maybe_fight(u, tx, ty)

    def _order_claiming(self, sq: _Squad, own_by_id: dict) -> None:
        # NOTE: claimers use plain `move` (not fight) so they don't get pulled
        # out of the 15-unit capture radius by an enemy. They're sitting ducks
        # until the spot is captured — that's intentional per spec ("collect
        # one metal extractor"). The classifier will switch them to defensive
        # the moment spot.owner == self._team.
        spot = self._spot_by_id(sq.target_spot_id) if sq.target_spot_id is not None else None
        if spot is None:
            return
        for u in sq.alive_units(own_by_id):
            d = math.hypot(u.x - spot.x, u.y - spot.y)
            if d > self.CAPTURE_RADIUS - 2:
                self._maybe_move(u, spot.x, spot.y)
            elif u.target is not None:
                self.stop([u.entity_id])

    def _order_defensive(self, sq: _Squad, cc, anchors: list,
                         defensive_threats: list, own_by_id: dict) -> None:
        # Anchor = farthest owned ME from CC, falling back to CC.
        if not anchors:
            anchor_x, anchor_y = cc.x, cc.y
        else:
            farthest = max(anchors, key=lambda a: (a[0] - cc.x) ** 2 + (a[1] - cc.y) ** 2)
            anchor_x, anchor_y = farthest

        for u in sq.alive_units(own_by_id):
            if defensive_threats:
                target = min(defensive_threats,
                             key=lambda e: (e.x - u.x) ** 2 + (e.y - u.y) ** 2)
                self._maybe_fight(u, target.x, target.y)
            else:
                # Idle on a deterministic ring around the anchor instead of
                # piling onto the (solid) anchor — units would otherwise
                # circle endlessly trying to occupy the same tile.
                angle = (u.entity_id * 137 % 360) * math.pi / 180.0
                tx = anchor_x + self.DEFENSIVE_IDLE_RADIUS * math.cos(angle)
                ty = anchor_y + self.DEFENSIVE_IDLE_RADIUS * math.sin(angle)
                self._maybe_fight(u, tx, ty)

    def _order_aggressive(self, sq: _Squad, cc, enemies: list, own_by_id: dict) -> None:
        living = sq.alive_units(own_by_id)
        if not living:
            return
        if enemies:
            # Pick the enemy unit nearest to the squad's centroid
            cx = sum(u.x for u in living) / len(living)
            cy = sum(u.y for u in living) / len(living)
            target = min(enemies, key=lambda e: (e.x - cx) ** 2 + (e.y - cy) ** 2)
            tx, ty = target.x, target.y
        else:
            # No enemies in sight (fog) — push toward nearest known spawn
            spawns = self.get_enemy_spawn_locations()
            if not spawns:
                return
            cx = sum(u.x for u in living) / len(living)
            cy = sum(u.y for u in living) / len(living)
            tx, ty = min(spawns, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        for u in living:
            self._maybe_fight(u, tx, ty)

    # ── small utilities ──────────────────────────────────────────────────────

    def _new_squad(self) -> _Squad:
        sq = _Squad(sid=self._next_squad_id)
        self._next_squad_id += 1
        self._squads.append(sq)
        return sq

    @staticmethod
    def _base_role(unit_type: str) -> str:
        """Strip the ``_t2`` suffix so a Marine counts as a soldier slot.

        Once the bot researches T2 soldiers, the CC keeps spawning when
        ``set_build('soldier')`` is issued but the resulting unit has
        ``unit_type == 'soldier_t2'``. Without this normalization the
        squad logic never recognizes the spawned marines as filling the
        soldier slots, the squad never completes, and every unit piles
        up in base_defense — exactly the user-reported bug.
        """
        return unit_type.removesuffix("_t2")

    def _is_squad_complete(self, sq: _Squad, own_by_id: dict) -> bool:
        living = sq.alive_units(own_by_id)
        if len(living) < self.SQUAD_SIZE:
            return False
        have = Counter(self._base_role(u.unit_type) for u in living)
        target = Counter(self.SQUAD_BUILD_ORDER)
        for role, n in target.items():
            if have[role] < n:
                return False
        return True

    def _missing_count(self, sq: _Squad, own_by_id: dict) -> int:
        living = sq.alive_units(own_by_id)
        have = Counter(self._base_role(u.unit_type) for u in living)
        target = Counter(self.SQUAD_BUILD_ORDER)
        missing = 0
        for role, n in target.items():
            if have[role] < n:
                missing += n - have[role]
        return missing

    def _next_missing_role(self, sq: _Squad, own_by_id: dict) -> str | None:
        """Walk SQUAD_BUILD_ORDER left-to-right; return the first role still
        under-represented in the squad's living roster."""
        have = Counter(self._base_role(u.unit_type) for u in sq.alive_units(own_by_id))
        for role in self.SQUAD_BUILD_ORDER:
            if have[role] > 0:
                have[role] -= 1
            else:
                return role
        return None

    def _squad_needs_role(self, sq: _Squad, role: str, own_by_id: dict) -> bool:
        # Always compare role at the T1 (base) level — Marines fill soldier
        # slots, Priests fill medic slots, Marksmen fill sniper slots.
        base_role = self._base_role(role)
        target = Counter(self.SQUAD_BUILD_ORDER)
        if base_role not in target:
            return False
        assigned_living = sum(
            1 for uid in sq.unit_ids
            if uid in own_by_id
            and self._base_role(own_by_id[uid].unit_type) == base_role
        )
        return assigned_living < target[base_role]

    def _safe_set_build(self, role: str) -> None:
        if role != self._last_built_role:
            self.set_build(role)
            self._last_built_role = role

    def _spot_by_id(self, spot_id: int):
        for s in self.get_metal_spots():
            if s.entity_id == spot_id:
                return s
        return None

    def _defensive_anchors(self, cc) -> list[tuple[float, float]]:
        """Owned metal extractor positions (no CC fallback — caller handles)."""
        return [(me.x, me.y) for me in self.get_own_metal_extractors()]

    def _enemies_near_any_anchor(self, anchors: list, enemies: list) -> list:
        """Enemies within ENGAGE_RADIUS of CC OR any owned metal extractor."""
        cc = self.get_cc()
        if cc is None:
            return []
        radius_sq = self.ENGAGE_RADIUS ** 2
        # CC is always an anchor for "near base" detection
        check_points = list(anchors) + [(cc.x, cc.y)]
        threats: list = []
        for e in enemies:
            for ax, ay in check_points:
                if (e.x - ax) ** 2 + (e.y - ay) ** 2 <= radius_sq:
                    threats.append(e)
                    break
        return threats

    def _any_enemy_within(self, x: float, y: float, radius: float, enemies: list) -> bool:
        r2 = radius * radius
        for e in enemies:
            if (e.x - x) ** 2 + (e.y - y) ** 2 <= r2:
                return True
        return False

    def _nearest_enemy_within(self, x: float, y: float, radius: float, enemies: list):
        r2 = radius * radius
        best = None
        best_d = r2
        for e in enemies:
            d = (e.x - x) ** 2 + (e.y - y) ** 2
            if d <= best_d:
                best = e
                best_d = d
        return best

    def _maybe_fight(self, u, x: float, y: float) -> None:
        """Re-issue a fight order only if the unit's target is None or far off."""
        if u.target is None:
            self.fight_unit(u, x, y)
            return
        cur_x, cur_y = u.target
        if (cur_x - x) ** 2 + (cur_y - y) ** 2 > self.REISSUE_DIST ** 2:
            self.fight_unit(u, x, y)

    def _maybe_move(self, u, x: float, y: float) -> None:
        if u.target is None:
            self.move_unit(u, x, y)
            return
        cur_x, cur_y = u.target
        if (cur_x - x) ** 2 + (cur_y - y) ** 2 > self.REISSUE_DIST ** 2:
            self.move_unit(u, x, y)
