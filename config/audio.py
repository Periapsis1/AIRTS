"""Global audio settings."""

master_volume: float = 0.3


def set_volume(v: float) -> None:
    """Set master volume (0.0–1.0)."""
    global master_volume
    master_volume = max(0.0, min(1.0, v))
