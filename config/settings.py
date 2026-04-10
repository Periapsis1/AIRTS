"""Central configuration for colors, physics, combat, and GUI tuning."""

# -- timing / fixed timestep ------------------------------------------------
TICK_RATE = 60
FIXED_DT = 1.0 / TICK_RATE
MAX_FRAME_DT = 0.25

# -- teams / selection ------------------------------------------------------
SELECTED_COLOR = (0, 255, 100)
DEFAULT_COLOR = (255, 255, 255)
SELECTION_RECT_COLOR = (0, 200, 255)
SELECTION_FILL_COLOR = (0, 200, 255, 40)

# Per-player colours (indexed by player_id - 1); supports up to 8 players
PLAYER_COLORS = [
    (80,  140, 255),  # P1 blue
    (80,  220, 160),  # P2 teal
    (255,  80,  80),  # P3 red
    (255, 160,  60),  # P4 orange
    (180,  80, 220),  # P5 purple
    (80,  220, 220),  # P6 cyan
    (220, 220,  80),  # P7 yellow
    (220,  80, 160),  # P8 pink
]

# Per-team colours — matches PLAYER_COLORS order so FFA (player==team) is consistent
TEAM_COLORS = {
    1: (80,  140, 255),  # T1 blue     (= P1)
    2: (80,  220, 160),  # T2 teal     (= P2)
    3: (255,  80,  80),  # T3 red      (= P3)
    4: (255, 160,  60),  # T4 orange   (= P4)
    5: (180,  80, 220),  # T5 purple   (= P5)
    6: (80,  220, 220),  # T6 cyan     (= P6)
    7: (220, 220,  80),  # T7 yellow   (= P7)
    8: (220,  80, 160),  # T8 pink     (= P8)
}

# Backward-compat aliases (metal_spot.py / metal_extractor.py still reference these)
TEAM1_COLOR = TEAM_COLORS[1]
TEAM1_SELECTED_COLOR = (150, 220, 255)
TEAM2_COLOR = TEAM_COLORS[2]
TEAM3_COLOR = TEAM_COLORS[3]
TEAM4_COLOR = TEAM_COLORS[4]
TEAM5_COLOR = TEAM_COLORS[5]
TEAM6_COLOR = TEAM_COLORS[6]
TEAM7_COLOR = TEAM_COLORS[7]
TEAM8_COLOR = TEAM_COLORS[8]
PATH_COLOR_TEAM1 = (80, 140, 255, 100)
PATH_DOT_COLOR = (255, 255, 255, 160)

RANGE_COLOR = (255, 0, 255, 80)

# -- obstacles --------------------------------------------------------------
OBSTACLE_COLOR = (120, 120, 120)
OBSTACLE_OUTLINE = (160, 160, 160)

# -- physics ----------------------------------------------------------------
UNIT_PUSH_FORCE = 200.0
OBSTACLE_PUSH_FORCE = 300.0
GOAL_ARRIVAL_MARGIN = 5.0

# -- command path -----------------------------------------------------------
COMMAND_PATH_COLOR = (255, 200, 60)
COMMAND_DOT_COLOR = (255, 255, 100)
PATH_SAMPLE_MIN_DIST = 4.0

# -- laser visuals ----------------------------------------------------------
LASER_FLASH_DURATION = 1.0

# -- command center ---------------------------------------------------------
CC_HP = 1000
CC_SPAWN_INTERVAL = 10.0  # seconds
CC_SPAWN_RATE = 0.01  # units per second
CC_SPAWN_RANGE = 50.0  # radius of the circle around the cc where units can spawn
CC_RADIUS = 10.0
CC_LASER_RANGE = 75.0
CC_LASER_DAMAGE = 20
CC_LASER_COOLDOWN = 1.0
CC_OBSTACLE_EXCLUSION = 120.0  # min distance from CC center to obstacle center

# -- reactive armor (tank passive) ------------------------------------------
REACTIVE_ARMOR_INTERVAL = 5.0       # seconds per stack
REACTIVE_ARMOR_MAX_STACKS = 2
REACTIVE_ARMOR_REDUCTION = 0.5      # damage reduction per stack (50%)
REACTIVE_ARMOR_COLOR = (200, 180, 60)

# -- electric armor (T2 tank passive) -----------------------------------------
ELECTRIC_ARMOR_INTERVAL = 2.0           # seconds per stack
ELECTRIC_ARMOR_MAX_STACKS = 6
ELECTRIC_ARMOR_REDUCTION = 0.60         # damage reduction per stack (60%)
ELECTRIC_ARMOR_REGEN_PER_STACK = 0.25    # HP/s per stack
ELECTRIC_ARMOR_SPEED_BONUS = 0.10       # +20% speed per stack
ELECTRIC_ARMOR_COLOR = (80, 180, 255)

# -- overclock (engineer passive) ---------------------------------------------
OVERCLOCK_RANGE = 70.0          # px — engineer aura radius
OVERCLOCK_REGEN = 1.0           # HP/s healed on each metal extractor in range
OVERCLOCK_BONUS = 0.02          # +2% additive spawn bonus per extractor
OVERCLOCK_REGEN_T2 = 2.0        # HP/s for Mechanic
OVERCLOCK_BONUS_T2 = 0.03       # +3% for Mechanic
OVERCLOCK_COLOR = (255, 180, 60)


# -- metal spot -------------------------------------------------------------
METAL_SPOT_COLOR = (255, 200, 60)
METAL_SPOT_RADIUS = 5.0

METAL_SPOT_CAPTURE_RADIUS = 15.0
METAL_SPOT_CAPTURE_RANGE_COLOR = (180, 180, 60, 30)
METAL_SPOT_CAPTURE_ARC_WIDTH = 2.0
METAL_SPOT_CAPTURE_RATE = 0.05  # 5% of the spot's capture progress per unit per second

# -- metal extractor --------------------------------------------------------
METAL_EXTRACTOR_RADIUS = 5.0

METAL_EXTRACTOR_HP = 200
METAL_EXTRACTOR_SPAWN_BONUS = 0.08          # 8% additive per extractor

REINFORCE_BONUS_MULTIPLIER = 2              # doubles bonus when fully reinforced
REINFORCE_HP_BONUS = 100
REINFORCE_STACK_INTERVAL = 15.0             # seconds per plating stack
REINFORCE_MAX_STACKS = 4

# -- T2 upgrade system -------------------------------------------------------
OUTPOST_UPGRADE_DURATION = 30.0              # seconds to build the Outpost
RESEARCH_LAB_UPGRADE_DURATION = 60.0         # seconds to build research lab
T2_SPAWN_BONUS = 0.20                       # 20% spawn bonus for Outpost / Research Lab
OUTPOST_HEAL_PER_SEC = 1.0
OUTPOST_LASER_RANGE = 75.0
OUTPOST_LASER_DAMAGE = 15
OUTPOST_LASER_COOLDOWN = 2.0
OUTPOST_HP_BONUS = 50
OUTPOST_LOS = 140.0                          # line-of-sight radius (vision)
RESEARCH_LAB_HP_BONUS = 100

# -- health bars ------------------------------------------------------------
HEALTH_BAR_WIDTH = 24
HEALTH_BAR_HEIGHT = 3
HEALTH_BAR_OFFSET = 4
HEALTH_BAR_BG = (60, 0, 0)
HEALTH_BAR_FG = (0, 220, 0)
HEALTH_BAR_LOW = (220, 0, 0)

# -- medic ------------------------------------------------------------------
MEDIC_HEAL_COLOR = (100, 255, 150, 80)
HEAL_LASER_COLOR = (100, 255, 150)

# -- GUI panel --------------------------------------------------------------
GUI_BG = (30, 30, 40)
GUI_BORDER = (80, 80, 100)
GUI_BTN_SIZE = 50
GUI_BTN_GAP = 8
GUI_BTN_SELECTED = (60, 200, 120)
GUI_BTN_HOVER = (60, 60, 80)
GUI_BTN_NORMAL = (45, 45, 55)
GUI_TEXT_COLOR = (200, 200, 200)
GUI_PANEL_HEIGHT = 92

# -- camera ----------------------------------------------------------------
CAMERA_ZOOM_STEP = 1.1
CAMERA_MAX_ZOOM = 3.0
EDGE_PAN_MARGIN = 10       # pixels from screen edge to trigger pan
EDGE_PAN_SPEED = 500.0     # screen-space pixels per second
