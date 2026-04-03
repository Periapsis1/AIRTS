"""Application controller — pygame lifecycle, screen routing."""
from __future__ import annotations
import pygame
from systems.ai import AIRegistry
from systems.crash_handler import log_crash
from screens.base import ScreenResult
from screens.main_menu import MainMenuScreen
from screens.create_lobby import CreateLobbyScreen
from screens.guides import GuidesScreen
from screens.unit_overview import UnitOverviewScreen
from screens.results import ResultsScreen
from screens.replay_list import ReplayListScreen
from screens.replay_playback import ReplayPlaybackScreen
from screens.crash_notice import CrashNoticeScreen
from screens.options import OptionsScreen
from screens.arena_screen import ArenaScreen
from screens.debug_screen import DebugScreen
from screens.multiplayer_lobby import MultiplayerLobbyScreen
from screens.client_game import ClientGameScreen
import config.display as display_config


class App:
    """Top-level application: initialises pygame once, routes between screens."""

    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        display_config.load_settings()
        self._screen = display_config.create_display()
        pygame.display.set_caption("AIRTS")
        self._clock = pygame.time.Clock()

        from systems import music
        music.init()

        self._registry = AIRegistry()
        self._registry.discover()
        if self._registry.errors:
            for err in self._registry.errors:
                print(f"[AI Registry] {err}")

    def run(self):
        result = ScreenResult("main_menu")
        while result.next_screen != "quit":
            try:
                result = self._run_screen(result)
            except Exception as exc:
                path = log_crash(exc, context="screen")
                print(f"[AIRTS] Crash logged to {path}")
                result = ScreenResult("crash_notice",
                                      data={"log_path": path, "context": "screen"})
        pygame.quit()

    def _run_screen(self, prev: ScreenResult) -> ScreenResult:
        name = prev.next_screen
        data = prev.data

        if name == "main_menu":
            return MainMenuScreen(self._screen, self._clock).run()

        elif name == "create_lobby":
            choices = self._registry.get_choices()
            if not choices:
                choices = [("wander", "Wander AI")]
            server = data.get("server") if data else None
            online_client = data.get("online_client") if data else None
            return CreateLobbyScreen(self._screen, self._clock, choices,
                                     server=server,
                                     online_client=online_client).run()

        elif name == "game":
            return self._run_game(data)

        elif name == "guides":
            return GuidesScreen(self._screen, self._clock).run()

        elif name == "unit_overview":
            return UnitOverviewScreen(self._screen, self._clock).run()

        elif name == "options":
            result = OptionsScreen(self._screen, self._clock).run()
            # Display mode may have changed; refresh screen reference
            self._screen = pygame.display.get_surface()
            return result

        elif name == "arena":
            choices = self._registry.get_choices()
            return ArenaScreen(self._screen, self._clock, choices).run()

        elif name == "replays":
            return ReplayListScreen(self._screen, self._clock).run()

        elif name == "replay_playback":
            return self._run_replay_playback(data)

        elif name == "results":
            winner = data.get("winner", 0)
            human_teams = data.get("human_teams", set())
            stats = data.get("stats")
            replay_filepath = data.get("replay_filepath")
            team_names = data.get("team_names", {})
            player_names = data.get("player_names", {})
            player_team = data.get("player_team", {})
            source_screen = data.get("source_screen", "main_menu")
            lobby_data = data.get("lobby_data", {})
            return ResultsScreen(self._screen, self._clock,
                                 winner, human_teams, stats=stats,
                                 replay_filepath=replay_filepath,
                                 team_names=team_names,
                                 player_names=player_names,
                                 player_team=player_team,
                                 source_screen=source_screen,
                                 lobby_data=lobby_data).run()

        elif name == "debug":
            return DebugScreen(self._screen, self._clock,
                               winner=data.get("winner", 0),
                               human_teams=data.get("human_teams", set()),
                               stats=data.get("stats"),
                               replay_filepath=data.get("replay_filepath"),
                               team_names=data.get("team_names", {})).run()

        elif name == "replay_debug":
            filepath = data.get("filepath", "")
            stats = data.get("stats")
            result = DebugScreen(self._screen, self._clock,
                                 stats=stats).run()
            if result.next_screen == "quit":
                return result
            # Return to replay playback
            return ScreenResult("replay_playback", data={"filepath": filepath})

        elif name == "multiplayer_lobby":
            returning_host = data.get("host") if data else None
            returning_client = data.get("client") if data else None
            return MultiplayerLobbyScreen(
                self._screen, self._clock,
                returning_host=returning_host,
                returning_client=returning_client,
            ).run()

        elif name == "mp_client_game":
            return self._run_mp_client_game(data)

        elif name == "crash_notice":
            return CrashNoticeScreen(self._screen, self._clock,
                                     log_path=data.get("log_path", ""),
                                     context=data.get("context", "")).run()

        else:
            # Unknown or placeholder screens → back to menu
            return ScreenResult("main_menu")

    def _run_game(self, data: dict) -> ScreenResult:
        from systems.map_generator import DefaultMapGenerator
        from networking.internal_server import InternalServer
        from networking.client import GameClient

        width = data.get("width", 800)
        height = data.get("height", 600)
        obs = data.get("obstacle_count", (4, 8))
        metal_spots: int = data.get("metal_spots", 0)
        player_name: str = data.get("player_name", "Unnamed Player")
        enable_t2: bool = data.get("enable_t2", False)
        fog_of_war: bool = data.get("fog_of_war", False)
        time_limit: int = data.get("time_limit", 0)  # minutes, 0 = no limit
        max_ticks = time_limit * 60 * 60 if time_limit > 0 else 0  # 60 ticks/sec

        # New format: player_ai_ids maps player_id → ai_id; fallback to legacy team_ai_ids
        player_ai_ids: dict[int, str] = (
            data.get("player_ai_ids")
            or data.get("team_ai_ids")
            or {}
        )
        player_team: dict[int, int] | None = data.get("player_team")

        # Build AI instances from registry
        player_ai: dict = {}
        for pid, ai_id in player_ai_ids.items():
            try:
                player_ai[pid] = self._registry.create(ai_id)
            except KeyError:
                from systems.ai import WanderAI
                player_ai[pid] = WanderAI()

        # Fallback only for bare programmatic calls with no player_team.
        if not player_ai and player_team is None:
            from systems.ai import WanderAI
            player_ai = {2: WanderAI()}

        replay_config = {
            "player_ai_ids": player_ai_ids,
            "player_ai_names": {pid: ai.ai_name for pid, ai in player_ai.items()},
            "player_team": player_team,
            "obstacle_count": list(obs),
            "player_name": player_name,
        }

        # Determine if there are human players
        all_pids = set(player_team.keys()) if player_team else {1, 2}
        human_pids = all_pids - set(player_ai.keys())
        headless: bool = data.get("headless", False)
        has_human = len(human_pids) > 0 and not headless

        map_gen = DefaultMapGenerator(obstacle_count=obs,
                                      metal_spots_per_side=metal_spots)

        if not has_human:
            # --- Bot-vs-bot or headless: run Game directly, no client needed ---
            from game import Game
            save_debug_summary: bool = data.get("save_debug_summary", False)
            screen_w = self._screen.get_width()
            screen_h = self._screen.get_height()

            game = Game(
                width=width, height=height,
                map_generator=map_gen,
                player_ai=player_ai,
                player_team=player_team,
                screen=self._screen,
                clock=self._clock,
                replay_config=replay_config,
                player_name=player_name,
                headless=headless,
                max_ticks=max_ticks,
                save_debug_summary=save_debug_summary,
                screen_width=screen_w,
                screen_height=screen_h,
                enable_t2=enable_t2,
                fog_of_war=fog_of_war,
            )

            try:
                result = game.run()
            except Exception as exc:
                path = log_crash(exc, context="game")
                print(f"[AIRTS] Game crashed — log saved to {path}")
                return ScreenResult("crash_notice",
                                    data={"log_path": path, "context": "game"})

            return ScreenResult("results", data={
                "winner": result.get("winner", 0),
                "human_teams": result.get("human_teams", set()),
                "stats": result.get("stats"),
                "replay_filepath": result.get("replay_filepath"),
                "team_names": result.get("team_names", {}),
                "player_names": result.get("player_names", {}),
                "player_team": result.get("player_team", {}),
                "source_screen": "create_lobby",
            })

        # --- Human present: route through InternalServer → GameClient → ClientGameScreen ---
        server: InternalServer | None = data.get("server")
        owns_server = server is None

        if server is None:
            # Determine first_player_id so client gets the right slot
            first_player_id = min(human_pids) if human_pids else 1
            server = InternalServer(
                port=0,
                host_name=player_name,
                max_players=1,
                first_player_id=first_player_id,
            )
            server.start()
            server.wait_ready()

        try:
            server.run_game(
                width=width,
                height=height,
                map_generator=map_gen,
                player_ai=player_ai,
                player_team=player_team,
                replay_config=replay_config,
                player_name=player_name,
                max_ticks=max_ticks,
                enable_t2=enable_t2,
                fog_of_war=fog_of_war,
            )

            client = GameClient("127.0.0.1", port=server.port, player_name=player_name)
            client.start()

            # Wait for game_start from server
            client._game_started.wait(timeout=10.0)
            if not client.game_started:
                server.stop()
                return ScreenResult("main_menu")

            result = ClientGameScreen(
                self._screen, self._clock, client, is_local=True,
            ).run()

            # If the game ended early (surrender/lobby), stop the server
            # game thread and propagate the winner so stats are finalized.
            game_obj = server._game
            if game_obj is not None and game_obj.running:
                client_winner = result.data.get("winner", 0)
                if client_winner != 0 and game_obj._winner == 0:
                    game_obj._winner = client_winner
                game_obj.running = False

            # Wait for server to finish and collect its result
            server.wait_done(timeout=5.0)
            srv_result = server.result or {}

            # Merge server-side data (stats, replay) with client-side outcome
            merged = {
                "winner": srv_result.get("winner", result.data.get("winner", 0)),
                "human_teams": srv_result.get("human_teams", result.data.get("human_teams", set())),
                "stats": srv_result.get("stats"),
                "replay_filepath": srv_result.get("replay_filepath") or result.data.get("replay_filepath"),
                "team_names": srv_result.get("team_names", result.data.get("team_names", {})),
                "player_names": srv_result.get("player_names", result.data.get("player_names", {})),
                "player_team": srv_result.get("player_team", result.data.get("player_team", {})),
                "source_screen": "create_lobby",
                "lobby_data": {"server": server},
            }

        except Exception as exc:
            server.stop()
            path = log_crash(exc, context="game")
            print(f"[AIRTS] Game crashed — log saved to {path}")
            return ScreenResult("crash_notice",
                                data={"log_path": path, "context": "game"})

        if result.next_screen in ("quit", "main_menu"):
            # User quit or escaped mid-game — tear down the server
            server.stop()
            merged.pop("lobby_data", None)
            if result.next_screen == "quit":
                return result
        else:
            # Normal game end — reset server for next game
            server.reset()

        return ScreenResult("results", data=merged)

    def _run_mp_client_game(self, data: dict) -> ScreenResult:
        """Run a multiplayer game as the thin client."""
        from networking.client import GameClient

        client: GameClient = data["client"]

        try:
            result = ClientGameScreen(self._screen, self._clock, client).run()
        except Exception as exc:
            client.stop()
            path = log_crash(exc, context="mp_client_game")
            print(f"[AIRTS] MP client game crashed — log saved to {path}")
            return ScreenResult("crash_notice",
                                data={"log_path": path, "context": "mp_client_game"})

        if result.next_screen == "results":
            # Determine where to return: online games go to create_lobby,
            # LAN join games go to multiplayer_lobby
            if data.get("from_online_lobby"):
                result.data["source_screen"] = "create_lobby"
                result.data["lobby_data"] = {"online_client": client}
            else:
                result.data["source_screen"] = "multiplayer_lobby"
                result.data["lobby_data"] = {"client": client}
        return result

    def _run_replay_playback(self, data: dict) -> ScreenResult:
        filepath = data.get("filepath", "")

        try:
            result = ReplayPlaybackScreen(self._screen, self._clock, filepath).run()
        except Exception as exc:
            path = log_crash(exc, context="replay")
            print(f"[AIRTS] Replay crashed — log saved to {path}")
            return ScreenResult("crash_notice",
                                data={"log_path": path, "context": "replay"})

        return result
