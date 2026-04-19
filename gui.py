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
    PLAYER_COLORS, TEAM1_SELECTED_COLOR,
    HEALTH_BAR_FG, HEALTH_BAR_LOW, HEALTH_BAR_BG,
    CC_SPAWN_INTERVAL,
    OUTPOST_UPGRADE_DURATION, RESEARCH_LAB_UPGRADE_DURATION,
    OUTPOST_HP_BONUS, OUTPOST_LASER_DAMAGE, OUTPOST_LASER_RANGE,
    OUTPOST_LASER_COOLDOWN, OUTPOST_HEAL_PER_SEC, OUTPOST_LOS,
    RESEARCH_LAB_HP_BONUS, T2_SPAWN_BONUS,
    REINFORCE_MAX_STACKS, REINFORCE_STACK_INTERVAL,
)
from config.unit_types import UNIT_TYPES, get_spawnable_types, get_t2_name
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

# CC build panel hotkey letters (QWERTY row) — must match
# _CC_BUILD_HOTKEYS in screens/client_game.py.
_BUILD_HOTKEY_LETTERS = ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"]

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


_T2_CHEVRON_COLOR = (255, 220, 60)


def _draw_t2_chevron(screen: pygame.Surface, x: int, y: int, size: int = 6):
    """Draw a small yellow upward chevron (^) at the given position."""
    half = size // 2
    pts = [(x - half, y + half), (x, y - half), (x + half, y + half)]
    pygame.draw.lines(screen, _T2_CHEVRON_COLOR, False, pts, 2)


# ── queries ──────────────────────────────────────────────────────────

def _is_cc(e) -> bool:
    """Duck-type check: works for real CommandCenter or proxy objects."""
    return getattr(e, '_is_command_center', False) or getattr(e, 'unit_type', '') == 'command_center'


def _is_me(e) -> bool:
    """Duck-type check: works for real MetalExtractor or proxy objects."""
    return getattr(e, '_is_metal_extractor', False) or getattr(e, 'unit_type', '') == 'metal_extractor'


def _reinforce_ability(me):
    """Return the Reinforce ability instance/proxy on a metal extractor, or None."""
    for ab in getattr(me, "abilities", []) or []:
        if getattr(ab, "name", "") == "reinforce":
            return ab
    return None


def _reinforce_stacks(me) -> int:
    ab = _reinforce_ability(me)
    return int(getattr(ab, "stacks", 0)) if ab is not None else 0


def get_selected_cc(entities):
    for e in entities:
        if _is_cc(e) and getattr(e, 'selected', False):
            return e
    return None


def _get_selected(entities) -> list:
    return [e for e in entities if getattr(e, '_is_unit', False) or isinstance(e, Unit) if getattr(e, 'selected', False)]


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
    actions = [("stop", "S"), ("attack", "A"), ("move", "M"),
               ("fight", "F"), ("hold_fire", "H")]
    pad, hdr = 8, 22
    out: list[tuple[pygame.Rect, str, str]] = []
    for i, (aid, key) in enumerate(actions):
        bx = ar.left + pad + i * (_ACTION_BTN_SIZE + _ACTION_BTN_GAP)
        by = ar.top + pad + hdr
        out.append((pygame.Rect(bx, by, _ACTION_BTN_SIZE, _ACTION_BTN_SIZE), aid, key))
    return out


_UPGRADE_BTN_W = 90
_UPGRADE_BTN_H = 30
_UPGRADE_BTN_GAP = 6


def _upgrade_btn_rects(ar: pygame.Rect) -> list[tuple[pygame.Rect, str, str]]:
    """Button rects for Outpost / Research Lab upgrade options."""
    options = [("outpost", "Outpost"), ("research_lab", "Research Lab")]
    pad, hdr = 8, 22
    out: list[tuple[pygame.Rect, str, str]] = []
    for i, (path, label) in enumerate(options):
        bx = ar.left + pad
        by = ar.top + pad + hdr + i * (_UPGRADE_BTN_H + _UPGRADE_BTN_GAP)
        out.append((pygame.Rect(bx, by, _UPGRADE_BTN_W, _UPGRADE_BTN_H), path, label))
    return out


def _research_btn_rects(ar: pygame.Rect) -> list[tuple[pygame.Rect, str]]:
    """Button rects for research lab unit type selection."""
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


# ── drawing ──────────────────────────────────────────────────────────

def draw_hud(screen: pygame.Surface, entities,
             width: int, height: int, hud_h: int,
             enable_t2: bool = False, t2_upgrades: dict | None = None,
             t2_researching: dict | None = None,
             camera=None, world_w: int = 0, world_h: int = 0,
             obstacles=None):
    """Draw the full HUD bar at the bottom of the screen.

    ``t2_upgrades`` are *completed* T2 unlocks (CC can spawn them).
    ``t2_researching`` are still being researched and must NOT be treated as
    unlocked by the CC UI — they only matter for the ME research-grid greying.
    """
    minimap, display, portrait, action = _hud_sections(width, height, hud_h)
    selected = _get_selected(entities)
    cc = get_selected_cc(entities)

    _draw_minimap(screen, minimap, entities, camera, world_w, world_h,
                  obstacles=obstacles)
    _draw_display(screen, display, selected, t2_upgrades=t2_upgrades)
    _draw_portrait(screen, portrait, selected)
    _draw_actions(screen, action, selected, cc,
                  enable_t2=enable_t2,
                  t2_upgrades=t2_upgrades,
                  t2_researching=t2_researching)

    # vertical dividers
    for r in (minimap, display, portrait):
        pygame.draw.line(screen, _DIVIDER,
                         (r.right - 1, r.top), (r.right - 1, r.bottom))


def _draw_minimap(screen: pygame.Surface, r: pygame.Rect,
                  entities=None, camera=None,
                  world_w: int = 0, world_h: int = 0,
                  obstacles=None):
    pygame.draw.rect(screen, _MINIMAP_BG, r)

    if not entities or world_w <= 0 or world_h <= 0:
        t = _font(14).render("MINIMAP", True, (50, 50, 65))
        screen.blit(t, (r.centerx - t.get_width() // 2,
                        r.centery - t.get_height() // 2))
        return

    pad = 4
    inner_w = r.width - pad * 2
    inner_h = r.height - pad * 2
    sx = inner_w / world_w
    sy = inner_h / world_h
    scale = min(sx, sy)
    mw = world_w * scale
    mh = world_h * scale
    ox = r.left + pad + (inner_w - mw) / 2
    oy = r.top + pad + (inner_h - mh) / 2

    def w2m(wx: float, wy: float) -> tuple[int, int]:
        return int(ox + wx * scale), int(oy + wy * scale)

    # Clip drawing to minimap area
    screen.set_clip(r)

    from entities.metal_spot import MetalSpot
    from entities.shapes import RectEntity, CircleEntity
    from config.settings import TEAM_COLORS, OBSTACLE_COLOR

    def _is_ms(e):
        return isinstance(e, MetalSpot) or getattr(e, '_is_metal_spot', False)

    def _is_me(e):
        return isinstance(e, MetalExtractor) or getattr(e, '_is_metal_extractor', False)

    def _is_unit(e):
        return (isinstance(e, Unit) or getattr(e, '_is_unit', False)) and not getattr(e, 'is_building', False) and not _is_ms(e) and not _is_me(e) and not _is_cc(e)

    def _is_cc(e):
        return isinstance(e, CommandCenter) or getattr(e, '_is_command_center', False)

    # Obstacles (grey) — from real entities or separate obstacle dicts
    for e in entities:
        if getattr(e, "obstacle", False) and getattr(e, "alive", False):
            mx, my = w2m(e.x, e.y)
            if isinstance(e, RectEntity):
                hw = max(1, int(e.width * scale / 2))
                hh = max(1, int(e.height * scale / 2))
                pygame.draw.rect(screen, (80, 80, 80),
                                 (mx - hw, my - hh, hw * 2, hh * 2))
            else:
                mr = max(1, int(getattr(e, "radius", 3) * scale))
                pygame.draw.circle(screen, (80, 80, 80), (mx, my), mr)
    # Obstacles from separate dict list (client-side)
    if obstacles:
        for obs in obstacles:
            if obs.get("shape") == "rect":
                ox2, oy2 = w2m(obs["x"], obs["y"])
                ow = max(1, int(obs["w"] * scale))
                oh = max(1, int(obs["h"] * scale))
                pygame.draw.rect(screen, (80, 80, 80), (ox2, oy2, ow, oh))
            elif obs.get("shape") == "circle":
                ox2, oy2 = w2m(obs["x"], obs["y"])
                orr = max(1, int(obs["r"] * scale))
                pygame.draw.circle(screen, (80, 80, 80), (ox2, oy2), orr)

    # Build a team→color lookup from actual entities for correct minimap colors
    _team_color_map: dict[int, tuple] = {}
    for e in entities:
        tm = getattr(e, "team", 0)
        if tm and tm not in _team_color_map:
            c = getattr(e, "_base_color", getattr(e, "color", None))
            if c:
                _team_color_map[tm] = c

    # Metal spots (small triangles)
    for e in entities:
        if _is_ms(e) and getattr(e, "alive", True):
            mx, my = w2m(e.x, e.y)
            s = max(2, int(4 * scale))
            pts = [(mx, my - s), (mx - s, my + s), (mx + s, my + s)]
            owner = getattr(e, "owner", None)
            if owner is None:
                color = (255, 255, 255)
            else:
                color = _team_color_map.get(owner,
                        TEAM_COLORS.get(owner, (255, 255, 255)))
            pygame.draw.polygon(screen, color, pts)

    # Metal extractors (colored triangles)
    for e in entities:
        if _is_me(e) and getattr(e, "alive", True):
            mx, my = w2m(e.x, e.y)
            s = max(2, int(5 * scale))
            pts = [(mx, my - s), (mx - s, my + s), (mx + s, my + s)]
            color = getattr(e, "color", getattr(e, "_base_color", (200, 200, 200)))
            if getattr(e, "ghost", False):
                color = tuple(c // 3 for c in color)
            pygame.draw.polygon(screen, color, pts)

    # Units (small circles) — ghosts are buildings only, so units are never ghosts
    for e in entities:
        if _is_unit(e) and getattr(e, "alive", True):
            mx, my = w2m(e.x, e.y)
            mr = max(1, int(getattr(e, "radius", 5) * scale * 0.6))
            pygame.draw.circle(screen, getattr(e, "color", (200, 200, 200)), (mx, my), mr)

    # Command centers (small octagons)
    for e in entities:
        if _is_cc(e) and getattr(e, "alive", True):
            mx, my = w2m(e.x, e.y)
            s = max(3, int(20 * scale))
            pts = []
            for i in range(8):
                a = math.tau * i / 8
                pts.append((mx + int(s * math.cos(a)),
                            my + int(s * math.sin(a))))
            color = getattr(e, "color", getattr(e, "_base_color", (200, 200, 200)))
            if getattr(e, "ghost", False):
                color = tuple(c // 3 for c in color)
            pygame.draw.polygon(screen, color, pts)

    # Camera viewport rectangle
    if camera is not None:
        vp = camera.get_world_viewport_rect()
        cx1, cy1 = w2m(max(0, vp.left), max(0, vp.top))
        cx2, cy2 = w2m(min(world_w, vp.right), min(world_h, vp.bottom))
        cam_w = max(1, cx2 - cx1)
        cam_h = max(1, cy2 - cy1)
        cam_rect = pygame.Rect(cx1, cy1, cam_w, cam_h)
        # Clip to minimap world area
        mini_world = pygame.Rect(int(ox), int(oy), int(mw), int(mh))
        cam_rect = cam_rect.clip(mini_world)
        if cam_rect.width > 0 and cam_rect.height > 0:
            pygame.draw.rect(screen, (255, 255, 255), cam_rect, 1)

    screen.set_clip(None)


# ── unit / group display ────────────────────────────────────────────

def _draw_display(screen: pygame.Surface, r: pygame.Rect,
                  selected: list, t2_upgrades: dict | None = None):
    pygame.draw.rect(screen, _SECTION_BG, r)
    if not selected:
        return
    pad = 8
    inner = pygame.Rect(r.left + pad, r.top + pad,
                        r.width - pad * 2, r.height - pad * 2)
    if len(selected) == 1:
        _draw_single_info(screen, inner, selected[0], t2_upgrades=t2_upgrades)
    else:
        _draw_group_grid(screen, inner, selected)


def _draw_single_info(screen: pygame.Surface, r: pygame.Rect, unit,
                      t2_upgrades: dict | None = None):
    tf = _font(18)
    sf = _font(16)
    y = r.top

    # name
    if _is_me(unit) and getattr(unit, 'upgrade_state', 'base') in ("outpost", "research_lab"):
        name = unit.upgrade_state.replace("_", " ").title()
    elif getattr(unit, "is_t2", False):
        name = get_t2_name(unit.unit_type)
    else:
        name = _display_name(unit.unit_type)
    ns = tf.render(name, True, _TITLE_COLOR)
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
    if _is_cc(unit):
        bp = unit.get_total_bonus_percent()
        if bp > 0:
            rows.append(("Bonus", f"+{bp}%"))
    if _is_me(unit):
        b = unit.get_spawn_bonus()
        rows.append(("Bonus", f"+{round(b * 100)}%"))
        if unit.upgrade_state.startswith("upgrading"):
            secs = max(0, int(unit.upgrade_timer))
            rows.append(("Upgrade", f"{secs}s"))
        elif unit.upgrade_state == "choosing_research":
            rows.append(("Status", "Select unit"))
        elif unit.upgrade_state == "research_lab" and unit.researched_unit_type:
            rows.append(("Research", get_t2_name(unit.researched_unit_type)))

    # Abilities (Reinforce on metal extractors gets its own progress bar below)
    for ab in unit.abilities:
        if _is_me(unit) and getattr(ab, "name", "") == "reinforce":
            continue
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
    last_row_y = y
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
        last_row_y = sy + 16

    # Reinforce plating progress bar (metal extractors)
    if _is_me(unit):
        ab = _reinforce_ability(unit)
        if ab is not None:
            stacks = int(getattr(ab, "stacks", 0))
            max_stacks = int(getattr(ab, "max_stacks", REINFORCE_MAX_STACKS))
            stack_timer = float(getattr(ab, "stack_timer", 0.0))
            stack_interval = float(getattr(ab, "stack_interval",
                                           REINFORCE_STACK_INTERVAL))
            full = stacks >= max_stacks
            if full:
                progress = 1.0
            else:
                step = (stack_timer / stack_interval) if stack_interval > 0 else 0.0
                progress = (stacks + step) / max_stacks

            label_y = last_row_y + 4
            bar_w = min(r.width, 150)
            bar_h = 8
            if label_y + 16 + bar_h <= r.bottom:
                label_text = ("Plating: Reinforced" if full
                              else f"Plating: {stacks}/{max_stacks}")
                lt = sf.render(label_text, True, _STAT_LABEL)
                screen.blit(lt, (r.left, label_y))
                bar_y = label_y + lt.get_height() + 2
                pygame.draw.rect(screen, (40, 40, 50),
                                 (r.left, bar_y, bar_w, bar_h))
                fill_w = int(bar_w * progress)
                bar_color = (100, 255, 140) if full else (200, 200, 60)
                pygame.draw.rect(screen, bar_color,
                                 (r.left, bar_y, fill_w, bar_h))
                # Sub-tick marks at each stack boundary
                for i in range(1, max_stacks):
                    tx = r.left + int(bar_w * i / max_stacks)
                    pygame.draw.line(screen, (20, 20, 28),
                                     (tx, bar_y), (tx, bar_y + bar_h - 1))
                last_row_y = bar_y + bar_h

    # CC spawn progress bar (below stat rows)
    if _is_cc(unit):
        cc_team_t2 = (t2_upgrades or {}).get(unit.team, set())
        spawn_name = (get_t2_name(unit.spawn_type)
                      if unit.spawn_type in cc_team_t2
                      else _display_name(unit.spawn_type))
        progress = min(unit._spawn_timer / CC_SPAWN_INTERVAL, 1.0)
        label_y = last_row_y + 4
        bar_w = min(r.width, 150)
        bar_h = 8
        if label_y + 16 + bar_h <= r.bottom:
            lt = sf.render(f"Spawning: {spawn_name}", True, _STAT_LABEL)
            screen.blit(lt, (r.left, label_y))
            bar_y = label_y + lt.get_height() + 2
            pygame.draw.rect(screen, (40, 40, 50), (r.left, bar_y, bar_w, bar_h))
            fill_w = int(bar_w * progress)
            bar_color = (100, 255, 140) if progress >= 1.0 else (200, 200, 60)
            pygame.draw.rect(screen, bar_color, (r.left, bar_y, fill_w, bar_h))


def _draw_group_grid(screen: pygame.Surface, r: pygame.Rect,
                     selected: list):
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
        base_color = getattr(unit, "_base_color", unit.color)

        if _is_cc(unit):
            pts = hexagon_points(bs * 0.3)
            tp = [(cx + px, cy + py) for px, py in pts]
            pygame.draw.polygon(screen, base_color, tp)
        elif sym is not None:
            sc = bs / 42.0
            pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
            pygame.draw.polygon(screen, base_color, pts)
        else:
            pygame.draw.circle(screen, base_color, (cx, cy), bs // 5)

        # T2 chevron indicator
        if getattr(unit, "is_t2", False):
            _draw_t2_chevron(screen, box.right - 4, box.top + 4, size=5)

        # hp bar below box
        hp = unit.hp / unit.max_hp if unit.max_hp > 0 else 0
        hy = by + bs + 1
        pygame.draw.rect(screen, HEALTH_BAR_BG, (bx, hy, bs, _GROUP_HP_H))
        fg = HEALTH_BAR_FG if hp > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(screen, fg, (bx, hy, int(bs * hp), _GROUP_HP_H))


# ── portrait ─────────────────────────────────────────────────────────

def _draw_portrait(screen: pygame.Surface, r: pygame.Rect,
                   selected: list):
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
    base_color = getattr(unit, "_base_color", unit.color)

    if _is_cc(unit):
        pts = hexagon_points(sz * 0.35)
        tp = [(cx + px, cy + py) for px, py in pts]
        pygame.draw.polygon(screen, base_color, tp)
        pygame.draw.polygon(screen, base_color, tp, 2)
    elif _is_me(unit):
        radius = sz * 0.3
        s = radius * math.sqrt(3) / 2
        pts = [(cx, cy - radius), (cx - s, cy + radius / 2),
               (cx + s, cy + radius / 2)]
        pygame.draw.polygon(screen, base_color, pts)
        pygame.draw.polygon(screen, base_color, pts, 1)
    elif sym is not None:
        sc = sz / 36.0
        pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
        pygame.draw.polygon(screen, base_color, pts)
        pygame.draw.polygon(screen, base_color, pts, 1)
    else:
        rad = int(sz * 0.3)
        pygame.draw.circle(screen, base_color, (cx, cy), rad)
        pygame.draw.circle(screen, base_color, (cx, cy), rad, 1)

    # name below portrait
    if _is_me(unit) and getattr(unit, 'upgrade_state', 'base') in ("outpost", "research_lab"):
        pname = unit.upgrade_state.replace("_", " ").title()
    elif getattr(unit, "is_t2", False):
        pname = get_t2_name(unit.unit_type)
    else:
        pname = _display_name(unit.unit_type)
    nt = nf.render(pname, True, _STAT_LABEL)
    nx = cx - nt.get_width() // 2
    ny = r.bottom - pad - label_h
    screen.blit(nt, (nx, ny))


# ── actions / build panel ────────────────────────────────────────────

def _draw_actions(screen: pygame.Surface, r: pygame.Rect,
                  selected: list, cc=None,
                  enable_t2: bool = False, t2_upgrades: dict | None = None,
                  t2_researching: dict | None = None):
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
        cc_team_t2 = (t2_upgrades or {}).get(cc.team, set()) if enable_t2 else set()

        hf = _font(12)
        for i, (br, ut) in enumerate(_build_btn_rects(r)):
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
            cc_color = getattr(cc, "_base_color", cc.color)
            if sym is not None:
                sc = 0.9
                pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
                pygame.draw.polygon(screen, cc_color, pts)
                pygame.draw.polygon(screen, cc_color, pts, 1)
            else:
                pygame.draw.circle(screen, cc_color, (cx, cy), 7)
                pygame.draw.circle(screen, cc_color, (cx, cy), 7, 1)

            # Hotkey letter (QWERTY row) in top-left corner
            if i < len(_BUILD_HOTKEY_LETTERS):
                ht = hf.render(_BUILD_HOTKEY_LETTERS[i], True, (255, 255, 255))
                screen.blit(ht, (br.left + 2, br.top + 1))

            # T2 chevron indicator
            if ut in cc_team_t2:
                _draw_t2_chevron(screen, br.right - 6, br.top + 6, size=6)

        if hovered_type is not None:
            is_t2_type = hovered_type in cc_team_t2
            _draw_tooltip(screen, hovered_type, r, show_t2=is_t2_type)

    elif enable_t2 and len(selected) == 1 and _is_me(selected[0]):
        me = selected[0]
        _draw_extractor_actions(screen, r, me,
                                t2_upgrades or {},
                                t2_researching or {})

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
            label = aid.replace("_", " ").title()
            lt = _font(12).render(label, True, _STAT_LABEL)
            screen.blit(lt, (br.centerx - lt.get_width() // 2,
                             br.bottom + 2))


def _draw_extractor_actions(screen: pygame.Surface, r: pygame.Rect,
                            me, t2_upgrades: dict, t2_researching: dict | None = None):
    """Draw upgrade/research actions for a selected metal extractor.

    ``t2_upgrades`` are completed unlocks; ``t2_researching`` are in-progress
    research. Both are used to grey out unit types in the research grid so the
    player can't kick off duplicate research, but only ``t2_upgrades`` should
    influence the CC build buttons.
    """
    if t2_researching is None:
        t2_researching = {}
    tf = _font(18)
    sf = _font(14)
    mx, my = pygame.mouse.get_pos()

    if me.upgrade_state == "base":
        # Always show Outpost / Research Lab upgrade buttons; grey out until
        # the extractor is fully reinforced so the player can see what's
        # available before they have the platings to commit.
        disabled = not me.is_fully_reinforced
        ts = tf.render("Upgrade", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))

        hovered_upgrade: str | None = None
        for br, path, label in _upgrade_btn_rects(r):
            is_hov = br.collidepoint(mx, my)
            if is_hov:
                hovered_upgrade = path
            if disabled:
                bg = (38, 38, 48)
                border = (60, 60, 75)
                text_color = (110, 110, 125)
            else:
                bg = GUI_BTN_HOVER if is_hov else GUI_BTN_NORMAL
                border = GUI_BORDER
                text_color = GUI_TEXT_COLOR
            pygame.draw.rect(screen, bg, br, border_radius=4)
            pygame.draw.rect(screen, border, br, 1, border_radius=4)
            lt = sf.render(label, True, text_color)
            screen.blit(lt, (br.centerx - lt.get_width() // 2,
                             br.centery - lt.get_height() // 2))

        if hovered_upgrade is not None:
            stacks = _reinforce_stacks(me)
            need = REINFORCE_MAX_STACKS - stacks
            _draw_upgrade_tooltip(screen, hovered_upgrade, r,
                                  disabled=disabled, missing_stacks=need)

    elif me.upgrade_state == "choosing_research":
        # Show unit type grid for research selection
        ts = tf.render("Select Research", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))
        hovered_type: str | None = None

        team_t2 = (t2_upgrades.get(me.team, set())
                   | t2_researching.get(me.team, set()))
        for br, ut in _research_btn_rects(r):
            already_t2 = ut in team_t2
            is_hov = br.collidepoint(mx, my)
            if is_hov:
                hovered_type = ut
            bg = (GUI_BTN_HOVER if is_hov and not already_t2
                  else GUI_BTN_NORMAL)

            pygame.draw.rect(screen, bg, br, border_radius=4)
            pygame.draw.rect(screen, GUI_BORDER, br, 1, border_radius=4)

            st = UNIT_TYPES[ut]
            sym = st["symbol"]
            cx, cy = br.centerx, br.centery
            if already_t2:
                # Grayed out (researched or in-progress)
                color = (60, 60, 70)
                outline = (80, 80, 90)
            else:
                color = getattr(me, "_base_color", me.color)
                outline = color
            if sym is not None:
                sc = 0.9
                pts = [(cx + px * sc, cy + py * sc) for px, py in sym]
                pygame.draw.polygon(screen, color, pts)
                pygame.draw.polygon(screen, outline, pts, 1)
            else:
                pygame.draw.circle(screen, color, (cx, cy), 7)
                pygame.draw.circle(screen, outline, (cx, cy), 7, 1)

        if hovered_type is not None:
            _draw_tooltip(screen, hovered_type, r, show_t2=True)

    elif me.upgrade_state.startswith("upgrading"):
        # Show progress
        ts = tf.render("Upgrading...", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))
        secs = max(0, int(me.upgrade_timer))
        pt = sf.render(f"{secs}s remaining", True, _STAT_VALUE)
        screen.blit(pt, (r.left + 8, r.top + 28))
        # Progress bar
        bar_w = min(r.width - 16, 180)
        bar_h = 8
        bar_y = r.top + 48
        _dur = OUTPOST_UPGRADE_DURATION if me.upgrade_state == "upgrading_outpost" else RESEARCH_LAB_UPGRADE_DURATION
        progress = 1.0 - max(0.0, me.upgrade_timer / _dur)
        pygame.draw.rect(screen, (40, 40, 50), (r.left + 8, bar_y, bar_w, bar_h))
        pygame.draw.rect(screen, (200, 200, 60), (r.left + 8, bar_y, int(bar_w * progress), bar_h))

    elif me.upgrade_state == "outpost":
        ts = tf.render("Outpost", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))

    elif me.upgrade_state == "research_lab":
        ts = tf.render("Research Lab", True, _TITLE_COLOR)
        screen.blit(ts, (r.left + 8, r.top + 6))
        if me.researched_unit_type:
            rt = sf.render(f"Producing: {get_t2_name(me.researched_unit_type)}", True, _STAT_VALUE)
            screen.blit(rt, (r.left + 8, r.top + 28))


def _draw_upgrade_tooltip(screen: pygame.Surface, path: str,
                          action_rect: pygame.Rect,
                          disabled: bool = False, missing_stacks: int = 0):
    """Tooltip shown when hovering an Outpost / Research Lab upgrade button.

    Lists the upgrade's description, stat changes, weapon (where relevant),
    and build duration so the player can compare the two options at a glance.
    When *disabled* is True, an extra red requirement line is appended.
    """
    tf = _font(20)
    bf = _font(16)

    if path == "outpost":
        title = "Outpost"
        desc = (
            "Fortifies the extractor with a defensive laser, extended vision, "
            "and self-repair."
        )
        duration = OUTPOST_UPGRADE_DURATION
        # (label, value, optional positive-diff color)
        rows: list[tuple[str, str, tuple | None]] = [
            ("HP", f"+{OUTPOST_HP_BONUS}", (100, 255, 100)),
            ("Spawn bonus", f"{int(T2_SPAWN_BONUS * 100)}%", (100, 255, 100)),
            ("Self-heal", f"{OUTPOST_HEAL_PER_SEC:g} HP/s", (100, 255, 100)),
            ("Vision", f"{int(OUTPOST_LOS)} px", (100, 255, 100)),
            ("Weapon", f"{OUTPOST_LASER_DAMAGE} dmg", None),
            ("Range", f"{int(OUTPOST_LASER_RANGE)} px", None),
            ("Cooldown", f"{OUTPOST_LASER_COOLDOWN:g}s", None),
        ]
    elif path == "research_lab":
        title = "Research Lab"
        desc = (
            "Unlocks T2 production for one chosen unit type. Affected CCs "
            "spawn the T2 variant."
        )
        duration = RESEARCH_LAB_UPGRADE_DURATION
        rows = [
            ("HP", f"+{RESEARCH_LAB_HP_BONUS}", (100, 255, 100)),
            ("Spawn bonus", f"{int(T2_SPAWN_BONUS * 100)}%", (100, 255, 100)),
            ("Unlocks", "T2 unit research", (100, 255, 100)),
        ]
    else:
        return

    # Word-wrap the description manually so the tooltip can size itself.
    tt_w = 240
    inner_w = tt_w - _TT_PAD * 2
    desc_lines: list[str] = []
    words = desc.split()
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if bf.size(test)[0] <= inner_w:
            cur = test
        else:
            if cur:
                desc_lines.append(cur)
            cur = w
    if cur:
        desc_lines.append(cur)

    title_h = _TT_LINE_H + 4
    desc_h = len(desc_lines) * (_TT_LINE_H - 2) + 4
    rows_h = len(rows) * _TT_LINE_H
    footer_h = _TT_LINE_H + 2
    req_h = (_TT_LINE_H + 2) if disabled else 0
    tt_h = _TT_PAD + title_h + desc_h + rows_h + footer_h + req_h + _TT_PAD

    tt_x = action_rect.left + 10
    tt_y = action_rect.top - tt_h - 6

    rect = pygame.Rect(tt_x, tt_y, tt_w, tt_h)
    pygame.draw.rect(screen, _TT_BG, rect, border_radius=6)
    pygame.draw.rect(screen, _TT_BORDER, rect, 1, border_radius=6)

    # Title
    ts = tf.render(title, True, (220, 220, 240))
    screen.blit(ts, (tt_x + _TT_PAD, tt_y + _TT_PAD))
    y = tt_y + _TT_PAD + title_h

    # Description (italic-ish grey, wrapped)
    for line in desc_lines:
        ds = bf.render(line, True, (160, 160, 180))
        screen.blit(ds, (tt_x + _TT_PAD, y))
        y += _TT_LINE_H - 2
    y += 4

    # Stat rows
    for label, value, color in rows:
        ls = bf.render(label, True, (140, 140, 165))
        vs = bf.render(value, True, color or (200, 200, 220))
        screen.blit(ls, (tt_x + _TT_PAD, y))
        screen.blit(vs, (tt_x + _TT_PAD + 100, y))
        y += _TT_LINE_H

    # Build time footer
    ft = bf.render(f"Build time: {int(duration)}s", True, (200, 200, 100))
    screen.blit(ft, (tt_x + _TT_PAD, y))
    y += _TT_LINE_H

    # Disabled requirement line (red)
    if disabled:
        plural = "s" if missing_stacks != 1 else ""
        rt = bf.render(
            f"Requires {missing_stacks} more plating{plural} to upgrade",
            True, (255, 110, 110),
        )
        screen.blit(rt, (tt_x + _TT_PAD, y))


def _draw_tooltip(screen: pygame.Surface, utype: str,
                  action_rect: pygame.Rect, show_t2: bool = False):
    """Draw a stats tooltip above the action panel.

    When *show_t2* is True, shows the T2 name and stat values with diff
    indicators (e.g.  ``HP  130 (+30)``) for any stat that changed.
    """
    t1_stats = UNIT_TYPES[utype]
    stats = UNIT_TYPES.get(utype + "_t2", t1_stats) if show_t2 else t1_stats
    tf = _font(20)
    bf = _font(16)

    def _fmt_cd(cd):
        return f"{cd:.1f}s" if cd != int(cd) else f"{int(cd)}s"

    def _diff_str(t2_val, t1_val):
        """Return a coloured diff suffix like ' (+30)' or '' if unchanged."""
        if t2_val == t1_val:
            return "", None
        d = t2_val - t1_val
        sign = "+" if d > 0 else ""
        color = (100, 255, 100) if d > 0 else (255, 100, 100)
        return f" ({sign}{d})", color

    rows: list[tuple[str, str, str, tuple | None]] = []  # (label, value, diff_text, diff_color)

    hp_diff, hp_c = _diff_str(stats["hp"], t1_stats["hp"]) if show_t2 else ("", None)
    rows.append(("HP", str(stats["hp"]), hp_diff, hp_c))

    spd_diff, spd_c = _diff_str(stats["speed"], t1_stats["speed"]) if show_t2 else ("", None)
    rows.append(("Speed", str(stats["speed"]), spd_diff, spd_c))

    wpn = stats.get("weapon")
    t1_wpn = t1_stats.get("weapon")
    if wpn:
        if wpn["damage"] < 0:
            label = "Heal/pulse"
            val = abs(wpn["damage"])
            t1_val = abs(t1_wpn["damage"]) if t1_wpn else val
        else:
            label = "Damage"
            val = wpn["damage"]
            t1_val = t1_wpn["damage"] if t1_wpn else val
        d_diff, d_c = _diff_str(val, t1_val) if show_t2 else ("", None)
        rows.append((label, str(val), d_diff, d_c))

        r_diff, r_c = _diff_str(int(wpn["range"]), int(t1_wpn["range"])) if show_t2 and t1_wpn else ("", None)
        rows.append(("Range", str(int(wpn["range"])), r_diff, r_c))

        cd = wpn["cooldown"]
        t1_cd = t1_wpn["cooldown"] if t1_wpn else cd
        cd_diff, cd_c = ("", None)
        if show_t2 and cd != t1_cd:
            d = cd - t1_cd
            sign = "+" if d > 0 else ""
            cd_c = (255, 100, 100) if d > 0 else (100, 255, 100)  # longer CD is bad
            cd_diff = f" ({sign}{d:.1f}s)"
        rows.append(("Cooldown", _fmt_cd(cd), cd_diff, cd_c))

    name = get_t2_name(utype) if show_t2 else _display_name(utype)
    tt_h = _TT_PAD + _TT_LINE_H + 4 + len(rows) * _TT_LINE_H + _TT_PAD
    tt_w = _TT_WIDTH + (50 if show_t2 else 0)  # wider for diff text
    tt_x = action_rect.left + 10
    tt_y = action_rect.top - tt_h - 6

    rect = pygame.Rect(tt_x, tt_y, tt_w, tt_h)
    pygame.draw.rect(screen, _TT_BG, rect, border_radius=6)
    pygame.draw.rect(screen, _TT_BORDER, rect, 1, border_radius=6)

    ts = tf.render(name, True, (220, 220, 240))
    screen.blit(ts, (tt_x + _TT_PAD, tt_y + _TT_PAD))
    # T2 chevron next to name
    if show_t2:
        _draw_t2_chevron(screen, tt_x + _TT_PAD + ts.get_width() + 8,
                         tt_y + _TT_PAD + ts.get_height() // 2, size=7)

    ry = tt_y + _TT_PAD + _TT_LINE_H + 4
    for label, value, diff_text, diff_color in rows:
        ls = bf.render(label, True, (140, 140, 165))
        vs = bf.render(value, True, (200, 200, 220))
        screen.blit(ls, (tt_x + _TT_PAD, ry))
        vx = tt_x + _TT_PAD + 80
        screen.blit(vs, (vx, ry))
        if diff_text and diff_color:
            ds = bf.render(diff_text, True, diff_color)
            screen.blit(ds, (vx + vs.get_width(), ry))
        ry += _TT_LINE_H


# ── click handling ───────────────────────────────────────────────────

def handle_minimap_click(mx: int, my: int,
                         width: int, height: int, hud_h: int,
                         world_w: int, world_h: int) -> tuple[float, float] | None:
    """If (mx, my) is inside the minimap, return corresponding world coords."""
    minimap, _, _, _ = _hud_sections(width, height, hud_h)
    if not minimap.collidepoint(mx, my):
        return None
    if world_w <= 0 or world_h <= 0:
        return None
    pad = 4
    inner_w = minimap.width - pad * 2
    inner_h = minimap.height - pad * 2
    sx = inner_w / world_w
    sy = inner_h / world_h
    scale = min(sx, sy)
    mw = world_w * scale
    mh = world_h * scale
    ox = minimap.left + pad + (inner_w - mw) / 2
    oy = minimap.top + pad + (inner_h - mh) / 2
    wx = (mx - ox) / scale
    wy = (my - oy) / scale
    wx = max(0.0, min(float(world_w), wx))
    wy = max(0.0, min(float(world_h), wy))
    return (wx, wy)

def handle_hud_click(entities, mx: int, my: int,
                     width: int, height: int, hud_h: int,
                     enable_t2: bool = False, t2_upgrades: dict | None = None,
                     t2_researching: dict | None = None) -> dict | None:
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

    elif enable_t2 and len(selected) == 1 and _is_me(selected[0]):
        me = selected[0]
        if me.upgrade_state == "base" and me.is_fully_reinforced:
            for br, path, _ in _upgrade_btn_rects(action):
                if br.collidepoint(mx, my):
                    return {"action": "upgrade_extractor", "entity_id": me.entity_id, "path": path}
        elif me.upgrade_state == "choosing_research":
            for br, ut in _research_btn_rects(action):
                if br.collidepoint(mx, my):
                    return {"action": "set_research_type", "entity_id": me.entity_id, "unit_type": ut}

    else:
        for br, aid, _ in _action_btn_rects(action):
            if br.collidepoint(mx, my):
                return {"action": aid}
    return None


def handle_display_click(entities, mx: int, my: int,
                         width: int, height: int, hud_h: int):
    """If the click hit a unit box in the group grid, return that unit (proxy). Else None."""
    minimap, display, portrait, _ = _hud_sections(width, height, hud_h)
    if not display.collidepoint(mx, my):
        return None

    selected = _get_selected(entities)
    if len(selected) <= 1:
        return None

    # Replicate group grid layout from _draw_group_grid
    cf = _font(16)
    ct_h = cf.get_height()
    pad = 8
    inner = pygame.Rect(display.left + pad, display.top + pad,
                        display.width - pad * 2, display.height - pad * 2)
    grid_top = inner.top + ct_h + 4
    bs = _GROUP_BOX_SIZE
    gap = _GROUP_BOX_GAP
    row_h = bs + _GROUP_HP_H + gap + 1
    cols = max(1, (inner.width + gap) // (bs + gap))

    for i, unit in enumerate(selected):
        c = i % cols
        ro = i // cols
        bx = inner.left + c * (bs + gap)
        by = grid_top + ro * row_h
        if by + bs > inner.bottom:
            break
        box = pygame.Rect(bx, by, bs, bs)
        if box.collidepoint(mx, my):
            return unit
    return None
