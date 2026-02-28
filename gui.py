"""Command-center GUI panel for selecting spawn type."""
from __future__ import annotations
import pygame
from entities.base import Entity
from entities.command_center import CommandCenter
from config.settings import (
    GUI_BG, GUI_BORDER, GUI_BTN_SIZE, GUI_BTN_GAP,
    GUI_BTN_SELECTED, GUI_BTN_HOVER, GUI_BTN_NORMAL,
    GUI_TEXT_COLOR, GUI_PANEL_HEIGHT,
    TEAM1_COLOR, TEAM1_SELECTED_COLOR,
)
from config.unit_types import UNIT_TYPES


def get_selected_cc(entities: list[Entity]) -> CommandCenter | None:
    for e in entities:
        if isinstance(e, CommandCenter) and e.selected:
            return e
    return None


def button_rects(width: int, height: int) -> list[tuple[pygame.Rect, str]]:
    types = list(UNIT_TYPES.keys())
    total_w = len(types) * GUI_BTN_SIZE + (len(types) - 1) * GUI_BTN_GAP
    start_x = (width - total_w) // 2
    y = height - GUI_PANEL_HEIGHT + (GUI_PANEL_HEIGHT - GUI_BTN_SIZE) // 2
    rects = []
    for i, utype in enumerate(types):
        bx = start_x + i * (GUI_BTN_SIZE + GUI_BTN_GAP)
        rects.append((pygame.Rect(bx, y, GUI_BTN_SIZE, GUI_BTN_SIZE), utype))
    return rects


def draw_cc_gui(
    screen: pygame.Surface,
    entities: list[Entity],
    width: int, height: int,
):
    cc = get_selected_cc(entities)
    if cc is None:
        return

    panel_rect = pygame.Rect(0, height - GUI_PANEL_HEIGHT, width, GUI_PANEL_HEIGHT)
    pygame.draw.rect(screen, GUI_BG, panel_rect)
    pygame.draw.line(screen, GUI_BORDER, (0, panel_rect.top), (width, panel_rect.top), 1)

    mx, my = pygame.mouse.get_pos()
    font = pygame.font.SysFont(None, 18)

    for btn_rect, utype in button_rects(width, height):
        is_selected = cc.spawn_type == utype
        is_hover = btn_rect.collidepoint(mx, my)

        if is_selected:
            bg = GUI_BTN_SELECTED
        elif is_hover:
            bg = GUI_BTN_HOVER
        else:
            bg = GUI_BTN_NORMAL

        pygame.draw.rect(screen, bg, btn_rect, border_radius=4)
        pygame.draw.rect(screen, GUI_BORDER, btn_rect, 1, border_radius=4)

        stats = UNIT_TYPES[utype]
        symbol = stats["symbol"]
        cx = btn_rect.centerx
        cy = btn_rect.centery - 4
        if symbol is not None:
            scale = 1.2
            pts = [(cx + px * scale, cy + py * scale) for px, py in symbol]
            pygame.draw.polygon(screen, TEAM1_COLOR, pts)
            pygame.draw.polygon(screen, TEAM1_SELECTED_COLOR, pts, 1)
        else:
            pygame.draw.circle(screen, TEAM1_COLOR, (cx, cy), 8)
            pygame.draw.circle(screen, TEAM1_SELECTED_COLOR, (cx, cy), 8, 1)

        label = font.render(utype.upper(), True, GUI_TEXT_COLOR)
        lx = btn_rect.centerx - label.get_width() // 2
        ly = btn_rect.bottom - label.get_height() - 2
        screen.blit(label, (lx, ly))


def handle_gui_click(
    entities: list[Entity],
    mx: int, my: int,
    width: int, height: int,
) -> bool:
    cc = get_selected_cc(entities)
    if cc is None:
        return False
    for btn_rect, utype in button_rects(width, height):
        if btn_rect.collidepoint(mx, my):
            cc.spawn_type = utype
            return True
    return False
