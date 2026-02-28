"""Game class — owns the loop, wires systems together."""
from __future__ import annotations
import math
import sys
import pygame

from entities.base import Entity
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.laser import LaserFlash
from systems.combat import combat_step, medic_heal_step, cc_heal_step
from systems.physics import (
    resolve_unit_collisions, resolve_obstacle_collisions,
    resolve_structure_collisions, clamp_units_to_bounds,
)
from systems.spawning import spawn_step
from systems.selection import click_select, apply_circle_selection
from systems.ai import BaseAI, WanderAI
from systems.map_generator import BaseMapGenerator, DefaultMapGenerator
from systems.capturing import capture_step
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from config.settings import (
    SELECTION_FILL_COLOR, SELECTION_RECT_COLOR,
    COMMAND_PATH_COLOR, COMMAND_DOT_COLOR, PATH_SAMPLE_MIN_DIST,
)
import gui


class Game:
    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        title: str = "AIRTS",
        map_generator: BaseMapGenerator | None = None,
        team_ai: dict[int, BaseAI] | None = None,
    ):
        """
        *team_ai* maps team numbers to AI controllers.  Teams **not** present
        in the dict are human-controlled.  At least one team must have an AI
        (Human-vs-Human is not supported).

        Examples::

            team_ai={2: WanderAI()}          # Human (T1) vs AI (T2)
            team_ai={1: MyAI()}              # AI (T1) vs Human (T2)
            team_ai={1: MyAI(), 2: WanderAI()} # AI vs AI (spectator)
        """
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        self.running = False
        self.fps = 60

        self.entities: list[Entity] = []
        self.laser_flashes: list[LaserFlash] = []

        gen = map_generator or DefaultMapGenerator()
        self.entities = gen.generate(width, height)
        self.metal_spots: list[MetalSpot] = [
            e for e in self.entities if isinstance(e, MetalSpot)
        ]

        self.team_ai: dict[int, BaseAI] = team_ai if team_ai is not None else {2: WanderAI()}
        self.human_teams: set[int] = {1, 2} - set(self.team_ai.keys())
        if self.human_teams == {1, 2}:
            raise ValueError("Human-vs-Human is not supported; at least one team must have an AI.")

        self._iteration = 0

        self._apply_selectability()
        self._bind_and_start_ais()

        self._has_human = len(self.human_teams) > 0
        self._dragging = False
        self._drag_start: tuple[int, int] = (0, 0)
        self._drag_end: tuple[int, int] = (0, 0)
        self._selection_surface = pygame.Surface((width, height), pygame.SRCALPHA)

        self._rdragging = False
        self._rpath: list[tuple[float, float]] = []

    # -- init helpers -------------------------------------------------------

    def _apply_selectability(self):
        for e in self.entities:
            if hasattr(e, "team") and hasattr(e, "selectable"):
                e.selectable = e.team in self.human_teams

    def _bind_and_start_ais(self):
        for team_id, ai in self.team_ai.items():
            ai._bind(team_id, self)
            ai.on_start()

    # -- queries ------------------------------------------------------------

    def _get_units(self) -> list[Unit]:
        return [e for e in self.entities if isinstance(e, Unit)]

    def _get_command_centers(self) -> list[CommandCenter]:
        return [e for e in self.entities if isinstance(e, CommandCenter)]

    def _get_obstacles(self) -> list[Entity]:
        return [e for e in self.entities if e.obstacle]

    def _get_metal_extractors(self) -> list[MetalExtractor]:
        return [e for e in self.entities if isinstance(e, MetalExtractor)]

    # -- selection helpers --------------------------------------------------

    def _selection_center(self) -> tuple[float, float]:
        return (float(self._drag_start[0]), float(self._drag_start[1]))

    def _selection_radius(self) -> float:
        cx, cy = self._selection_center()
        return math.hypot(self._drag_end[0] - cx, self._drag_end[1] - cy)

    # -- right-click path ---------------------------------------------------

    def _path_total_length(self) -> float:
        total = 0.0
        for i in range(1, len(self._rpath)):
            ax, ay = self._rpath[i - 1]
            bx, by = self._rpath[i]
            total += math.hypot(bx - ax, by - ay)
        return total

    def _resample_path(self, n: int) -> list[tuple[float, float]]:
        if n <= 0 or len(self._rpath) < 2:
            return list(self._rpath[:n])

        total = self._path_total_length()
        if total < 1e-6:
            return [self._rpath[0]] * n

        if n == 1:
            return [self._rpath[len(self._rpath) // 2]]

        spacing = total / (n - 1)
        points: list[tuple[float, float]] = [self._rpath[0]]
        accumulated = 0.0
        seg = 1
        seg_start = self._rpath[0]

        for i in range(1, n - 1):
            target_dist = i * spacing
            while seg < len(self._rpath):
                sx, sy = seg_start
                ex, ey = self._rpath[seg]
                seg_len = math.hypot(ex - sx, ey - sy)
                if accumulated + seg_len >= target_dist:
                    frac = (target_dist - accumulated) / seg_len if seg_len > 0 else 0
                    px = sx + (ex - sx) * frac
                    py = sy + (ey - sy) * frac
                    points.append((px, py))
                    break
                accumulated += seg_len
                seg_start = self._rpath[seg]
                seg += 1
            else:
                points.append(self._rpath[-1])

        points.append(self._rpath[-1])
        return points

    def _set_rally_points(self):
        if not self._rpath:
            return
        rally = self._rpath[-1]
        for entity in self.entities:
            if isinstance(entity, CommandCenter) and entity.selected:
                entity.rally_point = rally

    def _assign_path_goals(self):
        selected = [e for e in self.entities if isinstance(e, Unit) and e.selected]
        if not selected or len(self._rpath) < 2:
            if selected and len(self._rpath) == 1:
                px, py = self._rpath[0]
                for u in selected:
                    u.move(px, py)
            return

        goals = self._resample_path(len(selected))
        assigned: set[int] = set()

        for gx, gy in goals:
            best_idx = -1
            best_dist = float("inf")
            for i, unit in enumerate(selected):
                if i in assigned:
                    continue
                d = math.hypot(unit.x - gx, unit.y - gy)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            if best_idx >= 0:
                selected[best_idx].move(gx, gy)
                assigned.add(best_idx)

    # -- events -------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False

            if not self._has_human:
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if gui.handle_gui_click(self.entities, event.pos[0], event.pos[1],
                                        self.width, self.height):
                    continue
                self._dragging = True
                self._drag_start = event.pos
                self._drag_end = event.pos

            elif event.type == pygame.MOUSEMOTION:
                if self._dragging:
                    self._drag_end = event.pos
                if self._rdragging:
                    pos = (float(event.pos[0]), float(event.pos[1]))
                    if self._rpath:
                        last = self._rpath[-1]
                        if math.hypot(pos[0] - last[0], pos[1] - last[1]) >= PATH_SAMPLE_MIN_DIST:
                            self._rpath.append(pos)
                    else:
                        self._rpath.append(pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._dragging:
                self._drag_end = event.pos
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                sr = self._selection_radius()
                if sr < 5:
                    click_select(
                        self.entities,
                        float(event.pos[0]), float(event.pos[1]),
                        additive=bool(shift),
                    )
                else:
                    cx, cy = self._selection_center()
                    apply_circle_selection(
                        self.entities, cx, cy, sr,
                        additive=bool(shift),
                    )
                self._dragging = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self._rdragging = True
                self._rpath = [(float(event.pos[0]), float(event.pos[1]))]

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3 and self._rdragging:
                self._rdragging = False
                self._assign_path_goals()
                self._set_rally_points()
                self._rpath = []

    # -- step ---------------------------------------------------------------

    def step(self, dt: float):
        for entity in self.entities:
            entity.update(dt)

        units = self._get_units()
        ccs = self._get_command_centers()
        obstacles = self._get_obstacles()
        metal_extractors = self._get_metal_extractors()

        for ai in self.team_ai.values():
            ai.on_step(self._iteration)

        capture_step(self.entities, ccs, units, self.metal_spots, metal_extractors, dt)
        combat_step(units, ccs, metal_extractors, obstacles, self.laser_flashes, dt)
        medic_heal_step(units, dt)
        cc_heal_step(ccs, units, dt)
        spawn_step(self.entities, ccs, self.human_teams)

        self.entities = [e for e in self.entities if e.alive]

        units = self._get_units()
        ccs = self._get_command_centers()
        obstacles = self._get_obstacles()
        resolve_unit_collisions(units, dt)
        resolve_obstacle_collisions(units, obstacles, dt)
        resolve_structure_collisions(units, ccs, dt)
        clamp_units_to_bounds(units, self.width, self.height)

        self.laser_flashes = [lf for lf in self.laser_flashes if lf.update(dt)]
        self._iteration += 1

    # -- render -------------------------------------------------------------

    def render(self):
        self.screen.fill((0, 0, 0))
        for entity in self.entities:
            entity.draw(self.screen)

        for lf in self.laser_flashes:
            lf.draw(self.screen)

        if self._dragging:
            sr = self._selection_radius()
            if sr >= 5:
                cx, cy = self._selection_center()
                self._selection_surface.fill((0, 0, 0, 0))
                pygame.draw.circle(self._selection_surface, SELECTION_FILL_COLOR,
                                   (int(cx), int(cy)), int(sr))
                pygame.draw.circle(self._selection_surface, SELECTION_RECT_COLOR,
                                   (int(cx), int(cy)), int(sr), 1)
                self.screen.blit(self._selection_surface, (0, 0))

        if self._rdragging and len(self._rpath) >= 2:
            pygame.draw.lines(self.screen, COMMAND_PATH_COLOR, False, self._rpath, 2)
            selected_count = sum(
                1 for e in self.entities if isinstance(e, Unit) and e.selected
            )
            if selected_count > 0:
                preview = self._resample_path(selected_count)
                for px, py in preview:
                    pygame.draw.circle(self.screen, COMMAND_DOT_COLOR, (int(px), int(py)), 4, 1)

        if self._has_human:
            gui.draw_cc_gui(self.screen, self.entities, self.width, self.height)

        pygame.display.flip()

    # -- run ----------------------------------------------------------------

    def run(self):
        self.running = True
        while self.running:
            dt = self.clock.tick(self.fps) / 1000.0
            self.handle_events()
            self.step(dt)
            self.render()
        pygame.quit()
        sys.exit()
