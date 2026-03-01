"""Guides screen — sidebar with 6 topics, content pane with word-wrapped text."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, SIDEBAR_BG, SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT,
    CONTENT_BG, CONTENT_TEXT, CONTENT_HEADING, CONTENT_FONT_SIZE,
    HEADING_FONT_SIZE,
    TG_ACTIVE, TG_INACTIVE, TG_BORDER,
)
from ui.widgets import BackButton

# -- guide content -----------------------------------------------------------

TOPICS = [
    (
        "Overview",
        [
            "AIRTS is an AI Real-Time Strategy game built for the BlueOrange AI Jam.",
            "",
            "Two teams compete to destroy each other's Command Center. Each team "
            "can be controlled by a human player or an AI controller.",
            "",
            "Games end when a Command Center is destroyed, or both are destroyed "
            "simultaneously (draw).",
            "",
            "Build units, capture metal spots for faster spawning, and use tactical "
            "movement to outplay your opponent.",
        ],
    ),
    (
        "Selection & Movement",
        [
            "LEFT CLICK on a unit to select it. Hold SHIFT to add to selection.",
            "",
            "LEFT CLICK + DRAG draws a circle selection around multiple units.",
            "",
            "RIGHT CLICK + DRAG draws a movement path. Selected units are "
            "distributed along the path using nearest-neighbor assignment.",
            "",
            "RIGHT CLICK on a single point to move all selected units there.",
            "",
            "When a Command Center is selected, RIGHT CLICK sets a rally point "
            "for newly spawned units.",
        ],
    ),
    (
        "Combat & Fire Modes",
        [
            "Units with 'can_attack = True' automatically fire at enemies within range.",
            "",
            "Attacks are laser-based with damage, range, and cooldown stats.",
            "",
            "Command Centers also have a defensive laser that fires at nearby enemies.",
            "",
            "Medics do not attack but heal nearby friendly units instead.",
            "",
            "Combat is resolved every frame — position your units wisely to focus fire "
            "and avoid taking unnecessary damage.",
        ],
    ),
    (
        "Command Centers",
        [
            "Each team starts with one Command Center (CC).",
            "",
            "CCs spawn units periodically. Click the GUI panel at the bottom to "
            "choose which unit type to spawn.",
            "",
            "CCs have a defensive laser (range 75, damage 20).",
            "",
            "CCs heal nearby friendly units within range 40.",
            "",
            "Metal Extractors built near a CC boost its spawn speed by 5% each.",
            "",
            "If your CC is destroyed, you lose!",
        ],
    ),
    (
        "Metal Spots & Economy",
        [
            "Metal Spots are golden circles scattered across the map.",
            "",
            "Send units near a Metal Spot to capture it. The capture progress "
            "depends on how many units are within range.",
            "",
            "Once captured, a Metal Extractor is built on the spot.",
            "",
            "Each Metal Extractor boosts your CC's spawn speed by 5%.",
            "",
            "Extractors can be destroyed by the enemy team.",
            "",
            "Controlling metal spots gives you a significant unit production advantage.",
        ],
    ),
    (
        "Unit Overview",
        [
            "Click here to open the interactive Unit Overview browser, where you "
            "can inspect each unit type's symbol, stats, and special abilities.",
        ],
    ),
]


class GuidesScreen(BaseScreen):
    """Guide viewer with sidebar navigation and word-wrapped content."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)
        self._selected = 0
        self._back = BackButton()

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if self._back.handle_event(event):
                    return ScreenResult("main_menu")

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    for i in range(len(TOPICS)):
                        r = pygame.Rect(0, 60 + i * SIDEBAR_BTN_HEIGHT,
                                        SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT)
                        if r.collidepoint(event.pos):
                            # "Unit Overview" topic links to that screen
                            if i == len(TOPICS) - 1:
                                return ScreenResult("unit_overview")
                            self._selected = i

            self._draw()
            self.clock.tick(60)

    def _draw(self):
        self.screen.fill(MENU_BG)

        # Sidebar
        sidebar_rect = pygame.Rect(0, 0, SIDEBAR_WIDTH, self.height)
        pygame.draw.rect(self.screen, SIDEBAR_BG, sidebar_rect)

        font_s = pygame.font.SysFont(None, CONTENT_FONT_SIZE)
        mx, my = pygame.mouse.get_pos()

        for i, (title, _) in enumerate(TOPICS):
            r = pygame.Rect(0, 60 + i * SIDEBAR_BTN_HEIGHT,
                            SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT)
            active = i == self._selected
            hover = r.collidepoint(mx, my)
            bg = TG_ACTIVE if active else (TG_BORDER if hover else TG_INACTIVE)
            pygame.draw.rect(self.screen, bg, r)
            pygame.draw.line(self.screen, TG_BORDER,
                             (r.left, r.bottom), (r.right, r.bottom))

            suffix = " >" if i == len(TOPICS) - 1 else ""
            label = font_s.render(title + suffix, True, (255, 255, 255) if active else CONTENT_TEXT)
            self.screen.blit(label, (12, r.centery - label.get_height() // 2))

        self._back.draw(self.screen)

        # Content pane
        content_x = SIDEBAR_WIDTH + 20
        content_w = self.width - SIDEBAR_WIDTH - 40
        _, lines = TOPICS[self._selected]

        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        heading = font_h.render(TOPICS[self._selected][0], True, CONTENT_HEADING)
        self.screen.blit(heading, (content_x, 20))

        font_c = pygame.font.SysFont(None, CONTENT_FONT_SIZE)
        y = 60
        for line in lines:
            if not line:
                y += 10
                continue
            wrapped = self._wrap_text(font_c, line, content_w)
            for wline in wrapped:
                surf = font_c.render(wline, True, CONTENT_TEXT)
                self.screen.blit(surf, (content_x, y))
                y += surf.get_height() + 4

        pygame.display.flip()

    @staticmethod
    def _wrap_text(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]
