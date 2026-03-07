"""HUD system — minimap, unit display, portrait, action/build panel."""
from __future__ import annotations
import math
import pygame
from entities.base import Entity
from entities.unit import Unit
from entities.command_center import CommandCenter
from entities.metal_extractor import MetalExtractor
from config.settings import (
    GUI_BORDER, GUI_BTN_SELECTED, GUI_BTN_HOVER, GUI_BTN_NORMAL,
    GUI_TEXT_COLOR,
    TEAM1_COLOR, TEAM1_SELECTED_COLOR, TEAM2_COLOR,
    HEALTH_BAR_FG, HEALTH_BAR_LOW, HEALTH_BAR_BG,
    CC_SPAWN_INTERVAL,
)
from config.unit_types import UNIT_TYPES, get_spawnable_types
from core.helpers import hexagon_points

# ── colours ──────────────────────────────────────────────────────────
_SECTION_BG = (22, 22, 30)
_MINIMAP_BG = (10, 10, 15)
_PORTRAIT_BG = (28, 28, 38)
_DIVIDER = (50, 50, 65)
_TITLE_COLOR = (210, 210, 230)
_STAT_LABEL = (130, 130, 155)
_STAT_VALUE = (200, 200, 220)
_GROUP_BOX_BG = (35, 35, 48)
_GROUP_BOX_BORDER = (55, 55, 75)

# ── sizes ────────────────────────────────────────────────────────────
_BUILD_BTN_SIZE = 38
_BUILD_BTN_GAP = 4
_ACTION_BTN_SIZE = 38
_ACTION_BTN_GAP = 4
_GROUP_BOX_SIZE = 26
_GROUP_BOX_GAP = 2
_GROUP_HP_H = 3

# ── tooltip ──────────────────────────────────────────────────────────
_TT_BG = (22, 22, 34)
_TT_BORDER = (70, 70, 100)
_TT_PAD = 10
_TT_LINE_H = 20
_TT_WIDTH = 170

# ── font cache ───────────────────────────────────────────────────────
_font_cache: dict[int, pygame.font.Font] = {}


def _font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.SysFont(None, size)
    return _font_cache[size]


def _display_name(unit_type: str) -> str:
    return unit_type.replace("_", " ").title()


# ── queries ──────────────────────────────────────────────────────────

def get_selected_cc(entities: list[Entity]) -> CommandCenter | None:
    for e in entities:
        if isinstance(e, CommandCenter) and e.selected:
            return e
    return None


def _get_selected(entities: list[Entity]) -> list[Unit]:
    return [e for e in entities if isinstance(e, Unit) and e.selected]


# ── layout helpers ───────────────────────────────────────────────────

def _hud_sections(width: int, height: int, hud_h: int):
    """Return (minimap_rect, display_rect, portrait_rect, action_rect)."""
    y = height - hud_h
    minimap_w = hud_h
    action_w = max(220, int(width * 0.20))
    portrait_w = max(60, int(hud_h * 0.55))
    display_w = width - minimap_w - portrait_w - action_w

    minimap = pygame.Rect(0, y, minimap_w, hud_h)
    display = pygame.Rect(minimap_w, y, display_w, hud_h)
    portrait = pygame.Rect(minimap_w + display_w, y, portrait_w, hud_h)
    action = pygame.Rect(width - action_w, y, action_w, hud_h)
    return minimap, display, portrait, action


def _build_btn_rects(ar: pygame.Rect) -> list[tuple[pygame.Rect, str]]:
    """Button rects for CC build options inside the action panel."""
    types = list(get_spawnable_types().keys())
    pad, hdr = 8, 22
    iw = ar.width - pad * 2
    cols = max(1, (iw + _BUILD_BTN_GAP) // (_BUILD_BTN_SIZE + _BUILD_BTN_GAP))
    out: list[tuple[pygame.Rect, str]] = []
    for i, ut in enumerate(types):
        c, r = i % cols, i // cols
        bx = ar.left + pad + c * (_BUILD_BTN_SIZE + _BUILD_BTN_GAP)
        by = ar.top + pad + hdr + r * (_BUILD_BTN_SIZE + _BUILD_BTN_GAP)
        out.append((pygame.Rect(bx, by, _BUILD_BTN_SIZE, _BUILD_BTN_SIZE), ut))
    return out


def _action_btn_rects(ar: pygame.Rect) -> list[tuple[pygame.Rect, str, str]]:
    """Button rects for unit action buttons. Returns (rect, action_id, key_label)."""
    actions = [("stop", "S"), ("attack", "A"), ("move", "M")]
    pad, hdr = 8, 22
    out: list[tuple[pygame.Rect, str, str]] = []
    for i, (aid, key) in enumerate(actions):
        bx = ar.left + pad + i * (_ACTION_BTN_SIZE + _ACTION_BTN_GAP)
        by = ar.top + pad + hdr
        out.append((pygame.Rect(bx, by, _ACTION_BTN_SIZE, _ACTION_BTN_SIZE), aid, key))
    return out


# ── drawing ──────────────────────────────────────────────────────────

def draw_hud(screen: pygame.Surface, entities: list[Entity],
             width: int, height: int, hud_h: int):
    """Draw the full HUD bar at the bottom of the screen."""
    minimap, display, portrait, action = _hud_sections(width, height, hud_h)
    selected = _get_selected(entities)
    cc = get_selected_cc(entities)

    _draw_minimap(screen, minimap)
    _draw_display(screen, display, selected)
    _draw_portrait(screen, portrait, selected)
    _draw_actions(screen, action, selected, cc)

    # vertical dividers
    for r in (minimap, display, portrait):
        pygame.draw.line(screen, _DIVIDER,
                         (r.right - 1, r.top), (r.right - 1, r.bottom))


def _draw_minimap(screen: pygame.Surface, r: pygame.Rect):
    pygame.draw.rect(screen, _MINIMAP_BG, r)
    t = _font(14).render("MINIMAP", True, (50, 50, 65))
    screen.blit(t, (r.centerx - t.get_width() // 2,
                    r.centery - t.get_height() // 2))


# ── unit / group display ────────────────────────────────────────────

def _draw_display(screen: pygame.Surface, r: pygame.Rect,
                  selected: list[Unit]):
    pygame.draw.rect(screen, _SECTION_BG, r)
    if not selected:
        return
    pad = 8
    inner = pygame.Rect(r.left + pad, r.top + pad,
                        r.width - pad * 2, r.height - pad * 2)
    if len(selected) == 1:
        _draw_single_info(screen, inner, selected[0])
    else:
        _draw_group_grid(screen, inner, selected)


def _draw_single_info(screen: pygame.Surface, r: pygame.Rect, unit: Unit):
    tf = _font(18)
    sf = _font(16)
    y = r.top

    # name
    ns = tf.render(_display_name(unit.unit_type), True, _TITLE_COLOR)
    screen.blit(ns, (r.left, y))
    y += ns.get_height() + 4

    # hp bar
    bw = min(r.width, 150)
    bh = 6
    ratio = unit.hp / unit.max_hp if unit.max_hp > 0 else 0
    pygame.draw.rect(screen, HEALTH_BAR_BG, (r.left, y, bw, bh))
    fg = HEALTH_BAR_FG if ratio > 0.35 else HEALTH_BAR_LOW
    pygame.draw.rect(screen, fg, (r.left, y, int(bw * ratio), bh))
    ht = sf.render(f"{int(unit.hp)}/{int(unit.max_hp)}", True, _STAT_VALUE)
    screen.blit(ht, (r.left + bw + 6, y - 2))
    y += bh + 6

    # stat rows
    rows: list[tuple[str, str]] = []
    if unit.speed > 0:
        rows.append(("Speed", str(int(unit.speed))))
    if unit.weapon:
        w = unit.weapon
        if w.damage < 0:
            rows.append(("Heal", str(abs(w.damage))))
        else:
            rows.append(("Dmg", str(w.damage)))
        rows.append(("Range", str(int(w.range))))
        cd = w.cooldown
        rows.append(("CD", f"{cd:.1f}s" if cd != int(cd) else f"{int(cd)}s"))
    if isinstance(unit, CommandCenter):
        bp = unit.get_total_bonus_percent()
        if bp > 0:
            rows.append(("Bonus", f"+{bp}%"))
        rows.append(("Spawn", _display_name(unit.spawn_type)))
        progress = min(unit._spawn_timer / CC_SPAWN_INTERVAL, 1.0)
        rows.append(("Ready", f"{int(progress * 100)}%"))
    if isinstance(unit, MetalExtractor):
        b = unit.get_spawn_bonus()
        rows.append(("Bonus", f"+{round(b * 100)}%"))

    # Abilities
    for ab in unit.abilities:
        ab_name = ab.name.replace("_", " ").title()
        if hasattr(ab, "stacks") and hasattr(ab, "max_stacks"):
            if ab.active:
                rows.append((ab_name, "Active"))
            else:
                rows.append((ab_name, f"{ab.stacks}/{ab.max_stacks}"))
        elif hasattr(ab, "timer") and ab.timer > 0:
            rows.append((ab_name, f"{ab.timer:.1f}s"))
        elif ab.active:
            rows.append((ab_name, "Active"))

    col_w = 95
    for i, (label, value) in enumerate(rows):
        c = i % 2
        ro = i // 2
        sx = r.left + c * col_w
        sy = y + ro * 16
        if sy + 16 > r.bottom:
            break
        ls = sf.render(f"{label}: ", True, _STAT_LABEL)
        vs = sf.render(value, True, _STAT_VALUE)
        screen.blit(ls, (sx, sy))
        screen.blit(vs, (sx + ls.get_width(), sy))


def _draw_group_grid(screen: pygame.Surface, r: pygame.Rect,
                     selected: list[Unit]):
    cf = _font(16)
    ct = cf.render(f"{len(selected)} units", True, _TITLE_COLOR)
    screen.blit(ct, (r.left, r.top))

    grid_top = r.top + ct.get_height() + 4
    bs = _GROUP_BOX_SIZE
    gap = _GROUP_BOX_GAP
    row_h = bs + _GROUP_HP_H + gap + 1
    cols = max(1, (r.width + gap) // (bs + gap))

    for i, unit in enumerate(selected):
        c = i % cols
        ro = i // cols
        bx = r.left + c * (bs + gap)
        by = grid_top + ro * row_h
        if by + bs > r.bottom:
            break

        box = pygame.Rect(bx, by, bs, bs)
        pygame.draw.rect(screen, _GROUP_BOX_BG, box)
        pygame.draw.rect(screen, _GROUP_BOX_BORDER, box, 1)

        cx, cy = box.centerx, box.centery
        stats = UNIT_TYPES.get(unit.unit_type, {})
        sym = stats.get("symbol")
        base_color = TEAM1_COLOR if unit.team == 1 else TEAM2_COLOR

        if isinstance(unit, CommandCenter):
            pts = hexagon_points(bs * 0.3)
            tp = [(cx + px, cy + py) for px, py in pts]
            pygame.draw.polygon(screen, base_color, tp)
        elif sym is not None:
            sc = bs / 42.0
            pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
            pygame.draw.polygon(screen, base_color, pts)
        else:
            pygame.draw.circle(screen, base_color, (cx, cy), bs // 5)

        # hp bar below box
        hp = unit.hp / unit.max_hp if unit.max_hp > 0 else 0
        hy = by + bs + 1
        pygame.draw.rect(screen, HEALTH_BAR_BG, (bx, hy, bs, _GROUP_HP_H))
        fg = HEALTH_BAR_FG if hp > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(screen, fg, (bx, hy, int(bs * hp), _GROUP_HP_H))


# ── portrait ─────────────────────────────────────────────────────────

def _draw_portrait(screen: pygame.Surface, r: pygame.Rect,
                   selected: list[Unit]):
    pygame.draw.rect(screen, _PORTRAIT_BG, r)
    if not selected:
        return

    unit = selected[0]
    pad = 6
    nf = _font(14)
    label_h = nf.get_height()
    # Reserve space for the label at the bottom, center the icon in remaining area
    icon_area_h = r.height - pad * 2 - label_h - 4
    sz = min(r.width - pad * 2, icon_area_h)
    cx = r.centerx
    cy = r.top + pad + icon_area_h // 2

    stats = UNIT_TYPES.get(unit.unit_type, {})
    sym = stats.get("symbol")
    base_color = TEAM1_COLOR if unit.team == 1 else TEAM2_COLOR

    if isinstance(unit, CommandCenter):
        pts = hexagon_points(sz * 0.35)
        tp = [(cx + px, cy + py) for px, py in pts]
        pygame.draw.polygon(screen, base_color, tp)
        pygame.draw.polygon(screen, TEAM1_SELECTED_COLOR, tp, 2)
    elif isinstance(unit, MetalExtractor):
        radius = sz * 0.3
        s = radius * math.sqrt(3) / 2
        pts = [(cx, cy - radius), (cx - s, cy + radius / 2),
               (cx + s, cy + radius / 2)]
        pygame.draw.polygon(screen, base_color, pts)
        pygame.draw.polygon(screen, TEAM1_SELECTED_COLOR, pts, 1)
    elif sym is not None:
        sc = sz / 36.0
        pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
        pygame.draw.polygon(screen, base_color, pts)
        pygame.draw.polygon(screen, TEAM1_SELECTED_COLOR, pts, 1)
    else:
        rad = int(sz * 0.3)
        pygame.draw.circle(screen, base_color, (cx, cy), rad)
        pygame.draw.circle(screen, TEAM1_SELECTED_COLOR, (cx, cy), rad, 1)

    # name below portrait
    nt = nf.render(_display_name(unit.unit_type), True, _STAT_LABEL)
    nx = cx - nt.get_width() // 2
    ny = r.bottom - pad - label_h
    screen.blit(nt, (nx, ny))


# ── actions / build panel ────────────────────────────────────────────

def _draw_actions(screen: pygame.Surface, r: pygame.Rect,
                  selected: list[Unit], cc: CommandCenter | None):
    pygame.draw.rect(screen, _SECTION_BG, r)
    if not selected:
        return

    tf = _font(18)
    mx, my = pygame.mouse.get_pos()
    hovered_type: str | None = None

    if cc is not None:
        # Build options
        ts = tf.render("Build", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))

        for br, ut in _build_btn_rects(r):
            is_sel = cc.spawn_type == ut
            is_hov = br.collidepoint(mx, my)
            if is_hov:
                hovered_type = ut
            bg = (GUI_BTN_SELECTED if is_sel
                  else GUI_BTN_HOVER if is_hov
                  else GUI_BTN_NORMAL)

            pygame.draw.rect(screen, bg, br, border_radius=4)
            pygame.draw.rect(screen, GUI_BORDER, br, 1, border_radius=4)

            st = UNIT_TYPES[ut]
            sym = st["symbol"]
            cx, cy = br.centerx, br.centery
            if sym is not None:
                sc = 0.9
                pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
                pygame.draw.polygon(screen, TEAM1_COLOR, pts)
                pygame.draw.polygon(screen, TEAM1_SELECTED_COLOR, pts, 1)
            else:
                pygame.draw.circle(screen, TEAM1_COLOR, (cx, cy), 7)
                pygame.draw.circle(screen, TEAM1_SELECTED_COLOR, (cx, cy), 7, 1)

        if hovered_type is not None:
            _draw_tooltip(screen, hovered_type, r)
    else:
        # Action buttons for army units / extractors
        ts = tf.render("Actions", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))

        for br, aid, key in _action_btn_rects(r):
            is_hov = br.collidepoint(mx, my)
            bg = GUI_BTN_HOVER if is_hov else GUI_BTN_NORMAL

            pygame.draw.rect(screen, bg, br, border_radius=4)
            pygame.draw.rect(screen, GUI_BORDER, br, 1, border_radius=4)

            kt = _font(18).render(key, True, GUI_TEXT_COLOR)
            screen.blit(kt, (br.centerx - kt.get_width() // 2,
                             br.centery - kt.get_height() // 2))

            # label below button
            lt = _font(12).render(aid.title(), True, _STAT_LABEL)
            screen.blit(lt, (br.centerx - lt.get_width() // 2,
                             br.bottom + 2))


def _draw_tooltip(screen: pygame.Surface, utype: str,
                  action_rect: pygame.Rect):
    """Draw a stats tooltip above the action panel."""
    stats = UNIT_TYPES[utype]
    tf = _font(20)
    bf = _font(16)

    rows: list[tuple[str, str]] = [
        ("HP", str(stats["hp"])),
        ("Speed", str(stats["speed"])),
    ]
    wpn = stats.get("weapon")
    if wpn:
        if wpn["damage"] < 0:
            rows.append(("Heal/pulse", str(abs(wpn["damage"]))))
        else:
            rows.append(("Damage", str(wpn["damage"])))
        rows.append(("Range", str(wpn["range"])))
        cd = wpn["cooldown"]
        rows.append(("Cooldown", f"{cd:.1f}s" if cd != int(cd)
                      else f"{int(cd)}s"))

    name = _display_name(utype)
    tt_h = _TT_PAD + _TT_LINE_H + 4 + len(rows) * _TT_LINE_H + _TT_PAD
    tt_x = action_rect.left + 10
    tt_y = action_rect.top - tt_h - 6

    rect = pygame.Rect(tt_x, tt_y, _TT_WIDTH, tt_h)
    pygame.draw.rect(screen, _TT_BG, rect, border_radius=6)
    pygame.draw.rect(screen, _TT_BORDER, rect, 1, border_radius=6)

    ts = tf.render(name, True, (220, 220, 240))
    screen.blit(ts, (tt_x + _TT_PAD, tt_y + _TT_PAD))

    ry = tt_y + _TT_PAD + _TT_LINE_H + 4
    for label, value in rows:
        ls = bf.render(label, True, (140, 140, 165))
        vs = bf.render(value, True, (200, 200, 220))
        screen.blit(ls, (tt_x + _TT_PAD, ry))
        screen.blit(vs, (tt_x + _TT_WIDTH - _TT_PAD - vs.get_width(), ry))
        ry += _TT_LINE_H


# ── click handling ───────────────────────────────────────────────────

def handle_hud_click(entities: list[Entity], mx: int, my: int,
                     width: int, height: int, hud_h: int) -> dict | None:
    """Return an action dict if a button was clicked, else None."""
    _, _, _, action = _hud_sections(width, height, hud_h)
    if not action.collidepoint(mx, my):
        return None

    selected = _get_selected(entities)
    if not selected:
        return None

    cc = get_selected_cc(entities)
    if cc is not None:
        for br, ut in _build_btn_rects(action):
            if br.collidepoint(mx, my):
                return {"action": "set_spawn_type", "unit_type": ut}
    else:
        for br, aid, _ in _action_btn_rects(action):
            if br.collidepoint(mx, my):
                return {"action": aid}
    return None
