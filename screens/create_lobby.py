"""Create-lobby screen — two-column layout: player list (left), settings (right).
Supports up to 8 player slots with per-slot team assignment.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
import pygame
from screens.base import BaseScreen, ScreenResult
from systems import music
from ui.theme import (
    MENU_BG, CONTENT_TEXT, HEADING_FONT_SIZE, CONTENT_FONT_SIZE,
    BTN_WIDTH, BTN_HEIGHT, DD_HEIGHT, DD_FONT_SIZE,
)
from ui.widgets import (
    Button, BackButton, Dropdown, Slider, ToggleGroup, TextInput, Checkbox,
    _get_font,
)

# Player colour indicators — 8 distinct colours (matching in-game PLAYER_COLORS palette)
_PLAYER_COLORS = [
    (80,  140, 255),   # P1 blue
    (80,  220, 160),   # P2 teal
    (255,  80,  80),   # P3 red
    (255, 160,  60),   # P4 orange
    (180,  80, 220),   # P5 purple
    (80,  220, 220),   # P6 cyan
    (220, 220,  80),   # P7 yellow
    (220,  80, 160),   # P8 pink
]

_HUMAN_CHOICE = ("human", "Human")

# Map size presets
_MAP_PRESETS = [
    ("small",  "Small"),
    ("medium", "Medium"),
    ("large",  "Large"),
]
_MAP_SIZES = {
    "small":  (800,  600),
    "medium": (1200, 800),
    "large":  (1800, 1200),
}

from core.paths import app_path
_SETTINGS_PATH = app_path("lobby_settings.json")

_MAX_SLOTS = 8
_MIN_SLOTS = 2

# Slot row dimensions
_SLOT_ROW_H    = 38   # height per player row
_AI_DD_W       = 155  # AI / Human dropdown width
_TEAM_DD_W     = 72   # Team dropdown width
_REMOVE_BTN_W  = 26   # × button size
_HANDICAP_BTN_W = 92  # Add Handicap button width

# Handicap preset cycle — percent modifier applied to metal-extractor spawn
# bonus. -100% nullifies the bonus; +100% doubles it; +200% triples it.
_HANDICAP_STEPS = [-100, -75, -50, -25, 0, 25, 50, 75, 100, 150, 200]

# Panel visual constants
_PANEL_BG     = (18, 18, 28)
_PANEL_BORDER = (42, 42, 62)
_HDR_COLOR    = (160, 160, 185)   # subdued column-header colour
_DIVIDER_CLR  = (35, 35, 52)

_ONLINE_COLOR = (100, 255, 140)  # green tint for connected players

_TEAM_CHOICES = [(str(i), f"Team {i}") for i in range(1, 9)]

# Vertical layout constants (relative to top of screen)
_TITLE_Y      = 16
_PANEL_TOP_Y  = 56   # top of both panel rectangles
_PANEL_HDR_Y  = 64   # "Players" / "Settings" header text y
_COL_HDR_Y    = 86   # "AI / Human" and "Team" column header y
_SLOT_Y_START = 104  # y of first slot row


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_settings(settings: dict):
    try:
        with open(_SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


@dataclass
class _Slot:
    pid: int
    ai_dd: Dropdown
    team_dd: Dropdown
    remove_btn: Button
    handicap_btn: Button
    color_idx: int = 0
    name_input: TextInput | None = None  # only for human players
    online_pid: int = 0  # server-assigned player_id for connected online players
    handicap: int = 0    # percent modifier on metal-extractor spawn bonus


@dataclass
class _Spectator:
    """A player who opted out of a team and will watch the game instead."""
    name: str = ""
    online_pid: int = 0   # 0 = local offline spectator; otherwise server-assigned pid
    color_idx: int = 0    # remembered so rejoining restores the slot's look
    original_team: int = 1  # team to restore when rejoining

# Spectator sub-panel layout
_SPEC_GAP          = 10   # px gap between slot list and spectators panel
_SPEC_PANEL_PAD    = 8    # inner padding of the spectators sub-panel
_SPEC_ROW_H        = 26   # height per spectator row
_SPEC_HDR_H        = 22   # header strip height
_SPEC_BTN_H        = 26   # Join Spectator button
_SPEC_NEUTRAL_DOT  = (140, 140, 155)


class CreateLobbyScreen(BaseScreen):
    """Configure game format, AIs, and map settings, then start."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 ai_choices: list[tuple[str, str]],
                 server=None, online_client=None,
                 deprecated_ai_ids: set[str] | None = None):
        super().__init__(screen, clock)
        self._server = server  # InternalServer, reused across games
        self._online_client = online_client  # GameClient for online play

        # ai_choices contains every AI (deprecated included). We keep two
        # views: the full list (used when "Show Outdated AIs" is on) and the
        # active list (deprecated filtered out). Each slot's dropdown gets a
        # per-slot list that always retains its currently-selected ai_id, so
        # turning the toggle off can never silently invalidate a saved slot.
        self._deprecated_ai_ids: set[str] = set(deprecated_ai_ids or set())
        self._all_ai_choices: list[tuple[str, str]] = list(ai_choices)
        self._active_ai_choices: list[tuple[str, str]] = [
            (aid, name) for aid, name in self._all_ai_choices
            if aid not in self._deprecated_ai_ids
        ]
        # Backwards-compat alias used by existing helpers (_load_slots,
        # _add_slot, online sync). Default-pick should never be a deprecated
        # AI, so point at the active list.
        self._ai_choices = self._active_ai_choices
        self._full_choices: list[tuple[str, str]] = (
            [_HUMAN_CHOICE] + list(self._active_ai_choices)
        )

        # ── two-column layout ────────────────────────────────────────────────
        mid = self.width // 2

        # Left panel: player list
        self._lp_x = max(16, int(self.width * 0.03))  # panel rect left edge
        self._lp_w = mid - self._lp_x - 12            # panel rect width

        # Right panel: settings
        self._rp_x = mid + 12                          # panel rect left edge
        self._rp_w = self.width - self._rp_x - max(16, int(self.width * 0.03))

        # Slot row element x-positions (within left panel)
        self._label_x    = self._lp_x + 14             # dot + P# label
        self._ai_dd_x    = self._label_x + 44          # AI / Human dropdown
        self._team_dd_x  = self._ai_dd_x + _AI_DD_W + 8
        self._remove_x   = self._team_dd_x + _TEAM_DD_W + 6
        self._handicap_x = self._remove_x + _REMOVE_BTN_W + 6  # handicap button
        self._name_x     = self._handicap_x + _HANDICAP_BTN_W + 6  # inline name input
        self._name_w     = max(60, (self._lp_x + self._lp_w - 10) - self._name_x)

        # Right panel content starts here
        self._rx = self._rp_x + 14

        # ── widgets ─────────────────────────────────────────────────────────
        saved = _load_settings()

        # "Show Outdated AIs" toggle — when off, deprecated AIs are hidden
        # from dropdowns (except for any slot that already has one selected).
        self._show_outdated: bool = bool(saved.get("show_outdated_ais", False))

        self._slots: list[_Slot] = []
        self._load_slots(saved)

        # In online mode, replace slots with online-appropriate layout.
        # Start with only the local player's slot — joining the lobby must
        # not auto-add AI/extra slots, otherwise broadcasting our default
        # state would overwrite settings other players have configured.
        if self._online_client:
            self._slots.clear()
            local_pid = self._online_client.player_id
            local_name = self._online_client._player_name
            slot = self._make_slot(1, "human", 1, 0, name=local_name)
            slot.online_pid = local_pid
            self._slots.append(slot)

        # Spectator state — players who opted out of playing.
        self._spectators: list[_Spectator] = []

        # "+ Add Player" button (relabels to "Join Game" while local is spectator)
        self._add_btn = Button(self._label_x, 0, 150, 28, "+ Add Player",
                               font_size=14)
        # "Join Spectator" button lives in the spectators sub-panel.
        self._spec_btn = Button(self._label_x, 0, 140, _SPEC_BTN_H,
                                "Join Spectator", font_size=14)

        # Map size preset toggle
        saved_map = saved.get("map_size", "small")
        map_idx = next(
            (i for i, (v, _) in enumerate(_MAP_PRESETS) if v == saved_map), 0
        )
        ry = _SLOT_Y_START  # settings content top (aligned with first slot row)
        self._map_size = ToggleGroup(
            self._rx, ry + 20, _MAP_PRESETS,
            selected_index=map_idx, btn_w=73, btn_h=26,
        )

        self._sl_obstacles = Slider(
            self._rx, ry + 72, min(self._rp_w - 20, 220),
            "Obstacles", 0, 20, saved.get("obstacles", 0), 1,
        )
        self._sl_metal_spots = Slider(
            self._rx, ry + 126, min(self._rp_w - 20, 220),
            "Metal Spots / Side (0=random)", 0, 8, saved.get("metal_spots", 0), 1,
        )
        self._sl_time_limit = Slider(
            self._rx, ry + 180, min(self._rp_w - 20, 220),
            "Time Limit (min, 0=off)", 0, 60, saved.get("time_limit", 15), 1,
        )
        self._debug_summary_cb = Checkbox(
            self._rx, ry + 236,
            "Save game summary for debugging",
            checked=saved.get("save_debug_summary", False),
        )
        self._headless_cb = Checkbox(
            self._rx, ry + 266,
            "Headless (no rendering, max speed)",
            checked=saved.get("headless", False),
            enabled=False,
        )
        self._t2_cb = Checkbox(
            self._rx, ry + 296,
            "Enable T2 Units",
            checked=saved.get("enable_t2", False),
        )
        self._fog_of_war_cb = Checkbox(
            self._rx, ry + 326,
            "Fog of War",
            checked=saved.get("fog_of_war", False),
        )
        self._show_outdated_cb = Checkbox(
            self._rx, ry + 356,
            "Show Outdated AIs",
            checked=self._show_outdated,
        )

        # Bottom buttons (centered as a pair)
        cx = self.width // 2
        btn_y = self.height - 58
        btn_gap = 12
        self._back_btn = Button(
            cx - BTN_WIDTH - btn_gap // 2, btn_y,
            BTN_WIDTH, BTN_HEIGHT, "Back to Lobby",
        )
        self._start_btn = Button(
            cx + btn_gap // 2, btn_y, BTN_WIDTH, BTN_HEIGHT, "Start Game",
        )
        self._back = BackButton()

        # Lobby config sync state (online mode)
        self._last_lobby_config: dict | None = None
        self._last_received_config: dict | None = None

        self._rebuild_slot_positions()

    # ── slot helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _find_ai_index(ai_id: str | None, choices: list[tuple[str, str]],
                       default: int) -> int:
        if ai_id is None:
            return default
        for i, (val, _) in enumerate(choices):
            if val == ai_id:
                return i
        return default

    def _dropdown_choices_for(self, current_value: str | None) -> list[tuple[str, str]]:
        """Choice list for a single AI dropdown.

        Always begins with [Human] + active (non-deprecated) AIs. If the
        "Show Outdated AIs" toggle is on, all deprecated AIs are appended.
        Otherwise we still append just the slot's *current* deprecated value
        so an existing selection cannot silently disappear.
        """
        choices: list[tuple[str, str]] = [_HUMAN_CHOICE] + list(self._active_ai_choices)
        if self._show_outdated:
            for aid, name in self._all_ai_choices:
                if aid in self._deprecated_ai_ids:
                    choices.append((aid, name))
        elif current_value and current_value in self._deprecated_ai_ids:
            for aid, name in self._all_ai_choices:
                if aid == current_value:
                    choices.append((aid, name))
                    break
        return choices

    def _refresh_ai_dropdowns(self):
        """Rebuild every slot's AI dropdown choices after toggling outdated."""
        for slot in self._slots:
            current = slot.ai_dd.value
            new_choices = self._dropdown_choices_for(current)
            slot.ai_dd.choices = new_choices
            slot.ai_dd.selected_index = self._find_ai_index(current, new_choices, 0)

    def _slot_y(self, idx: int) -> int:
        return _SLOT_Y_START + idx * _SLOT_ROW_H

    def _make_slot(self, pid: int, ai_id: str, team_id: int, idx: int,
                   color_idx: int = -1, name: str = "",
                   handicap: int = 0) -> _Slot:
        y = self._slot_y(idx)
        choices = self._dropdown_choices_for(ai_id)
        ai_idx = self._find_ai_index(ai_id, choices, 0)
        team_idx = max(0, team_id - 1)
        ai_dd = Dropdown(self._ai_dd_x, y, _AI_DD_W, choices, ai_idx)
        team_dd = Dropdown(self._team_dd_x, y, _TEAM_DD_W, _TEAM_CHOICES, team_idx)
        remove_btn = Button(
            self._remove_x,
            y + (DD_HEIGHT - _REMOVE_BTN_W) // 2,
            _REMOVE_BTN_W, _REMOVE_BTN_W, "×",
        )
        handicap_btn = Button(
            self._handicap_x, y, _HANDICAP_BTN_W, DD_HEIGHT,
            self._handicap_label(handicap), font_size=14,
        )
        cidx = color_idx if color_idx >= 0 else idx % len(_PLAYER_COLORS)
        # Per-human name input (inline, same row after handicap button)
        name_input = TextInput(
            self._name_x, y, self._name_w,
            text=name, placeholder="Name", max_len=24,
        )
        return _Slot(pid=pid, ai_dd=ai_dd, team_dd=team_dd,
                     remove_btn=remove_btn, handicap_btn=handicap_btn,
                     color_idx=cidx, name_input=name_input,
                     handicap=int(handicap))

    @staticmethod
    def _handicap_label(pct: int) -> str:
        if pct == 0:
            return "Handicap"
        sign = "+" if pct > 0 else ""
        return f"Hcp {sign}{pct}%"

    @staticmethod
    def _cycle_handicap(current: int) -> int:
        # Snap current value to the nearest step, then advance.
        try:
            i = _HANDICAP_STEPS.index(current)
        except ValueError:
            # Nearest step if current doesn't match one (e.g. legacy value)
            i = min(range(len(_HANDICAP_STEPS)),
                    key=lambda j: abs(_HANDICAP_STEPS[j] - current))
        i = (i + 1) % len(_HANDICAP_STEPS)
        return _HANDICAP_STEPS[i]

    def _rebuild_slot_positions(self):
        for idx, slot in enumerate(self._slots):
            y = _SLOT_Y_START + idx * _SLOT_ROW_H
            slot.ai_dd.x = self._ai_dd_x
            slot.ai_dd.y = y
            slot.team_dd.x = self._team_dd_x
            slot.team_dd.y = y
            slot.remove_btn.rect.x = self._remove_x
            slot.remove_btn.rect.y = y + (DD_HEIGHT - _REMOVE_BTN_W) // 2
            slot.handicap_btn.rect.x = self._handicap_x
            slot.handicap_btn.rect.y = y
            slot.handicap_btn.label = self._handicap_label(slot.handicap)
            # Inline name input (same row, after handicap button)
            if slot.name_input:
                slot.name_input.rect.x = self._name_x
                slot.name_input.rect.y = y

        # Add button just below the last slot row
        n = len(self._slots)
        add_y = _SLOT_Y_START + n * _SLOT_ROW_H + 5
        self._add_btn.rect.y = add_y
        self._add_btn.rect.x = self._ai_dd_x
        # While local viewer is a spectator, the button becomes "Join Game".
        if self._is_local_spectator():
            self._add_btn.label = "Join Game"
            self._add_btn.enabled = n < _MAX_SLOTS
        else:
            self._add_btn.label = "+ Add Player"
            self._add_btn.enabled = n < _MAX_SLOTS

        # Spectators sub-panel sits below the add-player button.
        spec_y = add_y + 28 + _SPEC_GAP
        self._spec_panel_rect = self._compute_spec_panel_rect(spec_y)
        self._spec_btn.rect.x = self._spec_panel_rect.x + _SPEC_PANEL_PAD
        self._spec_btn.rect.y = (self._spec_panel_rect.bottom
                                 - _SPEC_BTN_H - _SPEC_PANEL_PAD)
        # Only offer "Join Spectator" when the local viewer is still playing.
        self._spec_btn.enabled = not self._is_local_spectator()

        has_human = any(s.ai_dd.value == "human" for s in self._slots)
        self._headless_cb.enabled = not has_human
        if has_human:
            self._headless_cb.checked = False

    def _compute_spec_panel_rect(self, top_y: int) -> pygame.Rect:
        """Rect for the Spectators sub-panel (header + list + Join button)."""
        list_h = max(1, len(self._spectators)) * _SPEC_ROW_H
        height = _SPEC_HDR_H + list_h + _SPEC_BTN_H + _SPEC_PANEL_PAD * 3
        # Indent slightly inside the left panel.
        x = self._lp_x + 10
        w = self._lp_w - 20
        return pygame.Rect(x, top_y, w, height)

    # ── spectator helpers ─────────────────────────────────────────────────────

    def _local_online_pid(self) -> int:
        """online_pid of the local client (or 0 in offline mode)."""
        if self._online_client:
            return int(self._online_client.player_id)
        return 0

    def _ping_for(self, online_pid: int) -> int | None:
        """Latency in ms for a connected player, or None if not yet measured."""
        if not self._online_client:
            return None
        ms = self._online_client.pings.get(int(online_pid))
        if ms is None or ms <= 0:
            return None
        return ms

    @staticmethod
    def _format_ping(ms: int) -> tuple[str, tuple[int, int, int]]:
        if ms < 60:
            color = (110, 220, 130)   # green
        elif ms < 150:
            color = (220, 200, 110)   # yellow
        else:
            color = (220, 110, 110)   # red
        return f"{ms} ms", color

    def _is_local_spectator(self) -> bool:
        if self._online_client:
            local_pid = self._local_online_pid()
            return any(sp.online_pid == local_pid for sp in self._spectators)
        return any(sp.online_pid == 0 for sp in self._spectators)

    def _join_spectator(self) -> None:
        """Move the local user from their slot into the Spectators list."""
        if self._is_local_spectator():
            return
        if self._online_client:
            local_pid = self._local_online_pid()
            for slot in list(self._slots):
                if slot.online_pid == local_pid:
                    self._spectators.append(_Spectator(
                        name=slot.name_input.text if slot.name_input else "",
                        online_pid=local_pid,
                        color_idx=slot.color_idx,
                        original_team=int(slot.team_dd.value),
                    ))
                    self._slots.remove(slot)
                    break
        else:
            # Offline: move the first human slot (local viewer).
            # Keep at least one playable slot so the game is startable.
            if sum(1 for s in self._slots) <= 1:
                return
            for slot in list(self._slots):
                if slot.ai_dd.value == "human":
                    self._spectators.append(_Spectator(
                        name=slot.name_input.text if slot.name_input else "",
                        online_pid=0,
                        color_idx=slot.color_idx,
                        original_team=int(slot.team_dd.value),
                    ))
                    self._slots.remove(slot)
                    break
        for i, s in enumerate(self._slots):
            s.pid = i + 1
        self._rebuild_slot_positions()

    def _rejoin_from_spectator(self) -> None:
        """Move the local spectator back into a playing slot."""
        if self._online_client:
            local_pid = self._local_online_pid()
            sp = next((s for s in self._spectators
                       if s.online_pid == local_pid), None)
        else:
            sp = next((s for s in self._spectators if s.online_pid == 0), None)
        if sp is None or len(self._slots) >= _MAX_SLOTS:
            return
        self._spectators.remove(sp)
        idx = len(self._slots)
        slot = self._make_slot(idx + 1, "human", sp.original_team, idx,
                               color_idx=sp.color_idx, name=sp.name)
        if sp.online_pid:
            slot.online_pid = sp.online_pid
        self._slots.append(slot)
        self._rebuild_slot_positions()

    def _load_slots(self, saved: dict):
        first_ai = self._ai_choices[0][0] if self._ai_choices else "human"
        slot_data = saved.get("slots")
        if slot_data and isinstance(slot_data, list) and len(slot_data) >= _MIN_SLOTS:
            for i, entry in enumerate(slot_data[:_MAX_SLOTS]):
                ai_id  = entry.get("ai_id", first_ai)
                team_id = int(entry.get("team", 1 if i == 0 else 2))
                color_idx = entry.get("color", i % len(_PLAYER_COLORS))
                name = entry.get("name", "")
                handicap = int(entry.get("handicap", 0))
                self._slots.append(self._make_slot(i + 1, ai_id, team_id, i,
                                                   color_idx=color_idx,
                                                   name=name,
                                                   handicap=handicap))
        else:
            # Legacy fallback
            fmt = saved.get("format", "1v1")
            if fmt == "2v2":
                pairs = [
                    (saved.get("ai_p1", "human"), 1),
                    (saved.get("ai_p2", first_ai), 1),
                    (saved.get("ai_p3", first_ai), 2),
                    (saved.get("ai_p4", first_ai), 2),
                ]
                for i, (ai_id, team_id) in enumerate(pairs):
                    self._slots.append(self._make_slot(i + 1, ai_id, team_id, i))
            else:
                p1 = saved.get("ai_p1", "human")
                p2 = saved.get("ai_p3", first_ai)
                self._slots.append(self._make_slot(1, p1, 1, 0))
                self._slots.append(self._make_slot(2, p2, 2, 1))

    def _next_free_color(self) -> int:
        used = {s.color_idx for s in self._slots}
        for i in range(len(_PLAYER_COLORS)):
            if i not in used:
                return i
        return len(self._slots) % len(_PLAYER_COLORS)

    def _cycle_color(self, slot: _Slot):
        used = {s.color_idx for s in self._slots if s is not slot}
        start = slot.color_idx
        for offset in range(1, len(_PLAYER_COLORS) + 1):
            candidate = (start + offset) % len(_PLAYER_COLORS)
            if candidate not in used:
                slot.color_idx = candidate
                return

    def _add_slot(self):
        if len(self._slots) >= _MAX_SLOTS:
            return
        first_ai = self._ai_choices[0][0] if self._ai_choices else "human"
        idx = len(self._slots)
        cidx = self._next_free_color()
        self._slots.append(self._make_slot(idx + 1, first_ai, 2, idx, color_idx=cidx))
        self._rebuild_slot_positions()

    def _remove_slot(self, slot: _Slot):
        if len(self._slots) <= _MIN_SLOTS:
            return
        if slot.online_pid:
            return  # cannot remove connected online players
        self._slots.remove(slot)
        for i, s in enumerate(self._slots):
            s.pid = i + 1
        self._rebuild_slot_positions()

    def _sync_online_slots(self):
        """Add/remove slots as online players connect/disconnect."""
        if not self._online_client:
            return
        lobby = self._online_client.lobby_status
        if not lobby:
            return

        players = lobby.get("players", {})
        connected: dict[int, str] = {}
        for pid_str, info in players.items():
            pid = int(pid_str) if isinstance(pid_str, str) else pid_str
            connected[pid] = info.get("name", "Player")

        local_pid = self._online_client.player_id
        if local_pid not in connected:
            connected[local_pid] = self._online_client._player_name

        current_online = {s.online_pid for s in self._slots if s.online_pid}
        spectator_online_pids = {
            sp.online_pid for sp in self._spectators if sp.online_pid
        }
        changed = False

        # Add new connected players as locked Human slots, unless they're
        # already tracked as a spectator on this host.
        for pid in sorted(connected.keys()):
            if pid in spectator_online_pids:
                continue
            if pid not in current_online:
                cidx = self._next_free_color()
                name = connected[pid]
                # Insert after existing online slots, before AI slots
                insert_idx = sum(1 for s in self._slots if s.online_pid > 0)
                slot = self._make_slot(
                    insert_idx + 1, "human", 2, insert_idx,
                    color_idx=cidx, name=name,
                )
                slot.online_pid = pid
                self._slots.insert(insert_idx, slot)
                changed = True

        # Remove disconnected players (never remove local player)
        for slot in list(self._slots):
            if (slot.online_pid
                    and slot.online_pid != local_pid
                    and slot.online_pid not in connected):
                self._slots.remove(slot)
                changed = True

        # Keep names in sync
        for slot in self._slots:
            if slot.online_pid and slot.online_pid in connected:
                name = connected[slot.online_pid]
                if slot.name_input and slot.name_input.text != name:
                    slot.name_input.text = name

        if changed:
            for i, s in enumerate(self._slots):
                s.pid = i + 1
            self._rebuild_slot_positions()

    # ── event loop ───────────────────────────────────────────────────────────

    def _any_dd_open(self) -> bool:
        return any(s.ai_dd.open or s.team_dd.open for s in self._slots)

    def run(self) -> ScreenResult:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if self._server is not None:
                        self._server.stop()
                    if self._online_client is not None:
                        self._online_client.stop()
                    return ScreenResult("quit")
                if self._back.handle_event(event) or self._back_btn.handle_event(event):
                    if self._server is not None:
                        self._server.stop()
                        self._server = None
                    if self._online_client is not None:
                        self._online_client.stop()
                        self._online_client = None
                    return ScreenResult("main_menu")

                # Per-slot name inputs (human players only, skip online slots)
                name_handled = False
                for slot in self._slots:
                    if slot.online_pid:
                        continue  # online slot names are locked
                    if slot.ai_dd.value == "human" and slot.name_input:
                        if slot.name_input.handle_event(event):
                            name_handled = True
                            break
                if name_handled:
                    continue

                # Dropdown handling (with open dropdown consuming clicks)
                dd_changed = False
                any_open = self._any_dd_open()
                for slot in self._slots:
                    # Skip AI dropdown for online slots (locked to Human)
                    if not slot.online_pid:
                        if slot.ai_dd.handle_event(event):
                            for s in self._slots:
                                if s is not slot:
                                    s.ai_dd.open = False
                                    s.team_dd.open = False
                            self._rebuild_slot_positions()
                            dd_changed = True
                            break
                    if slot.team_dd.handle_event(event):
                        for s in self._slots:
                            if s is not slot:
                                s.ai_dd.open = False
                                s.team_dd.open = False
                        dd_changed = True
                        break
                if dd_changed:
                    continue
                # If a dropdown was open and got closed, consume the click
                if any_open and not self._any_dd_open():
                    continue

                # Color dot click
                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    color_clicked = False
                    for slot in self._slots:
                        idx = slot.pid - 1
                        y = _SLOT_Y_START + idx * _SLOT_ROW_H
                        dot_cx = self._label_x + 6
                        dot_cy = y + DD_HEIGHT // 2
                        if (event.pos[0] - dot_cx) ** 2 + (event.pos[1] - dot_cy) ** 2 <= 64:
                            self._cycle_color(slot)
                            color_clicked = True
                            break
                    if color_clicked:
                        continue

                if self._add_btn.handle_event(event):
                    # "Join Game" when local is spectator, otherwise "+ Add Player".
                    if self._is_local_spectator():
                        self._rejoin_from_spectator()
                    else:
                        self._add_slot()
                    continue

                if self._spec_btn.handle_event(event):
                    self._join_spectator()
                    continue

                removed = None
                for slot in self._slots:
                    if slot.remove_btn.handle_event(event):
                        removed = slot
                        break
                if removed is not None:
                    self._remove_slot(removed)
                    continue

                # Handicap button click — cycle this slot's handicap value.
                handicap_clicked = False
                for slot in self._slots:
                    if slot.handicap_btn.handle_event(event):
                        slot.handicap = self._cycle_handicap(slot.handicap)
                        slot.handicap_btn.label = self._handicap_label(slot.handicap)
                        handicap_clicked = True
                        break
                if handicap_clicked:
                    continue

                self._map_size.handle_event(event)
                self._sl_obstacles.handle_event(event)
                self._sl_metal_spots.handle_event(event)
                self._sl_time_limit.handle_event(event)
                self._debug_summary_cb.handle_event(event)
                self._headless_cb.handle_event(event)
                self._t2_cb.handle_event(event)
                self._fog_of_war_cb.handle_event(event)
                if self._show_outdated_cb.handle_event(event):
                    self._show_outdated = self._show_outdated_cb.checked
                    self._refresh_ai_dropdowns()

                if self._start_btn.handle_event(event):
                    self._persist_settings()
                    if self._online_client is not None:
                        self._send_online_start()
                    else:
                        return self._build_result()

            # Online mode: sync connected players, settings, and check game start
            if self._online_client is not None:
                # Detect connection loss while sitting in the lobby.
                if (self._online_client.error
                        or not self._online_client.connected):
                    self._online_client.stop()
                    self._online_client = None
                    return ScreenResult("multiplayer_lobby",
                                        data={"lost_connection": True})
                self._sync_online_slots()
                self._maybe_apply_received_config()
                self._maybe_broadcast_config()
                if self._online_client.game_started:
                    return ScreenResult("mp_client_game", data={
                        "client": self._online_client,
                        "from_online_lobby": True,
                    })

            self._draw()
            self.clock.tick(60)
            music.update()

    # ── lobby config sync (online mode) ─────────────────────────────────────

    def _gather_lobby_config(self) -> dict:
        """Serialize current lobby state for network broadcast."""
        ai_slots = []
        player_teams: dict[str, int] = {}
        player_colors: dict[str, int] = {}
        player_handicaps: dict[str, int] = {}
        for slot in self._slots:
            if slot.online_pid:
                player_teams[str(slot.online_pid)] = int(slot.team_dd.value)
                player_colors[str(slot.online_pid)] = slot.color_idx
                player_handicaps[str(slot.online_pid)] = int(slot.handicap)
            else:
                ai_slots.append({
                    "ai_id": slot.ai_dd.value,
                    "team": int(slot.team_dd.value),
                    "color_idx": slot.color_idx,
                    "handicap": int(slot.handicap),
                })
        spectators = [
            {"online_pid": sp.online_pid, "name": sp.name,
             "color_idx": sp.color_idx, "original_team": sp.original_team}
            for sp in self._spectators
        ]
        return {
            "map_size": self._map_size.value,
            "obstacles": self._sl_obstacles.value,
            "metal_spots": self._sl_metal_spots.value,
            "time_limit": self._sl_time_limit.value,
            "enable_t2": self._t2_cb.checked,
            "fog_of_war": self._fog_of_war_cb.checked,
            "ai_slots": ai_slots,
            "player_teams": player_teams,
            "player_colors": player_colors,
            "player_handicaps": player_handicaps,
            "spectators": spectators,
        }

    def _apply_lobby_config(self, config: dict) -> None:
        """Apply received lobby configuration from another client."""
        # Map size
        map_key = config.get("map_size")
        if map_key:
            for i, (v, _) in enumerate(_MAP_PRESETS):
                if v == map_key:
                    self._map_size.selected_index = i
                    break

        # Sliders
        if "obstacles" in config:
            self._sl_obstacles.value = int(config["obstacles"])
        if "metal_spots" in config:
            self._sl_metal_spots.value = int(config["metal_spots"])
        if "time_limit" in config:
            self._sl_time_limit.value = int(config["time_limit"])

        # Checkboxes
        if "enable_t2" in config:
            self._t2_cb.checked = bool(config["enable_t2"])
        if "fog_of_war" in config:
            self._fog_of_war_cb.checked = bool(config["fog_of_war"])

        # AI slots — rebuild non-online slots from received data
        ai_slots = config.get("ai_slots")
        if ai_slots is not None:
            # Remove existing non-online slots
            self._slots = [s for s in self._slots if s.online_pid]
            # Add received AI slots
            for entry in ai_slots:
                idx = len(self._slots)
                cidx = entry.get("color_idx", self._next_free_color())
                ai_id = entry.get("ai_id", "human")
                team = int(entry.get("team", 2))
                handicap = int(entry.get("handicap", 0))
                slot = self._make_slot(idx + 1, ai_id, team, idx,
                                       color_idx=cidx, handicap=handicap)
                self._slots.append(slot)
            for i, s in enumerate(self._slots):
                s.pid = i + 1
            self._rebuild_slot_positions()

        # Player team, color, and handicap assignments (for online slots)
        player_teams = config.get("player_teams", {})
        player_colors = config.get("player_colors", {})
        player_handicaps = config.get("player_handicaps", {})
        for slot in self._slots:
            if slot.online_pid:
                pt_key = str(slot.online_pid)
                if pt_key in player_teams:
                    team_val = str(int(player_teams[pt_key]))
                    for i, (v, _) in enumerate(_TEAM_CHOICES):
                        if v == team_val:
                            slot.team_dd.selected_index = i
                            break
                if pt_key in player_colors:
                    slot.color_idx = int(player_colors[pt_key])
                if pt_key in player_handicaps:
                    slot.handicap = int(player_handicaps[pt_key])
                    slot.handicap_btn.label = self._handicap_label(slot.handicap)

        # Spectators sync — rebuild list from host-authoritative config.
        raw_spectators = config.get("spectators")
        if raw_spectators is not None:
            self._spectators = [
                _Spectator(
                    name=entry.get("name", ""),
                    online_pid=int(entry.get("online_pid", 0)),
                    color_idx=int(entry.get("color_idx", 0)),
                    original_team=int(entry.get("original_team", 1)),
                )
                for entry in raw_spectators
            ]
            # Remove any slot whose online_pid is now a spectator.
            spec_pids = {sp.online_pid for sp in self._spectators
                         if sp.online_pid}
            self._slots = [s for s in self._slots
                           if not s.online_pid or s.online_pid not in spec_pids]
            for i, s in enumerate(self._slots):
                s.pid = i + 1
            self._rebuild_slot_positions()

    def _maybe_broadcast_config(self) -> None:
        """If online and config changed since last broadcast, send to server."""
        if not self._online_client or not self._online_client.connected:
            return
        # If other players are already in the lobby and we haven't received
        # their settings yet, hold off. Broadcasting our default state would
        # overwrite the AI slots / handicaps / map options they configured.
        if self._last_received_config is None:
            lobby = self._online_client.lobby_status
            if lobby:
                local_pid = self._online_client.player_id
                others = [
                    pid_str for pid_str in lobby.get("players", {})
                    if int(pid_str) != local_pid
                ]
                if others:
                    return
        config = self._gather_lobby_config()
        if config != self._last_lobby_config:
            self._last_lobby_config = config
            self._online_client.send_lobby_settings(config)

    def _maybe_apply_received_config(self) -> None:
        """If new lobby settings received from server, apply to UI."""
        if not self._online_client:
            return
        settings = self._online_client.lobby_settings
        if settings is None or settings == self._last_received_config:
            return
        self._last_received_config = settings
        self._apply_lobby_config(settings)
        # Update our local tracking so we don't re-broadcast what we just received
        self._last_lobby_config = self._gather_lobby_config()

    # ── persistence ───────────────────────────────────────────────────────────

    def _persist_settings(self):
        slots_data = [
            {
                "ai_id": s.ai_dd.value,
                "team": int(s.team_dd.value),
                "color": s.color_idx,
                "name": s.name_input.text.strip() if s.name_input else "",
                "handicap": int(s.handicap),
            }
            for s in self._slots
        ]
        # Extract first human name for backward compat (multiplayer lobby reads it)
        first_human_name = ""
        for s in self._slots:
            if s.ai_dd.value == "human" and s.name_input:
                n = s.name_input.text.strip()
                if n:
                    first_human_name = n
                    break
        _save_settings({
            "slots": slots_data,
            "player_name": first_human_name,
            "map_size": self._map_size.value,
            "obstacles": self._sl_obstacles.value,
            "metal_spots": self._sl_metal_spots.value,
            "time_limit": self._sl_time_limit.value,
            "save_debug_summary": self._debug_summary_cb.checked,
            "headless": self._headless_cb.checked,
            "enable_t2": self._t2_cb.checked,
            "fog_of_war": self._fog_of_war_cb.checked,
            "show_outdated_ais": self._show_outdated_cb.checked,
        })

    # ── result builder ────────────────────────────────────────────────────────

    def _build_result(self) -> ScreenResult:
        player_ai_ids: dict[int, str] = {}
        player_team:   dict[int, int] = {}
        player_handicaps: dict[int, int] = {}
        for i, slot in enumerate(self._slots):
            pid = i + 1
            player_team[pid] = int(slot.team_dd.value)
            player_handicaps[pid] = int(slot.handicap)
            if slot.ai_dd.value != "human":
                player_ai_ids[pid] = slot.ai_dd.value

        # Spectators get player_ids after the last playing slot so they are
        # unique across the lobby. Offline lobbies don't route through a
        # server so any unique id is fine.
        spectators: list[int] = []
        spectator_names: dict[int, str] = {}
        next_pid = len(self._slots) + 1
        for sp in self._spectators:
            sp_pid = sp.online_pid or next_pid
            if not sp.online_pid:
                next_pid += 1
            spectators.append(sp_pid)
            if sp.name:
                spectator_names[sp_pid] = sp.name

        # Use first human slot's name, or first spectator's name, or fallback.
        player_name = "Unnamed Player"
        for slot in self._slots:
            if slot.ai_dd.value == "human" and slot.name_input:
                n = slot.name_input.text.strip()
                if n:
                    player_name = n
                    break
        else:
            for sp in self._spectators:
                if sp.name:
                    player_name = sp.name
                    break

        map_w, map_h = _MAP_SIZES[self._map_size.value]
        obs_val = self._sl_obstacles.value

        player_colors: dict[int, int] = {}
        for i, slot in enumerate(self._slots):
            pid = i + 1
            player_colors[pid] = slot.color_idx

        return ScreenResult("game", data={
            "player_ai_ids": player_ai_ids,
            "player_team":   player_team,
            "player_colors": player_colors,
            "player_handicaps": player_handicaps,
            "player_name":   player_name,
            "spectators":    spectators,
            "spectator_names": spectator_names,
            "width":         map_w,
            "height":        map_h,
            "obstacle_count": (obs_val, obs_val),
            "metal_spots":   self._sl_metal_spots.value,
            "time_limit":    self._sl_time_limit.value,
            "save_debug_summary": self._debug_summary_cb.checked,
            "headless":      self._headless_cb.checked,
            "enable_t2":     self._t2_cb.checked,
            "fog_of_war":    self._fog_of_war_cb.checked,
            "server":        self._server,
        })

    def _send_online_start(self) -> None:
        """Send game config to the remote server. The run() loop will detect
        game_started and transition to mp_client_game."""
        player_ai_ids: dict[int, str] = {}
        player_team:   dict[int, int] = {}

        client = self._online_client

        # Collect spectator online_pids so we can exclude them from player_team.
        spectator_pids: set[int] = {
            sp.online_pid for sp in self._spectators if sp.online_pid
        }

        # Step 1: Add all connected players (from online slots) as humans
        # Each online slot has the real server-assigned player_id.
        player_handicaps: dict[int, int] = {}
        for slot in self._slots:
            if slot.online_pid:
                player_team[slot.online_pid] = int(slot.team_dd.value)
                player_handicaps[slot.online_pid] = int(slot.handicap)

        # Ensure local player is included if not a spectator.
        if (client and client.player_id not in player_team
                and client.player_id not in spectator_pids):
            first_team = int(self._slots[0].team_dd.value) if self._slots else 1
            player_team[client.player_id] = first_team

        # Step 2: Add AI slots with non-conflicting IDs
        used_pids = set(player_team.keys())
        next_pid = max(used_pids | {0}) + 1
        for slot in self._slots:
            if slot.online_pid:
                continue  # already handled above
            if slot.ai_dd.value == "human":
                continue  # extra human slots with no connected player — skip
            while next_pid in used_pids:
                next_pid += 1
            player_team[next_pid] = int(slot.team_dd.value)
            player_ai_ids[next_pid] = slot.ai_dd.value
            player_handicaps[next_pid] = int(slot.handicap)
            used_pids.add(next_pid)
            next_pid += 1

        # Build player_colors: map each player_id to their selected color index
        player_colors: dict[int, int] = {}
        for slot in self._slots:
            if slot.online_pid:
                player_colors[slot.online_pid] = slot.color_idx
        # AI slots — match the pid assignment above
        used_pids2 = {s.online_pid for s in self._slots if s.online_pid}
        if client and client.player_id not in used_pids2:
            used_pids2.add(client.player_id)
        next_pid2 = max(used_pids2 | {0}) + 1
        for slot in self._slots:
            if slot.online_pid:
                continue
            if slot.ai_dd.value == "human":
                continue
            while next_pid2 in used_pids2:
                next_pid2 += 1
            player_colors[next_pid2] = slot.color_idx
            used_pids2.add(next_pid2)
            next_pid2 += 1

        map_w, map_h = _MAP_SIZES[self._map_size.value]

        config = {
            "player_ai_ids": {str(k): v for k, v in player_ai_ids.items()},
            "player_team":   {str(k): v for k, v in player_team.items()},
            "player_colors": {str(k): v for k, v in player_colors.items()},
            "player_handicaps": {str(k): v for k, v in player_handicaps.items()},
            "spectators":    sorted(spectator_pids),
            "width":         map_w,
            "height":        map_h,
            "obstacle_count": self._sl_obstacles.value,
            "metal_spots":   self._sl_metal_spots.value,
            "time_limit":    self._sl_time_limit.value,
            "enable_t2":     self._t2_cb.checked,
            "fog_of_war":    self._fog_of_war_cb.checked,
        }

        client.send_start_game(config)

    # ── rendering ─────────────────────────────────────────────────────────────

    def _draw_spectators_panel(self, font_small, font_tiny, mx: int, my: int):
        """Draw the Spectators sub-panel below the player slot list."""
        rect = getattr(self, "_spec_panel_rect", None)
        if rect is None:
            return
        pygame.draw.rect(self.screen, _PANEL_BG, rect, border_radius=6)
        pygame.draw.rect(self.screen, _PANEL_BORDER, rect, 1, border_radius=6)

        # Header
        hdr = font_tiny.render(
            f"Spectators ({len(self._spectators)})", True, _HDR_COLOR,
        )
        self.screen.blit(hdr, (rect.x + _SPEC_PANEL_PAD,
                               rect.y + _SPEC_PANEL_PAD))

        # List
        list_y = rect.y + _SPEC_PANEL_PAD + _SPEC_HDR_H
        for i, sp in enumerate(self._spectators):
            row_y = list_y + i * _SPEC_ROW_H
            dot_cx = rect.x + _SPEC_PANEL_PAD + 6
            dot_cy = row_y + _SPEC_ROW_H // 2
            pygame.draw.circle(self.screen, _SPEC_NEUTRAL_DOT,
                               (dot_cx, dot_cy), 5)
            label = sp.name or "Spectator"
            label_surf = font_small.render(label, True, CONTENT_TEXT)
            self.screen.blit(label_surf,
                             (dot_cx + 12,
                              row_y + (_SPEC_ROW_H - label_surf.get_height()) // 2))

        # Button (if viewer is not already a spectator)
        if not self._is_local_spectator():
            self._spec_btn.draw(self.screen)

    def _draw(self):
        self.screen.fill(MENU_BG)
        self._back.draw(self.screen)

        font_h = pygame.font.SysFont(None, HEADING_FONT_SIZE)
        font   = _get_font(CONTENT_FONT_SIZE + 2)
        small  = _get_font(DD_FONT_SIZE)
        tiny   = _get_font(13)
        mx, my = pygame.mouse.get_pos()

        # ── title ────────────────────────────────────────────────────────────
        title_text = "Online Lobby" if self._online_client else "Create Lobby"
        title_surf = font_h.render(title_text, True, CONTENT_TEXT)
        self.screen.blit(title_surf,
                         (self.width // 2 - title_surf.get_width() // 2, _TITLE_Y))

        # ── panel backgrounds ─────────────────────────────────────────────────
        panel_h = self.height - _PANEL_TOP_Y - 68  # leave room for Start button
        lp_rect = pygame.Rect(self._lp_x, _PANEL_TOP_Y, self._lp_w, panel_h)
        rp_rect = pygame.Rect(self._rp_x, _PANEL_TOP_Y, self._rp_w, panel_h)
        for r in (lp_rect, rp_rect):
            pygame.draw.rect(self.screen, _PANEL_BG,     r, border_radius=8)
            pygame.draw.rect(self.screen, _PANEL_BORDER, r, 1, border_radius=8)

        # ── left panel: Players ───────────────────────────────────────────────
        players_hdr = font.render("Players", True, CONTENT_TEXT)
        self.screen.blit(players_hdr, (self._lp_x + 14, _PANEL_HDR_Y))

        # Connected player count (online mode)
        if self._online_client:
            n_online = sum(1 for s in self._slots if s.online_pid)
            count_surf = tiny.render(f"{n_online} connected", True, _ONLINE_COLOR)
            self.screen.blit(count_surf,
                             (self._lp_x + 14 + players_hdr.get_width() + 10,
                              _PANEL_HDR_Y + 4))

        # Column headers
        team_hdr = tiny.render("Team", True, _HDR_COLOR)
        self.screen.blit(team_hdr, (self._team_dd_x + 14, _COL_HDR_Y))

        # Slot rows
        for slot in self._slots:
            idx = slot.pid - 1
            y = _SLOT_Y_START + idx * _SLOT_ROW_H
            dot_color = _PLAYER_COLORS[slot.color_idx % len(_PLAYER_COLORS)]

            # Color dot (clickable)
            dot_cx = self._label_x + 6
            dot_cy = y + DD_HEIGHT // 2
            pygame.draw.circle(self.screen, dot_color, (dot_cx, dot_cy), 5)
            # Hover ring
            if (mx - dot_cx) ** 2 + (my - dot_cy) ** 2 <= 64:
                pygame.draw.circle(self.screen, (255, 255, 255), (dot_cx, dot_cy), 7, 1)

            # P# label
            lbl = small.render(f"P{slot.pid}", True, CONTENT_TEXT)
            self.screen.blit(lbl, (self._label_x + 16,
                                   y + (DD_HEIGHT - lbl.get_height()) // 2))

            if slot.online_pid:
                # Online player: show name label instead of AI dropdown
                name = slot.name_input.text if slot.name_input else "Player"
                name_surf = small.render(name, True, _ONLINE_COLOR)
                self.screen.blit(name_surf,
                                 (self._ai_dd_x + 4,
                                  y + (DD_HEIGHT - name_surf.get_height()) // 2))
                # Latency indicator (right-aligned next to the name).
                ping_ms = self._ping_for(slot.online_pid)
                if ping_ms is not None:
                    ping_text, ping_color = self._format_ping(ping_ms)
                    ping_surf = tiny.render(ping_text, True, ping_color)
                    self.screen.blit(
                        ping_surf,
                        (self._ai_dd_x + 4 + name_surf.get_width() + 8,
                         y + (DD_HEIGHT - ping_surf.get_height()) // 2),
                    )
            else:
                # Regular slot: show remove button and name input
                if len(self._slots) > _MIN_SLOTS:
                    slot.remove_btn.draw(self.screen)
                # Per-human name input (inline, same row after handicap button)
                if slot.ai_dd.value == "human" and slot.name_input:
                    slot.name_input.draw(self.screen)

            # Handicap button (shown for every slot, online or AI)
            slot.handicap_btn.draw(self.screen)


        # Add player / Join Game button (inline after last slot)
        if self._is_local_spectator() or len(self._slots) < _MAX_SLOTS:
            self._add_btn.draw(self.screen)

        # ── spectators sub-panel ─────────────────────────────────────────────
        self._draw_spectators_panel(small, tiny, mx, my)

        # ── right panel: Settings ─────────────────────────────────────────────
        settings_hdr = font.render("Settings", True, CONTENT_TEXT)
        self.screen.blit(settings_hdr, (self._rp_x + 14, _PANEL_HDR_Y))

        # Map size label
        ry = _SLOT_Y_START
        map_lbl = small.render("Map Size", True, _HDR_COLOR)
        self.screen.blit(map_lbl, (self._rx, ry + 4))

        self._map_size.draw(self.screen)
        self._sl_obstacles.draw(self.screen)
        self._sl_metal_spots.draw(self.screen)
        self._sl_time_limit.draw(self.screen)
        self._debug_summary_cb.draw(self.screen)
        self._headless_cb.draw(self.screen)
        self._t2_cb.draw(self.screen)
        self._fog_of_war_cb.draw(self.screen)
        self._show_outdated_cb.draw(self.screen)

        # ── Start button ──────────────────────────────────────────────────────
        self._back_btn.draw(self.screen)
        self._start_btn.draw(self.screen)

        # ── overlays (drawn last for z-order) ─────────────────────────────────
        all_dds = []
        for s in self._slots:
            if not s.online_pid:
                all_dds.append(s.ai_dd)  # skip AI dropdown for online slots
            all_dds.append(s.team_dd)
        for dd in sorted(all_dds, key=lambda d: d.open):
            dd.draw(self.screen)

        pygame.display.flip()
