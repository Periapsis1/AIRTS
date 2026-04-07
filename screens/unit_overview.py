"""Unit overview screen — browse all unit/building types with stats, FOV, and passives."""
from __future__ import annotations
import math
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, SIDEBAR_BG, SIDEBAR_WIDTH, SIDEBAR_BTN_HEIGHT,
    CONTENT_TEXT, CONTENT_HEADING, CONTENT_FONT_SIZE, HEADING_FONT_SIZE,
    TG_ACTIVE, TG_INACTIVE, TG_BORDER,
)
from ui.widgets import BackButton, Button
from config.unit_types import UNIT_TYPES, get_spawnable_types, get_t2_name, get_t2_type
from config.settings import (
    TEAM1_COLOR, TEAM1_SELECTED_COLOR,
    CC_LASER_DAMAGE, CC_LASER_RANGE, CC_LASER_COOLDOWN, CC_RADIUS,
    CC_SPAWN_INTERVAL,
    METAL_EXTRACTOR_SPAWN_BONUS,
    REINFORCE_HP_BONUS, REINFORCE_MAX_STACKS, REINFORCE_STACK_INTERVAL,
    REINFORCE_BONUS_MULTIPLIER,
    REACTIVE_ARMOR_INTERVAL, REACTIVE_ARMOR_MAX_STACKS, REACTIVE_ARMOR_REDUCTION,
    ELECTRIC_ARMOR_INTERVAL, ELECTRIC_ARMOR_MAX_STACKS, ELECTRIC_ARMOR_REDUCTION,
    ELECTRIC_ARMOR_REGEN_PER_STACK, ELECTRIC_ARMOR_SPEED_BONUS,
    OVERCLOCK_RANGE, OVERCLOCK_REGEN, OVERCLOCK_BONUS,
    OVERCLOCK_REGEN_T2, OVERCLOCK_BONUS_T2,
)
from core.helpers import hexagon_points

# -- passive ability descriptions per unit type --------------------------------

_PASSIVES: dict[str, list[dict[str, str]]] = {
    "soldier": [],
    "medic": [
        {"name": "Heal Beam",
         "desc": "Heals friendly units instead of dealing damage."},
    ],
    "tank": [
        {"name": "Reactive Armor",
         "desc": (f"Every {REACTIVE_ARMOR_INTERVAL:.0f}s gain a charge "
                  f"(max {REACTIVE_ARMOR_MAX_STACKS}). Each charge reduces "
                  f"incoming damage by {REACTIVE_ARMOR_REDUCTION * 100:.0f}%. "
                  "All charges consumed when hit.")},
    ],
    "sniper": [
        {"name": "Focus",
         "desc": "After firing, speed drops to 25% and gradually recovers over 3s."},
    ],
    "machine_gunner": [],
    "scout": [
        {"name": "Pack Hunter",
         "desc": "Spawns in groups of 3."},
    ],
    "shockwave": [
        {"name": "Chain Lightning",
         "desc": "Laser chains to nearby enemies within 70px after a 0.2s delay."},
    ],
    "artillery": [],
    "engineer": [
        {"name": "Overclock",
         "desc": (f"Allied metal extractors within {OVERCLOCK_RANGE:.0f}px gain "
                  f"+{OVERCLOCK_REGEN:.0f} HP/s regeneration and an extra "
                  f"+{OVERCLOCK_BONUS * 100:.0f}% spawn boost.")},
    ],
    "command_center": [
        {"name": "Unit Production",
         "desc": (f"Spawns a unit every {CC_SPAWN_INTERVAL:.0f}s. "
                  "Metal extractors boost spawn speed.")},
    ],
    "metal_extractor": [
        {"name": "Spawn Boost",
         "desc": (f"Provides +{METAL_EXTRACTOR_SPAWN_BONUS * 100:.0f}% spawn "
                  "speed to its Command Center.")},
        {"name": "Reinforce",
         "desc": (f"Builds plating every {REINFORCE_STACK_INTERVAL:.0f}s "
                  f"(max {REINFORCE_MAX_STACKS}). At full stacks gains "
                  f"+{REINFORCE_HP_BONUS} HP and "
                  f"{REINFORCE_BONUS_MULTIPLIER}x spawn bonus.")},
    ],
    # -- T2 passives --
    "soldier_t2": [
        {"name": "Combat Stim",
         "desc": "For every 10 missing HP: -0.1s weapon cooldown and +5% movement speed."},
    ],
    "medic_t2": [
        {"name": "Heal Beam",
         "desc": "Heals friendly units instead of dealing damage."},
    ],
    "tank_t2": [
        {"name": "Electric Armor",
         "desc": (f"Gains a stack every {ELECTRIC_ARMOR_INTERVAL:.0f}s "
                  f"(max {ELECTRIC_ARMOR_MAX_STACKS}). If any stacks are active, gain "
                  f"{ELECTRIC_ARMOR_REDUCTION * 100:.0f}% damage reduction. "
                  f"Each stack: +{ELECTRIC_ARMOR_REGEN_PER_STACK:.2f} HP/s regen, "
                  f"+{ELECTRIC_ARMOR_SPEED_BONUS * 100:.0f}% speed. "
                  "Loses one stack when hit.")},
    ],
    "sniper_t2": [
        {"name": "Focus",
         "desc": "After firing, speed drops to 25% and gradually recovers over 3s."},
    ],
    "machine_gunner_t2": [],
    "scout_t2": [
        {"name": "Swarm",
         "desc": "Spawns in groups of 6."},
    ],
    "shockwave_t2": [
        {"name": "Arc Lightning",
         "desc": "Laser chains to nearby enemies within 50px after a 0.15s delay."},
    ],
    "artillery_t2": [],
    "engineer_t2": [
        {"name": "Overclock",
         "desc": (f"Allied metal extractors within {OVERCLOCK_RANGE:.0f}px gain "
                  f"+{OVERCLOCK_REGEN_T2:.0f} HP/s regeneration and an extra "
                  f"+{OVERCLOCK_BONUS_T2 * 100:.0f}% spawn boost.")},
    ],
}

# Stat diff colors
_DIFF_BETTER = (100, 255, 100)
_DIFF_WORSE = (255, 100, 100)
_DIFF_NEUTRAL = (200, 200, 200)


class UnitOverviewScreen(BaseScreen):
    """Interactive browser for unit types with enlarged symbols and stats."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)
        # Sidebar: only T1 spawnable + buildings
        spawnable = list(get_spawnable_types().keys())
        buildings = [k for k, v in UNIT_TYPES.items() if v.get("is_building", False)]
        self._types = spawnable + buildings
        self._selected = 0
        self._show_t2 = False
        self._back = BackButton()

        # T2 toggle button
        self._t2_btn = Button(0, 0, 100, 28, "Show T2", font_size=18)

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
                            self._show_t2 = False

                if self._t2_btn.handle_event(event):
                    self._show_t2 = not self._show_t2

            self._draw()
            self.clock.tick(60)

    # -- drawing ----------------------------------------------------------------

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
        base_type = self._types[self._selected]
        t2_key = get_t2_type(base_type)
        has_t2 = t2_key in UNIT_TYPES

        if self._show_t2 and has_t2:
            utype = t2_key
        else:
            utype = base_type

        stats = UNIT_TYPES[utype]
        content_x = SIDEBAR_WIDTH + 30
        content_w = self.width - SIDEBAR_WIDTH - 60

        # Heading
        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        if self._show_t2 and has_t2:
            heading_text = get_t2_name(base_type)
        else:
            heading_text = utype.replace("_", " ").title()
        heading = font_h.render(heading_text, True, CONTENT_HEADING)
        self.screen.blit(heading, (content_x, 20))

        # T2 toggle button (only for units that have T2 variants)
        if has_t2:
            self._t2_btn.rect.x = content_x + heading.get_width() + 15
            self._t2_btn.rect.y = 22
            btn_label = "Show T1" if self._show_t2 else "Show T2"
            self._t2_btn.label = btn_label
            self._t2_btn.draw(self.screen)

        # Unit symbol + FOV arc
        sym_cx = content_x + content_w // 2
        sym_cy = 110
        scale = 4.0
        self._draw_unit_symbol(utype, stats, sym_cx, sym_cy, scale)
        self._draw_fov_preview(stats, utype, sym_cx, sym_cy)

        # Stats table (with diffs when showing T2)
        t1_stats = UNIT_TYPES.get(base_type) if self._show_t2 and has_t2 else None
        table_bottom = self._draw_stats(stats, utype, content_x, content_w, 195,
                                        t1_stats=t1_stats)

        # Passive abilities
        passives = _PASSIVES.get(utype, [])
        if passives:
            self._draw_passives(passives, content_x, content_w, table_bottom + 14)

        pygame.display.flip()

    def _draw_unit_symbol(self, utype: str, stats: dict,
                          cx: float, cy: float, scale: float):
        """Draw the enlarged unit/building symbol."""
        if utype == "command_center":
            hex_pts = hexagon_points(CC_RADIUS)
            scaled = [(cx + px * scale, cy + py * scale) for px, py in hex_pts]
            pygame.draw.polygon(self.screen, TEAM1_COLOR, scaled)
            pygame.draw.polygon(self.screen, TEAM1_SELECTED_COLOR, scaled, 2)
        elif utype == "metal_extractor":
            r = stats["radius"] * scale
            s = r * math.sqrt(3) / 2
            pts = [(cx, cy - r), (cx - s, cy + r / 2), (cx + s, cy + r / 2)]
            pygame.draw.polygon(self.screen, TEAM1_COLOR, pts)
            pygame.draw.polygon(self.screen, TEAM1_SELECTED_COLOR, pts, 2)
        else:
            symbol = stats["symbol"]
            if symbol is not None:
                pts = [(cx + px * scale, cy + py * scale) for px, py in symbol]
                pygame.draw.polygon(self.screen, TEAM1_COLOR, pts)
                pygame.draw.polygon(self.screen, TEAM1_SELECTED_COLOR, pts, 2)
            else:
                radius = int(stats["radius"] * scale)
                pygame.draw.circle(self.screen, TEAM1_COLOR, (cx, cy), radius)
                pygame.draw.circle(self.screen, TEAM1_SELECTED_COLOR,
                                   (cx, cy), radius, 2)

    def _draw_fov_preview(self, stats: dict, utype: str,
                          cx: float, cy: float):
        """Draw a FOV arc overlay on the unit preview."""
        fov_deg = stats.get("fov", 90)
        fov_rad = math.radians(fov_deg)
        arc_r = 55
        facing = 0.0  # face right

        if fov_rad >= math.tau - 0.01:
            # Full circle — just draw ring
            temp = pygame.Surface((arc_r * 2 + 4, arc_r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(temp, (255, 0, 255, 40), (arc_r + 2, arc_r + 2), arc_r)
            pygame.draw.circle(temp, (255, 0, 255, 70), (arc_r + 2, arc_r + 2), arc_r, 1)
            self.screen.blit(temp, (int(cx) - arc_r - 2, int(cy) - arc_r - 2))
        else:
            # Pie wedge
            half_fov = fov_rad / 2
            steps = max(int(fov_deg / 3), 8)
            start = facing - half_fov

            points = [(cx, cy)]
            for i in range(steps + 1):
                a = start + fov_rad * i / steps
                points.append((cx + arc_r * math.cos(a),
                                cy + arc_r * math.sin(a)))
            points.append((cx, cy))

            temp_size = arc_r * 2 + 20
            temp = pygame.Surface((temp_size, temp_size), pygame.SRCALPHA)
            ox = temp_size // 2 - cx
            oy = temp_size // 2 - cy
            shifted = [(px + ox, py + oy) for px, py in points]

            if len(shifted) >= 3:
                pygame.draw.polygon(temp, (255, 0, 255, 25), shifted)
                pygame.draw.lines(temp, (255, 0, 255, 70), False, shifted, 1)
            self.screen.blit(temp, (int(cx) - temp_size // 2,
                                     int(cy) - temp_size // 2))

    def _draw_stats(self, stats: dict, utype: str,
                    content_x: int, content_w: int, y_start: int,
                    t1_stats: dict | None = None) -> int:
        """Draw the stats table. When t1_stats is provided, show diffs. Returns y after last row."""
        font_c = pygame.font.SysFont(None, CONTENT_FONT_SIZE)
        row_h = 24

        stat_rows: list[tuple[str, str, str]] = []  # (label, value, diff_text)

        def _add(label: str, val, t1_val=None, higher_is_better: bool = True):
            val_str = str(val)
            diff = ""
            if t1_stats is not None and t1_val is not None and val != t1_val:
                d = val - t1_val if isinstance(val, (int, float)) else 0
                if d != 0:
                    sign = "+" if d > 0 else ""
                    if isinstance(d, float):
                        diff = f" ({sign}{d:.1f})"
                    else:
                        diff = f" ({sign}{d})"
            stat_rows.append((label, val_str, diff))

        t1 = t1_stats or {}
        _add("HP", stats["hp"], t1.get("hp"))
        _add("Speed", stats["speed"], t1.get("speed"))
        _add("Radius", stats["radius"], t1.get("radius"))
        _add("FOV", f"{stats.get('fov', 90)}\u00b0")

        # Weapon stats
        wpn = stats.get("weapon")
        t1_wpn = t1.get("weapon") if t1 else None
        if utype == "command_center":
            wpn = {
                "damage": CC_LASER_DAMAGE,
                "range": CC_LASER_RANGE,
                "cooldown": CC_LASER_COOLDOWN,
            }

        if wpn:
            dmg = wpn["damage"]
            t1_dmg = t1_wpn["damage"] if t1_wpn else None
            if dmg < 0:
                _add("Heal/pulse", abs(dmg), abs(t1_dmg) if t1_dmg is not None else None)
            else:
                _add("Damage", dmg, t1_dmg)
            _add("Range", wpn["range"], t1_wpn["range"] if t1_wpn else None)

            cd = wpn["cooldown"]
            t1_cd = t1_wpn["cooldown"] if t1_wpn else None
            cd_str = f"{cd}s"
            diff = ""
            if t1_cd is not None and cd != t1_cd:
                d = cd - t1_cd
                sign = "+" if d > 0 else ""
                diff = f" ({sign}{d:.1f}s)"
            stat_rows.append(("Cooldown", cd_str, diff))

            if cd > 0:
                dps = abs(dmg) / cd
                t1_dps = abs(t1_dmg) / t1_cd if t1_wpn and t1_cd and t1_cd > 0 and t1_dmg is not None else None
                label = "HPS" if dmg < 0 else "DPS"
                dps_str = f"{dps:.1f}"
                diff = ""
                if t1_dps is not None and abs(dps - t1_dps) > 0.05:
                    d = dps - t1_dps
                    sign = "+" if d > 0 else ""
                    diff = f" ({sign}{d:.1f})"
                stat_rows.append((label, dps_str, diff))

        elif not stats["can_attack"]:
            stat_rows.append(("Can Attack", "No", ""))

        spawn_count = stats.get("spawn_count")
        t1_spawn = t1.get("spawn_count") if t1 else None
        if spawn_count and spawn_count > 1:
            diff = ""
            if t1_spawn and spawn_count != t1_spawn:
                d = spawn_count - t1_spawn
                diff = f" ({'+' if d > 0 else ''}{d})"
            stat_rows.append(("Spawn Count", str(spawn_count), diff))

        # Splash stats
        if wpn and wpn.get("splash_radius", 0) > 0:
            _add("Splash Radius", wpn["splash_radius"],
                 t1_wpn.get("splash_radius") if t1_wpn else None)
            _add("Splash Dmg", f"{wpn.get('splash_damage_max', 0)}-{wpn.get('splash_damage_min', 0)}")

        for i, (label, value, diff) in enumerate(stat_rows):
            y = y_start + i * row_h
            if i % 2 == 0:
                row_rect = pygame.Rect(content_x - 5, y - 2,
                                       content_w + 10, row_h)
                pygame.draw.rect(self.screen, (20, 20, 32), row_rect)

            lbl_surf = font_c.render(label, True, (160, 160, 180))
            val_surf = font_c.render(value, True, CONTENT_TEXT)
            self.screen.blit(lbl_surf, (content_x, y))
            self.screen.blit(val_surf, (content_x + 160, y))

            if diff:
                # Color based on sign
                if "+" in diff and "-" not in diff:
                    diff_color = _DIFF_BETTER
                elif "-" in diff:
                    diff_color = _DIFF_WORSE
                else:
                    diff_color = _DIFF_NEUTRAL
                # Cooldown: lower is better, so flip colors
                if label == "Cooldown":
                    if diff_color == _DIFF_BETTER:
                        diff_color = _DIFF_WORSE
                    elif diff_color == _DIFF_WORSE:
                        diff_color = _DIFF_BETTER
                diff_surf = font_c.render(diff, True, diff_color)
                self.screen.blit(diff_surf, (content_x + 160 + val_surf.get_width(), y))

        return y_start + len(stat_rows) * row_h

    def _draw_passives(self, passives: list[dict[str, str]],
                       content_x: int, content_w: int, y_start: int):
        """Draw passive ability cards below the stats table."""
        font_name = pygame.font.SysFont(None, CONTENT_FONT_SIZE + 2)
        font_desc = pygame.font.SysFont(None, CONTENT_FONT_SIZE - 1)

        pad = 8
        gap = 8
        y = y_start

        for passive in passives:
            desc_lines = _wrap_text(passive["desc"], font_desc,
                                    content_w - pad * 2 - 10)
            card_h = pad * 2 + 20 + len(desc_lines) * 16

            card_rect = pygame.Rect(content_x - 5, y, content_w + 10, card_h)
            pygame.draw.rect(self.screen, (25, 25, 40), card_rect,
                             border_radius=4)
            pygame.draw.rect(self.screen, (60, 60, 85), card_rect, 1,
                             border_radius=4)

            # Ability name
            name_surf = font_name.render(passive["name"], True, (220, 200, 120))
            self.screen.blit(name_surf, (content_x + pad, y + pad))

            # Description
            for j, line in enumerate(desc_lines):
                line_surf = font_desc.render(line, True, (170, 170, 190))
                self.screen.blit(line_surf,
                                 (content_x + pad, y + pad + 20 + j * 16))

            y += card_h + gap


# -- helpers -------------------------------------------------------------------

def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Word-wrap a string to fit within max_width pixels."""
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
