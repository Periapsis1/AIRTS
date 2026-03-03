"""AI Arena — Elo-rated round-robin tournament system.

Runs headless games in parallel via ProcessPoolExecutor and tracks
Elo ratings in ai_arena/arena_ratings.json.  Per-bot match and error
logs are written to ai_arena/bots/{ai_id}/logs/.
"""
from __future__ import annotations

import json
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AIRecord:
    rating: float = 1000.0
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.draws

    def to_dict(self) -> dict:
        return {"rating": self.rating, "wins": self.wins,
                "losses": self.losses, "draws": self.draws}

    @classmethod
    def from_dict(cls, d: dict) -> AIRecord:
        return cls(rating=d.get("rating", 1000.0),
                   wins=d.get("wins", 0),
                   losses=d.get("losses", 0),
                   draws=d.get("draws", 0))


@dataclass
class MatchResult:
    ai1_id: str
    ai2_id: str
    winner: int  # 1 = ai1 won, 2 = ai2 won, -1 = draw, 0 = error
    ticks: int = 0
    avg_step_ms: float = 0.0
    replay_path: str = ""
    error: str = ""
    error_traceback: str = ""


@dataclass
class TournamentProgress:
    total: int = 0
    completed: int = 0
    results: list[MatchResult] = field(default_factory=list)
    pending_matchups: list[tuple[str, str]] = field(default_factory=list)
    done: bool = False


# ---------------------------------------------------------------------------
# Elo Tracker
# ---------------------------------------------------------------------------

_ARENA_DIR = "ai_arena"
_RATINGS_PATH = os.path.join(_ARENA_DIR, "arena_ratings.json")
_REPLAYS_DIR = os.path.join(_ARENA_DIR, "replays")
_BOTS_DIR = os.path.join(_ARENA_DIR, "bots")
_K = 32


# ---------------------------------------------------------------------------
# Per-bot logging helpers
# ---------------------------------------------------------------------------

def _bot_log_dir(ai_id: str) -> str:
    """Return (and create) the logs directory for a bot."""
    d = os.path.join(_BOTS_DIR, ai_id, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _write_bot_log(
    ai_id: str,
    ai_name: str,
    opponent_id: str,
    opponent_name: str,
    *,
    winner: int,
    bot_team: int,
    ticks: int = 0,
    avg_step_ms: float = 0.0,
    replay_path: str = "",
    error_traceback: str = "",
) -> None:
    """Write a per-match log file into the bot's logs folder.

    *winner*: 1 = team-1 won, 2 = team-2 won, -1 = draw, 0 = error.
    *bot_team*: 1 or 2 — which team this bot was on.
    """
    now = datetime.now()
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_iso = now.isoformat(timespec="seconds")

    if winner == 0:
        outcome = "error"
    elif winner == bot_team:
        outcome = "win"
    elif winner == -1:
        outcome = "draw"
    else:
        outcome = "loss"

    filename = f"{ts_file}_vs_{opponent_id}_{outcome}.log"
    log_dir = _bot_log_dir(ai_id)
    filepath = os.path.join(log_dir, filename)

    lines: list[str] = ["AIRTS Arena Match Log"]
    lines.append(f"Time: {ts_iso}")
    lines.append(f"Bot: {ai_name} ({ai_id})")
    lines.append(f"Opponent: {opponent_name} ({opponent_id})")

    if winner == 0:
        lines.append("Result: Error")
        if error_traceback:
            lines.append("=" * 60)
            lines.append(error_traceback.rstrip())
    else:
        lines.append(f"Result: {outcome.capitalize()}")
        seconds = ticks / 60.0
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        lines.append(f"Ticks: {ticks} ({mins}:{secs:02d})")
        lines.append(f"Avg Step: {avg_step_ms:.1f}ms")
        if replay_path:
            lines.append(f"Replay: {replay_path}")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_discovery_error_log(bot_id: str, error_msg: str) -> None:
    """Write an initialization/discovery error log for a bot."""
    now = datetime.now()
    ts_file = now.strftime("%Y-%m-%d_%H-%M-%S")
    ts_iso = now.isoformat(timespec="seconds")

    filename = f"{ts_file}_discovery_error.log"
    log_dir = _bot_log_dir(bot_id)
    filepath = os.path.join(log_dir, filename)

    lines = [
        "AIRTS Arena Bot Error",
        f"Time: {ts_iso}",
        f"Bot: {bot_id}",
        "Context: AI discovery",
        "=" * 60,
        error_msg.rstrip(),
    ]
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class EloTracker:
    """Manages Elo ratings with JSON persistence."""

    def __init__(self):
        self.records: dict[str, AIRecord] = {}

    def load(self) -> None:
        if os.path.isfile(_RATINGS_PATH):
            try:
                with open(_RATINGS_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self.records = {k: AIRecord.from_dict(v)
                                    for k, v in raw.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                self.records = {}

    def save(self) -> None:
        os.makedirs(_ARENA_DIR, exist_ok=True)
        with open(_RATINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({k: v.to_dict() for k, v in self.records.items()}, f, indent=2)

    def ensure(self, ai_id: str) -> None:
        if ai_id not in self.records:
            self.records[ai_id] = AIRecord()

    def update(self, ai_a: str, ai_b: str, winner: int) -> None:
        """Update ratings after a match.

        winner: 1 = ai_a won, 2 = ai_b won, -1 = draw.
        """
        self.ensure(ai_a)
        self.ensure(ai_b)
        ra = self.records[ai_a].rating
        rb = self.records[ai_b].rating

        ea = 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))
        eb = 1.0 - ea

        if winner == 1:
            sa, sb = 1.0, 0.0
            self.records[ai_a].wins += 1
            self.records[ai_b].losses += 1
        elif winner == 2:
            sa, sb = 0.0, 1.0
            self.records[ai_a].losses += 1
            self.records[ai_b].wins += 1
        else:
            sa, sb = 0.5, 0.5
            self.records[ai_a].draws += 1
            self.records[ai_b].draws += 1

        self.records[ai_a].rating = ra + _K * (sa - ea)
        self.records[ai_b].rating = rb + _K * (sb - eb)

    def reset(self) -> None:
        self.records.clear()
        if os.path.isfile(_RATINGS_PATH):
            os.remove(_RATINGS_PATH)

    def compute_delta(self, ai_a: str, ai_b: str, winner: int,
                       ratings_snapshot: dict[str, float] | None = None,
                       ) -> tuple[float, float]:
        """Compute Elo deltas without applying them. Returns (delta_a, delta_b)."""
        if ratings_snapshot:
            ra = ratings_snapshot.get(ai_a, 1000.0)
            rb = ratings_snapshot.get(ai_b, 1000.0)
        else:
            self.ensure(ai_a)
            self.ensure(ai_b)
            ra = self.records[ai_a].rating
            rb = self.records[ai_b].rating

        ea = 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))
        eb = 1.0 - ea

        if winner == 1:
            sa, sb = 1.0, 0.0
        elif winner == 2:
            sa, sb = 0.0, 1.0
        else:
            sa, sb = 0.5, 0.5

        return (_K * (sa - ea), _K * (sb - eb))

    def get_leaderboard(self) -> list[tuple[str, AIRecord]]:
        return sorted(self.records.items(), key=lambda t: t[1].rating, reverse=True)


# ---------------------------------------------------------------------------
# Worker function (top-level, picklable)
# ---------------------------------------------------------------------------

def _run_arena_game(
    ai1_id: str,
    ai2_id: str,
    map_width: int,
    map_height: int,
    obstacle_count: tuple[int, int],
    max_ticks: int,
) -> MatchResult:
    """Run a single headless game in a worker process. Returns MatchResult."""
    import os as _os
    _os.environ["SDL_VIDEODRIVER"] = "dummy"

    import pygame as _pg
    _pg.init()
    # Dummy 1x1 display so SDL doesn't complain
    _pg.display.set_mode((1, 1))

    ai1_name = ai1_id
    ai2_name = ai2_id

    try:
        from systems.ai import AIRegistry
        from systems.map_generator import DefaultMapGenerator
        from game import Game

        registry = AIRegistry()
        registry.discover()

        # Log any AI discovery errors
        for err_msg in registry.errors:
            # Extract bot filename from error message (format: "filename.py: ...")
            colon_idx = err_msg.find(":")
            if colon_idx > 0:
                bot_file = err_msg[:colon_idx].replace(".py", "")
                _write_discovery_error_log(bot_file, err_msg)

        ai1 = registry.create(ai1_id)
        ai2 = registry.create(ai2_id)
        ai1_name = ai1.ai_name
        ai2_name = ai2.ai_name

        replay_config = {
            "team_ai_ids": {1: ai1_id, 2: ai2_id},
            "team_ai_names": {1: ai1_name, 2: ai2_name},
            "obstacle_count": list(obstacle_count),
            "player_name": "Arena",
        }

        game = Game(
            width=map_width,
            height=map_height,
            map_generator=DefaultMapGenerator(obstacle_count=obstacle_count),
            team_ai={1: ai1, 2: ai2},
            screen=_pg.display.get_surface(),
            clock=_pg.time.Clock(),
            replay_config=replay_config,
            headless=True,
            max_ticks=max_ticks,
            save_replay=True,
            step_timeout_ms=100,
            replay_output_dir=_REPLAYS_DIR,
        )

        result = game.run()
        winner = result.get("winner", 0)
        ticks = game._iteration
        replay_path = result.get("replay_filepath", "")

        # Rename replay with unique suffix to avoid collisions from parallel workers
        if replay_path and _os.path.exists(replay_path):
            import uuid
            base, ext = _os.path.splitext(replay_path)
            unique_path = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
            _os.rename(replay_path, unique_path)
            replay_path = unique_path

        # Compute average step time from stats
        avg_step_ms = 0.0
        stats = result.get("stats")
        if stats and stats.get("step_ms"):
            step_ms_list = stats["step_ms"]
            avg_step_ms = sum(step_ms_list) / len(step_ms_list)

        mr = MatchResult(ai1_id, ai2_id, winner=winner, ticks=ticks,
                         avg_step_ms=avg_step_ms, replay_path=replay_path)

        # Write per-bot match logs
        _write_bot_log(ai1_id, ai1_name, ai2_id, ai2_name,
                       winner=winner, bot_team=1, ticks=ticks,
                       avg_step_ms=avg_step_ms, replay_path=replay_path)
        _write_bot_log(ai2_id, ai2_name, ai1_id, ai1_name,
                       winner=winner, bot_team=2, ticks=ticks,
                       avg_step_ms=avg_step_ms, replay_path=replay_path)

        return mr

    except Exception as exc:
        tb = traceback.format_exc()
        mr = MatchResult(ai1_id, ai2_id, winner=0, error=str(exc),
                         error_traceback=tb)

        # Write error logs for both bots
        _write_bot_log(ai1_id, ai1_name, ai2_id, ai2_name,
                       winner=0, bot_team=1, error_traceback=tb)
        _write_bot_log(ai2_id, ai2_name, ai1_id, ai1_name,
                       winner=0, bot_team=2, error_traceback=tb)

        return mr

    finally:
        _pg.quit()


# ---------------------------------------------------------------------------
# Arena Runner
# ---------------------------------------------------------------------------

class ArenaRunner:
    """Orchestrates a round-robin tournament using a process pool."""

    def __init__(self):
        self._executor: ProcessPoolExecutor | None = None
        self._futures: list[tuple[Future, str, str]] = []  # (future, ai1, ai2)
        self._results: list[MatchResult] = []
        self._total: int = 0
        self._running: bool = False

    @property
    def running(self) -> bool:
        return self._running

    def start(
        self,
        ai_ids: list[str],
        rounds: int = 1,
        workers: int = 4,
        map_width: int = 800,
        map_height: int = 600,
        obstacle_count: tuple[int, int] = (4, 8),
        max_ticks: int = 72000,
    ) -> None:
        """Generate round-robin matchups and submit to process pool."""
        if self._running:
            return

        # Build matchup list: each pair plays both sides × rounds
        matchups: list[tuple[str, str]] = []
        for i, a in enumerate(ai_ids):
            for b in ai_ids[i + 1:]:
                for _ in range(rounds):
                    matchups.append((a, b))  # a as T1, b as T2
                    matchups.append((b, a))  # swap sides

        self._total = len(matchups)
        self._results = []
        self._futures = []
        self._running = True

        self._executor = ProcessPoolExecutor(max_workers=workers)
        for ai1, ai2 in matchups:
            fut = self._executor.submit(
                _run_arena_game, ai1, ai2,
                map_width, map_height, obstacle_count, max_ticks,
            )
            self._futures.append((fut, ai1, ai2))

    def poll(self) -> TournamentProgress:
        """Non-blocking progress check. Call each frame."""
        if not self._running:
            return TournamentProgress(done=True, results=self._results,
                                      total=self._total,
                                      completed=len(self._results))

        newly_done: list[tuple[Future, str, str]] = []
        for fut, ai1, ai2 in self._futures:
            if fut.done():
                try:
                    result = fut.result()
                except Exception as exc:
                    result = MatchResult(ai1, ai2, winner=0, error=str(exc))
                self._results.append(result)
                newly_done.append((fut, ai1, ai2))

        for item in newly_done:
            self._futures.remove(item)

        done = len(self._futures) == 0
        if done:
            self._running = False
            if self._executor is not None:
                self._executor.shutdown(wait=False)
                self._executor = None

        pending = [(ai1, ai2) for _, ai1, ai2 in self._futures]

        return TournamentProgress(
            total=self._total,
            completed=len(self._results),
            results=list(self._results),
            pending_matchups=pending,
            done=done,
        )

    def cancel(self) -> None:
        """Cancel remaining futures and shut down."""
        for fut, _, _ in self._futures:
            fut.cancel()
        self._futures.clear()
        self._running = False
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
