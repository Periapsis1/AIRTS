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

# Fields that get linearly interpolated between frames
_LERP_FIELDS = {"x", "y", "rot", "cp", "tx", "ty"}

_STAT_TABS = [
    ("cc_health", "CC HP"), ("army_count", "Army"),
    ("units_killed", "Kills"), ("damage_dealt", "Damage"),
    ("healing_done", "Healing"), ("metal_spots", "Metal"),
    ("apm", "APM"), ("build_order", "Build"),
]

# Stats shown in the inline comparison dropdown
_DROPDOWN_STATS = [
    ("cc_health", "CC Health"),
    ("army_count", "Army"),
    ("units_killed", "Kills"),
    ("damage_dealt", "Damage"),
    ("healing_done", "Healing"),
    ("metal_spots", "Metal"),
    ("apm", "APM"),
]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_entity(prev: dict, cur: dict, t: float) -> dict:
    """Blend numeric visual fields between two snapshots of the same entity."""
    result = dict(cur)
    for key in _LERP_FIELDS:
        if key in prev and key in cur:
            pv = prev[key]
            cv = cur[key]
            if isinstance(pv, (int, float)) and isinstance(cv, (int, float)):
                result[key] = _lerp(float(pv), float(cv), t)
    return result


class ReplayPlaybackScreen(BaseScreen):
    """Plays back a .rtsreplay file with transport controls."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 filepath: str):
        super().__init__(screen, clock)
        self._reader = ReplayReader(filepath)
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
        self._show_actions_btn = Button(mw - 300, top_cy, 95, btn_h,
                                        "Show Actions")
        self._show_actions = False

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
            self._stat_tabs = ToggleGroup(tab_x, 60, _STAT_TABS,
                                          selected_index=0, btn_w=tab_w, btn_h=28)
            overlay_h = TOP_BAR_HEIGHT + mh + BOTTOM_BAR_HEIGHT
            self._stat_graph = LineGraph(30, 95, mw - 60, overlay_h - 180,
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
        t1 = self._stats_data.get("teams", {}).get("1", {}).get(key, [])
        t2 = self._stats_data.get("teams", {}).get("2", {}).get(key, [])
        timestamps = self._stats_data.get("timestamps", [])
        x_labels = []
        for ts in timestamps:
            secs = ts / 60.0
            m, s = divmod(int(secs), 60)
            x_labels.append(f"{m}:{s:02d}")
        tab_dict = dict(self._stat_tabs.options)
        self._stat_graph.title = tab_dict.get(key, key)
        self._stat_graph.set_data(t1, t2, x_labels)

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

                if self._show_actions_btn.handle_event(event):
                    self._show_actions = not self._show_actions
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

        # Draw laser flashes
        for lf in self._cur_lasers:
            self._draw_laser(lf)

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
        self._show_actions_btn.draw(self.screen)
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

                self._draw_stat_text(str(int(v1)), val_font, GRAPH_LINE_T1,
                                     bar_x, ry + 12)
                v2s = val_font.render(str(int(v2)), True, GRAPH_LINE_T2)
                self._draw_stat_text(str(int(v2)), val_font, GRAPH_LINE_T2,
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

            v1s = val_font.render(str(int(v1)), True, GRAPH_LINE_T1)
            v2s = val_font.render(str(int(v2)), True, GRAPH_LINE_T2)
            self._draw_stat_text(str(int(v1)), val_font, GRAPH_LINE_T1,
                                 bar_x, bar_y + 14)
            self._draw_stat_text(str(int(v2)), val_font, GRAPH_LINE_T2,
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
        title = f"Team {winner} Victory" if winner > 0 else "Draw"
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
            s1_surf = score_font.render(f"Team 1: {s1:,}", True, (255, 255, 255))
            s2_surf = score_font.render(f"Team 2: {s2:,}", True, (255, 255, 255))

            s1_y = bar_y + (_BAR_HEIGHT - s1_surf.get_height()) // 2
            if w1 > s1_surf.get_width() + 16:
                self.screen.blit(s1_surf, (_BAR_PAD_X + 10, s1_y))
            elif progress > 0.05:
                self.screen.blit(s1_surf, (_BAR_PAD_X + w1 + 8, s1_y))

            s2_y = bar_y + (_BAR_HEIGHT - s2_surf.get_height()) // 2
            if w2 > s2_surf.get_width() + 16:
                self.screen.blit(s2_surf,
                                 (r2_x + w2 - s2_surf.get_width() - 10, s2_y))
            elif progress > 0.05:
                self.screen.blit(s2_surf, (r2_x - s2_surf.get_width() - 8, s2_y))

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
        h1 = hdr_font.render("Team 1", True, GRAPH_LINE_T1)
        h2 = hdr_font.render("Team 2", True, GRAPH_LINE_T2)
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

    # -- entity renderers ---------------------------------------------------
    # All entity positions are offset by self._gy (top bar height)

    def _draw_unit(self, ent: dict):
        x, y = ent.get("x", 0), ent.get("y", 0) + self._gy
        c = tuple(ent.get("c", [255, 255, 255]))
        r = ent.get("r", 5)
        hp = ent.get("hp", 100)
        ut = ent.get("ut", "soldier")

        # Move indicator: line + circle at target
        if self._show_actions and "tx" in ent and "ty" in ent:
            tx = ent["tx"]
            ty = ent["ty"] + self._gy
            pygame.draw.line(self.screen, c, (x, y), (tx, ty), 1)
            pygame.draw.circle(self.screen, c, (int(tx), int(ty)), 3, 1)

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
