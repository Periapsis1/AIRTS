"""Game statistics: running counters, time-series snapshots, and score calculation."""
from __future__ import annotations
from typing import Any

from config.settings import CC_HP


class TeamStats:
    """Running counters and time-series arrays for one team."""

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
        self.build_order: list[tuple[int, str, int]] = []  # (team, unit_type, tick)

        # Time-series snapshots (sampled every 60 ticks)
        self.ts_cc_health: list[float] = []
        self.ts_army_count: list[int] = []
        self.ts_units_killed: list[int] = []
        self.ts_damage_dealt: list[float] = []
        self.ts_healing_done: list[float] = []
        self.ts_metal_spots: list[int] = []
        self.ts_apm: list[float] = []


class GameStats:
    """Accumulates game statistics for both teams."""

    SAMPLE_INTERVAL = 60  # ticks between time-series snapshots

    def __init__(self):
        self.teams: dict[int, TeamStats] = {1: TeamStats(), 2: TeamStats()}
        self.timestamps: list[int] = []
        self._finalized = False

    # -- recording helpers (called by systems) --------------------------------

    def record_damage(self, attacker_team: int, target_team: int, amount: float):
        self.teams[attacker_team].damage_dealt += amount
        self.teams[target_team].damage_taken += amount

    def record_kill(self, killer_team: int, victim_team: int):
        self.teams[killer_team].units_killed += 1
        self.teams[victim_team].units_lost += 1

    def record_healing(self, team: int, amount: float):
        self.teams[team].healing_done += amount

    def record_spawn(self, team: int, unit_type: str, tick: int):
        self.teams[team].units_spawned += 1
        self.teams[team].build_order.append((team, unit_type, tick))

    def record_capture(self, team: int):
        self.teams[team].metal_spots_captured += 1

    def record_action(self, team: int):
        self.teams[team].actions += 1

    # -- time-series sampling -------------------------------------------------

    def sample_tick(self, tick: int, entities: list):
        """Snapshot current state into time-series arrays.

        Called from Game.step() every SAMPLE_INTERVAL ticks.
        """
        from entities.unit import Unit
        from entities.command_center import CommandCenter

        self.timestamps.append(tick)
        elapsed_minutes = max(tick / 3600.0, 1 / 3600.0)  # 60 ticks/sec

        for team_id, ts in self.teams.items():
            # CC health
            cc_hp = 0.0
            for e in entities:
                if isinstance(e, CommandCenter) and e.alive and e.team == team_id:
                    cc_hp = e.hp
                    break
            ts.ts_cc_health.append(cc_hp)

            # Army count
            army = sum(
                1 for e in entities
                if isinstance(e, Unit) and e.alive and e.team == team_id
            )
            ts.ts_army_count.append(army)

            # Cumulative counters
            ts.ts_units_killed.append(ts.units_killed)
            ts.ts_damage_dealt.append(ts.damage_dealt)
            ts.ts_healing_done.append(ts.healing_done)
            ts.ts_metal_spots.append(ts.metal_spots_captured)

            # APM
            apm = ts.actions / elapsed_minutes
            ts.ts_apm.append(round(apm, 1))

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
                "metal_spots": ts.ts_metal_spots,
                "apm": ts.ts_apm,
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
                "build_order": [
                    {"team": t, "unit_type": ut, "tick": tk}
                    for t, ut, tk in ts.build_order
                ],
            }

        return {
            "timestamps": self.timestamps,
            "teams": teams_data,
            "final": final_data,
            "game_duration_seconds": duration_seconds,
        }
