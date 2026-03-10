"""Host-side networking for authoritative multiplayer.

The host runs the full Game instance in the main thread (with pygame).
Networking runs in a daemon thread via asyncio. Two thread-safe queues
bridge the gap:
  - _inbound_commands: remote player commands → game step
  - _outbound_states:  game state frames → remote player
"""
from __future__ import annotations

import asyncio
import queue
import socket
import threading
from typing import Any

from networking.protocol import send_message, recv_message, DEFAULT_PORT
from systems.commands import GameCommand, CommandQueue
from systems.replay import (
    _entity_visual, _laser_visual, _obstacle_visual, RECORD_INTERVAL,
)


class GameHost:
    """Server that accepts one client and bridges commands/state over TCP."""

    def __init__(
        self,
        command_queue: CommandQueue,
        port: int = DEFAULT_PORT,
        host_name: str = "Host",
    ):
        self._command_queue = command_queue
        self._port = port
        self._host_name = host_name

        # Cross-thread queues
        self._inbound_commands: queue.Queue[GameCommand] = queue.Queue()
        self._outbound: queue.Queue[dict] = queue.Queue()

        # Connection state
        self._client_name: str = ""
        self._client_team: int = 2  # client always plays team 2
        self._client_connected = threading.Event()
        self._client_ready = threading.Event()
        self._running = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        # Determine local IP for display
        self.local_ip = self._get_local_ip()

    @property
    def client_name(self) -> str:
        return self._client_name

    @property
    def client_connected(self) -> bool:
        return self._client_connected.is_set()

    @property
    def client_ready(self) -> bool:
        return self._client_ready.is_set()

    @property
    def port(self) -> int:
        return self._port

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the networking thread and TCP server."""
        self._thread = threading.Thread(target=self._run_network, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Shut down the server and networking thread."""
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

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
    ) -> None:
        """Build a visual state frame and queue it for sending (every RECORD_INTERVAL)."""
        if tick % RECORD_INTERVAL != 0:
            return
        ent_visuals = []
        for e in entities:
            vd = _entity_visual(e)
            if vd is not None:
                ent_visuals.append(vd)
        lf_list = [_laser_visual(lf) for lf in laser_flashes]
        frame: dict[str, Any] = {
            "msg": "state",
            "tick": tick,
            "entities": ent_visuals,
            "lasers": lf_list,
            "winner": winner,
        }
        # Drop old unsent frames if client is slow — keep only latest
        try:
            while True:
                self._outbound.get_nowait()
        except queue.Empty:
            pass
        self._outbound.put(frame)

    def send_game_start(self, entities: list, map_width: int, map_height: int) -> None:
        """Send the initial game_start message with obstacle data."""
        obstacles = []
        for e in entities:
            od = _obstacle_visual(e)
            if od is not None:
                obstacles.append(od)
        self._outbound.put({
            "msg": "game_start",
            "obstacles": obstacles,
            "map_width": map_width,
            "map_height": map_height,
        })

    def send_game_over(self, winner: int) -> None:
        """Send game_over notification."""
        self._outbound.put({"msg": "game_over", "winner": winner})

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
        async with server:
            # Keep running until stopped
            while self._running:
                await asyncio.sleep(0.05)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection."""
        if self._client_connected.is_set():
            # Only one client allowed
            writer.close()
            await writer.wait_closed()
            return

        self._client_connected.set()

        try:
            # Send lobby info
            await send_message(writer, {
                "msg": "lobby_info",
                "client_team": self._client_team,
                "host_name": self._host_name,
            })

            # Wait for join
            msg = await recv_message(reader)
            if msg and msg.get("msg") == "join":
                self._client_name = msg.get("player_name", "Client")
                self._client_ready.set()

            # Run send/recv concurrently
            recv_task = asyncio.ensure_future(self._recv_loop(reader))
            send_task = asyncio.ensure_future(self._send_loop(writer))

            await asyncio.gather(recv_task, send_task)

        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            self._client_connected.clear()
            self._client_ready.clear()
            writer.close()

    async def _recv_loop(self, reader: asyncio.StreamReader) -> None:
        """Receive commands from the client."""
        while self._running:
            try:
                msg = await asyncio.wait_for(recv_message(reader), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except (asyncio.IncompleteReadError, ConnectionError):
                break
            if msg is None:
                break
            if msg.get("msg") == "command":
                cmd_data = msg.get("command", "")
                try:
                    cmd = GameCommand.deserialize(cmd_data)
                    # Force team to client's team for security
                    cmd.team = self._client_team
                    self._inbound_commands.put(cmd)
                except Exception:
                    pass

    async def _send_loop(self, writer: asyncio.StreamWriter) -> None:
        """Send queued state frames to the client."""
        while self._running:
            try:
                frame = self._outbound.get(timeout=0.05)
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            try:
                await send_message(writer, frame)
            except (ConnectionError, OSError):
                break

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
