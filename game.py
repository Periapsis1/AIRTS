"""Game class — owns the loop, wires systems together."""
from __future__ import annotations
import math
import random
import time
from typing import Any
import pygame

from entities.base import Entity
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.laser import LaserFlash
from systems.combat import combat_step, PendingChain, TargetingData
from systems.physics import clamp_units_to_bounds
from systems.spawning import spawn_step
from systems.selection import click_select, apply_circle_selection, select_all_of_type
from systems.ai import BaseAI, WanderAI
from systems.map_generator import BaseMapGenerator, DefaultMapGenerator
from systems.capturing import capture_step
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from config.settings import (
    SELECTION_FILL_COLOR, SELECTION_RECT_COLOR,
    COMMAND_PATH_COLOR, COMMAND_DOT_COLOR, PATH_SAMPLE_MIN_DIST,
    FIXED_DT, MAX_FRAME_DT, CC_RADIUS,
    TEAM1_COLOR, TEAM2_COLOR, HEALTH_BAR_OFFSET,
    CAMERA_ZOOM_STEP, CAMERA_MAX_ZOOM,
    EDGE_PAN_MARGIN, EDGE_PAN_SPEED,
)
from entities.shapes import RectEntity, CircleEntity, PolygonEntity
from systems.commands import GameCommand, CommandQueue
from systems.replay import ReplayRecorder
from systems.stats import GameStats
from core.vectorized import build_obstacle_arrays, batch_obstacle_push, batch_unit_collisions
from core.camera import Camera
import numpy as np
import os
from ui.widgets import Slider, Button
import gui

_DBLCLICK_MS = 400

# Type registry for deserialization dispatch
_ENTITY_TYPES: dict[str, type] = {
    "Entity": Entity,
    "RectEntity": RectEntity,
    "CircleEntity": CircleEntity,
    "PolygonEntity": PolygonEntity,
    "Unit": Unit,
    "CommandCenter": CommandCenter,
    "MetalSpot": MetalSpot,
    "MetalExtractor": MetalExtractor,
}


class Game:
    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        title: str = "AIRTS",
        map_generator: BaseMapGenerator | None = None,
        team_ai: dict[int, BaseAI] | None = None,
        screen: pygame.Surface | None = None,
        clock: pygame.time.Clock | None = None,
        replay_config: dict | None = None,
        player_name: str = "Human",
        headless: bool = False,
        max_ticks: int = 0,
        save_replay: bool = True,
        step_timeout_ms: float = 0,
        replay_output_dir: str = "replays",
    ):
        """
        *team_ai* maps team numbers to AI controllers.  Teams **not** present
        in the dict are human-controlled.  At least one team must have an AI
        (Human-vs-Human is not supported).

        When *screen* and *clock* are provided (by the App controller),
        the Game will use them instead of creating its own.

        Examples::

            team_ai={2: WanderAI()}          # Human (T1) vs AI (T2)
            team_ai={1: MyAI()}              # AI (T1) vs Human (T2)
            team_ai={1: MyAI(), 2: WanderAI()} # AI vs AI (spectator)
        """
        if screen is None:
            pygame.init()
            self.screen = pygame.display.set_mode((width, height))
            pygame.display.set_caption(title)
            self._owns_pygame = True
        else:
            self.screen = screen
            self._owns_pygame = False

        self.width = width
        self.height = height
        self.clock = clock or pygame.time.Clock()
        self.running = False
        self.fps = 60
        self._headless = headless
        self._max_ticks = max_ticks
        self._save_replay = save_replay
        self._step_timeout_ms = step_timeout_ms
        self._replay_output_dir = replay_output_dir
        self._player_name = player_name
        self._fps_font = pygame.font.SysFont(None, 22)
        self._label_font = pygame.font.SysFont(None, 20)

        self.entities: list[Entity] = []
        self.laser_flashes: list[LaserFlash] = []
        self._pending_chains: list[PendingChain] = []

        # -- sounds -----------------------------------------------------------
        if not headless:
            _sounds_dir = os.path.join(os.path.dirname(__file__), "sounds")
            self._sounds: dict[str, pygame.mixer.Sound] = {
                "fast_laser": pygame.mixer.Sound(os.path.join(_sounds_dir, "fast_laser.mp3")),
                "laser": pygame.mixer.Sound(os.path.join(_sounds_dir, "laser.mp3")),
            }
        else:
            self._sounds: dict[str, pygame.mixer.Sound] = {}

        gen = map_generator or DefaultMapGenerator()
        self.entities = gen.generate(width, height)
        self.metal_spots: list[MetalSpot] = [
            e for e in self.entities if isinstance(e, MetalSpot)
        ]
        self.units: list[Unit] = [e for e in self.entities if isinstance(e, Unit)]
        self.team_1_units: list[Unit] = [u for u in self.units if u.team == 1]
        self.team_2_units: list[Unit] = [u for u in self.units if u.team == 2]
        self.command_centers: list[CommandCenter] = [
            e for e in self.entities if isinstance(e, CommandCenter)
        ]
        self.metal_extractors: list[MetalExtractor] = [
            e for e in self.entities if isinstance(e, MetalExtractor)
        ]
        self._precompute_obstacles()

        self._next_entity_id: int = 1
        self._speed_multiplier: float = 1.0
        self._accumulator: float = 0.0
        self._assign_entity_ids()

        self.team_ai: dict[int, BaseAI] = team_ai if team_ai is not None else {2: WanderAI()}
        self.human_teams: set[int] = {1, 2} - set(self.team_ai.keys())
        if self.human_teams == {1, 2}:
            raise ValueError("Human-vs-Human is not supported; at least one team must have an AI.")

        self._iteration = 0
        self._winner = 0  # 0 = undecided, 1 or 2 = that team won
        self._stats = GameStats()

        self._command_queue = CommandQueue()

        self._apply_selectability()
        self._bind_and_start_ais()

        self._has_human = len(self.human_teams) > 0
        self._dragging = False
        self._drag_start: tuple[int, int] = (0, 0)
        self._drag_end: tuple[int, int] = (0, 0)
        self._selection_surface = pygame.Surface((width, height), pygame.SRCALPHA)

        self._rdragging = False
        self._rpath: list[tuple[float, float]] = []

        # Double-click detection
        self._last_click_time: int = 0
        self._last_click_pos: tuple[int, int] = (0, 0)

        self._speed_slider = Slider(width - 170, 10, 150, "Speed %", 25, 800, 100, 25)
        self._pause_btn = Button(width - 210, 12, 32, 24, "||", icon="pause")
        self._paused = False
        self._pause_font = pygame.font.SysFont(None, 48)
        self._mouse_grabbed = False

        # -- camera & world surface -------------------------------------------
        self._world_surface = pygame.Surface((width, height))
        self._camera = Camera(width, height, width, height,
                              max_zoom=CAMERA_MAX_ZOOM)
        self._mid_dragging = False
        self._mid_last: tuple[int, int] = (0, 0)

        if save_replay:
            self._replay_recorder = ReplayRecorder(width, height, replay_config)
        else:
            self._replay_recorder = None

        # -- phase state machine: warp_in → playing → explode ----------------
        self._phase: str = "warp_in"
        self._anim_timer: float = 0.0
        self._fragments: list[dict] = []
        self._anim_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self._fog_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self._fog_border = pygame.Surface((width, height))
        self._fog_border.set_colorkey((0, 0, 0))

        self._physics_cooldown: int = 60  # ticks remaining; handles initial spawn settling

        # Cache CC visual data at init (CCs don't move)
        self._cc_data: dict[int, dict] = {}
        for e in self.entities:
            if isinstance(e, CommandCenter):
                self._cc_data[e.team] = {
                    "x": e.x, "y": e.y,
                    "color": e.color,
                    "points": list(e.points),
                }

    # -- init helpers -------------------------------------------------------

    def _assign_entity_ids(self):
        for e in self.entities:
            if e.entity_id == 0:
                e.entity_id = self._next_entity_id
                self._next_entity_id += 1

    def _apply_selectability(self):
        for e in self.entities:
            if hasattr(e, "team") and hasattr(e, "selectable"):
                e.selectable = e.team in self.human_teams

    def _bind_and_start_ais(self):
        for team_id, ai in self.team_ai.items():
            ai._bind(team_id, self, stats=self._stats,
                     command_queue=self._command_queue)
            ai.on_start()

    # -- queries ------------------------------------------------------------

    def _precompute_obstacles(self):
        """Cache static obstacle geometry (CircleEntity/RectEntity never move)."""
        self._static_obstacles = [e for e in self.entities if e.obstacle]
        self._obs_circle = tuple(
            (obs.x, obs.y, obs.radius)
            for obs in self._static_obstacles if isinstance(obs, CircleEntity)
        )
        self._obs_rect = tuple(
            (obs.x, obs.y, obs.width, obs.height)
            for obs in self._static_obstacles if isinstance(obs, RectEntity)
        )
        self._circle_obs_np, self._rect_obs_np = build_obstacle_arrays(
            self._obs_circle, self._obs_rect
        )
        self._static_steer = tuple(
            (*e.center(), e.collision_radius())
            for e in self._static_obstacles if e.alive
        )

    def _refresh_steer_obstacles(self):
        """Build flat tuple of (x, y, radius) for unit steering."""
        bldg = tuple(
            (e.x, e.y, e.radius)
            for e in self.units if e.is_building and e.alive
        )
        Unit._steer_obstacles = self._static_steer + bldg

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
                team = entity.team
                if team in self.human_teams:
                    self._command_queue.enqueue(GameCommand(
                        type="set_rally",
                        team=team,
                        tick=self._iteration,
                        data={"team": team, "position": list(rally)},
                    ))
                    self._stats.record_action(team)

    def _assign_path_goals(self):
        selected = [e for e in self.entities if isinstance(e, Unit) and e.selected]
        if not selected or len(self._rpath) < 2:
            if selected and len(self._rpath) == 1:
                px, py = self._rpath[0]
                unit_ids = []
                targets = []
                for u in selected:
                    unit_ids.append(u.entity_id)
                    targets.append((px, py))
                    if u.team in self.human_teams:
                        self._stats.record_action(u.team)
                if unit_ids:
                    team = selected[0].team
                    self._command_queue.enqueue(GameCommand(
                        type="move",
                        team=team,
                        tick=self._iteration,
                        data={"unit_ids": unit_ids, "targets": targets},
                    ))
            return

        goals = self._resample_path(len(selected))
        assigned: set[int] = set()
        unit_ids: list[int] = []
        targets: list[tuple[float, float]] = []

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
                unit_ids.append(selected[best_idx].entity_id)
                targets.append((gx, gy))
                assigned.add(best_idx)
                if selected[best_idx].team in self.human_teams:
                    self._stats.record_action(selected[best_idx].team)

        if unit_ids:
            team = selected[0].team
            self._command_queue.enqueue(GameCommand(
                type="move",
                team=team,
                tick=self._iteration,
                data={"unit_ids": unit_ids, "targets": targets},
            ))

    # -- pause / mouse grab ------------------------------------------------

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.label = ">"
            self._pause_btn.icon = "play"
            self._set_mouse_grab(False)
        else:
            self._pause_btn.label = "||"
            self._pause_btn.icon = "pause"
            self._set_mouse_grab(True)

    def _set_mouse_grab(self, grab: bool):
        self._mouse_grabbed = grab
        pygame.event.set_grab(grab)

    def _update_edge_pan(self, dt: float):
        """Pan camera when mouse is at the screen edge (only while grabbed)."""
        if not self._mouse_grabbed:
            return
        mx, my = pygame.mouse.get_pos()
        dx = 0.0
        dy = 0.0
        if mx <= EDGE_PAN_MARGIN:
            dx = EDGE_PAN_SPEED * dt
        elif mx >= self.width - EDGE_PAN_MARGIN - 1:
            dx = -EDGE_PAN_SPEED * dt
        if my <= EDGE_PAN_MARGIN:
            dy = EDGE_PAN_SPEED * dt
        elif my >= self.height - EDGE_PAN_MARGIN - 1:
            dy = -EDGE_PAN_SPEED * dt
        if dx or dy:
            self._camera.pan(dx, dy)

    # -- coordinate helpers ------------------------------------------------

    def _screen_to_world(self, pos: tuple[int, int]) -> tuple[float, float]:
        """Convert a screen position to world coordinates via the camera."""
        return self._camera.screen_to_world(float(pos[0]), float(pos[1]))

    # -- events -------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._set_mouse_grab(False)
                self.running = False

            if self._pause_btn.handle_event(event):
                self._toggle_pause()
                continue

            # Click anywhere while paused → unpause
            if (self._paused
                    and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1):
                self._toggle_pause()
                continue

            if self._speed_slider.handle_event(event):
                self._speed_multiplier = self._speed_slider.value / 100.0

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._paused:
                        # Already paused — quit the game
                        self._set_mouse_grab(False)
                        self.running = False
                    else:
                        self._toggle_pause()

            # Scroll wheel zoom (available always, not just for human)
            if event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                if event.y > 0:
                    self._camera.zoom_at(mx, my, CAMERA_ZOOM_STEP)
                elif event.y < 0:
                    self._camera.zoom_at(mx, my, 1.0 / CAMERA_ZOOM_STEP)

            # Middle mouse pan
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
                self._mid_dragging = True
                self._mid_last = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
                self._mid_dragging = False
            elif event.type == pygame.MOUSEMOTION and self._mid_dragging:
                dx = event.pos[0] - self._mid_last[0]
                dy = event.pos[1] - self._mid_last[1]
                self._camera.pan(dx, dy)
                self._mid_last = event.pos

            if not self._has_human:
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # GUI click stays in screen space
                gui_result = gui.handle_gui_click(
                    self.entities, event.pos[0], event.pos[1],
                    self.width, self.height,
                )
                if gui_result is not None:
                    cc = gui.get_selected_cc(self.entities)
                    if cc is not None:
                        self._command_queue.enqueue(GameCommand(
                            type="set_spawn_type",
                            team=cc.team,
                            tick=self._iteration,
                            data={"team": cc.team, "unit_type": gui_result},
                        ))
                    continue
                # Drag start: store in world coords
                wx, wy = self._screen_to_world(event.pos)
                self._dragging = True
                self._drag_start = (int(wx), int(wy))
                self._drag_end = (int(wx), int(wy))

            elif event.type == pygame.MOUSEMOTION:
                if self._dragging:
                    wx, wy = self._screen_to_world(event.pos)
                    self._drag_end = (int(wx), int(wy))
                if self._rdragging:
                    wx, wy = self._screen_to_world(event.pos)
                    pos_w = (wx, wy)
                    if self._rpath:
                        last = self._rpath[-1]
                        if math.hypot(pos_w[0] - last[0], pos_w[1] - last[1]) >= PATH_SAMPLE_MIN_DIST:
                            self._rpath.append(pos_w)
                    else:
                        self._rpath.append(pos_w)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._dragging:
                wx, wy = self._screen_to_world(event.pos)
                self._drag_end = (int(wx), int(wy))
                shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
                sr = self._selection_radius()
                now = pygame.time.get_ticks()
                if sr < 5:
                    # Double-click detection uses screen-space distance
                    if (now - self._last_click_time < _DBLCLICK_MS
                            and math.hypot(event.pos[0] - self._last_click_pos[0],
                                           event.pos[1] - self._last_click_pos[1]) < 10):
                        select_all_of_type(
                            self.entities, wx, wy,
                        )
                    else:
                        click_select(
                            self.entities, wx, wy,
                            additive=bool(shift),
                        )
                    self._last_click_time = now
                    self._last_click_pos = event.pos  # screen space for distance check
                else:
                    cx, cy = self._selection_center()
                    apply_circle_selection(
                        self.entities, cx, cy, sr,
                        additive=bool(shift),
                    )
                self._dragging = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                wx, wy = self._screen_to_world(event.pos)
                self._rdragging = True
                self._rpath = [(wx, wy)]

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3 and self._rdragging:
                self._rdragging = False
                self._assign_path_goals()
                self._set_rally_points()
                self._rpath = []

    # -- command application ------------------------------------------------

    def _apply_command(self, cmd: GameCommand) -> None:
        """Resolve entity IDs in *cmd* and execute the mutation."""
        id_map: dict[int, Entity] = {e.entity_id: e for e in self.entities}
        data = cmd.data

        if cmd.type == "move":
            for uid, (tx, ty) in zip(data["unit_ids"], data["targets"]):
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive:
                    unit.move(tx, ty)

        elif cmd.type == "attack":
            unit = id_map.get(data["unit_id"])
            target = id_map.get(data["target_id"])
            if isinstance(unit, Unit) and unit.alive and target is not None and target.alive:
                unit.attack_target = target

        elif cmd.type == "stop":
            for uid in data["unit_ids"]:
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive:
                    unit.stop()

        elif cmd.type == "set_rally":
            pos = tuple(data["position"])
            for e in self.entities:
                if isinstance(e, CommandCenter) and e.team == data["team"]:
                    e.rally_point = pos

        elif cmd.type == "set_spawn_type":
            for e in self.entities:
                if isinstance(e, CommandCenter) and e.team == data["team"]:
                    e.spawn_type = data["unit_type"]

    # -- step ---------------------------------------------------------------

    def step(self, dt: float):
        _t0 = time.perf_counter()
        _perf = time.perf_counter

        # Drain and apply all pending commands before simulation
        _t = _perf()
        for cmd in self._command_queue.drain(self._iteration):
            self._apply_command(cmd)

        self._refresh_steer_obstacles()
        self._stats.record_subsystem("commands", (_perf() - _t) * 1000)

        # Build distance matrices for targeting
        _t = _perf()
        alive_t1 = [u for u in self.team_1_units if u.alive]
        alive_t2 = [u for u in self.team_2_units if u.alive]
        n1, n2 = len(alive_t1), len(alive_t2)

        t1_index = {id(u): i for i, u in enumerate(alive_t1)}
        t2_index = {id(u): i for i, u in enumerate(alive_t2)}

        # Empty arrays for degenerate cases
        _empty_0 = np.empty((0, 0), dtype=np.float64)
        _empty_idx = np.empty((0, 0), dtype=np.intp)

        t1_pos = np.array([(u.x, u.y) for u in alive_t1], dtype=np.float64).reshape(n1, 2) if n1 > 0 else np.empty((0, 2), dtype=np.float64)
        t2_pos = np.array([(u.x, u.y) for u in alive_t2], dtype=np.float64).reshape(n2, 2) if n2 > 0 else np.empty((0, 2), dtype=np.float64)

        if n1 > 0 and n2 > 0:
            diff = t1_pos[:, None, :] - t2_pos[None, :, :]  # (N1, N2, 2)
            enemy_dist_sq = np.sum(diff * diff, axis=2)       # (N1, N2)
            t1_sorted_enemy_idx = np.argsort(enemy_dist_sq, axis=1)
            t1_sorted_enemy_dist_sq = np.take_along_axis(enemy_dist_sq, t1_sorted_enemy_idx, axis=1)
            enemy_dist_sq_T = enemy_dist_sq.T.copy()          # (N2, N1)
            t2_sorted_enemy_idx = np.argsort(enemy_dist_sq_T, axis=1)
            t2_sorted_enemy_dist_sq = np.take_along_axis(enemy_dist_sq_T, t2_sorted_enemy_idx, axis=1)
        else:
            t1_sorted_enemy_idx = _empty_idx
            t1_sorted_enemy_dist_sq = _empty_0
            t2_sorted_enemy_idx = _empty_idx
            t2_sorted_enemy_dist_sq = _empty_0

        # Ally matrices (within-team, for healers)
        if n1 > 1:
            diff1 = t1_pos[:, None, :] - t1_pos[None, :, :]
            ally1_dist_sq = np.sum(diff1 * diff1, axis=2)
            np.fill_diagonal(ally1_dist_sq, np.inf)
            t1_sorted_ally_idx = np.argsort(ally1_dist_sq, axis=1)
            t1_sorted_ally_dist_sq = np.take_along_axis(ally1_dist_sq, t1_sorted_ally_idx, axis=1)
        else:
            t1_sorted_ally_idx = _empty_idx
            t1_sorted_ally_dist_sq = _empty_0

        if n2 > 1:
            diff2 = t2_pos[:, None, :] - t2_pos[None, :, :]
            ally2_dist_sq = np.sum(diff2 * diff2, axis=2)
            np.fill_diagonal(ally2_dist_sq, np.inf)
            t2_sorted_ally_idx = np.argsort(ally2_dist_sq, axis=1)
            t2_sorted_ally_dist_sq = np.take_along_axis(ally2_dist_sq, t2_sorted_ally_idx, axis=1)
        else:
            t2_sorted_ally_idx = _empty_idx
            t2_sorted_ally_dist_sq = _empty_0

        targeting = TargetingData(
            alive_t1=alive_t1, alive_t2=alive_t2,
            t1_sorted_enemy_idx=t1_sorted_enemy_idx,
            t1_sorted_enemy_dist_sq=t1_sorted_enemy_dist_sq,
            t2_sorted_enemy_idx=t2_sorted_enemy_idx,
            t2_sorted_enemy_dist_sq=t2_sorted_enemy_dist_sq,
            t1_sorted_ally_idx=t1_sorted_ally_idx,
            t1_sorted_ally_dist_sq=t1_sorted_ally_dist_sq,
            t2_sorted_ally_idx=t2_sorted_ally_idx,
            t2_sorted_ally_dist_sq=t2_sorted_ally_dist_sq,
            t1_index=t1_index, t2_index=t2_index,
        )

        # Populate per-unit targeting lists and collision neighbor lists
        for i, u in enumerate(alive_t1):
            diam_sq = u.diameter_sq
            rng_sq = u.attack_range_sq
            if n2 > 0:
                enemy_dsq = t1_sorted_enemy_dist_sq[i]
                enemy_idx = t1_sorted_enemy_idx[i]
                u.nearest_enemies = [alive_t2[j] for j in enemy_idx]
                u.enemies_in_range = u.nearest_enemies[:int(np.searchsorted(enemy_dsq, rng_sq, side='right'))]
                nearby_enemies = u.nearest_enemies[:int(np.searchsorted(enemy_dsq, diam_sq, side='right'))]
            else:
                u.nearest_enemies = []
                u.enemies_in_range = []
                nearby_enemies = []
            if n1 > 1:
                ally_dsq = t1_sorted_ally_dist_sq[i]
                ally_idx = t1_sorted_ally_idx[i]
                u.nearest_allies = [alive_t1[j] for j in ally_idx]
                u.allies_in_range = u.nearest_allies[:int(np.searchsorted(ally_dsq, rng_sq, side='right'))]
                nearby_allies = u.nearest_allies[:int(np.searchsorted(ally_dsq, diam_sq, side='right'))]
            else:
                u.nearest_allies = []
                u.allies_in_range = []
                nearby_allies = []
            u.nearby_units = nearby_enemies + nearby_allies
        for i, u in enumerate(alive_t2):
            diam_sq = u.diameter_sq
            rng_sq = u.attack_range_sq
            if n1 > 0:
                enemy_dsq = t2_sorted_enemy_dist_sq[i]
                enemy_idx = t2_sorted_enemy_idx[i]
                u.nearest_enemies = [alive_t1[j] for j in enemy_idx]
                u.enemies_in_range = u.nearest_enemies[:int(np.searchsorted(enemy_dsq, rng_sq, side='right'))]
                nearby_enemies = u.nearest_enemies[:int(np.searchsorted(enemy_dsq, diam_sq, side='right'))]
            else:
                u.nearest_enemies = []
                u.enemies_in_range = []
                nearby_enemies = []
            if n2 > 1:
                ally_dsq = t2_sorted_ally_dist_sq[i]
                ally_idx = t2_sorted_ally_idx[i]
                u.nearest_allies = [alive_t2[j] for j in ally_idx]
                u.allies_in_range = u.nearest_allies[:int(np.searchsorted(ally_dsq, rng_sq, side='right'))]
                nearby_allies = u.nearest_allies[:int(np.searchsorted(ally_dsq, diam_sq, side='right'))]
            else:
                u.nearest_allies = []
                u.allies_in_range = []
                nearby_allies = []
            u.nearby_units = nearby_enemies + nearby_allies

        self._stats.record_subsystem("targeting_build", (_perf() - _t) * 1000)

        _t = _perf()
        for entity in self.entities:
            entity.update(dt)
        self._stats.record_subsystem("entity_update", (_perf() - _t) * 1000)

        units = self.units
        obstacles = self._static_obstacles
        metal_extractors = self.metal_extractors

        _t = _perf()
        for team, ai in self.team_ai.items():
            try:
                ai.on_step(self._iteration)
            except Exception:
                other_team = 2 if team == 1 else 1
                self._winner = other_team
                self._phase = "explode"
                self._anim_timer = 0.0
        self._stats.record_subsystem("ai_step", (_perf() - _t) * 1000)

        # Capture — track new entities so extractors join units + team lists
        entity_count_before_capture = len(self.entities)
        _t = _perf()
        capture_step(self.entities, self.command_centers, self.units, self.metal_spots, metal_extractors, dt, stats=self._stats)
        self._stats.record_subsystem("capture", (_perf() - _t) * 1000)

        if len(self.entities) > entity_count_before_capture:
            for e in self.entities[entity_count_before_capture:]:
                if isinstance(e, Unit):
                    self.units.append(e)
                    if e.team == 1:
                        self.team_1_units.append(e)
                    elif e.team == 2:
                        self.team_2_units.append(e)

        _t = _perf()
        combat_step(self.units, obstacles, self.laser_flashes, dt, targeting=targeting,
                    circle_obs=self._obs_circle, rect_obs=self._obs_rect,
                    sounds=None if self._headless else self._sounds,
                    pending_chains=self._pending_chains, stats=self._stats)
        self._stats.record_subsystem("combat", (_perf() - _t) * 1000)

        # Spawn — spawn_step already appends to self.units; add to team lists
        entity_count_before_spawn = len(self.entities)
        _t = _perf()
        spawn_step(self.entities, self.command_centers, self.human_teams, stats=self._stats, tick=self._iteration, units=self.units)
        self._stats.record_subsystem("spawn", (_perf() - _t) * 1000)

        if len(self.entities) > entity_count_before_spawn:
            self._physics_cooldown = 60  # 1 second to settle after spawn
            for e in self.entities[entity_count_before_spawn:]:
                if isinstance(e, Unit):
                    if e.team == 1:
                        self.team_1_units.append(e)
                    elif e.team == 2:
                        self.team_2_units.append(e)

        _t = _perf()
        self.entities = [e for e in self.entities if e.alive]
        self.units = [u for u in self.units if u.alive]
        self.team_1_units = [u for u in self.team_1_units if u.alive]
        self.team_2_units = [u for u in self.team_2_units if u.alive]
        self.command_centers = [c for c in self.command_centers if c.alive]
        self.metal_extractors = [m for m in self.metal_extractors if m.alive]
        self._assign_entity_ids()
        self._stats.record_subsystem("cleanup", (_perf() - _t) * 1000)

        # Physics cooldown: detect movement to keep physics running
        _t = _perf()
        units = self.units
        mobile_units = [u for u in units if not u.is_building]

        any_moving = False
        for u in mobile_units:
            if u.target is not None:
                any_moving = True
                break
        if any_moving:
            self._physics_cooldown = 10  # keep running 10 ticks after movement stops

        if self._physics_cooldown > 0:
            self._physics_cooldown -= 1

            # Vectorized unit-unit collision + obstacle push
            if units:
                _tp = _perf()
                all_positions = np.column_stack([
                    np.array([u.x for u in units], dtype=np.float64),
                    np.array([u.y for u in units], dtype=np.float64),
                ])
                all_radii = np.array([u.radius for u in units], dtype=np.float64)
                all_is_bld = np.array([u.is_building for u in units], dtype=bool)

                # Build collision pairs from nearby_units (diameter-clipped)
                uid_to_idx = {id(u): i for i, u in enumerate(units)}
                _pairs_i: list[int] = []
                _pairs_j: list[int] = []
                for u in units:
                    ui = uid_to_idx[id(u)]
                    for nb in u.nearby_units:
                        nj = uid_to_idx.get(id(nb))
                        if nj is not None and ui < nj:
                            _pairs_i.append(ui)
                            _pairs_j.append(nj)
                if _pairs_i:
                    col_pi = np.array(_pairs_i, dtype=np.int64)
                    col_pj = np.array(_pairs_j, dtype=np.int64)
                else:
                    col_pi = None
                    col_pj = None
                self._stats.record_subsystem("phys_array_build", (_perf() - _tp) * 1000)

                _tp = _perf()
                all_positions = batch_unit_collisions(all_positions, all_radii, all_is_bld,
                                                     pair_i=col_pi, pair_j=col_pj)
                self._stats.record_subsystem("phys_unit_collisions", (_perf() - _tp) * 1000)

                # Obstacle push on mobile units only
                _tp = _perf()
                mobile_mask = ~all_is_bld
                if np.any(mobile_mask):
                    mob_pos = all_positions[mobile_mask]
                    mob_radii = all_radii[mobile_mask]
                    mob_pos = batch_obstacle_push(mob_pos, mob_radii, self._circle_obs_np, self._rect_obs_np)
                    all_positions[mobile_mask] = mob_pos
                self._stats.record_subsystem("phys_obstacle_push", (_perf() - _tp) * 1000)

                # Write back positions
                _tp = _perf()
                for i, u in enumerate(units):
                    u.x = float(all_positions[i, 0])
                    u.y = float(all_positions[i, 1])
                self._stats.record_subsystem("phys_writeback", (_perf() - _tp) * 1000)
            else:
                self._stats.record_subsystem("phys_array_build", 0.0)
                self._stats.record_subsystem("phys_unit_collisions", 0.0)
                self._stats.record_subsystem("phys_obstacle_push", 0.0)
                self._stats.record_subsystem("phys_writeback", 0.0)

            _tp = _perf()
            clamp_units_to_bounds(units, self.width, self.height)
            self._stats.record_subsystem("phys_clamp", (_perf() - _tp) * 1000)
        else:
            # Skip physics — just clamp bounds
            clamp_units_to_bounds(units, self.width, self.height)
            # Record zeros so sub-component averages use the same sample count
            self._stats.record_subsystem("phys_array_build", 0.0)
            self._stats.record_subsystem("phys_unit_collisions", 0.0)
            self._stats.record_subsystem("phys_obstacle_push", 0.0)
            self._stats.record_subsystem("phys_writeback", 0.0)
            self._stats.record_subsystem("phys_clamp", 0.0)
        self._stats.record_subsystem("physics", (_perf() - _t) * 1000)

        self.laser_flashes = [lf for lf in self.laser_flashes if lf.update(dt)]
        self._iteration += 1

        # Sample stats time-series every SAMPLE_INTERVAL ticks
        if self._iteration % GameStats.SAMPLE_INTERVAL == 0:
            self._stats.sample_tick(self._iteration, self.entities)

        if self._headless and (self._iteration == 1 or self._iteration % 5000 == 0):
            self._take_headless_snapshot()

        if self._replay_recorder is not None:
            self._replay_recorder.capture_tick(
                self._iteration, self.entities, self.laser_flashes,
            )

        # -- win condition: check if < 2 teams have a living CC ----------------
        surviving_teams = {cc.team for cc in self.command_centers}
        if len(surviving_teams) < 2 and self._winner == 0:
            if len(surviving_teams) == 1:
                self._winner = next(iter(surviving_teams))
            else:
                self._winner = -1  # draw — both CCs destroyed
            # Transition to explode phase instead of ending immediately
            self._phase = "explode"
            self._anim_timer = 0.0
            # Init fragments for all losing teams
            losing_teams = {1, 2} - surviving_teams
            for t in losing_teams:
                self._init_fragments(t)

        # Tick limit — force draw if exceeded
        if self._max_ticks > 0 and self._iteration >= self._max_ticks and self._winner == 0:
            self._winner = -1
            self._phase = "explode"
            self._anim_timer = 0.0

        _elapsed_ms = (time.perf_counter() - _t0) * 1000.0
        self._stats.record_step_time(_elapsed_ms)

        # Step timeout — force draw if a single step is too slow
        if self._step_timeout_ms > 0 and _elapsed_ms > self._step_timeout_ms and self._winner == 0:
            self._winner = -1
            self._phase = "explode"
            self._anim_timer = 0.0

    # -- serialization --------------------------------------------------------

    def save_state(self) -> dict[str, Any]:
        pending = []
        for ch in self._pending_chains:
            pending.append({
                "source_id": ch.source.entity_id,
                "last_target_id": ch.last_target.entity_id,
                "hit_set": list(ch.hit_set),
                "delay": ch.delay,
                "team": ch.team,
            })
        return {
            "entities": [e.to_dict() for e in self.entities],
            "laser_flashes": [lf.to_dict() for lf in self.laser_flashes],
            "pending_chains": pending,
            "iteration": self._iteration,
            "winner": self._winner,
            "next_entity_id": self._next_entity_id,
        }

    def load_state(self, data: dict[str, Any]):
        raw_entities = data["entities"]

        # Pass 1: create all entities from flat dicts
        pairs: list[tuple[Entity, dict]] = []
        for ed in raw_entities:
            cls = _ENTITY_TYPES[ed["type"]]
            entity = cls.from_dict(ed)
            pairs.append((entity, ed))

        # Pass 2: build lookup map, resolve cross-references
        id_map: dict[int, Entity] = {e.entity_id: e for e, _ in pairs}

        for entity, ed in pairs:
            if isinstance(entity, Unit):
                # Unit cross-references (applies to all Units including CC/ME)
                fid = ed.get("_follow_entity_id")
                if fid is not None and fid in id_map:
                    entity._follow_entity = id_map[fid]
                aid = ed.get("attack_target_id")
                if aid is not None and aid in id_map:
                    entity.attack_target = id_map[aid]
                # CC-specific cross-references
                if isinstance(entity, CommandCenter):
                    me_ids = ed.get("metal_extractor_ids", [])
                    entity.metal_extractors = [
                        id_map[mid] for mid in me_ids if mid in id_map
                    ]
                    entity._bounds = (self.width, self.height)
                # ME-specific cross-references
                elif isinstance(entity, MetalExtractor):
                    ms_id = ed.get("metal_spot_id")
                    if ms_id is not None and ms_id in id_map:
                        entity.metal_spot = id_map[ms_id]

        self.entities = [e for e, _ in pairs]
        self.metal_spots = [e for e in self.entities if isinstance(e, MetalSpot)]
        self.units = [e for e in self.entities if isinstance(e, Unit)]
        self.team_1_units = [u for u in self.units if u.team == 1]
        self.team_2_units = [u for u in self.units if u.team == 2]
        self.command_centers = [e for e in self.entities if isinstance(e, CommandCenter)]
        self.metal_extractors = [e for e in self.entities if isinstance(e, MetalExtractor)]
        self._precompute_obstacles()
        self.laser_flashes = [LaserFlash.from_dict(lfd) for lfd in data["laser_flashes"]]
        for lf, lfd in zip(self.laser_flashes, data["laser_flashes"]):
            sid = lfd.get("source_id")
            if sid is not None and sid in id_map:
                lf.source = id_map[sid]
            tid = lfd.get("target_id")
            if tid is not None and tid in id_map:
                lf.target = id_map[tid]
        self._pending_chains = []
        for chd in data.get("pending_chains", []):
            src_id = chd["source_id"]
            lt_id = chd["last_target_id"]
            if src_id not in id_map or lt_id not in id_map:
                continue
            src = id_map[src_id]
            if not hasattr(src, "weapon") or src.weapon is None:
                continue
            self._pending_chains.append(PendingChain(
                source=src,
                weapon=src.weapon,
                last_target=id_map[lt_id],
                hit_set=set(chd["hit_set"]),
                delay=chd["delay"],
                team=chd["team"],
            ))
        self._iteration = data["iteration"]
        self._winner = data["winner"]
        self._next_entity_id = data["next_entity_id"]
        self._apply_selectability()

    # -- render -------------------------------------------------------------

    def render(self):
        ws = self._world_surface
        ws.fill((0, 0, 0))

        if self._phase == "warp_in":
            self._render_warp_in()
        elif self._phase == "explode":
            self._render_explode()
        else:
            # Normal playing render
            for entity in self.entities:
                entity.draw(ws)
            self._draw_fog()

        if self._phase != "warp_in":
            for lf in self.laser_flashes:
                lf.draw(ws)

        # AI / Human name labels above command centers (with bonus %)
        for entity in self.entities:
            if isinstance(entity, CommandCenter) and entity.alive:
                ai = self.team_ai.get(entity.team)
                name = ai.ai_name if ai else self._player_name
                bonus_pct = entity.get_total_bonus_percent()
                if bonus_pct > 0:
                    name = f"{name} (+{bonus_pct}%)"
                team_color = TEAM1_COLOR if entity.team == 1 else TEAM2_COLOR
                name_surf = self._label_font.render(name, True, team_color)
                nx = int(entity.x) - name_surf.get_width() // 2
                ny = int(entity.y) - 40
                ws.blit(name_surf, (nx, ny))

        # Extractor bonus labels
        for entity in self.metal_extractors:
            if entity.alive:
                bonus = entity.get_spawn_bonus()
                pct = round(bonus * 100)
                team_color = TEAM1_COLOR if entity.team == 1 else TEAM2_COLOR
                label = f"+{pct}%"
                label_surf = self._label_font.render(label, True, team_color)
                lx = int(entity.x) - label_surf.get_width() // 2
                ly = int(entity.y) - int(entity.radius + HEALTH_BAR_OFFSET + 12)
                ws.blit(label_surf, (lx, ly))

        if self._dragging:
            sr = self._selection_radius()
            if sr >= 5:
                cx, cy = self._selection_center()
                self._selection_surface.fill((0, 0, 0, 0))
                pygame.draw.circle(self._selection_surface, SELECTION_FILL_COLOR,
                                   (int(cx), int(cy)), int(sr))
                pygame.draw.circle(self._selection_surface, SELECTION_RECT_COLOR,
                                   (int(cx), int(cy)), int(sr), 1)
                ws.blit(self._selection_surface, (0, 0))

        if self._rdragging and len(self._rpath) >= 2:
            pygame.draw.lines(ws, COMMAND_PATH_COLOR, False,
                              [(int(px), int(py)) for px, py in self._rpath], 2)
            selected_count = sum(
                1 for e in self.entities if isinstance(e, Unit) and e.selected
            )
            if selected_count > 0:
                preview = self._resample_path(selected_count)
                for px, py in preview:
                    pygame.draw.circle(ws, COMMAND_DOT_COLOR, (int(px), int(py)), 4, 1)

        # Project world surface to screen via camera
        self.screen.fill((0, 0, 0))
        self._camera.apply(ws, self.screen)

        # GUI stays in screen space
        if self._has_human:
            gui.draw_cc_gui(self.screen, self.entities, self.width, self.height)

        self._pause_btn.draw(self.screen)
        self._speed_slider.draw(self.screen)

        # FPS counter
        fps_val = self.clock.get_fps()
        fps_surf = self._fps_font.render(f"FPS: {fps_val:.0f}", True, (200, 200, 200))
        self.screen.blit(fps_surf, (4, 4))

        # Paused overlay
        if self._paused:
            pause_surf = self._pause_font.render("PAUSED", True, (220, 220, 240))
            hint_surf = self._fps_font.render("ESC again to quit", True, (140, 140, 160))
            px = self.width // 2 - pause_surf.get_width() // 2
            py = self.height // 2 - pause_surf.get_height() // 2 - 10
            self.screen.blit(pause_surf, (px, py))
            hx = self.width // 2 - hint_surf.get_width() // 2
            self.screen.blit(hint_surf, (hx, py + pause_surf.get_height() + 4))

        pygame.display.flip()

    # -- drawing helpers ----------------------------------------------------

    def _draw_fog(self):
        """Draw fog of war overlay — only when a human is playing."""
        if not self._has_human:
            return
        view_team = next(iter(self.human_teams))

        FOG_ALPHA = 200
        self._fog_surface.fill((0, 0, 0, FOG_ALPHA))

        # Collect friendly LOS sources (units + command centers)
        los_circles: list[tuple[int, int, int]] = []
        for entity in self.entities:
            if not entity.alive:
                continue
            if not hasattr(entity, "line_of_sight") or not hasattr(entity, "team"):
                continue
            if entity.team != view_team:
                continue
            r = int(entity.line_of_sight)
            if r <= 0:
                continue
            los_circles.append((int(entity.x), int(entity.y), r))

        # Punch transparent holes
        for ex, ey, r in los_circles:
            size = r * 2
            cutout = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(cutout, (0, 0, 0, FOG_ALPHA), (r, r), r)
            self._fog_surface.blit(cutout, (ex - r, ey - r),
                                   special_flags=pygame.BLEND_RGBA_SUB)

        self._world_surface.blit(self._fog_surface, (0, 0))

        # Border at the fog edge — outline of the union (no venn diagram)
        self._fog_border.fill((0, 0, 0))
        for ex, ey, r in los_circles:
            pygame.draw.circle(self._fog_border, (160, 160, 160), (ex, ey), r)
        for ex, ey, r in los_circles:
            pygame.draw.circle(self._fog_border, (0, 0, 0), (ex, ey), max(r - 1, 0))
        self._world_surface.blit(self._fog_border, (0, 0))

    # -- animation helpers --------------------------------------------------

    def _render_warp_in(self):
        """Render warp-in phase: non-CC entities normal, CCs scale in with glow."""
        ws = self._world_surface
        t = min(self._anim_timer / 3.0, 1.0)
        scale = t * (2.0 - t)  # ease-out curve

        # Draw all non-CC entities normally
        for entity in self.entities:
            if not isinstance(entity, CommandCenter):
                entity.draw(ws)

        # Draw CCs at scaled size
        for entity in self.entities:
            if isinstance(entity, CommandCenter) and entity.alive:
                entity.draw_scaled(ws, scale)

                # Glow ring: expands outward, fading
                glow_radius = int(CC_RADIUS * 3 * t)
                glow_alpha = int(120 * (1.0 - t))
                if glow_radius > 0 and glow_alpha > 0:
                    self._anim_surface.fill((0, 0, 0, 0))
                    glow_color = (*entity.color[:3], glow_alpha)
                    pygame.draw.circle(
                        self._anim_surface, glow_color,
                        (int(entity.x), int(entity.y)), glow_radius, 3,
                    )
                    ws.blit(self._anim_surface, (0, 0))

        self._draw_fog()

    def _init_fragments(self, team: int):
        """Create 6 triangular fragments from the losing CC's hexagon."""
        data = self._cc_data.get(team)
        if not data:
            return

        cx, cy = data["x"], data["y"]
        color = data["color"]
        pts = data["points"]  # hex vertex offsets relative to center

        for i in range(len(pts)):
            p1 = pts[i]
            p2 = pts[(i + 1) % len(pts)]
            # Triangle: center, vertex i, vertex i+1
            tri = [(0.0, 0.0), p1, p2]

            # Outward direction: average of the two outer vertices
            out_x = (p1[0] + p2[0]) / 2
            out_y = (p1[1] + p2[1]) / 2
            dist = math.hypot(out_x, out_y) or 1.0
            out_x /= dist
            out_y /= dist

            speed = random.uniform(40, 120)
            self._fragments.append({
                "points": tri,
                "cx": cx, "cy": cy,
                "vx": out_x * speed + random.uniform(-20, 20),
                "vy": out_y * speed + random.uniform(-20, 20),
                "angle": 0.0,
                "rot_speed": random.uniform(-4, 4),
                "color": color,
            })

    def _update_fragments(self, dt: float):
        """Move and rotate explosion fragments."""
        for frag in self._fragments:
            frag["cx"] += frag["vx"] * dt
            frag["cy"] += frag["vy"] * dt
            frag["angle"] += frag["rot_speed"] * dt

    def _render_explode(self):
        """Render explode phase: surviving entities normal, fragments fly out."""
        ws = self._world_surface
        # Draw all surviving entities normally
        for entity in self.entities:
            entity.draw(ws)
        self._draw_fog()

        # Draw explosion fragments
        t = min(self._anim_timer / 3.0, 1.0)
        alpha = int(255 * (1.0 - t))
        if alpha <= 0:
            return

        self._anim_surface.fill((0, 0, 0, 0))
        for frag in self._fragments:
            cos_a = math.cos(frag["angle"])
            sin_a = math.sin(frag["angle"])
            rotated = []
            for px, py in frag["points"]:
                rx = px * cos_a - py * sin_a + frag["cx"]
                ry = px * sin_a + py * cos_a + frag["cy"]
                rotated.append((rx, ry))

            frag_color = (*frag["color"][:3], alpha)
            pygame.draw.polygon(self._anim_surface, frag_color, rotated)

        ws.blit(self._anim_surface, (0, 0))

    # -- headless snapshot ----------------------------------------------------

    _SNAP_W = 240
    _SNAP_H = 180
    _SNAP_PAD = 10

    def _take_headless_snapshot(self) -> None:
        """Render a small top-down minimap of the current game state."""
        sw, sh = self._SNAP_W, self._SNAP_H
        surf = pygame.Surface((sw, sh))
        surf.fill((20, 20, 30))

        sx = sw / self.width
        sy = sh / self.height

        t1 = TEAM1_COLOR
        t2 = TEAM2_COLOR
        gold = (255, 200, 60)
        obstacle_col = (80, 80, 80)

        # Obstacles
        for e in self.entities:
            if isinstance(e, (RectEntity, CircleEntity, PolygonEntity)):
                r = max(int(getattr(e, "radius", 4) * sx), 2)
                pygame.draw.circle(surf, obstacle_col,
                                   (int(e.x * sx), int(e.y * sy)), r)

        # Metal spots
        for ms in self.metal_spots:
            col = gold
            if getattr(ms, "owner", None) == 1:
                col = t1
            elif getattr(ms, "owner", None) == 2:
                col = t2
            pygame.draw.circle(surf, col,
                               (int(ms.x * sx), int(ms.y * sy)), 3)

        # Metal extractors
        for e in self.metal_extractors:
            if e.alive:
                col = t1 if e.team == 1 else t2
                px, py = int(e.x * sx), int(e.y * sy)
                pygame.draw.polygon(surf, col,
                                    [(px, py - 3), (px + 3, py + 2), (px - 3, py + 2)])

        # Command centers
        for cc in self.command_centers:
            col = t1 if cc.team == 1 else t2
            pygame.draw.circle(surf, col,
                               (int(cc.x * sx), int(cc.y * sy)), 5)
            pygame.draw.circle(surf, (255, 255, 255),
                               (int(cc.x * sx), int(cc.y * sy)), 5, 1)

        # Mobile units
        for u in self.units:
            if u.is_building or not u.alive:
                continue
            col = t1 if u.team == 1 else t2
            r = 2 if u.unit_type != "tank" else 3
            pygame.draw.circle(surf, col,
                               (int(u.x * sx), int(u.y * sy)), r)

        # Border
        pygame.draw.rect(surf, (100, 100, 120), (0, 0, sw, sh), 1)

        # Tick label
        game_secs = self._iteration / 60.0
        m, s = divmod(int(game_secs), 60)
        label = self._headless_snap_font.render(
            f"tick {self._iteration}  ({m}:{s:02d})", True, (180, 180, 200))
        surf.blit(label, (4, sh - label.get_height() - 2))

        self._headless_snap_surf = surf

    # -- run ----------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run the game loop. Returns a result dict with winner info."""
        self.running = True

        if self._headless:
            self._phase = "playing"  # skip warp_in
            headless_font = pygame.font.SysFont(None, 28)
            self._headless_snap_font = pygame.font.SysFont(None, 18)
            self._headless_snap_surf: pygame.Surface | None = None
            while self.running:
                self.clock.tick(0)  # uncapped
                self.handle_events()  # pump events for QUIT/ESCAPE
                if not self._paused:
                    for _ in range(200):  # batch 200 ticks per frame
                        if self._phase != "playing":
                            break
                        self.step(FIXED_DT)
                if self._phase == "explode":
                    self.running = False  # skip explosion anim
                # Minimal display: black screen with in-game timer + snapshot
                self.screen.fill((0, 0, 0))
                game_secs = self._iteration / 60.0
                m, s = divmod(int(game_secs), 60)
                timer_str = f"Headless  —  {m}:{s:02d}  (tick {self._iteration})"
                timer_surf = headless_font.render(timer_str, True, (160, 160, 180))
                tx = self.width // 2 - timer_surf.get_width() // 2
                ty = self.height // 2 - timer_surf.get_height() // 2 - self._SNAP_H // 2 - 20
                self.screen.blit(timer_surf, (tx, ty))
                if self._headless_snap_surf is not None:
                    snap_x = self.width // 2 - self._SNAP_W // 2
                    snap_y = ty + timer_surf.get_height() + self._SNAP_PAD
                    self.screen.blit(self._headless_snap_surf, (snap_x, snap_y))
                pygame.display.flip()
        else:
            # Grab the mouse at game start
            self._set_mouse_grab(True)

            while self.running:
                raw_dt = self.clock.tick(self.fps) / 1000.0
                real_dt = min(raw_dt, MAX_FRAME_DT)

                self.handle_events()
                self._update_edge_pan(real_dt)

                if self._paused:
                    self.render()

                elif self._phase == "warp_in":
                    self._anim_timer += real_dt
                    if self._anim_timer >= 3.0:
                        self._phase = "playing"
                    self.render()

                elif self._phase == "playing":
                    if self._speed_multiplier <= 0:
                        sim_dt = FIXED_DT * 100  # unlimited: up to 100 ticks/frame
                    else:
                        sim_dt = real_dt * self._speed_multiplier

                    self._accumulator += sim_dt

                    while self._accumulator >= FIXED_DT and self.running:
                        self.step(FIXED_DT)
                        self._accumulator -= FIXED_DT

                    self.render()

                elif self._phase == "explode":
                    self._anim_timer += real_dt
                    self._update_fragments(real_dt)
                    if self._anim_timer >= 3.0:
                        self.running = False
                    self.render()

            # Release mouse on game exit
            self._set_mouse_grab(False)

        stats_data = self._stats.finalize(self._winner, self.entities)
        if self._replay_recorder is not None:
            replay_path = self._replay_recorder.save(
                self._winner, self.human_teams, stats=stats_data,
                output_dir=self._replay_output_dir,
            )
        else:
            replay_path = ""

        team_names = {}
        for team in [1, 2]:
            ai = self.team_ai.get(team)
            team_names[team] = ai.ai_name if ai else self._player_name

        result = {
            "winner": self._winner,
            "human_teams": self.human_teams,
            "stats": stats_data,
            "replay_filepath": replay_path,
            "team_names": team_names,
        }

        if self._owns_pygame:
            pygame.quit()
            import sys
            sys.exit()

        return result
