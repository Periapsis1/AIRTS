"""Replay recording and playback system.

Records game state at regular intervals using keyframe + delta encoding,
then compresses the result as gzip JSON with the .rtsreplay extension.
"""
from __future__ import annotations
import gzip
import json
import os
from datetime import datetime
from typing import Any

from entities.base import Entity
from entities.unit import Unit
from entities.metal_spot import MetalSpot
from entities.laser import LaserFlash
from entities.shapes import RectEntity, CircleEntity

# How many game ticks between recorded frames (60 FPS game / 6 = ~10 FPS replay)
RECORD_INTERVAL = 6
# How many *recorded frames* between full keyframes
KEYFRAME_INTERVAL = 60

# Short type codes
_TYPE_CODE = {
    "Unit": "U",
    "CommandCenter": "CC",
    "MetalSpot": "MS",
    "MetalExtractor": "ME",
}


def _q1(v: float) -> float:
    """Quantise to 1 decimal place."""
    return round(v, 1)


def _q2(v: float) -> float:
    """Quantise to 2 decimal places."""
    return round(v, 2)


def _color_list(c: tuple) -> list[int]:
    return list(c[:3])


# ---------------------------------------------------------------------------
# Entity -> visual dict
# ---------------------------------------------------------------------------

def _entity_visual(e: Entity) -> dict | None:
    """Return a slim visual-only dict for a single entity, or None to skip."""
    if isinstance(e, Unit):
        d = {
            "id": e.entity_id,
            "t": _TYPE_CODE["Unit"],
            "x": _q1(e.x),
            "y": _q1(e.y),
            "c": _color_list(e._base_color),
            "r": e.radius,
            "tm": e.team,
            "hp": int(e.hp),
            "ut": e.unit_type,
        }
        # CC-specific replay fields
        if e.unit_type == "command_center":
            d["t"] = "CC"
            d["pts"] = [list(p) for p in e.points]
        # ME-specific replay fields
        elif e.unit_type == "metal_extractor":
            d["t"] = "ME"
            d["rot"] = _q2(e.rotation)
        else:
            # Non-building units: record facing angle for FOV arc rendering
            d["fa"] = _q2(e.facing_angle)
        if e.target is not None:
            d["tx"] = _q1(e.target[0])
            d["ty"] = _q1(e.target[1])
        if e.attack_target is not None and e.attack_target.alive:
            d["atx"] = _q1(e.attack_target.x)
            d["aty"] = _q1(e.attack_target.y)
        return d
    if isinstance(e, MetalSpot):
        return {
            "id": e.entity_id,
            "t": _TYPE_CODE["MetalSpot"],
            "x": _q1(e.x),
            "y": _q1(e.y),
            "r": e.radius,
            "ow": e.owner,
            "cp": _q2(e.capture_progress),
        }
    # Obstacles and other shapes are stored in map.obstacles, not frames
    return None


def _laser_visual(lf: LaserFlash) -> list:
    """Compact tuple representation of a laser flash."""
    return [
        _q1(lf.x1), _q1(lf.y1),
        _q1(lf.x2), _q1(lf.y2),
        _color_list(lf.color), lf.width,
    ]


def _obstacle_visual(e: Entity) -> dict | None:
    """Capture an obstacle entity for the static map section."""
    if isinstance(e, RectEntity) and e.obstacle:
        return {
            "shape": "rect",
            "x": _q1(e.x), "y": _q1(e.y),
            "w": _q1(e.width), "h": _q1(e.height),
            "c": _color_list(e.color),
        }
    if isinstance(e, CircleEntity) and e.obstacle:
        return {
            "shape": "circle",
            "x": _q1(e.x), "y": _q1(e.y),
            "r": _q1(e.radius),
            "c": _color_list(e.color),
        }
    return None


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def _compute_delta(prev: dict, cur: dict) -> dict | None:
    """Return only the keys that changed between two visual dicts.

    Always includes 'id' and 't' for identification.
    Returns None if nothing changed.
    """
    diff: dict[str, Any] = {}
    for k, v in cur.items():
        if k in ("id", "t"):
            continue
        if prev.get(k) != v:
            diff[k] = v
    return diff if diff else None


# ===================================================================
# ReplayRecorder
# ===================================================================

class ReplayRecorder:
    """Captures game frames for later replay."""

    def __init__(
        self,
        map_width: int,
        map_height: int,
        replay_config: dict | None = None,
    ):
        self._map_width = map_width
        self._map_height = map_height
        self._config = replay_config or {}

        self._frames: list[dict] = []
        self._frame_index = 0  # counts recorded frames (not game ticks)
        self._prev_snapshot: dict[int, dict] = {}  # entity_id -> visual dict
        self._obstacles: list[dict] | None = None
        self._start_tick: int | None = None
        self._last_tick: int = 0

    # -- public API ---------------------------------------------------------

    def capture_tick(
        self,
        tick: int,
        entities: list[Entity],
        laser_flashes: list[LaserFlash],
    ):
        """Called every game tick.  Only records at RECORD_INTERVAL intervals."""
        if tick % RECORD_INTERVAL != 0:
            return

        if self._start_tick is None:
            self._start_tick = tick
        self._last_tick = tick

        # One-time obstacle capture
        if self._obstacles is None:
            self._obstacles = []
            for e in entities:
                od = _obstacle_visual(e)
                if od is not None:
                    self._obstacles.append(od)

        # Build current snapshot
        cur_snapshot: dict[int, dict] = {}
        entity_visuals: list[dict] = []
        for e in entities:
            vd = _entity_visual(e)
            if vd is not None:
                cur_snapshot[vd["id"]] = vd
                entity_visuals.append(vd)

        # Laser flashes (always recorded in full — they're transient)
        lf_list = [_laser_visual(lf) for lf in laser_flashes]

        is_keyframe = (self._frame_index % KEYFRAME_INTERVAL == 0)

        if is_keyframe:
            frame: dict[str, Any] = {
                "k": True,
                "tick": tick,
                "e": entity_visuals,
            }
            if lf_list:
                frame["lf"] = lf_list
        else:
            # Delta frame
            deltas: dict[str, dict] = {}
            added: list[dict] = []
            removed: list[int] = []

            prev_ids = set(self._prev_snapshot.keys())
            cur_ids = set(cur_snapshot.keys())

            # Removed entities
            for eid in prev_ids - cur_ids:
                removed.append(eid)

            # Added entities (full dict)
            for eid in cur_ids - prev_ids:
                added.append(cur_snapshot[eid])

            # Changed entities (delta only)
            for eid in prev_ids & cur_ids:
                d = _compute_delta(self._prev_snapshot[eid], cur_snapshot[eid])
                if d is not None:
                    deltas[str(eid)] = d

            frame = {"tick": tick}
            if deltas:
                frame["d"] = deltas
            if added:
                frame["a"] = added
            if removed:
                frame["r"] = removed
            if lf_list:
                frame["lf"] = lf_list

        self._frames.append(frame)
        self._prev_snapshot = cur_snapshot
        self._frame_index += 1

    def save(
        self,
        winner: int,
        human_teams: set[int],
        stats: dict | None = None,
    ) -> str:
        """Serialise and write replay to replays/ directory. Returns filepath."""
        start = self._start_tick or 0
        duration_ticks = self._last_tick - start
        duration_seconds = round(duration_ticks / 60.0, 2)

        data = {
            "version": 1,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "duration_ticks": duration_ticks,
            "duration_seconds": duration_seconds,
            "map": {
                "width": self._map_width,
                "height": self._map_height,
                "obstacles": self._obstacles or [],
            },
            "config": self._config,
            "winner": winner,
            "human_teams": sorted(human_teams),
            "keyframe_interval": KEYFRAME_INTERVAL,
            "record_interval": RECORD_INTERVAL,
        }
        if stats is not None:
            data["stats"] = stats
        data["frames"] = self._frames

        os.makedirs("replays", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"replay_{ts}.rtsreplay"
        filepath = os.path.join("replays", filename)

        raw = json.dumps(data, separators=(",", ":"))
        with gzip.open(filepath, "wt", encoding="utf-8", compresslevel=9) as f:
            f.write(raw)

        return filepath


# ===================================================================
# ReplayReader
# ===================================================================

class ReplayReader:
    """Loads and navigates a .rtsreplay file."""

    def __init__(self, filepath: str):
        with gzip.open(filepath, "rt", encoding="utf-8") as f:
            self._data: dict = json.load(f)

        self._frames: list[dict] = self._data["frames"]
        self._index: int = 0
        self._state: dict[int, dict] = {}  # entity_id -> visual dict
        self._laser_flashes: list[list] = []

        # Build initial state from first frame (which must be a keyframe)
        if self._frames:
            self._apply_frame(0)

    # -- metadata -----------------------------------------------------------

    @property
    def version(self) -> int:
        return self._data.get("version", 1)

    @property
    def timestamp(self) -> str:
        return self._data.get("timestamp", "")

    @property
    def duration_ticks(self) -> int:
        return self._data.get("duration_ticks", 0)

    @property
    def duration_seconds(self) -> float:
        return self._data.get("duration_seconds", 0.0)

    @property
    def map_width(self) -> int:
        return self._data["map"]["width"]

    @property
    def map_height(self) -> int:
        return self._data["map"]["height"]

    @property
    def obstacles(self) -> list[dict]:
        return self._data["map"].get("obstacles", [])

    @property
    def winner(self) -> int:
        return self._data.get("winner", 0)

    @property
    def human_teams(self) -> list[int]:
        return self._data.get("human_teams", [])

    @property
    def config(self) -> dict:
        return self._data.get("config", {})

    @property
    def stats_data(self) -> dict | None:
        """Return embedded stats dict, or None for old replays without stats."""
        return self._data.get("stats")

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_tick(self) -> int:
        if 0 <= self._index < len(self._frames):
            return self._frames[self._index].get("tick", 0)
        return 0

    # -- navigation ---------------------------------------------------------

    def _apply_frame(self, index: int):
        """Apply a single frame to current state."""
        frame = self._frames[index]
        self._laser_flashes = frame.get("lf", [])

        if frame.get("k"):
            # Keyframe — full snapshot replaces state
            self._state = {}
            for ent in frame["e"]:
                self._state[ent["id"]] = dict(ent)
        else:
            # Delta frame
            # Removed entities
            for eid in frame.get("r", []):
                self._state.pop(eid, None)

            # Added entities
            for ent in frame.get("a", []):
                self._state[ent["id"]] = dict(ent)

            # Changed fields
            for eid_str, delta in frame.get("d", {}).items():
                eid = int(eid_str)
                if eid in self._state:
                    self._state[eid].update(delta)

    def seek_to_frame(self, index: int):
        """Reconstruct state at a given frame index from the nearest keyframe."""
        index = max(0, min(index, len(self._frames) - 1))

        # Find the nearest keyframe at or before `index`
        kf = index
        while kf > 0 and not self._frames[kf].get("k"):
            kf -= 1

        # Rebuild from keyframe
        self._state = {}
        self._laser_flashes = []
        for i in range(kf, index + 1):
            self._apply_frame(i)
        self._index = index

    def advance(self) -> bool:
        """Step forward one frame. Returns False if at end."""
        if self._index + 1 >= len(self._frames):
            return False
        self._index += 1
        self._apply_frame(self._index)
        return True

    def get_state(self) -> tuple[list[dict], list[list]]:
        """Return (entities_list, laser_flashes) for the current frame."""
        return list(self._state.values()), list(self._laser_flashes)

    # -- static helpers -----------------------------------------------------

    @staticmethod
    def list_replays_iter(directory: str = "replays"):
        """Yield replay metadata dicts one at a time (newest first)."""
        if not os.path.isdir(directory):
            return

        for fname in sorted(os.listdir(directory), reverse=True):
            if not fname.endswith(".rtsreplay"):
                continue
            fpath = os.path.join(directory, fname)
            try:
                with gzip.open(fpath, "rt", encoding="utf-8") as f:
                    raw = f.read(4096)  # read just enough for metadata
                data = json.loads(raw if raw.endswith("}") else raw + "}")
            except (json.JSONDecodeError, Exception):
                try:
                    with gzip.open(fpath, "rt", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue

            yield {
                "filepath": fpath,
                "filename": fname,
                "timestamp": data.get("timestamp", ""),
                "duration_seconds": data.get("duration_seconds", 0),
                "winner": data.get("winner", 0),
                "map_width": data.get("map", {}).get("width", 0),
                "map_height": data.get("map", {}).get("height", 0),
                "file_size": os.path.getsize(fpath),
                "config": data.get("config", {}),
                "human_teams": data.get("human_teams", []),
            }

    @staticmethod
    def list_replays(directory: str = "replays") -> list[dict]:
        """Scan the replays directory and return metadata for each file."""
        return list(ReplayReader.list_replays_iter(directory))

    @staticmethod
    def delete_replay(filepath: str):
        """Delete a replay file."""
        if os.path.isfile(filepath):
            os.remove(filepath)
