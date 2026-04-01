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
        self._outbound_messages: queue.Queue[dict] = queue.Queue()  # raw pre-formatted messages

        # Connection state
        self.player_id: int = 0  # assigned by host in lobby_info
        self.host_name: str = ""
        self.map_width: int = 800
        self.map_height: int = 600
        self.obstacles: list[dict] = []
        self.enable_t2: bool = False
        self.fog_of_war: bool = False
        self.player_team: dict[int, int] = {}
        self.player_names: dict[int, str] = {}

        self._connected = threading.Event()
        self._game_started = threading.Event()
        self._error: str = ""
        self._running = True
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._tasks: list = []
        self.game_over_stats: dict | None = None

        # Lobby status from server (for "Play Online" mode)
        self._lobby_status: dict | None = None
        self._lobby_settings: dict | None = None
        self._lobby_lock = threading.Lock()
        self.opponent_name: str = ""

    @property
    def client_team(self) -> int:
        """Team this client belongs to, derived from player_team mapping."""
        if self.player_team and self.player_id in self.player_team:
            return self.player_team[self.player_id]
        return self.player_id  # fallback for legacy 1v1

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def game_started(self) -> bool:
        return self._game_started.is_set()

    @property
    def error(self) -> str:
        return self._error

    @property
    def lobby_status(self) -> dict | None:
        with self._lobby_lock:
            return self._lobby_status

    @property
    def lobby_settings(self) -> dict | None:
        with self._lobby_lock:
            return self._lobby_settings

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the networking thread and connect to host."""
        self._thread = threading.Thread(target=self._run_network, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Disconnect and shut down."""
        self._running = False
        # Cancel pending tasks so gather() returns promptly
        if self._loop is not None and not self._loop.is_closed():
            for task in self._tasks:
                if not task.done():
                    self._loop.call_soon_threadsafe(task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def reset(self) -> None:
        """Reset for a new game, keeping the connection alive."""
        self._game_started.clear()
        self.game_over_stats = None
        # Drain stale inbound frames
        while True:
            try:
                self._inbound.get_nowait()
            except queue.Empty:
                break

    # -- game-thread API (called from the main/pygame thread) ---------------

    def send_start_game(self, config: dict) -> None:
        """Send a start_game request to the server with game configuration."""
        self._outbound_messages.put({"msg": "start_game", "config": config})

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
            if msg and msg.get("msg") == "rejected":
                self._error = msg.get("reason", "Connection rejected by server")
                writer.close()
                return
            if msg and msg.get("msg") == "lobby_info":
                self.player_id = msg.get("client_player_id", msg.get("client_team", 2))
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
            self._tasks = [recv_task, send_task]
            await asyncio.gather(recv_task, send_task)

        except asyncio.CancelledError:
            pass  # Expected during clean shutdown via stop()
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            self._error = f"Disconnected: {e}"
        finally:
            self._tasks = []
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
                self.enable_t2 = msg.get("enable_t2", False)
                self.fog_of_war = msg.get("fog_of_war", False)
                # Restore int keys from JSON string keys
                raw_pt = msg.get("player_team", {})
                self.player_team = {int(k): v for k, v in raw_pt.items()} if raw_pt else {}
                raw_pn = msg.get("player_names", {})
                self.player_names = {int(k): v for k, v in raw_pn.items()} if raw_pn else {}
                self._game_started.set()
            elif msg_type == "lobby_status":
                with self._lobby_lock:
                    self._lobby_status = msg
                # Extract opponent name
                players = msg.get("players", {})
                for pid_str, info in players.items():
                    pid = int(pid_str) if isinstance(pid_str, str) else pid_str
                    if pid != self.player_id and info.get("name"):
                        self.opponent_name = info["name"]
            elif msg_type == "lobby_settings":
                with self._lobby_lock:
                    self._lobby_settings = msg
            elif msg_type == "return_to_lobby":
                self._game_started.clear()
                self._inbound.put(msg)
            elif msg_type == "game_over":
                self.game_over_stats = msg.get("stats")
                self._inbound.put(msg)
            elif msg_type == "state":
                self._inbound.put(msg)

    async def _send_loop(self, writer: asyncio.StreamWriter) -> None:
        """Send queued commands and raw messages to the host."""
        while self._running:
            sent = False
            # Drain raw messages (start_game, etc.)
            try:
                msg = self._outbound_messages.get_nowait()
                await send_message(writer, msg)
                sent = True
            except queue.Empty:
                pass
            except (ConnectionError, OSError):
                break
            # Drain game commands
            try:
                cmd_raw = self._outbound_commands.get_nowait()
                await send_message(writer, {
                    "msg": "command",
                    "command": cmd_raw,
                })
                sent = True
            except queue.Empty:
                pass
            except (ConnectionError, OSError):
                break
            if not sent:
                await asyncio.sleep(0.005)
