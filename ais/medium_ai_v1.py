"""Medium AI v1 — squad-based bot with aggressive eco, harass, and regrouping.

Modes: base_defense → claiming → defensive → harass
- base_defense: incomplete squads or emergency (CC under heavy damage)
- claiming: complete squads immediately claim unclaimed metal spots (no cap)
- defensive: excess complete squads when all spots are assigned
- harass: complete squads when no unclaimed spots remain — attacks enemy
  extractors or pushes to enemy spawn when we own everything

Key differences from Easy AI v1:
- No claim cooldown — squads claim as soon as they're complete
- Per-spot loss tracking — gives up on a spot after 5+ losses, retries
  once all other spots are taken (threshold increases by 5 each cycle)
- One-time squad regrouping when a new unit joins
- No T2 timer — upgrades as soon as possible
- Faster reaction time (STEP_INTERVAL = 6, ~0.1s @ 60fps)
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

    def alive_units(self, by_id: dict) -> list:
        return [by_id[i] for i in self.unit_ids if i in by_id]


class MediumAIv1(BaseAI):
    ai_id = "medium_v1"
    ai_name = "Medium AI v1"

    # ── tunables ─────────────────────────────────────────────────────────────
    STEP_INTERVAL = 6                 # ticks between decisions (~0.1s @ 60 fps)
    SQUAD_BUILD_ORDER = ("soldier", "soldier", "sniper", "soldier", "medic")
    SQUAD_BUILD_ORDER_LATE = ("soldier", "soldier", "sniper", "soldier", "artillery")
    SQUAD_BUILD_ORDER_ANTI_SNIPER = ("soldier", "sniper", "sniper", "soldier", "medic", "artillery")
    SQUAD_BUILD_ORDER_ANTI_SNIPER_LATE = ("soldier", "sniper", "sniper", "soldier", "artillery", "artillery")
    LATE_SQUAD_THRESHOLD = 3          # squads 4+ use the late comp
    SQUAD_SIZE = 5                    # default squad size (overridden by build order length)
    ANTI_SNIPER_THRESHOLD = 8         # enemy sniper count to trigger anti-sniper comp
    ANTI_SNIPER_HOLD = 2000           # min ticks anti-sniper mode stays active
    BASE_DEFENSE_RADIUS = 100         # ring around CC for idle base-defense units
    ENGAGE_RADIUS = 200               # "enemy nearby" threshold
    EMERGENCY_EXIT_RADIUS = 250       # hysteresis to avoid flapping
    LOW_HP_RATIO = 0.30               # base HP threshold for emergency
    CAPTURE_RADIUS = 15               # = METAL_SPOT_CAPTURE_RADIUS
    DEFENSIVE_IDLE_RADIUS = 30        # how far defenders idle from their anchor
    REISSUE_DIST = 10                 # tolerance for "current target close enough"
    T2_RESEARCH_PRIORITY = ("soldier", "artillery", "sniper")  # lab research order
    REGROUP_DIST = 40                 # max pairwise dist before squad regroups
    INITIAL_LOSS_THRESHOLD = 5        # give up on a spot after this many losses
    HOLD_ALL_TICKS = 2000             # ticks to hold all extractors before harass
    MAX_TOTAL_CLAIM_LOSSES = 5        # shared loss budget across all claiming ops

    def __init__(self):
        super().__init__()
        self._squads: list[_Squad] = []
        self._next_squad_id: int = 1
        self._squad_being_built: _Squad | None = None
        self._seen_unit_ids: set[int] = set()
        self._prev_alive_ids: set[int] = set()
        self._in_emergency: bool = False
        self._last_built_role: str | None = None
        # Eco tracking
        self._claim_losses: dict[int, int] = {}    # spot_id -> total deaths
        self._blacklisted_spots: set[int] = set()
        self._loss_threshold: int = self.INITIAL_LOSS_THRESHOLD
        # Regroup (one-shot per unit add)
        self._squads_needing_regroup: set[int] = set()  # sids
        # Harass gating: hold timer + shared claiming loss budget
        self._hold_all_since: int | None = None   # tick when we first held all extractors
        self._prev_extractor_count: int = 0       # to detect mex losses
        self._total_claim_losses: int = 0         # shared counter across all claiming ops
        # Anti-sniper mode (stays on for at least ANTI_SNIPER_HOLD ticks)
        self._anti_sniper_mode: bool = False
        self._anti_sniper_until: int = 0          # tick when mode is allowed to expire
        # First squad exemption (never pulled back to base_defense)
        self._first_squad_sid: int | None = None
        # Chat
        self._squad_last_chat_mode: dict[int, str] = {}
        self._last_complete_count: int = 0

    # ── lifecycle ────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self._safe_set_build(self._active_build_order()[0])

    def on_step(self, iteration: int) -> None:
        if iteration % self.STEP_INTERVAL != 0:
            return
        cc = self.get_cc()
        if cc is None:
            return

        own_by_id = {u.entity_id: u for u in self.get_own_mobile_units()}
        enemies = self.get_enemy_units()

        self._detect_new_units(own_by_id)
        self._track_claim_losses(own_by_id)
        self._update_claim_blacklist()
        self._check_blacklist_reset()
        self._cull_dead_squads(own_by_id)
        self._update_emergency(cc, enemies)
        self._update_hold_timer(iteration)
        self._update_anti_sniper(enemies)
        self._update_cc_build(own_by_id)
        self._update_t2_upgrades(cc)
        self._track_complete_squads(own_by_id)
        self._issue_squad_orders(cc, enemies, own_by_id)

        self._prev_alive_ids = set(own_by_id.keys())

    # ── phase 1: spawn attribution ───────────────────────────────────────────

    def _detect_new_units(self, own_by_id: dict) -> None:
        """Slot newly-spawned units into the squad that needs them most."""
        for uid in set(own_by_id.keys()) - self._seen_unit_ids:
            u = own_by_id[uid]
            role = self._base_role(u.unit_type)
            candidates = [
                sq for sq in self._squads
                if self._squad_needs_role(sq, role, own_by_id)
            ]
            if candidates:
                candidates.sort(key=lambda sq: (self._missing_count(sq, own_by_id), sq.sid))
                target_sq = candidates[0]
                target_sq.unit_ids.add(uid)
                self._squads_needing_regroup.add(target_sq.sid)
            else:
                sq = self._new_squad()
                sq.unit_ids.add(uid)
                self._squads_needing_regroup.add(sq.sid)
            self._seen_unit_ids.add(uid)

    # ── phase 2: track claim losses ──────────────────────────────────────────

    def _track_claim_losses(self, own_by_id: dict) -> None:
        """Detect units that died since last step and attribute to claim spots."""
        if not self._prev_alive_ids:
            return
        newly_dead = self._prev_alive_ids - set(own_by_id.keys())
        if not newly_dead:
            return
        for sq in self._squads:
            if sq.target_spot_id is None:
                continue
            squad_deaths = newly_dead & sq.unit_ids
            if squad_deaths:
                n = len(squad_deaths)
                spot_id = sq.target_spot_id
                self._claim_losses[spot_id] = self._claim_losses.get(spot_id, 0) + n
                self._total_claim_losses += n

    # ── phase 3: update blacklist ────────────────────────────────────────────

    def _update_claim_blacklist(self) -> None:
        """Blacklist spots where losses exceed threshold; release claiming squads."""
        for sq in self._squads:
            if sq.target_spot_id is None:
                continue
            losses = self._claim_losses.get(sq.target_spot_id, 0)
            if losses > self._loss_threshold:
                self._blacklisted_spots.add(sq.target_spot_id)
                self.send_chat(
                    f"Giving up on resource ({losses} losses)", "team",
                )
                sq.target_spot_id = None

    def _check_blacklist_reset(self) -> None:
        """When all unclaimed spots are blacklisted, raise threshold and retry."""
        if not self._blacklisted_spots:
            return
        unclaimed = self.get_unclaimed_moons()
        if not unclaimed:
            return
        non_blacklisted = [s for s in unclaimed
                           if s.entity_id not in self._blacklisted_spots]
        if not non_blacklisted:
            self._loss_threshold += 5
            self._blacklisted_spots.clear()
            self.send_chat(
                f"Retrying difficult resources (tolerance now {self._loss_threshold})",
                "team",
            )

    # ── phase 4: cull dead squads ────────────────────────────────────────────

    def _cull_dead_squads(self, own_by_id: dict) -> None:
        survivors: list[_Squad] = []
        for sq in self._squads:
            if not sq.unit_ids:
                survivors.append(sq)
                continue
            if any(uid in own_by_id for uid in sq.unit_ids):
                survivors.append(sq)
            else:
                if self._squad_being_built is sq:
                    self._squad_being_built = None
                self._squad_last_chat_mode.pop(sq.sid, None)
                self._squads_needing_regroup.discard(sq.sid)
        self._squads = survivors

    # ── phase 5: emergency mode (with hysteresis) ────────────────────────────

    def _update_emergency(self, cc, enemies: list) -> None:
        hp_ratio = cc.hp / cc.max_hp if cc.max_hp > 0 else 1.0
        if not self._in_emergency:
            if hp_ratio < self.LOW_HP_RATIO and self._any_enemy_within(
                cc.x, cc.y, self.ENGAGE_RADIUS, enemies
            ):
                self._in_emergency = True
                self.send_chat("Base under attack! All squads fall back to defend", "team")
        else:
            if hp_ratio >= self.LOW_HP_RATIO or not self._any_enemy_within(
                cc.x, cc.y, self.EMERGENCY_EXIT_RADIUS, enemies
            ):
                self._in_emergency = False
                self.send_chat("Base secure, resuming normal operations", "team")

    # ── hold timer + extractor loss detection ────────────────────────────────

    def _update_hold_timer(self, iteration: int) -> None:
        """Track how long we've held all metal extractors.

        Resets if we lose an extractor or any squad is still claiming.
        """
        owned = len(self.get_own_metal_extractors())
        total_spots = len(self.get_metal_spots())
        any_claiming = any(sq.target_spot_id is not None for sq in self._squads)

        # Detect mex loss — reset hold timer
        if owned < self._prev_extractor_count:
            self._hold_all_since = None
        self._prev_extractor_count = owned

        # Holding all spots with no active claim?
        if owned >= total_spots and not any_claiming:
            if self._hold_all_since is None:
                self._hold_all_since = iteration
        else:
            self._hold_all_since = None

    # ── anti-sniper mode detection ──────────────────────────────────────────

    def _update_anti_sniper(self, enemies: list) -> None:
        """Toggle anti-sniper comp when enemy has many snipers.

        Once triggered, stays active for at least ANTI_SNIPER_HOLD ticks.
        Re-triggering refreshes the duration.
        """
        now = self._game._iteration if self._game else 0
        enemy_snipers = sum(1 for e in enemies
                            if self._base_role(e.unit_type) == "sniper")
        triggered = enemy_snipers >= self.ANTI_SNIPER_THRESHOLD

        if triggered:
            # (Re-)activate and refresh hold duration
            if not self._anti_sniper_mode:
                self.send_chat(
                    f"Enemy has {enemy_snipers} snipers, switching to artillery comp",
                    "team",
                )
            self._anti_sniper_mode = True
            self._anti_sniper_until = now + self.ANTI_SNIPER_HOLD
        elif self._anti_sniper_mode and now >= self._anti_sniper_until:
            # Hold duration expired and condition no longer met — deactivate
            self._anti_sniper_mode = False
            self.send_chat("Enemy sniper count dropped, resuming normal comp", "team")

    # ── phase 6: CC build queue ──────────────────────────────────────────────

    def _update_cc_build(self, own_by_id: dict) -> None:
        incomplete: list[tuple[int, _Squad]] = []
        for sq in self._squads:
            missing = self._missing_count(sq, own_by_id)
            if missing > 0:
                incomplete.append((missing, sq))

        if incomplete:
            incomplete.sort(key=lambda t: (t[0], t[1].sid))
            sq = incomplete[0][1]
            role = self._next_missing_role(sq, own_by_id)
        else:
            sq = self._new_squad()
            role = self._active_build_order(sq)[0]

        self._squad_being_built = sq
        if role is not None:
            self._safe_set_build(role)

    # ── phase 7: T2 upgrades (no timer lock) ─────────────────────────────────

    def _update_t2_upgrades(self, cc) -> None:
        """Issue research-lab + outpost upgrades as soon as T2 is enabled.

        Research priority: soldier → artillery → sniper.  Only starts
        outposts once all three research labs are built or in progress.
        """
        if not getattr(self._game, "enable_t2", False):
            return

        own_extractors = self.get_own_metal_extractors()
        if not own_extractors:
            return

        # Pick research type for any lab waiting in choosing_research
        for me in own_extractors:
            if me.upgrade_state == "choosing_research":
                next_type = self._next_research_type(own_extractors)
                if next_type is not None:
                    self.set_research_type(me, next_type)

        # Determine which research types are covered (built or in progress)
        covered = self._covered_research_types(own_extractors)
        needed = [t for t in self.T2_RESEARCH_PRIORITY if t not in covered]

        ready = [me for me in own_extractors
                 if me.upgrade_state == "base" and me.is_fully_reinforced]

        if needed:
            # Still need more research labs — build one at a time
            already_upgrading = any(me.upgrade_state in ("upgrading_lab", "choosing_research")
                                    for me in own_extractors)
            if not already_upgrading and ready:
                target = min(ready,
                             key=lambda me: (me.x - cc.x) ** 2 + (me.y - cc.y) ** 2)
                self.upgrade_extractor(target, "research_lab")
            return

        # All research types covered — upgrade remaining to outposts
        for me in ready:
            self.upgrade_extractor(me, "outpost")

    # ── squad tracking (informational only) ──────────────────────────────────

    def _track_complete_squads(self, own_by_id: dict) -> None:
        """Chat when the number of complete squads changes."""
        complete = sum(1 for sq in self._squads
                       if self._is_squad_complete(sq, own_by_id))
        if complete > self._last_complete_count:
            self.send_chat(
                f"{complete} squad{'s' if complete != 1 else ''} ready", "team",
            )
        self._last_complete_count = complete

    # ── phase 8: per-squad orders ────────────────────────────────────────────

    def _issue_squad_orders(self, cc, enemies: list, own_by_id: dict) -> None:
        # One-time chat when shared claiming loss budget is hit
        if (self._total_claim_losses >= self.MAX_TOTAL_CLAIM_LOSSES
                and not getattr(self, '_claim_budget_announced', False)):
            self._claim_budget_announced = True
            self.send_chat(
                f"Lost {self._total_claim_losses} units claiming, switching to harass",
                "team",
            )

        # Precompute defensive anchors + threats once per step
        anchors = self._defensive_anchors(cc)
        defensive_threats = self._enemies_near_any_anchor(anchors, enemies)

        for sq in self._squads:
            living = sq.alive_units(own_by_id)
            if not living:
                continue

            mode = self._classify_squad_mode(sq, cc, own_by_id)

            # One-time regroup when a new unit was added to this squad
            if sq.sid in self._squads_needing_regroup:
                self._squads_needing_regroup.discard(sq.sid)
                if self._squad_needs_regroup(living):
                    # Claiming squads converge at the extractor; others at centroid
                    if mode == "claiming" and sq.target_spot_id is not None:
                        spot = self._spot_by_id(sq.target_spot_id)
                        if spot is not None:
                            gx, gy = spot.x, spot.y
                        else:
                            gx = sum(u.x for u in living) / len(living)
                            gy = sum(u.y for u in living) / len(living)
                    else:
                        gx = sum(u.x for u in living) / len(living)
                        gy = sum(u.y for u in living) / len(living)
                    for u in living:
                        self._maybe_fight(u, gx, gy)
                    continue  # skip normal orders this tick

            # Chat on mode transitions
            prev_mode = self._squad_last_chat_mode.get(sq.sid)
            if mode != prev_mode and living:
                self._squad_last_chat_mode[sq.sid] = mode
                if mode == "claiming":
                    self.send_chat(f"Squad {sq.sid} moving to claim resource", "team")
                elif mode == "harass":
                    self.send_chat(f"Squad {sq.sid} set to harass", "team")
                elif mode == "defensive":
                    self.send_chat(f"Squad {sq.sid} set to defensive", "team")

            if mode == "base_defense":
                self._order_base_defense(sq, cc, enemies, own_by_id)
            elif mode == "claiming":
                self._order_claiming(sq, own_by_id)
            elif mode == "defensive":
                self._order_defensive(sq, cc, anchors, defensive_threats, own_by_id)
            elif mode == "harass":
                self._order_harass(sq, cc, enemies, own_by_id)

    # ── regroup check ────────────────────────────────────────────────────────

    def _squad_needs_regroup(self, living: list) -> bool:
        """True if any pair of units is farther than REGROUP_DIST apart."""
        if len(living) < 2:
            return False
        max_dist_sq = self.REGROUP_DIST ** 2
        for i, a in enumerate(living):
            for b in living[i + 1:]:
                if (a.x - b.x) ** 2 + (a.y - b.y) ** 2 > max_dist_sq:
                    return True
        return False

    # ── mode classifier ──────────────────────────────────────────────────────

    def _classify_squad_mode(self, sq: _Squad, cc, own_by_id: dict) -> str:
        if self._in_emergency:
            return "base_defense"

        living = sq.alive_units(own_by_id)
        if not living:
            return "base_defense"

        # First claim: rush out immediately without waiting for a full squad.
        # Once we own at least one extractor, require a complete squad.
        # "other_claiming" excludes this squad so it doesn't block itself.
        owned_extractors = len(self.get_own_metal_extractors())
        other_claiming = any(s.target_spot_id is not None
                             for s in self._squads if s.sid != sq.sid)
        first_claim = owned_extractors == 0 and not other_claiming
        is_first_squad = sq.sid == self._first_squad_sid

        # The first squad and the first-claim rush are exempt from
        # completeness checks.  For everyone else, require SQUAD_SIZE
        # units (the base minimum — comp swaps won't pull squads back)
        # and a medic only when the active build order includes one.
        if not first_claim and not is_first_squad:
            if len(living) < self.SQUAD_SIZE:
                return "base_defense"
            build = self._active_build_order(sq)
            if "medic" in build and not any(
                self._base_role(u.unit_type) == "medic" for u in living
            ):
                return "base_defense"

        # Currently claiming a spot?
        if sq.target_spot_id is not None:
            spot = self._spot_by_id(sq.target_spot_id)
            if spot is not None and spot.owner != self._team:
                return "claiming"
            # Captured or spot vanished — release
            if spot is not None and spot.owner == self._team:
                self.send_chat(f"Squad {sq.sid} captured resource", "team")
            self._claim_losses.pop(sq.target_spot_id, None)
            sq.target_spot_id = None

        # Try to claim an unclaimed, non-blacklisted spot not already assigned
        already_claimed = {s.target_spot_id for s in self._squads
                           if s.target_spot_id is not None}
        unclaimed = self.get_unclaimed_moons()
        available = [s for s in unclaimed
                     if s.entity_id not in self._blacklisted_spots
                     and s.entity_id not in already_claimed]

        if available:
            target = min(available,
                         key=lambda s: math.hypot(s.x - cc.x, s.y - cc.y))
            sq.target_spot_id = target.entity_id
            if first_claim:
                self._first_squad_sid = sq.sid
            return "claiming"

        # No spot available for this squad
        if unclaimed:
            # Unclaimed spots exist but are all assigned or blacklisted — excess
            return "defensive"

        # All unclaimed spots are taken. Check if we should harass or defend.
        # If we lost a mex (enemy owns some), stay defensive unless claiming
        # has become too costly.
        owned = len(self.get_own_metal_extractors())
        total_spots = len(self.get_metal_spots())
        claiming_too_costly = self._total_claim_losses >= self.MAX_TOTAL_CLAIM_LOSSES

        if claiming_too_costly:
            # Too many losses trying to claim — just go harass
            return "harass"

        if owned < total_spots:
            # We don't own everything (enemy holds some) — stay defensive
            return "defensive"

        # We own all spots. Wait for hold timer before harass.
        now = self._game._iteration if self._game else 0
        if self._hold_all_since is not None and now - self._hold_all_since >= self.HOLD_ALL_TICKS:
            return "harass"

        return "defensive"

    # ── order helpers ────────────────────────────────────────────────────────

    def _order_base_defense(self, sq: _Squad, cc, enemies: list,
                            own_by_id: dict) -> None:
        for u in sq.alive_units(own_by_id):
            target = self._nearest_enemy_within(
                cc.x, cc.y, self.ENGAGE_RADIUS, enemies)
            if target is not None:
                self._maybe_fight(u, target.x, target.y)
            else:
                angle = (u.entity_id * 137 % 360) * math.pi / 180.0
                tx = cc.x + 0.6 * self.BASE_DEFENSE_RADIUS * math.cos(angle)
                ty = cc.y + 0.6 * self.BASE_DEFENSE_RADIUS * math.sin(angle)
                self._maybe_fight(u, tx, ty)

    def _order_claiming(self, sq: _Squad, own_by_id: dict) -> None:
        spot = (self._spot_by_id(sq.target_spot_id)
                if sq.target_spot_id is not None else None)
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
        # Anchor = farthest owned ME from CC, falling back to CC
        if not anchors:
            anchor_x, anchor_y = cc.x, cc.y
        else:
            farthest = max(anchors,
                           key=lambda a: (a[0] - cc.x) ** 2 + (a[1] - cc.y) ** 2)
            anchor_x, anchor_y = farthest

        for u in sq.alive_units(own_by_id):
            if defensive_threats:
                target = min(defensive_threats,
                             key=lambda e: (e.x - u.x) ** 2 + (e.y - u.y) ** 2)
                self._maybe_fight(u, target.x, target.y)
            else:
                angle = (u.entity_id * 137 % 360) * math.pi / 180.0
                tx = anchor_x + self.DEFENSIVE_IDLE_RADIUS * math.cos(angle)
                ty = anchor_y + self.DEFENSIVE_IDLE_RADIUS * math.sin(angle)
                self._maybe_fight(u, tx, ty)

    def _order_harass(self, sq: _Squad, cc, enemies: list,
                      own_by_id: dict) -> None:
        living = sq.alive_units(own_by_id)
        if not living:
            return

        cx = sum(u.x for u in living) / len(living)
        cy = sum(u.y for u in living) / len(living)

        # Priority 1: attack known enemy metal extractors
        all_extractors = self.get_metal_extractors()
        enemy_extractors = [e for e in all_extractors if e.team != self._team]
        if enemy_extractors:
            target = min(enemy_extractors,
                         key=lambda e: (e.x - cx) ** 2 + (e.y - cy) ** 2)
            for u in living:
                self._maybe_fight(u, target.x, target.y)
            return

        # Priority 2: push toward enemy spawn (we own everything)
        spawns = self.get_enemy_spawn_locations()
        if spawns:
            tx, ty = min(spawns,
                         key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
            for u in living:
                self._maybe_fight(u, tx, ty)

    # ── small utilities ──────────────────────────────────────────────────────

    def _new_squad(self) -> _Squad:
        sq = _Squad(sid=self._next_squad_id)
        self._next_squad_id += 1
        self._squads.append(sq)
        return sq

    def _active_build_order(self, sq: _Squad | None = None) -> tuple[str, ...]:
        late = sq is not None and sq.sid > self.LATE_SQUAD_THRESHOLD
        if self._anti_sniper_mode:
            return self.SQUAD_BUILD_ORDER_ANTI_SNIPER_LATE if late else self.SQUAD_BUILD_ORDER_ANTI_SNIPER
        return self.SQUAD_BUILD_ORDER_LATE if late else self.SQUAD_BUILD_ORDER

    def _active_squad_size(self, sq: _Squad | None = None) -> int:
        return len(self._active_build_order(sq))

    @staticmethod
    def _base_role(unit_type: str) -> str:
        """Strip the ``_t2`` suffix so a Marine counts as a soldier slot."""
        return unit_type.removesuffix("_t2")

    def _is_squad_complete(self, sq: _Squad, own_by_id: dict) -> bool:
        living = sq.alive_units(own_by_id)
        if len(living) < self._active_squad_size(sq):
            return False
        have = Counter(self._base_role(u.unit_type) for u in living)
        target = Counter(self._active_build_order(sq))
        for role, n in target.items():
            if have[role] < n:
                return False
        return True

    def _missing_count(self, sq: _Squad, own_by_id: dict) -> int:
        living = sq.alive_units(own_by_id)
        have = Counter(self._base_role(u.unit_type) for u in living)
        target = Counter(self._active_build_order(sq))
        missing = 0
        for role, n in target.items():
            if have[role] < n:
                missing += n - have[role]
        return missing

    def _next_missing_role(self, sq: _Squad, own_by_id: dict) -> str | None:
        """Return the first role still under-represented in the squad."""
        have = Counter(self._base_role(u.unit_type)
                       for u in sq.alive_units(own_by_id))
        for role in self._active_build_order(sq):
            if have[role] > 0:
                have[role] -= 1
            else:
                return role
        return None

    def _squad_needs_role(self, sq: _Squad, role: str, own_by_id: dict) -> bool:
        base_role = self._base_role(role)
        target = Counter(self._active_build_order(sq))
        if base_role not in target:
            return False
        assigned_living = sum(
            1 for uid in sq.unit_ids
            if uid in own_by_id
            and self._base_role(own_by_id[uid].unit_type) == base_role
        )
        return assigned_living < target[base_role]

    def _covered_research_types(self, own_extractors: list) -> set[str]:
        """Return research types that are already built or in progress."""
        covered: set[str] = set()
        for me in own_extractors:
            if me.upgrade_state in ("upgrading_lab", "research_lab",
                                     "choosing_research"):
                if getattr(me, "researched_unit_type", None):
                    covered.add(me.researched_unit_type)
        return covered

    def _next_research_type(self, own_extractors: list) -> str | None:
        """Return the highest-priority research type not yet covered."""
        covered = self._covered_research_types(own_extractors)
        for t in self.T2_RESEARCH_PRIORITY:
            if t not in covered:
                return t
        return None

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
        """Owned metal extractor positions."""
        return [(me.x, me.y) for me in self.get_own_metal_extractors()]

    def _enemies_near_any_anchor(self, anchors: list, enemies: list) -> list:
        """Enemies within ENGAGE_RADIUS of CC or any owned metal extractor."""
        cc = self.get_cc()
        if cc is None:
            return []
        radius_sq = self.ENGAGE_RADIUS ** 2
        check_points = list(anchors) + [(cc.x, cc.y)]
        threats: list = []
        for e in enemies:
            for ax, ay in check_points:
                if (e.x - ax) ** 2 + (e.y - ay) ** 2 <= radius_sq:
                    threats.append(e)
                    break
        return threats

    def _any_enemy_within(self, x: float, y: float, radius: float,
                          enemies: list) -> bool:
        r2 = radius * radius
        for e in enemies:
            if (e.x - x) ** 2 + (e.y - y) ** 2 <= r2:
                return True
        return False

    def _nearest_enemy_within(self, x: float, y: float, radius: float,
                              enemies: list):
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
