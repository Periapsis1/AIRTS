"""Internal server — runs Game + GameHost in a background thread for local play.

Used for singleplayer and LAN-host modes so that ALL game modes route through
the same GameClient → ClientGameScreen rendering path (Minecraft-style).
"""
from __future__ import annotations

import threading
import time
from typing import Any

from networking.host import GameHost
from systems.commands import CommandQueue


class InternalServer:
    """Persistent server that hosts games in a background thread.

    The server (GameHost + TCP socket) is created once and can run multiple
    games sequentially.  Between games, call ``reset()`` to clear state while
    keeping client connections alive, then call ``run_game()`` again.

    Lifecycle::

        __init__()         → creates GameHost
        start()            → starts GameHost TCP server
        run_game(params)   → spawns game thread
        wait_done()        → blocks until game ends
        reset()            → clears game state, host stays alive
        run_game(params)   → another game
        stop()             → tears everything down
    """

    def __init__(
        self,
        port: int = 0,
        host_name: str = "Host",
        max_players: int = 1,
        broadcast_interval: int = 2,
        first_player_id: int | None = None,
        existing_host: GameHost | None = None,
    ):
        self._host_name = host_name
        self._max_players = max_players
        self._broadcast_interval = broadcast_interval
        self._owns_host = existing_host is None

        self._command_queue = CommandQueue()

        if existing_host is not None:
            self._host = existing_host
            self._host._broadcast_interval = broadcast_interval
        else:
            self._host = GameHost(
                command_queue=self._command_queue,
                port=port,
                host_name=host_name,
                max_players=max_players,
                broadcast_interval=broadcast_interval,
                first_player_id=first_player_id if first_player_id is not None else (2 if max_players == 1 else 1),
            )

        self._result: dict[str, Any] | None = None
        self._done_event = threading.Event()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._game = None  # set on game thread

    # -- public API ---------------------------------------------------------

    @property
    def port(self) -> int:
        """Actual bound port (blocks briefly until server socket is ready)."""
        return self._host.bound_port

    @property
    def host(self) -> GameHost:
        return self._host

    @property
    def result(self) -> dict[str, Any] | None:
        """Game result dict (available after game finishes)."""
        return self._result

    def start(self) -> None:
        """Start the GameHost networking (TCP server). Does NOT start a game."""
        self._host.start()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Block until the server is listening and ready for connections."""
        return self._host._bound_event.wait(timeout=timeout)

    def wait_done(self, timeout: float | None = None) -> bool:
        """Block until the current game finishes."""
        return self._done_event.wait(timeout=timeout)

    def run_game(
        self,
        width: int,
        height: int,
        map_generator,
        player_ai: dict,
        player_team: dict[int, int] | None,
        player_colors: dict[int, int] | None = None,
        replay_config: dict | None = None,
        player_name: str = "Human",
        max_ticks: int = 0,
        enable_t2: bool = False,
        fog_of_war: bool = False,
        save_replay: bool = True,
    ) -> None:
        """Spawn a background thread to run a game with the given parameters.

        The GameHost must already be started via ``start()``.  Call
        ``wait_done()`` to block until the game finishes, then read
        ``result`` for the outcome.
        """
        self._game_params = {
            "width": width,
            "height": height,
            "map_generator": map_generator,
            "player_ai": player_ai,
            "player_team": player_team,
            "player_colors": player_colors,
            "replay_config": replay_config,
            "player_name": player_name,
            "max_ticks": max_ticks,
            "enable_t2": enable_t2,
            "fog_of_war": fog_of_war,
            "save_replay": save_replay,
        }
        self._stop_requested.clear()
        self._done_event.clear()
        self._result = None
        self._game = None
        self._thread = threading.Thread(target=self._run_game, daemon=True)
        self._thread.start()

    def reset(self) -> None:
        """Reset for a new game.  Keeps the TCP server and connections alive."""
        # Signal the game loop and pre-game wait loop to exit
        self._stop_requested.set()
        if self._game is not None:
            self._game.running = False
        # Wait for the game thread to finish
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._done_event.clear()
        self._result = None
        self._game = None
        self._host.reset(clear_clients=True)

    def stop(self) -> None:
        """Clean shutdown of game and networking."""
        self._stop_requested.set()
        if self._game is not None:
            self._game.running = False
        self._host.stop()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    # -- game thread --------------------------------------------------------

    def _run_game(self) -> None:
        """Entry point for the background game thread."""
        from game import Game

        p = self._game_params

        game = Game(
            width=p["width"],
            height=p["height"],
            map_generator=p["map_generator"],
            player_ai=p["player_ai"],
            player_team=p["player_team"],
            player_colors=p.get("player_colors"),
            player_name=p["player_name"],
            headless=True,
            max_ticks=p["max_ticks"],
            is_multiplayer=True,
            selectable_teams=set(),  # no local selection on server thread
            enable_t2=p["enable_t2"],
            fog_of_war=p["fog_of_war"],
            server_mode=True,
            save_replay=p["save_replay"],
            replay_config=p["replay_config"],
        )
        self._game = game

        # Bind host's command queue to the game's actual queue
        self._host._command_queue = game._command_queue

        # Wait for all clients to connect and be ready
        while not self._host.all_clients_ready:
            if not self._host._running or self._stop_requested.is_set():
                self._done_event.set()
                return
            time.sleep(0.05)

        # Build player_names for game_start message
        client_names = self._host.client_names
        player_names: dict[int, str] = {}
        for pid in sorted(game.all_players):
            if pid in client_names and client_names[pid]:
                player_names[pid] = client_names[pid]
            elif pid in game.player_ai:
                player_names[pid] = game.player_ai[pid].ai_name
            else:
                player_names[pid] = p["player_name"]

        # Build team_colors from game's resolved colors
        team_colors: dict[int, list[int]] = {}
        for t in game.all_teams:
            c = game._team_color(t)
            team_colors[t] = list(c[:3])

        # Send game_start
        self._host.send_game_start(
            game.entities, p["width"], p["height"],
            enable_t2=p["enable_t2"],
            fog_of_war=p["fog_of_war"],
            player_team=dict(game.player_team),
            player_names=player_names,
            team_colors=team_colors,
        )

        # Run simulation with networked callbacks
        def pre_step():
            self._host.inject_remote_commands()

        def post_step(tick, entities, laser_flashes, winner,
                      sound_events=None, death_events=None,
                      chat_events=None):
            self._host.broadcast_state(
                tick, entities, laser_flashes, winner,
                splash_effects=game.splash_effects,
                sound_events=sound_events,
                death_events=death_events,
                chat_events=chat_events,
                team_visibility=game._team_vision if game._fog_of_war else None,
                player_team=dict(game.player_team),
                metal_spots=game.metal_spots if game._fog_of_war else None,
            )

        try:
            result = game.run_server(pre_step=pre_step, post_step=post_step)
        except Exception as exc:
            result = {"winner": 0, "error": str(exc)}

        # Notify clients of game over (include stats for score screen)
        self._host.send_game_over(result.get("winner", 0), stats=result.get("stats"))
        time.sleep(0.3)  # brief delay for message to transmit

        self._result = result
        self._result["player_names"] = player_names
        self._done_event.set()
