"""Replay browser — lists saved replays with Watch / Delete actions."""
from __future__ import annotations
from datetime import datetime
import os
import subprocess
import sys
import threading
import pygame
from screens.base import BaseScreen, ScreenResult
from systems.replay import ReplayReader
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT,
)
from ui.widgets import Button, BackButton, _get_font


_CARD_HEIGHT = 72
_CARD_PAD = 8
_CARD_MARGIN_X = 30
_LIST_TOP = 80
_SCROLL_SPEED = 3
_CARD_BORDER_COLOR = (50, 50, 70)
_CARD_BG = (22, 22, 34)
_CARD_SELECTED_BG = (35, 35, 55)
_CARD_SELECTED_BORDER = (80, 80, 120)
_DBLCLICK_MS = 400
_SCROLLBAR_W = 8
_SCROLLBAR_MARGIN = 10
_SCROLLBAR_TRACK_COLOR = (35, 35, 50)
_SCROLLBAR_THUMB_COLOR = (70, 70, 100)
_SCROLLBAR_THUMB_HOVER = (90, 90, 130)


def _relative_time(iso_ts: str) -> str:
    """Return a human-readable relative time like '5 minutes ago'."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return ""
    now = datetime.now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago" if mins == 1 else f"{mins} mins ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hr ago" if hours == 1 else f"{hours} hrs ago"
    days = hours // 24
    if days < 30:
        return f"{days} day ago" if days == 1 else f"{days} days ago"
    months = days // 30
    if months < 12:
        return f"{months} month ago" if months == 1 else f"{months} months ago"
    years = days // 365
    return f"{years} year ago" if years == 1 else f"{years} years ago"


def _format_datetime(iso_ts: str) -> str:
    """Format ISO timestamp to '12/25/2025 3:45 PM' style."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return iso_ts[:19].replace("T", " ") if iso_ts else ""
    try:
        return dt.strftime("%#m/%d/%Y %#I:%M %p")  # Windows
    except ValueError:
        return dt.strftime("%-m/%d/%Y %-I:%M %p")  # Unix


def _team_name(team: int, config: dict, human_teams: list) -> str:
    """Resolve a team number to a display name."""
    ai_names = config.get("team_ai_names", {})
    ai_ids = config.get("team_ai_ids", {})
    player_name = config.get("player_name", "Player")
    t_str = str(team)
    t_int = team
    if t_int in human_teams:
        return player_name
    # Prefer ai_name, fall back to ai_id, then "Team N"
    name = ai_names.get(t_int) or ai_names.get(t_str)
    if name:
        return name
    name = ai_ids.get(t_int) or ai_ids.get(t_str)
    if name:
        return name.replace("_", " ").title()
    return f"Team {team}"


class ReplayListScreen(BaseScreen):
    """Scrollable list of saved replays with Watch and Delete buttons."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)
        self._back = BackButton()
        self._replays: list[dict] = []
        self._selected: int = -1
        self._scroll: int = 0
        self._loading = True

        # Per-card buttons (created dynamically during draw)
        self._card_buttons: list[tuple[Button, Button]] = []

        # Double-click tracking
        self._last_click_time: int = 0
        self._last_click_idx: int = -1

        # Scrollbar drag state
        self._sb_dragging = False
        self._sb_drag_offset = 0

        # Open Folder button (positioned in _draw)
        self._open_folder_btn = Button(0, 0, 110, 30, "Open Folder", font_size=18)

        self._start_loading()

    def _start_loading(self):
        self._replays = []
        self._loading = True
        self._selected = -1
        self._card_buttons = []
        self._scroll = 0
        t = threading.Thread(target=self._load_worker, daemon=True)
        t.start()

    def _load_worker(self):
        for meta in ReplayReader.list_replays_iter():
            self._replays.append(meta)  # GIL makes list.append atomic
        self._loading = False

    def _refresh(self):
        self._start_loading()

    def _visible_rows(self) -> int:
        return (self.height - _LIST_TOP - 20) // (_CARD_HEIGHT + _CARD_PAD)

    def _card_y(self, vi: int) -> int:
        return _LIST_TOP + vi * (_CARD_HEIGHT + _CARD_PAD)

    def _max_scroll(self) -> int:
        return max(0, len(self._replays) - self._visible_rows())

    def _scrollbar_geometry(self) -> tuple[pygame.Rect, pygame.Rect] | None:
        """Return (track_rect, thumb_rect) or None if scrollbar not needed."""
        total = len(self._replays)
        visible = self._visible_rows()
        if total <= visible:
            return None
        track_x = self.width - _SCROLLBAR_MARGIN - _SCROLLBAR_W
        list_h = visible * (_CARD_HEIGHT + _CARD_PAD)
        track_rect = pygame.Rect(track_x, _LIST_TOP, _SCROLLBAR_W, list_h)
        thumb_h = max(20, int(list_h * visible / total))
        max_s = self._max_scroll()
        if max_s > 0:
            thumb_y = _LIST_TOP + int((list_h - thumb_h) * self._scroll / max_s)
        else:
            thumb_y = _LIST_TOP
        thumb_rect = pygame.Rect(track_x, thumb_y, _SCROLLBAR_W, thumb_h)
        return track_rect, thumb_rect

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return ScreenResult("main_menu")
                if self._back.handle_event(event):
                    return ScreenResult("main_menu")
                if self._open_folder_btn.handle_event(event):
                    self._open_replays_folder()

                # Per-card Watch/Delete buttons
                for i, (wb, db) in enumerate(self._card_buttons):
                    idx = i + self._scroll
                    if wb.handle_event(event):
                        if 0 <= idx < len(self._replays):
                            fp = self._replays[idx]["filepath"]
                            return ScreenResult("replay_playback",
                                                data={"filepath": fp})
                    if db.handle_event(event):
                        if 0 <= idx < len(self._replays):
                            fp = self._replays[idx]["filepath"]
                            ReplayReader.delete_replay(fp)
                            self._refresh()
                            break

                # Scrollbar drag
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    geom = self._scrollbar_geometry()
                    if geom is not None:
                        track_rect, thumb_rect = geom
                        if thumb_rect.collidepoint(event.pos):
                            self._sb_dragging = True
                            self._sb_drag_offset = event.pos[1] - thumb_rect.y
                        elif track_rect.collidepoint(event.pos):
                            # Click on track — jump to that position
                            self._sb_dragging = True
                            self._sb_drag_offset = thumb_rect.h // 2
                            self._scrollbar_drag_to(event.pos[1])

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self._sb_dragging = False

                if event.type == pygame.MOUSEMOTION and self._sb_dragging:
                    self._scrollbar_drag_to(event.pos[1])

                # Scroll wheel
                if event.type == pygame.MOUSEWHEEL:
                    self._scroll = max(
                        0,
                        min(self._scroll - event.y * _SCROLL_SPEED,
                            self._max_scroll()),
                    )

                # Card click (select / double-click to watch)
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if not self._sb_dragging:
                        mx, my = event.pos
                        visible = self._visible_rows()
                        for vi in range(visible):
                            cy = self._card_y(vi)
                            card_rect = pygame.Rect(
                                _CARD_MARGIN_X, cy,
                                self.width - _CARD_MARGIN_X * 2,
                                _CARD_HEIGHT)
                            if card_rect.collidepoint(mx, my):
                                idx = vi + self._scroll
                                if 0 <= idx < len(self._replays):
                                    now = pygame.time.get_ticks()
                                    if (idx == self._last_click_idx and
                                            now - self._last_click_time < _DBLCLICK_MS):
                                        # Double-click — watch
                                        fp = self._replays[idx]["filepath"]
                                        return ScreenResult(
                                            "replay_playback",
                                            data={"filepath": fp})
                                    self._selected = idx
                                    self._last_click_idx = idx
                                    self._last_click_time = now
                                break

            self._draw()
            self.clock.tick(60)

    def _scrollbar_drag_to(self, mouse_y: int):
        """Update scroll position based on mouse y during scrollbar drag."""
        geom = self._scrollbar_geometry()
        if geom is None:
            return
        track_rect, thumb_rect = geom
        visible = self._visible_rows()
        list_h = visible * (_CARD_HEIGHT + _CARD_PAD)
        thumb_h = max(20, int(list_h * visible / len(self._replays)))
        usable = list_h - thumb_h
        if usable <= 0:
            return
        frac = (mouse_y - self._sb_drag_offset - _LIST_TOP) / usable
        frac = max(0.0, min(1.0, frac))
        self._scroll = round(frac * self._max_scroll())

    @staticmethod
    def _open_replays_folder():
        folder = os.path.abspath("replays")
        os.makedirs(folder, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def _draw(self):
        self.screen.fill(MENU_BG)
        self._back.draw(self.screen)

        # Title
        font_h = _get_font(HEADING_FONT_SIZE)
        title = font_h.render("Replays", True, CONTENT_TEXT)
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, 30))

        # Open Folder button (right-aligned near title)
        of_x = self.width - _CARD_MARGIN_X - 110
        of_y = 28
        self._open_folder_btn.rect = pygame.Rect(of_x, of_y, 110, 30)
        self._open_folder_btn.draw(self.screen)

        font = _get_font(CONTENT_FONT_SIZE)
        small_font = _get_font(CONTENT_FONT_SIZE - 4)

        # Snapshot current count (thread may be appending)
        replay_count = len(self._replays)

        if replay_count == 0:
            if self._loading:
                msg = font.render("Loading replays...", True, (140, 140, 160))
            else:
                msg = font.render("No replays found.", True, (140, 140, 160))
            self.screen.blit(msg, (self.width // 2 - msg.get_width() // 2,
                                   self.height // 2))
            self._card_buttons = []
        else:
            visible = self._visible_rows()
            card_w = self.width - _CARD_MARGIN_X * 2
            btn_w = 65
            btn_h = 24

            # Rebuild card buttons list to match visible cards
            new_buttons: list[tuple[Button, Button]] = []

            for vi in range(visible):
                idx = vi + self._scroll
                if idx >= replay_count:
                    break
                r = self._replays[idx]
                cy = self._card_y(vi)

                # Card background and border
                card_rect = pygame.Rect(_CARD_MARGIN_X, cy, card_w, _CARD_HEIGHT)
                is_selected = idx == self._selected
                bg = _CARD_SELECTED_BG if is_selected else _CARD_BG
                border = _CARD_SELECTED_BORDER if is_selected else _CARD_BORDER_COLOR
                pygame.draw.rect(self.screen, bg, card_rect, border_radius=6)
                pygame.draw.rect(self.screen, border, card_rect, 1, border_radius=6)

                # Left side: relative time + formatted datetime
                ts = r.get("timestamp", "")
                rel = _relative_time(ts)
                fmt = _format_datetime(ts)
                text_x = _CARD_MARGIN_X + 12
                text_y = cy + 10

                rel_surf = font.render(rel, True, (200, 200, 220))
                self.screen.blit(rel_surf, (text_x, text_y))

                fmt_surf = small_font.render(fmt, True, (120, 120, 145))
                self.screen.blit(fmt_surf, (text_x + rel_surf.get_width() + 10,
                                            text_y + 2))

                # Second row: matchup, duration, winner
                row2_y = cy + 36
                config = r.get("config", {})
                human_teams = r.get("human_teams", [])

                t1_name = _team_name(1, config, human_teams)
                t2_name = _team_name(2, config, human_teams)
                matchup = f"{t1_name} vs {t2_name}"

                dur_s = r.get("duration_seconds", 0)
                dm, ds = divmod(int(dur_s), 60)

                w = r.get("winner", 0)
                if w == -1:
                    outcome = "Draw"
                elif w in (1, 2):
                    outcome = f"{_team_name(w, config, human_teams)} won"
                else:
                    outcome = ""

                map_s = f"{r.get('map_width', 0)}x{r.get('map_height', 0)}"
                size_kb = f"{r.get('file_size', 0) / 1024:.0f} KB"

                parts = [matchup, f"{dm}:{ds:02d}"]
                if outcome:
                    parts.append(outcome)
                parts.extend([map_s, size_kb])
                detail = "  |  ".join(parts)

                detail_surf = small_font.render(detail, True, (140, 140, 165))
                self.screen.blit(detail_surf, (text_x, row2_y))

                # Right side: Watch and Delete buttons
                btn_x_watch = _CARD_MARGIN_X + card_w - btn_w * 2 - 22
                btn_x_delete = _CARD_MARGIN_X + card_w - btn_w - 12
                btn_y = cy + (_CARD_HEIGHT - btn_h) // 2

                # Reuse or create buttons
                if vi < len(self._card_buttons):
                    wb, db = self._card_buttons[vi]
                    wb.rect = pygame.Rect(btn_x_watch, btn_y, btn_w, btn_h)
                    db.rect = pygame.Rect(btn_x_delete, btn_y, btn_w, btn_h)
                else:
                    wb = Button(btn_x_watch, btn_y, btn_w, btn_h, "Watch",
                                font_size=18)
                    db = Button(btn_x_delete, btn_y, btn_w, btn_h, "Delete",
                                font_size=18)

                wb.draw(self.screen)
                db.draw(self.screen)
                new_buttons.append((wb, db))

            self._card_buttons = new_buttons

            # Loading indicator below last visible card
            if self._loading:
                last_vi = min(visible, replay_count - self._scroll)
                if last_vi > 0:
                    loading_y = self._card_y(last_vi) + 4
                    loading_surf = small_font.render(
                        "Loading...", True, (100, 100, 130))
                    self.screen.blit(loading_surf, (
                        self.width // 2 - loading_surf.get_width() // 2,
                        loading_y))

            # Scrollbar
            geom = self._scrollbar_geometry()
            if geom is not None:
                track_rect, thumb_rect = geom
                pygame.draw.rect(self.screen, _SCROLLBAR_TRACK_COLOR,
                                 track_rect, border_radius=4)
                mx, my = pygame.mouse.get_pos()
                hovering = thumb_rect.collidepoint(mx, my) or self._sb_dragging
                thumb_color = _SCROLLBAR_THUMB_HOVER if hovering else _SCROLLBAR_THUMB_COLOR
                pygame.draw.rect(self.screen, thumb_color,
                                 thumb_rect, border_radius=4)

        pygame.display.flip()
