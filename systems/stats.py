"""Game statistics: running counters, time-series snapshots, and score calculation."""
from __future__ import annotations
import os
from datetime import datetime
from typing import Any

from config.settings import CC_HP
from core.paths import app_path as _app_path


class TeamStats:
    """Running counters and time-series arrays for one team."""

    # Number of recent samples to smooth instantaneous APM over.
    # 6 samples * SAMPLE_INTERVAL(100) / 60tps ≈ 10s window.
    APM_INST_WINDOW = 6

    def __init__(self):
        # Running counters (updated every tick by systems)
        self.damage_dealt: float = 0.0
        self.damage_taken: float = 0.0
        self.healing_done: float = 0.0
        self.units_killed: int = 0
        self.units_lost: int = 0
        self.units_spawned: int = 0
        self.metal_spots_captured: int = 0
        self.actions: int = 0
        self.build_order: list[dict] = []  # {team, unit_type, tick, player_id}

        # Time-series snapshots (sampled every 60 ticks)
        self.ts_cc_health: list[float] = []
        self.ts_army_count: list[int] = []
        self.ts_units_killed: list[int] = []
        self.ts_damage_dealt: list[float] = []
        self.ts_healing_done: list[float] = []
        self.ts_metal_spots: list[int] = []    # legacy: extractor count
        self.ts_build_pct: list[float] = []    # actual build % bonus
        self.ts_apm: list[float] = []          # cumulative rolling-average APM
        self.ts_apm_inst: list[float] = []     # smoothed instantaneous APM

        # Internal APM tracking
        self._actions_at_last_sample: int = 0
        self._action_deltas: list[int] = []  # rolling window of per-sample deltas


class GameStats:
    """Accumulates game statistics for both teams."""

    SAMPLE_INTERVAL = 100  # ticks between time-series snapshots (~1.67s at 60 tps)

    def __init__(self, teams=(1, 2)):
        self.teams: dict[int, TeamStats] = {t: TeamStats() for t in teams}
        self.timestamps: list[int] = []
        self._finalized = False
        self._step_times_buf: list[float] = []
        self.ts_step_ms: list[float] = []

        # Per-subsystem timing breakdown (ms)
        self._subsystem_names = [
            "commands", "entity_update",
            "ai_step", "capture",
            "tgt_qf_sync", "tgt_nearest_enemy", "tgt_populate",
            "combat",
            "spawn", "cleanup", "physics",
            "phys_array_build", "phys_unit_collisions",
            "phys_obstacle_push", "phys_writeback", "phys_clamp",
            "bookkeeping",
        ]
        self._subsystem_bufs: dict[str, list[float]] = {n: [] for n in self._subsystem_names}
        self.ts_subsystems: dict[str, list[float]] = {n: [] for n in self._subsystem_names}

    # -- recording helpers (called by systems) --------------------------------

    def record_damage(self, attacker_team: int, target_team: int, amount: float):
        self.teams[attacker_team].damage_dealt += amount
        self.teams[target_team].damage_taken += amount

    def record_kill(self, killer_team: int, victim_team: int):
        self.teams[killer_team].units_killed += 1
        self.teams[victim_team].units_lost += 1

    def record_healing(self, team: int, amount: float):
        self.teams[team].healing_done += amount

    def record_spawn(self, team: int, unit_type: str, tick: int, player_id: int | None = None):
        self.teams[team].units_spawned += 1
        entry: dict = {"team": team, "unit_type": unit_type, "tick": tick}
        if player_id is not None:
            entry["player_id"] = player_id
        self.teams[team].build_order.append(entry)

    def record_capture(self, team: int):
        self.teams[team].metal_spots_captured += 1

    def record_action(self, team: int):
        self.teams[team].actions += 1

    def record_step_time(self, ms: float):
        self._step_times_buf.append(ms)

    def record_subsystem(self, name: str, ms: float):
        buf = self._subsystem_bufs.get(name)
        if buf is not None:
            buf.append(ms)

    # -- time-series sampling -------------------------------------------------

    def sample_tick(self, tick: int, entities: list):
        """Snapshot current state into time-series arrays.

        Called from Game.step() every SAMPLE_INTERVAL ticks.
        """
        from entities.unit import Unit
        from entities.command_center import CommandCenter

        self.timestamps.append(tick)
        elapsed_minutes = max(tick / 3600.0, 1 / 3600.0)  # 60 ticks/sec

        # Average step time for this sample interval
        if self._step_times_buf:
            avg = sum(self._step_times_buf) / len(self._step_times_buf)
            self.ts_step_ms.append(round(avg, 3))
            self._step_times_buf.clear()
        else:
            self.ts_step_ms.append(0.0)

        # Per-subsystem averages
        for name in self._subsystem_names:
            buf = self._subsystem_bufs[name]
            if buf:
                self.ts_subsystems[name].append(round(sum(buf) / len(buf), 3))
                buf.clear()
            else:
                self.ts_subsystems[name].append(0.0)

        for team_id, ts in self.teams.items():
            # CC health and build % bonus
            cc_hp = 0.0
            build_pct = 0.0
            for e in entities:
                if isinstance(e, CommandCenter) and e.alive and e.team == team_id:
                    cc_hp = e.hp
                    build_pct = e.get_total_bonus_percent()
                    break
            ts.ts_cc_health.append(cc_hp)
            ts.ts_build_pct.append(build_pct)

            # Army count (exclude buildings)
            army = sum(
                1 for e in entities
                if isinstance(e, Unit) and e.alive and e.team == team_id
                and not getattr(e, 'is_building', False)
            )
            ts.ts_army_count.append(army)

            # Cumulative counters
            ts.ts_units_killed.append(ts.units_killed)
            ts.ts_damage_dealt.append(ts.damage_dealt)
            ts.ts_healing_done.append(ts.healing_done)
            ts.ts_metal_spots.append(ts.metal_spots_captured)

            # APM — cumulative rolling average
            apm = ts.actions / elapsed_minutes
            ts.ts_apm.append(round(apm, 1))

            # APM — smoothed instantaneous (actions per minute over the trailing window).
            # We always divide by the *full* window length so early samples ramp up
            # from zero instead of spiking (1 action / 1.67s ≠ 36 APM at t=0).
            delta = ts.actions - ts._actions_at_last_sample
            ts._actions_at_last_sample = ts.actions
            ts._action_deltas.append(delta)
            if len(ts._action_deltas) > TeamStats.APM_INST_WINDOW:
                ts._action_deltas.pop(0)
            window_actions = sum(ts._action_deltas)
            full_window_minutes = (TeamStats.APM_INST_WINDOW * self.SAMPLE_INTERVAL) / 3600.0
            inst_apm = window_actions / full_window_minutes if full_window_minutes > 0 else 0.0
            ts.ts_apm_inst.append(round(inst_apm, 1))

    # -- score calculation ----------------------------------------------------

    def compute_score(self, team: int, entities: list, winner: int) -> int:
        """SC2-style fun score. Unbounded — longer games yield higher scores."""
        from entities.unit import Unit
        from entities.command_center import CommandCenter

        ts = self.teams[team]

        kill_score = ts.units_killed * 50
        damage_score = ts.damage_dealt / 20
        economy = ts.metal_spots_captured * 100
        units_alive = sum(
            1 for e in entities
            if isinstance(e, Unit) and e.alive and e.team == team
            and not getattr(e, 'is_building', False)
        )
        survival = units_alive * 25
        healing = ts.healing_done / 10

        cc_hp = 0.0
        max_hp = CC_HP
        for e in entities:
            if isinstance(e, CommandCenter) and e.alive and e.team == team:
                cc_hp = e.hp
                break
        cc_bonus = (cc_hp / max_hp) * 200 if max_hp > 0 else 0

        win_bonus = 500 if winner == team else 0

        total = (kill_score + damage_score + economy + survival
                 + healing + cc_bonus + win_bonus)
        return int(total)

    # -- finalization ---------------------------------------------------------

    def finalize(self, winner: int, entities: list) -> dict[str, Any]:
        """Produce the final stats dict for embedding in results/replays."""
        self._finalized = True

        duration_ticks = self.timestamps[-1] if self.timestamps else 0
        duration_seconds = round(duration_ticks / 60.0, 1)

        teams_data: dict[str, dict] = {}
        final_data: dict[str, dict] = {}

        for team_id, ts in self.teams.items():
            key = str(team_id)
            teams_data[key] = {
                "cc_health": ts.ts_cc_health,
                "army_count": ts.ts_army_count,
                "units_killed": ts.ts_units_killed,
                "damage_dealt": [round(v, 1) for v in ts.ts_damage_dealt],
                "healing_done": [round(v, 1) for v in ts.ts_healing_done],
                "metal_spots": ts.ts_build_pct,
                "apm": ts.ts_apm,
                "apm_inst": ts.ts_apm_inst,
            }

            score = self.compute_score(team_id, entities, winner)
            final_data[key] = {
                "score": score,
                "units_killed": ts.units_killed,
                "units_lost": ts.units_lost,
                "units_spawned": ts.units_spawned,
                "damage_dealt": round(ts.damage_dealt, 1),
                "damage_taken": round(ts.damage_taken, 1),
                "healing_done": round(ts.healing_done, 1),
                "metal_spots_captured": ts.metal_spots_captured,
                "actions": ts.actions,
                "build_order": list(ts.build_order),
            }

        return {
            "timestamps": self.timestamps,
            "teams": teams_data,
            "final": final_data,
            "game_duration_seconds": duration_seconds,
            "step_ms": self.ts_step_ms,
            "subsystem_ms": {k: list(v) for k, v in self.ts_subsystems.items()},
        }

    # -- post-game log --------------------------------------------------------

    _LOG_DIR = _app_path("logs")

    def save_summary_log(
        self,
        stats_data: dict[str, Any],
        winner: int,
        team_names: dict[int, str] | None = None,
    ) -> str:
        """Write a human-readable game summary + debug performance table to a log file.

        Returns the filepath of the written log.
        """
        os.makedirs(self._LOG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self._LOG_DIR, f"game_summary_{ts}.log")

        lines: list[str] = []
        lines.append("AIRTS — Post-Game Summary")
        lines.append(f"Date: {datetime.now().isoformat(timespec='seconds')}")
        lines.append("=" * 64)

        # -- Match overview --
        duration = stats_data.get("game_duration_seconds", 0)
        m, s = divmod(int(duration), 60)
        lines.append(f"\nMatch Duration : {m}m {s:02d}s  ({duration}s)")

        if winner > 0:
            winner_label = (team_names or {}).get(winner, f"Team {winner}")
            lines.append(f"Winner        : {winner_label}  (Team {winner})")
        elif winner == -1:
            lines.append("Winner        : Draw")
        else:
            lines.append("Winner        : Undecided")

        # -- Per-team stats --
        final = stats_data.get("final", {})
        for team_id in sorted(final, key=int):
            tf = final[team_id]
            name = (team_names or {}).get(int(team_id), f"Team {team_id}")
            lines.append(f"\n--- {name}  (Team {team_id}) ---")
            lines.append(f"  Score              : {tf.get('score', 0)}")
            lines.append(f"  Units Spawned      : {tf.get('units_spawned', 0)}")
            lines.append(f"  Units Killed       : {tf.get('units_killed', 0)}")
            lines.append(f"  Units Lost         : {tf.get('units_lost', 0)}")
            lines.append(f"  Damage Dealt       : {tf.get('damage_dealt', 0)}")
            lines.append(f"  Damage Taken       : {tf.get('damage_taken', 0)}")
            lines.append(f"  Healing Done       : {tf.get('healing_done', 0)}")
            lines.append(f"  Metal Spots Captured: {tf.get('metal_spots_captured', 0)}")
            lines.append(f"  Actions            : {tf.get('actions', 0)}")

            build_order = tf.get("build_order", [])
            if build_order:
                lines.append(f"  Build Order ({len(build_order)} units):")
                for entry in build_order[:30]:
                    tick = entry.get("tick", 0)
                    ut = entry.get("unit_type", "?")
                    bo_sec = round(tick / 60.0, 1)
                    lines.append(f"    {bo_sec:>7.1f}s  {ut}")
                if len(build_order) > 30:
                    lines.append(f"    ... and {len(build_order) - 30} more")

        # -- Performance / debug table (mirrors the debug screen) --
        step_ms = stats_data.get("step_ms", [])
        subsystem_ms = stats_data.get("subsystem_ms", {})

        lines.append(f"\n{'=' * 64}")
        lines.append("Performance Debug  (subsystem timings in ms)")
        lines.append(f"{'=' * 64}")
        lines.append(f"{'Subsystem':<24s} {'Min':>9s} {'Avg':>9s} {'Max':>9s} {'Samples':>8s}")
        lines.append("-" * 64)

        all_series = [("step_ms", step_ms)]
        for name in self._subsystem_names:
            all_series.append((name, subsystem_ms.get(name, [])))

        for name, data in all_series:
            if data:
                mn = min(data)
                avg = sum(data) / len(data)
                mx = max(data)
                n = len(data)
            else:
                mn = avg = mx = 0.0
                n = 0
            lines.append(f"{name:<24s} {mn:>8.3f}  {avg:>8.3f}  {mx:>8.3f}  {n:>7d}")

        lines.append("")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return filepath
