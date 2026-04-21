"""Client-side game screen — thin renderer that receives state from host."""
from __future__ import annotations

import math
import os
import random
import pygame
import pygame.sndarray
import numpy as np
from screens.base import BaseScreen, ScreenResult
from networking.client import GameClient
from systems.commands import GameCommand
from config.settings import (
    OBSTACLE_OUTLINE, HEALTH_BAR_WIDTH, HEALTH_BAR_HEIGHT,
    HEALTH_BAR_BG, HEALTH_BAR_FG, HEALTH_BAR_LOW, HEALTH_BAR_OFFSET,
    CC_RADIUS, METAL_SPOT_CAPTURE_RADIUS,
    METAL_SPOT_CAPTURE_RANGE_COLOR, METAL_EXTRACTOR_RADIUS,
    CC_HP, METAL_EXTRACTOR_HP,
    METAL_SPOT_CAPTURE_ARC_WIDTH,
    SELECTED_COLOR, SELECTION_FILL_COLOR, SELECTION_RECT_COLOR,
    TEAM_COLORS, PLAYER_COLORS,
    CAMERA_ZOOM_STEP, CAMERA_MAX_ZOOM,
    EDGE_PAN_MARGIN, EDGE_PAN_SPEED,
    GUI_BORDER, GUI_BTN_SELECTED, GUI_BTN_HOVER, GUI_BTN_NORMAL,
    GUI_TEXT_COLOR,
    RANGE_COLOR, MEDIC_HEAL_COLOR, CC_LASER_RANGE,
    REACTIVE_ARMOR_COLOR, ELECTRIC_ARMOR_COLOR,
    OUTPOST_LOS,
    FIXED_DT,
)
from core.camera import Camera
from config import audio
from config.unit_types import UNIT_TYPES, get_spawnable_types
from ui.widgets import _get_font, Slider, Button, draw_countdown_overlay
import gui
from gui_adapter import wrap_entities
from systems.replay import normalize_cp
from systems.client_stats import ClientFrameStats
from systems.chat import (
    ChatLog, ChatMessage, FloatingChatText,
    CHAT_DISPLAY_COUNT, CHAT_DISPLAY_DURATION, MAX_MESSAGE_LENGTH,
)
from config import display as display_config
from entities.effects import DeathBurst

_STATUS_COLOR = (180, 180, 200)
_DISCONNECT_COLOR = (255, 100, 100)

# Command arrow colours/sizes (matching replay_playback.py)
_MOVE_CMD_COLOR = (0, 140, 40)
_ATTACK_CMD_COLOR = (180, 30, 30)
_FIGHT_CMD_COLOR = (180, 50, 180)
_ARROW_SIZE = 6

# HUD constants (matching gui.py style)
_SECTION_BG = (22, 22, 30)
_TITLE_COLOR = (210, 210, 230)
_STAT_LABEL = (130, 130, 155)
_DIVIDER = (50, 50, 65)
_BUILD_BTN_SIZE = 38
_BUILD_BTN_GAP = 4

# Hotkeys for CC build panel — QWERTY row maps to unit types by position.
_CC_BUILD_HOTKEYS: dict[int, int] = {
    pygame.K_q: 0, pygame.K_w: 1, pygame.K_e: 2, pygame.K_r: 3,
    pygame.K_t: 4, pygame.K_y: 5, pygame.K_u: 6, pygame.K_i: 7,
    pygame.K_o: 8, pygame.K_p: 9,
}

# Metallic border colours (matching game.py)
_BORDER_OUTER = (160, 165, 175)
_BORDER_MID = (100, 105, 115)
_BORDER_INNER = (60, 62, 70)


def _draw_metallic_border(surface: pygame.Surface, rect: pygame.Rect,
                          thickness: int = 3) -> None:
    colors = [_BORDER_OUTER, _BORDER_MID, _BORDER_INNER]
    for i in range(min(thickness, len(colors))):
        c = colors[i]
        r = rect.inflate(-i * 2, -i * 2)
        if r.w > 0 and r.h > 0:
            pygame.draw.rect(surface, c, r, 1)


class ClientGameScreen(BaseScreen):
    """Renders state received from a GameHost and sends commands."""

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        client: GameClient,
        is_local: bool = False,
    ):
        super().__init__(screen, clock)
        self._client = client
        self._is_local = is_local
        self._is_spectator: bool = bool(getattr(client, "is_spectator", False))
        self._my_team: int = client.client_team
        self._all_teams: set[int] = set(client.player_team.values()) if client.player_team else {1, 2}
        self._team_colors: dict[int, tuple] = getattr(client, 'team_colors', {}) or {}

        # Spectator-only team-view cycle (mirrors replay playback's button).
        self._team_view: int = 0
        self._team_view_options: list[tuple[int, str]] = [(0, "All Teams")]
        for _tid in sorted(self._all_teams):
            self._team_view_options.append((_tid, f"Team {_tid}"))
        self._team_view_btn: Button | None = None
        if self._is_spectator:
            self._team_view_btn = Button(200, 12, 95, 24, "All Teams",
                                         font_size=18)
        self._spectator_font = pygame.font.SysFont(None, 20)
        mw = client.map_width
        mh = client.map_height

        # Layout areas — match host's header/hud/game area proportions
        self._header_h = 40
        self._hud_h = int(self.height * 0.20)
        self._header_rect = pygame.Rect(0, 0, self.width, self._header_h)
        self._hud_rect = pygame.Rect(0, self.height - self._hud_h,
                                     self.width, self._hud_h)
        self._game_area = pygame.Rect(0, self._header_h, self.width,
                                      self.height - self._header_h - self._hud_h)

        # Detect GPU renderer mode. In GPU mode we replace `self.screen`
        # with an SRCALPHA scratch so non-world draws (labels, HUD,
        # border) become opaque pixels on a transparent canvas. Areas
        # left transparent let the GPU-composed world + overlays show
        # through at `present()` time. Deferred until after the layout
        # rects are built since texture sizing depends on game_area.
        self._gpu_mode = display_config.renderer_mode == "gpu"
        if self._gpu_mode:
            self.screen = pygame.Surface(
                (self.width, self.height), pygame.SRCALPHA,
            )
            _ctx = display_config.gpu_context()
            ga_size = (self._game_area.w, self._game_area.h)
            self._scratch_tex = _ctx.streaming_texture(
                (self.width, self.height),
            )
            self._ws_tex = _ctx.streaming_texture((mw, mh))
            self._fog_tex = _ctx.streaming_texture(ga_size)
            self._fx_tex = _ctx.streaming_texture(ga_size)
            self._arc_tex = _ctx.streaming_texture(ga_size)
            # Alpha blending on textures that get drawn as overlays so
            # their transparency composes correctly. BLENDMODE_BLEND is
            # exposed on the pygame top-level module, not on
            # pygame._sdl2.video.
            for _t in (self._scratch_tex, self._fog_tex,
                       self._fx_tex, self._arc_tex):
                _t.blend_mode = pygame.BLENDMODE_BLEND

            # Scratch upload optimization state. Rather than uploading the
            # full-screen SRCALPHA scratch every frame we compute a dirty
            # bbox for game-area chrome (labels, floating chats, overlays)
            # and upload only header + HUD strips + that bbox. Union with
            # the previous frame's bbox ensures stale pixels get cleared.
            self._header_strip = pygame.Rect(0, 0, self.width, self._header_h)
            self._hud_strip = pygame.Rect(
                0, self.height - self._hud_h,
                self.width, self._hud_h,
            )
            self._scratch_game_bbox: pygame.Rect | None = None
            self._last_scratch_game_bbox: pygame.Rect | None = None
            # Set to True when a full-screen overlay is active and scratch
            # content outside the normal bbox needs uploading.
            self._scratch_needs_full_game: bool = False
            # Stores the metallic border rect each frame so present() can
            # draw it directly via renderer primitives (avoiding a draw on
            # the scratch surface which would keep it dirty every frame).
            self._border_rect: pygame.Rect | None = None

        # World surface and camera
        self._world_surface = pygame.Surface((mw, mh))
        self._bg_surface, self._bg_tile = self._build_background(mw, mh)
        self._map_w = mw
        self._map_h = mh
        self._camera = Camera(self._game_area.w, self._game_area.h, mw, mh,
                              max_zoom=CAMERA_MAX_ZOOM)

        # State from host
        self._obstacles: list[dict] = client.obstacles

        # Obstacles are static for the match — bake them into the background
        # surface once here so the per-frame `bg` pass is a single cached
        # blit (no per-obstacle draw calls).
        for _obs in self._obstacles:
            _c = tuple(_obs.get("c", [120, 120, 120]))
            if _obs["shape"] == "rect":
                _x, _y, _w, _h = _obs["x"], _obs["y"], _obs["w"], _obs["h"]
                pygame.draw.rect(self._bg_surface, _c, (_x, _y, _w, _h))
                pygame.draw.rect(self._bg_surface, OBSTACLE_OUTLINE,
                                 (_x, _y, _w, _h), 1)
            elif _obs["shape"] == "circle":
                _cx, _cy, _r = int(_obs["x"]), int(_obs["y"]), int(_obs["r"])
                pygame.draw.circle(self._bg_surface, _c, (_cx, _cy), _r)
                pygame.draw.circle(self._bg_surface, OBSTACLE_OUTLINE,
                                   (_cx, _cy), _r, 1)
        self._entities: list[dict] = []
        self._lasers: list[list] = []
        self._tick: int = 0
        self._winner: int = 0

        # Movement extrapolation state
        self._last_server_positions: dict[int, tuple[float, float]] = {}
        self._last_server_targets: dict[int, tuple] = {}
        self._last_extrap_tick: int = 0
        self._unit_velocities: dict[int, tuple[float, float]] = {}
        self._extrap_dt: float = 0.0

        # Local selection
        self._selected_ids: set[int] = set()
        self._dragging = False
        self._drag_start: tuple[int, int] = (0, 0)
        self._drag_end: tuple[int, int] = (0, 0)

        # Middle mouse pan
        self._mid_dragging = False
        self._mid_last: tuple[int, int] = (0, 0)

        # Right-click path drawing
        self._rdragging = False
        self._rpath: list[tuple[float, float]] = []
        self._PATH_MIN_DIST = 2.5
        self._fight_mode = False  # F-key: next right-click sends fight command
        self._attack_mode = False  # A-key: next right-click sends attack command

        # Selection surface for circle draw
        self._selection_surface = pygame.Surface((mw, mh), pygame.SRCALPHA)

        # Fog / effects surfaces — sized to the game area (viewport), not to
        # the full map. Overlays render in screen coords and blit directly to
        # self.screen after camera.apply, so world_surface never gets dirtied
        # by fog or fx. This unlocks a much cheaper bg pass (dirty-rect
        # restoration possible) and cuts fog cost at non-1x zoom since there
        # is no per-frame scale of a map-sized SRCALPHA surface.
        gaw, gah = self._game_area.w, self._game_area.h
        self._fog_surface = pygame.Surface((gaw, gah), pygame.SRCALPHA)
        self._fog_border = pygame.Surface((gaw, gah))
        self._fog_border.set_colorkey((0, 0, 0))
        # Pre-baked circle brushes keyed by (screen) radius.
        # * `_los_brushes` — opaque alpha=255 (hard fog / spectator path).
        # * `_los_soft_brushes` — radial alpha gradient, opaque at center
        #   fading to 0 at the edge. Used by soft fog; when blitted with
        #   BLEND_RGBA_SUB against FOG_ALPHA fog, the soft edge produces a
        #   smooth transition without any explicit blur pass. Replaces the
        #   old half-res + smoothscale upsample approach.
        self._los_brushes: dict[int, pygame.Surface] = {}
        self._los_soft_brushes: dict[int, pygame.Surface] = {}
        # Cache key for composited fog (snapped screen positions, etc.).
        # Skips the full rebuild when fog inputs haven't changed.
        self._fog_cache_key: tuple | None = None
        # Per-frame flags: set by each overlay pass when it has content to
        # show this frame, read by the world-scope screen-blit step.
        self._fog_ready: bool = False
        self._fx_ready: bool = False
        self._arc_ready: bool = False

        # Dirty-rect tracking for bg restoration. Each frame records which
        # regions of `_world_surface` were drawn on by entities / command
        # arrows / etc.; the next frame's bg pass restores only those rects
        # from `_bg_surface` instead of the whole viewport. Empty list =>
        # first frame, fall back to viewport-wide restore.
        self._last_dirty_rects: list[pygame.Rect] = []

        # Disconnect tracking
        self._disconnect_timer: float = 0.0

        # Server performance metrics (reported via state frames)
        self._server_tick_ms: float = 0.0
        self._server_tps: float = 0.0

        # Client frame-time breakdown (F3 toggles the overlay)
        self._frame_stats = ClientFrameStats()
        self._show_perf: bool = False

        # HUD proxy cache — rebuild only when the state-frame entities list
        # swaps (≈10 Hz) instead of every render frame (60 Hz). Selection-only
        # changes are patched in place without rebuilding.
        self._hud_proxies: list | None = None
        self._hud_proxies_entities: list | None = None
        self._hud_proxies_selected: set[int] = set()

        # ESC menu pre-rendered surfaces (overlay tint + title).
        self._esc_menu_overlay: pygame.Surface | None = None
        self._esc_menu_title: pygame.Surface | None = None

        # Enable T2 and upgrade tracking (from game_start message)
        self._enable_t2: bool = client.enable_t2
        self._fog_of_war: bool = client.fog_of_war
        self._t2_upgrades: dict[int, set[str]] = {}        # completed unlocks
        self._t2_researching: dict[int, set[str]] = {}     # in-progress only

        # HUD build button rects (cached) — still used for basic click detection
        self._build_btns = self._compute_build_btn_rects()

        # Animation state
        self._phase: str = "warp_in"  # warp_in → playing → explode
        self._anim_timer: float = 0.0
        self._anim_surface = pygame.Surface((mw, mh), pygame.SRCALPHA)
        # Viewport-sized SRCALPHA overlay buffers. Lasers and FOV arcs each
        # get their own buffer so they don't stomp on each other's content.
        # Rendered in screen coords and blitted directly to self.screen after
        # camera.apply — world_surface is never touched by these passes.
        self._fx_surface = pygame.Surface(
            (self._game_area.w, self._game_area.h), pygame.SRCALPHA,
        )
        self._arc_surface = pygame.Surface(
            (self._game_area.w, self._game_area.h), pygame.SRCALPHA,
        )
        self._fragments: list[dict] = []
        self._splashes: list[dict] = []
        self._death_bursts: list[DeathBurst] = []

        # Chat state
        self._chat_log = ChatLog()
        self._floating_chats: list[FloatingChatText] = []
        self._chat_input_active = False
        self._chat_input_text = ""
        self._chat_mode = "all"
        self._chat_scroll = 0
        self._game_time = 0.0

        # Player names from game_start
        self._player_names: dict[int, str] = client.player_names or {}

        # Double-click detection
        self._last_click_time: int = 0
        self._last_click_pos: tuple[int, int] = (0, 0)
        _DBLCLICK_MS = 400

        # Local game controls (pause/speed/reset cam)
        self._paused = False
        if is_local:
            self._speed_slider = Slider(self.width - 170, 10, 150, "Speed %", 25, 800, 100, 25)
            self._pause_btn = Button(self.width - 210, 12, 32, 24, "||", icon="pause")
            self._reset_cam_btn = Button(70, 12, 50, 24, "Reset", font_size=18)
            self._pause_font = pygame.font.SysFont(None, 48)
        else:
            self._speed_slider = None
            self._pause_btn = None
            self._reset_cam_btn = None
            self._pause_font = None

        # Escape menu. Spectators have no team to surrender, so we drop that
        # button and promote "Back to Lobby" into its slot.
        self._esc_menu_open = False
        _mbw, _mbh, _mgap = 260, 44, 12
        _mx = self.width // 2 - _mbw // 2
        _rows = 3 if self._is_spectator else 4
        _total_h = _rows * _mbh + (_rows - 1) * _mgap
        _my = self.height // 2 - _total_h // 2 + 20
        self._esc_menu_btns = [
            ("resume", Button(_mx, _my, _mbw, _mbh, "Back To Game")),
            ("settings", Button(_mx, _my + (_mbh + _mgap), _mbw, _mbh, "Settings", enabled=False)),
        ]
        if not self._is_spectator:
            self._esc_menu_btns.append(
                ("surrender", Button(_mx, _my + 2 * (_mbh + _mgap), _mbw, _mbh, "Surrender"))
            )
        _lobby_row = 3 if not self._is_spectator else 2
        self._esc_menu_btns.append(
            ("lobby", Button(_mx, _my + _lobby_row * (_mbh + _mgap), _mbw, _mbh, "Back to Lobby"))
        )

        # Sound effects
        from core.paths import asset_path
        _sounds_dir = asset_path("sounds")
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            self._sounds["fast_laser"] = pygame.mixer.Sound(os.path.join(_sounds_dir, "fast_laser.mp3"))
            self._sounds["laser"] = pygame.mixer.Sound(os.path.join(_sounds_dir, "laser.mp3"))
            # Generate artillery sound (pitch-shifted laser)
            _base = pygame.mixer.Sound(os.path.join(_sounds_dir, "laser.mp3"))
            _arr = pygame.sndarray.array(_base)
            _factor = 1.7
            _n = int(len(_arr) * _factor)
            _idx = np.linspace(0, len(_arr) - 1, _n).astype(np.int32)
            _heavy = _arr[_idx]
            _heavy_f = _heavy.astype(np.float32) * 1.4
            if np.issubdtype(_arr.dtype, np.integer):
                _info = np.iinfo(_arr.dtype)
                _heavy = np.clip(_heavy_f, _info.min, _info.max).astype(_arr.dtype)
            else:
                _heavy = np.clip(_heavy_f, -1.0, 1.0).astype(_arr.dtype)
            self._sounds["artillery"] = pygame.sndarray.make_sound(_heavy)
        except Exception:
            pass

    def _compute_build_btn_rects(self) -> list[tuple[pygame.Rect, str]]:
        """Compute spawn-type button rects inside the action panel area of the HUD."""
        # Action panel is rightmost 20% of HUD
        action_w = max(220, int(self.width * 0.20))
        ar = pygame.Rect(self.width - action_w, self.height - self._hud_h,
                         action_w, self._hud_h)
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

    def run(self) -> ScreenResult:
        pygame.event.set_grab(True)
        try:
            return self._run_loop()
        finally:
            pygame.event.set_grab(False)

    def _run_loop(self) -> ScreenResult:
        from systems import music
        while True:
            dt = self.clock.tick(60) / 1000.0
            music.update()
            self._anim_timer += dt
            if not self._paused:
                self._extrap_dt += dt

            # Poll for new state from host
            with self._frame_stats.scope("net"):
                frame = self._client.poll_state()
                if frame:
                    msg_type = frame.get("msg")
                    if msg_type == "state":
                        self._entities = frame.get("entities", [])
                        self._lasers = frame.get("lasers", [])
                        self._splashes = frame.get("splashes", [])
                        self._tick = frame.get("tick", 0)
                        self._winner = frame.get("winner", 0)
                        self._server_tick_ms = frame.get("srv_ms", 0.0)
                        self._server_tps = frame.get("srv_tps", 0.0)
                        self._disconnect_timer = 0.0
                        # Play sounds from server events
                        self._play_sound_events(frame.get("sounds", []))
                        # Spawn death-burst particles for units that died this tick
                        self._spawn_death_bursts(frame.get("deaths", []))
                        # Recompute movement extrapolation state
                        self._update_extrapolation(self._entities)
                        # Rebuild T2 upgrade display from entity state
                        self._refresh_t2_display()
                        # Process chat events
                        for ce in frame.get("chats", []):
                            msg = ChatMessage(
                                player_id=ce["pid"], player_name=ce["name"],
                                team_id=ce["tid"], message=ce["msg"],
                                mode=ce["mode"], tick=ce.get("tick", 0),
                                timestamp=self._game_time,
                            )
                            self._chat_log.add_message(msg)
                            # Spawn floating text above sender's CC
                            for ent in self._entities:
                                if ent.get("t") == "CC" and ent.get("pid") == ce["pid"]:
                                    color = PLAYER_COLORS[(ce["pid"] - 1) % len(PLAYER_COLORS)]
                                    self._floating_chats.append(FloatingChatText(
                                        x=ent["x"], y=ent["y"] - 60,
                                        message=ce["msg"], color=color,
                                        player_name=ce["name"],
                                    ))
                                    break
                    elif msg_type == "game_over":
                        self._winner = frame.get("winner", 0)
                else:
                    self._disconnect_timer += dt

            # Phase transitions
            if self._phase == "warp_in" and self._anim_timer >= 3.0:
                self._phase = "playing"

            if self._winner != 0 and self._phase == "playing":
                self._phase = "explode"
                self._anim_timer = 0.0
                # Close escape menu if game ended naturally
                if self._esc_menu_open:
                    self._esc_menu_open = False
                    pygame.event.set_grab(True)
                # Build fragments from losing CCs
                losing_teams = self._all_teams - {self._winner} if self._winner > 0 else set()
                for _lt in losing_teams:
                    self._init_fragments(_lt)

            # Update explosion fragments
            if self._phase == "explode":
                self._update_fragments(dt)

            # Update death-burst particles every frame (independent of phase)
            if self._death_bursts:
                self._death_bursts = [b for b in self._death_bursts if b.update(dt)]

            # Update floating chat text
            self._floating_chats = [fc for fc in self._floating_chats if fc.update(dt)]
            self._game_time += dt

            # Check for disconnect or game over
            if not self._is_local:
                lost = bool(self._client.error) or not self._client.connected
                if lost and self._winner == 0:
                    # Mid-game disconnect — kick back to lobby with a message.
                    self._client.stop()
                    return ScreenResult("multiplayer_lobby",
                                        data={"lost_connection": True})
                if lost:
                    return self._build_result()
            if self._phase == "explode" and self._anim_timer >= 3.0:
                return self._build_result()

            # Handle input
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._client.stop()
                    return ScreenResult("quit")

                # F3 toggles the frame-time breakdown overlay. Handled at the
                # top so it works regardless of chat/escape-menu state.
                if event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
                    self._show_perf = not self._show_perf
                    continue

                # -- Chat input handling (must be before ESC handler) --------
                if self._chat_input_active:
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            self._chat_input_active = False
                            self._chat_input_text = ""
                            self._chat_scroll = 0
                        elif event.key == pygame.K_RETURN:
                            if self._chat_input_text.strip():
                                self._client.send_command(GameCommand(
                                    type="chat",
                                    player_id=self._client.player_id,
                                    tick=self._tick,
                                    data={"message": self._chat_input_text,
                                          "mode": self._chat_mode},
                                ))
                            self._chat_input_active = False
                            self._chat_input_text = ""
                            self._chat_scroll = 0
                        elif event.key == pygame.K_TAB:
                            # Spectators have no team, so keep chat pinned to "all".
                            if not self._is_spectator:
                                self._chat_mode = (
                                    "team" if self._chat_mode == "all" else "all"
                                )
                        elif event.key == pygame.K_BACKSPACE:
                            self._chat_input_text = self._chat_input_text[:-1]
                        elif event.unicode and event.unicode.isprintable():
                            if len(self._chat_input_text) < MAX_MESSAGE_LENGTH:
                                self._chat_input_text += event.unicode
                    elif event.type == pygame.MOUSEWHEEL:
                        self._chat_scroll = max(0, self._chat_scroll - event.y)
                    continue  # block ALL events while chat is active

                # Enter key opens chat
                if (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN
                        and not self._esc_menu_open):
                    self._chat_input_active = True
                    self._chat_input_text = ""
                    self._chat_scroll = 0
                    continue

                # ESC toggles the escape menu (without pausing)
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._esc_menu_open = not self._esc_menu_open
                    pygame.event.set_grab(not self._esc_menu_open)
                    continue

                # When escape menu is open, only handle menu button clicks
                if self._esc_menu_open:
                    for action, btn in self._esc_menu_btns:
                        if btn.handle_event(event):
                            if action == "resume":
                                self._esc_menu_open = False
                                pygame.event.set_grab(True)
                            elif action == "surrender":
                                if self._winner == 0:
                                    other = self._all_teams - {self._my_team}
                                    self._winner = next(iter(other)) if other else -1
                                # Tell the server so it can end the game
                                self._client.send_command(GameCommand(
                                    type="surrender",
                                    player_id=self._my_team,
                                    tick=self._tick,
                                ))
                                return self._build_result()
                            elif action == "lobby":
                                if self._winner == 0:
                                    self._winner = -1
                                # Spectators have no team to surrender — just
                                # leave the view and return to the lobby.
                                if not self._is_spectator:
                                    self._client.send_command(GameCommand(
                                        type="surrender",
                                        player_id=self._my_team,
                                        tick=self._tick,
                                    ))
                                return self._build_result()
                            break
                    continue

                # Pause toggle (spacebar for local games)
                if (event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE
                        and self._is_local):
                    self._toggle_pause()

                # Selection hotkeys — spectators cannot select / command units.
                if event.type == pygame.KEYDOWN and self._is_spectator:
                    pass  # drop selection hotkeys
                elif event.type == pygame.KEYDOWN:
                    mods = pygame.key.get_mods()
                    if event.key == pygame.K_z and mods & pygame.KMOD_CTRL:
                        # Select own CC
                        self._selected_ids.clear()
                        for ent in self._entities:
                            if ent.get("t") == "CC" and ent.get("tm") == self._my_team:
                                eid = ent.get("id")
                                if eid is not None:
                                    self._selected_ids.add(eid)
                    elif event.key == pygame.K_TAB:
                        # Select all army units
                        self._selected_ids.clear()
                        for ent in self._entities:
                            if ent.get("t") == "U" and ent.get("tm") == self._my_team:
                                eid = ent.get("id")
                                if eid is not None:
                                    self._selected_ids.add(eid)
                    elif event.key == pygame.K_c and mods & pygame.KMOD_CTRL:
                        # Expand selection to all matching unit types
                        sel_types = set()
                        for ent in self._entities:
                            if (ent.get("t") == "U"
                                    and ent.get("id") in self._selected_ids):
                                sel_types.add(ent.get("ut"))
                        if sel_types:
                            for ent in self._entities:
                                if (ent.get("t") == "U"
                                        and ent.get("tm") == self._my_team
                                        and ent.get("ut") in sel_types):
                                    eid = ent.get("id")
                                    if eid is not None:
                                        self._selected_ids.add(eid)
                    elif event.key == pygame.K_s:
                        # Stop selected units
                        stop_ids = [
                            ent.get("id") for ent in self._entities
                            if ent.get("t") == "U"
                            and ent.get("id") in self._selected_ids
                        ]
                        if stop_ids:
                            self._client.send_command(GameCommand(
                                type="stop",
                                player_id=self._my_team,
                                tick=self._tick,
                                data={"unit_ids": stop_ids},
                            ))
                    elif event.key == pygame.K_f:
                        self._fight_mode = True
                    elif event.key == pygame.K_a:
                        self._attack_mode = True
                    elif event.key == pygame.K_h:
                        # Toggle hold fire on selected units
                        sel_units = [
                            ent for ent in self._entities
                            if ent.get("id") in self._selected_ids and ent.get("t") == "U"
                        ]
                        if sel_units:
                            any_not_held = any(not ent.get("hf") for ent in sel_units)
                            new_mode = "hold_fire" if any_not_held else "free_fire"
                            self._client.send_command(GameCommand(
                                type="set_fire_mode",
                                player_id=self._my_team,
                                tick=self._tick,
                                data={
                                    "unit_ids": [e["id"] for e in sel_units],
                                    "mode": new_mode,
                                },
                            ))
                    elif event.key in _CC_BUILD_HOTKEYS:
                        # CC build panel: pick the unit type at this list position.
                        has_own_cc = any(
                            ent.get("t") == "CC"
                            and ent.get("tm") == self._my_team
                            and ent.get("id") in self._selected_ids
                            for ent in self._entities
                        )
                        if has_own_cc:
                            spawnable = list(get_spawnable_types().keys())
                            idx = _CC_BUILD_HOTKEYS[event.key]
                            if idx < len(spawnable):
                                self._client.send_command(GameCommand(
                                    type="set_spawn_type",
                                    player_id=self._my_team,
                                    tick=self._tick,
                                    data={"unit_type": spawnable[idx]},
                                ))

                # Spectator: cycle through "All Teams / Team 1 / Team 2 / ..."
                if self._team_view_btn is not None and self._team_view_btn.handle_event(event):
                    n_opts = len(self._team_view_options)
                    if n_opts > 1:
                        self._team_view = (self._team_view + 1) % n_opts
                        _, label = self._team_view_options[self._team_view]
                        self._team_view_btn.label = label
                        self._selected_ids.clear()
                    continue

                # Header bar interactions (local controls)
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and self._is_local and self._header_rect.collidepoint(event.pos)):
                    mx_h, my_h = event.pos
                    if self._pause_btn and self._pause_btn.rect.collidepoint(mx_h, my_h):
                        self._toggle_pause()
                    elif self._reset_cam_btn and self._reset_cam_btn.rect.collidepoint(mx_h, my_h):
                        self._camera.reset()

                # Speed slider (local games)
                if self._is_local and self._speed_slider:
                    changed = self._speed_slider.handle_event(event)
                    if changed:
                        speed_pct = self._speed_slider.value
                        self._client.send_command(GameCommand(
                            type="set_speed",
                            player_id=self._my_team,
                            tick=self._tick,
                            data={"speed": speed_pct / 100.0},
                        ))

                # Zoom
                if event.type == pygame.MOUSEWHEEL:
                    mx, my = pygame.mouse.get_pos()
                    if self._game_area.collidepoint(mx, my):
                        vx = mx - self._game_area.x
                        vy = my - self._game_area.y
                        if event.y > 0:
                            self._camera.zoom_at(vx, vy, CAMERA_ZOOM_STEP)
                        elif event.y < 0:
                            self._camera.zoom_at(vx, vy, 1.0 / CAMERA_ZOOM_STEP)

                # Middle mouse pan
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
                    if self._game_area.collidepoint(event.pos):
                        self._mid_dragging = True
                        self._mid_last = event.pos
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
                    self._mid_dragging = False
                elif event.type == pygame.MOUSEMOTION and self._mid_dragging:
                    dx = event.pos[0] - self._mid_last[0]
                    dy = event.pos[1] - self._mid_last[1]
                    self._camera.pan(dx, dy)
                    self._mid_last = event.pos

                # Spectators cannot issue selection or commands; minimap click
                # still centers the camera though, so allow that path.
                spec_block = self._is_spectator

                # Left click — HUD or selection
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self._hud_rect.collidepoint(event.pos):
                        # Minimap click — center camera
                        minimap_world = gui.handle_minimap_click(
                            event.pos[0], event.pos[1],
                            self.width, self.height, self._hud_h,
                            self._map_w, self._map_h,
                        )
                        if minimap_world is not None:
                            self._camera.center_on(*minimap_world)
                            continue
                        if spec_block:
                            continue
                        self._handle_hud_click(event.pos)
                        # Check if a unit in the group grid was clicked
                        self._handle_display_click(event.pos)
                        continue
                    if self._game_area.collidepoint(event.pos) and not spec_block:
                        self._dragging = True
                        self._drag_start = event.pos
                        self._drag_end = event.pos

                elif event.type == pygame.MOUSEMOTION and self._dragging and not spec_block:
                    self._drag_end = event.pos

                elif (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                        and self._dragging and not spec_block):
                    self._dragging = False
                    self._handle_selection(event.pos)

                # Right click — movement commands (skip for spectators)
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 3
                        and not spec_block):
                    if self._game_area.collidepoint(event.pos):
                        self._rdragging = True
                        wx, wy = self._screen_to_world(event.pos)
                        self._rpath = [(wx, wy)]

                elif event.type == pygame.MOUSEMOTION and self._rdragging:
                    wx, wy = self._screen_to_world(event.pos)
                    if self._rpath:
                        lx, ly = self._rpath[-1]
                        if math.hypot(wx - lx, wy - ly) >= self._PATH_MIN_DIST:
                            self._rpath.append((wx, wy))

                elif event.type == pygame.MOUSEBUTTONUP and event.button == 3 and self._rdragging:
                    self._rdragging = False
                    wx, wy = self._screen_to_world(event.pos)
                    if not self._rpath:
                        self._rpath = [(wx, wy)]
                    elif math.hypot(wx - self._rpath[-1][0], wy - self._rpath[-1][1]) > 1:
                        self._rpath.append((wx, wy))
                    self._send_move_commands()
                    self._rpath = []
                    self._fight_mode = False
                    self._attack_mode = False

            # Edge panning (use screen edges, not game area edges)
            mx, my = pygame.mouse.get_pos()
            dx = dy = 0.0
            if mx <= EDGE_PAN_MARGIN:
                dx = EDGE_PAN_SPEED * dt
            elif mx >= self.width - EDGE_PAN_MARGIN - 1:
                dx = -EDGE_PAN_SPEED * dt
            if my <= EDGE_PAN_MARGIN:
                dy = EDGE_PAN_SPEED * dt
            elif my >= self.height - EDGE_PAN_MARGIN - 1:
                dy = -EDGE_PAN_SPEED * dt
            if dx or dy:
                self._camera.pan(dx, dy)

            self._draw()

    # -- selection ----------------------------------------------------------

    def _handle_selection(self, pos: tuple[int, int]) -> None:
        sx, sy = self._drag_start
        drag_r = math.hypot(pos[0] - sx, pos[1] - sy)
        additive = pygame.key.get_mods() & pygame.KMOD_SHIFT

        if drag_r < 5:
            # Double-click detection
            now = pygame.time.get_ticks()
            is_dblclick = (
                now - self._last_click_time < 400
                and math.hypot(pos[0] - self._last_click_pos[0],
                               pos[1] - self._last_click_pos[1]) < 10
            )
            self._last_click_time = now
            self._last_click_pos = pos

            # Click select
            wx, wy = self._screen_to_world(pos)
            if not additive:
                self._selected_ids.clear()
            best_id = None
            best_dist = float("inf")
            best_ut = None
            for ent in self._entities:
                if ent.get("tm") != self._my_team:
                    continue
                t = ent.get("t")
                if t not in ("U", "CC", "ME"):
                    continue
                ex, ey = ent.get("x", 0), ent.get("y", 0)
                r = ent.get("r", 5)
                d = math.hypot(ex - wx, ey - wy)
                if d <= r + 5 and d < best_dist:
                    best_dist = d
                    best_id = ent.get("id")
                    best_ut = ent.get("ut")
            if best_id is not None:
                self._selected_ids.add(best_id)
                # Double-click: select all visible units of same type
                if is_dblclick and best_ut:
                    vp = self._camera.get_world_viewport_rect()
                    for ent in self._entities:
                        if (ent.get("tm") == self._my_team
                                and ent.get("ut") == best_ut
                                and ent.get("t") == "U"
                                and vp.collidepoint(ent.get("x", 0),
                                                    ent.get("y", 0))):
                            eid = ent.get("id")
                            if eid is not None:
                                self._selected_ids.add(eid)
        else:
            # Drag select — army units take priority over buildings
            if not additive:
                self._selected_ids.clear()
            army_ids: list[int] = []
            building_ids: list[int] = []

            if display_config.selection_mode == "rectangle":
                # Rectangle select: corners are drag_start and release pos
                wx1, wy1 = self._screen_to_world(self._drag_start)
                wx2, wy2 = self._screen_to_world(pos)
                rx = min(wx1, wx2)
                ry = min(wy1, wy2)
                rw = abs(wx2 - wx1)
                rh = abs(wy2 - wy1)
                rcx, rcy = rx + rw / 2, ry + rh / 2
                hw, hh = rw / 2, rh / 2
                for ent in self._entities:
                    if ent.get("tm") != self._my_team:
                        continue
                    t = ent.get("t")
                    if t not in ("U", "CC", "ME"):
                        continue
                    ex, ey = ent.get("x", 0), ent.get("y", 0)
                    er = ent.get("r", 5)
                    if abs(ex - rcx) <= hw + er and abs(ey - rcy) <= hh + er:
                        eid = ent.get("id")
                        if eid is not None:
                            if t == "U":
                                army_ids.append(eid)
                            else:
                                building_ids.append(eid)
            else:
                # Circle select (center = drag start, radius = distance to release)
                ccx, ccy = self._screen_to_world(self._drag_start)
                w_ex, w_ey = self._screen_to_world(pos)
                sr = math.hypot(w_ex - ccx, w_ey - ccy)
                for ent in self._entities:
                    if ent.get("tm") != self._my_team:
                        continue
                    t = ent.get("t")
                    if t not in ("U", "CC", "ME"):
                        continue
                    ex, ey = ent.get("x", 0), ent.get("y", 0)
                    if math.hypot(ex - ccx, ey - ccy) <= sr:
                        eid = ent.get("id")
                        if eid is not None:
                            if t == "U":
                                army_ids.append(eid)
                            else:
                                building_ids.append(eid)

            targets = army_ids if army_ids else building_ids
            for eid in targets:
                self._selected_ids.add(eid)

    # -- HUD interaction ----------------------------------------------------

    def _handle_hud_click(self, pos: tuple[int, int]) -> None:
        proxies = wrap_entities(self._entities, self._selected_ids)
        mx, my = pos
        result = gui.handle_hud_click(
            proxies, mx, my,
            self.width, self.height, self._hud_h,
            enable_t2=self._enable_t2,
            t2_upgrades=self._t2_upgrades,
            t2_researching=self._t2_researching,
        )
        if result is None:
            return
        action = result["action"]
        if action == "set_spawn_type":
            self._client.send_command(GameCommand(
                type="set_spawn_type",
                player_id=self._my_team,
                tick=self._tick,
                data={"unit_type": result["unit_type"]},
            ))
        elif action == "stop":
            selected = [
                ent for ent in self._entities
                if ent.get("id") in self._selected_ids and ent.get("t") == "U"
            ]
            if selected:
                self._client.send_command(GameCommand(
                    type="stop",
                    player_id=self._my_team,
                    tick=self._tick,
                    data={"unit_ids": [e["id"] for e in selected]},
                ))
        elif action == "attack":
            self._attack_mode = True
        elif action == "move":
            self._fight_mode = False
            self._attack_mode = False
        elif action == "fight":
            self._fight_mode = True
        elif action == "hold_fire":
            sel_units = [
                ent for ent in self._entities
                if ent.get("id") in self._selected_ids and ent.get("t") == "U"
            ]
            if sel_units:
                any_not_held = any(not ent.get("hf") for ent in sel_units)
                new_mode = "hold_fire" if any_not_held else "free_fire"
                self._client.send_command(GameCommand(
                    type="set_fire_mode",
                    player_id=self._my_team,
                    tick=self._tick,
                    data={
                        "unit_ids": [e["id"] for e in sel_units],
                        "mode": new_mode,
                    },
                ))
        elif action == "upgrade_extractor":
            self._client.send_command(GameCommand(
                type="upgrade_extractor",
                player_id=self._my_team,
                tick=self._tick,
                data={"entity_id": result["entity_id"], "path": result["path"]},
            ))
        elif action == "set_research_type":
            self._client.send_command(GameCommand(
                type="set_research_type",
                player_id=self._my_team,
                tick=self._tick,
                data={"entity_id": result["entity_id"], "unit_type": result["unit_type"]},
            ))

    # -- commands -----------------------------------------------------------

    def _entity_at_world_pos(self, wx: float, wy: float) -> dict | None:
        """Find the closest entity (unit/building) at a world position."""
        best = None
        best_dist = float("inf")
        for ent in self._entities:
            t = ent.get("t")
            if t not in ("U", "CC", "ME"):
                continue
            ex, ey = ent.get("x", 0), ent.get("y", 0)
            r = ent.get("r", 5)
            d = math.hypot(ex - wx, ey - wy)
            if d <= r + 5 and d < best_dist:
                best_dist = d
                best = ent
        return best

    def _send_move_commands(self) -> None:
        """Send move commands for selected units to the drawn path."""
        shift_held = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        selected = [
            ent for ent in self._entities
            if ent.get("id") in self._selected_ids and ent.get("t") == "U"
        ]
        if not selected or not self._rpath:
            # Check for rally point on selected CC
            if self._rpath:
                rally = self._rpath[-1]
                for ent in self._entities:
                    if (ent.get("id") in self._selected_ids
                            and ent.get("t") == "CC"
                            and ent.get("tm") == self._my_team):
                        self._client.send_command(GameCommand(
                            type="set_rally",
                            player_id=self._my_team,
                            tick=self._tick,
                            data={"position": list(rally)},
                        ))
            return

        # Attack mode: check for entity under cursor
        if self._attack_mode and len(self._rpath) == 1:
            target_ent = self._entity_at_world_pos(*self._rpath[0])
            if target_ent is not None:
                target_id = target_ent.get("id")
                target_team = target_ent.get("tm")
                if target_team != self._my_team:
                    # Enemy: send attack-unit command per unit
                    for ent in selected:
                        cmd_data = {"unit_id": ent["id"], "target_id": target_id}
                        if shift_held:
                            cmd_data["queue"] = True
                        self._client.send_command(GameCommand(
                            type="attack",
                            player_id=self._my_team,
                            tick=self._tick,
                            data=cmd_data,
                        ))
                    return
                else:
                    # Ally: medics get attack (heal priority), others get attack-move
                    medic_ids = []
                    other_ids = []
                    for ent in selected:
                        ut = ent.get("ut", "")
                        stats = UNIT_TYPES.get(ut, {})
                        weapon = stats.get("weapon", {})
                        if weapon.get("hits_only_friendly"):
                            medic_ids.append(ent["id"])
                        else:
                            other_ids.append(ent["id"])
                    for mid in medic_ids:
                        cmd_data = {"unit_id": mid, "target_id": target_id}
                        if shift_held:
                            cmd_data["queue"] = True
                        self._client.send_command(GameCommand(
                            type="attack",
                            player_id=self._my_team,
                            tick=self._tick,
                            data=cmd_data,
                        ))
                    if other_ids:
                        px, py = self._rpath[0]
                        cmd_data = {"unit_ids": other_ids, "targets": [(px, py)] * len(other_ids)}
                        if shift_held:
                            cmd_data["queue"] = True
                        self._client.send_command(GameCommand(
                            type="attack_move",
                            player_id=self._my_team,
                            tick=self._tick,
                            data=cmd_data,
                        ))
                    return

        # Single point: all units go to same location
        if len(self._rpath) == 1:
            px, py = self._rpath[0]
            unit_ids = [e["id"] for e in selected]
            targets = [(px, py)] * len(unit_ids)
        else:
            # Resample path and assign goals
            goals = self._resample_path(len(selected))
            assigned: set[int] = set()
            unit_ids: list[int] = []
            targets: list[tuple[float, float]] = []
            for gx, gy in goals:
                best_idx = -1
                best_dist = float("inf")
                for i, ent in enumerate(selected):
                    if i in assigned:
                        continue
                    d = math.hypot(ent.get("x", 0) - gx, ent.get("y", 0) - gy)
                    if d < best_dist:
                        best_dist = d
                        best_idx = i
                if best_idx >= 0:
                    unit_ids.append(selected[best_idx]["id"])
                    targets.append((gx, gy))
                    assigned.add(best_idx)

        if unit_ids:
            if self._attack_mode:
                cmd_type = "attack_move"
            elif self._fight_mode:
                cmd_type = "fight"
            else:
                cmd_type = "move"
            cmd_data = {"unit_ids": unit_ids, "targets": targets}
            if shift_held:
                cmd_data["queue"] = True
            self._client.send_command(GameCommand(
                type=cmd_type,
                player_id=self._my_team,
                tick=self._tick,
                data=cmd_data,
            ))

    def _resample_path(self, n: int) -> list[tuple[float, float]]:
        path = self._rpath
        if n <= 0 or len(path) < 2:
            return list(path[:n])
        total = sum(
            math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
            for i in range(1, len(path))
        )
        if total < 1e-6:
            return [path[0]] * n
        if n == 1:
            return [path[len(path) // 2]]
        spacing = total / (n - 1)
        points: list[tuple[float, float]] = [path[0]]
        accumulated = 0.0
        seg = 1
        seg_start = path[0]
        for i in range(1, n - 1):
            target_dist = i * spacing
            while seg < len(path):
                sx, sy = seg_start
                ex, ey = path[seg]
                seg_len = math.hypot(ex - sx, ey - sy)
                if accumulated + seg_len >= target_dist:
                    frac = (target_dist - accumulated) / seg_len if seg_len > 0 else 0
                    points.append((sx + (ex - sx) * frac, sy + (ey - sy) * frac))
                    break
                accumulated += seg_len
                seg_start = path[seg]
                seg += 1
            else:
                points.append(path[-1])
        points.append(path[-1])
        return points

    # -- coordinate helpers -------------------------------------------------

    def _screen_to_world(self, pos: tuple[int, int]) -> tuple[float, float]:
        return self._camera.screen_to_world(
            float(pos[0] - self._game_area.x),
            float(pos[1] - self._game_area.y),
        )

    # -- result -------------------------------------------------------------

    def _build_result(self) -> ScreenResult:
        stats = None
        if self._is_local:
            self._client.stop()
        else:
            # Wait briefly for the server to process surrender and send stats
            import time
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                frame = self._client.poll_state()
                if frame and frame.get("msg") == "game_over":
                    break
                if self._client.game_over_stats is not None:
                    break
                time.sleep(0.05)
            stats = self._client.game_over_stats
            self._client.reset()
        # Build team_names from player_names / player_team, supporting N teams
        team_names: dict[int, str] = {}
        if self._player_names and self._client.player_team:
            for pid, pname in self._player_names.items():
                tm = self._client.player_team.get(pid, pid)
                team_names[tm] = pname
        if not team_names:
            team_names[self._my_team] = self._client._player_name
            opponent_name = self._client.opponent_name or self._client.host_name
            for t in self._all_teams - {self._my_team}:
                team_names[t] = opponent_name
        return ScreenResult("results", data={
            "winner": self._winner,
            "human_teams": set() if self._is_spectator else {self._my_team},
            "stats": stats,
            "replay_filepath": None,
            "team_names": team_names,
            "player_names": dict(self._player_names),
            "player_team": dict(self._client.player_team) if self._client.player_team else {},
            "was_spectator": self._is_spectator,
        })

    # -- display click (group grid → center camera) --------------------------

    def _handle_display_click(self, pos: tuple[int, int]) -> None:
        """If a unit box in the group grid was clicked, select only that unit."""
        proxies = wrap_entities(self._entities, self._selected_ids)
        mx, my = pos
        unit = gui.handle_display_click(
            proxies, mx, my,
            self.width, self.height, self._hud_h,
        )
        if unit is not None:
            self._selected_ids.clear()
            self._selected_ids.add(unit.entity_id)

    # -- pause / mouse grab -------------------------------------------------

    def _toggle_pause(self):
        self._paused = not self._paused
        pygame.event.set_grab(not self._paused)
        self._client.send_command(GameCommand(
            type="set_pause",
            player_id=self._my_team,
            tick=self._tick,
            data={"paused": self._paused},
        ))

    # -- movement extrapolation ----------------------------------------------

    @staticmethod
    def _effective_speed(ent: dict) -> float:
        """Compute effective unit speed accounting for ability modifiers."""
        base = UNIT_TYPES.get(ent.get("ut", ""), {}).get("speed", 0)
        if base <= 0:
            return 0.0
        mult = 1.0
        for ab in ent.get("abs", []):
            name = ab.get("n")
            if name == "focus":
                timer = ab.get("tm", 0.0)
                if timer > 0:
                    t = timer / 3.0
                    mult *= 0.25 + 0.75 * (1.0 - t)
            elif name == "electric_armor":
                stacks = ab.get("s", 0)
                mult *= 1.0 + 0.10 * stacks
            elif name == "combat_stim" and ab.get("a"):
                missing = max(0.0, ent.get("mhp", 0) - ent.get("hp", 0))
                stacks = int(missing / 10.0)
                mult *= 1.0 + 0.05 * stacks
        return base * mult

    def _refresh_t2_display(self) -> None:
        """Rebuild T2 upgrade display sets from raw entity dicts.

        Completed research goes into ``_t2_upgrades`` (CC can spawn the unit);
        in-progress research labs go into ``_t2_researching`` so the ME
        research grid greys out the unit but the CC UI still treats it as T1.
        """
        t2_done: dict[int, set[str]] = {}
        t2_wip: dict[int, set[str]] = {}
        for ent in self._entities:
            if ent.get("t") != "ME":
                continue
            us = ent.get("us", "base")
            rut = ent.get("rut", "") or None
            if not rut:
                continue
            team = ent.get("tm", 0)
            if us == "research_lab":
                t2_done.setdefault(team, set()).add(rut)
            elif us == "upgrading_lab":
                t2_wip.setdefault(team, set()).add(rut)
        self._t2_upgrades = t2_done
        self._t2_researching = t2_wip

    def _update_extrapolation(self, entities: list[dict]) -> None:
        """Recompute velocity predictions from the latest server frame.

        Hybrid: use actual position delta when we have a prior sample and the
        command hasn't just changed — this naturally yields zero velocity for
        units stuck in clumps, against obstacles, fight-paused with an enemy
        in range, or artillery locked while charging. Fall back to
        target-direction velocity on the first frame after a new command (or
        for a freshly-seen unit) so newly-issued moves feel responsive.
        """
        prev_positions = self._last_server_positions
        prev_targets = self._last_server_targets
        tick_delta = self._tick - self._last_extrap_tick
        frame_dt = tick_delta * FIXED_DT if tick_delta > 0 else 0.0

        positions: dict[int, tuple[float, float]] = {}
        velocities: dict[int, tuple[float, float]] = {}
        targets: dict[int, tuple] = {}
        for ent in entities:
            if ent.get("t") != "U":
                continue
            eid = ent.get("id")
            if eid is None:
                continue
            ex = ent.get("x", 0.0)
            ey = ent.get("y", 0.0)
            positions[eid] = (ex, ey)

            # Effective direction target: move target first, then attack target
            tx = ent.get("tx")
            ty = ent.get("ty")
            if tx is None or ty is None:
                tx = ent.get("atx")
                ty = ent.get("aty")

            # Track move target + presence of attack target for command-change
            # detection. atx/aty shifts with moving enemies, so we key on its
            # existence rather than its value to avoid spurious "new command"
            # triggers every frame while following a moving target.
            cur_target_key = (ent.get("tx"), ent.get("ty"),
                              ent.get("atx") is not None)
            targets[eid] = cur_target_key

            prev_pos = prev_positions.get(eid)
            prev_target_key = prev_targets.get(eid)
            new_command = (prev_target_key is not None
                           and prev_target_key != cur_target_key)

            if prev_pos is not None and frame_dt > 0.0 and not new_command:
                # Position-delta velocity: honours server-side blocking,
                # fight-pause, and charge-lock automatically.
                vx = (ex - prev_pos[0]) / frame_dt
                vy = (ey - prev_pos[1]) / frame_dt
                velocities[eid] = (vx, vy)
            elif tx is not None and ty is not None:
                # First frame after a new command (or brand-new entity):
                # aim straight at the target so the unit starts moving now
                # instead of waiting a full frame for the delta to catch up.
                dx = tx - ex
                dy = ty - ey
                dist = math.hypot(dx, dy)
                if dist > 0.5:
                    speed = self._effective_speed(ent)
                    velocities[eid] = (dx / dist * speed, dy / dist * speed)
                else:
                    velocities[eid] = (0.0, 0.0)
            else:
                velocities[eid] = (0.0, 0.0)

        self._last_server_positions = positions
        self._last_server_targets = targets
        self._last_extrap_tick = self._tick
        self._unit_velocities = velocities
        self._extrap_dt = 0.0

    def _apply_extrapolation(self, entities: list[dict]) -> list[dict]:
        """Return entity list with unit positions extrapolated forward."""
        dt = self._extrap_dt
        if dt <= 0:
            return entities
        result: list[dict] = []
        for ent in entities:
            eid = ent.get("id")
            if ent.get("t") == "U" and eid in self._unit_velocities:
                vx, vy = self._unit_velocities[eid]
                if vx != 0.0 or vy != 0.0:
                    sx, sy = self._last_server_positions.get(eid, (ent.get("x", 0), ent.get("y", 0)))
                    ent = dict(ent)
                    ent["x"] = sx + vx * dt
                    ent["y"] = sy + vy * dt
            result.append(ent)
        return result

    # -- sound effects ------------------------------------------------------

    def _play_sound_events(self, events: list[str]) -> None:
        """Play sound effects sent by the server."""
        if not self._sounds or not events:
            return
        for name in events:
            snd = self._sounds.get(name)
            if snd is not None:
                snd.set_volume(audio.master_volume)
                snd.play()

    def _spawn_death_bursts(self, events: list[dict]) -> None:
        """Spawn DeathBurst particles for unit-death events from the server."""
        if not events or self._phase != "playing":
            return
        DeathBurst.extend_from_events(self._death_bursts, events)

    # -- animations ---------------------------------------------------------

    def _init_fragments(self, losing_team: int) -> None:
        """Create 6 triangular fragments from each losing CC's hexagon."""
        for ent in self._entities:
            if ent.get("t") != "CC":
                continue
            if ent.get("tm") != losing_team:
                continue
            cx, cy = ent.get("x", 0), ent.get("y", 0)
            color = tuple(ent.get("c", [255, 255, 255]))
            pts = ent.get("pts", [])
            for i in range(len(pts)):
                p1 = pts[i]
                p2 = pts[(i + 1) % len(pts)]
                tri = [(0.0, 0.0), (p1[0], p1[1]), (p2[0], p2[1])]
                out_x = (p1[0] + p2[0]) / 2
                out_y = (p1[1] + p2[1]) / 2
                dist = math.hypot(out_x, out_y) or 1.0
                out_x /= dist
                out_y /= dist
                speed = random.uniform(40, 120)
                self._fragments.append({
                    "points": tri,
                    "cx": cx, "cy": cy,
                    "vx": out_x * speed + random.uniform(-20, 20),
                    "vy": out_y * speed + random.uniform(-20, 20),
                    "angle": 0.0,
                    "rot_speed": random.uniform(-4, 4),
                    "color": color,
                })

    def _update_fragments(self, dt: float) -> None:
        for frag in self._fragments:
            frag["cx"] += frag["vx"] * dt
            frag["cy"] += frag["vy"] * dt
            frag["angle"] += frag["rot_speed"] * dt

    def _render_warp_in(self, ws: pygame.Surface) -> None:
        """Draw CCs scaled in with glow rings during warp_in phase."""
        t = min(self._anim_timer / 3.0, 1.0)
        scale = t * (2.0 - t)  # ease-out

        for ent in self._entities:
            if ent.get("t") != "CC":
                continue
            cx, cy = ent.get("x", 0), ent.get("y", 0)
            color = tuple(ent.get("c", [255, 255, 255]))
            pts = ent.get("pts", [])
            tm = ent.get("tm", 1)
            if pts:
                scaled = [(cx + px * scale, cy + py * scale) for px, py in pts]
                pygame.draw.polygon(ws, color, scaled)
                pygame.draw.polygon(ws, color, scaled, 2)

            # Glow ring
            glow_radius = int(CC_RADIUS * 3 * t)
            glow_alpha = int(120 * (1.0 - t))
            if glow_radius > 0 and glow_alpha > 0:
                self._anim_surface.fill((0, 0, 0, 0))
                glow_color = (*color[:3], glow_alpha)
                pygame.draw.circle(self._anim_surface, glow_color,
                                   (int(cx), int(cy)), glow_radius, 3)
                ws.blit(self._anim_surface, (0, 0))

    def _render_explode(self, ws: pygame.Surface) -> None:
        """Draw explosion fragments flying out."""
        t = min(self._anim_timer / 3.0, 1.0)
        alpha = int(255 * (1.0 - t))
        if alpha <= 0:
            return
        self._anim_surface.fill((0, 0, 0, 0))
        for frag in self._fragments:
            cos_a = math.cos(frag["angle"])
            sin_a = math.sin(frag["angle"])
            rotated = []
            for px, py in frag["points"]:
                rx = px * cos_a - py * sin_a + frag["cx"]
                ry = px * sin_a + py * cos_a + frag["cy"]
                rotated.append((rx, ry))
            frag_color = (*frag["color"][:3], alpha)
            pygame.draw.polygon(self._anim_surface, frag_color, rotated)
        ws.blit(self._anim_surface, (0, 0))

    # -- rendering ----------------------------------------------------------

    def _mark_scratch_dirty(self, rect: pygame.Rect) -> None:
        """Union *rect* into this frame's scratch game-area dirty bbox.

        GPU-mode only; no-op in CPU mode. Callers pass rects in screen
        coordinates; the rect is clipped to `_game_area` and unioned with
        the running bbox.
        """
        if not self._gpu_mode:
            return
        clipped = rect.clip(self._game_area)
        if clipped.w <= 0 or clipped.h <= 0:
            return
        if self._scratch_game_bbox is None:
            self._scratch_game_bbox = clipped.copy()
        else:
            self._scratch_game_bbox.union_ip(clipped)

    def _compute_scratch_game_bbox(self) -> pygame.Rect | None:
        """Return the bbox (in screen coords) of scratch chrome inside
        the game area this frame, or None if nothing was drawn there.

        When a full-screen overlay is active (warp-in countdown, winner,
        paused, chat input, ESC menu, perf overlay) fall back to the
        full game_area — those overlays can cover arbitrary regions.
        Otherwise derive the bbox conservatively from entity label
        positions + floating chat trajectories + chat-log strip.

        This is GPU-mode-only; `present()` uses the result to pick how
        much of the scratch surface to upload to the GPU texture.
        """
        ga = self._game_area

        # Fullscreen-ish overlays: upload the whole game_area.
        if (self._phase == "warp_in"
                or self._winner != 0
                or (self._paused and self._is_local and not self._esc_menu_open)
                or self._chat_input_active
                or self._esc_menu_open
                or self._show_perf):
            return ga.copy()

        bbox: pygame.Rect | None = None

        def _u(r: pygame.Rect) -> None:
            nonlocal bbox
            c = r.clip(ga)
            if c.w <= 0 or c.h <= 0:
                return
            if bbox is None:
                bbox = c.copy()
            else:
                bbox.union_ip(c)

        # Entity label region — ME bonus labels, team names above CCs.
        # Labels render above the unit sprite; include margin for label
        # height + health bar / selection ring below.
        cam = self._camera
        for e in self._entities:
            ex = e.get("x", 0)
            ey = e.get("y", 0)
            sx, sy = cam.world_to_screen(ex, ey)
            sx += ga.x
            sy += ga.y
            r = e.get("r", 20)
            _u(pygame.Rect(
                int(sx - r - 24), int(sy - r - 64),
                int(r * 2 + 48), int(r * 2 + 84),
            ))

        # Floating chat text rises ~200 px from source.
        for fc in self._floating_chats:
            sx, sy = cam.world_to_screen(fc.x, fc.y)
            sx += ga.x
            sy += ga.y
            _u(pygame.Rect(int(sx - 150), int(sy - 260), 300, 280))

        # Chat log strip at top of game area when there are messages to
        # fade out.
        if self._chat_log.get_visible(self._game_time):
            _u(pygame.Rect(ga.x + 6, ga.y + 4, 500, 140))

        return bbox

    def present(self) -> None:
        """Present the current frame.

        CPU mode: defer to BaseScreen.present() (upload scratch to the
        streaming texture in GPU compat, or pygame.display.flip() in pure
        CPU).

        GPU mode: compose the frame directly on the SDL2 renderer by
        uploading the world and overlay surfaces as textures and drawing
        them in layer order:

            1. Clear renderer.
            2. Draw tiled dead-space bg (covers the full game_area so the
               areas beyond the map edge aren't transparent).
            3. Upload world_surface → ws_tex, draw scaled to game_area
               using the camera's viewport rect as srcrect (GPU scales).
            4. Upload fog / fx / arc overlays, draw at game_area position.
            5. Upload the scratch SRCALPHA surface → scratch_tex and draw
               it on top (alpha-blended). Chrome drawn on scratch lands
               on top; transparent regions within the game area let the
               composed content show through.
            6. Present.
        """
        if not self._gpu_mode:
            super().present()
            return

        ctx = display_config.gpu_context()
        renderer = ctx.renderer
        ga = self._game_area
        ga_dst = pygame.Rect(ga.x, ga.y, ga.w, ga.h)

        ctx.clear((0, 0, 0))

        # 1. Dead-space bg tile — cheap tiled draw against scaled tile
        # texture. For now, reuse the CPU blit_screen_background into a
        # scratch-less local surface and upload. This is not the final
        # implementation (future phase will keep the scaled tile on GPU),
        # but it preserves the dead-space look while we validate the
        # world-scale path.
        # Simpler interim: skip dead-space bg entirely — it only appears
        # at the extreme zoom-out corners on large maps; most play time
        # the world fills the game area so it's invisible anyway.

        # 2. Scaled world via GPU. Upload only the viewport region of
        # world_surface to ws_tex (the texture retains stale pixels
        # outside the viewport, but we only draw the viewport region so
        # those never appear on screen). This halves upload cost on
        # large maps where the viewport is a fraction of map area.
        vp = self._camera.get_world_viewport_rect()
        ws_rect = self._world_surface.get_rect()
        src = vp.clip(ws_rect)
        if src.w > 0 and src.h > 0:
            self._ws_tex.update(
                self._world_surface.subsurface(src), area=src,
            )
            # Compute dst sub-rect when the clipped source doesn't cover
            # the full viewport (e.g. panned past the map edge).
            dst_x = ga.x + int((src.x - vp.x) * self._camera.zoom)
            dst_y = ga.y + int((src.y - vp.y) * self._camera.zoom)
            dst_w = int(src.w * self._camera.zoom)
            dst_h = int(src.h * self._camera.zoom)
            self._ws_tex.draw(
                srcrect=src,
                dstrect=pygame.Rect(dst_x, dst_y, dst_w, dst_h),
            )

        # 3. Overlay textures — each is viewport-sized and already in
        # screen coords (phase-1 refactor put fog/fx/arc onto viewport
        # surfaces). Draw in the same order as the CPU pipeline:
        # arcs < lasers < fog.
        if self._arc_ready:
            self._arc_tex.update(self._arc_surface)
            self._arc_tex.draw(dstrect=ga_dst)
        if self._fx_ready:
            self._fx_tex.update(self._fx_surface)
            self._fx_tex.draw(dstrect=ga_dst)
        if self._fog_ready:
            # Upload only when the fog surface was rebuilt this frame.
            # On a cache hit, the texture still holds the correct content
            # from the last rebuild — just redraw it.
            if self._fog_tex_dirty:
                self._fog_tex.update(self._fog_surface)
            self._fog_tex.draw(dstrect=ga_dst)

        # 4. Metallic border via renderer primitives. Drawn as 3 nested
        # 1-px rect outlines with the border colours. This lives on the
        # renderer path so the scratch surface stays clean in the
        # game-area border region (otherwise scratch is dirty every
        # frame wherever the border crosses).
        if self._border_rect is not None:
            br = self._border_rect
            for i, col in enumerate((_BORDER_OUTER, _BORDER_MID, _BORDER_INNER)):
                r2 = br.inflate(-i * 2, -i * 2)
                if r2.w <= 0 or r2.h <= 0:
                    break
                renderer.draw_color = (col[0], col[1], col[2], 255)
                renderer.draw_rect(r2)

        # 5. Chrome scratch on top (alpha-blended). Upload only the rects
        # that changed this frame: header strip, HUD strip, and the
        # game-area chrome bbox (union with last frame's bbox so stale
        # pixels like moved labels get cleared). Full-game fallback when
        # a large overlay is active.
        bbox_game = self._compute_scratch_game_bbox()
        # Upload chrome strips (header + HUD) — they always change
        # (FPS counter, timers, build bars, etc.).
        self._scratch_tex.update(
            self.screen.subsurface(self._header_strip),
            area=self._header_strip,
        )
        self._scratch_tex.update(
            self.screen.subsurface(self._hud_strip),
            area=self._hud_strip,
        )
        # Upload the game-area bbox (this frame ∪ previous frame).
        upload_bbox: pygame.Rect | None = None
        if bbox_game is not None:
            upload_bbox = bbox_game.copy()
        if self._last_scratch_game_bbox is not None:
            if upload_bbox is None:
                upload_bbox = self._last_scratch_game_bbox.copy()
            else:
                upload_bbox.union_ip(self._last_scratch_game_bbox)
        if upload_bbox is not None:
            upload_bbox = upload_bbox.clip(self._game_area)
            if upload_bbox.w > 0 and upload_bbox.h > 0:
                self._scratch_tex.update(
                    self.screen.subsurface(upload_bbox),
                    area=upload_bbox,
                )
        self._last_scratch_game_bbox = bbox_game

        self._scratch_tex.draw()

        ctx.present()

    def _draw(self) -> None:
        ws = self._world_surface
        # Per-frame overlay readiness flags. Each overlay pass sets its flag
        # to True iff it has content to blit this frame.
        self._fog_ready = False
        self._fx_ready = False
        self._arc_ready = False
        # `_fog_tex_dirty` tracks whether the fog surface was rebuilt this
        # frame. In GPU mode we skip `fog_tex.update(...)` when the fog
        # cache hit — the texture still holds last frame's content which
        # is still correct. Huge win during static-camera play where fog
        # cache hits every frame.
        self._fog_tex_dirty = False
        if self._gpu_mode:
            # Reset scratch upload tracking. `_last_scratch_game_bbox` is
            # preserved from the previous frame so we can clear stale
            # pixels (e.g. labels that moved) via the union.
            self._scratch_game_bbox = None
            self._scratch_needs_full_game = False
            self._border_rect = None
        with self._frame_stats.scope("bg"):
            # Obstacles are baked into `_bg_surface`. Restore only the regions
            # that were drawn on last frame (entities + command arrows), not
            # the whole viewport. On the first frame `_last_dirty_rects` is
            # empty, so fall back to a viewport-wide restore.
            bg = self._bg_surface
            bg_rect = bg.get_rect()
            if self._last_dirty_rects:
                # Also clip every restore to the current viewport — no point
                # restoring pixels `camera.apply` never reads.
                vp = self._camera.get_world_viewport_rect()
                vp_clipped = vp.clip(bg_rect)
                for dr in self._last_dirty_rects:
                    clip = dr.clip(vp_clipped)
                    if clip.w > 0 and clip.h > 0:
                        ws.blit(bg, (clip.x, clip.y), area=clip)
            else:
                vp = self._camera.get_world_viewport_rect()
                clipped = vp.clip(bg_rect)
                if clipped.w > 0 and clipped.h > 0:
                    ws.blit(bg, (clipped.x, clipped.y), area=clipped)
        # Reset new-dirty accumulator for this frame.
        self._dirty_rects_new: list[pygame.Rect] = []

        with self._frame_stats.scope("entities"):
            # Sort entities by type for layering
            order = {"MS": 0, "ME": 1, "CC": 2, "U": 3}
            draw_entities = self._entities
            if display_config.movement_smoothing:
                draw_entities = self._apply_extrapolation(draw_entities)
            entities = sorted(draw_entities,
                              key=lambda e: order.get(e.get("t", ""), 4))

            is_warp_in = self._phase == "warp_in"

            # Collect LOS circles for fog-of-war visibility filtering
            if self._should_apply_fog():
                _los = self._collect_los_circles(entities)
                self._los_cache = _los
            else:
                _los = None
                self._los_cache = None

            # Resolve selected-and-visible entities once per frame. Previously
            # three separate passes (FOV arcs, selection rings, command
            # arrows) each re-scanned the full entity list.
            selected_visible: list[dict] = []
            if self._selected_ids:
                for ent in entities:
                    if ent.get("id") not in self._selected_ids:
                        continue
                    if _los is not None:
                        ex = ent.get("x", 0)
                        ey = ent.get("y", 0)
                        if not self._is_visible(ex, ey, _los):
                            continue
                    selected_visible.append(ent)

            # FOV arcs rendered onto viewport-sized `_arc_surface` in screen
            # coords. The actual screen blit happens later in the world
            # scope after camera.apply — world_surface is not touched here.
            # Consequence: arcs now layer on top of entity sprites rather
            # than beneath (previously drawn first on ws then covered).
            if not is_warp_in and selected_visible:
                self._draw_fov_arcs_batched(selected_visible)

            for ent in entities:
                t = ent.get("t")
                is_ghost = ent.get("ghost", False)
                if t == "MS":
                    self._draw_metal_spot(ent)
                elif t == "ME":
                    if is_ghost:
                        self._draw_metal_extractor_faded(ent)
                    elif _los is not None:
                        ex, ey = ent.get("x", 0), ent.get("y", 0)
                        if self._is_visible(ex, ey, _los):
                            self._draw_metal_extractor(ent)
                        else:
                            self._draw_metal_extractor_faded(ent)
                    else:
                        self._draw_metal_extractor(ent)
                elif t == "CC":
                    if not is_warp_in:
                        if is_ghost:
                            self._draw_command_center_faded(ent)
                        elif _los is not None and not self._is_visible(
                                ent.get("x", 0), ent.get("y", 0), _los):
                            self._draw_command_center_faded(ent)
                        else:
                            self._draw_command_center(ent)
                elif t == "U":
                    if not is_warp_in:
                        if _los is not None and not self._is_visible(
                                ent.get("x", 0), ent.get("y", 0), _los):
                            continue
                        self._draw_unit(ent)

            # Warp-in animation overlays CCs with scale + glow
            if is_warp_in:
                self._render_warp_in(ws)

            # Selection rings (drawn on top so selection is always visible).
            # Iterates the pre-filtered selected_visible list — no full-entity
            # scan needed.
            for ent in selected_visible:
                t = ent.get("t")
                ex = ent.get("x", 0)
                ey = ent.get("y", 0)
                r = CC_RADIUS + 2 if t == "CC" else ent.get("r", 5) + 2
                pygame.draw.circle(ws, SELECTED_COLOR, (int(round(ex)), int(round(ey))), int(r), 1)

            # Record entity bbox for next frame's bg restore. Includes a
            # generous margin for sprites, health bars, selection rings.
            if entities:
                emin_x = emin_y = 10 ** 9
                emax_x = emax_y = -(10 ** 9)
                for e in entities:
                    ex = e.get("x", 0)
                    ey = e.get("y", 0)
                    er = e.get("r", 20) + 12  # sprite + hp bar + ring
                    if ex - er < emin_x: emin_x = ex - er
                    if ex + er > emax_x: emax_x = ex + er
                    if ey - er < emin_y: emin_y = ey - er
                    if ey + er > emax_y: emax_y = ey + er
                self._dirty_rects_new.append(pygame.Rect(
                    int(emin_x), int(emin_y),
                    int(emax_x - emin_x) + 1, int(emax_y - emin_y) + 1,
                ))

        with self._frame_stats.scope("cmds"):
            self._draw_command_arrows(selected_visible)
            # Record command-arrow bbox for next frame's bg restore. Arrows
            # can span from selected units to distant targets and queue
            # waypoints — include all those endpoints.
            if selected_visible:
                cmin_x = cmin_y = 10 ** 9
                cmax_x = cmax_y = -(10 ** 9)
                have_cmd = False
                for e in selected_visible:
                    ex = e.get("x", 0)
                    ey = e.get("y", 0)
                    for key_x, key_y in (("tx", "ty"), ("atx", "aty"),
                                         ("rx", "ry")):
                        tx = e.get(key_x)
                        ty = e.get(key_y)
                        if tx is None or ty is None:
                            continue
                        have_cmd = True
                        if ex < cmin_x: cmin_x = ex
                        if ex > cmax_x: cmax_x = ex
                        if ey < cmin_y: cmin_y = ey
                        if ey > cmax_y: cmax_y = ey
                        if tx < cmin_x: cmin_x = tx
                        if tx > cmax_x: cmax_x = tx
                        if ty < cmin_y: cmin_y = ty
                        if ty > cmax_y: cmax_y = ty
                    for qcmd in e.get("cq", []) or []:
                        qx = qcmd.get("x")
                        qy = qcmd.get("y")
                        if qx is None or qy is None:
                            continue
                        have_cmd = True
                        if qx < cmin_x: cmin_x = qx
                        if qx > cmax_x: cmax_x = qx
                        if qy < cmin_y: cmin_y = qy
                        if qy > cmax_y: cmax_y = qy
                if have_cmd:
                    # Inflate by 8 px for arrowhead polygon.
                    self._dirty_rects_new.append(pygame.Rect(
                        int(cmin_x) - 8, int(cmin_y) - 8,
                        int(cmax_x - cmin_x) + 16,
                        int(cmax_y - cmin_y) + 16,
                    ))

        with self._frame_stats.scope("lasers"):
            # Render lasers in screen coords on the viewport-sized
            # `_fx_surface`; the final blit onto the screen happens in the
            # world scope after camera.apply. World_surface is not touched.
            if self._lasers:
                cam = self._camera
                zoom = cam.zoom
                drew_any = False
                for lf in self._lasers:
                    if len(lf) < 6:
                        continue
                    if _los is not None and not self._is_visible(lf[0], lf[1], _los):
                        continue
                    if not drew_any:
                        self._fx_surface.fill((0, 0, 0, 0))
                        drew_any = True
                    color = lf[4]
                    sx1, sy1 = cam.world_to_screen(lf[0], lf[1])
                    sx2, sy2 = cam.world_to_screen(lf[2], lf[3])
                    width = max(1, int(lf[5] * zoom))
                    pygame.draw.line(
                        self._fx_surface,
                        (color[0], color[1], color[2], 200),
                        (int(sx1), int(sy1)), (int(sx2), int(sy2)), width,
                    )
                if drew_any:
                    self._fx_ready = True

        with self._frame_stats.scope("effects"):
            # Charge beams (artillery charge preview)
            for ent in entities:
                chx = ent.get("chx")
                if chx is not None:
                    ex, ey = ent.get("x", 0), ent.get("y", 0)
                    if _los is not None and not self._is_visible(ex, ey, _los):
                        continue
                    chy = ent.get("chy", 0)
                    chp = ent.get("chp", 0)
                    orange = (255, 140, 0, int(100 + 100 * chp))
                    temp = pygame.Surface(ws.get_size(), pygame.SRCALPHA)
                    pygame.draw.line(temp, orange, (int(ex), int(ey)),
                                     (int(chx), int(chy)), 2)
                    # Splash ring at target
                    splash_r = int(30 * chp)
                    if splash_r > 0:
                        pygame.draw.circle(temp, (255, 100, 0, int(60 * chp)),
                                           (int(chx), int(chy)), splash_r, 1)
                    ws.blit(temp, (0, 0))

            # Splash effects (expanding red circles)
            for s in self._splashes:
                sx, sy = s.get("x", 0), s.get("y", 0)
                if _los is not None and not self._is_visible(sx, sy, _los):
                    continue
                sr = s.get("r", 30)
                sp = s.get("p", 0)
                cur_r = int(sr * sp)
                alpha = int(180 * (1.0 - sp))
                if cur_r > 0 and alpha > 0:
                    temp = pygame.Surface(ws.get_size(), pygame.SRCALPHA)
                    pygame.draw.circle(temp, (255, 60, 30, alpha),
                                       (int(sx), int(sy)), cur_r, 2)
                    ws.blit(temp, (0, 0))

            # Death-burst particles (drawn into the shared anim surface)
            if self._death_bursts:
                self._anim_surface.fill((0, 0, 0, 0))
                drew_any = False
                for b in self._death_bursts:
                    if _los is not None and not self._is_visible(b.x, b.y, _los):
                        continue
                    b.draw(self._anim_surface)
                    drew_any = True
                if drew_any:
                    ws.blit(self._anim_surface, (0, 0))

        # (ME bonus labels and team labels drawn in screen space after camera.apply)
        self._label_data = (entities, _los)

        # Drag selection visual
        if self._dragging:
            sx, sy = self._drag_start
            ex, ey = self._drag_end
            screen_r = math.hypot(ex - sx, ey - sy)
            if screen_r >= 5:
                self._selection_surface.fill((0, 0, 0, 0))
                if display_config.selection_mode == "rectangle":
                    wcx1, wcy1 = self._screen_to_world(self._drag_start)
                    wcx2, wcy2 = self._screen_to_world(self._drag_end)
                    rx = min(wcx1, wcx2)
                    ry = min(wcy1, wcy2)
                    rw = abs(wcx2 - wcx1)
                    rh = abs(wcy2 - wcy1)
                    rect = pygame.Rect(int(rx), int(ry), int(rw), int(rh))
                    pygame.draw.rect(self._selection_surface, SELECTION_FILL_COLOR, rect)
                    pygame.draw.rect(self._selection_surface, SELECTION_RECT_COLOR, rect, 1)
                    drag_bbox = pygame.Rect(
                        int(rx) - 2, int(ry) - 2, int(rw) + 4, int(rh) + 4,
                    )
                else:
                    wcx, wcy = self._screen_to_world(self._drag_start)
                    w_ex, w_ey = self._screen_to_world(self._drag_end)
                    wr = math.hypot(w_ex - wcx, w_ey - wcy)
                    pygame.draw.circle(self._selection_surface, SELECTION_FILL_COLOR,
                                       (int(wcx), int(wcy)), int(wr))
                    pygame.draw.circle(self._selection_surface, SELECTION_RECT_COLOR,
                                       (int(wcx), int(wcy)), int(wr), 1)
                    drag_bbox = pygame.Rect(
                        int(wcx - wr) - 2, int(wcy - wr) - 2,
                        int(wr) * 2 + 4, int(wr) * 2 + 4,
                    )
                ws.blit(self._selection_surface, (0, 0))
                self._dirty_rects_new.append(drag_bbox)

        # Right-click path with unit-count dots
        if self._rdragging and len(self._rpath) > 1:
            if self._attack_mode:
                path_color = (200, 80, 80)
            elif self._fight_mode:
                path_color = (200, 80, 200)
            else:
                path_color = (0, 200, 60)
            for i in range(1, len(self._rpath)):
                ax, ay = self._rpath[i - 1]
                bx, by = self._rpath[i]
                pygame.draw.line(ws, path_color, (ax, ay), (bx, by), 1)
            selected_count = sum(
                1 for e in self._entities
                if e.get("id") in self._selected_ids and e.get("t") == "U"
            )
            if selected_count > 0:
                preview = self._resample_path(selected_count)
                for px, py in preview:
                    pygame.draw.circle(ws, path_color, (int(px), int(py)), 3)
            # Dirty bbox spans the full path.
            pxs = [p[0] for p in self._rpath]
            pys = [p[1] for p in self._rpath]
            self._dirty_rects_new.append(pygame.Rect(
                int(min(pxs)) - 6, int(min(pys)) - 6,
                int(max(pxs) - min(pxs)) + 12,
                int(max(pys) - min(pys)) + 12,
            ))

        with self._frame_stats.scope("fog"):
            # Fog of war
            self._draw_fog(entities)

            # Explosion fragments overlay. Fragments scatter — use viewport
            # as the dirty rect for safety rather than tracking each piece.
            if self._phase == "explode":
                self._render_explode(ws)
                vp = self._camera.get_world_viewport_rect()
                self._dirty_rects_new.append(pygame.Rect(
                    vp.x, vp.y, vp.w, vp.h,
                ))

        # Warp-in CC glow rings extend ~3× CC_RADIUS beyond entity bboxes
        # and their stale pixels would otherwise persist on world_surface.
        # Force a restore of the entire map next frame while warp_in is
        # active — viewport-only isn't enough because enemy CCs can spawn
        # off-screen and their glow pixels linger after the user pans to
        # them (the viewport dirty rect for the last warp_in frame didn't
        # cover their position).
        if self._phase == "warp_in":
            self._dirty_rects_new.append(pygame.Rect(
                0, 0, self._map_w, self._map_h,
            ))

        _header_scope = self._frame_stats.scope("header")
        _header_scope.__enter__()
        # -- Composite to screen --
        # In GPU mode, scratch starts fully transparent so the GPU-composed
        # world + overlays show through wherever we don't paint chrome.
        if self._gpu_mode:
            self.screen.fill((0, 0, 0, 0))
        else:
            self.screen.fill((0, 0, 0))

        # Header bar
        pygame.draw.rect(self.screen, (20, 20, 30), self._header_rect)
        pygame.draw.line(self.screen, (40, 40, 55),
                         (0, self._header_h - 1),
                         (self.width, self._header_h - 1))

        # Header content
        font = _get_font(22)

        # Team indicator (spectators show a neutral "SPECTATING" label).
        if self._is_spectator:
            team_color = (230, 200, 90)
            team_label = self._spectator_font.render("SPECTATING", True, team_color)
        else:
            team_color = self._resolve_team_color(self._my_team)
            team_label = font.render(f"Team {self._my_team}", True, team_color)
        self.screen.blit(team_label, (10, 10))

        # Spectator's team-view cycle button
        if self._team_view_btn is not None:
            self._team_view_btn.draw(self.screen)

        # Game time (centered)
        m, s = divmod(self._tick // 60, 60)
        timer = font.render(f"{m}:{s:02d}", True, _STATUS_COLOR)
        self.screen.blit(timer, (self.width // 2 - timer.get_width() // 2, 10))

        # Disconnect warning (suppress for local games)
        if self._disconnect_timer > 3.0 and not self._is_local:
            warn = font.render("Connection lost...", True, _DISCONNECT_COLOR)
            self.screen.blit(warn, (self.width - warn.get_width() - 10, 10))

        # FPS (client render rate) and server-performance counter.
        # Server budget is 16.67 ms/tick at 60 TPS; colour the tick_ms
        # value by headroom so the player can spot a server bottleneck
        # that isn't visible in client FPS alone.
        fps_font = _get_font(18)
        fps_val = self.clock.get_fps()
        fps_surf = fps_font.render(f"FPS: {fps_val:.0f}", True, (200, 200, 200))
        fps_x = team_label.get_width() + 20
        if self._reset_cam_btn:
            fps_x = self._reset_cam_btn.rect.right + 10
        self.screen.blit(fps_surf, (fps_x, 12))

        if self._server_tps > 0.0:
            tick_ms = self._server_tick_ms
            if tick_ms < 5.0:
                srv_color = (110, 220, 130)
            elif tick_ms < 10.0:
                srv_color = (220, 200, 110)
            elif tick_ms < 16.67:
                srv_color = (220, 150, 90)
            else:
                srv_color = (220, 110, 110)
            srv_text = f"SRV: {self._server_tps:.0f} TPS / {tick_ms:.1f} ms"
            srv_surf = fps_font.render(srv_text, True, srv_color)
            self.screen.blit(srv_surf, (fps_x + fps_surf.get_width() + 12, 12))

        # Latency table (multiplayer only): "Name: 32 ms" for each connected
        # player, stacked top-down just below the header bar.
        if not self._is_local and self._client.pings:
            ping_font = _get_font(15)
            row_y = self._header_h + 4
            for pid in sorted(self._client.pings.keys()):
                ms = self._client.pings[pid]
                if ms <= 0:
                    continue  # not yet measured
                name = self._player_names.get(pid, f"P{pid}")
                if ms < 60:
                    color = (110, 220, 130)
                elif ms < 150:
                    color = (220, 200, 110)
                else:
                    color = (220, 110, 110)
                line = ping_font.render(f"{name}: {ms} ms", True, color)
                self.screen.blit(line, (self.width - line.get_width() - 10, row_y))
                row_y += line.get_height() + 1

        # Local game controls in header
        if self._is_local:
            if self._speed_slider:
                self._speed_slider.draw(self.screen)
            if self._pause_btn:
                self._pause_btn.draw(self.screen)
            if self._reset_cam_btn:
                self._reset_cam_btn.draw(self.screen)

        _header_scope.__exit__(None, None, None)
        _world_scope = self._frame_stats.scope("world")
        _world_scope.__enter__()
        from core.background import blit_screen_background
        ga = self._game_area
        if self._gpu_mode:
            # GPU mode: the scaled world, tiled dead-space bg, and overlay
            # textures are composed by the renderer in `present()`. Nothing
            # to paint onto the scratch surface here — it stays transparent
            # within the game area so that composed content shows through.
            pass
        else:
            # Game area: tiled background (covers beyond-map dead space)
            # then camera projection.
            blit_screen_background(self.screen, ga, self._camera, self._bg_tile)
            self._camera.apply(ws, self.screen, dest=(ga.x, ga.y))

            # Screen-space overlays: FOV arcs, lasers, fog. Each is
            # viewport-sized and has been prepared in screen coords by its
            # respective pass, so these are single cheap blits (no scale).
            # Metallic border still draws on top below.
            if self._arc_ready:
                bb = getattr(self, "_arc_bbox", None)
                if bb is not None:
                    self.screen.blit(
                        self._arc_surface,
                        (ga.x + bb.x, ga.y + bb.y),
                        area=bb,
                    )
                else:
                    self.screen.blit(self._arc_surface, (ga.x, ga.y))
            if self._fx_ready:
                self.screen.blit(self._fx_surface, (ga.x, ga.y))
            if self._fog_ready:
                self.screen.blit(self._fog_surface, (ga.x, ga.y))

        # Metallic border around the world edge (rendered in screen space)
        bx0, by0 = self._camera.world_to_screen(0, 0)
        bx1, by1 = self._camera.world_to_screen(self._map_w, self._map_h)
        border_rect = pygame.Rect(
            int(bx0) + ga.x, int(by0) + ga.y,
            int(bx1 - bx0), int(by1 - by0),
        )
        clip_save = self.screen.get_clip()
        self.screen.set_clip(ga)
        if self._gpu_mode:
            # Defer border drawing to present() so it renders via renderer
            # primitives — keeps the scratch surface clean of per-frame
            # border strokes (which would otherwise make scratch always
            # dirty in the game_area).
            self._border_rect = border_rect.clip(ga)
        else:
            _draw_metallic_border(self.screen, border_rect, 3)

        _world_scope.__exit__(None, None, None)
        _labels_scope = self._frame_stats.scope("labels")
        _labels_scope.__enter__()
        # Screen-space labels (crisp text at any zoom)
        if hasattr(self, '_label_data'):
            entities_l, _los_l = self._label_data
            cam = self._camera
            me_font_size = max(8, int(round(14 * cam.zoom)))
            me_font = _get_font(me_font_size)
            # ME spawn bonus labels
            for ent in entities_l:
                if ent.get("t") == "ME":
                    ex, ey = ent.get("x", 0), ent.get("y", 0)
                    if _los_l is not None and not self._is_visible(ex, ey, _los_l):
                        continue
                    meb = ent.get("meb", 0)
                    if meb > 0:
                        label = me_font.render(f"+{meb}%", True, (255, 255, 255))
                        wy = ey - ent.get("r", 10) - HEALTH_BAR_OFFSET - 12
                        sx, sy = cam.world_to_screen(ex, wy)
                        self.screen.blit(label, (int(sx) + ga.x - label.get_width() // 2,
                                                 int(sy) + ga.y))
            # Team name labels above CCs
            self._draw_team_labels_screen(entities_l, _los_l)

            # Floating chat text (world-space, rendered in screen-space)
            chat_font_size = max(8, int(round(20 * cam.zoom)))
            chat_font = _get_font(chat_font_size)
            for fc in self._floating_chats:
                alpha = int(220 * fc.alpha_frac)
                sx, sy = cam.world_to_screen(fc.x, fc.y)
                sy -= fc.rise_offset
                display = f"{fc.player_name}: {fc.message}" if fc.player_name else fc.message
                if len(display) > 50:
                    display = display[:47] + "..."
                chat_surf = chat_font.render(display, True, fc.color)
                chat_surf.set_alpha(alpha)
                self.screen.blit(chat_surf,
                                 (int(sx) + ga.x - chat_surf.get_width() // 2,
                                  int(sy) + ga.y))

        self.screen.set_clip(clip_save)

        _labels_scope.__exit__(None, None, None)
        _panel_scope = self._frame_stats.scope("panel")
        _panel_scope.__enter__()
        # HUD area
        pygame.draw.rect(self.screen, (20, 20, 30), self._hud_rect)
        pygame.draw.line(self.screen, (40, 40, 55),
                         (0, self._hud_rect.top),
                         (self.width, self._hud_rect.top))
        self._draw_hud()
        _panel_scope.__exit__(None, None, None)

        _overlays_scope = self._frame_stats.scope("overlays")
        _overlays_scope.__enter__()
        # Game-start countdown (3, 2, 1) overlay during warp-in
        if self._phase == "warp_in":
            draw_countdown_overlay(self.screen, self._game_area, self._anim_timer)

        # Winner overlay
        if self._winner:
            big_font = pygame.font.SysFont(None, 64)
            if self._winner == -1:
                text = "DRAW"
                color = (200, 200, 100)
            elif self._winner == self._my_team:
                text = "VICTORY!"
                color = (100, 255, 140)
            else:
                text = "DEFEAT"
                color = (255, 100, 100)
            surf = big_font.render(text, True, color)
            self.screen.blit(surf, (self.width // 2 - surf.get_width() // 2,
                                    self.height // 2 - surf.get_height() // 2))

        # PAUSED overlay (local games) — only when escape menu is not open
        if self._paused and self._is_local and self._pause_font and not self._esc_menu_open:
            pause_surf = self._pause_font.render("PAUSED", True, (255, 255, 255))
            px = self.width // 2 - pause_surf.get_width() // 2
            py = self.height // 2 - pause_surf.get_height() // 2
            self.screen.blit(pause_surf, (px, py))

        # Chat log overlay + chat input box
        self._draw_chat_overlay()
        if self._chat_input_active:
            self._draw_chat_input()

        # Escape menu overlay
        if self._esc_menu_open:
            self._draw_esc_menu()

        # Frame-time breakdown overlay (F3 toggle)
        if self._show_perf:
            self._draw_perf_overlay()

        _overlays_scope.__exit__(None, None, None)
        # Hand off this frame's dirty rects to be restored next frame.
        self._last_dirty_rects = self._dirty_rects_new
        with self._frame_stats.scope("flip"):
            self.present()

    # -- chat overlay / input -------------------------------------------------

    def _draw_chat_overlay(self) -> None:
        """Draw chat messages near the top-left of the game area.

        When chat input is open, shows the full scrollable history.
        Otherwise, shows only recent messages that fade out.
        """
        font = _get_font(20)
        ga = self._game_area
        x = ga.x + 8
        line_h = font.get_height() + 3

        if self._chat_input_active:
            all_msgs = self._chat_log.get_all()
            if not all_msgs:
                return
            max_lines = max(1, (ga.h - 60) // line_h)
            max_scroll = max(0, len(all_msgs) - max_lines)
            self._chat_scroll = min(self._chat_scroll, max_scroll)
            start = len(all_msgs) - max_lines - self._chat_scroll
            end = start + max_lines
            start = max(0, start)
            window = all_msgs[start:end]

            y = ga.y + 8
            for msg in window:
                prefix = "[TEAM] " if msg.mode == "team" else ""
                color = PLAYER_COLORS[(msg.player_id - 1) % len(PLAYER_COLORS)]
                text = f"{prefix}{msg.player_name}: {msg.message}"
                surf = font.render(text, True, color)
                bg = pygame.Surface((surf.get_width() + 8, surf.get_height() + 2), pygame.SRCALPHA)
                bg.fill((0, 0, 0, 150))
                self.screen.blit(bg, (x - 4, y - 1))
                self.screen.blit(surf, (x, y))
                y += line_h
        else:
            visible = self._chat_log.get_visible(self._game_time)
            if not visible:
                return
            y = ga.y + 8
            for msg in visible[-CHAT_DISPLAY_COUNT:]:
                age = self._game_time - msg.timestamp
                alpha = max(0, min(255, int(255 * (1.0 - age / CHAT_DISPLAY_DURATION))))
                prefix = "[TEAM] " if msg.mode == "team" else ""
                color = PLAYER_COLORS[(msg.player_id - 1) % len(PLAYER_COLORS)]
                text = f"{prefix}{msg.player_name}: {msg.message}"
                surf = font.render(text, True, color)
                surf.set_alpha(alpha)
                bg = pygame.Surface((surf.get_width() + 8, surf.get_height() + 2), pygame.SRCALPHA)
                bg.fill((0, 0, 0, int(120 * alpha / 255)))
                self.screen.blit(bg, (x - 4, y - 1))
                self.screen.blit(surf, (x, y))
                y += line_h

    def _draw_chat_input(self) -> None:
        """Draw the chat input box at the bottom of the game area."""
        font = _get_font(22)
        ga = self._game_area
        box_h = 28
        box_w = min(400, ga.w - 16)
        box_x = ga.x + 8
        box_y = ga.bottom - box_h - 8

        bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg.fill((20, 20, 30, 200))
        self.screen.blit(bg, (box_x, box_y))
        pygame.draw.rect(self.screen, (80, 80, 100),
                         pygame.Rect(box_x, box_y, box_w, box_h), 1)

        mode_label = "[ALL] " if self._chat_mode == "all" else "[TEAM] "
        mode_color = (200, 200, 200) if self._chat_mode == "all" else (100, 255, 100)
        mode_surf = font.render(mode_label, True, mode_color)
        self.screen.blit(mode_surf, (box_x + 6,
                                     box_y + (box_h - mode_surf.get_height()) // 2))

        text_x = box_x + 6 + mode_surf.get_width()
        max_text_w = box_w - mode_surf.get_width() - 16
        text_surf = font.render(self._chat_input_text, True, (220, 220, 220))
        if text_surf.get_width() > max_text_w:
            clip_x = text_surf.get_width() - max_text_w
            self.screen.blit(text_surf, (text_x, box_y + (box_h - text_surf.get_height()) // 2),
                             area=pygame.Rect(clip_x, 0, max_text_w, text_surf.get_height()))
            cursor_x = text_x + max_text_w + 2
        else:
            self.screen.blit(text_surf, (text_x,
                                         box_y + (box_h - text_surf.get_height()) // 2))
            cursor_x = text_x + text_surf.get_width() + 2

        if (pygame.time.get_ticks() // 500) % 2 == 0:
            pygame.draw.line(self.screen, (220, 220, 220),
                             (cursor_x, box_y + 5), (cursor_x, box_y + box_h - 5))

        hint_font = _get_font(16)
        hint = hint_font.render("TAB: toggle mode  |  ENTER: send  |  ESC: close  |  Scroll: history",
                                True, (100, 100, 120))
        self.screen.blit(hint, (box_x, box_y - hint.get_height() - 2))

    # -- perf overlay ---------------------------------------------------------

    def _draw_perf_overlay(self) -> None:
        """Top-left panel showing per-phase client frame-time breakdown.

        Rolling mean over ~1 s (60 samples). Rows are colour-coded by cost
        so a bottleneck (e.g. a 12 ms `lasers` row during chain lightning)
        stands out at a glance. Phases are summed into a `total` row; any
        gap vs. `1000/fps` is time spent idle or in un-instrumented work.
        """
        items = self._frame_stats.items()
        if not items:
            return

        font = _get_font(14)
        pad = 6
        line_h = font.get_height() + 2
        panel_w = 190
        panel_h = pad * 2 + line_h * (len(items) + 2)

        # Top-left, below the header bar. Ping table is top-right, so no conflict.
        x = 10
        y = self._header_h + 6

        overlay = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (x, y))
        pygame.draw.rect(self.screen, (80, 80, 100),
                         (x, y, panel_w, panel_h), 1)

        def _row_color(ms: float) -> tuple[int, int, int]:
            if ms < 1.0:
                return (140, 210, 150)
            if ms < 3.0:
                return (200, 210, 130)
            if ms < 6.0:
                return (230, 180, 100)
            return (230, 110, 110)

        total = 0.0
        ry = y + pad
        header = font.render("CLIENT FRAME (ms)", True, (200, 200, 220))
        self.screen.blit(header, (x + pad, ry))
        ry += line_h

        for name, ms in items:
            total += ms
            label = font.render(name, True, (210, 210, 215))
            value = font.render(f"{ms:5.2f}", True, _row_color(ms))
            self.screen.blit(label, (x + pad, ry))
            self.screen.blit(value, (x + panel_w - pad - value.get_width(), ry))
            ry += line_h

        # Total row is coloured by the 60 FPS frame budget (16.67 ms).
        if total < 10.0:
            total_color = (140, 210, 150)
        elif total < 14.0:
            total_color = (210, 200, 120)
        elif total < 16.67:
            total_color = (230, 170, 100)
        else:
            total_color = (230, 110, 110)
        total_label = font.render("total", True, (230, 230, 240))
        total_value = font.render(f"{total:5.2f}", True, total_color)
        self.screen.blit(total_label, (x + pad, ry))
        self.screen.blit(total_value, (x + panel_w - pad - total_value.get_width(), ry))

    # -- escape menu overlay ---------------------------------------------------

    def _draw_esc_menu(self) -> None:
        """Draw a semi-transparent overlay with pause menu buttons.

        Overlay surface and title text are static — build once on first open
        and reuse. The previous implementation allocated a full-screen
        SRCALPHA surface per frame, which spiked HUD time to 20+ ms while the
        menu was open (same bug pattern as the laser flash allocation).
        """
        if self._esc_menu_overlay is None:
            self._esc_menu_overlay = pygame.Surface(
                (self.width, self.height), pygame.SRCALPHA,
            )
            self._esc_menu_overlay.fill((0, 0, 0, 150))
            self._esc_menu_title = _get_font(48).render(
                "MENU", True, (220, 220, 240),
            )
        self.screen.blit(self._esc_menu_overlay, (0, 0))

        title_surf = self._esc_menu_title
        tx = self.width // 2 - title_surf.get_width() // 2
        first_btn_y = self._esc_menu_btns[0][1].rect.top
        ty = first_btn_y - title_surf.get_height() - 16
        self.screen.blit(title_surf, (tx, ty))

        for _, btn in self._esc_menu_btns:
            btn.draw(self.screen)

    # -- HUD drawing (delegated to gui.py via adapter) -----------------------

    def _draw_hud(self) -> None:
        """Draw the full HUD bar using gui.py through adapter proxies.

        ``wrap_entities`` is expensive (proxy + weapon + ability namespaces for
        every entity). The HUD only needs to reflect the server's state, which
        swaps at ~10 Hz, so cache the wrapped list by identity of
        ``self._entities`` and patch the ``selected`` flag in place when only
        the local selection changes.
        """
        entities = self._entities
        selected = self._selected_ids
        if self._hud_proxies is None or self._hud_proxies_entities is not entities:
            self._hud_proxies = wrap_entities(entities, selected)
            self._hud_proxies_entities = entities
            self._hud_proxies_selected = set(selected)
        elif self._hud_proxies_selected != selected:
            for p in self._hud_proxies:
                p.selected = p.entity_id in selected
            self._hud_proxies_selected = set(selected)

        gui.draw_hud(
            self.screen, self._hud_proxies,
            self.width, self.height, self._hud_h,
            enable_t2=self._enable_t2,
            t2_upgrades=self._t2_upgrades,
            t2_researching=self._t2_researching,
            camera=self._camera,
            world_w=self._map_w,
            world_h=self._map_h,
            obstacles=self._obstacles,
        )

    # -- entity drawing (adapted from ReplayPlaybackScreen) -----------------

    def _draw_command_line(self, x1: float, y1: float, x2: float, y2: float,
                           color: tuple) -> None:
        """Draw a command line with arrowhead from (x1,y1) to (x2,y2)."""
        ws = self._world_surface
        pygame.draw.line(ws, color, (x1, y1), (x2, y2), 1)
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        ux, uy = dx / dist, dy / dist
        px, py = -uy, ux
        s = _ARROW_SIZE
        wing1 = (x2 - ux * s + px * s * 0.5, y2 - uy * s + py * s * 0.5)
        wing2 = (x2 - ux * s - px * s * 0.5, y2 - uy * s - py * s * 0.5)
        pygame.draw.polygon(ws, color, [(x2, y2), wing1, wing2])

    def _draw_command_arrows(self, selected_visible: list[dict]) -> None:
        """Batched command-arrow pass for all selected units.

        Dedups arrows by (quantized_start, quantized_end, color) at an
        8 px grid. A group of units converging on the same target
        (a common RTS pattern) collapses to a single arrow instead of one
        per unit. Also coalesces overlapping queued-waypoint segments.
        The quantization is below the perceptual threshold against the
        existing 1 px line + arrowhead.
        """
        if not selected_visible:
            return
        ws = self._world_surface
        drawn: set[tuple] = set()
        GRID = 8

        for ent in selected_visible:
            ix, iy = int(round(ent.get("x", 0))), int(round(ent.get("y", 0)))

            # Active command
            if "atx" in ent and "aty" in ent:
                tx, ty = int(round(ent["atx"])), int(round(ent["aty"]))
                key = (ix // GRID, iy // GRID, tx // GRID, ty // GRID, 0)
                if key not in drawn:
                    drawn.add(key)
                    self._draw_command_line(ix, iy, tx, ty, _ATTACK_CMD_COLOR)
            elif "tx" in ent and "ty" in ent:
                if ent.get("am"):
                    color = _ATTACK_CMD_COLOR
                    cid = 0
                elif ent.get("fm"):
                    color = _FIGHT_CMD_COLOR
                    cid = 2
                else:
                    color = _MOVE_CMD_COLOR
                    cid = 1
                tx, ty = int(round(ent["tx"])), int(round(ent["ty"]))
                key = (ix // GRID, iy // GRID, tx // GRID, ty // GRID, cid)
                if key not in drawn:
                    drawn.add(key)
                    self._draw_command_line(ix, iy, tx, ty, color)

            # Queued waypoints
            cq = ent.get("cq")
            if not cq:
                continue
            if "atx" in ent:
                qpx, qpy = int(round(ent["atx"])), int(round(ent["aty"]))
            elif "tx" in ent:
                qpx, qpy = int(round(ent["tx"])), int(round(ent["ty"]))
            else:
                qpx, qpy = ix, iy
            for qcmd in cq:
                qx_val = qcmd.get("x")
                qy_val = qcmd.get("y")
                if qx_val is None or qy_val is None:
                    continue
                qx, qy = int(round(qx_val)), int(round(qy_val))
                qt = qcmd.get("t", "move")
                if qt == "attack_move" or qt == "attack":
                    qcolor = _ATTACK_CMD_COLOR
                    qcid = 0
                elif qt == "fight":
                    qcolor = _FIGHT_CMD_COLOR
                    qcid = 2
                else:
                    qcolor = _MOVE_CMD_COLOR
                    qcid = 1
                key = (qpx // GRID, qpy // GRID, qx // GRID, qy // GRID, qcid)
                if key not in drawn:
                    drawn.add(key)
                    self._draw_command_line(qpx, qpy, qx, qy, qcolor)
                    pygame.draw.circle(ws, qcolor, (qx, qy), 3, 1)
                qpx, qpy = qx, qy

    def _fov_arc_shape(self, ent: dict) -> tuple | None:
        """Return (kind, ix, iy, r, color[, fov_deg, fa]) for this unit's
        FOV/range arc, or None if the unit shouldn't show one.

        `kind` is "CIRCLE" for full circles (CC, outpost, 360° FOV units)
        and "ARC" for partial-FOV polylines.
        """
        t = ent.get("t")
        ix = int(round(ent.get("x", 0)))
        iy = int(round(ent.get("y", 0)))

        if t == "CC":
            return ("CIRCLE", ix, iy, int(CC_LASER_RANGE), RANGE_COLOR)

        if t == "ME":
            if ent.get("us") == "outpost":
                from config.settings import OUTPOST_LASER_RANGE
                return ("CIRCLE", ix, iy, int(OUTPOST_LASER_RANGE), RANGE_COLOR)
            return None

        ut = ent.get("ut", "soldier")
        stats = UNIT_TYPES.get(ut, {})
        weapon = stats.get("weapon")
        if not weapon:
            return None
        # Prefer live per-entity attack_range (includes sweeper aura) over the
        # static weapon.range from UNIT_TYPES.
        r = int(ent.get("rng", weapon.get("range", 50)))
        if r <= 0:
            return None

        is_healer = weapon.get("hits_only_friendly", False)
        if ent.get("hf"):
            color = (120, 120, 120)
        elif is_healer:
            color = MEDIC_HEAL_COLOR
        else:
            color = RANGE_COLOR

        fov_deg = stats.get("fov", 90)
        if fov_deg >= 359:
            return ("CIRCLE", ix, iy, r, color)

        return ("ARC", ix, iy, r, color, fov_deg, ent.get("fa", 0.0))

    def _draw_fov_arcs_batched(self, selected_visible: list[dict]) -> None:
        """Render FOV/range arcs onto viewport-sized `_arc_surface` in screen
        coords. The caller blits `_arc_surface` to the screen after
        camera.apply; `world_surface` is never touched.

        Bounding-box-clipped: only the arcs' collective bbox gets filled and
        blitted. For tight groups this is near-free.
        """
        self._arc_ready = False
        if not selected_visible:
            return

        cam = self._camera
        zoom = cam.zoom

        # Pass 1: convert each arc shape to SCREEN coords + accumulate bbox.
        # Each entry becomes (kind, sx, sy, rs, color[, fov_deg, fa]).
        shapes: list[tuple] = []
        min_x = min_y = 10 ** 9
        max_x = max_y = -(10 ** 9)
        for ent in selected_visible:
            shape = self._fov_arc_shape(ent)
            if shape is None:
                continue
            # shape has world ix, iy, world r — convert both.
            wix, wiy = shape[1], shape[2]
            wr = shape[3]
            sx, sy = cam.world_to_screen(wix, wiy)
            isx, isy = int(sx), int(sy)
            rs = max(1, int(wr * zoom))
            if shape[0] == "CIRCLE":
                shapes.append(("CIRCLE", isx, isy, rs, shape[4]))
            else:
                shapes.append(("ARC", isx, isy, rs, shape[4], shape[5], shape[6]))
            if isx - rs < min_x:
                min_x = isx - rs
            if isx + rs > max_x:
                max_x = isx + rs
            if isy - rs < min_y:
                min_y = isy - rs
            if isy + rs > max_y:
                max_y = isy + rs

        if not shapes:
            return

        arc = self._arc_surface
        fw, fh = arc.get_size()
        bb_x = max(0, min_x)
        bb_y = max(0, min_y)
        bb_r = min(fw, max_x + 1)
        bb_b = min(fh, max_y + 1)
        bb_w = bb_r - bb_x
        bb_h = bb_b - bb_y
        if bb_w <= 0 or bb_h <= 0:
            return
        bb_rect = pygame.Rect(bb_x, bb_y, bb_w, bb_h)
        # In GPU mode the whole surface is uploaded as a texture each
        # frame — stale pixels outside the current bb would become
        # visible trails on the screen. Full-fill to clear those.
        # In CPU mode we only blit bb to the screen, so a bb-only fill
        # is sufficient.
        if self._gpu_mode:
            arc.fill((0, 0, 0, 0))
        else:
            arc.fill((0, 0, 0, 0), rect=bb_rect)

        # Pass 2: draw arcs at screen coords on `_arc_surface`.
        for shape in shapes:
            kind = shape[0]
            if kind == "CIRCLE":
                _, sx, sy, rs, color = shape
                pygame.draw.circle(arc, color, (sx, sy), rs, 1)
            else:  # "ARC"
                _, sx, sy, rs, color, fov_deg, fa = shape
                fov = math.radians(fov_deg)
                half_fov = fov / 2.0
                start = fa - half_fov
                steps = max(int(fov_deg / 3), 8)
                points = [(sx, sy)]
                for i in range(steps + 1):
                    a = start + fov * i / steps
                    points.append((int(round(sx + rs * math.cos(a))),
                                   int(round(sy + rs * math.sin(a)))))
                points.append((sx, sy))
                pygame.draw.lines(arc, color, False, points, 1)

        # Stash bbox so the screen-blit step can copy only the used rect.
        self._arc_bbox = bb_rect
        self._arc_ready = True

    def _draw_unit(self, ent: dict) -> None:
        from core.sprite_cache import get_unit_sprite
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        c = tuple(ent.get("c", [255, 255, 255]))
        r = ent.get("r", 5)
        hp = ent.get("hp", 100)
        ut = ent.get("ut", "soldier")
        ix, iy = int(round(x)), int(round(y))

        # Command arrows are drawn in a separate batched pass
        # (see `_draw_command_arrows`) so the cost can be measured on its
        # own and redundant overlapping arrows can dedup.
        sprite = get_unit_sprite(ut, c, r)
        hw, hh = sprite.get_width() // 2, sprite.get_height() // 2
        ws.blit(sprite, (ix - hw, iy - hh))

        stats = UNIT_TYPES.get(ut, {})
        max_hp = ent.get("mhp", stats.get("hp", 100))
        if hp < max_hp:
            self._draw_health_bar(ix, iy, r + HEALTH_BAR_OFFSET, hp, max_hp)

        # Ability indicators above unit
        _ABILITY_COLORS = {
            "reactive_armor": REACTIVE_ARMOR_COLOR,
            "electric_armor": ELECTRIC_ARMOR_COLOR,
        }
        for ab in ent.get("abs", []):
            ab_name = ab.get("n", "")
            # Stack-based abilities: diamond indicators
            stacks = ab.get("s", 0)
            if stacks > 0 and ab_name in _ABILITY_COLORS:
                color = _ABILITY_COLORS[ab_name]
                size = 2 if ab_name == "electric_armor" else 3
                spacing = 5 if ab_name == "electric_armor" else 6
                y_off = r + 6
                start_x = ix - (stacks - 1) * spacing / 2
                for i in range(stacks):
                    cx = int(round(start_x + i * spacing))
                    cy = iy - y_off
                    pts = [
                        (cx, cy - size),
                        (cx + size, cy),
                        (cx, cy + size),
                        (cx - size, cy),
                    ]
                    pygame.draw.polygon(ws, color, pts)
            # Combat stim: green chevron when active
            elif ab_name == "combat_stim" and ab.get("a", False):
                cy = iy - r - 6
                size = 3
                pts = [(ix - size, cy + size), (ix, cy - size), (ix + size, cy + size)]
                pygame.draw.lines(ws, (100, 255, 100), False, pts, 2)

        # Hold fire indicator: small red X above unit
        if ent.get("hf"):
            hf_s = 3
            hf_y = iy - r - 4
            hf_c = (200, 60, 60)
            pygame.draw.line(ws, hf_c, (ix - hf_s, hf_y - hf_s), (ix + hf_s, hf_y + hf_s), 1)
            pygame.draw.line(ws, hf_c, (ix - hf_s, hf_y + hf_s), (ix + hf_s, hf_y - hf_s), 1)

    def _draw_command_center(self, ent: dict) -> None:
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        c = tuple(ent.get("c", [255, 255, 255]))
        pts = ent.get("pts", [])
        tm = ent.get("tm", 1)
        hp = ent.get("hp", 1000)

        if pts:
            translated = [(x + px, y + py) for px, py in pts]
            pygame.draw.polygon(ws, c, translated)
            pygame.draw.polygon(ws, c, translated, 2)

        # Spawn progress arc
        spt = ent.get("spt", 0.0)
        arc_r = CC_RADIUS + 5
        if spt < 1.0:
            start_angle = math.pi / 2
            end_angle = start_angle + spt * math.tau
            rect = pygame.Rect(x - arc_r, y - arc_r, arc_r * 2, arc_r * 2)
            pygame.draw.arc(ws, SELECTED_COLOR, rect, start_angle, end_angle, 2)
        else:
            pygame.draw.circle(ws, SELECTED_COLOR, (int(x), int(y)), int(arc_r), 2)

        # Rally point line + flag (only when selected)
        rx = ent.get("rx")
        if rx is not None and ent.get("id") in self._selected_ids:
            ry = ent.get("ry", 0)
            pygame.draw.line(ws, c, (x, y), (rx, ry), 1)
            pygame.draw.line(ws, (200, 200, 200), (rx, ry), (rx, ry - 14), 1)
            flag_pts = [(rx, ry - 14), (rx + 8, ry - 10), (rx, ry - 6)]
            pygame.draw.polygon(ws, c, flag_pts)
            pygame.draw.circle(ws, c, (int(rx), int(ry)), 3, 1)

        if hp < CC_HP:
            self._draw_health_bar(x, y, CC_RADIUS + HEALTH_BAR_OFFSET,
                                  hp, CC_HP, bar_w=40)

    def _resolve_team_color(self, team_id: int) -> tuple:
        """Return the color for a team, using server-provided team_colors if available."""
        if self._team_colors and team_id in self._team_colors:
            return self._team_colors[team_id]
        return TEAM_COLORS.get(team_id, PLAYER_COLORS[0])

    def _draw_metal_spot(self, ent: dict) -> None:
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        r = ent.get("r", 5)
        ow = ent.get("ow")
        cp = ent.get("cp", 0.0)

        cr = int(METAL_SPOT_CAPTURE_RADIUS)
        size = cr * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(temp, METAL_SPOT_CAPTURE_RANGE_COLOR, (cr, cr), cr)
        ws.blit(temp, (int(x) - cr, int(y) - cr))

        if ow is None:
            color = (255, 200, 60)
        else:
            color = self._resolve_team_color(ow)
        pygame.draw.circle(ws, color, (int(x), int(y)), int(r))

        cp_dict = normalize_cp(cp)
        if ow is None and cp_dict:
            arc_r = METAL_SPOT_CAPTURE_RADIUS + METAL_SPOT_CAPTURE_ARC_WIDTH
            rect = pygame.Rect(int(x - arc_r), int(y - arc_r),
                               int(arc_r * 2), int(arc_r * 2))
            start_angle = math.pi / 2
            for team_id, progress in cp_dict.items():
                if progress < 0.01:
                    continue
                progress_color = self._resolve_team_color(team_id)
                end_angle = start_angle + progress * math.tau
                pygame.draw.arc(ws, progress_color, rect,
                                start_angle, end_angle,
                                int(METAL_SPOT_CAPTURE_ARC_WIDTH))

    def _draw_metal_extractor(self, ent: dict) -> None:
        ws = self._world_surface
        x, y = ent.get("x", 0), ent.get("y", 0)
        r = ent.get("r", METAL_EXTRACTOR_RADIUS)
        rot = ent.get("rot", 0.0)
        hp = ent.get("hp", 200)
        c = tuple(ent.get("c", [255, 255, 255]))

        s = r * math.sqrt(3) / 2
        static_points = [
            complex(0, r),
            complex(-s, -r / 2),
            complex(s, -r / 2),
        ]
        rotated = [p * complex(math.cos(rot), math.sin(rot)) for p in static_points]
        points = [(p.real + x, p.imag + y) for p in rotated]
        pygame.draw.polygon(ws, c, points)
        pygame.draw.polygon(ws, (0, 0, 0), points, 1)

        # Reinforcement plating arcs
        rst = ent.get("rst", 0)
        if rst > 0:
            arc_color = c
            arc_r = METAL_SPOT_CAPTURE_RADIUS
            rect = pygame.Rect(x - arc_r, y - arc_r, arc_r * 2, arc_r * 2)
            arc_span = math.radians(87.5)
            half_span = arc_span / 2
            cardinal_angles = [
                math.radians(90),    # N
                math.radians(0),     # E
                math.radians(270),   # S
                math.radians(180),   # W
            ]
            for i in range(min(rst, 4)):
                center = cardinal_angles[i]
                start = center - half_span
                end = center + half_span
                pygame.draw.arc(ws, arc_color, rect, start, end, 2)

        max_hp = ent.get("mhp", METAL_EXTRACTOR_HP)
        if hp < max_hp:
            self._draw_health_bar(x, y, r + HEALTH_BAR_OFFSET,
                                  hp, max_hp)

    def _draw_health_bar(self, cx: float, cy: float, offset_y: float,
                         hp: float, max_hp: float,
                         bar_w: float = HEALTH_BAR_WIDTH) -> None:
        ws = self._world_surface
        ratio = hp / max_hp if max_hp > 0 else 0
        bx = int(round(cx - bar_w / 2))
        by = int(round(cy - offset_y))
        pygame.draw.rect(ws, HEALTH_BAR_BG,
                         (bx, by, bar_w, HEALTH_BAR_HEIGHT))
        fg = HEALTH_BAR_FG if ratio > 0.35 else HEALTH_BAR_LOW
        pygame.draw.rect(ws, fg,
                         (bx, by, int(bar_w * ratio), HEALTH_BAR_HEIGHT))

    def _draw_team_labels(self, entities: list[dict]) -> None:
        font = _get_font(20)
        ws = self._world_surface
        # Use enriched player_names from game_start, fallback to client/host names
        names: dict[int, str] = {}
        if self._player_names:
            # Build team→name mapping
            pt = self._client.player_team
            for pid, pname in self._player_names.items():
                tm = pt.get(pid, pid)
                names[tm] = pname
        if not names:
            names[self._my_team] = self._client._player_name
            opponent_name = self._client.opponent_name or self._client.host_name
            for t in self._all_teams - {self._my_team}:
                names[t] = opponent_name
        _los = getattr(self, '_los_cache', None)
        for ent in entities:
            if ent.get("t") != "CC":
                continue
            if _los is not None and not self._is_visible(
                    ent.get("x", 0), ent.get("y", 0), _los):
                continue
            tm = ent.get("tm", 1)
            name = names.get(tm, f"Team {tm}")
            # Append bonus % to name (matching game.py)
            bp = ent.get("bp", 0)
            if bp > 0:
                name = f"{name} (+{bp}%)"
            team_color = self._resolve_team_color(tm)
            name_surf = font.render(name, True, team_color)
            nx = int(ent.get("x", 0)) - name_surf.get_width() // 2
            ny = int(ent.get("y", 0)) - 40
            ws.blit(name_surf, (nx, ny))

    def _draw_team_labels_screen(self, entities: list[dict],
                                  _los=None) -> None:
        """Draw team name labels in screen space for crisp text at any zoom."""
        font = _get_font(max(8, int(round(20 * self._camera.zoom))))
        cam = self._camera
        ga = self._game_area
        names: dict[int, str] = {}
        if self._player_names:
            pt = self._client.player_team
            for pid, pname in self._player_names.items():
                tm = pt.get(pid, pid)
                names[tm] = pname
        if not names:
            names[self._my_team] = self._client._player_name
            opponent_name = self._client.opponent_name or self._client.host_name
            for t in self._all_teams - {self._my_team}:
                names[t] = opponent_name
        for ent in entities:
            if ent.get("t") != "CC":
                continue
            ex, ey = ent.get("x", 0), ent.get("y", 0)
            if _los is not None and not self._is_visible(ex, ey, _los):
                continue
            tm = ent.get("tm", 1)
            name = names.get(tm, f"Team {tm}")
            bp = ent.get("bp", 0)
            if bp > 0:
                name = f"{name} (+{bp}%)"
            team_color = self._resolve_team_color(tm)
            name_surf = font.render(name, True, team_color)
            sx, sy = cam.world_to_screen(ex, ey - 40)
            self.screen.blit(name_surf, (int(sx) + ga.x - name_surf.get_width() // 2,
                                         int(sy) + ga.y))

    @staticmethod
    def _build_background(width: int, height: int) -> tuple[pygame.Surface, pygame.Surface]:
        from core.background import build_background
        return build_background(width, height)

    def _effective_view_team(self) -> int | None:
        """Team whose LOS drives fog; ``None`` reveals everything (spectator 'All Teams')."""
        if self._is_spectator:
            if self._team_view == 0:
                return None
            return self._team_view_options[self._team_view][0]
        return self._my_team

    def _should_apply_fog(self) -> bool:
        """True when entity visibility should be gated by LOS for rendering."""
        if self._is_spectator:
            return self._team_view > 0
        return self._fog_of_war

    def _collect_los_circles(self, entities: list[dict]) -> list[tuple[int, int, int]]:
        """Collect LOS circles from the viewer's team for the fog overlay.

        Always computed client-side from the received entity positions
        (including extrapolation) so the fog updates smoothly at 60 FPS
        rather than at the server broadcast rate (~10 FPS). Spectators see
        through their selected team's vision (see ``_effective_view_team``).
        """
        view_team = self._effective_view_team()
        if view_team is None:
            return []
        circles: list[tuple[int, int, int]] = []
        for ent in entities:
            t = ent.get("t")
            if t not in ("U", "CC", "ME"):
                continue
            if ent.get("tm") != view_team:
                continue
            if ent.get("ghost", False):
                continue
            ut = ent.get("ut", "soldier")
            stats = UNIT_TYPES.get(ut, {})
            # Prefer the server-sent live LOS (includes sweeper aura stacking)
            # over the static base from UNIT_TYPES.
            los = int(ent.get("los", stats.get("los", 100)))
            # Outpost upgrade grants extended vision
            if ut == "metal_extractor" and ent.get("us") == "outpost":
                los = int(OUTPOST_LOS)
            if los > 0:
                circles.append((int(ent.get("x", 0)), int(ent.get("y", 0)), los))
        return circles

    @staticmethod
    def _is_visible(px: float, py: float,
                    los_circles: list[tuple[int, int, int]]) -> bool:
        """Check if a point is within any LOS circle."""
        for cx, cy, r in los_circles:
            dx = px - cx
            dy = py - cy
            if dx * dx + dy * dy <= r * r:
                return True
        return False

    def _draw_metal_extractor_faded(self, ent: dict, alpha: int = 90) -> None:
        """Draw a metal extractor at reduced opacity (seen through fog)."""
        x, y = ent.get("x", 0), ent.get("y", 0)
        margin = 40
        size = margin * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        saved_ws = self._world_surface
        self._world_surface = temp
        self._draw_metal_extractor(dict(ent, x=margin, y=margin))
        self._world_surface = saved_ws
        temp.set_alpha(alpha)
        saved_ws.blit(temp, (int(x - margin), int(y - margin)))

    def _draw_command_center_faded(self, ent: dict, alpha: int = 90) -> None:
        """Draw a command center at reduced opacity (ghost / seen through fog)."""
        x, y = ent.get("x", 0), ent.get("y", 0)
        margin = 40
        size = margin * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        saved_ws = self._world_surface
        self._world_surface = temp
        self._draw_command_center(dict(ent, x=margin, y=margin))
        self._world_surface = saved_ws
        temp.set_alpha(alpha)
        saved_ws.blit(temp, (int(x - margin), int(y - margin)))

    def _get_soft_brush(self, r: int) -> pygame.Surface:
        """Return a cached SRCALPHA circle brush with a soft alpha edge.

        Alpha is 255 from the center out to ``r - EDGE``, then falls linearly
        to 0 at the outer edge. Used with ``BLEND_RGBA_SUB`` to produce
        smoothly faded fog cut-outs without any separate blur pass.
        """
        brush = self._los_soft_brushes.get(r)
        if brush is not None:
            return brush
        size = r * 2
        brush = pygame.Surface((size, size), pygame.SRCALPHA)
        EDGE = 4.0
        # Radial distance → alpha via numpy (vectorised). 255 at center,
        # linear ramp to 0 across the last EDGE pixels of radius r.
        y, x = np.ogrid[:size, :size]
        d = np.sqrt((x - r) ** 2 + (y - r) ** 2)
        alpha = np.clip((r - d) / EDGE, 0.0, 1.0) * 255.0
        # pygame.surfarray.pixels_alpha indexes as [x, y]; numpy produced
        # [y, x], so transpose before assigning.
        arr = pygame.surfarray.pixels_alpha(brush)
        arr[:, :] = alpha.astype(np.uint8).T
        del arr  # release the surface lock
        self._los_soft_brushes[r] = brush
        return brush

    def _draw_fog(self, entities: list[dict]) -> None:
        """Prepare fog-of-war onto `self._fog_surface` in SCREEN coordinates.

        Does NOT touch `world_surface`. The caller is responsible for
        blitting `_fog_surface` onto the screen after `camera.apply`.

        Two layers of caching:
        * `_los_brushes` / `_los_soft_brushes` — circle brushes keyed by
          screen radius, built once and reused. Soft brushes have a radial
          alpha gradient baked in, so BLEND_RGBA_SUB against FOG_ALPHA fog
          produces smoothly faded edges without any separate blur pass.
        * `_fog_cache_key` — snapped screen positions + radii. Camera pan or
          zoom invalidates cache, but each miss is viewport-sized work
          (previously map-sized) so misses are much cheaper.
        """
        self._fog_ready = False
        if self._is_spectator and self._team_view == 0:
            return  # "All Teams" view reveals everything

        spectator_fog = self._is_spectator
        # 70% bg dimmed to ~30% → alpha ≈ 146; classic mode keeps heavier fog
        FOG_ALPHA = 146 if (self._fog_of_war and not spectator_fog) else 200
        soft_fog = self._fog_of_war and not spectator_fog
        draw_border = not soft_fog

        los_circles = getattr(self, '_los_cache', None)
        if los_circles is None:
            los_circles = self._collect_los_circles(entities)

        # Convert LOS circles from world to screen coords. `camera.world_to_screen`
        # returns viewport-relative coords — exactly what we need since the fog
        # surface is viewport-sized.
        cam = self._camera
        zoom = cam.zoom
        GRID = 2
        snapped: list[tuple[int, int, int]] = []
        for ex, ey, r in los_circles:
            sx, sy = cam.world_to_screen(ex, ey)
            # Snap to 2 px screen grid for cache stability; radius scales by zoom.
            isx = (int(sx) // GRID) * GRID
            isy = (int(sy) // GRID) * GRID
            rs = max(1, int(r * zoom))
            snapped.append((isx, isy, rs))
        snapped_tuple = tuple(snapped)

        cache_key = (FOG_ALPHA, soft_fog, draw_border, snapped_tuple)
        if cache_key == self._fog_cache_key:
            self._fog_ready = True
            return

        # -- Rebuild fog_surface (viewport-sized, screen coords). --
        if soft_fog:
            # Render directly at full viewport resolution using soft-edged
            # brushes. No smoothscale, no intermediate surface — the alpha
            # ramp in the brush IS the blur.
            self._fog_surface.fill((0, 0, 0, FOG_ALPHA))
            for sx, sy, rs in snapped:
                brush = self._get_soft_brush(rs)
                self._fog_surface.blit(brush, (sx - rs, sy - rs),
                                       special_flags=pygame.BLEND_RGBA_SUB)
        else:
            # Hard fog (spectator) — full viewport resolution, no blur.
            self._fog_surface.fill((0, 0, 0, FOG_ALPHA))
            for sx, sy, rs in snapped:
                brush = self._los_brushes.get(rs)
                if brush is None:
                    size = rs * 2
                    brush = pygame.Surface((size, size), pygame.SRCALPHA)
                    pygame.draw.circle(brush, (0, 0, 0, 255), (rs, rs), rs)
                    self._los_brushes[rs] = brush
                self._fog_surface.blit(brush, (sx - rs, sy - rs),
                                       special_flags=pygame.BLEND_RGBA_SUB)

        # Border ring (hard fog only). Two-pass: gray then inner black so
        # overlapping circles produce one ring around their union.
        if draw_border:
            self._fog_border.fill((0, 0, 0))
            for sx, sy, rs in snapped:
                pygame.draw.circle(self._fog_border, (160, 160, 160),
                                   (sx, sy), rs)
            for sx, sy, rs in snapped:
                pygame.draw.circle(self._fog_border, (0, 0, 0),
                                   (sx, sy), max(rs - 1, 0))
            # Composite border into fog_surface so a single final blit covers
            # both. Colorkey on _fog_border makes black transparent.
            self._fog_surface.blit(self._fog_border, (0, 0))

        self._fog_cache_key = cache_key
        self._fog_ready = True
        # Surface was rebuilt — the GPU texture (if any) needs re-uploading.
        self._fog_tex_dirty = True
