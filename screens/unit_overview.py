"""Unit overview screen — browse unit types, see symbols and stats."""
from __future__ import annotations
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, SIDEBAR_BG, SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT,
    CONTENT_TEXT, CONTENT_HEADING, CONTENT_FONT_SIZE, HEADING_FONT_SIZE,
    TG_ACTIVE, TG_INACTIVE, TG_BORDER,
)
from ui.widgets import BackButton
from config.unit_types import UNIT_TYPES
from config.settings import TEAM1_COLOR, TEAM1_SELECTED_COLOR


class UnitOverviewScreen(BaseScreen):
    """Interactive browser for unit types with enlarged symbols and stats."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)
        self._types = list(UNIT_TYPES.keys())
        self._selected = 0
        self._back = BackButton()

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if self._back.handle_event(event):
                    return ScreenResult("guides")

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    for i in range(len(self._types)):
                        r = pygame.Rect(0, 60 + i * SIDEBAR_BTN_HEIGHT,
                                        SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT)
                        if r.collidepoint(event.pos):
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

        for i, utype in enumerate(self._types):
            r = pygame.Rect(0, 60 + i * SIDEBAR_BTN_HEIGHT,
                            SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT)
            active = i == self._selected
            hover = r.collidepoint(mx, my)
            bg = TG_ACTIVE if active else (TG_BORDER if hover else TG_INACTIVE)
            pygame.draw.rect(self.screen, bg, r)
            pygame.draw.line(self.screen, TG_BORDER,
                             (r.left, r.bottom), (r.right, r.bottom))

            label = font_s.render(utype.replace("_", " ").title(), True,
                                  (255, 255, 255) if active else CONTENT_TEXT)
            self.screen.blit(label, (12, r.centery - label.get_height() // 2))

        self._back.draw(self.screen)

        # Content area
        utype = self._types[self._selected]
        stats = UNIT_TYPES[utype]
        content_x = SIDEBAR_WIDTH + 30
        content_w = self.width - SIDEBAR_WIDTH - 60

        # Heading
        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        heading = font_h.render(utype.replace("_", " ").title(), True, CONTENT_HEADING)
        self.screen.blit(heading, (content_x, 20))

        # Draw enlarged symbol
        cx = content_x + content_w // 2
        cy = 140
        scale = 5.0
        symbol = stats["symbol"]
        if symbol is not None:
            pts = [(cx + px * scale, cy + py * scale) for px, py in symbol]
            pygame.draw.polygon(self.screen, TEAM1_COLOR, pts)
            pygame.draw.polygon(self.screen, TEAM1_SELECTED_COLOR, pts, 2)
        else:
            radius = int(16 * scale / 2)
            pygame.draw.circle(self.screen, TEAM1_COLOR, (cx, cy), radius)
            pygame.draw.circle(self.screen, TEAM1_SELECTED_COLOR, (cx, cy), radius, 2)

        # Stats table
        font_c = pygame.font.SysFont(None, CONTENT_FONT_SIZE)
        table_y = 240
        row_h = 26

        stat_rows = [
            ("HP", str(stats["hp"])),
            ("Speed", str(stats["speed"])),
            ("Radius", str(stats["radius"])),
            ("Damage", str(stats["damage"])),
            ("Range", str(stats["range"])),
            ("Cooldown", f"{stats['cooldown']}s"),
            ("Can Attack", "Yes" if stats["can_attack"] else "No"),
        ]

        # Medic-specific stats
        if "heal_rate" in stats:
            stat_rows.append(("Heal Rate", str(stats["heal_rate"])))
        if "heal_range" in stats:
            stat_rows.append(("Heal Range", str(stats["heal_range"])))
        if "heal_targets" in stats:
            stat_rows.append(("Heal Targets", str(stats["heal_targets"])))

        for i, (label, value) in enumerate(stat_rows):
            y = table_y + i * row_h

            # Alternating row background
            if i % 2 == 0:
                row_rect = pygame.Rect(content_x - 5, y - 2,
                                       content_w + 10, row_h)
                pygame.draw.rect(self.screen, (20, 20, 32), row_rect)

            lbl_surf = font_c.render(label, True, (160, 160, 180))
            val_surf = font_c.render(value, True, CONTENT_TEXT)
            self.screen.blit(lbl_surf, (content_x, y))
            self.screen.blit(val_surf, (content_x + 160, y))

        pygame.display.flip()
