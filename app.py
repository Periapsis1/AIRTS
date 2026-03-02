"""Application controller — pygame lifecycle, screen routing."""
from __future__ import annotations
import pygame
from ui.theme import MENU_WIDTH, MENU_HEIGHT
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


class App:
    """Top-level application: initialises pygame once, routes between screens."""

    def __init__(self):
        pygame.init()
        self._screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))
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
                self._screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))
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

        # Resize display for game map dimensions
        game_screen = pygame.display.set_mode((width, height))

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
            screen=game_screen,
            clock=self._clock,
            replay_config=replay_config,
            player_name=player_name,
            headless=headless,
        )

        try:
            result = game.run()
        except Exception as exc:
            path = log_crash(exc, context="game")
            print(f"[AIRTS] Game crashed — log saved to {path}")
            self._screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))
            return ScreenResult("crash_notice",
                                data={"log_path": path, "context": "game"})

        # Restore menu display size
        self._screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))

        return ScreenResult("results", data={
            "winner": result.get("winner", 0),
            "human_teams": result.get("human_teams", set()),
            "stats": result.get("stats"),
            "replay_filepath": result.get("replay_filepath"),
            "team_names": result.get("team_names", {}),
        })

    def _run_replay_playback(self, data: dict) -> ScreenResult:
        from systems.replay import ReplayReader
        from screens.replay_playback import TOP_BAR_HEIGHT, BOTTOM_BAR_HEIGHT

        filepath = data.get("filepath", "")
        reader = ReplayReader(filepath)
        mw = reader.map_width
        mh = reader.map_height

        # Resize display for replay: top bar + map + bottom bar
        replay_screen = pygame.display.set_mode((mw, TOP_BAR_HEIGHT + mh + BOTTOM_BAR_HEIGHT))

        try:
            result = ReplayPlaybackScreen(replay_screen, self._clock, filepath).run()
        except Exception as exc:
            path = log_crash(exc, context="replay")
            print(f"[AIRTS] Replay crashed — log saved to {path}")
            self._screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))
            return ScreenResult("crash_notice",
                                data={"log_path": path, "context": "replay"})

        # Restore menu display size
        self._screen = pygame.display.set_mode((MENU_WIDTH, MENU_HEIGHT))

        return result
