"""Options screen — volume control and display mode settings."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import MENU_BG, TITLE_COLOR, TITLE_FONT_SIZE, CONTENT_TEXT
from ui.widgets import Slider, BackButton, ToggleGroup, _get_font
import config.audio as audio
import config.display as display_config
from systems import music


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

        self._music_slider = Slider(
            sl_x, sl_y + 60, sl_w, "Music Volume",
            min_val=0, max_val=100,
            value=int(music.get_volume() * 100),
            step=5,
        )

        # Display mode toggle
        mode_idx = 0 if display_config.display_mode == "windowed_fullscreen" else 1
        self._display_toggle = ToggleGroup(
            self.width // 2 - 145, self.height // 2 + 90,
            [
                ("windowed_fullscreen", "Borderless"),
                ("windowed", "Windowed"),
            ],
            selected_index=mode_idx,
            btn_w=140,
            btn_h=32,
        )

        # Color mode toggle
        color_idx = 0 if display_config.color_mode == "player" else 1
        self._color_toggle = ToggleGroup(
            self.width // 2 - 145, self.height // 2 + 170,
            [
                ("player", "Player Colors"),
                ("team", "Team Colors"),
            ],
            selected_index=color_idx,
            btn_w=140,
            btn_h=32,
        )

        # Selection mode toggle
        sel_idx = 0 if display_config.selection_mode == "rectangle" else 1
        self._selection_toggle = ToggleGroup(
            self.width // 2 - 145, self.height // 2 + 250,
            [
                ("rectangle", "Rectangle"),
                ("circle", "Circle"),
            ],
            selected_index=sel_idx,
            btn_w=140,
            btn_h=32,
        )

        # Movement smoothing toggle
        ms_idx = 0 if display_config.movement_smoothing else 1
        self._smoothing_toggle = ToggleGroup(
            self.width // 2 - 145, self.height // 2 + 330,
            [
                ("on", "Enabled"),
                ("off", "Disabled"),
            ],
            selected_index=ms_idx,
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
        self._music_slider.x = sl_x
        self._music_slider.y = self.height // 2
        self._music_slider.w = sl_w
        self._display_toggle.x = self.width // 2 - 145
        self._display_toggle.y = self.height // 2 + 90
        self._color_toggle.x = self.width // 2 - 145
        self._color_toggle.y = self.height // 2 + 170
        self._selection_toggle.x = self.width // 2 - 145
        self._selection_toggle.y = self.height // 2 + 250
        self._smoothing_toggle.x = self.width // 2 - 145
        self._smoothing_toggle.y = self.height // 2 + 330

    def run(self) -> ScreenResult:
        while True:
            self.clock.tick(60)
            music.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return ScreenResult("main_menu")

                if self._back.handle_event(event):
                    return ScreenResult("main_menu")

                if self._volume_slider.handle_event(event):
                    audio.set_volume(self._volume_slider.value / 100.0)

                if self._music_slider.handle_event(event):
                    music.set_volume(self._music_slider.value / 100.0)

                if self._display_toggle.handle_event(event):
                    self._apply_display_mode()

                if self._color_toggle.handle_event(event):
                    display_config.set_color_mode(self._color_toggle.value)

                if self._selection_toggle.handle_event(event):
                    display_config.set_selection_mode(self._selection_toggle.value)

                if self._smoothing_toggle.handle_event(event):
                    display_config.set_movement_smoothing(
                        self._smoothing_toggle.value == "on")

            self._draw()

    def _draw(self):
        self.screen.fill(MENU_BG)

        # Title
        font_title = pygame.font.SysFont(None, TITLE_FONT_SIZE)
        title = font_title.render("Options", True, TITLE_COLOR)
        tx = self.width // 2 - title.get_width() // 2
        self.screen.blit(title, (tx, 80))

        # Labels
        label_font = _get_font(18)
        dm_label = label_font.render("Display Mode", True, CONTENT_TEXT)
        self.screen.blit(dm_label, (self.width // 2 - dm_label.get_width() // 2,
                                    self._display_toggle.y - 24))

        cm_label = label_font.render("Color Mode", True, CONTENT_TEXT)
        self.screen.blit(cm_label, (self.width // 2 - cm_label.get_width() // 2,
                                    self._color_toggle.y - 24))

        sm_label = label_font.render("Selection Mode", True, CONTENT_TEXT)
        self.screen.blit(sm_label, (self.width // 2 - sm_label.get_width() // 2,
                                    self._selection_toggle.y - 24))

        ms_label = label_font.render("Movement Smoothing", True, CONTENT_TEXT)
        self.screen.blit(ms_label, (self.width // 2 - ms_label.get_width() // 2,
                                    self._smoothing_toggle.y - 24))

        # Widgets
        self._back.draw(self.screen)
        self._volume_slider.draw(self.screen)
        self._music_slider.draw(self.screen)
        self._display_toggle.draw(self.screen)
        self._color_toggle.draw(self.screen)
        self._selection_toggle.draw(self.screen)
        self._smoothing_toggle.draw(self.screen)

        pygame.display.flip()
