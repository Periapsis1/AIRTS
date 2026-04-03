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
import socket
import threading
from typing import Any

from networking.protocol import send_message, recv_message, DEFAULT_PORT
from systems.commands import GameCommand, CommandQueue
from systems.replay import (
    _entity_visual, _laser_visual, _obstacle_visual, _splash_visual,
    _ghost_visual, _metal_spot_visual_filtered,
    RECORD_INTERVAL,
)


@dataclasses.dataclass
class ClientConnection:
    """State for a single connected client."""
    player_id: int
    name: str = ""
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    outbound: queue.Queue = dataclasses.field(default_factory=queue.Queue)
    connected: threading.Event = dataclasses.field(default_factory=threading.Event)
    ready: threading.Event = dataclasses.field(default_factory=threading.Event)


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
    ):
        self._command_queue = command_queue
        self._port = port
        self._host_name = host_name
        self._max_players = max_players
        self._broadcast_interval = broadcast_interval
        self._pending_sounds: list[str] = []

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
        team_visibility: dict | None = None,
        player_team: dict[int, int] | None = None,
        metal_spots: list | None = None,
    ) -> None:
        """Build a visual state frame and queue it for sending (every broadcast_interval).

        When *team_visibility* is provided (fog of war enabled), each client
        receives only the entities visible to their team, plus ghost buildings
        and server-computed LOS circles for the fog overlay.
        """
        if sound_events:
            self._pending_sounds.extend(sound_events)
        if tick % self._broadcast_interval != 0:
            return

        # Common data shared across all frames
        lf_list = [_laser_visual(lf) for lf in laser_flashes]
        splash_list = [_splash_visual(s) for s in splash_effects] if splash_effects else None
        sounds = self._pending_sounds if self._pending_sounds else None
        if sounds:
            self._pending_sounds = []

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
                }
                if splash_list:
                    frame["splashes"] = splash_list
                if sounds:
                    frame["sounds"] = sounds
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
            }
            if splash_list:
                frame["splashes"] = splash_list
            if sounds:
                frame["sounds"] = sounds
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
        with self._clients_lock:
            for c in self._clients.values():
                c.outbound.put(msg)

    def send_game_over(self, winner: int, stats: dict | None = None) -> None:
        """Send game_over notification with optional stats."""
        msg: dict[str, Any] = {"msg": "game_over", "winner": winner}
        if stats is not None:
            msg["stats"] = stats
        with self._clients_lock:
            for c in self._clients.values():
                c.outbound.put(msg)

    def send_return_to_lobby(self) -> None:
        """Notify clients that the server is returning to the lobby."""
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

        async with server:
            # Keep running until stopped
            while self._running:
                await asyncio.sleep(0.05)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new client connection."""
        # Determine player_id for this client (reuse freed IDs first)
        with self._clients_lock:
            if len(self._clients) >= self._max_players:
                # Full — reject
                try:
                    await send_message(writer, {"msg": "rejected", "reason": "Server full"})
                except Exception:
                    pass
                writer.close()
                await writer.wait_closed()
                return
            if self._freed_player_ids:
                player_id = self._freed_player_ids.pop(0)
            else:
                player_id = self._next_player_id
                self._next_player_id += 1
            conn = ClientConnection(player_id=player_id, reader=reader, writer=writer)
            self._clients[player_id] = conn

        conn.connected.set()

        try:
            # Send lobby info
            await send_message(writer, {
                "msg": "lobby_info",
                "client_player_id": player_id,
                "host_name": self._host_name,
            })

            # Wait for join
            msg = await recv_message(reader)
            if msg and msg.get("msg") == "join":
                conn.name = msg.get("player_name", "Client")
                conn.ready.set()
                print(f"[Server] Player '{conn.name}' connected (id={player_id})")

            # Broadcast lobby status and settings to all clients
            await self._broadcast_lobby_status()
            self.broadcast_lobby_settings()

            # Run send/recv concurrently — cancel the other when one exits
            recv_task = asyncio.ensure_future(self._recv_loop(reader, player_id))
            send_task = asyncio.ensure_future(self._send_loop(writer, conn.outbound))

            done, pending = await asyncio.wait(
                [recv_task, send_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
            pass
        finally:
            if conn.name:
                print(f"[Server] Player '{conn.name}' disconnected (id={player_id})")
            conn.connected.clear()
            conn.ready.clear()
            with self._clients_lock:
                self._clients.pop(player_id, None)
                self._freed_player_ids.append(player_id)
            writer.close()
            # Notify remaining clients about the disconnection
            try:
                await self._broadcast_lobby_status()
            except Exception:
                pass

    async def _recv_loop(self, reader: asyncio.StreamReader, player_id: int) -> None:
        """Receive commands from a specific client."""
        while self._running:
            try:
                msg = await asyncio.wait_for(recv_message(reader), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except (asyncio.IncompleteReadError, ConnectionError):
                break
            if msg is None:
                break
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

    async def _send_loop(self, writer: asyncio.StreamWriter, outbound: queue.Queue) -> None:
        """Send queued state frames to a specific client."""
        while self._running:
            try:
                frame = outbound.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.005)
                continue
            try:
                await send_message(writer, frame)
            except (ConnectionError, OSError):
                break

    async def _broadcast_lobby_status(self) -> None:
        """Send lobby_status to all connected clients with current roster."""
        with self._clients_lock:
            roster = {
                pid: {"name": c.name, "ready": c.ready.is_set()}
                for pid, c in self._clients.items()
                if c.connected.is_set()
            }
            writers = [
                c.writer for c in self._clients.values()
                if c.connected.is_set() and c.writer is not None
            ]

        msg = {
            "msg": "lobby_status",
            "players": roster,
            "max_players": self._max_players,
            "host_name": self._host_name,
        }
        for w in writers:
            try:
                await send_message(w, msg)
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
