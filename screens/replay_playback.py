"""Replay playback screen — renders recorded frames with transport controls."""
from __future__ import annotations
import math
import pygame
from screens.base import BaseScreen, ScreenResult
from screens.results import _draw_3d_bar, _ease_out_cubic, _BAR_T1_COLOR, _BAR_T2_COLOR, _BAR_BORDER_T1, _BAR_BORDER_T2, _BAR_HEIGHT, _BAR_PAD_X, _BAR_GAP, _ANIM_MS
from systems.replay import ReplayReader
from config.settings import (
    OBSTACLE_OUTLINE, HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT,
    HEALTH_BAR_BG, HEALTH_BAR_FG, HEALTH_BAR_LOW, HEALTH_BAR_OFFSET,
    LASER_FLASH_DURATION, CC_RADIUS, METAL_SPOT_CAPTURE_RADIUS,
    METAL_SPOT_CAPTURE_RANGE_COLOR, METAL_EXTRACTOR_RADIUS,
    CC_HP, METAL_EXTRACTOR_HP,
    METAL_SPOT_CAPTURE_ARC_WIDTH,
    METAL_SPOT_CAPTURE_ARC_COLOR_T1,
    METAL_SPOT_CAPTURE_ARC_COLOR_T2,
    METAL_EXTRACTOR_SPAWN_BONUS,
    SELECTED_COLOR, SELECTION_FILL_COLOR, SELECTION_RECT_COLOR,
    TEAM1_COLOR, TEAM2_COLOR, RANGE_COLOR, MEDIC_HEAL_COLOR,
    CC_LASER_RANGE, CC_HEAL_RADIUS,
    CC_HEAL_COLOR_T1, CC_HEAL_COLOR_T2,
    CC_HEAL_RING_T1, CC_HEAL_RING_T2,
)
from config.unit_types import UNIT_TYPES
from ui.widgets import Slider, Button, ToggleGroup, LineGraph, _get_font
from ui.theme import (
    MENU_BG, GRAPH_LINE_T1, GRAPH_LINE_T2,
    SCORE_FONT_SIZE, SCORE_T1_COLOR, SCORE_T2_COLOR,
    STATS_HEADER_FONT_SIZE, STATS_SUB_FONT_SIZE,
    BUILD_ORDER_RADIUS,
)

TOP_BAR_HEIGHT = 40
BOTTOM_BAR_HEIGHT = 50
_SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0]

# Command line colors for selected unit action indicators
_MOVE_CMD_COLOR = (0, 140, 40)     # dark green for move commands
_ATTACK_CMD_COLOR = (180, 30, 30)  # dark red for attack commands
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
        self._reader = ReplayReader(filepath)

        # Resolve team names from replay config
        config = self._reader.config
        human_teams = self._reader.human_teams
        ai_names = config.get("team_ai_names", {})
        ai_ids = config.get("team_ai_ids", {})
        player_name = config.get("player_name", "Player")
        self._team_names: dict[int, str] = {}
        for team in [1, 2]:
            if team in human_teams:
                self._team_names[team] = player_name
            else:
                name = ai_names.get(team) or ai_names.get(str(team))
                if not name:
                    name = ai_ids.get(team) or ai_ids.get(str(team))
                    if name:
                        name = name.replace("_", " ").title()
                self._team_names[team] = name or f"Team {team}"
        self._name1 = self._team_names.get(1, "Team 1")
        self._name2 = self._team_names.get(2, "Team 2")

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

        mw = self._reader.map_width
        mh = self._reader.map_height
        total = self._reader.frame_count

        # Y offset for game area (below top bar)
        self._gy = TOP_BAR_HEIGHT
        # Bottom bar top edge
        bot_y = TOP_BAR_HEIGHT + mh

        # ── Top bar: Back (left) → Show Actions, Score Screen, Show Stats (right) ──
        btn_h = 28
        top_cy = (TOP_BAR_HEIGHT - btn_h) // 2  # vertically centered
        self._back_btn = Button(8, top_cy, 55, btn_h, "Back")

        self._stats_data = self._reader.stats_data
        has_stats = self._stats_data is not None
        # Right-aligned buttons (from right edge)
        self._inline_stats_btn = Button(mw - 95, top_cy, 90, btn_h,
                                        "Show Stats", enabled=has_stats)
        self._score_screen_btn = Button(mw - 200, top_cy, 100, btn_h,
                                        "Score Screen", enabled=has_stats)
        self._team_view = 0  # 0=All Teams, 1=Team 1, 2=Team 2
        self._team_view_btn = Button(mw - 300, top_cy, 95, btn_h,
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

        # ── Bottom bar: Play/Pause (left), Scrubber (middle), Speed (right) ──
        self._play_btn = Button(8, bot_y + 12, 45, btn_h, "||",
                                icon="pause")
        scrub_x = 60
        scrub_w = mw - 145
        self._scrubber = Slider(
            scrub_x, bot_y + 10, scrub_w, "Snapshot",
            0, max(total - 1, 1), 0, 1,
        )
        self._speed_btn = Button(mw - 70, bot_y + 12, 65, btn_h,
                                 f"{_SPEEDS[self._speed_idx]}x")

        # Score Screen overlay state
        self._show_score_screen = False
        self._build_scroll: int = 0
        self._score_anim_start: int = 0

        # Stats HUD state: 0=hidden, 1=show all, 2=single stat with arrows
        self._stat_mode = 0
        self._stat_dropdown_idx = 0

        # Score Screen overlay widgets
        if has_stats:
            tab_w = min(90, (mw - 40) // len(_STAT_TABS) - 2)
            tab_x = (mw - len(_STAT_TABS) * (tab_w + 2)) // 2
            self._stat_tabs = ToggleGroup(tab_x, 80, _STAT_TABS,
                                          selected_index=0, btn_w=tab_w, btn_h=28)
            overlay_h = TOP_BAR_HEIGHT + mh + BOTTOM_BAR_HEIGHT
            self._stat_graph = LineGraph(30, 115, mw - 60, overlay_h - 200,
                                         color1=GRAPH_LINE_T1, color2=GRAPH_LINE_T2)
            self._stat_close_btn = Button(mw // 2 - 60, overlay_h - 45, 120, 30, "Close")
            self._update_stat_graph()

        # Arrow buttons for single-stat mode
        self._dd_left_btn = Button(0, 0, 22, 22, "<")
        self._dd_right_btn = Button(0, 0, 22, 22, ">")

    def _update_stat_graph(self):
        if self._stats_data is None:
            return
        key = self._stat_tabs.value
        if key == "build_order":
            return  # build order tab doesn't use graph
        if key == "step_ms":
            t1 = self._stats_data.get("step_ms", [])
            t2 = []
        else:
            t1 = self._stats_data.get("teams", {}).get("1", {}).get(key, [])
            t2 = self._stats_data.get("teams", {}).get("2", {}).get(key, [])

        # Convert metal spots to build % bonus
        if key == "metal_spots":
            bonus_pct = METAL_EXTRACTOR_SPAWN_BONUS * 100  # 8
            t1 = [v * bonus_pct for v in t1]
            t2 = [v * bonus_pct for v in t2]

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
        self._stat_graph.y_integer_ticks = key in ("army_count", "units_killed")

        self._stat_graph.set_data(t1, t2, x_labels, timestamps=timestamps)

    def _is_build_tab(self) -> bool:
        return self._stats_data is not None and self._stat_tabs.value == "build_order"

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
        return True

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
        while True:
            dt = self.clock.tick(60) / 1000.0

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
                    if self._stat_tabs.handle_event(event):
                        self._build_scroll = 0
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
                    self._team_view = (self._team_view + 1) % 3
                    _TV_LABELS = ["All Teams", self._name1, self._name2]
                    self._team_view_btn.label = _TV_LABELS[self._team_view]
                    self._selected_ids.clear()
                    continue

                if self._play_btn.handle_event(event):
                    self._toggle_play()

                if self._speed_btn.handle_event(event):
                    self._speed_idx = (self._speed_idx + 1) % len(_SPEEDS)
                    self._speed_btn.label = f"{_SPEEDS[self._speed_idx]}x"

                if self._scrubber.handle_event(event):
                    self._reader.seek_to_frame(self._scrubber.value)
                    self._capture_current_snapshot()
                    self._prev_entities = dict(self._cur_entities)
                    self._lerp_t = 1.0
                    # If we were at end, scrubbing resets that
                    if self._ended:
                        self._ended = False
                        self._play_btn.label = ">"
                        self._play_btn.icon = "play"

                # Selection input handling (only in game area)
                mw = self._reader.map_width
                mh = self._reader.map_height
                game_rect = pygame.Rect(0, self._gy, mw, mh)

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if game_rect.collidepoint(event.pos):
                        self._dragging = True
                        self._drag_start = event.pos
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
                        # Click or double-click
                        now = pygame.time.get_ticks()
                        lx, ly = self._last_click_pos
                        if (now - self._last_click_time < 400
                                and math.hypot(mx - lx, my - ly) < 10):
                            self._select_all_of_type(entities, mx, my - self._gy)
                        else:
                            self._click_select(entities, mx, my - self._gy, additive)
                        self._last_click_time = now
                        self._last_click_pos = (mx, my)
                    else:
                        # Circle select using center and radius of drag
                        cx = (sx + mx) / 2.0
                        cy = (sy + my) / 2.0 - self._gy
                        sr = drag_r / 2.0
                        self._circle_select(entities, cx, cy, sr, additive)

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

            self._draw()

    def _draw(self):
        mw = self._reader.map_width
        mh = self._reader.map_height
        gy = self._gy  # game area y offset

        # Black game area
        self.screen.fill((0, 0, 0), (0, gy, mw, mh))

        # Clip to game area so entities/health bars don't bleed over bars
        self.screen.set_clip(pygame.Rect(0, gy, mw, mh))

        # Draw obstacles (static) — offset by top bar
        for obs in self._reader.obstacles:
            c = tuple(obs.get("c", [120, 120, 120]))
            if obs["shape"] == "rect":
                x, y, w, h = obs["x"], obs["y"] + gy, obs["w"], obs["h"]
                pygame.draw.rect(self.screen, c, (x, y, w, h))
                pygame.draw.rect(self.screen, OBSTACLE_OUTLINE, (x, y, w, h), 1)
            elif obs["shape"] == "circle":
                cx, cy, r = int(obs["x"]), int(obs["y"]) + gy, int(obs["r"])
                pygame.draw.circle(self.screen, c, (cx, cy), r)
                pygame.draw.circle(self.screen, OBSTACLE_OUTLINE, (cx, cy), r, 1)

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
                    ey = ent.get("y", 0) + gy
                    r = CC_RADIUS + 2 if t == "CC" else ent.get("r", 5) + 2
                    pygame.draw.circle(self.screen, SELECTED_COLOR,
                                       (int(ex), int(ey)), int(r), 1)

        # Draw laser flashes
        for lf in self._cur_lasers:
            self._draw_laser(lf)

        # Team name labels above command centers
        self._draw_team_labels(entities)

        # Drag selection circle
        if self._dragging:
            sx, sy = self._drag_start
            ex, ey = self._drag_end
            cx = (sx + ex) / 2.0
            cy = (sy + ey) / 2.0
            r = math.hypot(ex - sx, ey - sy) / 2.0
            if r >= 5:
                self._selection_surface.fill((0, 0, 0, 0))
                pygame.draw.circle(self._selection_surface, SELECTION_FILL_COLOR,
                                   (int(cx), int(cy - gy)), int(r))
                pygame.draw.circle(self._selection_surface, SELECTION_RECT_COLOR,
                                   (int(cx), int(cy - gy)), int(r), 1)
                self.screen.blit(self._selection_surface, (0, gy))

        # Fog of war
        self._draw_fog(entities)

        # Remove clip
        self.screen.set_clip(None)

        # Re-fill top bar and bottom bar backgrounds (covers any bleed)
        self.screen.fill((20, 20, 30), (0, 0, mw, TOP_BAR_HEIGHT))
        pygame.draw.line(self.screen, (40, 40, 55), (0, TOP_BAR_HEIGHT - 1),
                         (mw, TOP_BAR_HEIGHT - 1))

        self.screen.fill((20, 20, 30), (0, gy + mh, mw, BOTTOM_BAR_HEIGHT))
        pygame.draw.line(self.screen, (40, 40, 55), (0, gy + mh),
                         (mw, gy + mh))

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

    def _get_latest_stat_values(self, key: str) -> tuple[float, float]:
        """Get the time-series value for a stat key at the current replay time."""
        if not self._stats_data:
            return 0.0, 0.0
        idx = self._get_stat_index()
        teams = self._stats_data.get("teams", {})
        t1_list = teams.get("1", {}).get(key, [])
        t2_list = teams.get("2", {}).get(key, [])
        v1 = t1_list[idx] if idx < len(t1_list) else (t1_list[-1] if t1_list else 0.0)
        v2 = t2_list[idx] if idx < len(t2_list) else (t2_list[-1] if t2_list else 0.0)
        return float(v1), float(v2)

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
                             v1: float, v2: float):
        """Draw a horizontal bar split proportionally between T1 and T2."""
        total = v1 + v2
        if total <= 0:
            # Both zero — gray 50/50
            pygame.draw.rect(self.screen, (60, 60, 70), (x, y, w, h),
                             border_radius=2)
        else:
            t1_w = max(1, int(w * v1 / total))
            t2_w = w - t1_w
            if t1_w > 0:
                pygame.draw.rect(self.screen, GRAPH_LINE_T1,
                                 (x, y, t1_w, h), border_radius=2)
            if t2_w > 0:
                pygame.draw.rect(self.screen, GRAPH_LINE_T2,
                                 (x + t1_w, y, t2_w, h), border_radius=2)

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
                v1, v2 = self._get_latest_stat_values(key)

                self._draw_stat_text(label, font, (180, 180, 200), px + 6, ry + 2)

                bar_x = px + 70
                bar_w = pw - 76
                self._draw_comparison_bar(bar_x, ry + 3, bar_w, 8, v1, v2)

                v1_str = _fmt_stat(key, v1)
                v2_str = _fmt_stat(key, v2)
                self._draw_stat_text(v1_str, val_font, GRAPH_LINE_T1,
                                     bar_x, ry + 12)
                v2s = val_font.render(v2_str, True, GRAPH_LINE_T2)
                self._draw_stat_text(v2_str, val_font, GRAPH_LINE_T2,
                                     bar_x + bar_w - v2s.get_width(), ry + 12)

        elif self._stat_mode == 2:
            # Single-stat view with arrows (no background)
            key, label = _DROPDOWN_STATS[self._stat_dropdown_idx]
            v1, v2 = self._get_latest_stat_values(key)

            lbl = font.render(label, True, (200, 200, 220))
            lbl_x = px + pw // 2 - lbl.get_width() // 2
            self._draw_stat_text(label, font, (200, 200, 220), lbl_x, py + 5)

            bar_x = px + 28
            bar_w = pw - 56
            bar_y = py + 24
            self._draw_comparison_bar(bar_x, bar_y, bar_w, 10, v1, v2)

            v1_str = _fmt_stat(key, v1)
            v2_str = _fmt_stat(key, v2)
            v1s = val_font.render(v1_str, True, GRAPH_LINE_T1)
            v2s = val_font.render(v2_str, True, GRAPH_LINE_T2)
            self._draw_stat_text(v1_str, val_font, GRAPH_LINE_T1,
                                 bar_x, bar_y + 14)
            self._draw_stat_text(v2_str, val_font, GRAPH_LINE_T2,
                                 bar_x + bar_w - v2s.get_width(), bar_y + 14)

            # Arrow buttons on sides
            self._dd_left_btn.rect.topleft = (px + 4, py + 24)
            self._dd_right_btn.rect.topleft = (px + pw - 26, py + 24)
            self._dd_left_btn.draw(self.screen)
            self._dd_right_btn.draw(self.screen)

    def _draw_stats_overlay(self):
        """Draw the Score Screen overlay (full screen replacement)."""
        mw = self._reader.map_width
        total_h = TOP_BAR_HEIGHT + self._reader.map_height + BOTTOM_BAR_HEIGHT
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

        # Animated score bars
        if self._stats_data and "final" in self._stats_data:
            final = self._stats_data["final"]
            s1 = final.get("1", {}).get("score", 0)
            s2 = final.get("2", {}).get("score", 0)
            total_score = s1 + s2

            elapsed = pygame.time.get_ticks() - self._score_anim_start
            progress = _ease_out_cubic(min(1.0, elapsed / _ANIM_MS))

            bar_y = 38
            bar_area = mw - _BAR_PAD_X * 2 - _BAR_GAP
            frac1 = s1 / total_score if total_score > 0 else 0.5
            w1 = int(bar_area * frac1 * progress)
            w2 = int(bar_area * (1.0 - frac1) * progress)

            r1 = pygame.Rect(_BAR_PAD_X, bar_y, w1, _BAR_HEIGHT)
            _draw_3d_bar(self.screen, r1, _BAR_T1_COLOR, _BAR_BORDER_T1)

            r2_x = mw - _BAR_PAD_X - w2
            r2 = pygame.Rect(r2_x, bar_y, w2, _BAR_HEIGHT)
            _draw_3d_bar(self.screen, r2, _BAR_T2_COLOR, _BAR_BORDER_T2)

            score_font = _get_font(SCORE_FONT_SIZE)
            s1_surf = score_font.render(f"{self._name1}: {s1:,}", True, (255, 255, 255))
            s2_surf = score_font.render(f"{self._name2}: {s2:,}", True, (255, 255, 255))

            s1_y = bar_y + (_BAR_HEIGHT - s1_surf.get_height()) // 2
            if progress > 0.05:
                self.screen.blit(s1_surf, (_BAR_PAD_X + 10, s1_y))

            s2_y = bar_y + (_BAR_HEIGHT - s2_surf.get_height()) // 2
            if progress > 0.05:
                self.screen.blit(s2_surf,
                                 (mw - _BAR_PAD_X - s2_surf.get_width() - 10, s2_y))

        self._stat_tabs.draw(self.screen)

        if self._is_build_tab():
            self._draw_build_order_tab()
        else:
            self._stat_graph.draw(self.screen)

        self._stat_close_btn.draw(self.screen)
        pygame.display.flip()

    def _draw_build_order_tab(self):
        """Draw two-column scrollable build order within the graph area."""
        area = self._stat_graph.rect
        ax, ay, aw, ah = area.x, area.y, area.w, area.h

        # Background
        pygame.draw.rect(self.screen, (20, 20, 32), area, border_radius=4)
        pygame.draw.rect(self.screen, (40, 40, 55), area, 1, border_radius=4)

        if not self._stats_data or "final" not in self._stats_data:
            return

        final = self._stats_data["final"]
        bo1 = final.get("1", {}).get("build_order", [])
        bo2 = final.get("2", {}).get("build_order", [])

        font = _get_font(14)
        row_h = 18
        r = BUILD_ORDER_RADIUS
        pad_x = 12
        pad_y = 8
        col_w = aw // 2

        # Clip to graph area
        clip_rect = pygame.Rect(ax, ay, aw, ah)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        # Column headers
        hdr_y = ay + pad_y - self._build_scroll
        hdr_font = _get_font(16)
        h1 = hdr_font.render(self._name1, True, GRAPH_LINE_T1)
        h2 = hdr_font.render(self._name2, True, GRAPH_LINE_T2)
        self.screen.blit(h1, (ax + pad_x, hdr_y))
        self.screen.blit(h2, (ax + col_w + pad_x, hdr_y))

        start_y = hdr_y + row_h + 4

        def _draw_column(entries: list, col_x: int, color: tuple):
            for i, entry in enumerate(entries):
                ey = start_y + i * row_h
                if ey + row_h < ay or ey > ay + ah:
                    continue
                cx = col_x + pad_x + r
                cy = ey + row_h // 2
                pygame.draw.circle(self.screen, color, (cx, cy), r)
                ut = entry.get("unit_type", "soldier") if isinstance(entry, dict) else "soldier"
                name = ut.replace("_", " ").title()
                name_surf = font.render(name, True, (200, 200, 220))
                self.screen.blit(name_surf, (cx + r + 6, cy - name_surf.get_height() // 2))

        _draw_column(bo1, ax, GRAPH_LINE_T1)
        _draw_column(bo2, ax + col_w, GRAPH_LINE_T2)

        # Clamp scroll to content
        max_rows = max(len(bo1), len(bo2))
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
        return ent.get("tm") == self._team_view

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

    def _circle_select(self, entities: list[dict], cx: float, cy: float,
                       sr: float, additive: bool):
        """Select all selectable entities in a drag circle (CC only if no units)."""
        if not additive:
            self._selected_ids.clear()
        selected_units: list[int] = []
        cc_id: int | None = None
        for ent in entities:
            if not self._is_selectable(ent):
                continue
            ex, ey = ent.get("x", 0), ent.get("y", 0)
            t = ent.get("t")
            er = CC_RADIUS if t == "CC" else ent.get("r", 5)
            if math.hypot(ex - cx, ey - cy) <= sr + er:
                if t == "CC":
                    cc_id = ent.get("id")
                elif t == "U":
                    selected_units.append(ent.get("id"))
        if selected_units:
            self._selected_ids.update(selected_units)
        elif cc_id is not None:
            self._selected_ids.add(cc_id)

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
            # CC heal ring: also show when selected
            return

        ex = ent.get("x", 0)
        ey = ent.get("y", 0) + self._gy
        tm = ent.get("tm", 1)

        # CC: show heal radius circle + attack range
        if t == "CC":
            # Heal radius circle
            heal_r = int(CC_HEAL_RADIUS)
            heal_color = CC_HEAL_COLOR_T1 if tm == 1 else CC_HEAL_COLOR_T2
            heal_ring = CC_HEAL_RING_T1 if tm == 1 else CC_HEAL_RING_T2
            temp = pygame.Surface((heal_r * 2, heal_r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp, heal_color, (heal_r, heal_r), heal_r)
            pygame.draw.circle(temp, heal_ring, (heal_r, heal_r), heal_r, 1)
            self.screen.blit(temp, (int(ex) - heal_r, int(ey) - heal_r))

            # Attack range circle
            atk_r = int(CC_LASER_RANGE)
            temp2 = pygame.Surface((atk_r * 2, atk_r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp2, RANGE_COLOR, (atk_r, atk_r), atk_r, 1)
            self.screen.blit(temp2, (int(ex) - atk_r, int(ey) - atk_r))
            return

        # ME: no weapon, skip
        if t == "ME":
            return

        # Unit: draw FOV arc
        weapon = stats.get("weapon")
        if not weapon:
            return
        r = int(weapon.get("range", 50))
        if r <= 0:
            return
        is_healer = weapon.get("hits_only_friendly", False)
        color = MEDIC_HEAL_COLOR if is_healer else RANGE_COLOR
        fa = ent.get("fa", 0.0)

        half_fov = fov / 2.0
        if fov >= math.tau - 0.01:
            temp = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp, color, (r, r), r, 1)
            self.screen.blit(temp, (int(ex) - r, int(ey) - r))
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
        self.screen.blit(temp, (ex - temp_size // 2, ey - temp_size // 2))

    # -- fog of war ---------------------------------------------------------

    def _draw_fog(self, entities: list[dict]):
        """Draw fog of war overlay when in team view mode."""
        if self._team_view == 0:
            return

        FOG_ALPHA = 200
        mw = self._reader.map_width
        mh = self._reader.map_height
        self._fog_surface.fill((0, 0, 0, FOG_ALPHA))

        # Collect LOS circles from the viewed team's entities
        los_circles: list[tuple[int, int, int]] = []
        for ent in entities:
            t = ent.get("t")
            if t not in ("U", "CC", "ME"):
                continue
            if ent.get("tm") != self._team_view:
                continue
            ut = ent.get("ut", "soldier")
            stats = UNIT_TYPES.get(ut, {})
            los = int(stats.get("los", 100))
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

        self.screen.blit(self._fog_surface, (0, self._gy))

        # Border at the fog edge
        self._fog_border.fill((0, 0, 0))
        for ex, ey, r in los_circles:
            pygame.draw.circle(self._fog_border, (160, 160, 160), (ex, ey), r)
        for ex, ey, r in los_circles:
            pygame.draw.circle(self._fog_border, (0, 0, 0), (ex, ey), max(r - 1, 0))
        self.screen.blit(self._fog_border, (0, self._gy))

    # -- team name labels ---------------------------------------------------

    def _draw_team_labels(self, entities: list[dict]):
        """Draw player/AI name labels above command centers."""
        font = _get_font(20)
        for ent in entities:
            if ent.get("t") != "CC":
                continue
            tm = ent.get("tm", 1)
            name = self._team_names.get(tm, f"Team {tm}")
            team_color = TEAM1_COLOR if tm == 1 else TEAM2_COLOR
            name_surf = font.render(name, True, team_color)
            nx = int(ent.get("x", 0)) - name_surf.get_width() // 2
            ny = int(ent.get("y", 0)) + self._gy - 40
            self.screen.blit(name_surf, (nx, ny))

    # -- command line helper ------------------------------------------------

    def _draw_command_line(self, x1: float, y1: float, x2: float, y2: float,
                           color: tuple):
        """Draw a command line from (x1,y1) to (x2,y2) with an arrowhead at the end."""
        pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), 1)
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
        pygame.draw.polygon(self.screen, color, [(x2, y2), wing1, wing2])

    # -- entity renderers ---------------------------------------------------
    # All entity positions are offset by self._gy (top bar height)

    def _draw_unit(self, ent: dict):
        x, y = ent.get("x", 0), ent.get("y", 0) + self._gy
        c = tuple(ent.get("c", [255, 255, 255]))
        r = ent.get("r", 5)
        hp = ent.get("hp", 100)
        ut = ent.get("ut", "soldier")

        # Command indicators (shown for selected units)
        eid = ent.get("id")
        if eid in self._selected_ids:
            if "atx" in ent and "aty" in ent:
                # Attack command: dark red line + arrow
                atx = ent["atx"]
                aty = ent["aty"] + self._gy
                self._draw_command_line(x, y, atx, aty, _ATTACK_CMD_COLOR)
            elif "tx" in ent and "ty" in ent:
                # Move command: dark green line + arrow
                tx = ent["tx"]
                ty = ent["ty"] + self._gy
                self._draw_command_line(x, y, tx, ty, _MOVE_CMD_COLOR)

        pygame.draw.circle(self.screen, c, (x, y), r)

        # Symbol
        stats = UNIT_TYPES.get(ut, {})
        symbol = stats.get("symbol")
        if symbol:
            scale = r / 16.0
            translated = [(x + px * scale, y + py * scale) for px, py in symbol]
            pygame.draw.polygon(self.screen, (0, 0, 0), translated)
            pygame.draw.polygon(self.screen, c, translated, 1)

        # Health bar
        max_hp = stats.get("hp", 100)
        if hp < max_hp:
            self._draw_health_bar(x, y, r + HEALTH_BAR_OFFSET, hp, max_hp)

    def _draw_command_center(self, ent: dict):
        x, y = ent.get("x", 0), ent.get("y", 0) + self._gy
        c = tuple(ent.get("c", [255, 255, 255]))
        pts = ent.get("pts", [])
        tm = ent.get("tm", 1)
        hp = ent.get("hp", 1000)

        if pts:
            translated = [(x + px, y + py) for px, py in pts]
            pygame.draw.polygon(self.screen, c, translated)
            outline = (150, 220, 255) if tm == 1 else (255, 140, 140)
            pygame.draw.polygon(self.screen, outline, translated, 2)

        if hp < CC_HP:
            self._draw_health_bar(x, y, CC_RADIUS + HEALTH_BAR_OFFSET,
                                  hp, CC_HP, bar_w=40)

    def _draw_metal_spot(self, ent: dict):
        x, y = ent.get("x", 0), ent.get("y", 0) + self._gy
        r = ent.get("r", 5)
        ow = ent.get("ow")
        cp = ent.get("cp", 0.0)

        # Capture range circle with alpha
        cr = int(METAL_SPOT_CAPTURE_RADIUS)
        size = cr * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(temp, METAL_SPOT_CAPTURE_RANGE_COLOR, (cr, cr), cr)
        self.screen.blit(temp, (int(x) - cr, int(y) - cr))

        # Base dot
        if ow is None:
            color = (255, 200, 60)
        elif ow == 1:
            color = (80, 140, 255)
        else:
            color = (255, 80, 80)
        pygame.draw.circle(self.screen, color, (int(x), int(y)), int(r))

        # Capture progress arc
        if ow is None and abs(cp) > 0.01:
            progress_color = METAL_SPOT_CAPTURE_ARC_COLOR_T1 if cp > 0 else METAL_SPOT_CAPTURE_ARC_COLOR_T2
            arc_r = METAL_SPOT_CAPTURE_RADIUS + METAL_SPOT_CAPTURE_ARC_WIDTH
            start_angle = math.pi / 2
            end_angle = start_angle + cp * math.tau
            if cp > 0:
                a, b = start_angle, end_angle
            else:
                a, b = end_angle, start_angle
            rect = pygame.Rect(int(x - arc_r), int(y - arc_r),
                               int(arc_r * 2), int(arc_r * 2))
            pygame.draw.arc(self.screen, progress_color, rect, a, b,
                            int(METAL_SPOT_CAPTURE_ARC_WIDTH))

    def _draw_metal_extractor(self, ent: dict):
        x, y = ent.get("x", 0), ent.get("y", 0) + self._gy
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
        pygame.draw.polygon(self.screen, (0, 0, 0), points, 1)

        if hp < METAL_EXTRACTOR_HP:
            self._draw_health_bar(x, y, r + HEALTH_BAR_OFFSET,
                                  hp, METAL_EXTRACTOR_HP)

    def _draw_laser(self, lf: list):
        if len(lf) < 6:
            return
        x1, y1, x2, y2 = lf[0], lf[1] + self._gy, lf[2], lf[3] + self._gy
        color = tuple(lf[4])
        width = lf[5]
        temp = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        c = (*color[:3], 200)
        pygame.draw.line(temp, c, (x1, y1), (x2, y2), width)
        self.screen.blit(temp, (0, 0))

    def _draw_health_bar(self, cx: float, cy: float, offset_y: float,
                         hp: float, max_hp: float,
                         bar_w: float = HEALTH_BAR_WIDTH):
        ratio = hp / max_hp if max_hp > 0 else 0
        bx = cx - bar_w / 2
        by = cy - offset_y
        pygame.draw.rect(self.screen, HEALTH_BAR_BG,
                         (bx, by, bar_w, HEALTH_BAR_HEIGHT))
        fg = HEALTH_BAR_FG if ratio > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(self.screen, fg,
                         (bx, by, bar_w * ratio, HEALTH_BAR_HEIGHT))
