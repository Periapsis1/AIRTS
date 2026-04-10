from __future__ import annotations
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.base import Entity

from config.settings import METAL_SPOT_CAPTURE_RADIUS

import math

def capture_step(entities: list[Entity], command_centers: list[CommandCenter], units: list[Unit], metal_spots: list[MetalSpot], metal_extractors: list[MetalExtractor], dt: float, stats=None, grid=None, teams=None):
    all_teams = sorted(teams) if teams else [1, 2]
    cap_radius_sq = METAL_SPOT_CAPTURE_RADIUS * METAL_SPOT_CAPTURE_RADIUS
    for metal_spot in metal_spots:
        if metal_spot.owner is not None:
            continue
        team_counts: dict[int, float] = {t: 0.0 for t in all_teams}
        # Track per-player contribution to determine ME owner
        player_counts: dict[int, float] = {}
        player_team_map: dict[int, int] = {}
        sx, sy = metal_spot.center()
        nearby = grid.get_units_exact(sx, sy, METAL_SPOT_CAPTURE_RADIUS) if grid is not None else units
        for unit in nearby:
            if getattr(unit, 'is_building', False):
                continue
            dx = unit.x - sx
            dy = unit.y - sy
            if dx * dx + dy * dy > cap_radius_sq:
                continue
            if unit.team not in team_counts:
                continue
            weight = 0.3 if unit.unit_type == "scout" else 1.0
            team_counts[unit.team] += weight
            pid = getattr(unit, 'player_id', unit.team)
            player_counts[pid] = player_counts.get(pid, 0.0) + weight
            player_team_map[pid] = unit.team

        metal_spot.update_progress(team_counts, dt)

        def _claim_for(claiming_team: int):
            # Find the player on this team with the most units near the spot
            best_pid = claiming_team
            best_weight = -1.0
            for pid, w in player_counts.items():
                if player_team_map.get(pid) == claiming_team and w > best_weight:
                    best_weight = w
                    best_pid = pid
            metal_spot.claim(claiming_team)
            metal_extractor = MetalExtractor(metal_spot=metal_spot, team=claiming_team,
                                             player_id=best_pid)
            entities.append(metal_extractor)
            metal_extractors.append(metal_extractor)
            # Give the spawn bonus to ALL living CCs on the claiming team equally
            for cc in command_centers:
                if cc.team == claiming_team and cc.alive:
                    cc.metal_extractors.append(metal_extractor)
            if stats is not None:
                stats.record_capture(claiming_team)

        # Check if any team has completed capture
        for tid, prog in list(metal_spot.capture_progress.items()):
            if prog >= 1.0:
                _claim_for(tid)
                break
