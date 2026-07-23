"""Builders for the browser-only handshake payloads (ai_choices + server_config).

These snapshot the Python-side constants and AI registry into plain JSON-able
dicts so the browser client doesn't have to duplicate ``config/`` in
TypeScript. They are built once by callers that already own a registry
(``server.py``, ``app.py``, ``internal_server.py``) and passed into
``GameHost`` — ``host.py`` itself never imports ``config`` or the registry,
keeping the network thread free of that import cost.

Desktop (TCP) clients ignore these extra messages; only the browser client
reads them.
"""
from __future__ import annotations


def build_ai_choices(registry) -> dict:
    """Snapshot the AI registry for the lobby AI dropdowns.

    The browser can't enumerate Python AI classes, so this list is the only
    way it learns which bots exist.
    """
    choices = registry.get_choices(include_deprecated=True)
    deprecated = registry.get_deprecated_ids()
    return {
        "choices": [[ai_id, ai_name] for ai_id, ai_name in choices],
        "deprecated": sorted(deprecated),
    }


def build_static_config() -> dict:
    """Snapshot the display constants the browser client needs to render and
    label the game. Sent live each connect, so it stays in sync with ``config/``
    as the game is balanced (no hand-copied constants in TypeScript)."""
    from config import settings as s
    from config.unit_types import UNIT_TYPES, T2_NAMES, get_spawnable_types
    from systems.replay import RECORD_INTERVAL
    from systems.abilities import ABILITY_REGISTRY

    return {
        "unit_types": UNIT_TYPES,
        "t2_names": T2_NAMES,
        "spawnable_types": list(get_spawnable_types().keys()),
        "player_colors": [list(c) for c in s.PLAYER_COLORS],
        "team_colors": {str(t): list(c) for t, c in s.TEAM_COLORS.items()},
        "selected_color": list(s.SELECTED_COLOR),
        "broadcast_interval": RECORD_INTERVAL,
        "timing": {
            "tick_rate": s.TICK_RATE,
            "fixed_dt": s.FIXED_DT,
            "max_frame_dt": s.MAX_FRAME_DT,
        },
        "command_center": {
            "hp": s.CC_HP,
            "radius": s.CC_RADIUS,
            "spawn_interval": s.CC_SPAWN_INTERVAL,
            "spawn_range": s.CC_SPAWN_RANGE,
            "laser_range": s.CC_LASER_RANGE,
        },
        "metal": {
            "spot_radius": s.METAL_SPOT_RADIUS,
            "capture_radius": s.METAL_SPOT_CAPTURE_RADIUS,
            "extractor_radius": s.METAL_EXTRACTOR_RADIUS,
            "extractor_spawn_bonus": s.METAL_EXTRACTOR_SPAWN_BONUS,
            "reinforce_max_stacks": s.REINFORCE_MAX_STACKS,
        },
        "upgrades": {
            "outpost_duration": s.OUTPOST_UPGRADE_DURATION,
            "research_lab_duration": s.RESEARCH_LAB_UPGRADE_DURATION,
            "t2_spawn_bonus": s.T2_SPAWN_BONUS,
            # Stat details for the browser's upgrade tooltips (gui.py parity).
            "outpost": {
                "hp_bonus": s.OUTPOST_HP_BONUS,
                "heal_per_sec": s.OUTPOST_HEAL_PER_SEC,
                "los": s.OUTPOST_LOS,
                "laser_damage": s.OUTPOST_LASER_DAMAGE,
                "laser_range": s.OUTPOST_LASER_RANGE,
                "laser_cooldown": s.OUTPOST_LASER_COOLDOWN,
            },
            "research_lab": {
                "hp_bonus": s.RESEARCH_LAB_HP_BONUS,
            },
            "reinforce": {
                "max_stacks": s.REINFORCE_MAX_STACKS,
                "stack_interval": s.REINFORCE_STACK_INTERVAL,
                "hp_bonus": s.REINFORCE_HP_BONUS,
                "bonus_multiplier": s.REINFORCE_BONUS_MULTIPLIER,
            },
        },
        # name -> description for the HUD abilities panel (registry lives in
        # Python; the browser can't import systems/abilities.py).
        "ability_descriptions": {
            name: getattr(cls, "description", "")
            for name, cls in ABILITY_REGISTRY.items()
        },
        "camera": {
            "zoom_step": s.CAMERA_ZOOM_STEP,
            "max_zoom": s.CAMERA_MAX_ZOOM,
            "edge_pan_margin": s.EDGE_PAN_MARGIN,
            "edge_pan_speed": s.EDGE_PAN_SPEED,
        },
        "health_bar": {
            "width": s.HEALTH_BAR_WIDTH,
            "height": s.HEALTH_BAR_HEIGHT,
            "offset": s.HEALTH_BAR_OFFSET,
        },
    }
