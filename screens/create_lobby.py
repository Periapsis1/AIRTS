"""Create-lobby screen — mode toggle, team columns, AI pickers, map settings."""
from __future__ import annotations
import json
import os
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT, DD_WIDTH, DD_BG, DD_BORDER, DD_TEXT,
    DD_HEIGHT, DD_FONT_SIZE,
)
from ui.widgets import (
    Button, BackButton, Dropdown, Slider, ToggleGroup, TextInput, Checkbox,
    _get_font,
)

# Team colour indicators (matching in-game palette)
_T1_COLOR = (80, 140, 255)
_T2_COLOR = (255, 80, 80)

# Horizontal column centres
_COL1_CX = 200
_COL2_CX = 600

# Map size presets: (label, width, height)
_MAP_PRESETS = [
    ("small", "Small"),
    ("medium", "Medium"),
    ("large", "Large"),
]
_MAP_SIZES = {
    "small": (800, 600),
    "medium": (1200, 800),
    "large": (1800, 1200),
}

# Settings file path (next to the executable / project root)
_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lobby_settings.json")


def _load_settings() -> dict:
    """Load saved lobby settings from disk, or return empty dict."""
    try:
        with open(_SETTINGS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings: dict):
    """Persist lobby settings to disk."""
    try:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


class CreateLobbyScreen(BaseScreen):
    """Configure game mode, AIs, and map settings, then start."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 ai_choices: list[tuple[str, str]]):
        super().__init__(screen, clock)
        self._ai_choices = ai_choices
        cx = self.width // 2

        # Load saved settings
        saved = _load_settings()

        # -- Mode toggle: Human vs AI | AI vs AI ----------------------------
        mode_index = 1 if saved.get("mode") == "ai_vs_ai" else 0
        self._mode = ToggleGroup(
            cx - 145, 80,
            [
                ("human_vs_ai", "Human vs AI"),
                ("ai_vs_ai", "AI vs AI"),
            ],
            selected_index=mode_index,
            btn_w=140,
            btn_h=32,
        )

        # Which team the human controls (1 or 2) in human_vs_ai mode
        self._human_team: int = saved.get("human_team", 1)

        # -- AI dropdowns (one per column) ----------------------------------
        dd_x1 = _COL1_CX - DD_WIDTH // 2
        dd_x2 = _COL2_CX - DD_WIDTH // 2

        # Restore saved AI selections
        t1_idx = self._find_ai_index(saved.get("ai_t1"), ai_choices, 0)
        t2_idx = self._find_ai_index(saved.get("ai_t2"), ai_choices, 0)
        self._dd_t1 = Dropdown(dd_x1, 165, DD_WIDTH, ai_choices, t1_idx)
        self._dd_t2 = Dropdown(dd_x2, 165, DD_WIDTH, ai_choices, t2_idx)

        # -- Player name input (appears on the human side) ------------------
        self._name_input = TextInput(
            dd_x1, 228, DD_WIDTH,
            text=saved.get("player_name", ""),
            placeholder="Unnamed Player",
            max_len=24,
        )

        # -- Swap sides button ----------------------------------------------
        self._swap_btn = Button(cx - 30, 168, 60, 28, "<->", font_size=14)

        # -- Map size preset toggle -----------------------------------------
        saved_map = saved.get("map_size", "small")
        map_idx = next((i for i, (v, _) in enumerate(_MAP_PRESETS) if v == saved_map), 0)
        sl_x = cx - 110
        self._map_size = ToggleGroup(
            sl_x, 310, _MAP_PRESETS,
            selected_index=map_idx,
            btn_w=73,
            btn_h=28,
        )

        # -- Obstacles slider (single, sets both min and max) ---------------
        self._sl_obstacles = Slider(sl_x, 355, 220, "Obstacles", 0, 20,
                                    saved.get("obstacles", 0), 1)

        # -- Time limit slider ----------------------------------------------
        self._sl_time_limit = Slider(sl_x, 400, 220, "Time Limit (min, 0=off)",
                                     0, 60, saved.get("time_limit", 15), 1)

        # -- Headless checkbox ----------------------------------------------
        self._headless_cb = Checkbox(
            sl_x, 445, "Headless (no rendering, max speed)",
            checked=saved.get("headless", False),
            enabled=False,
        )

        # -- Start button ---------------------------------------------------
        self._start_btn = Button(
            cx - BTN_WIDTH // 2, self.height - 80,
            BTN_WIDTH, BTN_HEIGHT, "Start Game",
        )
        self._back = BackButton()

        self._update_layout()

    @staticmethod
    def _find_ai_index(ai_id: str | None, choices: list[tuple[str, str]],
                       default: int) -> int:
        """Find the index of an AI id in the choices list."""
        if ai_id is None:
            return default
        for i, (val, _) in enumerate(choices):
            if val == ai_id:
                return i
        return default

    # -- layout helpers -----------------------------------------------------

    def _update_layout(self):
        """Show/hide widgets and reposition name input based on mode + human side."""
        mode = self._mode.value
        dd_x1 = _COL1_CX - DD_WIDTH // 2
        dd_x2 = _COL2_CX - DD_WIDTH // 2

        if mode == "human_vs_ai":
            if self._human_team == 1:
                self._dd_t1.visible = False
                self._dd_t2.visible = True
                self._name_input.rect.x = dd_x1
            else:
                self._dd_t1.visible = True
                self._dd_t2.visible = False
                self._name_input.rect.x = dd_x2
            self._name_input.visible = True
            self._headless_cb.enabled = False
            self._headless_cb.checked = False
        else:
            # AI vs AI — both dropdowns, no name input
            self._dd_t1.visible = True
            self._dd_t2.visible = True
            self._name_input.visible = False
            self._headless_cb.enabled = True

    def _swap_sides(self):
        """Exchange the two team configurations."""
        # Swap AI dropdown selections
        idx1 = self._dd_t1.selected_index
        idx2 = self._dd_t2.selected_index
        self._dd_t1.selected_index = idx2
        self._dd_t2.selected_index = idx1
        # Toggle which side is human
        self._human_team = 3 - self._human_team
        self._update_layout()

    # -- event loop ---------------------------------------------------------

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return ScreenResult("quit")
                if self._back.handle_event(event):
                    return ScreenResult("main_menu")

                # Text input gets priority for keyboard events
                if self._name_input.handle_event(event):
                    continue

                if self._mode.handle_event(event):
                    self._name_input.active = False
                    self._update_layout()
                    self._dd_t1.open = False
                    self._dd_t2.open = False

                if self._swap_btn.handle_event(event):
                    self._name_input.active = False
                    self._swap_sides()
                    self._dd_t1.open = False
                    self._dd_t2.open = False

                self._dd_t1.handle_event(event)
                self._dd_t2.handle_event(event)

                self._map_size.handle_event(event)
                self._sl_obstacles.handle_event(event)
                self._sl_time_limit.handle_event(event)
                self._headless_cb.handle_event(event)

                if self._start_btn.handle_event(event):
                    self._persist_settings()
                    return self._build_result()

            self._draw()
            self.clock.tick(60)

    # -- settings persistence -----------------------------------------------

    def _persist_settings(self):
        """Save current lobby settings to disk."""
        _save_settings({
            "mode": self._mode.value,
            "human_team": self._human_team,
            "ai_t1": self._dd_t1.value,
            "ai_t2": self._dd_t2.value,
            "player_name": self._name_input.text.strip(),
            "map_size": self._map_size.value,
            "obstacles": self._sl_obstacles.value,
            "time_limit": self._sl_time_limit.value,
            "headless": self._headless_cb.checked,
        })

    # -- result builder -----------------------------------------------------

    def _build_result(self) -> ScreenResult:
        mode = self._mode.value
        team_ai: dict[int, str] = {}

        if mode == "human_vs_ai":
            ai_team = 3 - self._human_team
            if ai_team == 1:
                team_ai[1] = self._dd_t1.value
            else:
                team_ai[2] = self._dd_t2.value
        elif mode == "ai_vs_ai":
            team_ai[1] = self._dd_t1.value
            team_ai[2] = self._dd_t2.value

        player_name = self._name_input.text.strip() or "Unnamed Player"

        # Resolve map size from preset
        map_w, map_h = _MAP_SIZES[self._map_size.value]

        obs_val = self._sl_obstacles.value

        return ScreenResult("game", data={
            "team_ai_ids": team_ai,
            "player_name": player_name,
            "width": map_w,
            "height": map_h,
            "obstacle_count": (obs_val, obs_val),
            "time_limit": self._sl_time_limit.value,
            "headless": self._headless_cb.checked,
        })

    # -- rendering ----------------------------------------------------------

    def _draw_human_box(self, col_cx: int):
        """Draw the locked 'Human' indicator box on one column."""
        font = _get_font(DD_FONT_SIZE)
        hx = col_cx - DD_WIDTH // 2
        hy = 165
        hr = pygame.Rect(hx, hy, DD_WIDTH, DD_HEIGHT)
        pygame.draw.rect(self.screen, DD_BG, hr, border_radius=4)
        pygame.draw.rect(self.screen, DD_BORDER, hr, 1, border_radius=4)
        text = font.render("Human", True, DD_TEXT)
        self.screen.blit(text, (hr.x + 8, hr.centery - text.get_height() // 2))

    def _draw(self):
        self.screen.fill(MENU_BG)
        self._back.draw(self.screen)

        # Title
        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        title = font_h.render("Create Lobby", True, CONTENT_TEXT)
        self.screen.blit(title, (self.width // 2 - title.get_width() // 2, 30))

        # Mode toggle
        self._mode.draw(self.screen)

        # -- Team column headers with colour dots ---------------------------
        font = _get_font(CONTENT_FONT_SIZE + 2)

        t1_surf = font.render("Team 1", True, CONTENT_TEXT)
        t1_x = _COL1_CX - t1_surf.get_width() // 2
        pygame.draw.circle(self.screen, _T1_COLOR, (t1_x - 12, 140), 5)
        self.screen.blit(t1_surf, (t1_x, 132))

        t2_surf = font.render("Team 2", True, CONTENT_TEXT)
        t2_x = _COL2_CX - t2_surf.get_width() // 2
        pygame.draw.circle(self.screen, _T2_COLOR, (t2_x - 12, 140), 5)
        self.screen.blit(t2_surf, (t2_x, 132))

        # -- Human locked box (only in human_vs_ai) -------------------------
        mode = self._mode.value
        if mode == "human_vs_ai":
            human_cx = _COL1_CX if self._human_team == 1 else _COL2_CX
            self._draw_human_box(human_cx)

            # "Name:" label above the text input
            small_font = _get_font(DD_FONT_SIZE)
            label = small_font.render("Name:", True, CONTENT_TEXT)
            self.screen.blit(label, (self._name_input.rect.x, 210))

        # -- Swap button ----------------------------------------------------
        self._swap_btn.draw(self.screen)

        # -- Map settings header --------------------------------------------
        map_label = font.render("Map Settings", True, CONTENT_TEXT)
        self.screen.blit(map_label,
                         (self.width // 2 - map_label.get_width() // 2, 280))

        self._map_size.draw(self.screen)
        self._sl_obstacles.draw(self.screen)
        self._sl_time_limit.draw(self.screen)
        self._headless_cb.draw(self.screen)

        # -- Start button ---------------------------------------------------
        self._start_btn.draw(self.screen)

        # -- Overlays (drawn last so they render on top) --------------------
        self._name_input.draw(self.screen)
        self._dd_t1.draw(self.screen)
        self._dd_t2.draw(self.screen)

        pygame.display.flip()
