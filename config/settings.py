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

TEAM1_COLOR = (80, 140, 255)
TEAM1_SELECTED_COLOR = (150, 220, 255)
TEAM2_COLOR = (255, 80, 80)
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
UNIT_LASER_COLOR_T1 = (120, 180, 255)
UNIT_LASER_COLOR_T2 = (255, 120, 120)
CC_LASER_COLOR_T1 = (180, 220, 255)
CC_LASER_COLOR_T2 = (255, 180, 180)
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

CC_HEAL_RADIUS = 40.0
CC_HEAL_RATE = 5
CC_HEAL_COLOR_T1 = (60, 180, 100, 30)
CC_HEAL_COLOR_T2 = (180, 60, 60, 30)
CC_HEAL_RING_T1 = (60, 180, 100, 80)
CC_HEAL_RING_T2 = (180, 60, 60, 80)

# -- metal spot -------------------------------------------------------------
METAL_SPOT_COLOR = (255, 200, 60)
METAL_SPOT_RADIUS = 5.0

METAL_SPOT_CAPTURE_RADIUS = 15.0
METAL_SPOT_CAPTURE_RANGE_COLOR = (180, 180, 60, 30)
METAL_SPOT_CAPTURE_ARC_WIDTH = 2.0
METAL_SPOT_CAPTURE_ARC_COLOR_T1 = (80, 140, 255)
METAL_SPOT_CAPTURE_ARC_COLOR_T2 = (255, 80, 80)
METAL_SPOT_CAPTURE_RATE = 0.05  # 5% of the spot's capture progress per unit per second

# -- metal extractor --------------------------------------------------------
METAL_EXTRACTOR_RADIUS = 5.0

METAL_EXTRACTOR_HP = 200
METAL_EXTRACTOR_BOOST_FACTOR = 1.05

# -- health bars ------------------------------------------------------------
HEALTH_BAR_WIDTH = 24
HEALTH_BAR_HEIGHT = 3
HEALTH_BAR_OFFSET = 4
HEALTH_BAR_BG = (60, 0, 0)
HEALTH_BAR_FG = (0, 220, 0)
HEALTH_BAR_LOW = (220, 0, 0)

# -- medic ------------------------------------------------------------------
MEDIC_HEAL_COLOR = (100, 255, 150, 80)

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
