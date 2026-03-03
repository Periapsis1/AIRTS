from __future__ import annotations
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.base import Entity

from config.settings import METAL_SPOT_CAPTURE_RADIUS

import math

def capture_step(entities: list[Entity], command_centers: list[CommandCenter], units: list[Unit], metal_spots: list[MetalSpot], metal_extractors: list[MetalExtractor], dt: float, stats=None, grid=None):
    cap_radius_sq = METAL_SPOT_CAPTURE_RADIUS * METAL_SPOT_CAPTURE_RADIUS
    for metal_spot in metal_spots:
        if metal_spot.owner is not None:
            continue
        unit_difference = 0
        sx, sy = metal_spot.center()
        nearby = grid.query_radius(sx, sy, METAL_SPOT_CAPTURE_RADIUS) if grid is not None else units
        for unit in nearby:
            if getattr(unit, 'is_building', False):
                continue
            dx = unit.x - sx
            dy = unit.y - sy
            if dx * dx + dy * dy > cap_radius_sq:
                continue
            weight = 0.3 if unit.unit_type == "scout" else 1
            if unit.team == 1:
                unit_difference += weight
            elif unit.team == 2:
                unit_difference -= weight
        metal_spot.update_progress(unit_difference, dt)
        if metal_spot.capture_progress >= 1.0:
            metal_spot.claim(1)
            metal_extractor = MetalExtractor(metal_spot=metal_spot, team=1)
            entities.append(metal_extractor)
            cc = next((c for c in command_centers if c.team == 1), None)
            if cc is not None:
                cc.metal_extractors.append(metal_extractor)
            if stats is not None:
                stats.record_capture(1)
        elif metal_spot.capture_progress <= -1.0:
            metal_spot.claim(2)
            metal_extractor = MetalExtractor(metal_spot=metal_spot, team=2)
            entities.append(metal_extractor)
            cc = next((c for c in command_centers if c.team == 2), None)
            if cc is not None:
                cc.metal_extractors.append(metal_extractor)
            if stats is not None:
                stats.record_capture(2)
