"""Rolling per-subsystem frame-time tracker for the client render loop.

Companion to systems/stats.py (which tracks server-side subsystem timings for
the post-game analytics screen). ClientFrameStats is much lighter: it only
keeps a rolling window of recent samples so a debug HUD can show where the
client frame time is going.

Usage:

    stats = ClientFrameStats()
    with stats.scope("lasers"):
        draw_lasers(...)
    ms = stats.ms("lasers")       # rolling-mean ms
"""
from __future__ import annotations

from collections import deque
from time import perf_counter


class _Scope:
    __slots__ = ("_stats", "_name", "_start")

    def __init__(self, stats: "ClientFrameStats", name: str) -> None:
        self._stats = stats
        self._name = name
        self._start = 0.0

    def __enter__(self) -> "_Scope":
        self._start = perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        dur_ms = (perf_counter() - self._start) * 1000.0
        self._stats._record(self._name, dur_ms)


class ClientFrameStats:
    """Rolling-window timer for named phases of the client loop.

    Each phase keeps the last *window* samples; `ms(name)` returns the mean.
    `items()` yields phases in the order they were first recorded, so the
    HUD display is stable across frames.
    """

    def __init__(self, window: int = 60) -> None:
        self._window = window
        self._buffers: dict[str, deque[float]] = {}
        self._order: list[str] = []

    def scope(self, name: str) -> _Scope:
        return _Scope(self, name)

    def _record(self, name: str, dur_ms: float) -> None:
        buf = self._buffers.get(name)
        if buf is None:
            buf = deque(maxlen=self._window)
            self._buffers[name] = buf
            self._order.append(name)
        buf.append(dur_ms)

    def ms(self, name: str) -> float:
        buf = self._buffers.get(name)
        if not buf:
            return 0.0
        return sum(buf) / len(buf)

    def items(self) -> list[tuple[str, float]]:
        return [(n, self.ms(n)) for n in self._order]
