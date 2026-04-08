"""Replay playback screen — renders recorded frames with transport controls."""
from __future__ import annotations
import math
import pygame
from screens.base import BaseScreen, ScreenResult
from screens.results import (_draw_3d_bar, _ease_out_cubic,
                              _compress_build_order, _build_order_label,
                              _lighten_color,
                              _PLAYER_COLORS as _RES_PLAYER_COLORS,
                              _BAR_HEIGHT, _BAR_PAD_X, _BAR_GAP, _ANIM_MS)
from systems.replay import ReplayReader, normalize_cp
from entities.effects import DeathBurst
from config.settings import (
    OBSTACLE_OUTLINE, HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT,
    HEALTH_BAR_BG, HEALTH_BAR_FG, HEALTH_BAR_LOW, HEALTH_BAR_OFFSET,
    LASER_FLASH_DURATION, CC_RADIUS, METAL_SPOT_CAPTURE_RADIUS,
    METAL_SPOT_CAPTURE_RANGE_COLOR, METAL_EXTRACTOR_RADIUS,
    CC_HP, METAL_EXTRACTOR_HP,
    METAL_SPOT_CAPTURE_ARC_WIDTH,
    METAL_EXTRACTOR_SPAWN_BONUS,
    SELECTED_COLOR, SELECTION_FILL_COLOR, SELECTION_RECT_COLOR,
    TEAM_COLORS, PLAYER_COLORS, RANGE_COLOR, MEDIC_HEAL_COLOR,
    CC_LASER_RANGE,
    CAMERA_ZOOM_STEP, CAMERA_MAX_ZOOM,
    OUTPOST_LOS,
)
from core.camera import Camera
from config.unit_types import UNIT_TYPES
from ui.widgets import Slider, Button, ToggleGroup, LineGraph, _get_font
import gui
from gui_adapter import wrap_entities
from ui.theme import (
    MENU_BG, GRAPH_LINE_COLORS,
    SCORE_FONT_SIZE, SCORE_TEAM_COLORS,
    STATS_HEADER_FONT_SIZE, STATS_SUB_FONT_SIZE,
    BUILD_ORDER_RADIUS,
)

TOP_BAR_HEIGHT = 40
BOTTOM_BAR_HEIGHT = 50
_SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]

# Command line colors for selected unit action indicators
_MOVE_CMD_COLOR = (0, 140, 40)     # dark green for move commands
_ATTACK_CMD_COLOR = (180, 30, 30)  # dark red for attack commands
_FIGHT_CMD_COLOR = (180, 50, 180)  # pinkish purple for fight commands
_ARROW_SIZE = 6                     # arrowhead half-length

# Fields that get linearly interpolated between frames
_LERP_FIELDS = {"x", "y", "rot", "cp", "tx", "ty", "fa", "atx", "aty"}

_STAT_TABS = [
    ("cc_health", "CC HP"), ("army_count", "Army Size"),
    ("units_killed", "Kills"), ("damage_dealt", "Damage"),
    ("healing_done", "Healing"), ("metal_spots", "Build %"),
    ("apm", "APM"), ("step_ms", "Step ms"),
    ("build_order", "Build"),
]

# Stats shown in the inline comparison dropdown
_DROPDOWN_STATS = [
    ("cc_health", "CC Health"),
    ("army_count", "Army Size"),
    ("units_killed", "Kills"),
    ("damage_dealt", "Damage"),
    ("healing_done", "Healing"),
    ("metal_spots", "Build %"),
    ("apm", "APM"),
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _angle_lerp(a: float, b: float, t: float) -> float:
    """Lerp between two angles (radians) using shortest path."""
    d = (b - a) % math.tau
    if d > math.pi:
        d -= math.tau
    return a + d * t


def _lerp_entity(prev: dict, cur: dict, t: float) -> dict:
    """Blend numeric visual fields between two snapshots of the same entity."""
    result = dict(cur)
    for key in _LERP_FIELDS:
        if key in prev and key in cur:
            pv = prev[key]
            cv = cur[key]
            if isinstance(pv, (int, float)) and isinstance(cv, (int, float)):
                if key == "fa":
                    result[key] = _angle_lerp(float(pv), float(cv), t)
                else:
                    result[key] = _lerp(float(pv), float(cv), t)
    return result


class ReplayPlaybackScreen(BaseScreen):
    """Plays back a .rtsreplay file with transport controls."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 filepath: str):
        super().__init__(screen, clock)
        self._filepath = filepath
        self._reader = ReplayReader(filepath)

        # Resolve team/player names from replay config.
        # Supports both new format (player_ai_names, player_team) and old format
        # (team_ai_names, team_ai_ids) so pre-existing replays still load correctly.
        config = self._reader.config
        human_teams: set[int] = set(self._reader.human_teams)

        # Accept either key prefix; int-key the dicts for uniform lookup
        _raw_ai_names = config.get("player_ai_names") or config.get("team_ai_names") or {}
        _raw_ai_ids   = config.get("player_ai_ids")   or config.get("team_ai_ids")   or {}
        ai_names = {int(k): v for k, v in _raw_ai_names.items()}
        ai_ids   = {int(k): v for k, v in _raw_ai_ids.items()}
        player_name_cfg = config.get("player_name", "Player")

        # player_team maps player_id → team_id (only present in new-format replays)
        self._player_team: dict[int, int] = {
            int(k): int(v)
            for k, v in (config.get("player_team") or {}).items()
        }

        # Collect all known player IDs
        all_pids: set[int] = set(ai_names) | set(ai_ids) | set(self._player_team)
        # Ensure human players appear (for old replays where team_id == player_id)
        for t in human_teams:
            all_pids.add(t)

        # Infer missing player→team mappings (old format: team_id == player_id)
        for pid in sorted(all_pids):
            if pid not in self._player_team:
                self._player_team[pid] = pid

        # Build per-player display names
        self._player_names: dict[int, str] = {}
        for pid in sorted(all_pids):
            team = self._player_team.get(pid, pid)
            if team in human_teams:
                self._player_names[pid] = player_name_cfg
            else:
                name = ai_names.get(pid)
                if not name:
                    aid = ai_ids.get(pid)
                    name = aid.replace("_", " ").title() if aid else None
                self._player_names[pid] = name or f"P{pid}"

        # Build per-team display names (join player names with " & ")
        team_to_pids: dict[int, list[int]] = {}
        for pid, tid in self._player_team.items():
            team_to_pids.setdefault(tid, []).append(pid)

        self._team_names: dict[int, str] = {}
        for tid, pids in team_to_pids.items():
            names = [self._player_names.get(p, f"P{p}") for p in sorted(pids)]
            self._team_names[tid] = " & ".join(names) if names else f"Team {tid}"

        # Build ordered list of (team_id, label) for team view cycling
        # Index 0 = "All Teams", then one entry per team sorted by team_id
        self._team_view_options: list[tuple[int, str]] = [(0, "All Teams")]
        for tid, name in sorted(self._team_names.items()):
            self._team_view_options.append((tid, name))

        self._playing = True
        self._ended = False
        self._speed_idx = 2  # 1.0x
        self._accumulator = 0.0
        self._frame_dt = 1.0 / 10.0  # replay records at ~10 FPS
        self._lerp_t = 1.0  # interpolation factor 0..1 between prev and cur

        # Snapshot caches for interpolation
        self._prev_entities: dict[int, dict] = {}  # id -> visual dict
        self._cur_entities: dict[int, dict] = {}
        self._cur_lasers: list[list] = []
        self._capture_current_snapshot()

        # Death-burst particle effects (client-side, ticked each frame)
        self._death_bursts: list[DeathBurst] = []

        mw = self._reader.map_width
        mh = self._reader.map_height
        total = self._reader.frame_count
        sw = self.width   # screen width
        sh = self.height  # screen height

        # Layout: top bar, game area, in-game HUD, bottom bar
        # The in-game HUD (minimap/display/portrait/actions) sits between the
        # game area and the transport bar so the player can see stats/minimap
        # for the currently selected entities, matching the live game.
        self._hud_h = int(sh * 0.20)
        self._game_area = pygame.Rect(
            0, TOP_BAR_HEIGHT, sw,
            sh - TOP_BAR_HEIGHT - BOTTOM_BAR_HEIGHT - self._hud_h,
        )
        # Y offset for game area (below top bar)
        self._gy = TOP_BAR_HEIGHT
        # Bottom bar top edge
        bot_y = sh - BOTTOM_BAR_HEIGHT
        # In-game HUD rect — sits directly above the bottom bar
        self._hud_rect = pygame.Rect(
            0, bot_y - self._hud_h, sw, self._hud_h,
        )
        # Effective screen height to pass to gui.draw_hud so the HUD anchors
        # to the top of the bottom bar instead of the very bottom of the screen.
        self._hud_screen_h = bot_y

        # ── Top bar: Back (left) → Show Actions, Score Screen, Show Stats (right) ──
        btn_h = 28
        top_cy = (TOP_BAR_HEIGHT - btn_h) // 2  # vertically centered
        self._back_btn = Button(8, top_cy, 55, btn_h, "Back")

        self._stats_data = self._reader.stats_data
        has_stats = self._stats_data is not None
        # Right-aligned buttons (from right edge)
        self._inline_stats_btn = Button(sw - 95, top_cy, 90, btn_h,
                                        "Show Stats", enabled=has_stats)
        self._score_screen_btn = Button(sw - 200, top_cy, 100, btn_h,
                                        "Score Screen", enabled=has_stats)
        self._team_view = 0  # 0=All Teams, 1=Team 1, 2=Team 2
        self._team_view_btn = Button(sw - 300, top_cy, 95, btn_h,
                                     "All Teams")

        # Selection state
        self._selected_ids: set[int] = set()
        self._dragging = False
        self._drag_start: tuple[int, int] = (0, 0)
        self._drag_end: tuple[int, int] = (0, 0)
        self._selection_surface = pygame.Surface((mw, mh), pygame.SRCALPHA)
        self._last_click_time = 0
        self._last_click_pos: tuple[int, int] = (0, 0)

        # Fog of war surfaces
        self._fog_surface = pygame.Surface((mw, mh), pygame.SRCALPHA)
        self._fog_border = pygame.Surface((mw, mh))
        self._fog_border.set_colorkey((0, 0, 0))

        # Camera & world surface for zoom/pan (viewport = game area)
        self._world_surface = pygame.Surface((mw, mh))
        # SRCALPHA scratch for transient effects (death bursts)
        self._anim_surface = pygame.Surface((mw, mh), pygame.SRCALPHA)
        self._bg_surface, self._bg_tile = self._build_background(mw, mh)
        self._camera = Camera(self._game_area.w, self._game_area.h,
                              mw, mh, max_zoom=CAMERA_MAX_ZOOM)
        self._mid_dragging = False
        self._mid_last: tuple[int, int] = (0, 0)

        # ── Bottom bar: Play/Pause (left), Scrubber (middle), Speed (right) ──
        self._play_btn = Button(8, bot_y + 12, 45, btn_h, "||",
                                icon="pause")
        scrub_x = 60
        scrub_w = sw - 145
        self._scrubber = Slider(
            scrub_x, bot_y + 10, scrub_w, "Snapshot",
            0, max(total - 1, 1), 0, 1,
        )
        self._speed_btn = Button(sw - 70, bot_y + 12, 65, btn_h,
                                 f"{_SPEEDS[self._speed_idx]}x")

        # Score Screen overlay state
        self._show_score_screen = False
        self._build_scroll: int = 0
        self._score_anim_start: int = 0

        # Stats HUD state: 0=hidden, 1=show all, 2=single stat with arrows
        self._stat_mode = 0
        self._stat_dropdown_idx = 0

        # APM tab: show all teams by default; user can hide AI to make
        # the player line readable when AI APM is much larger.
        self._apm_hide_ai: bool = False

        # Score Screen overlay widgets
        if has_stats:
            tab_w = min(90, (sw - 40) // len(_STAT_TABS) - 2)
            tab_x = (sw - len(_STAT_TABS) * (tab_w + 2)) // 2
            self._stat_tabs = ToggleGroup(tab_x, 80, _STAT_TABS,
                                          selected_index=0, btn_w=tab_w, btn_h=28)
            self._stat_graph = LineGraph(30, 115, sw - 60, sh - 200,
                                         color1=GRAPH_LINE_COLORS[0],
                                         color2=GRAPH_LINE_COLORS[1]
                                              if len(GRAPH_LINE_COLORS) > 1
                                              else GRAPH_LINE_COLORS[0])
            has_subsystem = "subsystem_ms" in (self._stats_data or {})
            btn_w = 120
            gap = 10
            total_btns_w = btn_w * 2 + gap
            btn_start_x = sw // 2 - total_btns_w // 2
            self._stat_close_btn = Button(btn_start_x, sh - 45,
                                          btn_w, 30, "Close")
            self._stat_debug_btn = Button(btn_start_x + btn_w + gap,
                                          sh - 45, btn_w, 30,
                                          "Debug", enabled=has_subsystem)
            # APM "Show/Hide AI" toggle — drawn on the APM tab, right of tabs.
            self._apm_ai_btn = Button(
                sw - 130, 80, 110, 28,
                "Show AI" if self._apm_hide_ai else "Hide AI",
                font_size=14,
            )
            self._update_stat_graph()

        # Arrow buttons for single-stat mode
        self._dd_left_btn = Button(0, 0, 22, 22, "<")
        self._dd_right_btn = Button(0, 0, 22, 22, ">")

    def _screen_to_world(self, pos: tuple[int, int]) -> tuple[float, float]:
        """Convert screen pos to world coords (accounting for game area offset)."""
        return self._camera.screen_to_world(
            float(pos[0] - self._game_area.x),
            float(pos[1] - self._game_area.y))

    def _update_stat_graph(self):
        if self._stats_data is None:
            return
        key = self._stat_tabs.value
        if key == "build_order":
            return  # build order tab doesn't use graph

        teams_data = self._stats_data.get("teams", {})
        human_teams: set[int] = set(self._reader.human_teams)

        if key == "step_ms":
            # step_ms is global, not per-team
            series = [(self._stats_data.get("step_ms", []),
                        GRAPH_LINE_COLORS[0], "Step ms")]
        else:
            # Build one series per team, sorted by team key
            series: list[tuple[list[float], tuple, str]] = []
            for team_key in sorted(teams_data.keys(), key=lambda k: int(k)):
                tid = int(team_key)
                # On the APM tab, optionally hide AI teams so the player APM
                # is readable (AI APM can be in the tens of thousands).
                if key == "apm" and self._apm_hide_ai and tid not in human_teams:
                    continue
                data = teams_data[team_key].get(key, [])
                # Convert metal spots to build % bonus
                if key == "metal_spots":
                    bonus_pct = METAL_EXTRACTOR_SPAWN_BONUS * 100  # 8
                    data = [v * bonus_pct for v in data]
                color_idx = tid - 1
                color = GRAPH_LINE_COLORS[color_idx % len(GRAPH_LINE_COLORS)]
                label = self._team_names.get(tid, f"Team {tid}")

                if key == "apm":
                    # Plot rolling-average and instantaneous APM as two lines.
                    inst_data = teams_data[team_key].get("apm_inst", [])
                    series.append((data, color, f"{label} avg"))
                    series.append((inst_data, _lighten_color(color, 0.5),
                                   f"{label} now"))
                else:
                    series.append((data, color, label))

        timestamps = self._stats_data.get("timestamps", [])
        x_labels = []
        for ts in timestamps:
            secs = ts / 60.0
            m, s = divmod(int(secs), 60)
            x_labels.append(f"{m}:{s:02d}")
        tab_dict = dict(self._stat_tabs.options)
        self._stat_graph.title = tab_dict.get(key, key)

        # Per-tab formatting
        self._stat_graph.y_suffix = "%" if key == "metal_spots" else ""
        self._stat_graph.value_format = "{:.2f}" if key == "step_ms" else None
        self._stat_graph.y_tick_step = 8.0 if key == "metal_spots" else None
        self._stat_graph.y_integer_ticks = key in (
            "army_count", "units_killed", "apm", "damage_dealt", "healing_done"
        )
        # CC health is hard-capped at CC_HP, so anchor the y-axis there.
        self._stat_graph.y_max_fixed = float(CC_HP) if key == "cc_health" else None

        self._stat_graph.set_series(series, x_labels, timestamps=timestamps)

    def _is_build_tab(self) -> bool:
        return self._stats_data is not None and self._stat_tabs.value == "build_order"

    def _is_apm_tab(self) -> bool:
        return self._stats_data is not None and self._stat_tabs.value == "apm"

    def _capture_current_snapshot(self):
        """Store the reader's current entity state as a lookup dict."""
        entities, lasers = self._reader.get_state()
        self._cur_entities = {e["id"]: dict(e) for e in entities}
        self._cur_lasers = lasers

    def _advance_frame(self) -> bool:
        """Advance one replay frame, shifting cur -> prev for interpolation."""
        self._prev_entities = dict(self._cur_entities)
        if not self._reader.advance():
            return False
        self._capture_current_snapshot()
        self._spawn_death_bursts_from_reader()
        return True

    def _spawn_death_bursts_from_reader(self) -> None:
        """Spawn DeathBurst particles for any deaths recorded in the current frame."""
        events = self._reader.get_deaths()
        if events:
            DeathBurst.extend_from_events(self._death_bursts, events)

    def _get_interpolated_entities(self) -> list[dict]:
        """Return entities with positions blended between prev and cur frames."""
        t = self._lerp_t
        result: list[dict] = []
        for eid, cur in self._cur_entities.items():
            prev = self._prev_entities.get(eid)
            if prev is not None and prev.get("t") == cur.get("t") and t < 1.0:
                result.append(_lerp_entity(prev, cur, t))
            else:
                result.append(cur)
        return result

    def _restart(self):
        """Restart replay from the beginning after it ended."""
        self._reader.seek_to_frame(0)
        self._capture_current_snapshot()
        self._prev_entities = dict(self._cur_entities)
        self._death_bursts.clear()
        self._lerp_t = 1.0
        self._ended = False
        self._playing = True
        self._accumulator = 0.0
        self._scrubber.value = 0
        self._play_btn.label = "||"
        self._play_btn.icon = "pause"

    def _toggle_play(self):
        if self._ended:
            self._restart()
            return
        self._playing = not self._playing
        if self._playing:
            self._play_btn.label = "||"
            self._play_btn.icon = "pause"
        else:
            self._play_btn.label = ">"
            self._play_btn.icon = "play"

    def run(self) -> ScreenResult:
        from systems import music
        while True:
            dt = self.clock.tick(60) / 1000.0
            music.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")

                # Score Screen overlay mode (full-screen)
                if self._show_score_screen:
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self._show_score_screen = False
                        continue
                    if self._stat_close_btn.handle_event(event):
                        self._show_score_screen = False
                        continue
                    if self._stat_debug_btn.handle_event(event):
                        return ScreenResult("replay_debug", data={
                            "filepath": self._filepath,
                            "stats": self._stats_data,
                        })
                    if self._stat_tabs.handle_event(event):
                        self._build_scroll = 0
                        self._update_stat_graph()
                        continue
                    if self._is_apm_tab() and self._apm_ai_btn.handle_event(event):
                        self._apm_hide_ai = not self._apm_hide_ai
                        self._apm_ai_btn.label = (
                            "Show AI" if self._apm_hide_ai else "Hide AI"
                        )
                        self._update_stat_graph()
                        continue
                    if self._is_build_tab():
                        if event.type == pygame.MOUSEWHEEL:
                            self._build_scroll -= event.y * 18
                            self._build_scroll = max(0, self._build_scroll)
                    else:
                        self._stat_graph.handle_event(event)
                    continue

                # Stats HUD arrow events (mode 2 = single stat)
                if self._stat_mode == 2:
                    if self._handle_stat_dropdown_event(event):
                        continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return ScreenResult("replays")
                    if event.key == pygame.K_SPACE:
                        self._toggle_play()

                if self._back_btn.handle_event(event):
                    return ScreenResult("replays")

                if self._inline_stats_btn.handle_event(event):
                    # Cycle: 0→1→2→0
                    self._stat_mode = (self._stat_mode + 1) % 3
                    _STAT_LABELS = ["Show Stats", "Show One Stat", "Hide Stats"]
                    self._inline_stats_btn.label = _STAT_LABELS[self._stat_mode]
                    continue

                if self._score_screen_btn.handle_event(event):
                    self._show_score_screen = True
                    self._score_anim_start = pygame.time.get_ticks()
                    continue

                if self._team_view_btn.handle_event(event):
                    n_opts = len(self._team_view_options)
                    self._team_view = (self._team_view + 1) % n_opts
                    tid, label = self._team_view_options[self._team_view]
                    self._team_view_btn.label = label
                    self._selected_ids.clear()
                    continue

                if self._play_btn.handle_event(event):
                    self._toggle_play()

                if self._speed_btn.handle_event(event):
                    self._speed_idx = (self._speed_idx + 1) % len(_SPEEDS)
                    self._speed_btn.label = f"{_SPEEDS[self._speed_idx]}x"

                if (event.type == pygame.MOUSEBUTTONUP and event.button == 3
                        and self._speed_btn.rect.collidepoint(event.pos)):
                    self._speed_idx = (self._speed_idx - 1) % len(_SPEEDS)
                    self._speed_btn.label = f"{_SPEEDS[self._speed_idx]}x"

                if self._scrubber.handle_event(event):
                    self._reader.seek_to_frame(self._scrubber.value)
                    self._capture_current_snapshot()
                    self._prev_entities = dict(self._cur_entities)
                    self._death_bursts.clear()
                    self._lerp_t = 1.0
                    # If we were at end, scrubbing resets that
                    if self._ended:
                        self._ended = False
                        self._play_btn.label = ">"
                        self._play_btn.icon = "play"

                # Zoom/pan in game area
                game_rect = self._game_area

                if event.type == pygame.MOUSEWHEEL:
                    mx, my = pygame.mouse.get_pos()
                    if game_rect.collidepoint(mx, my):
                        vx = mx - game_rect.x
                        vy = my - game_rect.y
                        if event.y > 0:
                            self._camera.zoom_at(vx, vy, CAMERA_ZOOM_STEP)
                        elif event.y < 0:
                            self._camera.zoom_at(vx, vy, 1.0 / CAMERA_ZOOM_STEP)

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
                    if game_rect.collidepoint(event.pos):
                        self._mid_dragging = True
                        self._mid_last = event.pos
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
                    self._mid_dragging = False
                elif event.type == pygame.MOUSEMOTION and self._mid_dragging:
                    dx = event.pos[0] - self._mid_last[0]
                    dy = event.pos[1] - self._mid_last[1]
                    self._camera.pan(dx, dy)
                    self._mid_last = event.pos

                # Selection input handling (only in game area)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Minimap click → recenter camera (handled before drag)
                    if self._hud_rect.collidepoint(event.pos):
                        minimap_world = gui.handle_minimap_click(
                            event.pos[0], event.pos[1],
                            self.width, self._hud_screen_h, self._hud_h,
                            self._reader.map_width, self._reader.map_height,
                        )
                        if minimap_world is not None:
                            self._camera.center_on(*minimap_world)
                        continue
                    if game_rect.collidepoint(event.pos):
                        self._dragging = True
                        self._drag_start = event.pos  # screen space for threshold
                        self._drag_end = event.pos

                elif event.type == pygame.MOUSEMOTION and self._dragging:
                    self._drag_end = event.pos

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._dragging:
                    self._dragging = False
                    mx, my = event.pos
                    sx, sy = self._drag_start
                    drag_r = math.hypot(mx - sx, my - sy)
                    additive = pygame.key.get_mods() & pygame.KMOD_SHIFT
                    entities = self._get_interpolated_entities()

                    if drag_r < 5:
                        # Click or double-click — world coords
                        wx, wy = self._screen_to_world(event.pos)
                        now = pygame.time.get_ticks()
                        lx, ly = self._last_click_pos
                        if (now - self._last_click_time < 400
                                and math.hypot(mx - lx, my - ly) < 10):
                            self._select_all_of_type(entities, wx, wy)
                        else:
                            self._click_select(entities, wx, wy, additive)
                        self._last_click_time = now
                        self._last_click_pos = (mx, my)  # screen space for distance
                    else:
                        # Box select — convert both endpoints to world
                        w_sx, w_sy = self._screen_to_world(self._drag_start)
                        w_ex, w_ey = self._screen_to_world(event.pos)
                        self._box_select(entities, w_sx, w_sy,
                                         w_ex, w_ey, additive)

            if self._show_score_screen:
                self._draw_stats_overlay()
                continue

            # Advance frames with sub-frame accumulator for interpolation
            if self._playing:
                speed = _SPEEDS[self._speed_idx]
                self._accumulator += dt * speed
                while self._accumulator >= self._frame_dt:
                    self._accumulator -= self._frame_dt
                    if not self._advance_frame():
                        self._playing = False
                        self._ended = True
                        self._play_btn.label = "R"
                        self._play_btn.icon = "refresh"
                        self._accumulator = 0.0
                        break
                self._lerp_t = min(1.0, self._accumulator / self._frame_dt)
                self._scrubber.value = self._reader.current_index

            # Update death-burst particles every render frame, scaled by speed
            if self._death_bursts:
                burst_dt = dt * _SPEEDS[self._speed_idx] if self._playing else dt
                self._death_bursts = [b for b in self._death_bursts
                                      if b.update(burst_dt)]

            self._draw()

    def _draw(self):
        mw = self._reader.map_width
        mh = self._reader.map_height
        ws = self._world_surface

        # Tiled space background
        ws.blit(self._bg_surface, (0, 0))

        # Draw obstacles (static) — no gy offset on world surface
        for obs in self._reader.obstacles:
            c = tuple(obs.get("c", [120, 120, 120]))
            if obs["shape"] == "rect":
                x, y, w, h = obs["x"], obs["y"], obs["w"], obs["h"]
                pygame.draw.rect(ws, c, (x, y, w, h))
                pygame.draw.rect(ws, OBSTACLE_OUTLINE, (x, y, w, h), 1)
            elif obs["shape"] == "circle":
                cx, cy, r = int(obs["x"]), int(obs["y"]), int(obs["r"])
                pygame.draw.circle(ws, c, (cx, cy), r)
                pygame.draw.circle(ws, OBSTACLE_OUTLINE, (cx, cy), r, 1)

        entities = self._get_interpolated_entities()

        # Draw entities sorted by type for correct layering
        order = {"MS": 0, "ME": 1, "CC": 2, "U": 3}
        entities.sort(key=lambda e: order.get(e.get("t", ""), 4))

        for ent in entities:
            t = ent.get("t")
            if t == "MS":
                self._draw_metal_spot(ent)
            elif t == "ME":
                self._draw_metal_extractor(ent)
            elif t == "CC":
                self._draw_command_center(ent)
            elif t == "U":
                self._draw_unit(ent)

        # FOV arcs and selection rings (drawn on top of entities)
        for ent in entities:
            t = ent.get("t")
            if t in ("U", "CC", "ME"):
                self._draw_fov_arc(ent)
                eid = ent.get("id")
                if eid in self._selected_ids:
                    ex = ent.get("x", 0)
                    ey = ent.get("y", 0)
                    r = CC_RADIUS + 2 if t == "CC" else ent.get("r", 5) + 2
                    pygame.draw.circle(ws, SELECTED_COLOR,
                                       (int(ex), int(ey)), int(r), 1)

        # Draw laser flashes
        for lf in self._cur_lasers:
            self._draw_laser(lf)

        # Death-burst particles
        if self._death_bursts:
            self._anim_surface.fill((0, 0, 0, 0))
            for b in self._death_bursts:
                b.draw(self._anim_surface)
            ws.blit(self._anim_surface, (0, 0))

        # Team name labels above command centers
        self._draw_team_labels(entities)

        # Drag selection rectangle (in world space) — matches the live game's
        # box select rather than the older circle select.
        if self._dragging:
            sx, sy = self._drag_start
            ex, ey = self._drag_end
            screen_dist = math.hypot(ex - sx, ey - sy)
            if screen_dist >= 5:
                w_sx, w_sy = self._screen_to_world(self._drag_start)
                w_ex, w_ey = self._screen_to_world(self._drag_end)
                rx = min(w_sx, w_ex)
                ry = min(w_sy, w_ey)
                rw = abs(w_ex - w_sx)
                rh = abs(w_ey - w_sy)
                rect = pygame.Rect(int(rx), int(ry), int(rw), int(rh))
                self._selection_surface.fill((0, 0, 0, 0))
                pygame.draw.rect(self._selection_surface,
                                 SELECTION_FILL_COLOR, rect)
                pygame.draw.rect(self._selection_surface,
                                 SELECTION_RECT_COLOR, rect, 1)
                ws.blit(self._selection_surface, (0, 0))

        # Fog of war
        self._draw_fog(entities)

        # Composite to screen
        ga = self._game_area
        sw = self.width
        sh = self.height
        bot_y = sh - BOTTOM_BAR_HEIGHT

        self.screen.fill((0, 0, 0))

        # Top bar
        self.screen.fill((20, 20, 30), (0, 0, sw, TOP_BAR_HEIGHT))
        pygame.draw.line(self.screen, (40, 40, 55), (0, TOP_BAR_HEIGHT - 1),
                         (sw, TOP_BAR_HEIGHT - 1))

        # Game area: tiled background (covers beyond-map dead space) then camera projection
        from core.background import blit_screen_background
        blit_screen_background(self.screen, ga, self._camera, self._bg_tile)
        self._camera.apply(ws, self.screen, dest=(ga.x, ga.y))

        # In-game HUD (minimap / display / portrait / actions) — always
        # visible so the minimap is available, and selection details show
        # whenever entities are picked.
        self.screen.fill((20, 20, 30), self._hud_rect)
        pygame.draw.line(self.screen, (40, 40, 55),
                         (0, self._hud_rect.top),
                         (sw, self._hud_rect.top))
        proxies = wrap_entities(entities, self._selected_ids)
        gui.draw_hud(
            self.screen, proxies,
            sw, self._hud_screen_h, self._hud_h,
            enable_t2=self._reader.config.get("enable_t2", False),
            t2_upgrades=None,
            t2_researching=None,
            camera=self._camera,
            world_w=self._reader.map_width,
            world_h=self._reader.map_height,
            obstacles=self._reader.obstacles,
        )

        # Bottom bar
        self.screen.fill((20, 20, 30), (0, bot_y, sw, BOTTOM_BAR_HEIGHT))
        pygame.draw.line(self.screen, (40, 40, 55), (0, bot_y),
                         (sw, bot_y))

        # Top bar buttons
        self._back_btn.draw(self.screen)
        self._team_view_btn.draw(self.screen)
        self._score_screen_btn.draw(self.screen)
        self._inline_stats_btn.draw(self.screen)

        # Bottom bar controls
        self._play_btn.draw(self.screen)
        self._scrubber.draw(self.screen)
        self._speed_btn.draw(self.screen)

        # Time display MM:SS in bottom bar (right-aligned, inline with slider label)
        font = _get_font(14)
        record_interval = self._reader._data.get("record_interval", 6)
        cur_s = self._reader.current_index * record_interval / 60.0
        total_s = self._reader.duration_seconds
        cm, cs = divmod(int(cur_s), 60)
        tm, ts = divmod(int(total_s), 60)
        time_str = f"{cm}:{cs:02d} / {tm}:{ts:02d}"
        time_surf = font.render(time_str, True, (180, 180, 200))
        # Position: same y as the scrubber label, left of the speed button
        time_x = self._speed_btn.rect.x - time_surf.get_width() - 10
        time_y = self._scrubber.y + 2
        self.screen.blit(time_surf, (time_x, time_y))

        # Stats HUD (always on top)
        if self._stat_mode > 0:
            self._draw_stat_dropdown()

        pygame.display.flip()

    # -- inline stats dropdown -------------------------------------------------

    def _get_stat_index(self) -> int:
        """Return the stats time-series index matching the current replay tick."""
        if not self._stats_data:
            return 0
        timestamps = self._stats_data.get("timestamps", [])
        if not timestamps:
            return 0
        cur_tick = self._reader.current_tick
        # Find the last timestamp <= current tick (bisect right - 1)
        idx = 0
        for i, ts in enumerate(timestamps):
            if ts <= cur_tick:
                idx = i
            else:
                break
        return idx

    def _get_latest_stat_values(self, key: str) -> dict[int, float]:
        """Get the time-series value for a stat key at the current replay time.

        Returns a dict mapping team_id -> value for all teams in the data.
        """
        if not self._stats_data:
            return {}
        idx = self._get_stat_index()
        teams = self._stats_data.get("teams", {})
        result: dict[int, float] = {}
        for team_key in sorted(teams.keys(), key=lambda k: int(k)):
            tid = int(team_key)
            data_list = teams[team_key].get(key, [])
            val = data_list[idx] if idx < len(data_list) else (data_list[-1] if data_list else 0.0)
            result[tid] = float(val)
        return result

    def _handle_stat_dropdown_event(self, event: pygame.event.Event) -> bool:
        """Handle arrow button events for single-stat mode (mode 2)."""
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            pos = event.pos
            if self._dd_left_btn.rect.collidepoint(pos):
                self._stat_dropdown_idx = (self._stat_dropdown_idx - 1) % len(_DROPDOWN_STATS)
                return True
            if self._dd_right_btn.rect.collidepoint(pos):
                self._stat_dropdown_idx = (self._stat_dropdown_idx + 1) % len(_DROPDOWN_STATS)
                return True
        return False

    def _draw_comparison_bar(self, x: int, y: int, w: int, h: int,
                             values: dict[int, float]):
        """Draw a horizontal bar split proportionally among N teams."""
        total = sum(values.values())
        if total <= 0:
            pygame.draw.rect(self.screen, (60, 60, 70), (x, y, w, h),
                             border_radius=2)
        else:
            cx = x
            sorted_tids = sorted(values.keys())
            for i, tid in enumerate(sorted_tids):
                frac = values[tid] / total
                is_last = (i == len(sorted_tids) - 1)
                seg_w = (w - (cx - x)) if is_last else max(1, int(w * frac))
                if seg_w > 0:
                    color_idx = tid - 1
                    color = GRAPH_LINE_COLORS[color_idx % len(GRAPH_LINE_COLORS)]
                    pygame.draw.rect(self.screen, color,
                                     (cx, y, seg_w, h), border_radius=2)
                cx += seg_w

    def _draw_stat_text(self, text: str, font, color: tuple, x: int, y: int):
        """Draw text with a dark shadow for readability against the game."""
        shadow = font.render(text, True, (0, 0, 0))
        self.screen.blit(shadow, (x + 1, y + 1))
        surf = font.render(text, True, color)
        self.screen.blit(surf, (x, y))

    def _draw_stat_dropdown(self):
        """Draw the transparent stats HUD overlay."""
        btn = self._inline_stats_btn.rect
        px = btn.x - 110  # panel left edge
        py = btn.bottom + 6
        pw = 200

        font = _get_font(14)
        val_font = _get_font(13)

        def _fmt_stat(key, v):
            if key == "metal_spots":
                return f"{int(v * METAL_EXTRACTOR_SPAWN_BONUS * 100)}%"
            return str(int(v))

        if self._stat_mode == 1:
            # Show all stats stacked (no background)
            row_h = 22
            for i, (key, label) in enumerate(_DROPDOWN_STATS):
                ry = py + i * row_h
                values = self._get_latest_stat_values(key)

                self._draw_stat_text(label, font, (180, 180, 200), px + 6, ry + 2)

                bar_x = px + 70
                bar_w = pw - 76
                self._draw_comparison_bar(bar_x, ry + 3, bar_w, 8, values)

                # Draw per-team value labels below the bar
                sorted_tids = sorted(values.keys())
                n_teams = len(sorted_tids)
                for j, tid in enumerate(sorted_tids):
                    v_str = _fmt_stat(key, values[tid])
                    color_idx = tid - 1
                    color = GRAPH_LINE_COLORS[color_idx % len(GRAPH_LINE_COLORS)]
                    if n_teams <= 2:
                        # Classic layout: first left-aligned, last right-aligned
                        if j == 0:
                            self._draw_stat_text(v_str, val_font, color,
                                                 bar_x, ry + 12)
                        else:
                            vs = val_font.render(v_str, True, color)
                            self._draw_stat_text(v_str, val_font, color,
                                                 bar_x + bar_w - vs.get_width(), ry + 12)
                    else:
                        # Evenly spaced for 3+ teams
                        seg = bar_w // n_teams
                        self._draw_stat_text(v_str, val_font, color,
                                             bar_x + j * seg, ry + 12)

        elif self._stat_mode == 2:
            # Single-stat view with arrows (no background)
            key, label = _DROPDOWN_STATS[self._stat_dropdown_idx]
            values = self._get_latest_stat_values(key)

            lbl = font.render(label, True, (200, 200, 220))
            lbl_x = px + pw // 2 - lbl.get_width() // 2
            self._draw_stat_text(label, font, (200, 200, 220), lbl_x, py + 5)

            bar_x = px + 28
            bar_w = pw - 56
            bar_y = py + 24
            self._draw_comparison_bar(bar_x, bar_y, bar_w, 10, values)

            # Draw per-team value labels below the bar
            sorted_tids = sorted(values.keys())
            n_teams = len(sorted_tids)
            for j, tid in enumerate(sorted_tids):
                v_str = _fmt_stat(key, values[tid])
                color_idx = tid - 1
                color = GRAPH_LINE_COLORS[color_idx % len(GRAPH_LINE_COLORS)]
                if n_teams <= 2:
                    if j == 0:
                        self._draw_stat_text(v_str, val_font, color,
                                             bar_x, bar_y + 14)
                    else:
                        vs = val_font.render(v_str, True, color)
                        self._draw_stat_text(v_str, val_font, color,
                                             bar_x + bar_w - vs.get_width(), bar_y + 14)
                else:
                    seg = bar_w // n_teams
                    self._draw_stat_text(v_str, val_font, color,
                                         bar_x + j * seg, bar_y + 14)

            # Arrow buttons on sides
            self._dd_left_btn.rect.topleft = (px + 4, py + 24)
            self._dd_right_btn.rect.topleft = (px + pw - 26, py + 24)
            self._dd_left_btn.draw(self.screen)
            self._dd_right_btn.draw(self.screen)

    def _draw_stats_overlay(self):
        """Draw the Score Screen overlay (full screen replacement)."""
        mw = self.width
        total_h = self.height
        self.screen.fill(MENU_BG, (0, 0, mw, total_h))

        # Header
        font = _get_font(STATS_HEADER_FONT_SIZE)
        winner = self._reader.winner
        if winner > 0:
            winner_name = self._team_names.get(winner, f"Team {winner}")
            title = f"{winner_name} Victory"
        else:
            title = "Draw"
        title_surf = font.render(title, True, (220, 220, 240))
        self.screen.blit(title_surf, (mw // 2 - title_surf.get_width() // 2, 8))

        # Game length top-right
        dur = self._reader.duration_seconds
        m, s = divmod(int(dur), 60)
        dur_str = f"Game Length: {m}:{s:02d}"
        sub_font = _get_font(STATS_SUB_FONT_SIZE)
        dur_surf = sub_font.render(dur_str, True, (160, 160, 180))
        self.screen.blit(dur_surf, (mw - dur_surf.get_width() - 15, 15))

        # Animated score bars — N-team proportional
        if self._stats_data and "final" in self._stats_data:
            final = self._stats_data["final"]

            # Collect scores for all teams
            team_scores: list[tuple[int, int]] = []  # (team_id, score)
            for team_key in sorted(final.keys(), key=lambda k: int(k)):
                tid = int(team_key)
                score = final[team_key].get("score", 0)
                team_scores.append((tid, score))

            total_score = sum(s for _, s in team_scores)
            elapsed = pygame.time.get_ticks() - self._score_anim_start
            progress = _ease_out_cubic(min(1.0, elapsed / _ANIM_MS))

            bar_y = 38
            n_teams = len(team_scores)
            bar_area = mw - _BAR_PAD_X * 2 - _BAR_GAP * max(0, n_teams - 1)
            score_font = _get_font(SCORE_FONT_SIZE)

            bx = _BAR_PAD_X
            for i, (tid, score) in enumerate(team_scores):
                frac = score / total_score if total_score > 0 else 1.0 / max(n_teams, 1)
                seg_w = int(bar_area * frac * progress)

                color_idx = tid - 1
                bar_color = SCORE_TEAM_COLORS[color_idx % len(SCORE_TEAM_COLORS)]
                border_color = tuple(min(c + 30, 255) for c in bar_color[:3])

                r = pygame.Rect(bx, bar_y, seg_w, _BAR_HEIGHT)
                _draw_3d_bar(self.screen, r, bar_color, border_color)

                team_name = self._team_names.get(tid, f"Team {tid}")
                s_surf = score_font.render(f"{team_name}: {score:,}", True, (255, 255, 255))
                s_y = bar_y + (_BAR_HEIGHT - s_surf.get_height()) // 2
                if progress > 0.05 and seg_w > 10:
                    self.screen.blit(s_surf, (bx + 10, s_y))

                bx += seg_w + _BAR_GAP

        self._stat_tabs.draw(self.screen)

        if self._is_build_tab():
            self._draw_build_order_tab()
        else:
            self._stat_graph.draw(self.screen)
            if self._is_apm_tab():
                self._apm_ai_btn.draw(self.screen)

        self._stat_close_btn.draw(self.screen)
        self._stat_debug_btn.draw(self.screen)
        pygame.display.flip()

    def _draw_build_order_tab(self):
        """Draw multi-column scrollable build order within the graph area.

        One column per player (new replays) or one per team (old replays that
        lack player_id in build order entries).  Two-level compression applies.
        """
        area = self._stat_graph.rect
        ax, ay, aw, ah = area.x, area.y, area.w, area.h

        pygame.draw.rect(self.screen, (20, 20, 32), area, border_radius=4)
        pygame.draw.rect(self.screen, (40, 40, 55), area, 1, border_radius=4)

        if not self._stats_data or "final" not in self._stats_data:
            return

        final = self._stats_data["final"]

        # Group raw entries by player_id when available, else by team_id
        player_raw: dict[int, list[dict]] = {}
        has_player_ids = False
        for team_key in sorted(final.keys(), key=lambda k: int(k)):
            team_id = int(team_key)
            for entry in final.get(team_key, {}).get("build_order", []):
                if not isinstance(entry, dict):
                    continue
                if "player_id" in entry:
                    has_player_ids = True
                key = entry["player_id"] if "player_id" in entry else team_id
                player_raw.setdefault(key, []).append(entry)

        columns: list[tuple[str, list[dict], tuple]] = []
        for pid in sorted(player_raw):
            bo = _compress_build_order(player_raw[pid])
            color = _RES_PLAYER_COLORS[(pid - 1) % len(_RES_PLAYER_COLORS)]
            if has_player_ids and self._player_names:
                header = self._player_names.get(pid, f"P{pid}")
            else:
                header = self._team_names.get(pid, f"Team {pid}")
            columns.append((header, bo, color))

        n_cols = max(2, len(columns))
        col_w = aw // n_cols
        font = _get_font(14)
        row_h = 18
        r = BUILD_ORDER_RADIUS
        pad_x = 12
        pad_y = 8

        clip_rect = pygame.Rect(ax, ay, aw, ah)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        hdr_y = ay + pad_y - self._build_scroll
        hdr_font = _get_font(16)

        for ci, (col_name, bo, color) in enumerate(columns):
            col_x = ax + ci * col_w
            hdr_surf = hdr_font.render(col_name, True, color)
            self.screen.blit(hdr_surf, (col_x + pad_x, hdr_y))

            start_y = hdr_y + row_h + 4
            for i, entry in enumerate(bo):
                ey = start_y + i * row_h
                if ey + row_h < ay or ey > ay + ah:
                    continue
                ecx = col_x + pad_x + r
                ecy = ey + row_h // 2
                pygame.draw.circle(self.screen, color, (ecx, ecy), r)
                name_surf = font.render(_build_order_label(entry), True, (200, 200, 220))
                self.screen.blit(name_surf, (ecx + r + 6, ecy - name_surf.get_height() // 2))

        max_rows = max((len(bo) for _, bo, _ in columns), default=0)
        max_scroll = max(0, (max_rows * row_h + pad_y + row_h + 4) - ah)
        self._build_scroll = min(self._build_scroll, max_scroll)

        self.screen.set_clip(old_clip)

    # -- selection system ---------------------------------------------------

    def _is_selectable(self, ent: dict) -> bool:
        """Check if an entity is selectable in the current team view mode."""
        t = ent.get("t")
        if t not in ("U", "CC", "ME"):
            return False
        if self._team_view == 0:
            return True
        viewed_tid = self._team_view_options[self._team_view][0]
        return ent.get("tm") == viewed_tid

    def _click_select(self, entities: list[dict], mx: float, my: float,
                      additive: bool):
        """Select the closest selectable entity under cursor."""
        best_id: int | None = None
        best_dist = float("inf")
        for ent in entities:
            if not self._is_selectable(ent):
                continue
            ex, ey = ent.get("x", 0), ent.get("y", 0)
            t = ent.get("t")
            r = CC_RADIUS if t == "CC" else ent.get("r", 5)
            d = math.hypot(ex - mx, ey - my)
            if d <= r and d < best_dist:
                best_dist = d
                best_id = ent.get("id")
        if not additive:
            self._selected_ids.clear()
        if best_id is not None:
            self._selected_ids.add(best_id)

    def _box_select(self, entities: list[dict],
                    wx1: float, wy1: float,
                    wx2: float, wy2: float, additive: bool):
        """Select all selectable entities inside a drag rectangle.

        Army units take priority over buildings — if any units are inside the
        box only those get selected, otherwise the buildings inside the box
        (e.g. a CC) get selected. Mirrors client_game.py's rectangle select.
        """
        if not additive:
            self._selected_ids.clear()
        rx = min(wx1, wx2)
        ry = min(wy1, wy2)
        rw = abs(wx2 - wx1)
        rh = abs(wy2 - wy1)
        rcx, rcy = rx + rw / 2.0, ry + rh / 2.0
        hw, hh = rw / 2.0, rh / 2.0

        army_ids: list[int] = []
        building_ids: list[int] = []
        for ent in entities:
            if not self._is_selectable(ent):
                continue
            ex, ey = ent.get("x", 0), ent.get("y", 0)
            t = ent.get("t")
            er = CC_RADIUS if t == "CC" else ent.get("r", 5)
            if abs(ex - rcx) <= hw + er and abs(ey - rcy) <= hh + er:
                eid = ent.get("id")
                if eid is None:
                    continue
                if t == "U":
                    army_ids.append(eid)
                else:
                    building_ids.append(eid)
        targets = army_ids if army_ids else building_ids
        self._selected_ids.update(targets)

    def _select_all_of_type(self, entities: list[dict], mx: float, my: float):
        """Double-click: select all selectable units of the same type under cursor."""
        best: dict | None = None
        best_dist = float("inf")
        for ent in entities:
            if ent.get("t") != "U" or not self._is_selectable(ent):
                continue
            ex, ey = ent.get("x", 0), ent.get("y", 0)
            r = ent.get("r", 5)
            d = math.hypot(ex - mx, ey - my)
            if d <= r and d < best_dist:
                best_dist = d
                best = ent
        if best is None:
            return
        self._selected_ids.clear()
        target_type = best.get("ut")
        target_team = best.get("tm")
        for ent in entities:
            if (ent.get("t") == "U" and self._is_selectable(ent)
                    and ent.get("ut") == target_type
                    and ent.get("tm") == target_team):
                self._selected_ids.add(ent.get("id"))

    # -- FOV arc drawing ----------------------------------------------------

    def _draw_fov_arc(self, ent: dict):
        """Draw FOV arc for a unit/CC/ME, mirroring Unit._draw_fov_arc."""
        t = ent.get("t")
        ut = ent.get("ut", "soldier")
        eid = ent.get("id")
        stats = UNIT_TYPES.get(ut, {})
        fov_deg = stats.get("fov", 90)
        fov = math.radians(fov_deg)

        # Visibility rules: selected → show; non-selectable (enemy) → show;
        # selectable but not selected (ally) → hide
        is_selected = eid in self._selected_ids
        is_selectable = self._is_selectable(ent)
        if not is_selected and is_selectable:
            return

        ws = self._world_surface
        ex = ent.get("x", 0)
        ey = ent.get("y", 0)
        tm = ent.get("tm", 1)

        # CC: show attack range
        if t == "CC":
            atk_r = int(CC_LASER_RANGE)
            temp2 = pygame.Surface((atk_r * 2, atk_r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp2, RANGE_COLOR, (atk_r, atk_r), atk_r, 1)
            ws.blit(temp2, (int(ex) - atk_r, int(ey) - atk_r))
            return

        # ME: only Outpost has a range circle
        if t == "ME":
            if ent.get("us") == "outpost":
                from config.settings import OUTPOST_LASER_RANGE
                atk_r = int(OUTPOST_LASER_RANGE)
                temp = pygame.Surface((atk_r * 2, atk_r * 2), pygame.SRCALPHA)
                pygame.draw.circle(temp, RANGE_COLOR, (atk_r, atk_r), atk_r, 1)
                ws.blit(temp, (int(ex) - atk_r, int(ey) - atk_r))
            return

        # Unit: draw FOV arc
        weapon = stats.get("weapon")
        if not weapon:
            return
        r = int(weapon.get("range", 50))
        if r <= 0:
            return
        is_healer = weapon.get("hits_only_friendly", False)
        if ent.get("hf"):
            color = (120, 120, 120)  # grey for hold fire
        elif is_healer:
            color = MEDIC_HEAL_COLOR
        else:
            color = RANGE_COLOR
        fa = ent.get("fa", 0.0)

        half_fov = fov / 2.0
        if fov >= math.tau - 0.01:
            temp = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp, color, (r, r), r, 1)
            ws.blit(temp, (int(ex) - r, int(ey) - r))
            return

        # Polygon arc: center -> arc points -> center
        start = fa - half_fov
        steps = max(int(math.degrees(fov) / 3), 8)
        points = [(ex, ey)]
        for i in range(steps + 1):
            a = start + fov * i / steps
            points.append((ex + r * math.cos(a), ey + r * math.sin(a)))
        points.append((ex, ey))

        temp_size = r * 2 + 4
        temp = pygame.Surface((temp_size, temp_size), pygame.SRCALPHA)
        ox = temp_size // 2 - ex
        oy = temp_size // 2 - ey
        shifted = [(px + ox, py + oy) for px, py in points]
        pygame.draw.lines(temp, color, False, shifted, 1)
        ws.blit(temp, (ex - temp_size // 2, ey - temp_size // 2))

    @staticmethod
    def _build_background(width: int, height: int) -> tuple[pygame.Surface, pygame.Surface]:
        from core.background import build_background
        return build_background(width, height)

    # -- fog of war ---------------------------------------------------------

    def _draw_fog(self, entities: list[dict]):
        """Draw fog of war overlay when in team view mode."""
        if self._team_view == 0:
            return

        viewed_tid = self._team_view_options[self._team_view][0]

        FOG_ALPHA = 200
        self._fog_surface.fill((0, 0, 0, FOG_ALPHA))

        # Collect LOS circles from the viewed team's entities
        los_circles: list[tuple[int, int, int]] = []
        for ent in entities:
            t = ent.get("t")
            if t not in ("U", "CC", "ME"):
                continue
            if ent.get("tm") != viewed_tid:
                continue
            ut = ent.get("ut", "soldier")
            stats = UNIT_TYPES.get(ut, {})
            los = int(stats.get("los", 100))
            # Outpost upgrade grants extended vision
            if ut == "metal_extractor" and ent.get("us") == "outpost":
                los = int(OUTPOST_LOS)
            if los <= 0:
                continue
            los_circles.append((int(ent.get("x", 0)), int(ent.get("y", 0)), los))

        # Punch transparent holes for LOS
        for ex, ey, r in los_circles:
            size = r * 2
            cutout = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(cutout, (0, 0, 0, FOG_ALPHA), (r, r), r)
            self._fog_surface.blit(cutout, (ex - r, ey - r),
                                   special_flags=pygame.BLEND_RGBA_SUB)

        ws = self._world_surface
        ws.blit(self._fog_surface, (0, 0))

        # Border at the fog edge
        self._fog_border.fill((0, 0, 0))
        for ex, ey, r in los_circles:
            pygame.draw.circle(self._fog_border, (160, 160, 160), (ex, ey), r)
        for ex, ey, r in los_circles:
            pygame.draw.circle(self._fog_border, (0, 0, 0), (ex, ey), max(r - 1, 0))
        ws.blit(self._fog_border, (0, 0))

    # -- team name labels ---------------------------------------------------

    def _draw_team_labels(self, entities: list[dict]):
        """Draw player/AI name labels above command centers and
        spawn-bonus labels above metal extractors."""
        font = _get_font(20)
        ws = self._world_surface
        for ent in entities:
            t = ent.get("t")
            if t == "CC":
                tm = ent.get("tm", 1)
                name = self._team_names.get(tm, f"Team {tm}")
                bonus_pct = int(ent.get("bp", 0))
                if bonus_pct > 0:
                    name = f"{name} (+{bonus_pct}%)"
                team_color = TEAM_COLORS.get(tm, PLAYER_COLORS[0])
                name_surf = font.render(name, True, team_color)
                nx = int(ent.get("x", 0)) - name_surf.get_width() // 2
                ny = int(ent.get("y", 0)) - 40
                ws.blit(name_surf, (nx, ny))
            elif t == "ME":
                pct = int(ent.get("meb", 0))
                if pct <= 0:
                    continue
                label_surf = font.render(f"+{pct}%", True, (255, 255, 255))
                r = ent.get("r", METAL_EXTRACTOR_RADIUS)
                lx = int(ent.get("x", 0)) - label_surf.get_width() // 2
                ly = int(ent.get("y", 0) - r - HEALTH_BAR_OFFSET - 12)
                ws.blit(label_surf, (lx, ly))

    # -- command line helper ------------------------------------------------

    def _draw_command_line(self, x1: float, y1: float, x2: float, y2: float,
                           color: tuple):
        """Draw a command line from (x1,y1) to (x2,y2) with an arrowhead at the end."""
        ws = self._world_surface
        pygame.draw.line(ws, color, (x1, y1), (x2, y2), 1)
        # Arrowhead
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        # Unit direction vector
        ux, uy = dx / dist, dy / dist
        # Perpendicular
        px, py = -uy, ux
        s = _ARROW_SIZE
        # Arrow tip is at (x2, y2), two wings behind it
        wing1 = (x2 - ux * s + px * s * 0.5, y2 - uy * s + py * s * 0.5)
        wing2 = (x2 - ux * s - px * s * 0.5, y2 - uy * s - py * s * 0.5)
        pygame.draw.polygon(ws, color, [(x2, y2), wing1, wing2])

    # -- entity renderers ---------------------------------------------------
    # All entity positions are offset by self._gy (top bar height)

    def _draw_unit(self, ent: dict):
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        c = tuple(ent.get("c", [255, 255, 255]))
        r = ent.get("r", 5)
        hp = ent.get("hp", 100)
        ut = ent.get("ut", "soldier")

        # Command indicators (shown for selected units)
        eid = ent.get("id")
        if eid in self._selected_ids:
            if "atx" in ent and "aty" in ent:
                atx = ent["atx"]
                aty = ent["aty"]
                self._draw_command_line(x, y, atx, aty, _ATTACK_CMD_COLOR)
            elif "tx" in ent and "ty" in ent:
                tx = ent["tx"]
                ty = ent["ty"]
                if ent.get("am"):
                    color = _ATTACK_CMD_COLOR
                elif ent.get("fm"):
                    color = _FIGHT_CMD_COLOR
                else:
                    color = _MOVE_CMD_COLOR
                self._draw_command_line(x, y, tx, ty, color)

            # Draw queued command waypoints
            if "cq" in ent:
                if "atx" in ent:
                    px, py = ent["atx"], ent["aty"]
                elif "tx" in ent:
                    px, py = ent["tx"], ent["ty"]
                else:
                    px, py = x, y
                for qcmd in ent["cq"]:
                    qx_val = qcmd.get("x")
                    qy_val = qcmd.get("y")
                    if qx_val is None or qy_val is None:
                        continue
                    qt = qcmd.get("t", "move")
                    if qt in ("attack_move", "attack"):
                        qcolor = _ATTACK_CMD_COLOR
                    elif qt == "fight":
                        qcolor = _FIGHT_CMD_COLOR
                    else:
                        qcolor = _MOVE_CMD_COLOR
                    self._draw_command_line(px, py, qx_val, qy_val, qcolor)
                    pygame.draw.circle(ws, qcolor, (int(round(qx_val)), int(round(qy_val))), 3, 1)
                    px, py = qx_val, qy_val

        pygame.draw.circle(ws, c, (x, y), r)

        # Symbol
        stats = UNIT_TYPES.get(ut, {})
        symbol = stats.get("symbol")
        if symbol:
            scale = r / 16.0
            translated = [(x + px * scale, y + py * scale) for px, py in symbol]
            pygame.draw.polygon(ws, (0, 0, 0), translated)
            pygame.draw.polygon(ws, c, translated, 1)

        # Health bar
        max_hp = stats.get("hp", 100)
        if hp < max_hp:
            self._draw_health_bar(x, y, r + HEALTH_BAR_OFFSET, hp, max_hp)

    def _draw_command_center(self, ent: dict):
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        c = tuple(ent.get("c", [255, 255, 255]))
        pts = ent.get("pts", [])
        tm = ent.get("tm", 1)
        hp = ent.get("hp", 1000)

        if pts:
            translated = [(x + px, y + py) for px, py in pts]
            pygame.draw.polygon(ws, c, translated)
            tc = TEAM_COLORS.get(tm, PLAYER_COLORS[0])
            outline = tuple(min(c + 70, 255) for c in tc[:3])
            pygame.draw.polygon(ws, outline, translated, 2)

        if hp < CC_HP:
            self._draw_health_bar(x, y, CC_RADIUS + HEALTH_BAR_OFFSET,
                                  hp, CC_HP, bar_w=40)

    def _draw_metal_spot(self, ent: dict):
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        r = ent.get("r", 5)
        ow = ent.get("ow")
        raw_cp = ent.get("cp", 0.0)

        # Capture range circle with alpha
        cr = int(METAL_SPOT_CAPTURE_RADIUS)
        size = cr * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(temp, METAL_SPOT_CAPTURE_RANGE_COLOR, (cr, cr), cr)
        ws.blit(temp, (int(x) - cr, int(y) - cr))

        # Base dot — color by owner team
        if ow is None:
            color = (255, 200, 60)
        else:
            color = TEAM_COLORS.get(ow, PLAYER_COLORS[0])
        pygame.draw.circle(ws, color, (int(x), int(y)), int(r))

        # Capture progress arcs — one per team with progress
        cp_dict = normalize_cp(raw_cp)
        if ow is None and cp_dict:
            arc_r = METAL_SPOT_CAPTURE_RADIUS + METAL_SPOT_CAPTURE_ARC_WIDTH
            rect = pygame.Rect(int(x - arc_r), int(y - arc_r),
                               int(arc_r * 2), int(arc_r * 2))
            for tid, progress in sorted(cp_dict.items()):
                if progress < 0.01:
                    continue
                progress_color = TEAM_COLORS.get(tid, PLAYER_COLORS[0])
                start_angle = math.pi / 2
                end_angle = start_angle + progress * math.tau
                pygame.draw.arc(ws, progress_color, rect,
                                start_angle, end_angle,
                                int(METAL_SPOT_CAPTURE_ARC_WIDTH))

    def _draw_metal_extractor(self, ent: dict):
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        r = ent.get("r", METAL_EXTRACTOR_RADIUS)
        rot = ent.get("rot", 0.0)
        hp = ent.get("hp", 200)

        # Rotating equilateral triangle
        s = r * math.sqrt(3) / 2
        static_points = [
            complex(0, r),
            complex(-s, -r / 2),
            complex(s, -r / 2),
        ]
        rotated = [p * complex(math.cos(rot), math.sin(rot)) for p in static_points]
        points = [(p.real + x, p.imag + y) for p in rotated]
        pygame.draw.polygon(ws, (0, 0, 0), points, 1)

        if hp < METAL_EXTRACTOR_HP:
            self._draw_health_bar(x, y, r + HEALTH_BAR_OFFSET,
                                  hp, METAL_EXTRACTOR_HP)

    def _draw_laser(self, lf: list):
        if len(lf) < 6:
            return
        ws = self._world_surface
        x1, y1, x2, y2 = lf[0], lf[1], lf[2], lf[3]
        color = tuple(lf[4])
        width = lf[5]
        temp = pygame.Surface(ws.get_size(), pygame.SRCALPHA)
        c = (*color[:3], 200)
        pygame.draw.line(temp, c, (x1, y1), (x2, y2), width)
        ws.blit(temp, (0, 0))

    def _draw_health_bar(self, cx: float, cy: float, offset_y: float,
                         hp: float, max_hp: float,
                         bar_w: float = HEALTH_BAR_WIDTH):
        ws = self._world_surface
        ratio = hp / max_hp if max_hp > 0 else 0
        bx = cx - bar_w / 2
        by = cy - offset_y
        pygame.draw.rect(ws, HEALTH_BAR_BG,
                         (bx, by, bar_w, HEALTH_BAR_HEIGHT))
        fg = HEALTH_BAR_FG if ratio > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(ws, fg,
                         (bx, by, bar_w * ratio, HEALTH_BAR_HEIGHT))
