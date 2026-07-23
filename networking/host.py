"""Host-side networking for authoritative multiplayer.

The host runs the full Game instance in the main thread (with pygame).
Networking runs in a daemon thread via asyncio. Two thread-safe queues
bridge the gap:
  - _inbound_commands: remote player commands → game step
  - _outbound per client: game state frames → remote player

Supports up to *max_players* remote clients (default 2 for dedicated server,
1 for LAN host mode where the host itself is player 1).
"""
from __future__ import annotations

import asyncio
import dataclasses
import queue
import secrets
import socket
import threading
import time
import json
from typing import Any, Awaitable, Callable

# How long a mid-game WS client's slot survives a dropped connection before
# it is released for reuse (browser reconnect grace period).
RECONNECT_GRACE_SECONDS = 60.0

from networking.protocol import send_message, recv_message, DEFAULT_PORT, DEFAULT_WS_PORT
from systems.commands import GameCommand, CommandQueue
from systems.replay import (
    _entity_visual, _laser_visual, _obstacle_visual, _splash_visual,
    _ghost_visual, _metal_spot_visual_filtered,
    RECORD_INTERVAL,
)


@dataclasses.dataclass
class ClientConnection:
    """State for a single connected client.

    Transport-agnostic: ``send`` serializes+writes one message dict for this
    connection (TCP uses the length-prefixed protocol, WS uses a JSON text
    frame), and ``close`` tears the underlying transport down. The
    frame-building code only ever touches ``outbound`` / ``send``, so it does
    not care which transport backs a given client.
    """
    player_id: int
    name: str = ""
    transport: str = "tcp"  # "tcp" | "ws"
    send: Callable[[dict], Awaitable[None]] | None = None
    close: Callable[[], Awaitable[None]] | None = None
    outbound: queue.Queue = dataclasses.field(default_factory=queue.Queue)
    connected: threading.Event = dataclasses.field(default_factory=threading.Event)
    ready: threading.Event = dataclasses.field(default_factory=threading.Event)
    # Latency tracking — server pings clients and measures RTT.
    last_ping_id: int = 0
    last_ping_sent: float = 0.0
    ping_ms: int = 0
    # Browser reconnect: a secret issued on join; a new WS connection that
    # presents it mid-game is rebound to this slot instead of a fresh one.
    token: str = ""


class GameHost:
    """Server that accepts remote clients and bridges commands/state over TCP.

    *max_players* controls how many remote connections are accepted.
    For LAN host mode (host plays locally), set max_players=1.
    For dedicated server (both players remote), set max_players=2.
    """

    def __init__(
        self,
        command_queue: CommandQueue,
        port: int = DEFAULT_PORT,
        host_name: str = "Host",
        max_players: int = 1,
        broadcast_interval: int = RECORD_INTERVAL,
        first_player_id: int | None = None,
        ws_port: int | None = None,
        ai_choices: dict | None = None,
        static_config: dict | None = None,
    ):
        self._command_queue = command_queue
        self._port = port
        self._host_name = host_name
        self._max_players = max_players
        self._broadcast_interval = broadcast_interval
        # WebSocket listener (browser clients). None/0 disables it.
        self._ws_port = ws_port
        # Browser-only handshake extras (desktop TCP clients ignore them):
        #   ai_choices  -> lobby AI dropdowns (registry can't be enumerated in JS)
        #   static_config -> display constants (UNIT_TYPES, colors, timings, ...)
        self._ai_choices = ai_choices
        self._static_config = static_config
        self._pending_sounds: list[str] = []
        self._pending_deaths: list[dict] = []
        self._pending_chats: list[dict] = []

        # Cross-thread queues
        self._inbound_commands: queue.Queue[GameCommand] = queue.Queue()
        self._start_game_queue: queue.Queue[dict] = queue.Queue()  # start_game requests from clients

        # Multi-client tracking: player_id → ClientConnection
        self._clients: dict[int, ClientConnection] = {}
        self._clients_lock = threading.Lock()
        if first_player_id is not None:
            self._next_player_id = first_player_id
        else:
            self._next_player_id = 2 if max_players == 1 else 1  # LAN: client=2; dedicated: start at 1
        self._first_player_id = self._next_player_id
        self._freed_player_ids: list[int] = []  # reusable IDs from disconnected clients

        self._running = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        # True between game_start and game_over/return_to_lobby — gates the
        # WS reconnect grace period (a lobby disconnect frees the slot as
        # before; a mid-game disconnect holds it for RECONNECT_GRACE_SECONDS).
        self._game_in_progress = False

        # Lobby settings (broadcast to clients when changed)
        self._lobby_settings: dict | None = None

        # Ephemeral port support: when port=0, OS assigns a free port
        self._bound_port: int = 0
        self._bound_event = threading.Event()

        # Determine local IP for display
        self.local_ip = self._get_local_ip()

    # -- backward-compat properties (for LAN host, first/only client) -------

    @property
    def client_name(self) -> str:
        with self._clients_lock:
            for c in self._clients.values():
                return c.name
        return ""

    @property
    def client_connected(self) -> bool:
        with self._clients_lock:
            for c in self._clients.values():
                if c.connected.is_set():
                    return True
        return False

    @property
    def client_ready(self) -> bool:
        with self._clients_lock:
            for c in self._clients.values():
                if c.ready.is_set():
                    return True
        return False

    @property
    def port(self) -> int:
        return self._port

    @property
    def bound_port(self) -> int:
        """Actual port after bind (waits for server to start if using port 0)."""
        self._bound_event.wait(timeout=10.0)
        return self._bound_port if self._bound_port else self._port

    # -- multi-client properties -------------------------------------------

    @property
    def all_clients_connected(self) -> bool:
        with self._clients_lock:
            if len(self._clients) < self._max_players:
                return False
            return all(c.connected.is_set() for c in self._clients.values())

    @property
    def all_clients_ready(self) -> bool:
        with self._clients_lock:
            if len(self._clients) < self._max_players:
                return False
            return all(c.ready.is_set() for c in self._clients.values())

    @property
    def client_names(self) -> dict[int, str]:
        with self._clients_lock:
            return {pid: c.name for pid, c in self._clients.items()}

    @property
    def connected_count(self) -> int:
        with self._clients_lock:
            return sum(1 for c in self._clients.values() if c.connected.is_set())

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the networking thread and TCP server."""
        self._thread = threading.Thread(target=self._run_network, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shut down the server and networking thread."""
        self._running = False
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass  # event loop already closed
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def poll_start_game(self) -> dict | None:
        """Non-blocking poll for a start_game config from a client."""
        try:
            return self._start_game_queue.get_nowait()
        except queue.Empty:
            return None

    # -- lobby settings API ---------------------------------------------------

    def set_lobby_settings(self, settings: dict) -> None:
        """Store lobby settings and broadcast to all connected clients."""
        self._lobby_settings = settings
        self.broadcast_lobby_settings()

    def broadcast_lobby_settings(self) -> None:
        """Send current lobby settings to all connected clients."""
        if self._lobby_settings is None:
            return
        msg = {"msg": "lobby_settings", **self._lobby_settings}
        with self._clients_lock:
            for c in self._clients.values():
                if c.connected.is_set():
                    c.outbound.put(msg)

    # -- game-thread API (called from the main/pygame thread) ---------------

    def inject_remote_commands(self) -> None:
        """Drain inbound commands and enqueue them into the game's CommandQueue."""
        while True:
            try:
                cmd = self._inbound_commands.get_nowait()
                self._command_queue.enqueue(cmd)
            except queue.Empty:
                break

    def broadcast_state(
        self,
        tick: int,
        entities: list,
        laser_flashes: list,
        winner: int,
        splash_effects: list | None = None,
        sound_events: list[str] | None = None,
        death_events: list[dict] | None = None,
        chat_events: list[dict] | None = None,
        team_visibility: dict | None = None,
        player_team: dict[int, int] | None = None,
        metal_spots: list | None = None,
        server_tick_ms: float = 0.0,
        server_tick_cpu_ms: float = 0.0,
        server_tps: float = 0.0,
    ) -> None:
        """Build a visual state frame and queue it for sending (every broadcast_interval).

        When *team_visibility* is provided (fog of war enabled), each client
        receives only the entities visible to their team, plus ghost buildings
        and server-computed LOS circles for the fog overlay.
        """
        if sound_events:
            self._pending_sounds.extend(sound_events)
        if death_events:
            self._pending_deaths.extend(death_events)
        if chat_events:
            self._pending_chats.extend(chat_events)
        if tick % self._broadcast_interval != 0:
            return

        # Common data shared across all frames
        lf_list = [_laser_visual(lf) for lf in laser_flashes]
        splash_list = [_splash_visual(s) for s in splash_effects] if splash_effects else None
        sounds = self._pending_sounds if self._pending_sounds else None
        if sounds:
            self._pending_sounds = []
        deaths = self._pending_deaths if self._pending_deaths else None
        if deaths:
            self._pending_deaths = []
        chats = self._pending_chats if self._pending_chats else None
        if chats:
            self._pending_chats = []

        if team_visibility and player_team:
            # -- Per-team filtered frames (fog of war) --
            from entities.metal_spot import MetalSpot
            team_frames: dict[int, dict] = {}

            for team_id, vis in team_visibility.items():
                # Build filtered entity visuals for this team
                ent_visuals = []
                seen_ms_ids: set[int] = set()

                for e in entities:
                    vd = _entity_visual(e)
                    if vd is None:
                        continue
                    if e.entity_id in vis.visible_entity_ids:
                        ent_visuals.append(vd)
                        if isinstance(e, MetalSpot):
                            seen_ms_ids.add(e.entity_id)

                # Add MetalSpots not in LOS with stripped capture info
                if metal_spots:
                    for ms in metal_spots:
                        if ms.entity_id not in seen_ms_ids:
                            last_owner = vis.metal_spot_memory.get(ms.entity_id)
                            ent_visuals.append(
                                _metal_spot_visual_filtered(ms, last_owner)
                            )

                # Append ghost buildings (not currently visible)
                for gid, ghost in vis.building_ghosts.items():
                    if gid not in vis.visible_entity_ids:
                        ent_visuals.append(_ghost_visual(ghost))

                # Build the frame
                frame: dict[str, Any] = {
                    "msg": "state",
                    "tick": tick,
                    "entities": ent_visuals,
                    "lasers": lf_list,
                    "winner": winner,
                    "srv_ms": round(server_tick_ms, 2),
                    "srv_cpu_ms": round(server_tick_cpu_ms, 2),
                    "srv_tps": round(server_tps, 1),
                }
                if splash_list:
                    frame["splashes"] = splash_list
                if sounds:
                    frame["sounds"] = sounds
                if deaths:
                    frame["deaths"] = deaths
                # Filter chat events: "all" for everyone, "team" only for this team
                if chats:
                    team_chats = [ce for ce in chats
                                  if ce["mode"] == "all" or ce["tid"] == team_id]
                    if team_chats:
                        frame["chats"] = team_chats
                team_frames[team_id] = frame

            # Queue per-client based on their team
            with self._clients_lock:
                for c in self._clients.values():
                    if not c.connected.is_set():
                        continue
                    c_team = player_team.get(c.player_id)
                    frame = team_frames.get(c_team)
                    if frame is None:
                        continue
                    self._queue_frame(c, frame)
        else:
            # -- Unfiltered broadcast (fog disabled) --
            ent_visuals = []
            for e in entities:
                vd = _entity_visual(e)
                if vd is not None:
                    ent_visuals.append(vd)
            frame = {
                "msg": "state",
                "tick": tick,
                "entities": ent_visuals,
                "lasers": lf_list,
                "winner": winner,
                "srv_ms": round(server_tick_ms, 2),
                "srv_cpu_ms": round(server_tick_cpu_ms, 2),
                "srv_tps": round(server_tps, 1),
            }
            if splash_list:
                frame["splashes"] = splash_list
            if sounds:
                frame["sounds"] = sounds
            if deaths:
                frame["deaths"] = deaths

            # Chat: if any team-only messages, must filter per-client
            has_team_chat = chats and any(ce["mode"] == "team" for ce in chats)
            if has_team_chat and player_team:
                with self._clients_lock:
                    for c in self._clients.values():
                        if not c.connected.is_set():
                            continue
                        c_team = player_team.get(c.player_id, c.player_id)
                        client_chats = [ce for ce in chats
                                        if ce["mode"] == "all" or ce["tid"] == c_team]
                        client_frame = dict(frame)
                        if client_chats:
                            client_frame["chats"] = client_chats
                        self._queue_frame(c, client_frame)
            else:
                if chats:
                    frame["chats"] = chats
                with self._clients_lock:
                    for c in self._clients.values():
                        if c.connected.is_set():
                            self._queue_frame(c, frame)

    @staticmethod
    def _queue_frame(client: ClientConnection, frame: dict) -> None:
        """Queue a state frame to a client, dropping stale STATE frames."""
        preserved = []
        try:
            while True:
                old = client.outbound.get_nowait()
                if old.get("msg") != "state":
                    preserved.append(old)
        except queue.Empty:
            pass
        for item in preserved:
            client.outbound.put(item)
        client.outbound.put(frame)

    def send_game_start(
        self,
        entities: list,
        map_width: int,
        map_height: int,
        *,
        enable_t2: bool = False,
        fog_of_war: bool = False,
        player_team: dict[int, int] | None = None,
        player_names: dict[int, str] | None = None,
        team_colors: dict[int, list[int]] | None = None,
        spectators: "set[int] | list[int] | None" = None,
    ) -> None:
        """Send the initial game_start message with obstacle data."""
        obstacles = []
        for e in entities:
            od = _obstacle_visual(e)
            if od is not None:
                obstacles.append(od)
        msg: dict[str, Any] = {
            "msg": "game_start",
            "obstacles": obstacles,
            "map_width": map_width,
            "map_height": map_height,
            "enable_t2": enable_t2,
            "fog_of_war": fog_of_war,
        }
        if player_team is not None:
            msg["player_team"] = {str(k): v for k, v in player_team.items()}
        if player_names is not None:
            msg["player_names"] = {str(k): v for k, v in player_names.items()}
        if team_colors is not None:
            msg["team_colors"] = {str(k): v for k, v in team_colors.items()}
        if spectators:
            msg["spectators"] = sorted(int(p) for p in spectators)
        self._game_in_progress = True
        with self._clients_lock:
            for c in self._clients.values():
                c.outbound.put(msg)

    def send_game_over(self, winner: int, stats: dict | None = None) -> None:
        """Send game_over notification with optional stats."""
        self._game_in_progress = False
        msg: dict[str, Any] = {"msg": "game_over", "winner": winner}
        if stats is not None:
            msg["stats"] = stats
        with self._clients_lock:
            for c in self._clients.values():
                c.outbound.put(msg)

    def send_return_to_lobby(self) -> None:
        """Notify clients that the server is returning to the lobby."""
        self._game_in_progress = False
        msg = {"msg": "return_to_lobby"}
        with self._clients_lock:
            for c in self._clients.values():
                c.outbound.put(msg)

    def reset(self, clear_clients: bool = False) -> None:
        """Reset to lobby state. Keeps TCP server and connections alive.

        *clear_clients* should be True for local/internal-server games where
        the client disconnects between games (player-ID counter is reset and
        stale entries are removed).  For dedicated-server / online games the
        clients stay connected, so we only drain queues.
        """
        self._game_in_progress = False
        if clear_clients:
            self._next_player_id = self._first_player_id
            self._freed_player_ids.clear()
            with self._clients_lock:
                self._clients.clear()
        else:
            with self._clients_lock:
                for c in self._clients.values():
                    while not c.outbound.empty():
                        try:
                            c.outbound.get_nowait()
                        except queue.Empty:
                            break
        # Drain stale inbound commands
        while True:
            try:
                self._inbound_commands.get_nowait()
            except queue.Empty:
                break
        # Drain stale start_game requests
        while True:
            try:
                self._start_game_queue.get_nowait()
            except queue.Empty:
                break

    # -- networking thread --------------------------------------------------

    def _run_network(self) -> None:
        """Entry point for the daemon thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            pass
        finally:
            # Suppress Windows proactor cleanup warnings
            try:
                self._loop.close()
            except Exception:
                pass

    async def _serve(self) -> None:
        server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self._port,
        )
        # Capture actual bound port (important for port=0 / ephemeral)
        sock = server.sockets[0] if server.sockets else None
        if sock is not None:
            self._bound_port = sock.getsockname()[1]
        else:
            self._bound_port = self._port
        self._bound_event.set()

        # Optional WebSocket listener for browser clients, on a separate port.
        # Shares this event loop, _clients dict, and command/outbound queues
        # with the TCP server above. Disabled when ws_port is None/0.
        ws_server = None
        if self._ws_port:
            try:
                import websockets
                ws_server = await websockets.serve(
                    self._handle_ws, "0.0.0.0", self._ws_port,
                    max_size=10_000_000,        # mirror the TCP 10MB cap
                    compression="deflate",       # permessage-deflate
                    ping_interval=20, ping_timeout=20,
                )
                print(f"[Server] WebSocket listening on port {self._ws_port}")
            except ImportError:
                print("[Server] 'websockets' not installed — browser clients "
                      "disabled. Run: pip install websockets")
            except Exception as exc:  # noqa: BLE001 — listener is best-effort
                print(f"[Server] Failed to start WebSocket listener: {exc}")

        ping_task = asyncio.ensure_future(self._ping_loop())

        async with server:
            # Keep running until stopped
            while self._running:
                await asyncio.sleep(0.05)

        ping_task.cancel()
        try:
            await ping_task
        except (asyncio.CancelledError, Exception):
            pass

        if ws_server is not None:
            ws_server.close()
            try:
                await ws_server.wait_closed()
            except Exception:
                pass

    async def _ping_loop(self) -> None:
        """Periodically ping each client to measure RTT and broadcast a
        ping table so every client can see everyone's latency."""
        while self._running:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return
            now = time.monotonic()
            # Send a ping to every connected client.
            with self._clients_lock:
                clients = list(self._clients.values())
            for c in clients:
                if not c.connected.is_set():
                    continue
                # If the previous ping is still outstanding (no pong arrived
                # before we send the next one), surface the elapsed time as a
                # lower bound on latency. A pong clears last_ping_sent to 0,
                # so a healthy roundtrip skips this branch.
                if c.last_ping_sent > 0:
                    elapsed_ms = int((now - c.last_ping_sent) * 1000)
                    if elapsed_ms > c.ping_ms:
                        c.ping_ms = elapsed_ms
                c.last_ping_id += 1
                c.last_ping_sent = now
                c.outbound.put({"msg": "ping", "id": c.last_ping_id})
            # Broadcast the current ping table to everyone.
            with self._clients_lock:
                pings = {
                    str(pid): c.ping_ms
                    for pid, c in self._clients.items()
                    if c.connected.is_set()
                }
                msg = {"msg": "pings", "pings": pings}
                for c in self._clients.values():
                    if c.connected.is_set():
                        c.outbound.put(msg)

    # -- shared connection helpers (transport-agnostic) --------------------

    def _alloc_connection(self, transport: str) -> ClientConnection | None:
        """Atomically assign a player_id and register a connection slot.

        Reuses freed IDs first. Returns None if the server is already full.
        The caller fills in ``send``/``close`` and sets ``connected`` after.
        """
        with self._clients_lock:
            if len(self._clients) >= self._max_players:
                return None
            if self._freed_player_ids:
                player_id = self._freed_player_ids.pop(0)
            else:
                player_id = self._next_player_id
                self._next_player_id += 1
            conn = ClientConnection(player_id=player_id, transport=transport)
            self._clients[player_id] = conn
            return conn

    def _release_player_id(self, player_id: int) -> None:
        """Remove a client and free its id for reuse by a future connection.

        Only frees the id if the slot was actually registered — callers can
        race (grace-timer release vs. handler cleanup) and a double-append
        would hand the same id to two future clients.
        """
        with self._clients_lock:
            if self._clients.pop(player_id, None) is not None:
                self._freed_player_ids.append(player_id)

    def _lobby_info_msg(self, player_id: int) -> dict:
        """First message sent to a new client. Carries ai_choices for the
        browser lobby (desktop clients ignore the extra key)."""
        msg = {
            "msg": "lobby_info",
            "client_player_id": player_id,
            "host_name": self._host_name,
        }
        if self._ai_choices is not None:
            msg["ai_choices"] = self._ai_choices
        return msg

    def _dispatch_inbound(self, msg: dict, player_id: int) -> None:
        """Handle one decoded inbound message from a client. Shared by the TCP
        and WebSocket recv loops so both transports behave identically."""
        msg_type = msg.get("msg")
        if msg_type == "command":
            cmd_data = msg.get("command", "")
            try:
                cmd = GameCommand.deserialize(cmd_data)
                # Force player_id to this client's slot for security
                cmd.player_id = player_id
                self._inbound_commands.put(cmd)
            except Exception:
                pass
        elif msg_type == "start_game":
            self._start_game_queue.put(msg.get("config", {}))
        elif msg_type == "lobby_settings":
            # Relay lobby settings to all OTHER clients (not back to sender)
            settings = {k: v for k, v in msg.items() if k != "msg"}
            self._lobby_settings = settings
            relay_msg = {"msg": "lobby_settings", **settings}
            with self._clients_lock:
                for pid, c in self._clients.items():
                    if pid != player_id and c.connected.is_set():
                        c.outbound.put(relay_msg)
        elif msg_type == "pong":
            pong_id = msg.get("id", -1)
            with self._clients_lock:
                c = self._clients.get(player_id)
                if (c is not None
                        and c.last_ping_id == pong_id
                        and c.last_ping_sent > 0):
                    c.ping_ms = int(
                        (time.monotonic() - c.last_ping_sent) * 1000
                    )
                    # Mark "no outstanding ping" so the next loop tick
                    # doesn't mistake a healthy connection for a stall.
                    c.last_ping_sent = 0.0

    async def _post_join(self, conn: ClientConnection) -> None:
        """Common steps after a client's join is received: send static config
        (browser-only) then broadcast the updated roster + settings."""
        if self._static_config is not None and conn.send is not None:
            try:
                await conn.send({"msg": "server_config", "config": self._static_config})
            except Exception:
                pass
        await self._broadcast_lobby_status()
        self.broadcast_lobby_settings()

    async def _run_client_loops(
        self, conn: ClientConnection, recv_coro: Awaitable[None],
    ) -> None:
        """Run a client's recv loop and the shared send loop concurrently,
        cancelling the survivor when either exits."""
        recv_task = asyncio.ensure_future(recv_coro)
        send_task = asyncio.ensure_future(self._send_loop(conn))
        try:
            await asyncio.wait(
                [recv_task, send_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (recv_task, send_task):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    # -- TCP transport -----------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new TCP (desktop) client connection."""
        conn = self._alloc_connection("tcp")
        if conn is None:
            try:
                await send_message(writer, {"msg": "rejected", "reason": "Server full"})
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return

        player_id = conn.player_id

        async def _tcp_close() -> None:
            writer.close()

        conn.send = lambda d: send_message(writer, d)
        conn.close = _tcp_close
        conn.connected.set()

        try:
            await conn.send(self._lobby_info_msg(player_id))

            # Wait for join
            msg = await recv_message(reader)
            if msg and msg.get("msg") == "join":
                conn.name = msg.get("player_name", "Client")
                conn.ready.set()
                print(f"[Server] Player '{conn.name}' connected (id={player_id}, tcp)")

            await self._post_join(conn)
            await self._run_client_loops(conn, self._recv_loop(reader, player_id))

        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            if conn.name:
                print(f"[Server] Player '{conn.name}' disconnected (id={player_id})")
            conn.connected.clear()
            conn.ready.clear()
            self._release_player_id(player_id)
            writer.close()
            # Notify remaining clients about the disconnection
            try:
                await self._broadcast_lobby_status()
            except Exception:
                pass

    async def _recv_loop(self, reader: asyncio.StreamReader, player_id: int) -> None:
        """Receive and dispatch messages from a specific TCP client."""
        while self._running:
            try:
                msg = await asyncio.wait_for(recv_message(reader), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except (asyncio.IncompleteReadError, ConnectionError):
                break
            if msg is None:
                break
            self._dispatch_inbound(msg, player_id)

    # -- WebSocket transport (browser clients) -----------------------------

    async def _handle_ws(self, ws, *args) -> None:
        """Handle a new WebSocket (browser) client connection.

        Mirrors _handle_client but uses JSON text frames: the WebSocket layer
        frames messages (no 4-byte length prefix) and permessage-deflate
        handles compression (no manual zlib/"Z"). Feeds the same _clients dict
        and command/outbound queues as the TCP path. (``*args`` absorbs the
        legacy ``path`` argument removed from the handler signature in
        websockets v11.)
        """
        # Allocation may fail while the server is "full" only because a
        # disconnected player's slot is being held for reconnect — so even
        # then, give the socket a chance to present its reconnect token.
        conn = self._alloc_connection("ws")
        provisional_id = conn.player_id if conn is not None else 0

        async def _ws_close() -> None:
            await ws.close()

        def ws_send(d: dict) -> Awaitable[None]:
            return ws.send(json.dumps(d, separators=(",", ":")))

        try:
            await ws_send(self._lobby_info_msg(provisional_id))

            # Wait for join
            raw = await ws.recv()
            msg = json.loads(raw)
            if not (isinstance(msg, dict) and msg.get("msg") == "join"):
                return  # protocol violation — cleanup in finally

            # -- reconnect path: rebind this socket to the held slot --------
            token = msg.get("reconnect_token", "")
            old = self._find_reconnect_conn(token) if token else None
            if old is not None:
                if conn is not None:
                    self._release_player_id(conn.player_id)
                conn = old
                conn.send = ws_send
                conn.close = _ws_close
                conn.connected.set()
                conn.ready.set()
                print(f"[Server] Player '{conn.name}' reconnected "
                      f"(id={conn.player_id}, ws)")
                # Re-send identity + config; the next broadcast delivers a
                # full state frame, which is all the resync a client needs.
                await ws_send(self._lobby_info_msg(conn.player_id))
                await self._post_join(conn)
                await self._run_client_loops(
                    conn, self._recv_loop_ws(ws, conn.player_id))
                return

            # -- fresh join --------------------------------------------------
            if conn is None:
                await ws_send({"msg": "rejected", "reason": "Server full"})
                return

            conn.send = ws_send
            conn.close = _ws_close
            conn.connected.set()
            conn.name = msg.get("player_name", "Client")
            conn.ready.set()
            conn.token = secrets.token_hex(16)
            print(f"[Server] Player '{conn.name}' connected "
                  f"(id={conn.player_id}, ws)")
            # Browser-only: reconnect token (desktop TCP never gets one).
            await ws_send({"msg": "session", "token": conn.token})

            await self._post_join(conn)
            await self._run_client_loops(conn, self._recv_loop_ws(ws, conn.player_id))

        except Exception:
            # ConnectionClosed / malformed JSON / etc. — fall through to cleanup.
            pass
        finally:
            # Only clean up if this handler still owns the slot: after a
            # rebind, conn.send belongs to the newer socket's handler and the
            # old handler must not clear its state.
            if conn is not None and conn.send is ws_send:
                if conn.name:
                    print(f"[Server] Player '{conn.name}' disconnected "
                          f"(id={conn.player_id})")
                conn.connected.clear()
                conn.ready.clear()
                if self._game_in_progress and conn.token:
                    # Hold the slot so the browser can reconnect mid-game.
                    asyncio.ensure_future(self._grace_release(conn))
                else:
                    self._release_player_id(conn.player_id)
            try:
                await ws.close()
            except Exception:
                pass
            try:
                await self._broadcast_lobby_status()
            except Exception:
                pass

    def _find_reconnect_conn(self, token: str) -> ClientConnection | None:
        """Find the disconnected WS slot matching a client's reconnect token."""
        if not token or not isinstance(token, str):
            return None
        with self._clients_lock:
            for c in self._clients.values():
                if (c.transport == "ws" and c.token
                        and not c.connected.is_set()
                        and secrets.compare_digest(c.token, token)):
                    return c
        return None

    async def _grace_release(self, conn: ClientConnection) -> None:
        """Release a held slot if its player hasn't reconnected in time."""
        try:
            await asyncio.sleep(RECONNECT_GRACE_SECONDS)
        except asyncio.CancelledError:
            return
        if conn.connected.is_set():
            return  # player came back
        with self._clients_lock:
            if self._clients.get(conn.player_id) is not conn:
                return  # slot was already released / replaced
        print(f"[Server] Reconnect window expired for '{conn.name}' "
              f"(id={conn.player_id})")
        self._release_player_id(conn.player_id)
        try:
            await self._broadcast_lobby_status()
        except Exception:
            pass

    async def _recv_loop_ws(self, ws, player_id: int) -> None:
        """Receive and dispatch messages from a WebSocket client."""
        while self._running:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break  # ConnectionClosed and friends
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(msg, dict):
                self._dispatch_inbound(msg, player_id)

    # -- shared send loop --------------------------------------------------

    async def _send_loop(self, conn: ClientConnection) -> None:
        """Send queued state frames to a client over whichever transport backs
        it (``conn.send``). Used identically by TCP and WebSocket clients."""
        while self._running:
            try:
                frame = conn.outbound.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
            if conn.send is None:
                break
            try:
                await conn.send(frame)
            except Exception:
                # Any send failure means the connection is dead — exit so the
                # handler can clean up (covers ConnectionError/OSError and the
                # WebSocket ConnectionClosed family).
                break

    async def _broadcast_lobby_status(self) -> None:
        """Send lobby_status to all connected clients with current roster."""
        with self._clients_lock:
            roster = {
                pid: {"name": c.name, "ready": c.ready.is_set()}
                for pid, c in self._clients.items()
                if c.connected.is_set()
            }
            conns = [
                c for c in self._clients.values()
                if c.connected.is_set() and c.send is not None
            ]

        msg = {
            "msg": "lobby_status",
            "players": roster,
            "max_players": self._max_players,
            "host_name": self._host_name,
        }
        for c in conns:
            try:
                await c.send(msg)
            except Exception:
                pass

    @staticmethod
    def _get_local_ip() -> str:
        """Best-effort local IP detection."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
