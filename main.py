"""Entry point for AIRTS."""
from game import Game
from systems.map_generator import DefaultMapGenerator
from systems.ai import WanderAI


def main():
    game = Game(
        width=800,
        height=600,
        title="AIRTS",
        map_generator=DefaultMapGenerator(),
        # Human (team 1) vs AI (team 2):
        team_ai={2: WanderAI()},
        # AI vs AI (spectator mode):
        # team_ai={1: WanderAI(), 2: WanderAI()},
    )
    game.run()


if __name__ == "__main__":
    main()
