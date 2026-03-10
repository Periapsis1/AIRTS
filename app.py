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
            return CreateLobbyScreen(self._screen, self._clock, choices).run()

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
            return ResultsScreen(self._screen, self._clock,
                                 winner, human_teams, stats=stats,
                                 replay_filepath=replay_filepath,
                                 team_names=team_names).run()

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
            return MultiplayerLobbyScreen(self._screen, self._clock).run()

        elif name == "mp_host_game":
            return self._run_mp_host_game(data)

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
        from game import Game
        from systems.map_generator import DefaultMapGenerator

        width = data.get("width", 800)
        height = data.get("height", 600)
        obs = data.get("obstacle_count", (4, 8))
        team_ai_ids: dict[int, str] = data.get("team_ai_ids", {})
        player_name: str = data.get("player_name", "Unnamed Player")
        headless: bool = data.get("headless", False)
        save_debug_summary: bool = data.get("save_debug_summary", False)
        time_limit: int = data.get("time_limit", 0)  # minutes, 0 = no limit
        max_ticks = time_limit * 60 * 60 if time_limit > 0 else 0  # 60 ticks/sec

        # Build AI instances from registry
        team_ai = {}
        for team, ai_id in team_ai_ids.items():
            try:
                team_ai[team] = self._registry.create(ai_id)
            except KeyError:
                from systems.ai import WanderAI
                team_ai[team] = WanderAI()

        if not team_ai:
            from systems.ai import WanderAI
            team_ai = {2: WanderAI()}

        screen_w = self._screen.get_width()
        screen_h = self._screen.get_height()

        replay_config = {
            "team_ai_ids": team_ai_ids,
            "team_ai_names": {t: ai.ai_name for t, ai in team_ai.items()},
            "obstacle_count": list(obs),
            "player_name": player_name,
        }

        game = Game(
            width=width,
            height=height,
            map_generator=DefaultMapGenerator(obstacle_count=obs),
            team_ai=team_ai,
            screen=self._screen,
            clock=self._clock,
            replay_config=replay_config,
            player_name=player_name,
            headless=headless,
            max_ticks=max_ticks,
            save_debug_summary=save_debug_summary,
            screen_width=screen_w,
            screen_height=screen_h,
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
        })

    def _run_mp_host_game(self, data: dict) -> ScreenResult:
        """Run a multiplayer game as the authoritative host."""
        from game import Game
        from systems.map_generator import DefaultMapGenerator
        from networking.host import GameHost
        from systems.replay import RECORD_INTERVAL

        width = data.get("width", 800)
        height = data.get("height", 600)
        obs = data.get("obstacle_count", (4, 8))
        host_name = data.get("host_name", "Host")
        client_name = data.get("client_name", "Client")
        host_obj: GameHost = data["host"]

        screen_w = self._screen.get_width()
        screen_h = self._screen.get_height()

        replay_config = {
            "team_ai_ids": {},
            "team_ai_names": {1: host_name, 2: client_name},
            "obstacle_count": list(obs),
            "player_name": host_name,
        }

        # Create game with NO AI — both teams are human
        game = Game(
            width=width,
            height=height,
            map_generator=DefaultMapGenerator(obstacle_count=obs),
            team_ai={},  # both teams human
            screen=self._screen,
            clock=self._clock,
            replay_config=replay_config,
            player_name=host_name,
            screen_width=screen_w,
            screen_height=screen_h,
        )

        # Rebind the host's command queue to the game's actual queue
        host_obj._command_queue = game._command_queue
        host_obj._host_name = host_name

        # Send game_start to client
        host_obj.send_game_start(game.entities, width, height)

        # Override selectability: host only selects team 1
        for e in game.entities:
            if hasattr(e, "team") and hasattr(e, "selectable"):
                e.selectable = (e.team == 1)

        # Wrap the game's step to inject remote commands and broadcast state
        original_step = game.step

        def networked_step(dt: float) -> None:
            host_obj.inject_remote_commands()
            original_step(dt)
            host_obj.broadcast_state(
                game._iteration, game.entities,
                game.laser_flashes, game._winner,
            )

        game.step = networked_step  # type: ignore[method-assign]

        try:
            result = game.run()
        except Exception as exc:
            host_obj.stop()
            path = log_crash(exc, context="mp_host_game")
            print(f"[AIRTS] MP host game crashed — log saved to {path}")
            return ScreenResult("crash_notice",
                                data={"log_path": path, "context": "mp_host_game"})

        # Notify client of game over
        host_obj.send_game_over(result.get("winner", 0))
        import time
        time.sleep(0.5)  # brief delay for message to transmit
        host_obj.stop()

        return ScreenResult("results", data={
            "winner": result.get("winner", 0),
            "human_teams": result.get("human_teams", set()),
            "stats": result.get("stats"),
            "replay_filepath": result.get("replay_filepath"),
            "team_names": {1: host_name, 2: client_name},
        })

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
