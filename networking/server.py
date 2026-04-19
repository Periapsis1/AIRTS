"""Dedicated server — lobby-based headless server for online play.

Accepts remote clients, waits for a ``start_game`` request with game
configuration (map, slots, bots), creates the game, and runs it.
After the game ends, returns to the lobby for the next game.
"""
from __future__ import annotations

import time
from typing import Any

from networking.host import GameHost
from networking.protocol import DEFAULT_PORT
from systems.commands import CommandQueue


class DedicatedServer:
    """Lobby-based headless server that supports PvE and PvP.

    Usage::

        server = DedicatedServer(port=7777)
        server.run()  # blocks, loops lobby → game → lobby
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host_name: str = "Server",
        max_players: int = 8,
        max_ticks_default: int = 0,
        enable_t2_default: bool = False,
    ):
        self._port = port
        self._host_name = host_name
        self._max_players = max_players
        self._max_ticks_default = max_ticks_default
        self._enable_t2_default = enable_t2_default

        self._game = None
        self._host: GameHost | None = None

    def run(self) -> None:
        """Start server and loop: lobby → game → lobby."""
        # AI registry for creating bots
        from systems.ai import AIRegistry
        registry = AIRegistry()
        registry.discover()

        cq = CommandQueue()
        host = GameHost(
            command_queue=cq,
            port=self._port,
            host_name=self._host_name,
            max_players=self._max_players,
        )
        self._host = host
        host.start()

        print(f"[Server] Listening on port {self._port}")
        print(f"[Server] Local IP: {host.local_ip}")
        print(f"[Server] Waiting for players to connect and start a game...")

        while True:
            result = self._run_lobby_then_game(host, registry)
            if result is None:
                break  # server shutting down

            winner = result.get("winner", 0)
            team_names = result.get("team_names", {})
            if winner > 0:
                print(f"[Server] Winner: Team {winner} ({team_names.get(winner, '?')})")
            elif winner == -1:
                print("[Server] Result: Draw")
            else:
                print("[Server] Result: Undecided")

            # Return to lobby
            host.send_return_to_lobby()
            time.sleep(0.3)
            host.reset()
            print("[Server] Returned to lobby. Waiting for next game...")

    def _run_lobby_then_game(
        self, host: GameHost, registry,
    ) -> dict[str, Any] | None:
        """Wait for a start_game request, then create and run the game."""
        from game import Game
        from systems.map_generator import DefaultMapGenerator

        # -- Lobby phase: wait for a client to send start_game --
        config = None
        while config is None:
            if not host._running:
                return None
            config = host.poll_start_game()
            if config is None:
                time.sleep(0.05)

        # -- Parse config --
        width = config.get("width", 800)
        height = config.get("height", 600)
        obs_val = config.get("obstacle_count", 0)
        metal_spots: int = config.get("metal_spots", 0)
        time_limit: int = config.get("time_limit", 0)
        enable_t2: bool = config.get("enable_t2", self._enable_t2_default)
        fog_of_war: bool = config.get("fog_of_war", False)
        max_ticks = time_limit * 60 * 60 if time_limit > 0 else self._max_ticks_default

        # Build player_ai, player_team, and player_colors from config
        player_ai_ids: dict[int, str] = {}
        player_team: dict[int, int] = {}
        player_colors: dict[int, int] = {}

        raw_ai = config.get("player_ai_ids", {})
        raw_team = config.get("player_team", {})
        raw_colors = config.get("player_colors", {})
        raw_spectators = config.get("spectators", []) or []
        spectators: set[int] = {int(p) for p in raw_spectators}
        for k, v in raw_ai.items():
            player_ai_ids[int(k)] = v
        for k, v in raw_team.items():
            player_team[int(k)] = int(v)
        for k, v in raw_colors.items():
            player_colors[int(k)] = int(v)

        # Fallback: if no player_team, default to 1v1
        if not player_team:
            player_team = {1: 1, 2: 2}

        # Create AI instances from registry
        player_ai: dict = {}
        for pid, ai_id in player_ai_ids.items():
            try:
                player_ai[pid] = registry.create(ai_id)
            except KeyError:
                from systems.ai import WanderAI
                player_ai[pid] = WanderAI()

        obs = (obs_val, obs_val)
        map_gen = DefaultMapGenerator(
            obstacle_count=obs,
            metal_spots_per_side=metal_spots,
        )

        print(f"[Server] Starting game: {width}x{height}, "
              f"{len(player_team)} players, {len(player_ai)} bots")

        # -- Create and run game --
        game = Game(
            width=width,
            height=height,
            map_generator=map_gen,
            player_ai=player_ai,
            player_team=player_team,
            player_colors=player_colors or None,
            player_name=self._host_name,
            headless=True,
            max_ticks=max_ticks,
            is_multiplayer=True,
            selectable_teams=set(),
            enable_t2=enable_t2,
            fog_of_war=fog_of_war,
            server_mode=True,
            spectator_players=spectators,
        )
        self._game = game

        # Rebind host's command queue to the game's actual queue
        host._command_queue = game._command_queue

        # Build player_names
        client_names = host.client_names
        player_names: dict[int, str] = {}
        for pid in sorted(game.all_players):
            if pid in client_names and client_names[pid]:
                player_names[pid] = client_names[pid]
            elif pid in game.player_ai:
                player_names[pid] = game.player_ai[pid].ai_name
            else:
                player_names[pid] = self._host_name
        # Spectators aren't in all_players but still need display names.
        for sp_pid in spectators:
            if sp_pid in player_names:
                continue
            if sp_pid in client_names and client_names[sp_pid]:
                player_names[sp_pid] = client_names[sp_pid]
            else:
                player_names[sp_pid] = self._host_name

        # Build team_colors from game's resolved colors
        team_colors: dict[int, list[int]] = {}
        for t in game.all_teams:
            c = game._team_color(t)
            team_colors[t] = list(c[:3])

        # Send game_start to all clients
        host.send_game_start(
            game.entities, width, height,
            enable_t2=enable_t2,
            fog_of_war=fog_of_war,
            player_team=dict(game.player_team),
            player_names=player_names,
            team_colors=team_colors,
            spectators=spectators,
        )

        print("[Server] Game started!")

        # Run simulation with networked callbacks
        def pre_step():
            host.inject_remote_commands()

        def post_step(tick, entities, laser_flashes, winner,
                      sound_events=None, death_events=None):
            host.broadcast_state(
                tick, entities, laser_flashes, winner,
                splash_effects=game.splash_effects,
                sound_events=sound_events,
                death_events=death_events,
                team_visibility=game._team_vision if game._fog_of_war else None,
                player_team=dict(game.player_team) if game._fog_of_war else None,
                metal_spots=game.metal_spots if game._fog_of_war else None,
            )

        result = game.run_server(pre_step=pre_step, post_step=post_step)

        # Send game_over to all clients (include stats for score screen)
        host.send_game_over(result.get("winner", 0), stats=result.get("stats"))
        time.sleep(0.5)

        # Build team/player names for result
        result["team_names"] = {}
        for pid, name in player_names.items():
            tm = player_team.get(pid, pid)
            result["team_names"][tm] = name
        result["player_names"] = player_names

        self._game = None
        return result
