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

_LABEL_FONT_SIZE = 14
_LABEL_MAX_W = GUI_BTN_SIZE + GUI_BTN_GAP
_LABEL_COLOR = (180, 180, 200)
_LABEL_GAP = 3  # gap between button bottom and first label line

# Tooltip styling
_TT_BG = (22, 22, 34)
_TT_BORDER = (70, 70, 100)
_TT_TITLE_COLOR = (220, 220, 240)
_TT_LABEL_COLOR = (140, 140, 165)
_TT_VALUE_COLOR = (200, 200, 220)
_TT_PAD = 10
_TT_LINE_H = 20
_TT_TITLE_FONT = 20
_TT_BODY_FONT = 16
_TT_WIDTH = 170


def _display_name(unit_type: str) -> str:
    """Convert internal key to human-readable name."""
    return unit_type.replace("_", " ").title()


def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Split text into lines that fit within max_width."""
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
    return lines


def get_selected_cc(entities: list[Entity]) -> CommandCenter | None:
    for e in entities:
        if isinstance(e, CommandCenter) and e.selected:
            return e
    return None


def button_rects(width: int, height: int) -> list[tuple[pygame.Rect, str]]:
    types = list(UNIT_TYPES.keys())
    total_w = len(types) * GUI_BTN_SIZE + (len(types) - 1) * GUI_BTN_GAP
    start_x = (width - total_w) // 2
    y = height - GUI_PANEL_HEIGHT + 8
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
    label_font = pygame.font.SysFont(None, _LABEL_FONT_SIZE)
    hovered_type: str | None = None

    for btn_rect, utype in button_rects(width, height):
        is_selected = cc.spawn_type == utype
        is_hover = btn_rect.collidepoint(mx, my)
        if is_hover:
            hovered_type = utype

        if is_selected:
            bg = GUI_BTN_SELECTED
        elif is_hover:
            bg = GUI_BTN_HOVER
        else:
            bg = GUI_BTN_NORMAL

        pygame.draw.rect(screen, bg, btn_rect, border_radius=4)
        pygame.draw.rect(screen, GUI_BORDER, btn_rect, 1, border_radius=4)

        # Draw unit symbol centered in the button
        stats = UNIT_TYPES[utype]
        symbol = stats["symbol"]
        cx = btn_rect.centerx
        cy = btn_rect.centery
        if symbol is not None:
            scale = 1.2
            pts = [(cx + px * scale, cy + py * scale) for px, py in symbol]
            pygame.draw.polygon(screen, TEAM1_COLOR, pts)
            pygame.draw.polygon(screen, TEAM1_SELECTED_COLOR, pts, 1)
        else:
            pygame.draw.circle(screen, TEAM1_COLOR, (cx, cy), 8)
            pygame.draw.circle(screen, TEAM1_SELECTED_COLOR, (cx, cy), 8, 1)

        # Label below the button with word wrapping
        name = _display_name(utype)
        lines = _wrap_text(name, label_font, _LABEL_MAX_W)
        ly = btn_rect.bottom + _LABEL_GAP
        for line in lines:
            surf = label_font.render(line, True, _LABEL_COLOR)
            lx = btn_rect.centerx - surf.get_width() // 2
            screen.blit(surf, (lx, ly))
            ly += surf.get_height() + 1

    # Draw tooltip for hovered unit type
    if hovered_type is not None:
        _draw_tooltip(screen, hovered_type, height)


def _draw_tooltip(screen: pygame.Surface, utype: str, screen_h: int):
    """Draw a stats tooltip in the bottom-left corner."""
    stats = UNIT_TYPES[utype]
    title_font = pygame.font.SysFont(None, _TT_TITLE_FONT)
    body_font = pygame.font.SysFont(None, _TT_BODY_FONT)

    # Build stat rows
    rows: list[tuple[str, str]] = [
        ("HP", str(stats["hp"])),
        ("Speed", str(stats["speed"])),
    ]
    if stats.get("can_attack") and stats["damage"] > 0:
        rows.append(("Damage", str(stats["damage"])))
        rows.append(("Range", str(stats["range"])))
        cd = stats["cooldown"]
        rows.append(("Cooldown", f"{cd:.1f}s" if cd != int(cd) else f"{int(cd)}s"))
    if stats.get("heal_rate"):
        rows.append(("Heal Rate", str(stats["heal_rate"])))
        rows.append(("Heal Range", str(stats["heal_range"])))
        rows.append(("Heal Targets", str(stats["heal_targets"])))

    # Calculate tooltip size
    name = _display_name(utype)
    tt_h = _TT_PAD + _TT_LINE_H + 4 + len(rows) * _TT_LINE_H + _TT_PAD
    tt_x = 10
    tt_y = screen_h - GUI_PANEL_HEIGHT - tt_h - 6

    rect = pygame.Rect(tt_x, tt_y, _TT_WIDTH, tt_h)
    pygame.draw.rect(screen, _TT_BG, rect, border_radius=6)
    pygame.draw.rect(screen, _TT_BORDER, rect, 1, border_radius=6)

    # Title
    title_surf = title_font.render(name, True, _TT_TITLE_COLOR)
    screen.blit(title_surf, (tt_x + _TT_PAD, tt_y + _TT_PAD))

    # Stat rows
    row_y = tt_y + _TT_PAD + _TT_LINE_H + 4
    for label, value in rows:
        lbl_surf = body_font.render(label, True, _TT_LABEL_COLOR)
        val_surf = body_font.render(value, True, _TT_VALUE_COLOR)
        screen.blit(lbl_surf, (tt_x + _TT_PAD, row_y))
        screen.blit(val_surf, (tt_x + _TT_WIDTH - _TT_PAD - val_surf.get_width(), row_y))
        row_y += _TT_LINE_H


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
