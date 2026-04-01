"""Victory / Defeat / Draw results screen with post-game statistics."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from systems import music
from ui.theme import (
    MENU_BG, BTN_WIDTH, BTN_HEIGHT,
    GRAPH_LINE_COLORS, GRAPH_FILL_COLORS, SCORE_TEAM_COLORS,
    SCORE_FONT_SIZE,
    STATS_HEADER_FONT_SIZE, STATS_SUB_FONT_SIZE,
    BUILD_ORDER_RADIUS,
)
from ui.widgets import Button, ToggleGroup, MultiLineGraph, _get_font
from config.unit_types import UNIT_TYPES
from config.settings import TEAM_COLORS

# Player colour dots (matches lobby palette)
_PLAYER_COLORS = [
    (80,  140, 255), (80,  220, 160), (255,  80,  80), (255, 160,  60),
    (180,  80, 220), (80,  220, 220), (220, 220,  80), (220,  80, 160),
]
_BADGE_ROW_H = 20  # height added to tab/graph offset when badges are shown

# Tab definitions: (value, label)
_TABS = [
    ("cc_health", "CC HP"),
    ("army_count", "Army Size"),
    ("units_killed", "Kills"),
    ("damage_dealt", "Damage"),
    ("healing_done", "Healing"),
    ("metal_spots", "Build %"),
    ("apm", "APM"),
    ("step_ms", "Step ms"),
    ("build_order", "Build"),
]

_WHITE = (220, 220, 240)

# Score bar animation
_BAR_PAD_X = 30
_BAR_GAP = 4
_BAR_HEIGHT = 28
_BAR_Y = 48
_ANIM_MS = 3000


def _bar_color(team_id: int) -> tuple:
    """Return (base_color, border_color) for a team's score bar."""
    base = TEAM_COLORS.get(team_id, (120, 120, 120))
    # Lighten the base color slightly for the border
    border = tuple(min(255, c + 30) for c in base[:3])
    return base, border


def _compress_build_order(bo: list[dict]) -> list[dict]:
    """Two-level compression of a build order list.

    Level 1 — same-tick, same-type entries -> one entry with ``spawn_count``
               (handles units like scouts that produce 3 per spawn cycle).
    Level 2 — consecutive events of the same type and spawn_count -> ``run_count``
               (e.g. four scout batches in a row: Scout (x3) x4).

    Output entries have keys: unit_type, tick, spawn_count, run_count.
    """
    if not bo:
        return []

    # Level 1: group same-tick same-type
    events: list[dict] = []
    i = 0
    while i < len(bo):
        entry = bo[i]
        tick = entry.get("tick", 0)
        ut = entry.get("unit_type", "")
        j = i + 1
        while j < len(bo) and bo[j].get("tick") == tick and bo[j].get("unit_type") == ut:
            j += 1
        events.append({"unit_type": ut, "tick": tick, "spawn_count": j - i})
        i = j

    # Level 2: group consecutive same-type, same-spawn-count
    result: list[dict] = []
    i = 0
    while i < len(events):
        ev = events[i]
        ut = ev["unit_type"]
        sc = ev["spawn_count"]
        j = i + 1
        while j < len(events) and events[j]["unit_type"] == ut and events[j]["spawn_count"] == sc:
            j += 1
        result.append({"unit_type": ut, "tick": ev["tick"],
                        "spawn_count": sc, "run_count": j - i})
        i = j
    return result


def _build_order_label(entry: dict) -> str:
    """Format a compressed build order entry as a display string."""
    ut = entry.get("unit_type", "soldier") if isinstance(entry, dict) else "soldier"
    name = ut.replace("_", " ").title()
    sc = entry.get("spawn_count", 1) if isinstance(entry, dict) else 1
    rc = entry.get("run_count", 1) if isinstance(entry, dict) else 1
    if sc > 1 and rc > 1:
        return f"{name} (x{sc}) x{rc}"
    elif sc > 1:
        return f"{name} (x{sc})"
    elif rc > 1:
        return f"{name} x{rc}"
    return name


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _draw_3d_bar(surface: pygame.Surface, rect: pygame.Rect,
                 base_color: tuple, border_color: tuple):
    """Draw a filled bar with a vertical gradient for a 3D bevel look."""
    if rect.w <= 0 or rect.h <= 0:
        return
    r, g, b = base_color[:3]
    # Build a gradient surface: lighter at top, darker at bottom
    bar = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    for row in range(rect.h):
        frac = row / max(1, rect.h - 1)
        if frac < 0.45:
            # Highlight zone — blend toward white
            t = 1.0 - frac / 0.45
            lr = min(255, r + int(45 * t))
            lg = min(255, g + int(45 * t))
            lb = min(255, b + int(45 * t))
        else:
            # Shadow zone — blend toward black
            t = (frac - 0.45) / 0.55
            lr = max(0, r - int(50 * t))
            lg = max(0, g - int(50 * t))
            lb = max(0, b - int(50 * t))
        bar.fill((lr, lg, lb, 255), (0, row, rect.w, 1))
    # Mask to rounded shape: draw a rounded rect on a mask surface, then composite
    mask = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), (0, 0, rect.w, rect.h),
                     border_radius=5)
    # Apply mask: keep only pixels where the mask is opaque
    bar.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    surface.blit(bar, rect.topleft)
    # Border
    pygame.draw.rect(surface, border_color, rect, 1, border_radius=5)


class ResultsScreen(BaseScreen):
    """Shows game outcome with tabbed stat graphs and build order."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 winner: int = 0, human_teams: set[int] | None = None,
                 stats: dict | None = None,
                 replay_filepath: str | None = None,
                 team_names: dict[int, str] | None = None,
                 player_names: dict[int, str] | None = None,
                 player_team: dict[int, int] | None = None,
                 source_screen: str = "main_menu",
                 lobby_data: dict | None = None):
        super().__init__(screen, clock)
        self._winner = winner
        self._human_teams = human_teams or set()
        self._stats = stats  # the full stats dict from GameStats.finalize()
        self._replay_filepath = replay_filepath
        self._team_names = team_names or {}
        self._player_names = player_names or {}
        self._player_team = player_team or {}
        self._source_screen = source_screen
        self._lobby_data = lobby_data or {}

        # Derive the set of team IDs from stats or player_team
        self._team_ids: list[int] = self._derive_team_ids()

        # Badge row: show when 3+ players (shifts tab/graph down)
        self._show_badges = len(self._player_names) >= 3
        badge_offset = _BADGE_ROW_H if self._show_badges else 0

        # Buttons — three centered side by side at bottom
        btn_w = 240
        gap = 10
        total_w = btn_w * 3 + gap * 2
        start_x = self.width // 2 - total_w // 2
        btn_y = self.height - 50

        back_label = "Return to Lobby" if source_screen != "main_menu" else "Return to Menu"
        self._btn = Button(start_x, btn_y, btn_w, BTN_HEIGHT, back_label)
        self._replay_btn = Button(start_x + btn_w + gap, btn_y,
                                  btn_w, BTN_HEIGHT, "Watch Replay",
                                  enabled=replay_filepath is not None)
        has_subsystem = stats is not None and "subsystem_ms" in (stats or {})
        self._debug_btn = Button(start_x + (btn_w + gap) * 2, btn_y,
                                 btn_w, BTN_HEIGHT, "Debug",
                                 enabled=has_subsystem)

        # Build order scroll state
        self._build_scroll: int = 0

        # Score bar animation start
        self._anim_start: int = pygame.time.get_ticks()

        # Tab bar and graph (only if stats available)
        self._has_stats = stats is not None and "teams" in (stats or {})
        if self._has_stats:
            tab_options = [(key, label) for key, label in _TABS]
            total_tabs = len(tab_options)
            tab_w = min(90, (self.width - 40) // total_tabs - 2)
            tab_x = (self.width - total_tabs * (tab_w + 2)) // 2
            tab_y = 90 + badge_offset
            self._tabs = ToggleGroup(tab_x, tab_y, tab_options,
                                     selected_index=0, btn_w=tab_w, btn_h=28)

            graph_y = 125 + badge_offset
            graph_h = 340 - badge_offset
            self._graph = MultiLineGraph(30, graph_y, self.width - 60, graph_h)
            self._update_graph()

    def _derive_team_ids(self) -> list[int]:
        """Build a sorted list of team IDs from stats or player_team data."""
        ids: set[int] = set()
        if self._stats and "teams" in self._stats:
            for k in self._stats["teams"]:
                try:
                    ids.add(int(k))
                except (ValueError, TypeError):
                    pass
        if self._stats and "final" in self._stats:
            for k in self._stats["final"]:
                try:
                    ids.add(int(k))
                except (ValueError, TypeError):
                    pass
        for t in self._player_team.values():
            ids.add(t)
        # Fallback if nothing found
        if not ids:
            ids = {1, 2}
        return sorted(ids)

    def _update_graph(self):
        if not self._has_stats:
            return
        key = self._tabs.value
        if key == "build_order":
            return  # build order tab doesn't use graph

        # Build series for each team
        series: list[dict] = []
        timestamps = self._stats.get("timestamps", [])

        if key == "step_ms":
            # step_ms is global, not per-team; show as a single series
            data = self._stats.get("step_ms", [])
            series.append({
                "name": "Step ms",
                "data": data,
                "color": GRAPH_LINE_COLORS[0],
                "visible": True,
            })
        else:
            teams_data = self._stats.get("teams", {})
            for team_id in sorted(self._team_ids):
                team_key = str(team_id)
                data = teams_data.get(team_key, {}).get(key, [])

                # metal_spots data is already in build % (from stats sampling)

                color_idx = (team_id - 1) % len(GRAPH_LINE_COLORS)
                team_name = self._team_names.get(team_id, f"Team {team_id}")
                series.append({
                    "name": team_name,
                    "data": data,
                    "color": GRAPH_LINE_COLORS[color_idx],
                    "visible": True,
                })

        title = dict(_TABS).get(key, key)
        self._graph.title = title

        # Per-tab formatting
        self._graph.y_suffix = "%" if key == "metal_spots" else ""
        self._graph.value_format = "{:.2f}" if key == "step_ms" else None
        self._graph.y_tick_step = 10.0 if key == "metal_spots" else None
        self._graph.y_integer_ticks = key in ("army_count", "units_killed")

        self._graph.set_series(series, timestamps=timestamps)

    def _is_build_tab(self) -> bool:
        return self._has_stats and self._tabs.value == "build_order"

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if self._btn.handle_event(event):
                    return ScreenResult(self._source_screen, data=self._lobby_data)
                if self._replay_btn.handle_event(event):
                    return ScreenResult("replay_playback",
                                        data={"filepath": self._replay_filepath})
                if self._debug_btn.handle_event(event):
                    return ScreenResult("debug", data={
                        "winner": self._winner,
                        "human_teams": self._human_teams,
                        "stats": self._stats,
                        "replay_filepath": self._replay_filepath,
                        "team_names": self._team_names,
                    })
                if self._has_stats:
                    if self._tabs.handle_event(event):
                        self._build_scroll = 0
                        self._update_graph()
                    if self._is_build_tab():
                        if event.type == pygame.MOUSEWHEEL:
                            self._build_scroll -= event.y * 18
                            self._build_scroll = max(0, self._build_scroll)
                    else:
                        self._graph.handle_event(event)

            self._draw()
            self.clock.tick(60)
            music.update()

    def _draw(self):
        self.screen.fill(MENU_BG)

        if self._has_stats:
            self._draw_stats_view()
        else:
            self._draw_simple_view()

        self._btn.draw(self.screen)
        self._replay_btn.draw(self.screen)
        self._debug_btn.draw(self.screen)
        pygame.display.flip()

    def _header_text(self) -> str:
        """Return header string: 'Draw', '{team_name} Victory', or 'Defeat'."""
        if self._winner <= 0:
            return "Draw"
        winner_name = self._team_names.get(self._winner, f"Team {self._winner}")
        if self._human_teams and self._winner not in self._human_teams:
            return "Defeat"
        return f"{winner_name} Victory"

    def _draw_simple_view(self):
        """Fallback when no stats available."""
        text = self._header_text()

        font_big = _get_font(72)
        surf = font_big.render(text, True, _WHITE)
        x = self.width // 2 - surf.get_width() // 2
        y = self.height // 2 - surf.get_height() // 2 - 30
        self.screen.blit(surf, (x, y))

        font_sub = _get_font(24)
        if self._winner > 0:
            winner_name = self._team_names.get(self._winner, f"Team {self._winner}")
            sub = f"{winner_name} destroyed the enemy Command Center."
        else:
            sub = "All Command Centers were destroyed."
        sub_surf = font_sub.render(sub, True, (160, 160, 180))
        sx = self.width // 2 - sub_surf.get_width() // 2
        sy = y + surf.get_height() + 8
        self.screen.blit(sub_surf, (sx, sy))

    def _draw_stats_view(self):
        """Full stats dashboard with header, tabs, graph, build order."""
        # -- Header: result text in white --
        result_text = self._header_text()

        header_font = _get_font(STATS_HEADER_FONT_SIZE)
        h_surf = header_font.render(result_text, True, _WHITE)

        # Center header
        hx = self.width // 2 - h_surf.get_width() // 2
        self.screen.blit(h_surf, (hx, 10))

        # Duration top-right
        duration = self._stats.get("game_duration_seconds", 0)
        m, s = divmod(int(duration), 60)
        dur_str = f"Game Length: {m}:{s:02d}"
        sub_font = _get_font(STATS_SUB_FONT_SIZE)
        dur_surf = sub_font.render(dur_str, True, (160, 160, 180))
        self.screen.blit(dur_surf, (self.width - dur_surf.get_width() - 15, 15))

        # -- Animated score bars (N teams, stacked vertically) --
        self._draw_score_bars()

        # -- Player badges (shown when 3+ players) --
        if self._show_badges:
            self._draw_player_badges()

        # -- Tab bar --
        self._tabs.draw(self.screen)

        # -- Graph or Build Order --
        if self._is_build_tab():
            self._draw_build_order_tab()
        else:
            self._graph.draw(self.screen)

    def _draw_score_bars(self):
        """Draw N horizontal score bars, one per team, stacked vertically."""
        final = self._stats.get("final", {})

        # Gather scores for all teams
        team_scores: list[tuple[int, int]] = []
        for team_id in sorted(self._team_ids):
            score = final.get(str(team_id), {}).get("score", 0)
            team_scores.append((team_id, score))

        max_score = max((s for _, s in team_scores), default=1)
        if max_score <= 0:
            max_score = 1

        elapsed = pygame.time.get_ticks() - self._anim_start
        progress = _ease_out_cubic(min(1.0, elapsed / _ANIM_MS))

        bar_area = self.width - _BAR_PAD_X * 2
        n_teams = len(team_scores)
        score_font = _get_font(SCORE_FONT_SIZE if n_teams <= 2 else max(16, SCORE_FONT_SIZE - 4 * (n_teams - 2)))

        for i, (team_id, score) in enumerate(team_scores):
            bar_y = _BAR_Y + i * (_BAR_HEIGHT + _BAR_GAP)
            frac = score / max_score if max_score > 0 else 0.0
            w = int(bar_area * frac * progress)
            w = max(w, 0)

            base_color, border_color = _bar_color(team_id)
            rect = pygame.Rect(_BAR_PAD_X, bar_y, w, _BAR_HEIGHT)
            _draw_3d_bar(self.screen, rect, base_color, border_color)

            # Score text on bar
            team_name = self._team_names.get(team_id, f"Team {team_id}")
            color_idx = (team_id - 1) % len(SCORE_TEAM_COLORS)
            text_color = SCORE_TEAM_COLORS[color_idx]
            label_surf = score_font.render(f"{team_name}: {score:,}", True, (255, 255, 255))

            text_y = bar_y + (_BAR_HEIGHT - label_surf.get_height()) // 2
            if progress > 0.05:
                # Place text inside the bar if it fits, otherwise just after it
                text_x = _BAR_PAD_X + 10
                self.screen.blit(label_surf, (text_x, text_y))

    def _draw_player_badges(self):
        """Draw a row of colored dots + player names just below the score bars."""
        n_teams = len(self._team_ids)
        badge_y = _BAR_Y + n_teams * (_BAR_HEIGHT + _BAR_GAP) + 2
        font = _get_font(14)

        # Group players by team dynamically
        team_pids: dict[int, list[int]] = {}
        for pid, t in self._player_team.items():
            team_pids.setdefault(t, []).append(pid)

        # Layout: spread team groups across the width
        sorted_teams = sorted(team_pids.keys())
        n_groups = len(sorted_teams)
        if n_groups == 0:
            return

        section_w = (self.width - _BAR_PAD_X * 2) // n_groups

        for gi, team_id in enumerate(sorted_teams):
            pids = sorted(team_pids[team_id])
            start_x = _BAR_PAD_X + gi * section_w
            x = start_x
            for pid in pids:
                name = self._player_names.get(pid, f"P{pid}")
                color = _PLAYER_COLORS[(pid - 1) % len(_PLAYER_COLORS)]
                dot_r = 5
                dot_cx = x + dot_r
                dot_cy = badge_y + dot_r
                pygame.draw.circle(self.screen, color, (dot_cx, dot_cy), dot_r)
                name_surf = font.render(name, True, (180, 180, 200))
                name_x = dot_cx + dot_r + 3
                self.screen.blit(name_surf, (name_x, dot_cy - name_surf.get_height() // 2))
                item_w = dot_r * 2 + 4 + name_surf.get_width() + 10
                x += item_w

    def _draw_build_order_tab(self):
        """Draw multi-column scrollable build order within the graph area.

        One column per player.  New replays include player_id on each entry so
        teammates' builds are separated.  Old replays (no player_id) fall back
        to one column per team.  Uses two-level compression: same-tick batches
        become spawn_count, consecutive repeats become run_count.
        """
        area = self._graph.rect
        ax, ay, aw, ah = area.x, area.y, area.w, area.h

        pygame.draw.rect(self.screen, (20, 20, 32), area, border_radius=4)
        pygame.draw.rect(self.screen, (40, 40, 55), area, 1, border_radius=4)

        final = self._stats.get("final", {})

        # Collect all raw entries, grouped by player_id when available
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

        # Build columns ordered by player_id (or team_id for old data)
        columns: list[tuple[str, list[dict], tuple]] = []
        for pid in sorted(player_raw):
            bo = _compress_build_order(player_raw[pid])
            color = _PLAYER_COLORS[(pid - 1) % len(_PLAYER_COLORS)]
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
