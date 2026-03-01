"""Create-lobby screen — mode toggle, AI pickers, map settings, Start."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT, DD_WIDTH,
)
from ui.widgets import Button, BackButton, Dropdown, Slider, ToggleGroup


class CreateLobbyScreen(BaseScreen):
    """Configure game mode, AIs, and map settings, then start."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 ai_choices: list[tuple[str, str]]):
        super().__init__(screen, clock)
        self._ai_choices = ai_choices

        cx = self.width // 2

        # Mode toggle
        self._mode = ToggleGroup(
            cx - 215, 80,
            [
                ("human_vs_ai", "Human vs AI"),
                ("ai_vs_human", "AI vs Human"),
                ("ai_vs_ai", "AI vs AI"),
            ],
            selected_index=0,
            btn_w=140,
            btn_h=32,
        )

        # AI dropdowns
        dd_x = cx - DD_WIDTH // 2
        self._dd_t1 = Dropdown(dd_x, 150, DD_WIDTH, ai_choices, 0)
        self._dd_t2 = Dropdown(dd_x, 200, DD_WIDTH, ai_choices, 0)

        # Map sliders
        sl_x = cx - 110
        self._sl_width = Slider(sl_x, 270, 220, "Map Width", 200, 1600, 800, 100)
        self._sl_height = Slider(sl_x, 320, 220, "Map Height", 200, 1200, 600, 100)
        self._sl_obs_min = Slider(sl_x, 370, 220, "Obstacles Min", 0, 20, 4, 1)
        self._sl_obs_max = Slider(sl_x, 420, 220, "Obstacles Max", 0, 20, 8, 1)

        # Start button
        self._start_btn = Button(
            cx - BTN_WIDTH // 2, self.height - 80,
            BTN_WIDTH, BTN_HEIGHT, "Start Game",
        )
        self._back = BackButton()
        self._update_visibility()

    def _update_visibility(self):
        mode = self._mode.value
        self._dd_t1.visible = mode in ("ai_vs_human", "ai_vs_ai")
        self._dd_t2.visible = mode in ("human_vs_ai", "ai_vs_ai")

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if self._back.handle_event(event):
                    return ScreenResult("main_menu")

                if self._mode.handle_event(event):
                    self._update_visibility()
                    # Close any open dropdown when mode changes
                    self._dd_t1.open = False
                    self._dd_t2.open = False

                # Handle dropdowns (order matters — open one closes on outside click)
                self._dd_t1.handle_event(event)
                self._dd_t2.handle_event(event)

                self._sl_width.handle_event(event)
                self._sl_height.handle_event(event)
                self._sl_obs_min.handle_event(event)
                self._sl_obs_max.handle_event(event)

                # Enforce obs_min <= obs_max
                if self._sl_obs_min.value > self._sl_obs_max.value:
                    self._sl_obs_max.value = self._sl_obs_min.value
                if self._sl_obs_max.value < self._sl_obs_min.value:
                    self._sl_obs_min.value = self._sl_obs_max.value

                if self._start_btn.handle_event(event):
                    return self._build_result()

            self._draw()
            self.clock.tick(60)

    def _build_result(self) -> ScreenResult:
        mode = self._mode.value
        team_ai: dict[int, str] = {}

        if mode == "human_vs_ai":
            team_ai[2] = self._dd_t2.value
        elif mode == "ai_vs_human":
            team_ai[1] = self._dd_t1.value
        elif mode == "ai_vs_ai":
            team_ai[1] = self._dd_t1.value
            team_ai[2] = self._dd_t2.value

        return ScreenResult("game", data={
            "team_ai_ids": team_ai,
            "width": self._sl_width.value,
            "height": self._sl_height.value,
            "obstacle_count": (self._sl_obs_min.value, self._sl_obs_max.value),
        })

    def _draw(self):
        self.screen.fill(MENU_BG)
        self._back.draw(self.screen)

        # Title
        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        title = font_h.render("Create Lobby", True, CONTENT_TEXT)
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, 30))

        self._mode.draw(self.screen)

        # Labels for dropdowns
        font = pygame.font.SysFont(None, CONTENT_FONT_SIZE)
        if self._dd_t1.visible:
            lbl1 = font.render("Team 1 AI:", True, CONTENT_TEXT)
            self.screen.blit(lbl1, (self._dd_t1.x - lbl1.get_width() - 10,
                                    self._dd_t1.y + 6))
        if self._dd_t2.visible:
            lbl2 = font.render("Team 2 AI:", True, CONTENT_TEXT)
            self.screen.blit(lbl2, (self._dd_t2.x - lbl2.get_width() - 10,
                                    self._dd_t2.y + 6))

        self._sl_width.draw(self.screen)
        self._sl_height.draw(self.screen)
        self._sl_obs_min.draw(self.screen)
        self._sl_obs_max.draw(self.screen)
        self._start_btn.draw(self.screen)

        # Draw dropdowns last so their open lists render on top
        self._dd_t1.draw(self.screen)
        self._dd_t2.draw(self.screen)

        pygame.display.flip()
