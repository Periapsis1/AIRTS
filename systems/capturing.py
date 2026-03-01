from __future__ import annotations
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.base import Entity

from config.settings import METAL_SPOT_CAPTURE_RADIUS

import math

def capture_step(entities: list[Entity], command_centers: list[CommandCenter], units: list[Unit], metal_spots: list[MetalSpot], metal_extractors: list[MetalExtractor], dt: float, stats=None):
    # for each unclaimed metal spot, check the radius, then compute team 1 units - team 2 units in the radius
    for metal_spot in metal_spots:
        if metal_spot.owner is not None:
            continue
        unit_difference = 0
        for unit in units:
            if math.hypot(unit.x - metal_spot.center()[0], unit.y - metal_spot.center()[1]) > METAL_SPOT_CAPTURE_RADIUS:
                continue
            if unit.team == 1:
                unit_difference += 1
            elif unit.team == 2:
                unit_difference -= 1
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
