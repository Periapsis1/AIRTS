"""Performance debug screen — multi-line graph of subsystem timings."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import MENU_BG, DEBUG_LINE_COLORS, GRAPH_BG, GRAPH_GRID, GRAPH_AXIS_TEXT
from ui.widgets import BackButton, MultiLineGraph, _get_font

_SUBSYSTEM_ORDER = [
    "commands", "entity_update",
    "ai_step", "capture", "targeting_build", "combat",
    "spawn", "cleanup", "physics",
    "phys_array_build", "phys_unit_collisions",
    "phys_obstacle_push", "phys_writeback", "phys_clamp",
]

_TABLE_TOP = 380
_TABLE_PAD = 20
_ROW_H = 16
_HDR_COLOR = (200, 200, 220)
_VAL_COLOR = (170, 170, 190)


class DebugScreen(BaseScreen):
    """Shows per-subsystem performance data as a multi-line graph."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 winner: int = 0, human_teams: set[int] | None = None,
                 stats: dict | None = None,
                 replay_filepath: str | None = None,
                 team_names: dict[int, str] | None = None):
        super().__init__(screen, clock)
        self._data = {
            "winner": winner,
            "human_teams": human_teams or set(),
            "stats": stats,
            "replay_filepath": replay_filepath,
            "team_names": team_names or {},
        }

        self._back = BackButton()
        self._graph = MultiLineGraph(20, 50, self.width - 40, 320,
                                     title="Performance Debug")
        self._series_info: list[dict] = []
        self._table_scroll: int = 0
        self._load_series(stats or {})

    def _load_series(self, stats: dict):
        timestamps = stats.get("timestamps", [])
        step_ms = stats.get("step_ms", [])
        subsystem_ms = stats.get("subsystem_ms", {})

        series = []
        # First series: total step_ms
        series.append({
            "name": "step_ms",
            "data": step_ms,
            "color": DEBUG_LINE_COLORS[0],
            "visible": True,
        })

        for i, name in enumerate(_SUBSYSTEM_ORDER):
            data = subsystem_ms.get(name, [])
            series.append({
                "name": name,
                "data": data,
                "color": DEBUG_LINE_COLORS[min(i + 1, len(DEBUG_LINE_COLORS) - 1)],
                "visible": True,
            })

        self._graph.set_series(series, timestamps=timestamps)

        # Precompute min/avg/max for the stats table
        self._series_info = []
        for s in series:
            d = s["data"]
            if d:
                mn = min(d)
                mx = max(d)
                avg = sum(d) / len(d)
            else:
                mn = mx = avg = 0.0
            self._series_info.append({
                "name": s["name"],
                "color": s["color"],
                "min": mn,
                "avg": avg,
                "max": mx,
            })

    def _draw_stats_table(self):
        font = _get_font(14)
        x = _TABLE_PAD
        y = _TABLE_TOP
        w = self.width - _TABLE_PAD * 2
        total_rows = len(self._series_info) + 1  # +1 for header
        content_h = total_rows * _ROW_H + 10

        # Visible height: clamp to available screen space (leave room for back btn)
        max_visible_h = self.height - y - 40
        visible_h = min(content_h, max_visible_h)

        # Clamp scroll
        max_scroll = max(0, content_h - visible_h)
        self._table_scroll = max(0, min(self._table_scroll, max_scroll))

        # Background — draw at visible size
        table_rect = pygame.Rect(x, y, w, visible_h)
        pygame.draw.rect(self.screen, GRAPH_BG, table_rect, border_radius=4)
        pygame.draw.rect(self.screen, GRAPH_GRID, table_rect, 1, border_radius=4)

        # Clip to table area
        old_clip = self.screen.get_clip()
        self.screen.set_clip(table_rect)

        # Column positions
        col_name = x + 10
        col_min = x + 200
        col_avg = x + 320
        col_max = x + 440
        col_samples = x + 560

        # Header row (scrolls with content)
        hy = y + 5 - self._table_scroll
        for label, cx in [("Subsystem", col_name), ("Min", col_min),
                           ("Avg", col_avg), ("Max", col_max),
                           ("Samples", col_samples)]:
            s = font.render(label, True, _HDR_COLOR)
            self.screen.blit(s, (cx, hy))

        # Separator line
        pygame.draw.line(self.screen, GRAPH_GRID,
                         (x + 6, hy + _ROW_H), (x + w - 6, hy + _ROW_H), 1)

        # Data rows
        for i, info in enumerate(self._series_info):
            ry = hy + _ROW_H + 2 + i * _ROW_H

            # Skip rows fully outside visible area
            if ry + _ROW_H < y or ry > y + visible_h:
                continue

            # Color swatch
            swatch = pygame.Rect(col_name, ry + 3, 8, 8)
            pygame.draw.rect(self.screen, info["color"], swatch)

            # Name
            name_s = font.render(info["name"], True, info["color"])
            self.screen.blit(name_s, (col_name + 12, ry))

            # Values
            for val, cx in [(info["min"], col_min),
                            (info["avg"], col_avg),
                            (info["max"], col_max)]:
                vs = font.render(f"{val:.3f} ms", True, _VAL_COLOR)
                self.screen.blit(vs, (cx, ry))

            # Sample count from corresponding series data
            n = len(self._graph._series[i]["data"]) if i < len(self._graph._series) else 0
            ns = font.render(str(n), True, _VAL_COLOR)
            self.screen.blit(ns, (col_samples, ry))

        self.screen.set_clip(old_clip)

        # Scrollbar indicator if content overflows
        if max_scroll > 0:
            sb_x = x + w - 6
            sb_h = max(12, int(visible_h * (visible_h / content_h)))
            sb_y = y + int((visible_h - sb_h) * (self._table_scroll / max_scroll))
            pygame.draw.rect(self.screen, (80, 80, 100),
                             (sb_x, sb_y, 4, sb_h), border_radius=2)

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return ScreenResult("results", data=self._data)
                if self._back.handle_event(event):
                    return ScreenResult("results", data=self._data)
                if event.type == pygame.MOUSEWHEEL:
                    self._table_scroll -= event.y * 18
                self._graph.handle_event(event)

            self.screen.fill(MENU_BG)
            self._graph.draw(self.screen)
            self._draw_stats_table()
            self._back.draw(self.screen)
            pygame.display.flip()
            self.clock.tick(60)
