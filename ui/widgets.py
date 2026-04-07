"""Reusable UI widgets for menu screens."""
from __future__ import annotations
import os
import pygame
from ui.theme import (
    BTN_NORMAL, BTN_HOVER, BTN_PRESS, BTN_TEXT, BTN_BORDER,
    BTN_HEIGHT, BTN_FONT_SIZE, BTN_BORDER_RADIUS,
    BACK_BTN_SIZE, BACK_BTN_MARGIN, BACK_BTN_COLOR,
    DD_BG, DD_HOVER, DD_BORDER, DD_TEXT, DD_HEIGHT, DD_FONT_SIZE,
    TI_BG, TI_ACTIVE_BG, TI_BORDER, TI_ACTIVE_BORDER, TI_TEXT, TI_PLACEHOLDER,
    SL_TRACK_COLOR, SL_FILL_COLOR, SL_HANDLE_COLOR, SL_TEXT_COLOR,
    SL_WIDTH, SL_HEIGHT, SL_HANDLE_RADIUS, SL_FONT_SIZE,
    TG_ACTIVE, TG_INACTIVE, TG_BORDER, TG_TEXT, TG_FONT_SIZE,
    CB_BOX, CB_CHECK, CB_BORDER, CB_DISABLED,
    GRAPH_BG, GRAPH_GRID, GRAPH_AXIS_TEXT, GRAPH_LINE_T1, GRAPH_LINE_T2,
    GRAPH_TITLE_COLOR, GRAPH_FONT_SIZE,
    DEBUG_LINE_COLORS,
)

_font_cache: dict[int, pygame.font.Font] = {}
_icon_cache: dict[tuple[str, int], pygame.Surface | None] = {}

from core.paths import asset_path
_SPRITES_UI_DIR = asset_path("sprites", "ui")


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
    """Click-to-expand dropdown selector with scrolling support."""

    def __init__(self, x: int, y: int, w: int, choices: list[tuple[str, str]],
                 selected_index: int = 0, max_visible: int = 8):
        """choices: list of (value, display_label) tuples."""
        self.x = x
        self.y = y
        self.w = w
        self.h = DD_HEIGHT
        self.choices = choices
        self.selected_index = selected_index
        self.open = False
        self.visible = True
        self._max_visible = max_visible
        self._scroll_offset = 0

    @property
    def value(self) -> str:
        if not self.choices:
            return ""
        return self.choices[self.selected_index][0]

    @property
    def header_rect(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def _list_y(self) -> int:
        """Y coordinate for the top of the open list; opens upward if needed."""
        n = min(self._max_visible, len(self.choices))
        screen_h = pygame.display.get_surface().get_height()
        if self.y + self.h + n * self.h > screen_h:
            return self.y - n * self.h  # open upward
        return self.y + self.h

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if selection changed."""
        if not self.visible:
            return False
        if event.type == pygame.MOUSEWHEEL and self.open:
            max_scroll = max(0, len(self.choices) - self._max_visible)
            self._scroll_offset = max(0, min(max_scroll, self._scroll_offset - event.y))
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.open:
                n = min(self._max_visible, len(self.choices))
                ly = self._list_y()
                for i in range(n):
                    r = pygame.Rect(self.x, ly + i * self.h, self.w, self.h)
                    if r.collidepoint(event.pos):
                        self.selected_index = self._scroll_offset + i
                        self.open = False
                        return True
                self.open = False
            else:
                if self.header_rect.collidepoint(event.pos):
                    self.open = True
                    # Scroll so the selected item is visible
                    n = min(self._max_visible, len(self.choices))
                    self._scroll_offset = max(0, min(
                        self.selected_index,
                        len(self.choices) - n,
                    ))
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
            n = min(self._max_visible, len(self.choices))
            ly = self._list_y()
            can_scroll_up   = self._scroll_offset > 0
            can_scroll_down = self._scroll_offset + n < len(self.choices)
            for i in range(n):
                choice_idx = self._scroll_offset + i
                _, display = self.choices[choice_idx]
                r = pygame.Rect(self.x, ly + i * self.h, self.w, self.h)
                hover = r.collidepoint(mx, my)
                bg = DD_HOVER if hover else DD_BG
                pygame.draw.rect(surface, bg, r)
                pygame.draw.rect(surface, DD_BORDER, r, 1)
                t = font.render(display, True, DD_TEXT)
                surface.blit(t, (r.x + 8, r.centery - t.get_height() // 2))
                # Scroll indicator triangles on first/last visible row
                cx = r.right - 10
                cy = r.centery
                if i == 0 and can_scroll_up:
                    pygame.draw.polygon(surface, DD_TEXT, [
                        (cx - 5, cy + 3), (cx + 5, cy + 3), (cx, cy - 4),
                    ])
                elif i == n - 1 and can_scroll_down:
                    pygame.draw.polygon(surface, DD_TEXT, [
                        (cx - 5, cy - 3), (cx + 5, cy - 3), (cx, cy + 4),
                    ])


# ---------------------------------------------------------------------------
# TextInput
# ---------------------------------------------------------------------------

class TextInput:
    """Single-line editable text field with placeholder support."""

    def __init__(self, x: int, y: int, w: int,
                 text: str = "", placeholder: str = "",
                 max_len: int = 24):
        self.rect = pygame.Rect(x, y, w, DD_HEIGHT)
        self.text = text
        self.placeholder = placeholder
        self.max_len = max_len
        self.active = False
        self.visible = True

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if the event was consumed by the input."""
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.active = True
                return True
            else:
                self.active = False
                return False
        if self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                self.active = False
            elif event.unicode and event.unicode.isprintable() and len(self.text) < self.max_len:
                self.text += event.unicode
            return True
        return False

    def draw(self, surface: pygame.Surface):
        if not self.visible:
            return
        font = _get_font(DD_FONT_SIZE)

        bg = TI_ACTIVE_BG if self.active else TI_BG
        border = TI_ACTIVE_BORDER if self.active else TI_BORDER
        pygame.draw.rect(surface, bg, self.rect, border_radius=4)
        pygame.draw.rect(surface, border, self.rect, 1, border_radius=4)

        if self.text:
            text_surf = font.render(self.text, True, TI_TEXT)
        else:
            text_surf = font.render(self.placeholder, True, TI_PLACEHOLDER)

        # Clip text to input bounds
        clip_rect = pygame.Rect(self.rect.x + 4, self.rect.y,
                                self.rect.w - 8, self.rect.h)
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)
        surface.blit(text_surf, (self.rect.x + 8,
                                 self.rect.centery - text_surf.get_height() // 2))
        surface.set_clip(old_clip)

        # Blinking cursor when active
        if self.active and (pygame.time.get_ticks() // 500) % 2 == 0:
            text_w = font.size(self.text)[0] if self.text else 0
            cx = self.rect.x + 8 + text_w
            cy1 = self.rect.centery - 8
            cy2 = self.rect.centery + 8
            pygame.draw.line(surface, TI_TEXT, (cx, cy1), (cx, cy2), 1)


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
# Checkbox
# ---------------------------------------------------------------------------

class Checkbox:
    """Small checkbox (18x18) with a text label to the right."""

    _SIZE = 18

    def __init__(self, x: int, y: int, label: str,
                 checked: bool = False, enabled: bool = True):
        self.x = x
        self.y = y
        self.label = label
        self.checked = checked
        self.enabled = enabled
        self._font = _get_font(SL_FONT_SIZE)
        label_w = self._font.size(label)[0]
        self._hit_rect = pygame.Rect(x, y, self._SIZE + 6 + label_w, self._SIZE)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if checked state changed."""
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._hit_rect.collidepoint(event.pos):
                self.checked = not self.checked
                return True
        return False

    def draw(self, surface: pygame.Surface):
        box = pygame.Rect(self.x, self.y, self._SIZE, self._SIZE)
        border = CB_DISABLED if not self.enabled else CB_BORDER
        fill = CB_BOX if self.enabled else (25, 25, 35)
        pygame.draw.rect(surface, fill, box, border_radius=3)
        pygame.draw.rect(surface, border, box, 1, border_radius=3)

        if self.checked:
            color = CB_DISABLED if not self.enabled else CB_CHECK
            # Draw a small checkmark
            cx, cy = box.centerx, box.centery
            pygame.draw.lines(surface, color, False, [
                (cx - 4, cy), (cx - 1, cy + 4), (cx + 5, cy - 3),
            ], 2)

        text_color = (100, 100, 110) if not self.enabled else (200, 200, 220)
        lbl = self._font.render(self.label, True, text_color)
        surface.blit(lbl, (self.x + self._SIZE + 6,
                           self.y + self._SIZE // 2 - lbl.get_height() // 2))


# ---------------------------------------------------------------------------
# LineGraph
# ---------------------------------------------------------------------------

def _nice_ticks_for_max(y_max: float) -> list[float]:
    """Pick ~5–6 evenly spaced 'nice' ticks ending exactly at *y_max*.

    Used when a graph has a hard cap (e.g. CC HP = 1000) so the top tick
    lands on the cap rather than overshooting.
    """
    if y_max <= 0:
        return [0.0, 1.0]
    nice_steps = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50,
                  100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000,
                  100000, 200000, 500000, 1000000]
    step = nice_steps[-1]
    for s in nice_steps:
        n = y_max / s
        if 4 <= n <= 6 and abs(n - round(n)) < 1e-9:
            step = s
            break
    else:
        # Fallback: closest step that gives ≤8 intervals.
        for s in nice_steps:
            if y_max / s <= 8:
                step = s
                break
    ticks: list[float] = []
    v = 0.0
    while v <= y_max + step * 1e-6:
        ticks.append(v)
        v += step
    if ticks[-1] < y_max - step * 1e-6:
        ticks.append(y_max)
    return ticks


class LineGraph:
    """Draws a line graph with N data series."""

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
        # N-series support: list of (data, color, label)
        self._series: list[tuple[list[float], tuple, str]] = []
        self.x_labels: list[str] | None = None  # optional time labels
        self.timestamps: list[int] | None = None  # raw tick values for x-axis
        self.y_suffix: str = ""  # appended to y-axis labels (e.g. "%")
        self.y_tick_step: float | None = None  # explicit y-axis step (e.g. 8 for Build %)
        self.y_integer_ticks: bool = False  # snap y ticks to nice whole numbers
        self.y_max_fixed: float | None = None  # force y-axis maximum (e.g. 1000 for CC HP)
        self.value_format: str | None = None  # tooltip format (e.g. "{:.2f}")
        self._hover_index: int | None = None
        self._hover_mouse_y: int = 0

    def set_data(self, data1: list[float], data2: list[float] | None = None,
                 x_labels: list[str] | None = None,
                 timestamps: list[int] | None = None):
        """Backward-compat: set 1 or 2 series."""
        self.data1 = data1
        self.data2 = data2 if data2 is not None else []
        self._series = []  # clear N-series when using legacy API
        self.x_labels = x_labels
        self.timestamps = timestamps

    def set_series(self, series: list[tuple[list[float], tuple, str]],
                   x_labels: list[str] | None = None,
                   timestamps: list[int] | None = None):
        """Set N data series. Each entry is (data, color, label)."""
        self._series = series
        # Also populate data1/data2 for backward compat in hover/draw logic
        self.data1 = series[0][0] if len(series) > 0 else []
        self.data2 = series[1][0] if len(series) > 1 else []
        self.x_labels = x_labels
        self.timestamps = timestamps

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Track mouse hover for tooltip. Returns True if hover state changed."""
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            # Compute plot area (must match draw())
            font = _get_font(GRAPH_FONT_SIZE)
            margin_l = 50
            margin_r = 15
            margin_t = 28 if self.title else 12
            margin_b = font.get_height() + 8
            gx = self.rect.x + margin_l
            gy = self.rect.y + margin_t
            gw = self.rect.w - margin_l - margin_r
            gh = self.rect.h - margin_t - margin_b

            n = max((len(s[0]) for s in self._series), default=0) if self._series else max(len(self.data1), len(self.data2))
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

    def _compute_y_ticks(self, data_max: float) -> list[float]:
        """Compute y-axis tick values based on configuration."""
        if self.y_tick_step is not None:
            # Explicit step (e.g. 8 for Build %)
            step = self.y_tick_step
            ticks = []
            v = 0.0
            top = data_max + step  # include one step above data max
            while v <= top:
                ticks.append(v)
                v += step
            return ticks

        if self.y_integer_ticks:
            # Nice whole-number steps
            nice_steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000,
                          10000, 20000, 50000, 100000, 200000, 500000, 1000000]
            step = nice_steps[-1]
            for s in nice_steps:
                if data_max / s <= 6:
                    step = s
                    break
            ticks = []
            v = 0
            top = data_max + step  # include one step above data max
            while v <= top:
                ticks.append(float(v))
                v += step
            return ticks

        # Default: pick a "nice" step from a wide range so labels stay readable
        # for both very small and very large data. Mirrors MultiLineGraph.
        nice_steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500,
                      1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]
        step = nice_steps[-1]
        for s in nice_steps:
            if data_max / s <= 6:
                step = s
                break
        ticks = []
        v = 0.0
        top = data_max + step
        while v <= top:
            ticks.append(v)
            v += step
        return ticks

    def _compute_x_ticks(self, n: int, gw: int, font) -> list[int]:
        """Return data indices for x-axis tick marks at 30-second intervals."""
        if not self.timestamps or len(self.timestamps) < 2:
            # Fallback: evenly spaced
            count = min(6, n)
            return [int(i * (n - 1) / max(count - 1, 1)) for i in range(count)]

        max_tick = self.timestamps[-1]
        game_seconds = max_tick / 60.0

        # Choose interval: smallest multiple of 30s giving <= 10 labels
        interval_s = 30
        while game_seconds / interval_s > 10:
            interval_s *= 2

        interval_ticks = interval_s * 60  # convert to game ticks

        # Minimum pixel gap between labels to avoid overlap
        min_px_gap = font.size("0:00")[0] + 12

        indices: list[int] = []
        prev_px = -min_px_gap * 2  # allow first label always
        t = 0
        while t <= max_tick:
            # Find closest index (timestamps are sorted, ~evenly spaced)
            best_idx = 0
            best_dist = abs(self.timestamps[0] - t)
            for i, ts_val in enumerate(self.timestamps):
                d = abs(ts_val - t)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            if best_idx < n:
                px = int(best_idx * gw / (n - 1))
                if px - prev_px >= min_px_gap or not indices:
                    indices.append(best_idx)
                    prev_px = px
            t += interval_ticks

        return indices

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
        margin_b = font.get_height() + 8  # room for x-axis labels

        gx = x + margin_l
        gy = y + margin_t
        gw = w - margin_l - margin_r
        gh = h - margin_t - margin_b

        if gw <= 0 or gh <= 0:
            return

        # Resolve series list
        if self._series:
            series = self._series
        else:
            series = []
            if self.data1:
                series.append((self.data1, self.color1, "T1"))
            if self.data2:
                series.append((self.data2, self.color2, "T2"))

        n = max((len(s[0]) for s in series), default=0) if series else 0
        # Backward-compat accessors for hover code
        n1 = len(series[0][0]) if len(series) > 0 else 0
        n2 = len(series[1][0]) if len(series) > 1 else 0
        if n < 2:
            no_data = font.render("No data", True, GRAPH_AXIS_TEXT)
            surface.blit(no_data, (gx + gw // 2 - no_data.get_width() // 2,
                                   gy + gh // 2 - no_data.get_height() // 2))
            return

        # Compute Y range
        all_vals = []
        for s_data, _, _ in series:
            all_vals.extend(s_data)
        y_min = 0.0
        data_max = max(all_vals) if all_vals else 1.0
        if data_max <= y_min:
            data_max = y_min + 1.0

        # Compute y-axis tick values
        if self.y_max_fixed is not None:
            y_max = float(self.y_max_fixed)
            y_ticks = _nice_ticks_for_max(y_max)
        else:
            y_ticks = self._compute_y_ticks(data_max)
            y_max = y_ticks[-1] if y_ticks else data_max * 1.1

        # Grid lines at computed tick positions
        for val in y_ticks:
            frac = (val - y_min) / (y_max - y_min) if y_max > y_min else 0
            ly = gy + gh - int(frac * gh)
            pygame.draw.line(surface, GRAPH_GRID, (gx, ly), (gx + gw, ly), 1)
            if val == int(val):
                lbl = f"{int(val)}"
            elif y_max >= 10:
                lbl = f"{val:.0f}"
            else:
                lbl = f"{val:.1f}"
            lbl += self.y_suffix
            ls = font.render(lbl, True, GRAPH_AXIS_TEXT)
            surface.blit(ls, (gx - ls.get_width() - 4, ly - ls.get_height() // 2))

        # X-axis labels (time) — fixed interval ticks
        x_tick_indices = self._compute_x_ticks(n, gw, font)
        for idx in x_tick_indices:
            lx = gx + int(idx * gw / (n - 1))
            if self.x_labels and idx < len(self.x_labels):
                lbl = self.x_labels[idx]
            else:
                lbl = str(idx)
            ls = font.render(lbl, True, GRAPH_AXIS_TEXT)
            text_x = lx - ls.get_width() // 2
            # Clamp so label stays within graph bounds
            text_x = max(gx, min(text_x, gx + gw - ls.get_width()))
            surface.blit(ls, (text_x, gy + gh + 4))

        def _data_to_points(data: list[float]) -> list[tuple[int, int]]:
            pts = []
            count = len(data)
            for i, v in enumerate(data):
                px = gx + int(i * gw / (n - 1))
                frac = (v - y_min) / (y_max - y_min) if y_max > y_min else 0
                py = gy + gh - int(frac * gh)
                pts.append((px, py))
            return pts

        # Draw lines for all series
        for s_data, s_color, _ in series:
            if len(s_data) >= 2:
                pts = _data_to_points(s_data)
                pygame.draw.lines(surface, s_color, False, pts, 2)

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

            hover_vals = []
            for s_data, s_color, s_label in series:
                v = s_data[hi] if hi < len(s_data) else None
                hover_vals.append((v, s_color, s_label))
                if v is not None:
                    pygame.draw.circle(surface, s_color, (hx_pos, _val_y(v)), 4)

            # Tooltip box
            tip_font = _get_font(GRAPH_FONT_SIZE)
            time_str = self.x_labels[hi] if self.x_labels and hi < len(self.x_labels) else str(hi)

            def _fmt_val(v):
                if v is None:
                    return "-"
                if self.value_format:
                    return self.value_format.format(v) + self.y_suffix
                return f"{v:.2f}{self.y_suffix}"

            time_s = tip_font.render(time_str, True, (220, 220, 240))
            tip_rendered = [time_s]
            tip_w = time_s.get_width()
            for v, s_color, s_label in hover_vals:
                txt = f"{s_label}: {_fmt_val(v)}"
                rendered = tip_font.render(txt, True, s_color)
                tip_rendered.append(rendered)
                tip_w = max(tip_w, rendered.get_width())
            tip_w += 12
            tip_h = sum(s.get_height() for s in tip_rendered) + 4 + 2 * len(tip_rendered)

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
            for rendered in tip_rendered:
                surface.blit(rendered, (tip_x + 6, cy_tip))
                cy_tip += rendered.get_height() + 2


# ---------------------------------------------------------------------------
# MultiLineGraph
# ---------------------------------------------------------------------------

class MultiLineGraph:
    """Line graph supporting N named data series with legend and hover tooltip."""

    def __init__(self, x: int, y: int, w: int, h: int, title: str = ""):
        self.rect = pygame.Rect(x, y, w, h)
        self.title = title
        self._series: list[dict] = []  # {name, data, color, visible}
        self._timestamps: list[int] = []
        self._x_labels: list[str] = []
        self._hover_index: int | None = None
        self._hover_mouse_y: int = 0
        self._legend_rects: list[pygame.Rect] = []  # hit areas per series
        # Formatting options (mirrored from LineGraph for compatibility)
        self.y_suffix: str = ""  # appended to y-axis labels (e.g. "%")
        self.y_tick_step: float | None = None  # explicit y-axis step
        self.y_integer_ticks: bool = False  # snap y ticks to nice whole numbers
        self.y_max_fixed: float | None = None  # force y-axis maximum (e.g. 1000 for CC HP)
        self.value_format: str | None = None  # tooltip format (e.g. "{:.2f}")

    def set_series(self, series_list: list[dict],
                   timestamps: list[int] | None = None):
        """Set data series.

        Each dict: {name: str, data: list[float], color: tuple, visible: bool}.
        """
        self._series = series_list
        self._timestamps = timestamps or []
        self._x_labels = []
        for ts in self._timestamps:
            secs = ts / 60.0
            m, s = divmod(int(secs), 60)
            self._x_labels.append(f"{m}:{s:02d}")

    # -- layout helpers -------------------------------------------------------

    _MARGIN_L = 50
    _MARGIN_R = 130  # room for legend
    _MARGIN_T_TITLE = 28
    _MARGIN_T_NO_TITLE = 12

    def _plot_area(self, font) -> tuple[int, int, int, int]:
        margin_t = self._MARGIN_T_TITLE if self.title else self._MARGIN_T_NO_TITLE
        margin_b = font.get_height() + 8
        gx = self.rect.x + self._MARGIN_L
        gy = self.rect.y + margin_t
        gw = self.rect.w - self._MARGIN_L - self._MARGIN_R
        gh = self.rect.h - margin_t - margin_b
        return gx, gy, gw, gh

    # -- event handling -------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            mx, my = event.pos
            for i, lr in enumerate(self._legend_rects):
                if lr.collidepoint(mx, my):
                    self._series[i]["visible"] = not self._series[i]["visible"]
                    return True

        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            font = _get_font(GRAPH_FONT_SIZE)
            gx, gy, gw, gh = self._plot_area(font)
            n = self._data_len()
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

    def _data_len(self) -> int:
        if not self._series:
            return 0
        return max((len(s["data"]) for s in self._series), default=0)

    # -- y/x tick computation (reused from LineGraph logic) -------------------

    def _compute_y_ticks(self, data_max: float) -> list[float]:
        if self.y_tick_step is not None:
            step = self.y_tick_step
            ticks: list[float] = []
            v = 0.0
            top = data_max + step
            while v <= top:
                ticks.append(v)
                v += step
            return ticks

        if self.y_integer_ticks:
            nice_int = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000,
                        10000, 20000, 50000, 100000, 200000, 500000, 1000000]
            step_i = nice_int[-1]
            for s in nice_int:
                if data_max / s <= 6:
                    step_i = s
                    break
            ticks = []
            v_i = 0
            top_i = data_max + step_i
            while v_i <= top_i:
                ticks.append(float(v_i))
                v_i += step_i
            return ticks

        nice_steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500,
                      1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]
        step = nice_steps[-1]
        for s in nice_steps:
            if data_max / s <= 6:
                step = s
                break
        ticks = []
        v = 0.0
        top = data_max + step
        while v <= top:
            ticks.append(v)
            v += step
        return ticks

    def _compute_x_ticks(self, n: int, gw: int, font) -> list[int]:
        if not self._timestamps or len(self._timestamps) < 2:
            count = min(6, n)
            return [int(i * (n - 1) / max(count - 1, 1)) for i in range(count)]

        max_tick = self._timestamps[-1]
        game_seconds = max_tick / 60.0

        interval_s = 30
        while game_seconds / interval_s > 10:
            interval_s *= 2

        interval_ticks = interval_s * 60
        min_px_gap = font.size("0:00")[0] + 12

        indices: list[int] = []
        prev_px = -min_px_gap * 2
        t = 0
        while t <= max_tick:
            best_idx = 0
            best_dist = abs(self._timestamps[0] - t)
            for i, ts_val in enumerate(self._timestamps):
                d = abs(ts_val - t)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            if best_idx < n:
                px = int(best_idx * gw / (n - 1))
                if px - prev_px >= min_px_gap or not indices:
                    indices.append(best_idx)
                    prev_px = px
            t += interval_ticks
        return indices

    # -- drawing --------------------------------------------------------------

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
            surface.blit(ts, (x + (w - self._MARGIN_R) // 2 - ts.get_width() // 2, y + 4))

        gx, gy, gw, gh = self._plot_area(font)
        if gw <= 0 or gh <= 0:
            return

        n = self._data_len()
        if n < 2:
            no_data = font.render("No data", True, GRAPH_AXIS_TEXT)
            surface.blit(no_data, (gx + gw // 2 - no_data.get_width() // 2,
                                   gy + gh // 2 - no_data.get_height() // 2))
            return

        # Compute Y range from visible series
        visible_vals = []
        for s in self._series:
            if s["visible"]:
                visible_vals.extend(s["data"])
        data_max = max(visible_vals) if visible_vals else 1.0
        if data_max <= 0:
            data_max = 1.0

        if self.y_max_fixed is not None:
            y_max = float(self.y_max_fixed)
            y_ticks = _nice_ticks_for_max(y_max)
        else:
            y_ticks = self._compute_y_ticks(data_max)
            y_max = y_ticks[-1] if y_ticks else data_max * 1.1

        # Grid lines
        for val in y_ticks:
            frac = val / y_max if y_max > 0 else 0
            ly = gy + gh - int(frac * gh)
            pygame.draw.line(surface, GRAPH_GRID, (gx, ly), (gx + gw, ly), 1)
            if val == int(val):
                lbl = f"{int(val)}"
            elif y_max >= 10:
                lbl = f"{val:.0f}"
            else:
                lbl = f"{val:.1f}"
            lbl += self.y_suffix
            ls = font.render(lbl, True, GRAPH_AXIS_TEXT)
            surface.blit(ls, (gx - ls.get_width() - 4, ly - ls.get_height() // 2))

        # X-axis labels
        x_tick_indices = self._compute_x_ticks(n, gw, font)
        for idx in x_tick_indices:
            lx = gx + int(idx * gw / (n - 1))
            lbl = self._x_labels[idx] if idx < len(self._x_labels) else str(idx)
            ls = font.render(lbl, True, GRAPH_AXIS_TEXT)
            text_x = lx - ls.get_width() // 2
            text_x = max(gx, min(text_x, gx + gw - ls.get_width()))
            surface.blit(ls, (text_x, gy + gh + 4))

        # Draw lines for visible series
        def _val_to_y(v: float) -> int:
            frac = v / y_max if y_max > 0 else 0
            return gy + gh - int(frac * gh)

        for s in self._series:
            if not s["visible"] or len(s["data"]) < 2:
                continue
            pts = []
            for i, v in enumerate(s["data"]):
                px = gx + int(i * gw / (n - 1))
                py = _val_to_y(v)
                pts.append((px, py))
            pygame.draw.lines(surface, s["color"], False, pts, 2)

        # Legend (right side)
        legend_x = gx + gw + 10
        legend_y = gy
        row_h = 16
        legend_font = _get_font(GRAPH_FONT_SIZE - 2)
        self._legend_rects = []
        for i, s in enumerate(self._series):
            ry = legend_y + i * row_h
            color = s["color"] if s["visible"] else (70, 70, 80)
            # Color swatch
            swatch = pygame.Rect(legend_x, ry + 3, 10, 10)
            pygame.draw.rect(surface, color, swatch)
            # Label
            name = s["name"]
            if len(name) > 12:
                name = name[:11] + ".."
            lbl = legend_font.render(name, True, color)
            surface.blit(lbl, (legend_x + 14, ry + 1))
            # Hit rect for toggling
            hit = pygame.Rect(legend_x, ry, self._MARGIN_R - 15, row_h)
            self._legend_rects.append(hit)

        # Hover tooltip
        if self._hover_index is not None and n >= 2:
            hi = self._hover_index
            hx_pos = gx + int(hi * gw / (n - 1))

            # Vertical line
            line_surf = pygame.Surface((1, gh), pygame.SRCALPHA)
            line_surf.fill((255, 255, 255, 80))
            surface.blit(line_surf, (hx_pos, gy))

            # Dots on visible lines
            for s in self._series:
                if s["visible"] and hi < len(s["data"]):
                    pygame.draw.circle(surface, s["color"],
                                       (hx_pos, _val_to_y(s["data"][hi])), 4)

            # Tooltip box
            tip_font = _get_font(GRAPH_FONT_SIZE)
            time_str = self._x_labels[hi] if hi < len(self._x_labels) else str(hi)

            lines_text = [time_str]
            lines_colors = [(220, 220, 240)]
            for s in self._series:
                if s["visible"] and hi < len(s["data"]):
                    val = s["data"][hi]
                    if self.value_format:
                        val_str = self.value_format.format(val) + self.y_suffix
                    else:
                        val_str = f"{val:.2f}{self.y_suffix}"
                    lines_text.append(f"{s['name']}: {val_str}")
                    lines_colors.append(s["color"])

            rendered = [tip_font.render(t, True, c)
                        for t, c in zip(lines_text, lines_colors)]
            tip_w = max(r.get_width() for r in rendered) + 12
            line_h = rendered[0].get_height()
            tip_h = line_h * len(rendered) + 8

            tip_x = hx_pos + 10
            tip_y = self._hover_mouse_y - tip_h // 2
            if tip_x + tip_w > gx + gw:
                tip_x = hx_pos - tip_w - 10
            tip_y = max(gy, min(tip_y, gy + gh - tip_h))

            tip_rect = pygame.Rect(tip_x, tip_y, tip_w, tip_h)
            pygame.draw.rect(surface, (20, 20, 32), tip_rect, border_radius=3)
            pygame.draw.rect(surface, (80, 80, 110), tip_rect, 1, border_radius=3)

            cy_tip = tip_y + 4
            for r_surf in rendered:
                surface.blit(r_surf, (tip_x + 6, cy_tip))
                cy_tip += line_h


# ---------------------------------------------------------------------------
# Game-start countdown overlay
# ---------------------------------------------------------------------------

def draw_countdown_overlay(surface: pygame.Surface, area: pygame.Rect,
                           anim_timer: float, total: float = 3.0) -> None:
    """Draw a 3-2-1 countdown centered in `area` during the warp-in phase.

    `anim_timer` counts up from 0.0 to `total` seconds. Each integer second
    pulses: starts large + slightly transparent, settles to a normal size,
    then fades out toward the next digit.
    """
    if anim_timer < 0 or anim_timer >= total:
        return
    digit = max(1, int(total) - int(anim_timer))
    frac = anim_timer - int(anim_timer)  # 0.0 → 1.0 within current second

    # Pop in (0.0–0.25), hold (0.25–0.7), fade out (0.7–1.0)
    if frac < 0.25:
        k = frac / 0.25
        scale = 1.6 - 0.6 * k
        alpha = int(120 + 135 * k)
    elif frac < 0.7:
        scale = 1.0
        alpha = 255
    else:
        k = (frac - 0.7) / 0.3
        scale = 1.0 + 0.3 * k
        alpha = int(255 * (1.0 - k))

    base_size = max(72, min(area.width, area.height) // 6)
    font = _get_font(base_size)
    text_surf = font.render(str(digit), True, (240, 240, 255))
    w = max(1, int(text_surf.get_width() * scale))
    h = max(1, int(text_surf.get_height() * scale))
    scaled = pygame.transform.smoothscale(text_surf, (w, h))
    scaled.set_alpha(alpha)

    cx = area.centerx - w // 2
    cy = area.centery - h // 2
    surface.blit(scaled, (cx, cy))
