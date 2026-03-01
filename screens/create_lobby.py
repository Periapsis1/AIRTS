"""Create-lobby screen — mode toggle, team columns, AI pickers, map settings."""
from __future__ import annotations
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


class CreateLobbyScreen(BaseScreen):
    """Configure game mode, AIs, and map settings, then start."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 ai_choices: list[tuple[str, str]]):
        super().__init__(screen, clock)
        self._ai_choices = ai_choices
        cx = self.width // 2

        # -- Mode toggle: Human vs AI | AI vs AI ----------------------------
        self._mode = ToggleGroup(
            cx - 145, 80,
            [
                ("human_vs_ai", "Human vs AI"),
                ("ai_vs_ai", "AI vs AI"),
            ],
            selected_index=0,
            btn_w=140,
            btn_h=32,
        )

        # Which team the human controls (1 or 2) in human_vs_ai mode
        self._human_team: int = 1

        # -- AI dropdowns (one per column) ----------------------------------
        dd_x1 = _COL1_CX - DD_WIDTH // 2
        dd_x2 = _COL2_CX - DD_WIDTH // 2
        self._dd_t1 = Dropdown(dd_x1, 165, DD_WIDTH, ai_choices, 0)
        self._dd_t2 = Dropdown(dd_x2, 165, DD_WIDTH, ai_choices, 0)

        # -- Player name input (appears on the human side) ------------------
        self._name_input = TextInput(
            dd_x1, 228, DD_WIDTH,
            text="",
            placeholder="Unnamed Player",
            max_len=24,
        )

        # -- Swap sides button ----------------------------------------------
        self._swap_btn = Button(cx - 30, 168, 60, 28, "<->", font_size=14)

        # -- Map sliders ----------------------------------------------------
        sl_x = cx - 110
        self._sl_width = Slider(sl_x, 310, 220, "Map Width", 200, 1600, 800, 100)
        self._sl_height = Slider(sl_x, 355, 220, "Map Height", 200, 1200, 600, 100)
        self._sl_obs_min = Slider(sl_x, 400, 220, "Obstacles Min", 0, 20, 4, 1)
        self._sl_obs_max = Slider(sl_x, 445, 220, "Obstacles Max", 0, 20, 8, 1)

        # -- Headless checkbox ----------------------------------------------
        self._headless_cb = Checkbox(
            sl_x, 490, "Headless (no rendering, max speed)",
            checked=False, enabled=False,
        )

        # -- Start button ---------------------------------------------------
        self._start_btn = Button(
            cx - BTN_WIDTH // 2, self.height - 80,
            BTN_WIDTH, BTN_HEIGHT, "Start Game",
        )
        self._back = BackButton()

        self._update_layout()

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

                self._sl_width.handle_event(event)
                self._sl_height.handle_event(event)
                self._sl_obs_min.handle_event(event)
                self._sl_obs_max.handle_event(event)
                self._headless_cb.handle_event(event)

                # Enforce obs_min <= obs_max
                if self._sl_obs_min.value > self._sl_obs_max.value:
                    self._sl_obs_max.value = self._sl_obs_min.value
                if self._sl_obs_max.value < self._sl_obs_min.value:
                    self._sl_obs_min.value = self._sl_obs_max.value

                if self._start_btn.handle_event(event):
                    return self._build_result()

            self._draw()
            self.clock.tick(60)

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

        return ScreenResult("game", data={
            "team_ai_ids": team_ai,
            "player_name": player_name,
            "width": self._sl_width.value,
            "height": self._sl_height.value,
            "obstacle_count": (self._sl_obs_min.value, self._sl_obs_max.value),
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

        self._sl_width.draw(self.screen)
        self._sl_height.draw(self.screen)
        self._sl_obs_min.draw(self.screen)
        self._sl_obs_max.draw(self.screen)
        self._headless_cb.draw(self.screen)

        # -- Start button ---------------------------------------------------
        self._start_btn.draw(self.screen)

        # -- Overlays (drawn last so they render on top) --------------------
        self._name_input.draw(self.screen)
        self._dd_t1.draw(self.screen)
        self._dd_t2.draw(self.screen)

        pygame.display.flip()
