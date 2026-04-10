"""In-game chat system -- message storage, filtering, and floating text."""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_MESSAGE_LENGTH = 200
CHAT_LOG_MAX = 50            # max messages stored in memory
CHAT_DISPLAY_COUNT = 6       # max messages visible in the overlay
CHAT_DISPLAY_DURATION = 8.0  # seconds a message stays visible in the log
FLOAT_TEXT_DURATION = 4.0    # seconds floating text persists above CC
FLOAT_TEXT_RISE = 30.0       # pixels the floating text drifts upward over its lifetime


@dataclass
class ChatMessage:
    """A single chat message with metadata for display and filtering."""

    player_id: int
    player_name: str
    team_id: int
    message: str
    mode: str          # "all" | "team"
    tick: int
    timestamp: float   # game-time seconds (for display fade calculation)


class ChatLog:
    """Stores recent chat messages for the overlay display."""

    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []

    def add_message(self, msg: ChatMessage) -> None:
        self._messages.append(msg)
        if len(self._messages) > CHAT_LOG_MAX:
            self._messages = self._messages[-CHAT_LOG_MAX:]

    def get_visible(self, current_time: float) -> list[ChatMessage]:
        """Return messages still within the display duration window."""
        cutoff = current_time - CHAT_DISPLAY_DURATION
        return [m for m in self._messages if m.timestamp >= cutoff]

    def get_all(self) -> list[ChatMessage]:
        return list(self._messages)


@dataclass
class FloatingChatText:
    """A chat message floating above a world position (sender's CC)."""

    x: float
    y: float
    message: str
    color: tuple
    player_name: str = ""
    ttl: float = FLOAT_TEXT_DURATION
    _init_ttl: float = field(default=FLOAT_TEXT_DURATION, repr=False)

    def __post_init__(self) -> None:
        self._init_ttl = self.ttl

    def update(self, dt: float) -> bool:
        """Advance timer. Returns False when expired."""
        self.ttl -= dt
        return self.ttl > 0

    @property
    def alpha_frac(self) -> float:
        """0.0 (invisible) to 1.0 (fully opaque)."""
        return max(0.0, self.ttl / self._init_ttl)

    @property
    def rise_offset(self) -> float:
        """Pixels to shift upward from the origin (increases as ttl decreases)."""
        return (1.0 - self.alpha_frac) * FLOAT_TEXT_RISE
