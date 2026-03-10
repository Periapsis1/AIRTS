"""Multiplayer lobby screen — host or join a networked game."""
from __future__ import annotations

import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT,
)
from ui.widgets import Button, BackButton, TextInput, ToggleGroup, Slider, _get_font
from networking.protocol import DEFAULT_PORT

# Map size presets (matching create_lobby.py)
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

_STATUS_COLOR = (180, 180, 200)
_ERROR_COLOR = (255, 100, 100)
_SUCCESS_COLOR = (100, 255, 140)


class MultiplayerLobbyScreen(BaseScreen):
    """Host/Join flow for multiplayer games."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        super().__init__(screen, clock)
        cx = self.width // 2

        # Mode: not yet chosen
        self._mode: str = ""  # "", "host", "join"

        # -- Initial menu buttons --
        self._host_btn = Button(
            cx - BTN_WIDTH // 2, self.height // 2 - 50,
            BTN_WIDTH, BTN_HEIGHT, "Host Game",
        )
        self._join_btn = Button(
            cx - BTN_WIDTH // 2, self.height // 2 + 20,
            BTN_WIDTH, BTN_HEIGHT, "Join Game",
        )
        self._back = BackButton()

        # -- Host mode widgets --
        self._host_name_input = TextInput(
            cx - 100, 160, 200,
            placeholder="Your Name", max_len=24,
        )
        self._host_map_size = ToggleGroup(
            cx - 110, 240, _MAP_PRESETS,
            selected_index=0, btn_w=73, btn_h=28,
        )
        self._host_obstacles = Slider(
            cx - 110, 290, 220, "Obstacles", 0, 20, 0, 1,
        )
        self._host_start_btn = Button(
            cx - BTN_WIDTH // 2, self.height - 80,
            BTN_WIDTH, BTN_HEIGHT, "Start Game",
        )
        self._host_obj = None
        self._host_status = "Waiting for player..."

        # -- Join mode widgets --
        self._join_ip_input = TextInput(
            cx - 100, 200, 200,
            placeholder="Host IP Address", max_len=45,
        )
        self._join_name_input = TextInput(
            cx - 100, 270, 200,
            placeholder="Your Name", max_len=24,
        )
        self._join_connect_btn = Button(
            cx - BTN_WIDTH // 2, 330,
            BTN_WIDTH, BTN_HEIGHT, "Connect",
        )
        self._client_obj = None
        self._join_status = ""
        self._join_error = ""

    def run(self) -> ScreenResult:
        while True:
            dt = self.clock.tick(60) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._cleanup()
                    return ScreenResult("quit")

                if self._back.handle_event(event):
                    self._cleanup()
                    return ScreenResult("main_menu")

                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if self._mode:
                        self._cleanup()
                        self._mode = ""
                        continue
                    else:
                        return ScreenResult("main_menu")

                if self._mode == "":
                    if self._host_btn.handle_event(event):
                        self._mode = "host"
                        self._start_host()
                    elif self._join_btn.handle_event(event):
                        self._mode = "join"

                elif self._mode == "host":
                    self._host_name_input.handle_event(event)
                    self._host_map_size.handle_event(event)
                    self._host_obstacles.handle_event(event)
                    if self._host_start_btn.handle_event(event):
                        if self._host_obj and self._host_obj.client_ready:
                            return self._build_host_result()

                elif self._mode == "join":
                    self._join_ip_input.handle_event(event)
                    self._join_name_input.handle_event(event)
                    if self._join_connect_btn.handle_event(event):
                        if not self._client_obj:
                            self._start_client()

            # Poll connection status
            if self._mode == "host" and self._host_obj:
                if self._host_obj.client_ready:
                    self._host_status = f"Player '{self._host_obj.client_name}' connected!"

            if self._mode == "join" and self._client_obj:
                if self._client_obj.error:
                    self._join_error = self._client_obj.error
                    self._join_status = ""
                elif self._client_obj.game_started:
                    # Host started the game — transition to client game screen
                    return self._build_join_result()
                elif self._client_obj.connected:
                    self._join_status = f"Connected to {self._client_obj.host_name}. Waiting for host to start..."
                    self._join_error = ""

            self._draw()

    def _start_host(self) -> None:
        from networking.host import GameHost
        from systems.commands import CommandQueue
        # Create a temporary command queue — the real one will be set when Game starts
        self._host_obj = GameHost(
            command_queue=CommandQueue(),
            port=DEFAULT_PORT,
            host_name=self._host_name_input.text.strip() or "Host",
        )
        self._host_obj.start()
        self._host_status = f"Hosting on {self._host_obj.local_ip}:{self._host_obj.port} — Waiting for player..."

    def _start_client(self) -> None:
        from networking.client import GameClient
        ip = self._join_ip_input.text.strip()
        if not ip:
            self._join_error = "Please enter a host IP address"
            return
        name = self._join_name_input.text.strip() or "Client"
        self._client_obj = GameClient(
            host_ip=ip, port=DEFAULT_PORT, player_name=name,
        )
        self._client_obj.start()
        self._join_status = f"Connecting to {ip}..."
        self._join_error = ""

    def _build_host_result(self) -> ScreenResult:
        map_key = self._host_map_size.value
        map_w, map_h = _MAP_SIZES[map_key]
        obs_val = self._host_obstacles.value
        host_name = self._host_name_input.text.strip() or "Host"
        return ScreenResult("mp_host_game", data={
            "host": self._host_obj,
            "host_name": host_name,
            "client_name": self._host_obj.client_name,
            "width": map_w,
            "height": map_h,
            "obstacle_count": (obs_val, obs_val),
        })

    def _build_join_result(self) -> ScreenResult:
        return ScreenResult("mp_client_game", data={
            "client": self._client_obj,
        })

    def _cleanup(self) -> None:
        if self._host_obj:
            self._host_obj.stop()
            self._host_obj = None
        if self._client_obj:
            self._client_obj.stop()
            self._client_obj = None

    def _draw(self) -> None:
        self.screen.fill(MENU_BG)
        self._back.draw(self.screen)

        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        font = _get_font(CONTENT_FONT_SIZE)
        cx = self.width // 2

        if self._mode == "":
            title = font_h.render("Multiplayer", True, CONTENT_TEXT)
            self.screen.blit(title, (cx - title.get_width() // 2, 80))
            self._host_btn.draw(self.screen)
            self._join_btn.draw(self.screen)

        elif self._mode == "host":
            title = font_h.render("Host Game", True, CONTENT_TEXT)
            self.screen.blit(title, (cx - title.get_width() // 2, 50))

            label = font.render("Name:", True, CONTENT_TEXT)
            self.screen.blit(label, (cx - 100, 142))
            self._host_name_input.draw(self.screen)

            map_label = font.render("Map Size:", True, CONTENT_TEXT)
            self.screen.blit(map_label, (cx - 110, 220))
            self._host_map_size.draw(self.screen)
            self._host_obstacles.draw(self.screen)

            # Status
            ready = self._host_obj and self._host_obj.client_ready
            color = _SUCCESS_COLOR if ready else _STATUS_COLOR
            status = font.render(self._host_status, True, color)
            self.screen.blit(status, (cx - status.get_width() // 2, 370))

            if ready:
                self._host_start_btn.draw(self.screen)

        elif self._mode == "join":
            title = font_h.render("Join Game", True, CONTENT_TEXT)
            self.screen.blit(title, (cx - title.get_width() // 2, 50))

            label_ip = font.render("Host IP:", True, CONTENT_TEXT)
            self.screen.blit(label_ip, (cx - 100, 182))
            self._join_ip_input.draw(self.screen)

            label_name = font.render("Name:", True, CONTENT_TEXT)
            self.screen.blit(label_name, (cx - 100, 252))
            self._join_name_input.draw(self.screen)

            if not self._client_obj or self._join_error:
                self._join_connect_btn.draw(self.screen)

            if self._join_error:
                err = font.render(self._join_error, True, _ERROR_COLOR)
                self.screen.blit(err, (cx - err.get_width() // 2, 390))
            elif self._join_status:
                st = font.render(self._join_status, True, _STATUS_COLOR)
                self.screen.blit(st, (cx - st.get_width() // 2, 390))

        pygame.display.flip()
