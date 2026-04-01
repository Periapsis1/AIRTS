"""Main menu screen with title, background animation, and navigation buttons."""
from __future__ import annotations
import random
import math
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, TITLE_COLOR, TITLE_SHADOW_COLOR, SUBTITLE_COLOR,
    TITLE_FONT_SIZE, SUBTITLE_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT,
    BG_DOT_RADIUS, BG_DOT_SPEED, BG_DOT_COUNT,
)
from ui.widgets import Button
from config.settings import TEAM1_COLOR, TEAM2_COLOR


class _BackgroundUnit:
    """Lightweight wandering dot for the menu background."""

    def __init__(self, width: int, height: int, color: tuple[int, int, int]):
        self.x = random.uniform(0, width)
        self.y = random.uniform(0, height)
        self.color = color
        self._width = width
        self._height = height
        self._tx = random.uniform(0, width)
        self._ty = random.uniform(0, height)

    def update(self, dt: float):
        dx = self._tx - self.x
        dy = self._ty - self.y
        dist = math.hypot(dx, dy)
        if dist < 5:
            self._tx = random.uniform(0, self._width)
            self._ty = random.uniform(0, self._height)
        else:
            speed = BG_DOT_SPEED
            self.x += dx / dist * speed * dt
            self.y += dy / dist * speed * dt

    def draw(self, surface: pygame.Surface):
        alpha_surf = pygame.Surface((BG_DOT_RADIUS * 2, BG_DOT_RADIUS * 2), pygame.SRCALPHA)
        r, g, b = self.color
        pygame.draw.circle(alpha_surf, (r, g, b, 100),
                           (BG_DOT_RADIUS, BG_DOT_RADIUS), BG_DOT_RADIUS)
        surface.blit(alpha_surf, (int(self.x) - BG_DOT_RADIUS,
                                  int(self.y) - BG_DOT_RADIUS))


class MainMenuScreen(BaseScreen):
    """Title screen with background animation and 6 navigation buttons."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)

        # Background units — half blue, half red
        self._dots: list[_BackgroundUnit] = []
        for i in range(BG_DOT_COUNT):
            color = TEAM1_COLOR if i < BG_DOT_COUNT // 2 else TEAM2_COLOR
            self._dots.append(_BackgroundUnit(self.width, self.height, color))

        # Buttons — vertically stacked in center
        labels = [
            ("Create Lobby", "create_lobby"),
            ("Multiplayer", "multiplayer_lobby"),
            ("AI Arena", "arena"),
            ("Replays", "replays"),
            ("Learn to Play", "guides"),
            ("Options", "options"),
            ("Exit", "quit"),
        ]
        start_y = self.height // 2 - 20
        spacing = BTN_HEIGHT + 10
        self._buttons: list[tuple[Button, str]] = []
        for i, (label, target) in enumerate(labels):
            bx = self.width // 2 - BTN_WIDTH // 2
            by = start_y + i * spacing
            enabled = True
            btn = Button(bx, by, BTN_WIDTH, BTN_HEIGHT, label, enabled=enabled)
            self._buttons.append((btn, target))

    def run(self) -> ScreenResult:
        from systems import music
        while True:
            dt = self.clock.tick(60) / 1000.0
            music.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return ScreenResult("quit")

                for btn, target in self._buttons:
                    if btn.handle_event(event):
                        return ScreenResult(target)

            for dot in self._dots:
                dot.update(dt)

            self._draw()

    def _draw(self):
        self.screen.fill(MENU_BG)

        # Background dots
        for dot in self._dots:
            dot.draw(self.screen)

        # Title with shadow
        font_title = pygame.font.SysFont(None, TITLE_FONT_SIZE)
        title_shadow = font_title.render("AIRTS", True, TITLE_SHADOW_COLOR)
        title_surf = font_title.render("AIRTS", True, TITLE_COLOR)
        tx = self.width // 2 - title_surf.get_width() // 2
        ty = 100
        self.screen.blit(title_shadow, (tx + 3, ty + 3))
        self.screen.blit(title_surf, (tx, ty))

        # Subtitle
        font_sub = pygame.font.SysFont(None, SUBTITLE_FONT_SIZE)
        sub = font_sub.render("AI Real-Time Strategy", True, SUBTITLE_COLOR)
        sx = self.width // 2 - sub.get_width() // 2
        sy = ty + title_surf.get_height() + 8
        self.screen.blit(sub, (sx, sy))

        # Buttons
        for btn, _ in self._buttons:
            btn.draw(self.screen)

        pygame.display.flip()
