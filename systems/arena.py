"""AI Arena — Elo-rated round-robin tournament system.

Runs headless games in parallel via ProcessPoolExecutor and tracks
Elo ratings in ai_arena/arena_ratings.json.  Error logs and tournament
summaries are written to ai_arena/logs/.
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
    error_log_path: str = ""
    match_index: int = -1


@dataclass
class TournamentProgress:
    total: int = 0
    completed: int = 0
    results: list[MatchResult] = field(default_factory=list)
    pending_matchups: list[tuple[str, str]] = field(default_factory=list)
    done: bool = False
    matchups: list[tuple[str, str]] = field(default_factory=list)
    active_match_indices: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Elo Tracker
# ---------------------------------------------------------------------------

_ARENA_DIR = "ai_arena"
_RATINGS_PATH = os.path.join(_ARENA_DIR, "arena_ratings.json")
_REPLAYS_DIR = os.path.join(_ARENA_DIR, "replays")
_LOGS_DIR = os.path.join(_ARENA_DIR, "logs")
_K = 32


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _write_error_log(
    ai1_id: str, ai2_id: str, error_msg: str, tb: str,
) -> str:
    """Write an error log for a failed match. Returns the filepath."""
    os.makedirs(_LOGS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"error_{ai1_id}_vs_{ai2_id}_{ts}.log"
    filepath = os.path.join(_LOGS_DIR, filename)
    lines = [
        "AIRTS Arena Match Error",
        f"Time: {datetime.now().isoformat(timespec='seconds')}",
        f"Match: {ai1_id} vs {ai2_id}",
        "=" * 60,
        error_msg.rstrip(),
        "",
        "Traceback:",
        tb.rstrip(),
    ]
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return filepath


def write_tournament_summary(
    results: list[MatchResult],
    elo_tracker: EloTracker,
    pre_ratings: dict[str, float],
    ai_names: dict[str, str],
    start_time: float,
) -> str:
    """Write a tournament summary log. Returns the filepath."""
    import time as _time
    os.makedirs(_LOGS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(_LOGS_DIR, f"tournament_result_{ts}.log")

    elapsed = _time.time() - start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60

    errors = sum(1 for r in results if r.winner == 0)
    lines: list[str] = [
        "AIRTS Arena Tournament Summary",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Duration: {mins}m {secs}s",
        f"Total matches: {len(results)} ({errors} errors)",
        "",
        "=" * 60,
        "Final Elo Ratings (with deltas)",
        "=" * 60,
    ]

    for ai_id, record in elo_tracker.get_leaderboard():
        name = ai_names.get(ai_id, ai_id)
        old = pre_ratings.get(ai_id, 1000.0)
        delta = record.rating - old
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"  {name:<20s}  Elo: {record.rating:7.1f}  ({sign}{delta:.1f})  "
            f"W:{record.wins} L:{record.losses} D:{record.draws}"
        )

    lines.append("")
    lines.append("=" * 60)
    lines.append("Per-Match Results")
    lines.append("=" * 60)
    for i, r in enumerate(results, 1):
        n1 = ai_names.get(r.ai1_id, r.ai1_id)
        n2 = ai_names.get(r.ai2_id, r.ai2_id)
        if r.winner == 1:
            outcome = f"{n1} wins"
        elif r.winner == 2:
            outcome = f"{n2} wins"
        elif r.winner == -1:
            outcome = "Draw"
        else:
            outcome = "Error"
        secs_game = r.ticks / 60.0
        m = int(secs_game) // 60
        s = int(secs_game) % 60
        lines.append(f"  {i:3d}. {n1} vs {n2}  ->  {outcome}  ({m}:{s:02d})")

    # Per-bot summary
    bot_stats: dict[str, dict[str, int]] = {}
    for r in results:
        for aid in (r.ai1_id, r.ai2_id):
            if aid not in bot_stats:
                bot_stats[aid] = {"wins": 0, "losses": 0, "draws": 0, "errors": 0}
        if r.winner == 0:
            bot_stats[r.ai1_id]["errors"] += 1
            bot_stats[r.ai2_id]["errors"] += 1
        elif r.winner == 1:
            bot_stats[r.ai1_id]["wins"] += 1
            bot_stats[r.ai2_id]["losses"] += 1
        elif r.winner == 2:
            bot_stats[r.ai2_id]["wins"] += 1
            bot_stats[r.ai1_id]["losses"] += 1
        else:
            bot_stats[r.ai1_id]["draws"] += 1
            bot_stats[r.ai2_id]["draws"] += 1

    lines.append("")
    lines.append("=" * 60)
    lines.append("Per-Bot Summary (this tournament)")
    lines.append("=" * 60)
    for aid, s in sorted(bot_stats.items()):
        name = ai_names.get(aid, aid)
        total = s["wins"] + s["losses"] + s["draws"] + s["errors"]
        lines.append(
            f"  {name:<20s}  W:{s['wins']} L:{s['losses']} D:{s['draws']} "
            f"E:{s['errors']}  Total:{total}"
        )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return filepath


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
    match_index: int,
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
    _pg.display.set_mode((1, 1))

    try:
        from systems.ai import AIRegistry
        from systems.map_generator import DefaultMapGenerator
        from game import Game

        registry = AIRegistry()
        registry.discover()

        # Retry once if either bot failed to register (transient import errors)
        needed = {ai1_id, ai2_id}
        registered = {aid for aid, _ in registry.get_choices()}
        if not needed.issubset(registered):
            import time as _time
            _time.sleep(0.1)
            registry = AIRegistry()
            registry.discover()

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

        avg_step_ms = 0.0
        stats = result.get("stats")
        if stats and stats.get("step_ms"):
            step_ms_list = stats["step_ms"]
            avg_step_ms = sum(step_ms_list) / len(step_ms_list)

        return MatchResult(ai1_id, ai2_id, winner=winner, ticks=ticks,
                           avg_step_ms=avg_step_ms, replay_path=replay_path,
                           match_index=match_index)

    except Exception as exc:
        tb = traceback.format_exc()
        error_log = _write_error_log(ai1_id, ai2_id, str(exc), tb)
        return MatchResult(ai1_id, ai2_id, winner=0, error=str(exc),
                           error_traceback=tb, error_log_path=error_log,
                           match_index=match_index)

    finally:
        _pg.quit()


# ---------------------------------------------------------------------------
# Arena Runner
# ---------------------------------------------------------------------------

def _distribute_matchups(
    matchups: list[tuple[str, str, int]], n_workers: int,
) -> list[list[tuple[str, str, int]]]:
    """Greedy bot-aware assignment of matchups to worker queues.

    Each entry is (ai1_id, ai2_id, match_index).  Assigns each matchup to
    the worker whose queue has the fewest matches involving either bot,
    tiebreak by shortest queue.
    """
    queues: list[list[tuple[str, str, int]]] = [[] for _ in range(n_workers)]
    # Per-worker bot counts for fast lookup
    bot_counts: list[dict[str, int]] = [{} for _ in range(n_workers)]

    for ai1, ai2, idx in matchups:
        best_w = 0
        best_score = (float("inf"), float("inf"))
        for w in range(n_workers):
            overlap = bot_counts[w].get(ai1, 0) + bot_counts[w].get(ai2, 0)
            score = (overlap, len(queues[w]))
            if score < best_score:
                best_score = score
                best_w = w
        queues[best_w].append((ai1, ai2, idx))
        bot_counts[best_w][ai1] = bot_counts[best_w].get(ai1, 0) + 1
        bot_counts[best_w][ai2] = bot_counts[best_w].get(ai2, 0) + 1

    return queues


class ArenaRunner:
    """Orchestrates a round-robin tournament using a process pool with
    slot-based submission (one match per worker at a time)."""

    def __init__(self):
        self._executor: ProcessPoolExecutor | None = None
        self._results: list[MatchResult] = []
        self._total: int = 0
        self._running: bool = False
        self._matchups: list[tuple[str, str]] = []

        # Slot-based state
        self._worker_queues: list[list[tuple[str, str, int]]] = []
        self._active_futures: dict[int, tuple[Future, int]] = {}  # slot -> (future, match_index)
        self._n_workers: int = 0

        # Game params stored for _submit_next
        self._map_width: int = 800
        self._map_height: int = 600
        self._obstacle_count: tuple[int, int] = (4, 8)
        self._max_ticks: int = 54000

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
        max_ticks: int = 54000,
    ) -> None:
        """Generate round-robin matchups, distribute to worker queues, start."""
        if self._running:
            return

        # Build matchup list: each pair plays both sides × rounds
        matchups: list[tuple[str, str]] = []
        for i, a in enumerate(ai_ids):
            for b in ai_ids[i + 1:]:
                for _ in range(rounds):
                    matchups.append((a, b))
                    matchups.append((b, a))

        self._matchups = matchups
        self._total = len(matchups)
        self._results = []
        self._running = True
        self._n_workers = min(workers, self._total)

        # Store game params
        self._map_width = map_width
        self._map_height = map_height
        self._obstacle_count = obstacle_count
        self._max_ticks = max_ticks

        # Distribute into per-worker queues
        indexed = [(a, b, idx) for idx, (a, b) in enumerate(matchups)]
        self._worker_queues = _distribute_matchups(indexed, self._n_workers)
        self._active_futures = {}

        self._executor = ProcessPoolExecutor(max_workers=self._n_workers)
        for slot in range(self._n_workers):
            self._submit_next(slot)

    def _submit_next(self, slot: int) -> None:
        """Pop next matchup from this worker's queue and submit it."""
        if not self._worker_queues[slot]:
            return
        ai1, ai2, match_index = self._worker_queues[slot].pop(0)
        fut = self._executor.submit(
            _run_arena_game, ai1, ai2, match_index,
            self._map_width, self._map_height,
            self._obstacle_count, self._max_ticks,
        )
        self._active_futures[slot] = (fut, match_index)

    def poll(self) -> TournamentProgress:
        """Non-blocking progress check. Call each frame."""
        if not self._running:
            return TournamentProgress(
                done=True, results=self._results,
                total=self._total, completed=len(self._results),
                matchups=self._matchups,
            )

        # Check active futures for completion
        completed_slots: list[int] = []
        for slot, (fut, match_index) in list(self._active_futures.items()):
            if fut.done():
                try:
                    result = fut.result()
                except Exception as exc:
                    ai1, ai2 = self._matchups[match_index]
                    result = MatchResult(ai1, ai2, winner=0, error=str(exc),
                                         match_index=match_index)
                self._results.append(result)
                completed_slots.append(slot)

        # Chain next matches for completed slots
        for slot in completed_slots:
            del self._active_futures[slot]
            self._submit_next(slot)

        # Done when all queues empty and no active futures
        done = (not self._active_futures and
                all(len(q) == 0 for q in self._worker_queues))
        if done:
            self._running = False
            if self._executor is not None:
                self._executor.shutdown(wait=False)
                self._executor = None

        active_indices = [mi for _, mi in self._active_futures.values()]

        return TournamentProgress(
            total=self._total,
            completed=len(self._results),
            results=list(self._results),
            done=done,
            matchups=self._matchups,
            active_match_indices=active_indices,
        )

    def cancel(self) -> None:
        """Cancel remaining futures and shut down."""
        for fut, _ in self._active_futures.values():
            fut.cancel()
        self._active_futures.clear()
        self._worker_queues = []
        self._running = False
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
