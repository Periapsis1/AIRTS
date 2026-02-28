"""Collision resolution and bounds clamping."""
from __future__ import annotations
import math
import random
from entities.unit import Unit
from entities.shapes import CircleEntity, RectEntity
from entities.command_center import CommandCenter
from entities.base import Entity
from config.settings import UNIT_PUSH_FORCE, OBSTACLE_PUSH_FORCE, CC_RADIUS


def resolve_unit_collisions(units: list[Unit], dt: float):
    for i in range(len(units)):
        for j in range(i + 1, len(units)):
            a, b = units[i], units[j]
            dx = b.x - a.x
            dy = b.y - a.y
            dist = math.hypot(dx, dy)
            min_dist = a.radius + b.radius
            if dist < min_dist and dist > 0:
                overlap = min_dist - dist
                nx = dx / dist
                ny = dy / dist
                push = overlap * 0.5 + UNIT_PUSH_FORCE * dt
                a.x -= nx * push * 0.5
                a.y -= ny * push * 0.5
                b.x += nx * push * 0.5
                b.y += ny * push * 0.5
            elif dist == 0:
                angle = random.uniform(0, math.tau)
                nudge = UNIT_PUSH_FORCE * dt
                a.x += math.cos(angle) * nudge
                a.y += math.sin(angle) * nudge


def resolve_obstacle_collisions(units: list[Unit], obstacles: list[Entity], dt: float):
    for unit in units:
        for obs in obstacles:
            if isinstance(obs, CircleEntity):
                _push_from_circle(unit, obs, dt)
            elif isinstance(obs, RectEntity):
                _push_from_rect(unit, obs, dt)


def resolve_structure_collisions(units: list[Unit], ccs: list[CommandCenter], dt: float):
    for unit in units:
        for cc in ccs:
            dx = unit.x - cc.x
            dy = unit.y - cc.y
            dist = math.hypot(dx, dy)
            min_dist = unit.radius + CC_RADIUS
            if dist < min_dist and dist > 0:
                nx = dx / dist
                ny = dy / dist
                push = (min_dist - dist) + OBSTACLE_PUSH_FORCE * dt
                unit.x += nx * push
                unit.y += ny * push
            elif dist == 0:
                angle = random.uniform(0, math.tau)
                unit.x += math.cos(angle) * OBSTACLE_PUSH_FORCE * dt
                unit.y += math.sin(angle) * OBSTACLE_PUSH_FORCE * dt


def clamp_units_to_bounds(units: list[Unit], width: int, height: int):
    for u in units:
        r = u.radius
        u.x = max(r, min(u.x, width - r))
        u.y = max(r, min(u.y, height - r))


def _push_from_circle(unit: Unit, obs: CircleEntity, dt: float):
    dx = unit.x - obs.x
    dy = unit.y - obs.y
    dist = math.hypot(dx, dy)
    min_dist = unit.radius + obs.radius
    if dist < min_dist and dist > 0:
        nx = dx / dist
        ny = dy / dist
        push = (min_dist - dist) + OBSTACLE_PUSH_FORCE * dt
        unit.x += nx * push
        unit.y += ny * push
    elif dist == 0:
        angle = random.uniform(0, math.tau)
        unit.x += math.cos(angle) * OBSTACLE_PUSH_FORCE * dt
        unit.y += math.sin(angle) * OBSTACLE_PUSH_FORCE * dt


def _push_from_rect(unit: Unit, obs: RectEntity, dt: float):
    cx = max(obs.x, min(unit.x, obs.x + obs.width))
    cy = max(obs.y, min(unit.y, obs.y + obs.height))
    dx = unit.x - cx
    dy = unit.y - cy
    dist = math.hypot(dx, dy)
    if dist < unit.radius:
        if dist > 0:
            nx = dx / dist
            ny = dy / dist
        else:
            angle = random.uniform(0, math.tau)
            nx = math.cos(angle)
            ny = math.sin(angle)
        push = (unit.radius - dist) + OBSTACLE_PUSH_FORCE * dt
        unit.x += nx * push
        unit.y += ny * push
