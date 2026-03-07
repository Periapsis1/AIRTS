"""Options screen — volume control and display mode settings."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import MENU_BG, TITLE_COLOR, TITLE_FONT_SIZE, CONTENT_TEXT
from ui.widgets import Slider, BackButton, ToggleGroup, _get_font
import config.audio as audio
import config.display as display_config


class OptionsScreen(BaseScreen):
    """Options screen with volume slider and display mode toggle."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)

        self._back = BackButton()

        # Volume slider — centered horizontally
        sl_w = 300
        sl_x = self.width // 2 - sl_w // 2
        sl_y = self.height // 2 - 60
        self._volume_slider = Slider(
            sl_x, sl_y, sl_w, "Master Volume",
            min_val=0, max_val=100,
            value=int(audio.master_volume * 100),
            step=5,
        )

        # Display mode toggle
        mode_idx = 0 if display_config.display_mode == "windowed_fullscreen" else 1
        self._display_toggle = ToggleGroup(
            self.width // 2 - 145, self.height // 2 + 30,
            [
                ("windowed_fullscreen", "Borderless"),
                ("windowed", "Windowed"),
            ],
            selected_index=mode_idx,
            btn_w=140,
            btn_h=32,
        )

    def _apply_display_mode(self):
        mode = self._display_toggle.value
        display_config.set_mode(mode)
        self.screen = display_config.create_display()
        self.width = self.screen.get_width()
        self.height = self.screen.get_height()
        # Reposition widgets
        sl_w = 300
        sl_x = self.width // 2 - sl_w // 2
        self._volume_slider.x = sl_x
        self._volume_slider.y = self.height // 2 - 60
        self._volume_slider.w = sl_w
        self._display_toggle.x = self.width // 2 - 145
        self._display_toggle.y = self.height // 2 + 30

    def run(self) -> ScreenResult:
        while True:
            self.clock.tick(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return ScreenResult("main_menu")

                if self._back.handle_event(event):
                    return ScreenResult("main_menu")

                if self._volume_slider.handle_event(event):
                    audio.set_volume(self._volume_slider.value / 100.0)

                if self._display_toggle.handle_event(event):
                    self._apply_display_mode()

            self._draw()

    def _draw(self):
        self.screen.fill(MENU_BG)

        # Title
        font_title = pygame.font.SysFont(None, TITLE_FONT_SIZE)
        title = font_title.render("Options", True, TITLE_COLOR)
        tx = self.width // 2 - title.get_width() // 2
        self.screen.blit(title, (tx, 80))

        # Display mode label
        label_font = _get_font(18)
        dm_label = label_font.render("Display Mode", True, CONTENT_TEXT)
        self.screen.blit(dm_label, (self.width // 2 - dm_label.get_width() // 2,
                                    self._display_toggle.y - 24))

        # Widgets
        self._back.draw(self.screen)
        self._volume_slider.draw(self.screen)
        self._display_toggle.draw(self.screen)

        pygame.display.flip()
