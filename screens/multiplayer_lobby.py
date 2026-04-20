"""Multiplayer lobby screen — host, join, or play online."""
from __future__ import annotations

import os
import pygame
from screens.base import BaseScreen, ScreenResult
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT,
)
from ui.widgets import Button, BackButton, TextInput, ToggleGroup, Slider, Dropdown, _get_font
from networking.protocol import DEFAULT_PORT
from screens.create_lobby import _load_settings


def _load_env() -> dict[str, str]:
    """Load key=value pairs from .env next to the executable (or project root)."""
    from core.paths import app_path
    env: dict[str, str] = {}
    env_path = app_path(".env")
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env

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
    """Host/Join/Play Online flow for multiplayer games."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 returning_host=None, returning_client=None,
                 lost_connection: bool = False):
        super().__init__(screen, clock)
        cx = self.width // 2

        # Load saved player name from lobby settings
        saved_name = _load_settings().get("player_name", "")

        # Go straight to online mode (Host/Join removed)
        self._mode: str = "online"
        self._back = BackButton()

        # -- Host mode widgets --
        self._host_name_input = TextInput(
            cx - 100, 160, 200,
            text=saved_name,
            placeholder="Your Name", max_len=24,
        )
        self._host_map_size = ToggleGroup(
            cx - 110, 240, _MAP_PRESETS,
            selected_index=0, btn_w=73, btn_h=28,
        )
        self._host_obstacles = Slider(
            cx - 110, 290, 220, "Obstacles", 0, 20, 0, 1,
        )
        self._host_team_choices = [(str(i), f"Team {i}") for i in range(1, 9)]
        self._host_team_dropdown = Dropdown(
            cx - 110, 330, 220, self._host_team_choices, 0,
        )
        self._host_start_btn = Button(
            cx - BTN_WIDTH // 2, self.height - 80,
            BTN_WIDTH, BTN_HEIGHT, "Start Game",
        )
        self._host_obj = None
        self._host_status = "Waiting for player..."
        self._copy_ip_btn = Button(
            cx - 45, 410, 90, 30, "Copy IP", font_size=18,
        )
        self._copy_flash: float = 0.0  # seconds remaining for "Copied!" feedback

        # -- Join mode widgets --
        self._join_ip_input = TextInput(
            cx - 100, 200, 200,
            placeholder="Host IP Address", max_len=45,
        )
        self._join_name_input = TextInput(
            cx - 100, 270, 200,
            text=saved_name,
            placeholder="Your Name", max_len=24,
        )
        self._join_connect_btn = Button(
            cx - BTN_WIDTH // 2, 330,
            BTN_WIDTH, BTN_HEIGHT, "Connect",
        )
        self._client_obj = None
        self._join_status = ""
        self._join_error = ""

        # -- Play Online mode widgets --
        env = _load_env()
        self._server_ip = env.get("SERVER_IP", "0.0.0.0")
        self._server_port = int(env.get("SERVER_PORT", str(DEFAULT_PORT)))
        self._needs_server_ip = self._server_ip in ("0.0.0.0", "")
        self._online_ip_input = TextInput(
            cx - 100, 200, 200,
            placeholder="Server IP Address", max_len=45,
        )
        self._online_name_input = TextInput(
            cx - 100, 270 if self._needs_server_ip else 220, 200,
            text=saved_name,
            placeholder="Your Name", max_len=24,
        )
        self._online_connect_btn = Button(
            cx - BTN_WIDTH // 2, 340 if self._needs_server_ip else 290,
            BTN_WIDTH, BTN_HEIGHT, "Connect",
        )
        self._online_client = None
        self._online_status = ""
        self._online_error = ""

        # If returning from a game with an existing host/client, restore state
        if returning_host is not None:
            self._mode = "host"
            self._host_obj = returning_host
            self._host_status = "Returned to lobby. Waiting for player..."
            if returning_host.client_ready:
                self._host_status = f"Player '{returning_host.client_name}' connected!"
        elif returning_client is not None:
            self._mode = "join"
            self._client_obj = returning_client
            self._join_status = f"Connected to {returning_client.host_name}. Waiting for host to start..."

        # Surface a "Lost Connection" message when we were kicked here from
        # an in-progress game / lobby because the server connection dropped.
        if lost_connection:
            self._online_error = "Lost Connection"
            self._join_error = "Lost Connection"

    def run(self) -> ScreenResult:
        from systems import music
        while True:
            dt = self.clock.tick(60) / 1000.0
            music.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._cleanup()
                    return ScreenResult("quit")

                if self._back.handle_event(event):
                    self._cleanup()
                    return ScreenResult("main_menu")

                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._cleanup()
                    return ScreenResult("main_menu")

                if self._mode == "host":
                    self._host_name_input.handle_event(event)
                    self._host_map_size.handle_event(event)
                    self._host_obstacles.handle_event(event)
                    self._host_team_dropdown.handle_event(event)
                    if self._copy_ip_btn.handle_event(event):
                        if self._host_obj:
                            self._copy_to_clipboard(self._host_obj.local_ip)
                            self._copy_flash = 2.0
                    if self._host_start_btn.handle_event(event):
                        if self._host_obj and self._host_obj.client_ready:
                            return self._build_host_result()

                elif self._mode == "join":
                    self._join_ip_input.handle_event(event)
                    self._join_name_input.handle_event(event)
                    if self._join_connect_btn.handle_event(event):
                        if not self._client_obj or self._join_error:
                            self._start_client()

                elif self._mode == "online":
                    if self._needs_server_ip:
                        self._online_ip_input.handle_event(event)
                    self._online_name_input.handle_event(event)
                    if self._online_connect_btn.handle_event(event):
                        if not self._online_client or self._online_error:
                            self._start_online_client()

            # Tick copy-flash timer
            if self._copy_flash > 0:
                self._copy_flash = max(0.0, self._copy_flash - dt)

            # Poll connection status
            if self._mode == "host" and self._host_obj:
                if self._host_obj.client_ready:
                    self._host_status = f"Player '{self._host_obj.client_name}' connected!"
                # Broadcast current lobby settings to connected clients
                if self._host_obj.connected_count > 0:
                    self._host_obj.set_lobby_settings(self._gather_host_settings())

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

            if self._mode == "online" and self._online_client:
                if self._online_client.error:
                    self._online_error = self._online_client.error
                    self._online_status = ""
                elif self._online_client.connected:
                    # Connected — go straight to the game lobby
                    return ScreenResult("create_lobby", data={
                        "online_client": self._online_client,
                    })

            self._draw()

    def _start_host(self) -> None:
        from networking.host import GameHost
        from systems.commands import CommandQueue
        # Create a temporary command queue — the real one will be set when Game starts
        self._host_obj = GameHost(
            command_queue=CommandQueue(),
            port=DEFAULT_PORT,
            host_name=self._host_name_input.text.strip() or "Host",
            max_players=1,  # LAN host: only 1 remote client
        )
        self._host_obj.start()
        self._host_status = f"Hosting on {self._host_obj.local_ip}:{self._host_obj.port} — Waiting for player..."

    @staticmethod
    def _sanitize_ip(raw: str) -> str:
        """Clean up common IP entry mistakes."""
        # Strip port suffix if present (e.g. "192.168.0.1:7777")
        ip = raw.split(":")[0].strip()
        # Strip leading zeros from each octet (e.g. "192.168.00.206" -> "192.168.0.206")
        parts = ip.split(".")
        if len(parts) == 4:
            try:
                ip = ".".join(str(int(p)) for p in parts)
            except ValueError:
                pass  # not a dotted-quad IP, leave as-is
        return ip

    def _start_client(self) -> None:
        from networking.client import GameClient
        # Clean up any previous failed attempt
        if self._client_obj:
            self._client_obj.stop()
            self._client_obj = None
        ip = self._sanitize_ip(self._join_ip_input.text)
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

    def _start_online_client(self) -> None:
        from networking.client import GameClient
        # Clean up any previous failed attempt
        if self._online_client:
            self._online_client.stop()
            self._online_client = None
        if self._needs_server_ip:
            ip = self._sanitize_ip(self._online_ip_input.text)
            if not ip:
                self._online_error = "Please enter a server IP address"
                return
        else:
            ip = self._server_ip
        port = self._server_port
        name = self._online_name_input.text.strip() or "Player"
        self._online_client = GameClient(
            host_ip=ip, port=port, player_name=name,
        )
        self._online_client.start()
        self._online_status = f"Connecting to {ip}:{port}..."
        self._online_error = ""

    def _gather_host_settings(self) -> dict:
        """Build a settings dict from the current host lobby UI state."""
        map_key = self._host_map_size.value
        host_name = self._host_name_input.text.strip() or "Host"
        host_team = int(self._host_team_dropdown.value)
        return {
            "map_size": map_key,
            "obstacles": self._host_obstacles.value,
            "host_name": host_name,
            "host_team": host_team,
        }

    def _build_host_result(self) -> ScreenResult:
        map_key = self._host_map_size.value
        map_w, map_h = _MAP_SIZES[map_key]
        obs_val = self._host_obstacles.value
        host_name = self._host_name_input.text.strip() or "Host"
        host_team = int(self._host_team_dropdown.value)
        # Assign client to a different team (next team cyclically)
        client_team = (host_team % 8) + 1 if host_team < 8 else 1
        player_team = {1: host_team, 2: client_team}
        return ScreenResult("mp_host_game", data={
            "host": self._host_obj,
            "host_name": host_name,
            "client_name": self._host_obj.client_name,
            "width": map_w,
            "height": map_h,
            "obstacle_count": (obs_val, obs_val),
            "player_team": player_team,
        })

    def _build_join_result(self) -> ScreenResult:
        return ScreenResult("mp_client_game", data={
            "client": self._client_obj,
        })

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        """Copy text to the system clipboard."""
        import subprocess
        try:
            subprocess.Popen(
                ["clip"], stdin=subprocess.PIPE, shell=True,
            ).communicate(text.encode())
        except Exception:
            pass

    def _cleanup(self) -> None:
        if self._host_obj:
            self._host_obj.stop()
            self._host_obj = None
        if self._client_obj:
            self._client_obj.stop()
            self._client_obj = None
        if self._online_client:
            self._online_client.stop()
            self._online_client = None

    def _draw_lobby_settings(self, client, y_start: int) -> None:
        """Draw a read-only panel showing lobby settings received from the host."""
        settings = client.lobby_settings if client else None
        if not settings:
            return
        font = _get_font(CONTENT_FONT_SIZE)
        small = _get_font(CONTENT_FONT_SIZE - 2)
        cx = self.width // 2

        # Map size
        map_key = settings.get("map_size", "?")
        _MAP_LABELS = {"small": "Small", "medium": "Medium", "large": "Large"}
        map_label = _MAP_LABELS.get(map_key, map_key)
        s = font.render(f"Map: {map_label}", True, CONTENT_TEXT)
        self.screen.blit(s, (cx - s.get_width() // 2, y_start))

        # Obstacles
        obs = settings.get("obstacles", 0)
        s = small.render(f"Obstacles: {obs}", True, _STATUS_COLOR)
        self.screen.blit(s, (cx - s.get_width() // 2, y_start + 26))

        # Fog of War
        if settings.get("fog_of_war"):
            s = small.render("Fog of War: On", True, _STATUS_COLOR)
            self.screen.blit(s, (cx - s.get_width() // 2, y_start + 48))
            y_offset = 70
        else:
            y_offset = 48

        # Host info
        host_name = settings.get("host_name", "Host")
        host_team = settings.get("host_team", 1)
        s = small.render(f"Host: {host_name} (Team {host_team})", True, _STATUS_COLOR)
        self.screen.blit(s, (cx - s.get_width() // 2, y_start + y_offset))

    def _draw(self) -> None:
        self.screen.fill(MENU_BG)
        self._back.draw(self.screen)

        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        font = _get_font(CONTENT_FONT_SIZE)
        cx = self.width // 2

        if self._mode == "host":
            title = font_h.render("Host Game", True, CONTENT_TEXT)
            self.screen.blit(title, (cx - title.get_width() // 2, 50))

            label = font.render("Name:", True, CONTENT_TEXT)
            self.screen.blit(label, (cx - 100, 142))
            self._host_name_input.draw(self.screen)

            map_label = font.render("Map Size:", True, CONTENT_TEXT)
            self.screen.blit(map_label, (cx - 110, 220))
            self._host_map_size.draw(self.screen)
            self._host_obstacles.draw(self.screen)

            team_label = font.render("Your Team:", True, CONTENT_TEXT)
            self.screen.blit(team_label, (cx - 110, 318))
            self._host_team_dropdown.draw(self.screen)

            # Status
            ready = self._host_obj and self._host_obj.client_ready
            color = _SUCCESS_COLOR if ready else _STATUS_COLOR
            status = font.render(self._host_status, True, color)
            self.screen.blit(status, (cx - status.get_width() // 2, 380))

            # Copy IP button
            if self._host_obj:
                self._copy_ip_btn.draw(self.screen)
                if self._copy_flash > 0:
                    copied = font.render("Copied!", True, _SUCCESS_COLOR)
                    self.screen.blit(copied, (cx - copied.get_width() // 2, 445))

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

            # Show lobby settings from host (when connected)
            if self._client_obj and self._client_obj.connected:
                self._draw_lobby_settings(self._client_obj, 430)

        elif self._mode == "online":
            title = font_h.render("Play Online", True, CONTENT_TEXT)
            self.screen.blit(title, (cx - title.get_width() // 2, 50))

            if self._needs_server_ip:
                label_ip = font.render("Server IP:", True, CONTENT_TEXT)
                self.screen.blit(label_ip, (cx - 100, 182))
                self._online_ip_input.draw(self.screen)
            else:
                server_label = font.render(
                    f"Server: {self._server_ip}:{self._server_port}", True, _STATUS_COLOR,
                )
                self.screen.blit(server_label, (cx - server_label.get_width() // 2, 170))

            y_name = 252 if self._needs_server_ip else 202
            label_name = font.render("Name:", True, CONTENT_TEXT)
            self.screen.blit(label_name, (cx - 100, y_name))
            self._online_name_input.draw(self.screen)

            if not self._online_client or self._online_error:
                self._online_connect_btn.draw(self.screen)

            status_y = 410 if self._needs_server_ip else 360
            if self._online_error:
                err = font.render(self._online_error, True, _ERROR_COLOR)
                self.screen.blit(err, (cx - err.get_width() // 2, status_y))
            elif self._online_status:
                st = font.render(self._online_status, True, _SUCCESS_COLOR)
                self.screen.blit(st, (cx - st.get_width() // 2, status_y))

            # Show lobby settings from server (when connected)
            if self._online_client and self._online_client.connected:
                self._draw_lobby_settings(self._online_client, status_y + 40)

        pygame.display.flip()
