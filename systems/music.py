"""Ambient music manager — shuffles tracks with random silence gaps.

Call ``init()`` once after ``pygame.mixer.init()``, then ``update()`` from
any frame loop.  The module keeps a single global instance so every screen
shares the same playback state.
"""
from __future__ import annotations

import os
import glob
import random
import time
import pygame

from core.paths import asset_path

_MUSIC_DIR = asset_path("sprites", "music")
_MAX_VOLUME = 0.15
_GAP_MIN = 5.0   # seconds of silence between tracks
_GAP_MAX = 15.0

_tracks: list[str] = []
_queue: list[str] = []
_gap_end: float = 0.0
_started: bool = False
_volume: float = 1.0  # 0.0–1.0 fraction of _MAX_VOLUME


def init() -> None:
    """Discover music files.  Safe to call more than once."""
    global _tracks, _queue
    if _tracks:
        return
    patterns = ("*.mp3", "*.ogg", "*.wav")
    for pat in patterns:
        _tracks.extend(glob.glob(os.path.join(_MUSIC_DIR, pat)))
    if _tracks:
        random.shuffle(_tracks)
        _queue = list(_tracks)


def update() -> None:
    """Call once per frame from any screen's main loop."""
    global _started, _gap_end, _queue
    if not _tracks:
        return
    if pygame.mixer.music.get_busy():
        return

    now = time.time()
    if not _started:
        _started = True
        _play_next()
        return

    if _gap_end == 0.0:
        _gap_end = now + random.uniform(_GAP_MIN, _GAP_MAX)
        return

    if now >= _gap_end:
        _gap_end = 0.0
        _play_next()


def set_volume(v: float) -> None:
    """Set music volume as a fraction 0.0–1.0 of the max."""
    global _volume
    _volume = max(0.0, min(1.0, v))
    if pygame.mixer.music.get_busy():
        pygame.mixer.music.set_volume(_MAX_VOLUME * _volume)


def get_volume() -> float:
    """Return current volume fraction (0.0–1.0)."""
    return _volume


def _play_next() -> None:
    global _queue
    if not _tracks:
        return
    if not _queue:
        _queue = list(_tracks)
        random.shuffle(_queue)
    track = _queue.pop()
    try:
        pygame.mixer.music.load(track)
        pygame.mixer.music.set_volume(_MAX_VOLUME * _volume)
        pygame.mixer.music.play()
    except Exception:
        pass
