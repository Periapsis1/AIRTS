"""Client-side transient visual effects (purely cosmetic)."""
from __future__ import annotations
import math
import random
import pygame

# Hard cap on simultaneous active bursts so massive battles can't blow out
# the particle list. Roughly MAX_DEATH_BURSTS * 8 circle blits per frame.
MAX_DEATH_BURSTS = 200


class DeathBurst:
    """Tiny particle shower at the location of a destroyed unit."""

    __slots__ = ("x", "y", "color", "ttl", "_init_ttl", "_particles")

    def __init__(self, x: float, y: float, color: tuple,
                 radius: float = 6.0, count: int = 8,
                 duration: float = 0.55):
        self.x = float(x)
        self.y = float(y)
        self.color = tuple(int(c) for c in color[:3])
        self._init_ttl = duration
        self.ttl = duration
        scale = max(0.5, radius / 6.0)
        # Each particle: [ox, oy, vx, vy, size]
        self._particles: list[list[float]] = []
        for _ in range(count):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(45.0, 95.0) * scale
            self._particles.append([
                0.0, 0.0,
                math.cos(angle) * speed,
                math.sin(angle) * speed,
                random.uniform(1.6, 3.0) * scale,
            ])

    @staticmethod
    def extend_from_events(active: list, events: list[dict]) -> None:
        """Append a DeathBurst per server-emitted event, in place.

        Trims *active* down to MAX_DEATH_BURSTS afterwards so callers don't
        need to repeat the cap logic.
        """
        for ev in events:
            active.append(DeathBurst(
                ev.get("x", 0),
                ev.get("y", 0),
                tuple(ev.get("c", (200, 200, 200))),
                float(ev.get("r", 6)),
            ))
        overflow = len(active) - MAX_DEATH_BURSTS
        if overflow > 0:
            del active[:overflow]

    def update(self, dt: float) -> bool:
        self.ttl -= dt
        damp = math.exp(-3.2 * dt)  # exponential drag
        for p in self._particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= damp
            p[3] *= damp
        return self.ttl > 0.0

    def draw(self, surface: pygame.Surface) -> None:
        """Draw into a SRCALPHA surface — caller passes a shared anim surface."""
        frac = max(0.0, self.ttl / self._init_ttl)
        alpha = int(230 * frac)
        if alpha <= 0:
            return
        c = (*self.color, alpha)
        for ox, oy, _vx, _vy, size in self._particles:
            r = max(1, int(size * (0.55 + 0.45 * frac)))  # shrink as it fades
            pygame.draw.circle(
                surface, c,
                (int(self.x + ox), int(self.y + oy)),
                r,
            )
