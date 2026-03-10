"""Client-side networking for multiplayer.

The client is a thin display layer: it sends commands to the host and
receives visual state frames for rendering. Like the host, networking
runs in a daemon thread with asyncio, bridged by thread-safe queues.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any

from networking.protocol import send_message, recv_message, DEFAULT_PORT
from systems.commands import GameCommand


class GameClient:
    """Connects to a GameHost and exchanges commands/state."""

    def __init__(
        self,
        host_ip: str,
        port: int = DEFAULT_PORT,
        player_name: str = "Client",
    ):
        self._host_ip = host_ip
        self._port = port
        self._player_name = player_name

        # Cross-thread queues
        self._inbound: queue.Queue[dict] = queue.Queue()
        self._outbound_commands: queue.Queue[str] = queue.Queue()

        # Connection state
        self.client_team: int = 2
        self.host_name: str = ""
        self.map_width: int = 800
        self.map_height: int = 600
        self.obstacles: list[dict] = []

        self._connected = threading.Event()
        self._game_started = threading.Event()
        self._error: str = ""
        self._running = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def game_started(self) -> bool:
        return self._game_started.is_set()

    @property
    def error(self) -> str:
        return self._error

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the networking thread and connect to host."""
        self._thread = threading.Thread(target=self._run_network, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Disconnect and shut down."""
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- game-thread API (called from the main/pygame thread) ---------------

    def send_command(self, cmd: GameCommand) -> None:
        """Queue a command to send to the host."""
        self._outbound_commands.put(cmd.serialize())

    def poll_state(self) -> dict | None:
        """Non-blocking poll for the latest state frame from the host.

        Returns the most recent frame, discarding any older queued frames.
        """
        latest = None
        while True:
            try:
                latest = self._inbound.get_nowait()
            except queue.Empty:
                break
        return latest

    # -- networking thread --------------------------------------------------

    def _run_network(self) -> None:
        """Entry point for the daemon thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_run())
        except Exception as e:
            self._error = str(e)
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _connect_and_run(self) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host_ip, self._port),
                timeout=10.0,
            )
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            self._error = f"Connection failed: {e}"
            return

        try:
            # Receive lobby info
            msg = await asyncio.wait_for(recv_message(reader), timeout=10.0)
            if msg and msg.get("msg") == "lobby_info":
                self.client_team = msg.get("client_team", 2)
                self.host_name = msg.get("host_name", "Host")

            # Send join
            await send_message(writer, {
                "msg": "join",
                "player_name": self._player_name,
            })
            self._connected.set()

            # Run send/recv concurrently
            recv_task = asyncio.ensure_future(self._recv_loop(reader))
            send_task = asyncio.ensure_future(self._send_loop(writer))
            await asyncio.gather(recv_task, send_task)

        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            self._error = f"Disconnected: {e}"
        finally:
            self._connected.clear()
            writer.close()

    async def _recv_loop(self, reader: asyncio.StreamReader) -> None:
        """Receive state frames and game events from the host."""
        while self._running:
            try:
                msg = await asyncio.wait_for(recv_message(reader), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except (asyncio.IncompleteReadError, ConnectionError):
                break
            if msg is None:
                break

            msg_type = msg.get("msg")
            if msg_type == "game_start":
                self.obstacles = msg.get("obstacles", [])
                self.map_width = msg.get("map_width", 800)
                self.map_height = msg.get("map_height", 600)
                self._game_started.set()
            elif msg_type in ("state", "game_over"):
                self._inbound.put(msg)

    async def _send_loop(self, writer: asyncio.StreamWriter) -> None:
        """Send queued commands to the host."""
        while self._running:
            try:
                cmd_raw = self._outbound_commands.get(timeout=0.05)
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            try:
                await send_message(writer, {
                    "msg": "command",
                    "command": cmd_raw,
                })
            except (ConnectionError, OSError):
                break
