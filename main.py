"""Entry point for AIRTS."""
from __future__ import annotations
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="AIRTS — AI Real-Time Strategy")
    parser.add_argument("--headless", action="store_true",
                        help="Run in headless mode (AI vs AI, no rendering, auto-exit)")
    parser.add_argument("--team1", type=str, default=None,
                        help="AI id for team 1 (e.g. 'wander') — 1v1 shorthand")
    parser.add_argument("--team2", type=str, default=None,
                        help="AI id for team 2 (e.g. 'wander') — 1v1 shorthand")
    parser.add_argument("--teams", type=str, default=None,
                        help="Comma-separated AI ids for FFA (e.g. 'wander,easy,hard')")
    parser.add_argument("--player", action="append", default=None,
                        help="Player spec: 'pid:team:ai_id' (repeatable)")
    parser.add_argument("--width", type=int, default=800,
                        help="Map width (default: 800)")
    parser.add_argument("--height", type=int, default=600,
                        help="Map height (default: 600)")
    parser.add_argument("--obs-min", type=int, default=4,
                        help="Minimum obstacles (default: 4)")
    parser.add_argument("--obs-max", type=int, default=8,
                        help="Maximum obstacles (default: 8)")
    parser.add_argument("--time-limit", type=int, default=15,
                        help="Time limit in minutes, 0 for no limit (default: 15)")
    parser.add_argument("--list-ais", action="store_true",
                        help="List available AI ids and exit")
    parser.add_argument("--server", action="store_true",
                        help="Run as a dedicated server (headless, 2 remote clients)")
    parser.add_argument("--port", type=int, default=7777,
                        help="Server port (default: 7777)")
    parser.add_argument("--ws-port", type=int, default=7778,
                        help="WebSocket port for browser clients, 0 to disable (default: 7778)")
    parser.add_argument("--enable-t2", action="store_true",
                        help="Enable T2 units")

    args = parser.parse_args()

    if args.list_ais:
        from systems.ai import AIRegistry
        registry = AIRegistry()
        registry.discover()
        choices = registry.get_choices()
        if not choices:
            print("No AIs found.")
        else:
            for ai_id, ai_name in choices:
                print(f"  {ai_id:20s}  {ai_name}")
        sys.exit(0)

    if args.server:
        _run_server(args)
    elif args.headless:
        _run_headless(args)
    else:
        from app import App
        try:
            App().run()
        except Exception as exc:
            from systems.crash_handler import log_crash
            path = log_crash(exc, context="fatal")
            print(f"[AIRTS] Fatal crash — log saved to {path}")


def _run_server(args):
    """Run as a dedicated server — lobby-based, accepts remote clients."""
    import os
    os.environ["SDL_VIDEODRIVER"] = "dummy"

    import pygame
    pygame.init()
    # Dummy display for pygame internals that need it
    pygame.display.set_mode((1, 1))

    from networking.server import DedicatedServer

    max_ticks = args.time_limit * 60 * 60 if args.time_limit > 0 else 0

    server = DedicatedServer(
        port=args.port,
        max_ticks_default=max_ticks,
        enable_t2_default=args.enable_t2,
        ws_port=(args.ws_port or None),
    )

    try:
        server.run()  # loops lobby → game → lobby
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
    except Exception as exc:
        from systems.crash_handler import log_crash
        path = log_crash(exc, context="server")
        print(f"[Server] Crashed — log saved to {path}")
        sys.exit(1)

    pygame.quit()
    sys.exit(0)


def _run_headless(args):
    """Run a headless AI-vs-AI game directly, then exit."""
    import pygame
    from systems.ai import AIRegistry
    from systems.map_generator import DefaultMapGenerator
    from game import Game

    registry = AIRegistry()
    registry.discover()
    choices = registry.get_choices()
    valid_ids = {c[0] for c in choices}

    # Build player_ai and player_team from args
    player_ai = {}
    player_team = {}

    if args.player:
        # Explicit --player pid:team:ai_id specs
        for spec in args.player:
            parts = spec.split(":")
            if len(parts) != 3:
                print(f"[AIRTS] Invalid --player spec '{spec}'. Format: pid:team:ai_id")
                sys.exit(1)
            pid, tid, ai_id = int(parts[0]), int(parts[1]), parts[2]
            if ai_id not in valid_ids:
                print(f"[AIRTS] Unknown AI '{ai_id}'. Use --list-ais to see options.")
                sys.exit(1)
            player_ai[pid] = registry.create(ai_id)
            player_team[pid] = tid
    elif args.teams:
        # FFA shorthand: --teams "wander,easy,hard"
        ai_list = [s.strip() for s in args.teams.split(",") if s.strip()]
        for i, ai_id in enumerate(ai_list):
            if ai_id not in valid_ids:
                print(f"[AIRTS] Unknown AI '{ai_id}'. Use --list-ais to see options.")
                sys.exit(1)
            pid = i + 1
            player_ai[pid] = registry.create(ai_id)
            player_team[pid] = pid  # each player on own team (FFA)
    else:
        # Legacy --team1/--team2 (1v1)
        ai_ids_list = [c[0] for c in choices]
        t1_id = args.team1 or (ai_ids_list[0] if ai_ids_list else "wander")
        t2_id = args.team2 or (ai_ids_list[0] if ai_ids_list else "wander")
        for label, ai_id in [("team1", t1_id), ("team2", t2_id)]:
            if ai_id not in valid_ids:
                print(f"[AIRTS] Unknown AI '{ai_id}' for {label}. Use --list-ais to see options.")
                sys.exit(1)
        player_ai = {1: registry.create(t1_id), 2: registry.create(t2_id)}
        player_team = {1: 1, 2: 2}

    obs = (args.obs_min, args.obs_max)
    max_ticks = args.time_limit * 60 * 60 if args.time_limit > 0 else 0

    pygame.init()
    pygame.mixer.init()
    screen = pygame.display.set_mode((args.width, args.height))
    pygame.display.set_caption("AIRTS — Headless")
    clock = pygame.time.Clock()

    # Build replay config
    ai_ids_map = {}
    ai_names_map = {}
    for pid, ai in player_ai.items():
        ai_ids_map[pid] = ai.ai_id
        ai_names_map[pid] = ai.ai_name

    replay_config = {
        "player_ai_ids": ai_ids_map,
        "player_ai_names": ai_names_map,
        "player_team": player_team,
        "obstacle_count": list(obs),
        "player_name": "Headless",
    }

    game = Game(
        width=args.width,
        height=args.height,
        map_generator=DefaultMapGenerator(obstacle_count=obs),
        player_ai=player_ai,
        player_team=player_team,
        screen=screen,
        clock=clock,
        replay_config=replay_config,
        player_name="Headless",
        headless=True,
        max_ticks=max_ticks,
    )

    try:
        result = game.run()
    except Exception as exc:
        from systems.crash_handler import log_crash
        path = log_crash(exc, context="headless")
        print(f"[AIRTS] Headless game crashed — log saved to {path}")
        sys.exit(1)

    winner = result.get("winner", 0)
    team_names = result.get("team_names", {})
    if winner > 0:
        print(f"[AIRTS] Winner: Team {winner} ({team_names.get(winner, '?')})")
    elif winner == -1:
        print("[AIRTS] Result: Draw")
    else:
        print("[AIRTS] Result: Undecided")

    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
