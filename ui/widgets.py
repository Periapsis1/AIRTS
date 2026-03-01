"""Reusable UI widgets for menu screens."""
from __future__ import annotations
import os
import pygame
from ui.theme import (
    BTN_NORMAL, BTN_HOVER, BTN_PRESS, BTN_TEXT, BTN_BORDER,
    BTN_HEIGHT, BTN_FONT_SIZE, BTN_BORDER_RADIUS,
    BACK_BTN_SIZE, BACK_BTN_MARGIN, BACK_BTN_COLOR,
    DD_BG, DD_HOVER, DD_BORDER, DD_TEXT, DD_HEIGHT, DD_FONT_SIZE,
    SL_TRACK_COLOR, SL_FILL_COLOR, SL_HANDLE_COLOR, SL_TEXT_COLOR,
    SL_WIDTH, SL_HEIGHT, SL_HANDLE_RADIUS, SL_FONT_SIZE,
    TG_ACTIVE, TG_INACTIVE, TG_BORDER, TG_TEXT, TG_FONT_SIZE,
    GRAPH_BG, GRAPH_GRID, GRAPH_AXIS_TEXT, GRAPH_LINE_T1, GRAPH_LINE_T2,
    GRAPH_TITLE_COLOR, GRAPH_FONT_SIZE,
)

_font_cache: dict[int, pygame.font.Font] = {}
_icon_cache: dict[tuple[str, int], pygame.Surface | None] = {}

_SPRITES_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "sprites", "ui")


def _get_font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.SysFont(None, size)
    return _font_cache[size]


def _load_icon(name: str, size: int) -> pygame.Surface | None:
    """Load sprites/ui/{name}.png scaled to size×size. Returns None on failure."""
    key = (name, size)
    if key in _icon_cache:
        return _icon_cache[key]
    path = os.path.join(_SPRITES_UI_DIR, f"{name}.png")
    try:
        img = pygame.image.load(path).convert_alpha()
        img = pygame.transform.smoothscale(img, (size, size))
        _icon_cache[key] = img
    except (FileNotFoundError, pygame.error):
        _icon_cache[key] = None
    return _icon_cache[key]


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------

class Button:
    """A clickable rectangular button with hover/press states."""

    def __init__(self, x: int, y: int, w: int, h: int, label: str,
                 font_size: int = BTN_FONT_SIZE, enabled: bool = True,
                 icon: str | None = None):
        self.rect = pygame.Rect(x, y, w, h)
        self.label = label
        self.font_size = font_size
        self.enabled = enabled
        self.icon = icon
        self._pressed = False

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if the button was clicked this event."""
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._pressed = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_pressed = self._pressed
            self._pressed = False
            if was_pressed and self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface: pygame.Surface):
        mx, my = pygame.mouse.get_pos()
        hover = self.rect.collidepoint(mx, my) and self.enabled

        if not self.enabled:
            bg = (30, 30, 35)
        elif self._pressed and hover:
            bg = BTN_PRESS
        elif hover:
            bg = BTN_HOVER
        else:
            bg = BTN_NORMAL

        pygame.draw.rect(surface, bg, self.rect, border_radius=BTN_BORDER_RADIUS)
        pygame.draw.rect(surface, BTN_BORDER, self.rect, 1,
                         border_radius=BTN_BORDER_RADIUS)

        color = BTN_TEXT if self.enabled else (80, 80, 90)

        # Try icon first, fall back to text label
        icon_surf = None
        if self.icon:
            icon_size = min(self.rect.w, self.rect.h) - 6
            icon_surf = _load_icon(self.icon, icon_size)

        if icon_surf is not None:
            ix = self.rect.centerx - icon_surf.get_width() // 2
            iy = self.rect.centery - icon_surf.get_height() // 2
            surface.blit(icon_surf, (ix, iy))
        else:
            font = _get_font(self.font_size)
            text = font.render(self.label, True, color)
            tx = self.rect.centerx - text.get_width() // 2
            ty = self.rect.centery - text.get_height() // 2
            surface.blit(text, (tx, ty))


# ---------------------------------------------------------------------------
# BackButton
# ---------------------------------------------------------------------------

class BackButton:
    """A small '<' button in the top-left corner."""

    def __init__(self):
        m = BACK_BTN_MARGIN
        s = BACK_BTN_SIZE
        self.rect = pygame.Rect(m, m, s, s)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface: pygame.Surface):
        mx, my = pygame.mouse.get_pos()
        hover = self.rect.collidepoint(mx, my)
        icon_size = BACK_BTN_SIZE - 4
        icon = _load_icon("chevron-left", icon_size)
        if icon is not None:
            # Tint brighter on hover
            img = icon.copy()
            if hover:
                img.fill((80, 80, 80), special_flags=pygame.BLEND_RGB_ADD)
            ix = self.rect.centerx - icon_size // 2
            iy = self.rect.centery - icon_size // 2
            surface.blit(img, (ix, iy))
        else:
            color = (255, 255, 255) if hover else BACK_BTN_COLOR
            font = _get_font(28)
            text = font.render("<", True, color)
            tx = self.rect.centerx - text.get_width() // 2
            ty = self.rect.centery - text.get_height() // 2
            surface.blit(text, (tx, ty))


# ---------------------------------------------------------------------------
# Dropdown
# ---------------------------------------------------------------------------

class Dropdown:
    """Click-to-expand dropdown selector."""

    def __init__(self, x: int, y: int, w: int, choices: list[tuple[str, str]],
                 selected_index: int = 0):
        """choices: list of (value, display_label) tuples."""
        self.x = x
        self.y = y
        self.w = w
        self.h = DD_HEIGHT
        self.choices = choices
        self.selected_index = selected_index
        self.open = False
        self.visible = True

    @property
    def value(self) -> str:
        if not self.choices:
            return ""
        return self.choices[self.selected_index][0]

    @property
    def header_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if selection changed."""
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.open:
                for i, _ in enumerate(self.choices):
                    r = pygame.Rect(self.x, self.y + (i + 1) * self.h,
                                    self.w, self.h)
                    if r.collidepoint(event.pos):
                        self.selected_index = i
                        self.open = False
                        return True
                self.open = False
            else:
                if self.header_rect.collidepoint(event.pos):
                    self.open = True
        return False

    def draw(self, surface: pygame.Surface):
        if not self.visible:
            return
        font = _get_font(DD_FONT_SIZE)
        mx, my = pygame.mouse.get_pos()

        # header
        hr = self.header_rect
        pygame.draw.rect(surface, DD_BG, hr, border_radius=4)
        pygame.draw.rect(surface, DD_BORDER, hr, 1, border_radius=4)

        if self.choices:
            label = self.choices[self.selected_index][1]
        else:
            label = "(none)"
        text = font.render(label, True, DD_TEXT)
        surface.blit(text, (hr.x + 8, hr.centery - text.get_height() // 2))

        # arrow
        arrow = font.render("v" if not self.open else "^", True, DD_TEXT)
        surface.blit(arrow, (hr.right - 20, hr.centery - arrow.get_height() // 2))

        if self.open:
            for i, (_, display) in enumerate(self.choices):
                r = pygame.Rect(self.x, self.y + (i + 1) * self.h,
                                self.w, self.h)
                hover = r.collidepoint(mx, my)
                bg = DD_HOVER if hover else DD_BG
                pygame.draw.rect(surface, bg, r)
                pygame.draw.rect(surface, DD_BORDER, r, 1)
                t = font.render(display, True, DD_TEXT)
                surface.blit(t, (r.x + 8, r.centery - t.get_height() // 2))


# ---------------------------------------------------------------------------
# Slider
# ---------------------------------------------------------------------------

class Slider:
    """Horizontal slider with label and value display."""

    def __init__(self, x: int, y: int, w: int, label: str,
                 min_val: int, max_val: int, value: int, step: int = 1):
        self.x = x
        self.y = y
        self.w = w
        self.label = label
        self.min_val = min_val
        self.max_val = max_val
        self.value = value
        self.step = step
        self._dragging = False

    @property
    def track_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y + 20, self.w, SL_HEIGHT)

    @property
    def _fraction(self) -> float:
        rng = self.max_val - self.min_val
        if rng == 0:
            return 0.0
        return (self.value - self.min_val) / rng

    def _handle_x(self) -> int:
        return int(self.x + self._fraction * self.w)

    def _value_from_x(self, mx: int) -> int:
        frac = max(0.0, min(1.0, (mx - self.x) / self.w))
        raw = self.min_val + frac * (self.max_val - self.min_val)
        snapped = round(raw / self.step) * self.step
        return max(self.min_val, min(self.max_val, snapped))

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if value changed."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hx = self._handle_x()
            hy = self.y + 20 + SL_HEIGHT // 2
            if abs(event.pos[0] - hx) < SL_HANDLE_RADIUS + 4 and \
               abs(event.pos[1] - hy) < SL_HANDLE_RADIUS + 4:
                self._dragging = True
            elif self.track_rect.inflate(0, 12).collidepoint(event.pos):
                self._dragging = True
                new = self._value_from_x(event.pos[0])
                if new != self.value:
                    self.value = new
                    return True
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            new = self._value_from_x(event.pos[0])
            if new != self.value:
                self.value = new
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
        return False

    def draw(self, surface: pygame.Surface):
        font = _get_font(SL_FONT_SIZE)
        # label and value
        lbl = font.render(f"{self.label}: {self.value}", True, SL_TEXT_COLOR)
        surface.blit(lbl, (self.x, self.y))

        # track
        tr = self.track_rect
        pygame.draw.rect(surface, SL_TRACK_COLOR, tr, border_radius=4)

        # fill
        fill_w = int(self._fraction * self.w)
        if fill_w > 0:
            fill_r = pygame.Rect(tr.x, tr.y, fill_w, SL_HEIGHT)
            pygame.draw.rect(surface, SL_FILL_COLOR, fill_r, border_radius=4)

        # handle
        hx = self._handle_x()
        hy = tr.centery
        pygame.draw.circle(surface, SL_HANDLE_COLOR, (hx, hy), SL_HANDLE_RADIUS)


# ---------------------------------------------------------------------------
# ToggleGroup
# ---------------------------------------------------------------------------

class ToggleGroup:
    """Mutually exclusive row of buttons."""

    def __init__(self, x: int, y: int, options: list[tuple[str, str]],
                 selected_index: int = 0, btn_w: int = 140, btn_h: int = 32):
        """options: list of (value, display_label) tuples."""
        self.x = x
        self.y = y
        self.options = options
        self.selected_index = selected_index
        self.btn_w = btn_w
        self.btn_h = btn_h

    @property
    def value(self) -> str:
        return self.options[self.selected_index][0]

    def _rects(self) -> list[pygame.Rect]:
        rects = []
        for i in range(len(self.options)):
            rects.append(pygame.Rect(
                self.x + i * (self.btn_w + 2), self.y,
                self.btn_w, self.btn_h,
            ))
        return rects

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if selection changed."""
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            for i, r in enumerate(self._rects()):
                if r.collidepoint(event.pos) and i != self.selected_index:
                    self.selected_index = i
                    return True
        return False

    def draw(self, surface: pygame.Surface):
        font = _get_font(TG_FONT_SIZE)
        mx, my = pygame.mouse.get_pos()
        for i, (_, label) in enumerate(self.options):
            r = self._rects()[i]
            active = i == self.selected_index
            hover = r.collidepoint(mx, my)
            bg = TG_ACTIVE if active else (TG_BORDER if hover else TG_INACTIVE)
            pygame.draw.rect(surface, bg, r, border_radius=4)
            pygame.draw.rect(surface, TG_BORDER, r, 1, border_radius=4)
            color = (255, 255, 255) if active else TG_TEXT
            t = font.render(label, True, color)
            surface.blit(t, (r.centerx - t.get_width() // 2,
                             r.centery - t.get_height() // 2))


# ---------------------------------------------------------------------------
# LineGraph
# ---------------------------------------------------------------------------

class LineGraph:
    """Draws a line graph with two data series (team 1 and team 2)."""

    def __init__(
        self,
        x: int, y: int, w: int, h: int,
        title: str = "",
        color1: tuple = GRAPH_LINE_T1,
        color2: tuple = GRAPH_LINE_T2,
    ):
        self.rect = pygame.Rect(x, y, w, h)
        self.title = title
        self.color1 = color1
        self.color2 = color2
        self.data1: list[float] = []
        self.data2: list[float] = []
        self.x_labels: list[str] | None = None  # optional time labels
        self._hover_index: int | None = None
        self._hover_mouse_y: int = 0

    def set_data(self, data1: list[float], data2: list[float],
                 x_labels: list[str] | None = None):
        self.data1 = data1
        self.data2 = data2
        self.x_labels = x_labels

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Track mouse hover for tooltip. Returns True if hover state changed."""
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            # Compute plot area
            margin_l = 50
            margin_r = 15
            margin_t = 28 if self.title else 12
            margin_b = 8
            gx = self.rect.x + margin_l
            gy = self.rect.y + margin_t
            gw = self.rect.w - margin_l - margin_r
            gh = self.rect.h - margin_t - margin_b

            n = max(len(self.data1), len(self.data2))
            if gw > 0 and gh > 0 and n >= 2 and gx <= mx <= gx + gw and gy <= my <= gy + gh:
                frac = (mx - gx) / gw
                idx = round(frac * (n - 1))
                idx = max(0, min(idx, n - 1))
                old = self._hover_index
                self._hover_index = idx
                self._hover_mouse_y = my
                return old != idx
            else:
                old = self._hover_index
                self._hover_index = None
                return old is not None
        return False

    def draw(self, surface: pygame.Surface):
        x, y, w, h = self.rect.x, self.rect.y, self.rect.w, self.rect.h
        font = _get_font(GRAPH_FONT_SIZE)

        # Background
        pygame.draw.rect(surface, GRAPH_BG, self.rect, border_radius=4)
        pygame.draw.rect(surface, GRAPH_GRID, self.rect, 1, border_radius=4)

        # Title
        if self.title:
            title_font = _get_font(GRAPH_FONT_SIZE + 4)
            ts = title_font.render(self.title, True, GRAPH_TITLE_COLOR)
            surface.blit(ts, (x + w // 2 - ts.get_width() // 2, y + 4))

        # Margins inside the graph area
        margin_l = 50
        margin_r = 15
        margin_t = 28 if self.title else 12
        margin_b = 8

        gx = x + margin_l
        gy = y + margin_t
        gw = w - margin_l - margin_r
        gh = h - margin_t - margin_b

        if gw <= 0 or gh <= 0:
            return

        n1 = len(self.data1)
        n2 = len(self.data2)
        n = max(n1, n2)
        if n < 2:
            no_data = font.render("No data", True, GRAPH_AXIS_TEXT)
            surface.blit(no_data, (gx + gw // 2 - no_data.get_width() // 2,
                                   gy + gh // 2 - no_data.get_height() // 2))
            return

        # Compute Y range
        all_vals = self.data1 + self.data2
        y_min = 0.0
        y_max = max(all_vals) if all_vals else 1.0
        if y_max <= y_min:
            y_max = y_min + 1.0

        # Add 10% headroom
        y_max *= 1.1

        # Grid lines (4 horizontal)
        for i in range(5):
            frac = i / 4.0
            ly = gy + gh - int(frac * gh)
            pygame.draw.line(surface, GRAPH_GRID, (gx, ly), (gx + gw, ly), 1)
            val = y_min + frac * (y_max - y_min)
            if y_max >= 1000:
                lbl = f"{val:.0f}"
            elif y_max >= 10:
                lbl = f"{val:.0f}"
            else:
                lbl = f"{val:.1f}"
            ls = font.render(lbl, True, GRAPH_AXIS_TEXT)
            surface.blit(ls, (gx - ls.get_width() - 4, ly - ls.get_height() // 2))

        # X-axis labels (time)
        num_x_labels = min(6, n)
        for i in range(num_x_labels):
            idx = int(i * (n - 1) / max(num_x_labels - 1, 1))
            lx = gx + int(idx * gw / (n - 1))
            if self.x_labels and idx < len(self.x_labels):
                lbl = self.x_labels[idx]
            else:
                lbl = str(idx)
            ls = font.render(lbl, True, GRAPH_AXIS_TEXT)
            surface.blit(ls, (lx - ls.get_width() // 2, gy + gh + 4))

        def _data_to_points(data: list[float]) -> list[tuple[int, int]]:
            pts = []
            count = len(data)
            for i, v in enumerate(data):
                px = gx + int(i * gw / (n - 1))
                frac = (v - y_min) / (y_max - y_min) if y_max > y_min else 0
                py = gy + gh - int(frac * gh)
                pts.append((px, py))
            return pts

        # Draw lines
        if n1 >= 2:
            pts1 = _data_to_points(self.data1)
            pygame.draw.lines(surface, self.color1, False, pts1, 2)
        if n2 >= 2:
            pts2 = _data_to_points(self.data2)
            pygame.draw.lines(surface, self.color2, False, pts2, 2)

        # Hover tooltip
        if self._hover_index is not None and n >= 2:
            hi = self._hover_index
            hx_pos = gx + int(hi * gw / (n - 1))

            # Vertical line
            line_surf = pygame.Surface((1, gh), pygame.SRCALPHA)
            line_surf.fill((255, 255, 255, 80))
            surface.blit(line_surf, (hx_pos, gy))

            # Dots on data lines
            def _val_y(val: float) -> int:
                frac = (val - y_min) / (y_max - y_min) if y_max > y_min else 0
                return gy + gh - int(frac * gh)

            v1 = self.data1[hi] if hi < n1 else None
            v2 = self.data2[hi] if hi < n2 else None
            if v1 is not None:
                pygame.draw.circle(surface, self.color1, (hx_pos, _val_y(v1)), 4)
            if v2 is not None:
                pygame.draw.circle(surface, self.color2, (hx_pos, _val_y(v2)), 4)

            # Tooltip box
            tip_font = _get_font(GRAPH_FONT_SIZE)
            time_str = self.x_labels[hi] if self.x_labels and hi < len(self.x_labels) else str(hi)
            t1_str = f"T1: {int(v1)}" if v1 is not None else "T1: -"
            t2_str = f"T2: {int(v2)}" if v2 is not None else "T2: -"

            time_s = tip_font.render(time_str, True, (220, 220, 240))
            t1_s = tip_font.render(t1_str, True, self.color1)
            t2_s = tip_font.render(t2_str, True, self.color2)

            tip_w = max(time_s.get_width(), t1_s.get_width(), t2_s.get_width()) + 12
            tip_h = time_s.get_height() + t1_s.get_height() + t2_s.get_height() + 12

            # Position tooltip to stay inside graph bounds
            tip_x = hx_pos + 10
            tip_y = self._hover_mouse_y - tip_h // 2
            if tip_x + tip_w > gx + gw:
                tip_x = hx_pos - tip_w - 10
            tip_y = max(gy, min(tip_y, gy + gh - tip_h))

            tip_rect = pygame.Rect(tip_x, tip_y, tip_w, tip_h)
            pygame.draw.rect(surface, (20, 20, 32), tip_rect, border_radius=3)
            pygame.draw.rect(surface, (80, 80, 110), tip_rect, 1, border_radius=3)

            cy_tip = tip_y + 4
            surface.blit(time_s, (tip_x + 6, cy_tip))
            cy_tip += time_s.get_height() + 2
            surface.blit(t1_s, (tip_x + 6, cy_tip))
            cy_tip += t1_s.get_height() + 2
            surface.blit(t2_s, (tip_x + 6, cy_tip))
