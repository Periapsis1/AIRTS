from __future__ import annotations
from config.settings import (
    METAL_SPOT_COLOR, METAL_SPOT_RADIUS, METAL_SPOT_CAPTURE_RATE, METAL_SPOT_CAPTURE_RADIUS, METAL_SPOT_CAPTURE_ARC_WIDTH, METAL_SPOT_CAPTURE_RANGE_COLOR,
    TEAM_COLORS,
)
from entities.shapes import CircleEntity
from entities.base import Damageable
import pygame
from datetime import datetime
import math

class MetalSpot(CircleEntity, Damageable):
    # Populated by Game after lobby player-colour selection is resolved, so
    # the owner circle and capture arcs match the CC/extractor triangle when
    # a player picks a non-default colour. Falls back to TEAM_COLORS.
    team_colors: dict[int, tuple] = {}

    def __init__(self, x: float = 0, y: float = 0):
        super().__init__(x, y, METAL_SPOT_RADIUS)
        self.color = METAL_SPOT_COLOR
        self.owner: int | None = None
        self.capture_progress: dict[int, float] = {}  # team_id -> 0.0..1.0
        self.no_decay: bool = False  # when True, neutral drift toward 0 is suppressed

    def update_progress(self, team_counts: dict[int, float], dt: float):
        """Update capture progress based on per-team unit presence.

        team_counts maps team_id -> weighted unit count near this spot.
        The team with strictly more presence than all others combined gains
        progress; all other teams' progress decays.
        """
        if self.owner is not None:
            return

        # Find dominant team (must have strict majority over all others combined)
        total = sum(team_counts.values())
        dominant_team = None
        dominant_count = 0.0
        for tid, count in team_counts.items():
            if count > 0 and count > dominant_count:
                dominant_count = count
                dominant_team = tid

        others_count = total - dominant_count
        has_majority = dominant_team is not None and dominant_count > others_count

        if has_majority:
            net = dominant_count - others_count
            gain = net * METAL_SPOT_CAPTURE_RATE * dt

            # First drain any existing progress from other teams
            for tid in list(self.capture_progress):
                if tid == dominant_team or gain <= 0:
                    continue
                old_val = self.capture_progress[tid]
                drain = min(old_val, gain)
                old_val -= drain
                gain -= drain
                if old_val <= 0.0:
                    del self.capture_progress[tid]
                else:
                    self.capture_progress[tid] = old_val

            # Remaining gain goes to the dominant team's progress
            if gain > 0:
                prog = self.capture_progress.get(dominant_team, 0.0)
                self.capture_progress[dominant_team] = min(1.0, prog + gain)

        # Decay non-dominant teams' progress (slow passive decay)
        for tid in list(self.capture_progress):
            if tid == dominant_team and has_majority:
                continue
            if self.no_decay and not has_majority:
                continue
            val = self.capture_progress[tid]
            val = max(0.0, val - 0.01 * dt)
            if val <= 0.0:
                del self.capture_progress[tid]
            else:
                self.capture_progress[tid] = val

    def claim(self, team: int):
        self.owner = team
        self.capture_progress = {}

    def release(self):
        self.owner = None

    def draw(self, surface: pygame.Surface):
        # draw the range circle on a temporary surface to respect alpha
        r = int(METAL_SPOT_CAPTURE_RADIUS)
        size = r * 2
        temp = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(temp, METAL_SPOT_CAPTURE_RANGE_COLOR, (r, r), r)
        surface.blit(temp, (int(self.x) - r, int(self.y) - r))

        # draw the base circle
        if self.owner is None:
            color = self.color
        else:
            color = self.team_colors.get(self.owner,
                                         TEAM_COLORS.get(self.owner, self.color))
        pygame.draw.circle(surface, color, self.center(), self.radius)

        if self.owner is not None:
            return

        # draw capture progress arcs (one per contesting team)
        if not self.capture_progress:
            return
        arc_r = METAL_SPOT_CAPTURE_RADIUS + METAL_SPOT_CAPTURE_ARC_WIDTH
        rect = pygame.Rect(int(self.x - arc_r), int(self.y - arc_r),
                           int(arc_r * 2), int(arc_r * 2))
        arc_w = int(METAL_SPOT_CAPTURE_ARC_WIDTH)
        teams_contesting = sorted(self.capture_progress.keys())
        n = len(teams_contesting)
        for i, tid in enumerate(teams_contesting):
            prog = self.capture_progress[tid]
            if abs(prog) < 0.01:
                continue
            tc = self.team_colors.get(tid, TEAM_COLORS.get(tid, (200, 200, 60)))
            # Each team's arc starts at an offset so they don't overlap
            base_angle = math.pi / 2 + (2 * math.pi * i / max(n, 1))
            end_angle = base_angle + prog * (2 * math.pi / max(n, 1))
            pygame.draw.arc(surface, tc, rect, base_angle, end_angle, arc_w)

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "owner": self.owner,
            "capture_progress": {str(tid): val for tid, val in self.capture_progress.items()},
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MetalSpot:
        ms = cls(data["x"], data["y"])
        ms.entity_id = data["entity_id"]
        ms.color = tuple(data["color"])
        ms.selected = data["selected"]
        ms.obstacle = data["obstacle"]
        ms.alive = data["alive"]
        ms.owner = data["owner"]
        raw_cp = data.get("capture_progress", {})
        if isinstance(raw_cp, dict):
            ms.capture_progress = {int(k): v for k, v in raw_cp.items()}
        elif isinstance(raw_cp, (int, float)):
            # Legacy format: float from -1.0 to 1.0
            if raw_cp >= 0 and raw_cp > 0.001:
                ms.capture_progress = {1: float(raw_cp)}
            elif raw_cp < -0.001:
                ms.capture_progress = {2: abs(float(raw_cp))}
            else:
                ms.capture_progress = {}
        else:
            ms.capture_progress = {}
        return ms
