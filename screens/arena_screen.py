"""AI Arena screen — leaderboard, tournament controls, scrollable game log."""
from __future__ import annotations

import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT,
)
from ui.widgets import Button, BackButton, Slider, _get_font
from systems.arena import EloTracker, ArenaRunner, TournamentProgress, MatchResult

# Colors
_HEADER_COLOR = (220, 220, 240)
_ROW_BG_EVEN = (22, 22, 34)
_ROW_BG_ODD = (28, 28, 42)
_ROW_HOVER = (38, 38, 55)
_GOLD = (255, 215, 80)
_SILVER = (200, 200, 210)
_BRONZE = (205, 150, 80)
_TEXT_DIM = (140, 140, 160)
_PROGRESS_BG = (40, 40, 55)
_PROGRESS_FILL = (80, 140, 255)
_STATUS_OK = (80, 255, 120)
_STATUS_ERR = (255, 100, 100)
_WIN_COLOR = (80, 255, 120)
_LOSS_COLOR = (255, 100, 100)
_DRAW_COLOR = (200, 200, 200)
_ELO_UP = (80, 255, 120)
_ELO_DOWN = (255, 100, 100)
_ONGOING_COLOR = (255, 200, 60)
_LINK_COLOR = (100, 170, 255)

# Layout constants
_TABLE_X = 30
_TABLE_W = 740
_LB_ROW_H = 22
_LB_HEADER_Y = 45
_LOG_ROW_H = 20
_LOG_FONT = 14


class _LogEntry:
    """Processed match result for display in the game log."""
    __slots__ = ("ai1_name", "ai2_name", "result_text", "result_color",
                 "length_text", "avg_step_text", "elo_text", "elo_color_a",
                 "elo_color_b", "finished", "replay_path")

    def __init__(self, ai1_name: str, ai2_name: str,
                 result_text: str, result_color: tuple,
                 length_text: str, avg_step_text: str,
                 elo_text: str, elo_color_a: tuple, elo_color_b: tuple,
                 finished: bool, replay_path: str):
        self.ai1_name = ai1_name
        self.ai2_name = ai2_name
        self.result_text = result_text
        self.result_color = result_color
        self.length_text = length_text
        self.avg_step_text = avg_step_text
        self.elo_text = elo_text
        self.elo_color_a = elo_color_a
        self.elo_color_b = elo_color_b
        self.finished = finished
        self.replay_path = replay_path


class ArenaScreen(BaseScreen):
    """AI Arena — run tournaments and view Elo leaderboard."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 ai_choices: list[tuple[str, str]]):
        super().__init__(screen, clock)

        # Filter out Crash Test AI
        self._ai_choices = [(aid, name) for aid, name in ai_choices
                            if aid != "crash_test"]
        self._ai_names: dict[str, str] = {aid: name for aid, name in self._ai_choices}

        # Elo tracker
        self._elo = EloTracker()
        self._elo.load()
        for aid, _ in self._ai_choices:
            self._elo.ensure(aid)

        # Arena runner
        self._runner = ArenaRunner()
        self._progress: TournamentProgress | None = None
        self._status_text: str = ""
        self._status_color: tuple[int, int, int] = _TEXT_DIM

        # Game log
        self._match_log: list[_LogEntry] = []
        self._log_scroll: int = 0  # index of first visible row
        self._last_seen_count: int = 0
        self._pre_ratings: dict[str, float] = {}  # snapshot before tournament
        self._watch_rects: list[tuple[pygame.Rect, str]] = []  # (rect, replay_path)

        # UI elements
        cx = self.width // 2

        self._back_btn = BackButton()

        # Settings sliders
        self._rounds_slider = Slider(cx - 110, 0, 220, "Rounds per matchup",
                                     1, 10, 1, 1)
        self._workers_slider = Slider(cx - 110, 0, 220, "Worker processes",
                                      1, 8, 4, 1)

        # Buttons — positioned at bottom
        btn_y = self.height - 62
        btn_w = 160
        self._start_btn = Button(cx - btn_w - 10, btn_y, btn_w, BTN_HEIGHT,
                                 "Start Tournament")
        self._reset_btn = Button(cx + 10, btn_y, btn_w, BTN_HEIGHT,
                                 "Reset Ratings")

    def run(self) -> ScreenResult:
        while True:
            self.clock.tick(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if self._runner.running:
                        self._runner.cancel()
                        self._status_text = "Tournament cancelled."
                        self._status_color = _STATUS_ERR
                        self._start_btn.label = "Start Tournament"
                    else:
                        return ScreenResult("main_menu")

                if self._back_btn.handle_event(event):
                    if self._runner.running:
                        self._runner.cancel()
                    return ScreenResult("main_menu")

                if not self._runner.running:
                    self._rounds_slider.handle_event(event)
                    self._workers_slider.handle_event(event)

                if self._start_btn.handle_event(event):
                    if self._runner.running:
                        self._runner.cancel()
                        self._status_text = "Tournament cancelled."
                        self._status_color = _STATUS_ERR
                        self._start_btn.label = "Start Tournament"
                    else:
                        self._start_tournament()

                if self._reset_btn.handle_event(event):
                    if not self._runner.running:
                        self._elo.reset()
                        for aid, _ in self._ai_choices:
                            self._elo.ensure(aid)
                        self._match_log.clear()
                        self._log_scroll = 0
                        self._status_text = "Ratings reset to 1000."
                        self._status_color = _STATUS_OK

                # Scroll the game log
                if event.type == pygame.MOUSEWHEEL:
                    self._log_scroll -= event.y
                    self._clamp_scroll()

                # Click on "Watch" replay links
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    for rect, path in self._watch_rects:
                        if rect.collidepoint(event.pos) and path:
                            if self._runner.running:
                                self._runner.cancel()
                            return ScreenResult("replay_playback",
                                                data={"filepath": path})

            # Poll tournament progress
            if self._runner.running:
                self._progress = self._runner.poll()
                self._process_new_results()
                if self._progress.done:
                    self._on_tournament_complete()

            self._draw()

    def _start_tournament(self) -> None:
        if len(self._ai_choices) < 2:
            self._status_text = "Need at least 2 AIs for a tournament."
            self._status_color = _STATUS_ERR
            return

        # Snapshot ratings before tournament for delta display
        self._pre_ratings = {
            ai_id: rec.rating for ai_id, rec in self._elo.records.items()
        }

        self._match_log.clear()
        self._log_scroll = 0
        self._last_seen_count = 0

        ai_ids = [aid for aid, _ in self._ai_choices]
        self._runner.start(
            ai_ids=ai_ids,
            rounds=self._rounds_slider.value,
            workers=self._workers_slider.value,
        )
        self._start_btn.label = "Cancel"
        self._status_text = "Tournament in progress..."
        self._status_color = _PROGRESS_FILL
        self._progress = TournamentProgress(total=0)

    def _process_new_results(self) -> None:
        """Convert newly completed MatchResults into log entries."""
        if self._progress is None:
            return

        results = self._progress.results
        while self._last_seen_count < len(results):
            mr = results[self._last_seen_count]
            self._last_seen_count += 1
            self._match_log.append(self._make_log_entry(mr))

            # Auto-scroll to bottom when new results arrive
            max_visible = self._log_visible_rows()
            if len(self._match_log) > max_visible:
                self._log_scroll = len(self._match_log) - max_visible

    def _make_log_entry(self, mr: MatchResult) -> _LogEntry:
        ai1_name = self._ai_names.get(mr.ai1_id, mr.ai1_id)
        ai2_name = self._ai_names.get(mr.ai2_id, mr.ai2_id)

        # Result
        if mr.winner == 0:
            result_text = "Error"
            result_color = _STATUS_ERR
        elif mr.winner == 1:
            result_text = f"{ai1_name} wins"
            result_color = _WIN_COLOR
        elif mr.winner == 2:
            result_text = f"{ai2_name} wins"
            result_color = _WIN_COLOR
        else:
            result_text = "Draw"
            result_color = _DRAW_COLOR

        # Game length
        seconds = mr.ticks / 60.0
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        length_text = f"{mins}:{secs:02d}"

        # Avg step
        avg_step_text = f"{mr.avg_step_ms:.1f}ms" if mr.avg_step_ms > 0 else "-"

        # Elo delta
        elo_color_a = _TEXT_DIM
        elo_color_b = _TEXT_DIM
        if mr.winner != 0:
            da, db = self._elo.compute_delta(
                mr.ai1_id, mr.ai2_id, mr.winner,
                ratings_snapshot=self._pre_ratings,
            )
            sign_a = "+" if da >= 0 else ""
            sign_b = "+" if db >= 0 else ""
            elo_text = f"{sign_a}{da:.0f} / {sign_b}{db:.0f}"
            elo_color_a = _ELO_UP if da >= 0 else _ELO_DOWN
            elo_color_b = _ELO_UP if db >= 0 else _ELO_DOWN
        else:
            elo_text = "-"

        return _LogEntry(
            ai1_name=ai1_name,
            ai2_name=ai2_name,
            result_text=result_text,
            result_color=result_color,
            length_text=length_text,
            avg_step_text=avg_step_text,
            elo_text=elo_text,
            elo_color_a=elo_color_a,
            elo_color_b=elo_color_b,
            finished=True,
            replay_path=mr.replay_path,
        )

    def _on_tournament_complete(self) -> None:
        """Process results and update Elo."""
        if self._progress is None:
            return

        errors = 0
        for result in self._progress.results:
            if result.winner == 0:
                errors += 1
                continue
            self._elo.update(result.ai1_id, result.ai2_id, result.winner)

        self._elo.save()
        self._start_btn.label = "Start Tournament"

        n = self._progress.completed
        err_str = f" ({errors} errors)" if errors else ""
        self._status_text = f"Tournament complete — {n} games played{err_str}."
        self._status_color = _STATUS_OK

    # -- layout helpers --------------------------------------------------------

    def _lb_bottom_y(self) -> int:
        """Y coordinate after the last leaderboard row."""
        n_rows = len(self._elo.get_leaderboard())
        return _LB_HEADER_Y + _LB_ROW_H + n_rows * _LB_ROW_H + 4

    def _log_top_y(self) -> int:
        """Y coordinate where the game log area starts."""
        return self._lb_bottom_y() + 8

    def _log_area_bottom(self) -> int:
        """Y coordinate where the log area ends (above buttons)."""
        return self.height - 72

    def _log_visible_rows(self) -> int:
        available = self._log_area_bottom() - self._log_top_y() - _LOG_ROW_H
        return max(1, available // _LOG_ROW_H)

    def _clamp_scroll(self) -> None:
        max_scroll = max(0, len(self._match_log) - self._log_visible_rows())
        self._log_scroll = max(0, min(self._log_scroll, max_scroll))

    # -- drawing ---------------------------------------------------------------

    def _draw(self) -> None:
        self.screen.fill(MENU_BG)

        # Title
        title_font = _get_font(HEADING_FONT_SIZE)
        title = title_font.render("AI Arena", True, _HEADER_COLOR)
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, 14))

        # Leaderboard
        self._draw_leaderboard()

        # Middle section: game log or settings
        if self._match_log or self._runner.running:
            self._draw_game_log()
        else:
            self._draw_settings()

        # Buttons
        self._start_btn.draw(self.screen)
        self._reset_btn.draw(self.screen)
        self._back_btn.draw(self.screen)

        # Status line
        if self._status_text:
            font = _get_font(CONTENT_FONT_SIZE)
            status = font.render(self._status_text, True, self._status_color)
            self.screen.blit(status, (self.width // 2 - status.get_width() // 2,
                                      self.height - 26))

        pygame.display.flip()

    def _draw_leaderboard(self) -> None:
        leaderboard = self._elo.get_leaderboard()
        if not leaderboard:
            return

        font = _get_font(CONTENT_FONT_SIZE)
        table_x = _TABLE_X
        table_w = _TABLE_W
        row_h = _LB_ROW_H
        header_y = _LB_HEADER_Y

        # Column positions
        col_rank = 0
        col_name = 30
        col_elo = table_w - 280
        col_w = table_w - 210
        col_l = table_w - 160
        col_d = table_w - 110
        col_games = table_w - 50

        # Header
        for cx, label in [(col_rank, "#"), (col_name, "AI Name"), (col_elo, "Elo"),
                          (col_w, "W"), (col_l, "L"), (col_d, "D"),
                          (col_games, "Games")]:
            surf = font.render(label, True, _TEXT_DIM)
            self.screen.blit(surf, (table_x + cx, header_y))

        pygame.draw.line(self.screen, (50, 50, 70),
                         (table_x, header_y + row_h - 2),
                         (table_x + table_w, header_y + row_h - 2), 1)

        mx, my = pygame.mouse.get_pos()
        for i, (ai_id, record) in enumerate(leaderboard):
            y = header_y + row_h + i * row_h
            bg = _ROW_BG_EVEN if i % 2 == 0 else _ROW_BG_ODD
            row_rect = pygame.Rect(table_x, y, table_w, row_h)
            if row_rect.collidepoint(mx, my):
                bg = _ROW_HOVER
            pygame.draw.rect(self.screen, bg, row_rect)

            rank = i + 1
            if rank == 1:
                rank_color = _GOLD
            elif rank == 2:
                rank_color = _SILVER
            elif rank == 3:
                rank_color = _BRONZE
            else:
                rank_color = CONTENT_TEXT

            name = self._ai_names.get(ai_id, ai_id)
            for cx, text, color in [
                (col_rank, str(rank), rank_color),
                (col_name, name, CONTENT_TEXT),
                (col_elo, f"{record.rating:.0f}", _HEADER_COLOR),
                (col_w, str(record.wins), _STATUS_OK),
                (col_l, str(record.losses), _STATUS_ERR),
                (col_d, str(record.draws), _TEXT_DIM),
                (col_games, str(record.games), _TEXT_DIM),
            ]:
                surf = font.render(text, True, color)
                self.screen.blit(surf, (table_x + cx,
                                        y + row_h // 2 - surf.get_height() // 2))

    def _draw_settings(self) -> None:
        """Draw sliders in the middle area when no tournament has run."""
        log_top = self._log_top_y()
        cx = self.width // 2
        self._rounds_slider.x = cx - 110
        self._rounds_slider.y = log_top + 20
        self._workers_slider.x = cx - 110
        self._workers_slider.y = log_top + 70
        self._rounds_slider.draw(self.screen)
        self._workers_slider.draw(self.screen)

    def _draw_game_log(self) -> None:
        """Draw progress bar + scrollable game log table."""
        font = _get_font(_LOG_FONT)
        table_x = _TABLE_X
        table_w = _TABLE_W
        row_h = _LOG_ROW_H
        log_top = self._log_top_y()
        log_bottom = self._log_area_bottom()
        self._watch_rects.clear()

        # -- Progress bar (thin, at top of log area) --
        if self._runner.running and self._progress:
            bar_w = table_w
            bar_h = 10
            bar_x = table_x
            bar_y = log_top

            pygame.draw.rect(self.screen, _PROGRESS_BG,
                             (bar_x, bar_y, bar_w, bar_h), border_radius=3)
            total = max(self._progress.total, 1)
            frac = self._progress.completed / total
            fill_w = int(frac * bar_w)
            if fill_w > 0:
                pygame.draw.rect(self.screen, _PROGRESS_FILL,
                                 (bar_x, bar_y, fill_w, bar_h), border_radius=3)
            pygame.draw.rect(self.screen, (60, 60, 80),
                             (bar_x, bar_y, bar_w, bar_h), 1, border_radius=3)

            pct = int(frac * 100)
            ptext = font.render(
                f"{self._progress.completed}/{self._progress.total} ({pct}%)",
                True, _HEADER_COLOR)
            self.screen.blit(ptext, (bar_x + bar_w // 2 - ptext.get_width() // 2,
                                     bar_y + bar_h + 2))
            header_y = bar_y + bar_h + 18
        elif self._match_log:
            # Settings sliders above the log when tournament is done
            cx = self.width // 2
            self._rounds_slider.x = cx - 110
            self._rounds_slider.y = log_top
            self._workers_slider.x = cx + 10
            self._workers_slider.y = log_top
            self._rounds_slider.draw(self.screen)
            self._workers_slider.draw(self.screen)
            header_y = log_top + 48
        else:
            header_y = log_top

        # -- Column positions --
        col_matchup = 0
        col_result = 220
        col_length = 340
        col_step = 400
        col_elo = 470
        col_status = 580
        col_watch = 660

        # -- Header row --
        for cx, label in [
            (col_matchup, "Matchup"),
            (col_result, "Result"),
            (col_length, "Length"),
            (col_step, "Avg Step"),
            (col_elo, "Elo +/-"),
            (col_status, "Status"),
            (col_watch, "Replay"),
        ]:
            surf = font.render(label, True, _TEXT_DIM)
            self.screen.blit(surf, (table_x + cx, header_y))

        pygame.draw.line(self.screen, (50, 50, 70),
                         (table_x, header_y + row_h - 2),
                         (table_x + table_w, header_y + row_h - 2), 1)

        # -- Clip region for rows --
        rows_top = header_y + row_h
        rows_bottom = log_bottom
        visible_count = max(1, (rows_bottom - rows_top) // row_h)
        self._clamp_scroll()

        old_clip = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(table_x, rows_top,
                                         table_w, rows_bottom - rows_top))

        mx, my = pygame.mouse.get_pos()

        # -- Completed game rows --
        for i in range(visible_count):
            idx = self._log_scroll + i
            if idx >= len(self._match_log):
                break

            entry = self._match_log[idx]
            y = rows_top + i * row_h

            bg = _ROW_BG_EVEN if idx % 2 == 0 else _ROW_BG_ODD
            row_rect = pygame.Rect(table_x, y, table_w, row_h)
            if row_rect.collidepoint(mx, my):
                bg = _ROW_HOVER
            pygame.draw.rect(self.screen, bg, row_rect)

            # Matchup
            matchup = f"{entry.ai1_name} vs {entry.ai2_name}"
            # Truncate if too long
            if font.size(matchup)[0] > 210:
                while font.size(matchup + "..")[0] > 210 and len(matchup) > 3:
                    matchup = matchup[:-1]
                matchup += ".."
            surf = font.render(matchup, True, CONTENT_TEXT)
            self.screen.blit(surf, (table_x + col_matchup,
                                    y + row_h // 2 - surf.get_height() // 2))

            # Result
            # Truncate result text if too long
            r_text = entry.result_text
            if font.size(r_text)[0] > 110:
                while font.size(r_text + "..")[0] > 110 and len(r_text) > 3:
                    r_text = r_text[:-1]
                r_text += ".."
            surf = font.render(r_text, True, entry.result_color)
            self.screen.blit(surf, (table_x + col_result,
                                    y + row_h // 2 - surf.get_height() // 2))

            # Length
            surf = font.render(entry.length_text, True, CONTENT_TEXT)
            self.screen.blit(surf, (table_x + col_length,
                                    y + row_h // 2 - surf.get_height() // 2))

            # Avg step
            surf = font.render(entry.avg_step_text, True, CONTENT_TEXT)
            self.screen.blit(surf, (table_x + col_step,
                                    y + row_h // 2 - surf.get_height() // 2))

            # Elo +/-  (color based on the first AI's delta direction)
            surf = font.render(entry.elo_text, True, entry.elo_color_a)
            self.screen.blit(surf, (table_x + col_elo,
                                    y + row_h // 2 - surf.get_height() // 2))

            # Status
            if entry.finished:
                status_text = "Done"
                status_color = _STATUS_OK
            else:
                status_text = "Ongoing"
                status_color = _ONGOING_COLOR
            surf = font.render(status_text, True, status_color)
            self.screen.blit(surf, (table_x + col_status,
                                    y + row_h // 2 - surf.get_height() // 2))

            # Watch replay link
            if entry.replay_path and not self._runner.running:
                watch_surf = font.render("Watch", True, _LINK_COLOR)
                wx = table_x + col_watch
                wy = y + row_h // 2 - watch_surf.get_height() // 2
                self.screen.blit(watch_surf, (wx, wy))
                # Underline on hover
                watch_rect = pygame.Rect(wx, wy, watch_surf.get_width(),
                                         watch_surf.get_height())
                if watch_rect.collidepoint(mx, my):
                    pygame.draw.line(self.screen, _LINK_COLOR,
                                     (wx, wy + watch_surf.get_height()),
                                     (wx + watch_surf.get_width(),
                                      wy + watch_surf.get_height()), 1)
                self._watch_rects.append((watch_rect, entry.replay_path))

        self.screen.set_clip(old_clip)

        # -- Scroll indicator --
        total_rows = len(self._match_log)
        if total_rows > visible_count:
            track_h = rows_bottom - rows_top
            thumb_h = max(12, int(track_h * visible_count / total_rows))
            thumb_y = rows_top + int(
                (track_h - thumb_h) * self._log_scroll /
                max(1, total_rows - visible_count)
            )
            thumb_x = table_x + table_w - 4
            pygame.draw.rect(self.screen, (60, 60, 80),
                             (thumb_x, rows_top, 4, track_h), border_radius=2)
            pygame.draw.rect(self.screen, (120, 120, 150),
                             (thumb_x, thumb_y, 4, thumb_h), border_radius=2)
