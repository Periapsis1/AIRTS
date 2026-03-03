"""Options screen — volume control and other settings."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import MENU_BG, TITLE_COLOR, TITLE_FONT_SIZE
from ui.widgets import Slider, BackButton
import config.audio as audio


class OptionsScreen(BaseScreen):
    """Simple options screen with a master volume slider."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)

        self._back = BackButton()

        # Volume slider — centered horizontally
        sl_w = 300
        sl_x = self.width // 2 - sl_w // 2
        sl_y = self.height // 2 - 20
        self._volume_slider = Slider(
            sl_x, sl_y, sl_w, "Master Volume",
            min_val=0, max_val=100,
            value=int(audio.master_volume * 100),
            step=5,
        )

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

            self._draw()

    def _draw(self):
        self.screen.fill(MENU_BG)

        # Title
        font_title = pygame.font.SysFont(None, TITLE_FONT_SIZE)
        title = font_title.render("Options", True, TITLE_COLOR)
        tx = self.width // 2 - title.get_width() // 2
        self.screen.blit(title, (tx, 80))

        # Widgets
        self._back.draw(self.screen)
        self._volume_slider.draw(self.screen)

        pygame.display.flip()
