"""Crash notification screen — shown after an unhandled exception."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import MENU_BG, BTN_WIDTH, BTN_HEIGHT
from ui.widgets import Button, _get_font


class CrashNoticeScreen(BaseScreen):
    """Displays a crash message with the log file path."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 log_path: str, context: str = ""):
        super().__init__(screen, clock)
        self._log_path = log_path
        self._context = context
        bx = self.width // 2 - BTN_WIDTH // 2
        self._btn = Button(bx, self.height - 80, BTN_WIDTH, BTN_HEIGHT,
                           "Return to Menu")

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                        return ScreenResult("main_menu")
                if self._btn.handle_event(event):
                    return ScreenResult("main_menu")

            self._draw()
            self.clock.tick(60)

    def _draw(self):
        self.screen.fill(MENU_BG)

        cx = self.width // 2

        # Warning icon (triangle made of text)
        icon_font = _get_font(48)
        icon = icon_font.render("!", True, (255, 200, 60))
        # Triangle background
        tri_cx = cx
        tri_cy = 80
        tri_pts = [(tri_cx, tri_cy - 30), (tri_cx - 28, tri_cy + 20),
                   (tri_cx + 28, tri_cy + 20)]
        pygame.draw.polygon(self.screen, (60, 50, 20), tri_pts)
        pygame.draw.polygon(self.screen, (255, 200, 60), tri_pts, 2)
        self.screen.blit(icon, (tri_cx - icon.get_width() // 2, tri_cy - 16))

        # Title
        title_font = _get_font(32)
        ctx = self._context.replace("_", " ").title() if self._context else "Application"
        title = title_font.render(f"{ctx} Crashed", True, (240, 100, 100))
        self.screen.blit(title, (cx - title.get_width() // 2, 130))

        # Description
        desc_font = _get_font(16)
        lines = [
            "An unexpected error occurred and has been logged.",
            "",
            "Log file:",
            self._log_path,
            "",
            "Check the logs/ folder for details.",
        ]
        y = 185
        for line in lines:
            color = (180, 180, 200) if line != self._log_path else (140, 180, 255)
            surf = desc_font.render(line, True, color)
            self.screen.blit(surf, (cx - surf.get_width() // 2, y))
            y += 24

        self._btn.draw(self.screen)
        pygame.display.flip()
