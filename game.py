"""Game class — owns the loop, wires systems together."""
from __future__ import annotations
import dataclasses
import math
import random
import sys
import time
from typing import Any
import pygame
import pygame.sndarray

from entities.base import Entity
from entities.unit import Unit, HOLD_FIRE, TARGET_FIRE, FREE_FIRE
from entities.command_center import CommandCenter
from entities.laser import LaserFlash, SplashEffect
from systems.combat import combat_step, PendingChain
from systems.physics import clamp_units_to_bounds
from systems.spawning import spawn_step
from systems.selection import (
    click_select, apply_circle_selection, apply_rect_selection,
    select_all_of_type, _deselect_all,
)
from systems.ai import BaseAI, WanderAI
from systems.map_generator import BaseMapGenerator, DefaultMapGenerator
from systems.capturing import capture_step
from systems.visibility import (
    collect_team_los, compute_team_visibility, get_visible_enemy_ids,
    TeamVisionState,
)
from entities.metal_spot import MetalSpot
from entities.metal_extractor import MetalExtractor
from config import display as display_config
from config.settings import (
    SELECTION_FILL_COLOR, SELECTION_RECT_COLOR,
    COMMAND_PATH_COLOR, COMMAND_DOT_COLOR, PATH_SAMPLE_MIN_DIST,
    FIXED_DT, MAX_FRAME_DT, CC_RADIUS, CC_SPAWN_INTERVAL,
    PLAYER_COLORS, TEAM_COLORS, HEALTH_BAR_OFFSET,
    CAMERA_ZOOM_STEP, CAMERA_MAX_ZOOM,
    EDGE_PAN_MARGIN, EDGE_PAN_SPEED,
)
from entities.shapes import RectEntity, CircleEntity, PolygonEntity
from systems.commands import GameCommand, CommandQueue
from systems.replay import ReplayRecorder
from systems.chat import (
    ChatLog, ChatMessage, FloatingChatText,
    MAX_MESSAGE_LENGTH, CHAT_DISPLAY_COUNT, CHAT_DISPLAY_DURATION,
)
from systems.stats import GameStats
from core.vectorized import build_obstacle_arrays, batch_obstacle_push, batch_unit_collisions, batch_facing_update
from core.quadfield import QuadField
from core.camera import Camera
import numpy as np
import config.audio as audio

try:
    from core.fast_collisions import collision_pass as _cy_collision_pass
    _HAS_CYTHON = True
except ImportError:
    _HAS_CYTHON = False

import os
from ui.widgets import Slider, Button, draw_countdown_overlay
import gui

_DBLCLICK_MS = 400

# -- metallic border colours (outer highlight → inner shadow) ----------
_BORDER_OUTER = (160, 165, 175)
_BORDER_MID = (100, 105, 115)
_BORDER_INNER = (60, 62, 70)


def _draw_metallic_border(surface: pygame.Surface, rect: pygame.Rect,
                          thickness: int = 3) -> None:
    """Draw a bevelled metallic border around *rect*."""
    colors = [_BORDER_OUTER, _BORDER_MID, _BORDER_INNER]
    for i in range(min(thickness, len(colors))):
        c = colors[i]
        r = rect.inflate(-i * 2, -i * 2)
        if r.w > 0 and r.h > 0:
            pygame.draw.rect(surface, c, r, 1)

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
        player_ai: dict[int, BaseAI] | None = None,
        player_team: dict[int, int] | None = None,
        player_colors: dict[int, int] | None = None,
        player_handicaps: dict[int, int] | None = None,
        team_ai: dict[int, BaseAI] | None = None,  # legacy alias for player_ai
        screen: pygame.Surface | None = None,
        clock: pygame.time.Clock | None = None,
        replay_config: dict | None = None,
        player_name: str = "Human",
        headless: bool = False,
        max_ticks: int = 0,
        save_replay: bool = True,
        save_debug_summary: bool = False,
        step_timeout_ms: float = 0,
        replay_output_dir: str = "",
        screen_width: int | None = None,
        screen_height: int | None = None,
        is_multiplayer: bool = False,
        selectable_teams: set[int] | None = None,
        enable_t2: bool = False,
        fog_of_war: bool = False,
        server_mode: bool = False,
        spectator_players: "set[int] | list[int] | None" = None,
        is_spectator_view: bool = False,
    ):
        """
        *team_ai* maps team numbers to AI controllers.  Teams **not** present
        in the dict are human-controlled.  At least one team must have an AI
        (Human-vs-Human is not supported).

        Legacy *team_ai* (maps team_id → AI) is still accepted and treated as
        player_ai with team_id == player_id (1v1 default).

        Examples::

            player_ai={2: WanderAI()}, player_team={1:1, 2:2}  # Human (P1/T1) vs AI (P2/T2)
            player_ai={1: EasyAI(), 2: WanderAI(), 3: EasyAI(), 4: WanderAI()},
            player_team={1:1, 2:1, 3:2, 4:2}  # 2v2
        """
        # Backward compat: treat team_ai as player_ai when player_ai not given
        if player_ai is None and team_ai is not None:
            player_ai = team_ai

        self._server_mode = server_mode

        if server_mode:
            # Headless dedicated server — no display, no fonts, no UI
            self.screen = pygame.Surface((1, 1))
            self._owns_pygame = False
            headless = True
        elif screen is None:
            pygame.init()
            self.screen = pygame.display.set_mode((width, height))
            pygame.display.set_caption(title)
            self._owns_pygame = True
        else:
            self.screen = screen
            self._owns_pygame = False

        # Map dimensions (world)
        self.width = width
        self.height = height

        # Screen dimensions (display) — defaults to map dims for backward compat
        self._screen_width = screen_width if screen_width is not None else width
        self._screen_height = screen_height if screen_height is not None else height

        if not server_mode:
            # Layout areas
            self._header_h = 40
            self._hud_h = int(self._screen_height * 0.20)
            self._header_rect = pygame.Rect(0, 0, self._screen_width, self._header_h)
            self._hud_rect = pygame.Rect(0, self._screen_height - self._hud_h,
                                         self._screen_width, self._hud_h)
            self._game_area = pygame.Rect(0, self._header_h, self._screen_width,
                                          self._screen_height - self._header_h - self._hud_h)

        self.clock = clock or pygame.time.Clock()
        self.running = False
        self.fps = 60
        self._headless = headless
        self._max_ticks = max_ticks
        self._save_replay = save_replay
        self._save_debug_summary = save_debug_summary
        self.enable_t2 = enable_t2
        self._fog_of_war = fog_of_war
        # Per-team vision state for server-side fog (populated in step())
        self._team_vision: dict[int, TeamVisionState] = {}
        self._visible_enemies_per_team: dict[int, set[int]] = {}
        self._step_timeout_ms = step_timeout_ms
        if not replay_output_dir:
            from core.paths import app_path
            replay_output_dir = app_path("replays")
        self._replay_output_dir = replay_output_dir
        self._player_name = player_name
        if not server_mode:
            self._fps_font = pygame.font.SysFont(None, 22)
            self._label_font = pygame.font.SysFont(None, 20)
        else:
            self._fps_font = None
            self._label_font = None

        self.entities: list[Entity] = []
        self.laser_flashes: list[LaserFlash] = []
        self.splash_effects: list[SplashEffect] = []
        self._pending_chains: list[PendingChain] = []

        # -- chat -------------------------------------------------------------
        self._chat_log = ChatLog()
        self._chat_events: list[dict] = []
        self._floating_chats: list[FloatingChatText] = []
        self._chat_input_active = False
        self._chat_input_text = ""
        self._chat_mode = "all"  # "all" or "team"
        self._chat_scroll = 0    # scroll offset for full chat log when input is open
        self._game_time = 0.0

        # -- sounds -----------------------------------------------------------
        if not headless:
            from core.paths import asset_path
            _sounds_dir = asset_path("sounds")
            self._sounds: dict[str, pygame.mixer.Sound] = {
                "fast_laser": pygame.mixer.Sound(os.path.join(_sounds_dir, "fast_laser.mp3")),
                "laser": pygame.mixer.Sound(os.path.join(_sounds_dir, "laser.mp3")),
            }
            # Generate "artillery" sound: pitch-shift laser.mp3 down ~8 semitones
            # by stretching the raw PCM array 1.7x longer.
            try:
                _base = pygame.mixer.Sound(os.path.join(_sounds_dir, "laser.mp3"))
                _arr = pygame.sndarray.array(_base)
                _factor = 1.7  # slower = lower pitch
                _n = int(len(_arr) * _factor)
                _idx = np.linspace(0, len(_arr) - 1, _n).astype(np.int32)
                _heavy = _arr[_idx]
                # Boost amplitude by 40% and clip to dtype range
                _heavy_f = _heavy.astype(np.float32) * 1.4
                if np.issubdtype(_arr.dtype, np.integer):
                    _info = np.iinfo(_arr.dtype)
                    _heavy = np.clip(_heavy_f, _info.min, _info.max).astype(_arr.dtype)
                else:
                    _heavy = np.clip(_heavy_f, -1.0, 1.0).astype(_arr.dtype)
                self._sounds["artillery"] = pygame.sndarray.make_sound(_heavy)
            except Exception:
                self._sounds["artillery"] = self._sounds["laser"]
        else:
            self._sounds: dict[str, pygame.mixer.Sound] = {}

        # -- player/team resolution -------------------------------------------
        _default_ai: dict[int, BaseAI] = {2: WanderAI()}
        self.player_ai: dict[int, BaseAI] = player_ai if player_ai is not None else _default_ai

        if player_team is not None:
            self.player_team: dict[int, int] = player_team
        else:
            # Default: each player is their own team
            _all_pids = set(self.player_ai.keys())
            if len(_all_pids) < 2:
                _all_pids |= {1, 2}  # backward compat: bare Game() gets 1v1
            self.player_team = {p: p for p in _all_pids}

        self.all_teams: set[int] = set(self.player_team.values())
        self.all_players: set[int] = set(self.player_team.keys())
        self.human_players: set[int] = self.all_players - set(self.player_ai.keys())
        self.human_teams: set[int] = {self.player_team[p] for p in self.human_players}
        self._selectable_teams: set[int] = (
            set(selectable_teams) if selectable_teams is not None else set(self.human_teams)
        )
        # Players whose spawned units should be selectable — derived from
        # _selectable_teams so multiplayer host (selectable_teams={1}) never
        # gets client-side units marked selectable.
        self._selectable_players: set[int] = {
            p for p, t in self.player_team.items() if t in self._selectable_teams
        }

        # Legacy alias so external code (Perigee, arena, etc.) keeps working
        self.team_ai: dict[int, BaseAI] = self.player_ai

        gen = map_generator or DefaultMapGenerator()
        self.entities = gen.generate(width, height, player_team=self.player_team)
        self.metal_spots: list[MetalSpot] = [
            e for e in self.entities if isinstance(e, MetalSpot)
        ]
        self.units: list[Unit] = [e for e in self.entities if isinstance(e, Unit)]
        self.team_units: dict[int, list[Unit]] = {
            t: [u for u in self.units if u.team == t] for t in self.all_teams
        }
        # Backward-compat references
        self.team_1_units: list[Unit] = self.team_units.get(1, [])
        self.team_2_units: list[Unit] = self.team_units.get(2, [])
        self.command_centers: list[CommandCenter] = [
            e for e in self.entities if isinstance(e, CommandCenter)
        ]
        # Snapshot each player's starting CC position. Survives CC destruction
        # so AIs can keep targeting an enemy spawn even after the CC is gone.
        self._spawn_locations: dict[int, tuple[float, float]] = {
            cc.player_id: (cc.x, cc.y) for cc in self.command_centers
        }
        self.metal_extractors: list[MetalExtractor] = [
            e for e in self.entities if isinstance(e, MetalExtractor)
        ]
        self._precompute_obstacles()

        # -- spatial index for fast proximity queries --------------------------
        self._quadfield = QuadField(width, height, cell_size=10)
        self._quadfield.rebuild(self.units)

        self._next_entity_id: int = 1
        self._speed_multiplier: float = 1.0
        self._accumulator: float = 0.0
        self._assign_entity_ids()

        self._iteration = 0
        self._winner = 0  # 0 = undecided, positive = winning team, -1 = draw
        self._stats = GameStats(teams=self.all_teams)

        self._command_queue = CommandQueue()

        # T2 upgrade tracking: team → set of unit_type strings upgraded to T2
        self._t2_upgrades: dict[int, set[str]] = {t: set() for t in self.all_teams}
        # T2 in-progress tracking: unit types currently being researched
        self._t2_researching: dict[int, set[str]] = {t: set() for t in self.all_teams}

        # Player color mapping: player_id → index into PLAYER_COLORS
        self._player_colors: dict[int, int] | None = player_colors
        if player_colors:
            self._apply_player_colors()
        else:
            # Even without lobby overrides, publish resolved team colours so
            # MetalSpots don't pick up stale data from a previous game.
            MetalSpot.team_colors = {t: self._team_color(t) for t in self.all_teams}

        # Per-player spawn-bonus handicap: percent modifier applied to each
        # player's metal-extractor spawn bonus. Stash on the CC so the bonus
        # calc in CommandCenter.update() uses the right multiplier.
        self._player_handicaps: dict[int, int] = {
            int(pid): int(pct)
            for pid, pct in (player_handicaps or {}).items()
        }
        if self._player_handicaps:
            for cc in self.command_centers:
                cc.handicap = self._player_handicaps.get(cc.player_id, 0)

        self._apply_selectability()
        self._bind_and_start_ais()

        self._has_human = len(self.human_players) > 0
        self._is_multiplayer = is_multiplayer

        # -- spectator state --------------------------------------------------
        # Players who joined the lobby as spectators (not in player_team).
        self.spectator_players: set[int] = set(spectator_players or ())
        # Local viewer is a spectator when explicitly flagged, or when an
        # all-bot singleplayer game is being watched (no humans at all).
        self._is_spectator_view: bool = bool(is_spectator_view) or (
            not headless and not server_mode and len(self.human_players) == 0
        )
        # Team-view cycle: 0 = "All Teams" (no fog), 1..N = specific team_id.
        # Built from all_teams so spectators can restrict vision to one team.
        self._team_view: int = 0
        self._team_view_options: list[tuple[int, str]] = [(0, "All Teams")]
        for _tid in sorted(self.all_teams):
            self._team_view_options.append((_tid, f"Team {_tid}"))
        self._dragging = False
        self._drag_start: tuple[int, int] = (0, 0)
        self._drag_end: tuple[int, int] = (0, 0)

        self._rdragging = False
        self._rpath: list[tuple[float, float]] = []
        self._fight_mode = False
        self._attack_mode = False

        # Double-click detection
        self._last_click_time: int = 0
        self._last_click_pos: tuple[int, int] = (0, 0)

        self._paused = False
        self._mouse_grabbed = False

        if not server_mode:
            self._selection_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            self._speed_slider = Slider(self._screen_width - 170, 10, 150, "Speed %", 25, 800, 100, 25)
            self._pause_btn = Button(self._screen_width - 210, 12, 32, 24, "||", icon="pause")
            self._reset_cam_btn = Button(70, 12, 50, 24, "Reset", font_size=18)
            self._color_mode_btn = Button(130, 12, 60, 24, "Player", font_size=18)
            self._color_mode: str = display_config.color_mode
            self._pause_font = pygame.font.SysFont(None, 48)

            # Spectator-only team-view cycle button (mirrors replay playback).
            self._team_view_btn: Button | None = None
            if self._is_spectator_view:
                self._team_view_btn = Button(200, 12, 95, 24, "All Teams",
                                             font_size=18)
            self._spectator_font = pygame.font.SysFont(None, 20)

            # Escape menu. Spectators have no team to surrender, so the
            # third slot becomes "Draw Game" (end the match in a draw).
            self._esc_menu_open = False
            _mbw, _mbh, _mgap = 260, 44, 12
            _mx = self._screen_width // 2 - _mbw // 2
            _total_h = 4 * _mbh + 3 * _mgap
            _my = self._screen_height // 2 - _total_h // 2 + 20
            if self._is_spectator_view:
                _third = ("draw_game", Button(_mx, _my + 2 * (_mbh + _mgap), _mbw, _mbh, "Draw Game"))
            else:
                _third = ("surrender", Button(_mx, _my + 2 * (_mbh + _mgap), _mbw, _mbh, "Surrender"))
            self._esc_menu_btns = [
                ("resume", Button(_mx, _my, _mbw, _mbh, "Back To Game")),
                ("settings", Button(_mx, _my + (_mbh + _mgap), _mbw, _mbh, "Settings", enabled=False)),
                _third,
                ("lobby", Button(_mx, _my + 3 * (_mbh + _mgap), _mbw, _mbh, "Back to Lobby")),
            ]

            # Headless "Draw Game" button — lets the user end a long-running
            # headless game in a draw with one click (no esc menu needed).
            self._draw_game_btn: Button | None = None
            if headless:
                _dgw, _dgh = 160, 40
                self._draw_game_btn = Button(
                    self._screen_width // 2 - _dgw // 2,
                    self._screen_height - _dgh - 30,
                    _dgw, _dgh, "Draw Game",
                )

            # -- camera & world surface -------------------------------------------
            self._world_surface = pygame.Surface((width, height))
            self._bg_surface, self._bg_tile = self._build_background(width, height)
            self._camera = Camera(self._game_area.w, self._game_area.h, width, height,
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
        self._dying_units: list[dict] = []  # frozen draw data for staggered death
        self._eliminated_teams: set[int] = set()  # teams that lost all CCs
        if not server_mode:
            self._anim_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            self._fog_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            self._fog_border = pygame.Surface((width, height))
            self._fog_border.set_colorkey((0, 0, 0))

        self._physics_cooldown: int = 60  # ticks remaining; handles initial spawn settling

        # Cache CC visual data at init (CCs don't move), keyed by player_id
        self._cc_data: dict[int, dict] = {}
        for e in self.entities:
            if isinstance(e, CommandCenter):
                self._cc_data[e.player_id] = {
                    "x": e.x, "y": e.y,
                    "color": e.color,
                    "points": list(e.points),
                    "team": e.team,
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
                e.selectable = e.team in self._selectable_teams

    def _refresh_t2_upgrades(self):
        """Rebuild T2 upgrade sets from living Research Labs."""
        for t in self.all_teams:
            self._t2_upgrades[t] = set()
            self._t2_researching[t] = set()
        for me in self.metal_extractors:
            if me.alive and me.researched_unit_type:
                if me.upgrade_state == "research_lab":
                    self._t2_upgrades[me.team].add(me.researched_unit_type)
                elif me.upgrade_state == "upgrading_lab":
                    self._t2_researching[me.team].add(me.researched_unit_type)

    def _get_t2_display(self) -> dict[int, set[str]]:
        """T2 unit types whose research has FINISHED (CC can spawn them)."""
        return {t: set(self._t2_upgrades.get(t, set())) for t in self.all_teams}

    def _get_t2_researching(self) -> dict[int, set[str]]:
        """T2 unit types currently being researched (in-progress, not yet usable)."""
        return {t: set(self._t2_researching.get(t, set())) for t in self.all_teams}

    def _bind_and_start_ais(self):
        for pid, ai in self.player_ai.items():
            ai._bind(pid, self.player_team[pid], self, stats=self._stats,
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
        # Engineer overclock aura needs the live extractor list each tick.
        from systems.abilities import Overclock, Detection
        Overclock.all_metal_extractors = tuple(
            me for me in self.metal_extractors if me.alive
        )
        # Sweeper detection aura needs live sweeper + ally-target lists.
        Detection.all_sweepers = tuple(
            u for u in self.units if u.alive and u.unit_type == "sweeper"
        )
        Detection.all_units = tuple(u for u in self.units if u.alive)

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
                pid = entity.player_id
                if pid in self.human_players:
                    self._command_queue.enqueue(GameCommand(
                        type="set_rally",
                        player_id=pid,
                        tick=self._iteration,
                        data={"position": list(rally)},
                    ))

    def _move_cmd_type(self) -> str:
        if self._attack_mode:
            return "attack_move"
        if self._fight_mode:
            return "fight"
        return "move"

    def _assign_path_goals(self):
        selected = [e for e in self.entities if isinstance(e, Unit) and e.selected]
        cmd_type = self._move_cmd_type()
        self._fight_mode = False
        self._attack_mode = False
        if not selected or len(self._rpath) < 2:
            if selected and len(self._rpath) == 1:
                px, py = self._rpath[0]
                by_player: dict[int, list[int]] = {}
                for u in selected:
                    by_player.setdefault(u.player_id, []).append(u.entity_id)
                for pid, uids in by_player.items():
                    self._command_queue.enqueue(GameCommand(
                        type=cmd_type,
                        player_id=pid,
                        tick=self._iteration,
                        data={"unit_ids": uids, "targets": [(px, py)] * len(uids)},
                    ))
            return

        goals = self._resample_path(len(selected))
        assigned: set[int] = set()
        # (player_id, entity_id, target)
        assignments: list[tuple[int, int, tuple[float, float]]] = []

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
                u = selected[best_idx]
                assignments.append((u.player_id, u.entity_id, (gx, gy)))
                assigned.add(best_idx)

        by_player: dict[int, tuple[list[int], list[tuple[float, float]]]] = {}
        for pid, eid, tgt in assignments:
            if pid not in by_player:
                by_player[pid] = ([], [])
            by_player[pid][0].append(eid)
            by_player[pid][1].append(tgt)
        for pid, (uids, tgts) in by_player.items():
            self._command_queue.enqueue(GameCommand(
                type=cmd_type,
                player_id=pid,
                tick=self._iteration,
                data={"unit_ids": uids, "targets": tgts},
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
        """Pan camera when mouse is at the game area edge (only while grabbed)."""
        if not self._mouse_grabbed:
            return
        mx, my = pygame.mouse.get_pos()
        ga = self._game_area
        dx = 0.0
        dy = 0.0
        # Top edge pan uses absolute screen top so it doesn't interfere
        # with the header controls (speed slider, etc.)
        if my <= EDGE_PAN_MARGIN:
            dy = EDGE_PAN_SPEED * dt
        if not ga.collidepoint(mx, my):
            if dy:
                self._camera.pan(0, dy)
            return
        if mx <= ga.left + EDGE_PAN_MARGIN:
            dx = EDGE_PAN_SPEED * dt
        elif mx >= ga.right - EDGE_PAN_MARGIN - 1:
            dx = -EDGE_PAN_SPEED * dt
        if my >= ga.bottom - EDGE_PAN_MARGIN - 1:
            dy = -EDGE_PAN_SPEED * dt
        if dx or dy:
            self._camera.pan(dx, dy)

    # -- coordinate helpers ------------------------------------------------

    def _screen_to_world(self, pos: tuple[int, int]) -> tuple[float, float]:
        """Convert a screen position to world coordinates via the camera."""
        return self._camera.screen_to_world(
            float(pos[0] - self._game_area.x),
            float(pos[1] - self._game_area.y),
        )

    def _player_color(self, player_id: int) -> tuple:
        """Return the PLAYER_COLORS entry for a player, respecting lobby selection."""
        if self._player_colors and player_id in self._player_colors:
            idx = self._player_colors[player_id] % len(PLAYER_COLORS)
        else:
            idx = (player_id - 1) % len(PLAYER_COLORS)
        return PLAYER_COLORS[idx]

    def _team_color(self, team: int) -> tuple:
        """Return the color for a team, using the first player's color on that team."""
        if self._player_colors:
            for pid, t in self.player_team.items():
                if t == team and pid in self._player_colors:
                    return self._player_color(pid)
        return PLAYER_COLORS[(team - 1) % len(PLAYER_COLORS)]

    def _apply_player_colors(self) -> None:
        """Recolor all entities using the lobby-selected player colors."""
        for e in self.entities:
            if not isinstance(e, Unit):
                continue
            new_color = self._player_color(e.player_id)
            e._base_color = new_color
            e.color = new_color
            # Update weapon laser color too (Weapon is a frozen dataclass)
            if hasattr(e, 'weapon') and e.weapon is not None:
                e.weapon = dataclasses.replace(e.weapon, laser_color=new_color)
        # Resolve team colours for MetalSpot (owner circle and capture arcs)
        # so the spot underneath an extractor matches the player-selected colour.
        MetalSpot.team_colors = {t: self._team_color(t) for t in self.all_teams}

    def _apply_color_mode(self) -> None:
        """Recolor all units based on current color mode (player or team)."""
        for e in self.entities:
            if not isinstance(e, Unit):
                continue
            if self._color_mode == "team":
                new_color = self._team_color(e.team)
            else:
                new_color = self._player_color(e.player_id)
            e._base_color = new_color
            if not e.selected:
                e.color = new_color

    # -- events -------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._set_mouse_grab(False)
                self.running = False

            # Headless: "Draw Game" button ends the game in a draw.
            if (self._headless and self._draw_game_btn is not None
                    and self._draw_game_btn.handle_event(event)):
                if self._winner == 0:
                    self._winner = -1
                self.running = False
                continue

            if self._pause_btn.handle_event(event):
                if not self._esc_menu_open:
                    self._toggle_pause()
                continue

            # -- Chat input handling (must be before ESC handler) ---------------
            if self._chat_input_active:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._chat_input_active = False
                        self._chat_input_text = ""
                        self._chat_scroll = 0
                    elif event.key == pygame.K_RETURN:
                        if self._chat_input_text.strip():
                            if self._has_human:
                                pid = next(iter(self.human_players), 1)
                                self._command_queue.enqueue(GameCommand(
                                    type="chat",
                                    player_id=pid,
                                    tick=self._iteration,
                                    data={"message": self._chat_input_text,
                                          "mode": self._chat_mode},
                                ))
                            else:
                                # Spectator: local-only message
                                self._chat_log.add_message(ChatMessage(
                                    player_id=0,
                                    player_name="Spectator",
                                    team_id=0,
                                    message=self._chat_input_text,
                                    mode="all",
                                    tick=self._iteration,
                                    timestamp=self._game_time,
                                ))
                        self._chat_input_active = False
                        self._chat_input_text = ""
                        self._chat_scroll = 0
                    elif event.key == pygame.K_TAB:
                        # Spectators have no team — keep chat mode pinned to "all".
                        if not self._is_spectator_view:
                            self._chat_mode = (
                                "team" if self._chat_mode == "all" else "all"
                            )
                    elif event.key == pygame.K_BACKSPACE:
                        self._chat_input_text = self._chat_input_text[:-1]
                    elif event.unicode and event.unicode.isprintable():
                        if len(self._chat_input_text) < MAX_MESSAGE_LENGTH:
                            self._chat_input_text += event.unicode
                elif event.type == pygame.MOUSEWHEEL:
                    # Scroll chat history
                    self._chat_scroll = max(0, self._chat_scroll - event.y)
                continue  # block ALL events while chat is active

            # Enter key opens chat (works for players and spectators)
            if (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN
                    and not self._esc_menu_open and not self._paused):
                self._chat_input_active = True
                self._chat_input_text = ""
                self._chat_scroll = 0
                continue

            # ESC toggles the escape menu
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._esc_menu_open = not self._esc_menu_open
                if self._esc_menu_open:
                    if not self._paused:
                        self._toggle_pause()
                else:
                    if self._paused:
                        self._toggle_pause()
                continue

            # When escape menu is open, only handle menu button clicks
            if self._esc_menu_open:
                for action, btn in self._esc_menu_btns:
                    if btn.handle_event(event):
                        if action == "resume":
                            self._esc_menu_open = False
                            if self._paused:
                                self._toggle_pause()
                        elif action == "surrender":
                            if self._winner == 0:
                                my_teams = self._selectable_teams
                                other = self.all_teams - my_teams
                                self._winner = next(iter(other)) if other else -1
                            self._set_mouse_grab(False)
                            self.running = False
                        elif action == "draw_game":
                            if self._winner == 0:
                                self._winner = -1
                            self._set_mouse_grab(False)
                            self.running = False
                        elif action == "lobby":
                            if self._winner == 0:
                                self._winner = -1
                            self._set_mouse_grab(False)
                            self.running = False
                        break
                continue

            # Scroll wheel zoom (available always, even while paused)
            if event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                if self._game_area.collidepoint(mx, my):
                    vx = mx - self._game_area.x
                    vy = my - self._game_area.y
                    if event.y > 0:
                        self._camera.zoom_at(vx, vy, CAMERA_ZOOM_STEP)
                    elif event.y < 0:
                        self._camera.zoom_at(vx, vy, 1.0 / CAMERA_ZOOM_STEP)

            # Middle mouse pan (available always, even while paused)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
                if self._game_area.collidepoint(event.pos):
                    self._mid_dragging = True
                    self._mid_last = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
                self._mid_dragging = False
            elif event.type == pygame.MOUSEMOTION and self._mid_dragging:
                dx = event.pos[0] - self._mid_last[0]
                dy = event.pos[1] - self._mid_last[1]
                self._camera.pan(dx, dy)
                self._mid_last = event.pos

            # Skip all other input while paused (use pause button or ESC)
            if self._paused:
                continue

            if self._speed_slider.handle_event(event):
                self._speed_multiplier = self._speed_slider.value / 100.0

            if self._reset_cam_btn.handle_event(event):
                self._camera.reset()
                continue

            if self._color_mode_btn.handle_event(event):
                new_mode = "team" if self._color_mode == "player" else "player"
                self._color_mode = new_mode
                self._color_mode_btn.label = new_mode.title()
                display_config.set_color_mode(new_mode)
                self._apply_color_mode()
                continue

            # Spectator: cycle through "All Teams / Team 1 / Team 2 / ..."
            if self._team_view_btn is not None and self._team_view_btn.handle_event(event):
                n_opts = len(self._team_view_options)
                if n_opts > 1:
                    self._team_view = (self._team_view + 1) % n_opts
                    _, label = self._team_view_options[self._team_view]
                    self._team_view_btn.label = label
                continue

            if not self._has_human:
                continue

            # -- Selection hotkeys -----------------------------------------
            if event.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                if event.key == pygame.K_z and mods & pygame.KMOD_CTRL:
                    # Select own CC
                    _deselect_all(self.entities)
                    for e in self.entities:
                        if (isinstance(e, CommandCenter) and e.alive
                                and e.team in self._selectable_teams):
                            e.set_selected(True)
                    continue
                elif event.key == pygame.K_TAB:
                    # Select all army units
                    _deselect_all(self.entities)
                    for e in self.entities:
                        if (isinstance(e, Unit) and not e.is_building
                                and e.selectable and e.alive):
                            e.set_selected(True)
                    continue
                elif event.key == pygame.K_c and mods & pygame.KMOD_CTRL:
                    # Expand selection to all matching unit types
                    selected = [e for e in self.entities
                                if isinstance(e, Unit) and e.selected and e.alive]
                    types = {u.unit_type for u in selected}
                    teams = {u.team for u in selected}
                    if types:
                        for e in self.entities:
                            if (isinstance(e, Unit) and e.selectable and e.alive
                                    and e.unit_type in types and e.team in teams):
                                e.set_selected(True)
                    continue
                elif event.key == pygame.K_s:
                    # Stop selected units
                    selected = [e for e in self.entities
                                if isinstance(e, Unit) and e.selected
                                and not e.is_building and e.alive]
                    if selected:
                        by_player: dict[int, list[int]] = {}
                        for u in selected:
                            by_player.setdefault(u.player_id, []).append(u.entity_id)
                        for pid, uids in by_player.items():
                            self._command_queue.enqueue(GameCommand(
                                type="stop", player_id=pid,
                                tick=self._iteration, data={"unit_ids": uids},
                            ))
                    continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # HUD click — consume all clicks in the HUD area
                if self._hud_rect.collidepoint(event.pos):
                    # Minimap click — center camera
                    minimap_world = gui.handle_minimap_click(
                        event.pos[0], event.pos[1],
                        self._screen_width, self._screen_height, self._hud_h,
                        self.width, self.height,
                    )
                    if minimap_world is not None:
                        self._camera.center_on(*minimap_world)
                        continue
                    hud_result = gui.handle_hud_click(
                        self.entities, event.pos[0], event.pos[1],
                        self._screen_width, self._screen_height, self._hud_h,
                        enable_t2=self.enable_t2,
                        t2_upgrades=self._get_t2_display(),
                        t2_researching=self._get_t2_researching(),
                    )
                    if hud_result is not None:
                        self._handle_hud_action(hud_result)
                    continue
                # Only start drag if click is in game area
                if not self._game_area.collidepoint(event.pos):
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
                            viewport_rect=self._camera.get_world_viewport_rect(),
                        )
                    else:
                        click_select(
                            self.entities, wx, wy,
                            additive=bool(shift),
                        )
                    self._last_click_time = now
                    self._last_click_pos = event.pos  # screen space for distance check
                else:
                    if display_config.selection_mode == "rectangle":
                        x1, y1 = self._drag_start
                        x2, y2 = self._drag_end
                        apply_rect_selection(
                            self.entities, x1, y1, x2, y2,
                            additive=bool(shift),
                            own_player_ids=self._selectable_players,
                        )
                    else:
                        cx, cy = self._selection_center()
                        apply_circle_selection(
                            self.entities, cx, cy, sr,
                            additive=bool(shift),
                            own_player_ids=self._selectable_players,
                        )
                self._dragging = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                if not self._game_area.collidepoint(event.pos):
                    continue
                wx, wy = self._screen_to_world(event.pos)
                self._rdragging = True
                self._rpath = [(wx, wy)]

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3 and self._rdragging:
                self._rdragging = False
                self._assign_path_goals()
                self._set_rally_points()
                self._rpath = []

    # -- command application ------------------------------------------------

    # Command types that count as a player/AI "action" for APM tracking.
    # Excludes meta commands like pause/speed/surrender.
    _ACTION_COMMANDS: frozenset[str] = frozenset({
        "move", "fight", "attack_move", "attack",
        "stop", "set_fire_mode",
        "set_rally", "set_spawn_type",
        "upgrade_extractor", "set_research_type",
    })

    def _apply_command(self, cmd: GameCommand) -> None:
        """Resolve entity IDs in *cmd* and execute the mutation."""
        id_map: dict[int, Entity] = {e.entity_id: e for e in self.entities}
        data = cmd.data

        # Count this command as one action for APM (regardless of source:
        # local input, AI, or networked client).
        if cmd.type in self._ACTION_COMMANDS:
            team = self.player_team.get(cmd.player_id)
            if team is not None and team in self._stats.teams:
                self._stats.record_action(team)

        queue_mode = data.get("queue", False)

        if cmd.type == "move":
            for uid, (tx, ty) in zip(data["unit_ids"], data["targets"]):
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive and unit.player_id == cmd.player_id:
                    if queue_mode and (unit.has_active_command() or unit.command_queue):
                        unit.command_queue.append({"type": "move", "x": tx, "y": ty})
                    else:
                        unit.command_queue.clear()
                        unit.move(tx, ty)

        elif cmd.type == "fight":
            for uid, (tx, ty) in zip(data["unit_ids"], data["targets"]):
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive and unit.player_id == cmd.player_id:
                    if queue_mode and (unit.has_active_command() or unit.command_queue):
                        unit.command_queue.append({"type": "fight", "x": tx, "y": ty})
                    else:
                        unit.command_queue.clear()
                        unit.fight(tx, ty)

        elif cmd.type == "attack_move":
            for uid, (tx, ty) in zip(data["unit_ids"], data["targets"]):
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive and unit.player_id == cmd.player_id:
                    if queue_mode and (unit.has_active_command() or unit.command_queue):
                        unit.command_queue.append({"type": "attack_move", "x": tx, "y": ty})
                    else:
                        unit.command_queue.clear()
                        unit.attack_move_to(tx, ty)
                        if unit.weapon and unit.weapon.charge_time > 0:
                            unit.attack_ground_pos = (tx, ty)

        elif cmd.type == "attack":
            unit = id_map.get(data["unit_id"])
            target = id_map.get(data["target_id"])
            if (isinstance(unit, Unit) and unit.alive and unit.player_id == cmd.player_id
                    and target is not None and target.alive):
                if queue_mode and (unit.has_active_command() or unit.command_queue):
                    unit.command_queue.append({
                        "type": "attack", "target_id": target.entity_id,
                        "_target_ref": target,
                    })
                else:
                    unit.command_queue.clear()
                    unit.attack_unit_cmd(target)
                    if unit.fire_mode == HOLD_FIRE:
                        unit.fire_mode = TARGET_FIRE

        elif cmd.type == "stop":
            for uid in data["unit_ids"]:
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive and unit.player_id == cmd.player_id:
                    unit.stop()

        elif cmd.type == "set_fire_mode":
            mode = data.get("mode", FREE_FIRE)
            if mode not in (HOLD_FIRE, TARGET_FIRE, FREE_FIRE):
                mode = FREE_FIRE
            for uid in data["unit_ids"]:
                unit = id_map.get(uid)
                if isinstance(unit, Unit) and unit.alive and unit.player_id == cmd.player_id:
                    unit.fire_mode = mode

        elif cmd.type == "set_rally":
            pos = tuple(data["position"])
            for e in self.entities:
                if isinstance(e, CommandCenter) and e.player_id == cmd.player_id:
                    e.rally_point = pos

        elif cmd.type == "set_spawn_type":
            for e in self.entities:
                if isinstance(e, CommandCenter) and e.player_id == cmd.player_id:
                    e.spawn_type = data["unit_type"]

        elif cmd.type == "upgrade_extractor":
            entity = id_map.get(data["entity_id"])
            path = data["path"]  # "outpost" or "research_lab"
            if (isinstance(entity, MetalExtractor)
                    and entity.alive
                    and entity.upgrade_state == "base"
                    and entity.is_fully_reinforced
                    and entity.team == self.player_team.get(cmd.player_id)
                    and self.enable_t2):
                if path == "outpost":
                    entity.start_upgrade("outpost")
                elif path == "research_lab":
                    entity.upgrade_state = "choosing_research"

        elif cmd.type == "set_research_type":
            entity = id_map.get(data["entity_id"])
            unit_type = data["unit_type"]
            if (isinstance(entity, MetalExtractor)
                    and entity.alive
                    and entity.upgrade_state == "choosing_research"
                    and entity.team == self.player_team.get(cmd.player_id)
                    and self.enable_t2):
                entity.researched_unit_type = unit_type
                entity.start_upgrade("lab")

        elif cmd.type == "chat":
            raw_msg = str(data.get("message", ""))[:MAX_MESSAGE_LENGTH]
            mode = data.get("mode", "all")
            if mode not in ("all", "team"):
                mode = "all"
            if raw_msg.strip():
                ai = self.player_ai.get(cmd.player_id)
                name = ai.ai_name if ai else self._player_name
                team = self.player_team.get(cmd.player_id, 0)
                msg = ChatMessage(
                    player_id=cmd.player_id,
                    player_name=name,
                    team_id=team,
                    message=raw_msg,
                    mode=mode,
                    tick=self._iteration,
                    timestamp=self._game_time,
                )
                self._chat_log.add_message(msg)
                self._chat_events.append({
                    "pid": cmd.player_id,
                    "name": name,
                    "tid": team,
                    "msg": raw_msg,
                    "mode": mode,
                    "tick": self._iteration,
                })
                # Spawn floating text above sender's CC
                for e in self.entities:
                    if isinstance(e, CommandCenter) and e.player_id == cmd.player_id and e.alive:
                        color = PLAYER_COLORS[(cmd.player_id - 1) % len(PLAYER_COLORS)]
                        self._floating_chats.append(FloatingChatText(
                            x=e.x, y=e.y - 60, message=raw_msg,
                            color=color, player_name=name,
                        ))
                        break

        elif cmd.type == "surrender":
            surrendering_team = self.player_team.get(cmd.player_id, cmd.player_id)
            self._eliminate_team(surrendering_team)
            # Check if game should end (≤1 team remaining)
            remaining = self.all_teams - self._eliminated_teams
            if len(remaining) <= 1 and self._winner == 0:
                if len(remaining) == 1:
                    self._winner = next(iter(remaining))
                else:
                    self._winner = -1
                self._phase = "explode"
                self._anim_timer = 0.0

        elif cmd.type == "set_pause":
            self._paused = bool(data.get("paused", False))

        elif cmd.type == "set_speed":
            self._speed_multiplier = max(0.25, min(8.0, float(data.get("speed", 1.0))))

    def _handle_hud_action(self, result: dict):
        """Process an action dict returned by gui.handle_hud_click."""
        action = result["action"]
        if action == "set_spawn_type":
            cc = gui.get_selected_cc(self.entities)
            if cc is not None:
                self._command_queue.enqueue(GameCommand(
                    type="set_spawn_type",
                    player_id=cc.player_id,
                    tick=self._iteration,
                    data={"unit_type": result["unit_type"]},
                ))
        elif action == "stop":
            selected = [e for e in self.entities
                        if isinstance(e, Unit) and e.selected and not e.is_building]
            if selected:
                by_player: dict[int, list[int]] = {}
                for u in selected:
                    by_player.setdefault(u.player_id, []).append(u.entity_id)
                for pid, uids in by_player.items():
                    self._command_queue.enqueue(GameCommand(
                        type="stop",
                        player_id=pid,
                        tick=self._iteration,
                        data={"unit_ids": uids},
                    ))
        elif action == "attack":
            self._attack_mode = True
        elif action == "move":
            self._fight_mode = False
            self._attack_mode = False
        elif action == "fight":
            self._fight_mode = True
        elif action == "hold_fire":
            selected = [e for e in self.entities
                        if isinstance(e, Unit) and e.selected
                        and not e.is_building and e.alive]
            if selected:
                any_not_held = any(u.fire_mode != HOLD_FIRE for u in selected)
                new_mode = HOLD_FIRE if any_not_held else FREE_FIRE
                by_player: dict[int, list[int]] = {}
                for u in selected:
                    by_player.setdefault(u.player_id, []).append(u.entity_id)
                for pid, uids in by_player.items():
                    self._command_queue.enqueue(GameCommand(
                        type="set_fire_mode",
                        player_id=pid,
                        tick=self._iteration,
                        data={"unit_ids": uids, "mode": new_mode},
                    ))
        elif action == "upgrade_extractor":
            eid = result["entity_id"]
            path = result["path"]
            # Find the player_id of a human on the extractor's team
            me = next((e for e in self.entities
                       if isinstance(e, MetalExtractor) and e.entity_id == eid), None)
            if me is not None:
                pid = next((p for p in self.human_players
                            if self.player_team.get(p) == me.team), None)
                if pid is not None:
                    self._command_queue.enqueue(GameCommand(
                        type="upgrade_extractor",
                        player_id=pid,
                        tick=self._iteration,
                        data={"entity_id": eid, "path": path},
                    ))
        elif action == "set_research_type":
            eid = result["entity_id"]
            unit_type = result["unit_type"]
            me = next((e for e in self.entities
                       if isinstance(e, MetalExtractor) and e.entity_id == eid), None)
            if me is not None:
                pid = next((p for p in self.human_players
                            if self.player_team.get(p) == me.team), None)
                if pid is not None:
                    self._command_queue.enqueue(GameCommand(
                        type="set_research_type",
                        player_id=pid,
                        tick=self._iteration,
                        data={"entity_id": eid, "unit_type": unit_type},
                    ))

    # -- step ---------------------------------------------------------------

    def step(self, dt: float):
        _t0 = time.perf_counter()
        _perf = time.perf_counter

        # Reset chat events before draining commands (commands populate this list)
        self._chat_events = []

        # Drain and apply all pending commands before simulation
        _t = _perf()
        for cmd in self._command_queue.drain(self._iteration):
            self._apply_command(cmd)

        self._refresh_steer_obstacles()
        self._stats.record_subsystem("commands", (_perf() - _t) * 1000)

        # -- QuadField-based targeting build ------------------------------------
        qf = self._quadfield
        alive_units = [u for u in self.units if u.alive]

        # Sync quadfield with current positions (early-outs when cell unchanged)
        _t_tgt = _perf()
        for u in alive_units:
            qf.moved_unit(u)
        self._stats.record_subsystem("tgt_qf_sync", (_perf() - _t_tgt) * 1000)

        # -- Server-side fog of war: compute per-team visibility ----------------
        _t_tgt = _perf()
        if self._fog_of_war and self._iteration % 15 == 0:
            new_vision: dict[int, TeamVisionState] = {}
            new_vis_enemies: dict[int, set[int]] = {}
            for team_id in self.all_teams:
                los = collect_team_los(team_id, self.entities)
                prev = self._team_vision.get(team_id)
                vis = compute_team_visibility(
                    team_id, los, self.entities, self.metal_spots,
                    prev_state=prev,
                )
                new_vision[team_id] = vis
                new_vis_enemies[team_id] = get_visible_enemy_ids(
                    team_id, los, alive_units,
                )
            self._team_vision = new_vision
            self._visible_enemies_per_team = new_vis_enemies

            # Invalidate attack targets and follow targets that left fog
            for u in alive_units:
                if u.attack_target is not None and u.attack_target.alive:
                    # Don't invalidate allied targets (e.g. medic heal priority)
                    if hasattr(u.attack_target, 'team') and u.attack_target.team == u.team:
                        continue
                    vis_ids = self._visible_enemies_per_team.get(u.team, set())
                    if u.attack_target.entity_id not in vis_ids:
                        u.attack_target = None
                        # Also clear follow if it was tracking the same target
                        if (u._follow_entity is not None
                                and hasattr(u._follow_entity, 'team')
                                and u._follow_entity.team != u.team):
                            u._follow_entity = None
        self._stats.record_subsystem("tgt_visibility", (_perf() - _t_tgt) * 1000)

        _t_tgt = _perf()
        # Vectorized nearest-enemy and nearest-ally calculation every 15 ticks
        if self._iteration % 15 == 0 and alive_units:
            positions = np.array([[u.x, u.y] for u in alive_units], dtype=np.float64)
            teams = np.array([u.team for u in alive_units], dtype=np.int8)

            for team_id in np.unique(teams):
                team_mask = teams == team_id
                team_indices = np.where(team_mask)[0]
                team_pos = positions[team_mask]      # (N, 2)

                # Build enemy mask — fog-filtered when enabled
                if self._fog_of_war:
                    vis_ids = self._visible_enemies_per_team.get(int(team_id), set())
                    enemy_mask = np.array([
                        (not tm) and alive_units[i].entity_id in vis_ids
                        for i, tm in enumerate(team_mask)
                    ], dtype=bool)
                else:
                    enemy_mask = ~team_mask

                enemy_indices = np.where(enemy_mask)[0]

                # Nearest enemy
                if len(enemy_indices) > 0:
                    enemy_pos = positions[enemy_mask]     # (M, 2)
                    diffs = team_pos[:, np.newaxis, :] - enemy_pos[np.newaxis, :, :]  # (N, M, 2)
                    dists_sq = np.sum(diffs ** 2, axis=2)                              # (N, M)
                    nearest_enemy_idx = np.argmin(dists_sq, axis=1)                    # (N,)

                    enemy_units = [alive_units[j] for j in enemy_indices]
                    for i, ti in enumerate(team_indices):
                        alive_units[ti].nearest_enemy = enemy_units[nearest_enemy_idx[i]]
                else:
                    # No visible enemies — clear nearest_enemy
                    for ti in team_indices:
                        alive_units[ti].nearest_enemy = None

                # Nearest ally (excluding self via inf on the diagonal)
                n_team = len(team_indices)
                if n_team > 1:
                    ally_diffs = team_pos[:, np.newaxis, :] - team_pos[np.newaxis, :, :]  # (N, N, 2)
                    ally_dists_sq = np.sum(ally_diffs ** 2, axis=2)                        # (N, N)
                    np.fill_diagonal(ally_dists_sq, np.inf)
                    nearest_ally_idx = np.argmin(ally_dists_sq, axis=1)                    # (N,)

                    ally_units = [alive_units[j] for j in team_indices]
                    for i, ti in enumerate(team_indices):
                        alive_units[ti].nearest_ally = ally_units[nearest_ally_idx[i]]
        self._stats.record_subsystem("tgt_nearest_enemy", (_perf() - _t_tgt) * 1000)



        # Collision detection + resolution
        _t_tgt = _perf()
        if _HAS_CYTHON:
            # Cython fast path: spatial hash + resolution entirely in C
            _cy_collision_pass(alive_units)
        else:
            # Pure Python fallback via QuadField queries
            _reuse_nearby: list = []
            for u in alive_units:
                if u.is_building:
                    continue
                nearby = qf.get_units_exact(u.x, u.y, u.radius, out=_reuse_nearby)
                for other in nearby:
                    if other is u:
                        continue
                    dx = other.x - u.x
                    dy = other.y - u.y
                    dist_sq = dx * dx + dy * dy
                    min_dist = u.radius + other.radius
                    if dist_sq < min_dist * min_dist:
                        dist = math.sqrt(max(dist_sq, 1e-24))
                        overlap = min_dist - dist
                        nx = dx / dist
                        ny = dy / dist
                        if other.is_building:
                            u.x -= nx * overlap
                            u.y -= ny * overlap
                        elif id(u) < id(other):
                            half = overlap * 0.5
                            u.x -= nx * half
                            u.y -= ny * half
                            other.x += nx * half
                            other.y += ny * half
        self._stats.record_subsystem("tgt_populate", (_perf() - _t_tgt) * 1000)

        # Batch facing update (replaces per-unit _update_facing)
        _t = _perf()
        facing_units = [u for u in alive_units if not u.is_building and u._tick % 5 == 0]
        batch_facing_update(facing_units, dt * 5)

        for entity in self.entities:
            entity.update(dt)
        self._stats.record_subsystem("entity_update", (_perf() - _t) * 1000)

        units = self.units
        obstacles = self._static_obstacles
        metal_extractors = self.metal_extractors

        _t = _perf()
        for player_id, ai in self.player_ai.items():
            try:
                ai.on_step(self._iteration)
            except Exception:
                failing_team = self.player_team.get(player_id)
                if failing_team is not None:
                    self._eliminate_team(failing_team)
        self._stats.record_subsystem("ai_step", (_perf() - _t) * 1000)

        # Capture — track new entities so extractors join units + team lists
        entity_count_before_capture = len(self.entities)
        _t = _perf()
        capture_step(self.entities, self.command_centers, self.units, self.metal_spots, metal_extractors, dt, stats=self._stats, grid=self._quadfield, teams=self.all_teams)

        if len(self.entities) > entity_count_before_capture:
            for e in self.entities[entity_count_before_capture:]:
                if isinstance(e, Unit):
                    self.units.append(e)
                    self._quadfield.add_unit(e)
                    self.team_units.setdefault(e.team, []).append(e)
                    # Apply lobby-selected color to newly captured extractors
                    new_color = self._player_color(e.player_id)
                    e._base_color = new_color
                    e.color = new_color
                if hasattr(e, "selectable"):
                    e.selectable = e.team in self._selectable_teams
        self._stats.record_subsystem("capture", (_perf() - _t) * 1000)

        _t = _perf()
        self._sound_events: list[str] = []
        self._death_events: list[dict] = []
        self._game_time += dt
        combat_step(alive_units, obstacles, self.laser_flashes, dt,
                    quadfield=self._quadfield,
                    circle_obs=self._obs_circle, rect_obs=self._obs_rect,
                    splash_effects=None if self._headless else self.splash_effects,
                    sound_events=self._sound_events,
                    pending_chains=self._pending_chains, stats=self._stats)
        # Play sounds locally for non-headless games (bot-vs-bot spectating)
        if not self._headless and self._sounds:
            for snd_name in self._sound_events:
                snd = self._sounds.get(snd_name)
                if snd is not None:
                    snd.set_volume(audio.master_volume)
                    snd.play()
        self._stats.record_subsystem("combat", (_perf() - _t) * 1000)

        # Spawn — spawn_step already appends to self.units; add to team lists
        entity_count_before_spawn = len(self.entities)
        _t = _perf()
        spawn_step(self.entities, self.command_centers, self._selectable_players, stats=self._stats, tick=self._iteration, units=self.units,
                   t2_upgrades=self._t2_upgrades if self.enable_t2 else None)

        if len(self.entities) > entity_count_before_spawn:
            self._physics_cooldown = 60  # 1 second to settle after spawn
            for e in self.entities[entity_count_before_spawn:]:
                if isinstance(e, Unit):
                    self._quadfield.add_unit(e)
                    self.team_units.setdefault(e.team, []).append(e)
                    # Apply lobby-selected colors and color mode to newly spawned units
                    if hasattr(self, '_color_mode') and self._color_mode == "team":
                        new_color = self._team_color(e.team)
                    else:
                        new_color = self._player_color(e.player_id)
                    e._base_color = new_color
                    e.color = new_color
                    if hasattr(e, 'weapon') and e.weapon is not None:
                        e.weapon = dataclasses.replace(e.weapon, laser_color=new_color)
        self._stats.record_subsystem("spawn", (_perf() - _t) * 1000)

        _t = _perf()
        # Always assign IDs (cheap — skips entities that already have one)
        self._assign_entity_ids()
        # Remove dead units from quadfield; only rebuild lists if something died
        _had_deaths = False
        for u in self.units:
            if not u.alive:
                ev = u.on_death()
                if ev is not None:
                    self._death_events.append(ev)
                self._quadfield.remove_unit(u)
                _had_deaths = True
        if _had_deaths:
            self.entities = [e for e in self.entities if e.alive]
            self.units = [u for u in self.units if u.alive]
            for t in self.all_teams:
                if t in self.team_units:
                    self.team_units[t] = [u for u in self.team_units[t] if u.alive]
            self.command_centers = [c for c in self.command_centers if c.alive]
            self.metal_extractors = [m for m in self.metal_extractors if m.alive]
        if self.enable_t2:
            self._refresh_t2_upgrades()
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

            # Obstacle push (unit-unit collision already resolved above)
            if units:
                _tp = _perf()
                all_positions = np.column_stack([
                    np.array([u.x for u in units], dtype=np.float64),
                    np.array([u.y for u in units], dtype=np.float64),
                ])
                all_radii = np.array([u.radius for u in units], dtype=np.float64)
                all_is_bld = np.array([u.is_building for u in units], dtype=bool)
                self._stats.record_subsystem("phys_array_build", (_perf() - _tp) * 1000)
                self._stats.record_subsystem("phys_unit_collisions", 0.0)

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

        _t = _perf()
        self.laser_flashes = [lf for lf in self.laser_flashes if lf.update(dt)]
        self.splash_effects = [se for se in self.splash_effects if se.update(dt)]
        self._floating_chats = [fc for fc in self._floating_chats if fc.update(dt)]
        self._iteration += 1

        # Sample stats time-series every SAMPLE_INTERVAL ticks
        if self._iteration % GameStats.SAMPLE_INTERVAL == 0:
            self._stats.sample_tick(self._iteration, self.entities)

        if self._headless and not self._server_mode and (self._iteration == 1 or self._iteration % 5000 == 0):
            self._take_headless_snapshot()

        if self._replay_recorder is not None:
            self._replay_recorder.capture_tick(
                self._iteration, self.entities, self.laser_flashes,
                death_events=getattr(self, '_death_events', None),
                chat_events=self._chat_events or None,
            )

        # -- team elimination: kill units when a team loses all CCs ----------------
        surviving_teams = {cc.team for cc in self.command_centers if cc.alive}
        newly_dead = (self.all_teams - surviving_teams) - self._eliminated_teams
        for t in newly_dead:
            self._eliminate_team(t)

        # -- win condition: game ends when <= 1 team remains alive ---------------
        remaining = self.all_teams - self._eliminated_teams
        if len(remaining) <= 1 and self._winner == 0:
            if len(remaining) == 1:
                self._winner = next(iter(remaining))
            else:
                self._winner = -1  # draw (all teams eliminated)
            self._phase = "explode"
            self._anim_timer = 0.0

        # Tick limit — score-based tiebreaker, then draw if still tied
        if self._max_ticks > 0 and self._iteration >= self._max_ticks and self._winner == 0:
            scores = {t: self._stats.compute_score(t, self.entities, 0)
                      for t in self.all_teams}
            max_score = max(scores.values()) if scores else 0
            top = [t for t, s in scores.items() if s == max_score]
            self._winner = top[0] if len(top) == 1 else -1
            self._phase = "explode"
            self._anim_timer = 0.0
        self._stats.record_subsystem("bookkeeping", (_perf() - _t) * 1000)

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
            "spawn_locations": {str(pid): list(pos)
                                for pid, pos in self._spawn_locations.items()},
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
                # Resolve _target_ref in queued commands
                for qcmd in entity.command_queue:
                    if qcmd.get("type") == "attack":
                        tid = qcmd.get("target_id")
                        if tid is not None and tid in id_map:
                            qcmd["_target_ref"] = id_map[tid]
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
        self.team_units = {t: [u for u in self.units if u.team == t] for t in self.all_teams}
        self.command_centers = [e for e in self.entities if isinstance(e, CommandCenter)]
        self.metal_extractors = [e for e in self.entities if isinstance(e, MetalExtractor)]
        self._precompute_obstacles()
        self._quadfield.rebuild(self.units)
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
        # Spawn locations: prefer the saved snapshot (handles late-frame loads
        # where CCs may already be destroyed); fall back to current CC
        # positions for older saves that pre-date this field.
        saved_spawns = data.get("spawn_locations")
        if saved_spawns:
            self._spawn_locations = {
                int(pid): tuple(pos) for pid, pos in saved_spawns.items()
            }
        else:
            self._spawn_locations = {
                cc.player_id: (cc.x, cc.y) for cc in self.command_centers
            }
        self._apply_selectability()

    # -- render -------------------------------------------------------------

    def render(self):
        ws = self._world_surface
        ws.blit(self._bg_surface, (0, 0))

        if self._phase == "warp_in":
            self._render_warp_in()
        elif self._phase == "explode":
            self._render_explode()
        else:
            # Normal playing render
            if self._should_apply_fog():
                los = self._collect_los_circles()
                # Pre-pass: FOV arcs render behind unit sprites
                for entity in self.entities:
                    if hasattr(entity, "draw_fov") and self._is_visible(entity.x, entity.y, los):
                        entity.draw_fov(ws)
                for entity in self.entities:
                    if isinstance(entity, (MetalExtractor, CommandCenter)):
                        if self._is_visible(entity.x, entity.y, los):
                            entity.draw(ws)
                        else:
                            self._draw_entity_faded(entity, ws)
                    elif isinstance(entity, (RectEntity, CircleEntity, PolygonEntity, MetalSpot)):
                        entity.draw(ws)
                    else:
                        if self._is_visible(entity.x, entity.y, los):
                            entity.draw(ws)
                self._los_cache = los
            else:
                for entity in self.entities:
                    if hasattr(entity, "draw_fov"):
                        entity.draw_fov(ws)
                for entity in self.entities:
                    entity.draw(ws)
                self._los_cache = None
            self._draw_fog()

        if self._phase != "warp_in":
            _los = getattr(self, '_los_cache', None)
            # Charge previews: targeting beam + splash zone while artillery charges
            for unit in self.units:
                if not unit.alive or unit._charge_pos is None or unit.weapon is None:
                    continue
                if _los is not None and not self._is_visible(unit.x, unit.y, _los):
                    continue
                tx, ty = unit._charge_pos
                wpn = unit.weapon
                charge_frac = 1.0 - unit._charge_timer / wpn.charge_time
                beam_alpha = int(80 + 80 * charge_frac)
                ring_alpha = int(60 + 80 * charge_frac)

                # Targeting beam
                _ct = pygame.Surface(ws.get_size(), pygame.SRCALPHA)
                pygame.draw.line(_ct, (255, 160, 30, beam_alpha),
                                 (unit.x, unit.y), (tx, ty), wpn.laser_width)
                ws.blit(_ct, (0, 0))

                # Splash zone ring
                vis_r = int(wpn.splash_radius)
                if vis_r > 0:
                    _cr = pygame.Surface((vis_r * 2 + 4, vis_r * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.circle(_cr, (255, 100, 30, ring_alpha),
                                       (vis_r + 2, vis_r + 2), vis_r, 2)
                    ws.blit(_cr, (int(tx) - vis_r - 2, int(ty) - vis_r - 2))

            for se in self.splash_effects:
                if _los is not None and not self._is_visible(se.x, se.y, _los):
                    continue
                se.draw(ws)
            for lf in self.laser_flashes:
                if _los is not None and not self._is_visible(lf.x1, lf.y1, _los):
                    continue
                lf.draw(ws)

        # (name labels and extractor bonus labels drawn in screen space after camera.apply)

        if self._dragging:
            sr = self._selection_radius()
            if sr >= 5:
                self._selection_surface.fill((0, 0, 0, 0))
                if display_config.selection_mode == "rectangle":
                    x1, y1 = self._drag_start
                    x2, y2 = self._drag_end
                    rect = pygame.Rect(min(x1, x2), min(y1, y2),
                                       abs(x2 - x1), abs(y2 - y1))
                    pygame.draw.rect(self._selection_surface, SELECTION_FILL_COLOR, rect)
                    pygame.draw.rect(self._selection_surface, SELECTION_RECT_COLOR, rect, 1)
                else:
                    cx, cy = self._selection_center()
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
                    pygame.draw.circle(ws, COMMAND_PATH_COLOR, (int(px), int(py)), 5)

        # -- Composite to screen --
        self.screen.fill((0, 0, 0))

        # Header bar
        pygame.draw.rect(self.screen, (20, 20, 30), self._header_rect)
        pygame.draw.line(self.screen, (40, 40, 55),
                         (0, self._header_h - 1),
                         (self._screen_width, self._header_h - 1))

        # Header widgets
        self._pause_btn.draw(self.screen)
        self._reset_cam_btn.draw(self.screen)
        self._color_mode_btn.draw(self.screen)
        if self._team_view_btn is not None:
            self._team_view_btn.draw(self.screen)
        self._speed_slider.draw(self.screen)
        fps_val = self.clock.get_fps()
        fps_surf = self._fps_font.render(f"FPS: {fps_val:.0f}", True, (200, 200, 200))
        self.screen.blit(fps_surf, (4, 12))

        # "SPECTATING" tag for spectator viewers
        if self._is_spectator_view:
            tag = self._spectator_font.render("SPECTATING", True, (230, 200, 90))
            # Place it just right of the team-view button (or where it would be).
            tag_x = 305 if self._team_view_btn is not None else 200
            self.screen.blit(tag, (tag_x, 14))

        # Game area: tiled background (covers beyond-map dead space) then camera projection
        from core.background import blit_screen_background
        ga = self._game_area
        blit_screen_background(self.screen, ga, self._camera, self._bg_tile)
        self._camera.apply(ws, self.screen, dest=(ga.x, ga.y))

        # Metallic border around the world edge (rendered in screen space)
        bx0, by0 = self._camera.world_to_screen(0, 0)
        bx1, by1 = self._camera.world_to_screen(self.width, self.height)
        border_rect = pygame.Rect(
            int(bx0) + ga.x, int(by0) + ga.y,
            int(bx1 - bx0), int(by1 - by0),
        )
        # Clip to game area for border + screen-space labels
        clip_save = self.screen.get_clip()
        self.screen.set_clip(ga)
        _draw_metallic_border(self.screen, border_rect, 3)

        # Name labels + extractor bonus labels (screen space for crisp text)
        _los = getattr(self, '_los_cache', None)
        cam = self._camera
        zoom_font_size = max(8, int(round(20 * cam.zoom)))
        _zfs = getattr(self, '_zoom_label_font_size', 0)
        if _zfs != zoom_font_size:
            self._zoom_label_font = pygame.font.SysFont(None, zoom_font_size)
            self._zoom_label_font_size = zoom_font_size
        zfont = self._zoom_label_font

        for entity in self.entities:
            if isinstance(entity, CommandCenter) and entity.alive:
                if _los is not None and not self._is_visible(entity.x, entity.y, _los):
                    continue
                ai = self.player_ai.get(entity.player_id)
                name = ai.ai_name if ai else self._player_name
                bonus_pct = entity.get_total_bonus_percent()
                if bonus_pct > 0:
                    name = f"{name} (+{bonus_pct}%)"
                label_color = self._player_color(entity.player_id)
                name_surf = zfont.render(name, True, label_color)
                sx, sy = cam.world_to_screen(entity.x, entity.y - 40)
                self.screen.blit(name_surf, (int(sx) + ga.x - name_surf.get_width() // 2,
                                             int(sy) + ga.y))

        for entity in self.metal_extractors:
            if entity.alive:
                if _los is not None and not self._is_visible(entity.x, entity.y, _los):
                    continue
                bonus = entity.get_spawn_bonus()
                pct = round(bonus * 100)
                label = f"+{pct}%"
                label_surf = zfont.render(label, True, (255, 255, 255))
                wy = entity.y - entity.radius - HEALTH_BAR_OFFSET - 12
                sx, sy = cam.world_to_screen(entity.x, wy)
                self.screen.blit(label_surf, (int(sx) + ga.x - label_surf.get_width() // 2,
                                              int(sy) + ga.y))

        # Floating chat text (world-space, rendered in screen-space for crisp text)
        for fc in self._floating_chats:
            alpha = int(220 * fc.alpha_frac)
            sx, sy = cam.world_to_screen(fc.x, fc.y)
            sy -= fc.rise_offset
            # Build display string: "Name: message" (truncated)
            display = f"{fc.player_name}: {fc.message}" if fc.player_name else fc.message
            if len(display) > 50:
                display = display[:47] + "..."
            chat_surf = zfont.render(display, True, fc.color)
            chat_surf.set_alpha(alpha)
            self.screen.blit(chat_surf,
                             (int(sx) + ga.x - chat_surf.get_width() // 2,
                              int(sy) + ga.y))

        self.screen.set_clip(clip_save)

        # HUD area
        pygame.draw.rect(self.screen, (20, 20, 30), self._hud_rect)
        pygame.draw.line(self.screen, (40, 40, 55),
                         (0, self._hud_rect.top),
                         (self._screen_width, self._hud_rect.top))
        if self._has_human:
            gui.draw_hud(self.screen, self.entities,
                         self._screen_width, self._screen_height, self._hud_h,
                         enable_t2=self.enable_t2,
                         t2_upgrades=self._get_t2_display(),
                         t2_researching=self._get_t2_researching(),
                         camera=self._camera, world_w=self.width, world_h=self.height)

        # Game-start countdown (3, 2, 1) overlay during warp-in
        if self._phase == "warp_in":
            draw_countdown_overlay(self.screen, ga, self._anim_timer)

        # Paused overlay (centered on game area) — only when escape menu is not open
        if self._paused and not self._esc_menu_open:
            pause_surf = self._pause_font.render("PAUSED", True, (220, 220, 240))
            hint_surf = self._fps_font.render("Press ESC for menu", True, (140, 140, 160))
            px = ga.centerx - pause_surf.get_width() // 2
            py = ga.centery - pause_surf.get_height() // 2 - 10
            self.screen.blit(pause_surf, (px, py))
            hx = ga.centerx - hint_surf.get_width() // 2
            self.screen.blit(hint_surf, (hx, py + pause_surf.get_height() + 4))

        # Chat log overlay + chat input box
        self._draw_chat_overlay()
        if self._chat_input_active:
            self._draw_chat_input()

        # Escape menu overlay
        if self._esc_menu_open:
            self._draw_esc_menu()

        pygame.display.flip()

    def _draw_chat_overlay(self) -> None:
        """Draw chat messages near the top-left of the game area.

        When chat input is open, shows the full scrollable history.
        Otherwise, shows only recent messages that fade out.
        """
        from ui.widgets import _get_font
        font = _get_font(20)
        ga = self._game_area
        x = ga.x + 8
        line_h = font.get_height() + 3

        if self._chat_input_active:
            # Full scrollable history
            all_msgs = self._chat_log.get_all()
            if not all_msgs:
                return
            # How many lines fit in the game area (leave room for input box at bottom)
            max_lines = max(1, (ga.h - 60) // line_h)
            # Clamp scroll
            max_scroll = max(0, len(all_msgs) - max_lines)
            self._chat_scroll = min(self._chat_scroll, max_scroll)
            start = len(all_msgs) - max_lines - self._chat_scroll
            end = start + max_lines
            start = max(0, start)
            window = all_msgs[start:end]

            y = ga.y + 8
            for msg in window:
                prefix = "[TEAM] " if msg.mode == "team" else ""
                color = PLAYER_COLORS[(msg.player_id - 1) % len(PLAYER_COLORS)]
                text = f"{prefix}{msg.player_name}: {msg.message}"
                surf = font.render(text, True, color)
                bg = pygame.Surface((surf.get_width() + 8, surf.get_height() + 2), pygame.SRCALPHA)
                bg.fill((0, 0, 0, 150))
                self.screen.blit(bg, (x - 4, y - 1))
                self.screen.blit(surf, (x, y))
                y += line_h
        else:
            # Fading recent messages
            visible = self._chat_log.get_visible(self._game_time)
            if not visible:
                return
            y = ga.y + 8
            for msg in visible[-CHAT_DISPLAY_COUNT:]:
                age = self._game_time - msg.timestamp
                alpha = max(0, min(255, int(255 * (1.0 - age / CHAT_DISPLAY_DURATION))))
                prefix = "[TEAM] " if msg.mode == "team" else ""
                color = PLAYER_COLORS[(msg.player_id - 1) % len(PLAYER_COLORS)]
                text = f"{prefix}{msg.player_name}: {msg.message}"
                surf = font.render(text, True, color)
                surf.set_alpha(alpha)
                bg = pygame.Surface((surf.get_width() + 8, surf.get_height() + 2), pygame.SRCALPHA)
                bg.fill((0, 0, 0, int(120 * alpha / 255)))
                self.screen.blit(bg, (x - 4, y - 1))
                self.screen.blit(surf, (x, y))
                y += line_h

    def _draw_chat_input(self) -> None:
        """Draw the chat input box at the bottom of the game area."""
        from ui.widgets import _get_font
        font = _get_font(22)
        ga = self._game_area
        box_h = 28
        box_w = min(400, ga.w - 16)
        box_x = ga.x + 8
        box_y = ga.bottom - box_h - 8

        # Background
        bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg.fill((20, 20, 30, 200))
        self.screen.blit(bg, (box_x, box_y))
        pygame.draw.rect(self.screen, (80, 80, 100),
                         pygame.Rect(box_x, box_y, box_w, box_h), 1)

        # Mode label
        mode_label = "[ALL] " if self._chat_mode == "all" else "[TEAM] "
        mode_color = (200, 200, 200) if self._chat_mode == "all" else (100, 255, 100)
        mode_surf = font.render(mode_label, True, mode_color)
        self.screen.blit(mode_surf, (box_x + 6,
                                     box_y + (box_h - mode_surf.get_height()) // 2))

        # Text + cursor
        text_x = box_x + 6 + mode_surf.get_width()
        max_text_w = box_w - mode_surf.get_width() - 16
        text_surf = font.render(self._chat_input_text, True, (220, 220, 220))
        # Scroll text left if it overflows
        if text_surf.get_width() > max_text_w:
            clip_x = text_surf.get_width() - max_text_w
            self.screen.blit(text_surf, (text_x, box_y + (box_h - text_surf.get_height()) // 2),
                             area=pygame.Rect(clip_x, 0, max_text_w, text_surf.get_height()))
            cursor_x = text_x + max_text_w + 2
        else:
            self.screen.blit(text_surf, (text_x,
                                         box_y + (box_h - text_surf.get_height()) // 2))
            cursor_x = text_x + text_surf.get_width() + 2

        # Blinking cursor
        if (pygame.time.get_ticks() // 500) % 2 == 0:
            pygame.draw.line(self.screen, (220, 220, 220),
                             (cursor_x, box_y + 5), (cursor_x, box_y + box_h - 5))

        # Hint text
        hint_font = _get_font(16)
        hint = hint_font.render("TAB: toggle mode  |  ENTER: send  |  ESC: close  |  Scroll: history",
                                True, (100, 100, 120))
        self.screen.blit(hint, (box_x, box_y - hint.get_height() - 2))

    def _draw_esc_menu(self) -> None:
        """Draw a semi-transparent overlay with pause menu buttons."""
        overlay = pygame.Surface(
            (self._screen_width, self._screen_height), pygame.SRCALPHA
        )
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        title_surf = self._pause_font.render("PAUSED", True, (220, 220, 240))
        tx = self._screen_width // 2 - title_surf.get_width() // 2
        first_btn_y = self._esc_menu_btns[0][1].rect.top
        ty = first_btn_y - title_surf.get_height() - 16
        self.screen.blit(title_surf, (tx, ty))

        for _, btn in self._esc_menu_btns:
            btn.draw(self.screen)

    # -- drawing helpers ----------------------------------------------------

    @staticmethod
    def _build_background(width: int, height: int) -> tuple[pygame.Surface, pygame.Surface]:
        from core.background import build_background
        return build_background(width, height)

    def _collect_los_circles(self) -> list[tuple[int, int, int]]:
        """Collect LOS circles from the viewer's team(s).

        Spectators with a specific team selected see through that team's vision;
        players see their own team's vision (union across human teams).
        """
        if self._is_spectator_view and self._team_view > 0:
            view_teams = {self._team_view_options[self._team_view][0]}
        else:
            view_teams = self.human_teams
        circles: list[tuple[int, int, int]] = []
        for entity in self.entities:
            if not entity.alive:
                continue
            if not hasattr(entity, "line_of_sight") or not hasattr(entity, "team"):
                continue
            if entity.team not in view_teams:
                continue
            r = int(entity.line_of_sight)
            if r > 0:
                circles.append((int(entity.x), int(entity.y), r))
        return circles

    def _should_apply_fog(self) -> bool:
        """True when entity visibility should be gated by LOS for rendering."""
        if self._is_spectator_view:
            return self._team_view > 0
        return self._fog_of_war and self._has_human

    @staticmethod
    def _is_visible(px: float, py: float,
                    los_circles: list[tuple[int, int, int]]) -> bool:
        """Check if a point is within any LOS circle."""
        for cx, cy, r in los_circles:
            dx = px - cx
            dy = py - cy
            if dx * dx + dy * dy <= r * r:
                return True
        return False

    def _draw_entity_faded(self, entity, surface, alpha: int = 90):
        """Draw an entity at reduced opacity via a temp surface."""
        margin = 40
        size = margin * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        ox, oy = entity.x, entity.y
        entity.x, entity.y = float(margin), float(margin)
        entity.draw(temp)
        entity.x, entity.y = ox, oy
        temp.set_alpha(alpha)
        surface.blit(temp, (int(ox - margin), int(oy - margin)))

    def _draw_fog(self):
        """Draw fog of war overlay — only when a viewer has a bounded view.

        Fog is skipped entirely in local games where humans play on multiple teams
        (useful for debugging / local co-op/vs). Online multiplayer always keeps fog.
        Spectators see fog only when they've selected a specific team to view;
        index 0 ("All Teams") reveals everything.
        """
        if self._is_spectator_view:
            if self._team_view == 0:
                return
            spectator_fog = True
        else:
            if not self._has_human:
                return
            # Local game with humans on both teams → no fog (full visibility)
            if not self._is_multiplayer and len(self.human_teams) > 1:
                return
            spectator_fog = False

        # 70% bg dimmed to ~30% → alpha ≈ 146; classic mode keeps heavier fog.
        # Spectator fog uses hard fog (alpha 200 with border) to match replay view.
        FOG_ALPHA = 146 if (self._fog_of_war and not spectator_fog) else 200
        self._fog_surface.fill((0, 0, 0, FOG_ALPHA))

        # Reuse cached LOS circles if available, otherwise collect fresh
        los_circles = getattr(self, '_los_cache', None)
        if los_circles is None:
            los_circles = self._collect_los_circles()

        # Punch transparent holes
        for ex, ey, r in los_circles:
            size = r * 2
            cutout = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(cutout, (0, 0, 0, FOG_ALPHA), (r, r), r)
            self._fog_surface.blit(cutout, (ex - r, ey - r),
                                   special_flags=pygame.BLEND_RGBA_SUB)

        # Blur the fog edges for a softer look when soft fog_of_war is active
        if self._fog_of_war and not spectator_fog:
            w, h = self._fog_surface.get_size()
            small = pygame.transform.smoothscale(self._fog_surface,
                                                 (max(1, w // 4), max(1, h // 4)))
            blurred = pygame.transform.smoothscale(small, (w, h))
            self._fog_surface.blit(blurred, (0, 0))

        self._world_surface.blit(self._fog_surface, (0, 0))

        # Border at the fog edge — outline of the union (no venn diagram)
        if not self._fog_of_war or spectator_fog:
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

        # Draw all non-CC entities, applying fog visibility when enabled
        if self._should_apply_fog():
            los = self._collect_los_circles()
            self._los_cache = los
            for entity in self.entities:
                if isinstance(entity, CommandCenter):
                    continue
                if isinstance(entity, MetalExtractor):
                    if self._is_visible(entity.x, entity.y, los):
                        entity.draw(ws)
                    else:
                        self._draw_entity_faded(entity, ws)
                elif isinstance(entity, (RectEntity, CircleEntity, PolygonEntity, MetalSpot)):
                    entity.draw(ws)
                else:
                    if self._is_visible(entity.x, entity.y, los):
                        entity.draw(ws)
        else:
            self._los_cache = None
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

    def _eliminate_team(self, team: int):
        """Kill all CCs and units for a team and mark it as eliminated."""
        if team in self._eliminated_teams:
            return
        self._eliminated_teams.add(team)
        # Kill all CCs for this team
        for cc in self.command_centers:
            if cc.team == team and cc.alive:
                cc.alive = False
        # Fragment + staggered death for units (includes MEs)
        self._init_fragments(team)
        self._init_unit_death(team)
        # Prune dead entities from all tracking lists
        self.entities = [e for e in self.entities if e.alive]
        self.units = [u for u in self.units if u.alive]
        self.metal_extractors = [m for m in self.metal_extractors if m.alive]
        for t in list(self.team_units):
            self.team_units[t] = [u for u in self.team_units[t] if u.alive]
        # Remove dead MEs from surviving CCs' extractor lists
        for cc in self.command_centers:
            if cc.alive:
                cc.metal_extractors = [m for m in cc.metal_extractors if m.alive]

    def _init_fragments(self, team: int):
        """Create 6 triangular fragments from each losing CC's hexagon."""
        for pid, data in self._cc_data.items():
            if data.get("team") != team:
                continue
            self._init_fragments_for_cc(data)

    def _init_fragments_for_cc(self, data: dict):
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

    def _init_unit_death(self, team: int):
        """Create staggered shard fragments for all units on the losing team."""
        team_units = [u for u in self.units
                      if u.team == team and u.alive and not isinstance(u, CommandCenter)]
        random.shuffle(team_units)

        for u in team_units:
            delay = random.uniform(0.3, 2.5)
            # Store draw data so we can draw the unit frozen until it explodes
            self._dying_units.append({
                "x": u.x, "y": u.y,
                "radius": u.radius,
                "color": u._base_color,
                "delay": delay,
            })
            # Create 4-6 triangular shards from the circle
            n_shards = random.randint(4, 6)
            for j in range(n_shards):
                a1 = math.tau * j / n_shards
                a2 = math.tau * (j + 1) / n_shards
                tri = [
                    (0.0, 0.0),
                    (u.radius * math.cos(a1), u.radius * math.sin(a1)),
                    (u.radius * math.cos(a2), u.radius * math.sin(a2)),
                ]
                out_x = math.cos((a1 + a2) / 2)
                out_y = math.sin((a1 + a2) / 2)
                speed = random.uniform(30, 80)
                self._fragments.append({
                    "points": tri,
                    "cx": u.x, "cy": u.y,
                    "vx": out_x * speed + random.uniform(-15, 15),
                    "vy": out_y * speed + random.uniform(-15, 15),
                    "angle": 0.0,
                    "rot_speed": random.uniform(-5, 5),
                    "color": u._base_color,
                    "delay": delay,
                })
            # Kill the unit and trigger cleanup (e.g. ME releases metal spot)
            u.alive = False
            if hasattr(u, "on_destroy"):
                u.on_destroy()

    def _update_fragments(self, dt: float):
        """Move and rotate explosion fragments."""
        for frag in self._fragments:
            if frag.get("delay", 0) > self._anim_timer:
                continue  # not yet started
            frag["cx"] += frag["vx"] * dt
            frag["cy"] += frag["vy"] * dt
            frag["angle"] += frag["rot_speed"] * dt

    def _render_explode(self):
        """Render explode phase: surviving entities normal, fragments fly out."""
        ws = self._world_surface
        # Draw all surviving entities (with fog visibility when enabled)
        if self._should_apply_fog():
            los = self._collect_los_circles()
            self._los_cache = los
            for entity in self.entities:
                if isinstance(entity, (MetalExtractor, CommandCenter)):
                    if self._is_visible(entity.x, entity.y, los):
                        entity.draw(ws)
                    else:
                        self._draw_entity_faded(entity, ws)
                elif isinstance(entity, (RectEntity, CircleEntity, PolygonEntity, MetalSpot)):
                    entity.draw(ws)
                else:
                    if self._is_visible(entity.x, entity.y, los):
                        entity.draw(ws)
        else:
            self._los_cache = None
            for entity in self.entities:
                entity.draw(ws)

        # Draw dying units that haven't exploded yet (frozen in place)
        for du in self._dying_units:
            if self._anim_timer < du["delay"]:
                pygame.draw.circle(ws, du["color"],
                                   (int(du["x"]), int(du["y"])), du["radius"])

        self._draw_fog()

        # Draw explosion fragments (with per-fragment delay and fade)
        self._anim_surface.fill((0, 0, 0, 0))
        any_drawn = False
        for frag in self._fragments:
            delay = frag.get("delay", 0.0)
            if self._anim_timer < delay:
                continue  # not yet started
            elapsed = self._anim_timer - delay
            t = min(elapsed / 2.0, 1.0)  # fade over 2 seconds after delay
            alpha = int(255 * (1.0 - t))
            if alpha <= 0:
                continue

            cos_a = math.cos(frag["angle"])
            sin_a = math.sin(frag["angle"])
            rotated = []
            for px, py in frag["points"]:
                rx = px * cos_a - py * sin_a + frag["cx"]
                ry = px * sin_a + py * cos_a + frag["cy"]
                rotated.append((rx, ry))

            frag_color = (*frag["color"][:3], alpha)
            pygame.draw.polygon(self._anim_surface, frag_color, rotated)
            any_drawn = True

        if any_drawn:
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
            col = gold if ms.owner is None else TEAM_COLORS.get(ms.owner, gold)
            pygame.draw.circle(surf, col,
                               (int(ms.x * sx), int(ms.y * sy)), 3)

        # Metal extractors
        for e in self.metal_extractors:
            if e.alive:
                col = TEAM_COLORS.get(e.team, PLAYER_COLORS[0])
                px, py = int(e.x * sx), int(e.y * sy)
                pygame.draw.polygon(surf, col,
                                    [(px, py - 3), (px + 3, py + 2), (px - 3, py + 2)])

        # Command centers
        for cc in self.command_centers:
            col = PLAYER_COLORS[(cc.player_id - 1) % len(PLAYER_COLORS)]
            pygame.draw.circle(surf, col,
                               (int(cc.x * sx), int(cc.y * sy)), 5)
            pygame.draw.circle(surf, (255, 255, 255),
                               (int(cc.x * sx), int(cc.y * sy)), 5, 1)

        # Mobile units
        for u in self.units:
            if u.is_building or not u.alive:
                continue
            col = PLAYER_COLORS[(u.player_id - 1) % len(PLAYER_COLORS)]
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
            for cc in self.command_centers:
                cc._spawn_timer = CC_SPAWN_INTERVAL
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
                tx = self._screen_width // 2 - timer_surf.get_width() // 2
                ty = self._screen_height // 2 - timer_surf.get_height() // 2 - self._SNAP_H // 2 - 20
                self.screen.blit(timer_surf, (tx, ty))
                if self._headless_snap_surf is not None:
                    snap_x = self._screen_width // 2 - self._SNAP_W // 2
                    snap_y = ty + timer_surf.get_height() + self._SNAP_PAD
                    self.screen.blit(self._headless_snap_surf, (snap_x, snap_y))
                if self._draw_game_btn is not None:
                    self._draw_game_btn.draw(self.screen)
                pygame.display.flip()
        else:
            # Grab the mouse at game start
            self._set_mouse_grab(True)

            from systems import music
            while self.running:
                raw_dt = self.clock.tick(self.fps) / 1000.0
                music.update()
                real_dt = min(raw_dt, MAX_FRAME_DT)

                self.handle_events()
                self._update_edge_pan(real_dt)

                if self._paused:
                    self.render()

                elif self._phase == "warp_in":
                    self._anim_timer += real_dt
                    if self._anim_timer >= 3.0:
                        self._phase = "playing"
                        # CCs ready to spawn on first tick after warp-in
                        for cc in self.command_centers:
                            cc._spawn_timer = CC_SPAWN_INTERVAL
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
                    if self._anim_timer >= 4.5:
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
            replay_path = None

        # Build per-player name: AI name for AI players, player_name for humans
        player_names: dict[int, str] = {
            pid: (self.player_ai[pid].ai_name if pid in self.player_ai
                  else self._player_name)
            for pid in sorted(self.all_players)
        }

        # Build per-team name: join all player names with " & "
        team_names: dict[int, str] = {}
        for team in self.all_teams:
            names = [
                player_names[pid]
                for pid in sorted(self.all_players)
                if self.player_team.get(pid) == team
            ]
            team_names[team] = " & ".join(names) if names else f"Team {team}"

        if self._save_debug_summary:
            log_path = self._stats.save_summary_log(
                stats_data, self._winner, team_names=team_names,
            )
            print(f"[AIRTS] Game summary saved to {log_path}")

        result = {
            "winner": self._winner,
            "human_teams": self.human_teams,
            "stats": stats_data,
            "replay_filepath": replay_path,
            "team_names": team_names,
            "player_names": player_names,
            "player_team": dict(self.player_team),
            "was_spectator": self._is_spectator_view,
        }

        if self._owns_pygame:
            pygame.quit()
            import sys
            sys.exit()

        return result

    def run_server(
        self,
        pre_step: "callable | None" = None,
        post_step: "callable | None" = None,
    ) -> dict[str, Any]:
        """Run the game loop for a dedicated server — no display, real-time 60Hz.

        *pre_step* is called before each tick (e.g. to inject remote commands).
        *post_step(tick, entities, laser_flashes, winner, sound_events,
        death_events, chat_events)* is called after each tick (e.g. to
        broadcast state to clients).
        """
        # On Windows, increase timer resolution from ~15.6ms to ~1ms so that
        # time.sleep() is accurate enough for a 60Hz game loop.
        _win_timer = False
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.winmm.timeBeginPeriod(1)
                _win_timer = True
            except Exception:
                pass

        self.running = True
        self._phase = "playing"

        # -- Warp-in delay: wait 3s so client can show the warp-in
        # animation.  Accept commands (so player can pick spawn type)
        # but don't step the simulation.
        warp_end = time.perf_counter() + 3.0
        while self.running and time.perf_counter() < warp_end:
            if pre_step:
                pre_step()
            # Apply commands (set_spawn_type, set_speed, etc.)
            for cmd in self._command_queue.drain(self._iteration + 999999):
                self._apply_command(cmd)
            if post_step:
                post_step(self._iteration, self.entities,
                          self.laser_flashes, self._winner,
                          getattr(self, '_sound_events', []),
                          getattr(self, '_death_events', []),
                          getattr(self, '_chat_events', []))
                self._chat_events = []
            time.sleep(0.016)

        # Set CCs ready to spawn on first tick
        for cc in self.command_centers:
            cc._spawn_timer = CC_SPAWN_INTERVAL

        tick_interval = FIXED_DT / 1.0  # ~16.67ms at 60 ticks/sec
        next_tick = time.perf_counter()

        try:
            while self.running and self._phase == "playing":
                now = time.perf_counter()

                # Always drain commands even while paused (so unpause arrives)
                if pre_step:
                    pre_step()

                if self._paused:
                    # Apply queued commands so set_pause/set_speed are processed
                    for cmd in self._command_queue.drain(self._iteration + 999999):
                        self._apply_command(cmd)
                    time.sleep(0.016)
                    # Still broadcast current state so clients stay in sync
                    if post_step:
                        post_step(self._iteration, self.entities,
                                  self.laser_flashes, self._winner,
                                  getattr(self, '_sound_events', []),
                                  getattr(self, '_death_events', []),
                                  getattr(self, '_chat_events', []))
                        self._chat_events = []
                    next_tick = time.perf_counter()
                    continue

                effective_interval = tick_interval / self._speed_multiplier
                if now < next_tick:
                    sleep_time = next_tick - now
                    # Sleep most of the remaining time, then yield for the rest.
                    # Use a shorter sleep to avoid Windows oversleeping.
                    if sleep_time > 0.002:
                        time.sleep(sleep_time - 0.002)
                    else:
                        time.sleep(0)  # yield timeslice to other threads
                    continue

                # Cap catch-up: if we fell too far behind (e.g. GIL contention),
                # don't try to replay dozens of ticks — just reset to now.
                if now - next_tick > effective_interval * 4:
                    next_tick = now

                next_tick += effective_interval

                self.step(FIXED_DT)

                if post_step:
                    post_step(self._iteration, self.entities,
                              self.laser_flashes, self._winner,
                              getattr(self, '_sound_events', []),
                              getattr(self, '_death_events', []),
                              getattr(self, '_chat_events', []))

                # If phase transitioned to explode, the game is over
                if self._phase == "explode":
                    self.running = False
        finally:
            if _win_timer:
                try:
                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:
                    pass

        # Build result dict (same as run())
        stats_data = self._stats.finalize(self._winner, self.entities)
        if self._replay_recorder is not None:
            replay_path = self._replay_recorder.save(
                self._winner, self.human_teams, stats=stats_data,
                output_dir=self._replay_output_dir,
            )
        else:
            replay_path = None

        player_names: dict[int, str] = {
            pid: (self.player_ai[pid].ai_name if pid in self.player_ai
                  else self._player_name)
            for pid in sorted(self.all_players)
        }
        team_names: dict[int, str] = {}
        for team in self.all_teams:
            names = [
                player_names[pid]
                for pid in sorted(self.all_players)
                if self.player_team.get(pid) == team
            ]
            team_names[team] = " & ".join(names) if names else f"Team {team}"

        return {
            "winner": self._winner,
            "human_teams": self.human_teams,
            "stats": stats_data,
            "replay_filepath": replay_path,
            "team_names": team_names,
            "player_names": player_names,
            "player_team": dict(self.player_team),
        }
