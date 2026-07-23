// Menu/widget colors and sizes — ported from ui/theme.py so the canvas-drawn
// UI matches the pygame client. RGB tuples become CSS rgb() strings via rgb().

export type RGB = [number, number, number];
export type RGBA = [number, number, number, number];

export function rgb(c: RGB | RGBA): string {
  if (c.length === 4) return `rgba(${c[0]},${c[1]},${c[2]},${c[3] / 255})`;
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

// -- background --
export const MENU_BG: RGB = [12, 12, 20];

// -- title --
export const TITLE_COLOR: RGB = [220, 220, 240];
export const TITLE_SHADOW_COLOR: RGB = [40, 40, 60];
export const SUBTITLE_COLOR: RGB = [140, 140, 170];
export const TITLE_FONT_SIZE = 64;
export const SUBTITLE_FONT_SIZE = 22;

// -- buttons --
export const BTN_NORMAL: RGB = [35, 35, 50];
export const BTN_HOVER: RGB = [55, 55, 75];
export const BTN_PRESS: RGB = [25, 25, 40];
export const BTN_TEXT: RGB = [220, 220, 240];
export const BTN_BORDER: RGB = [80, 80, 110];
export const BTN_DISABLED_TEXT: RGB = [110, 110, 130];
export const BTN_WIDTH = 260;
export const BTN_HEIGHT = 44;
export const BTN_FONT_SIZE = 20;
export const BTN_BORDER_RADIUS = 6;

// -- back button --
export const BACK_BTN_SIZE = 36;
export const BACK_BTN_MARGIN = 12;
export const BACK_BTN_COLOR: RGB = [180, 180, 200];

// -- dropdown --
export const DD_BG: RGB = [30, 30, 45];
export const DD_HOVER: RGB = [50, 50, 70];
export const DD_BORDER: RGB = [70, 70, 100];
export const DD_TEXT: RGB = [200, 200, 220];
export const DD_WIDTH = 220;
export const DD_HEIGHT = 32;
export const DD_FONT_SIZE = 16;

// -- text input --
export const TI_BG: RGB = [30, 30, 45];
export const TI_ACTIVE_BG: RGB = [40, 40, 55];
export const TI_BORDER: RGB = [70, 70, 100];
export const TI_ACTIVE_BORDER: RGB = [80, 140, 255];
export const TI_TEXT: RGB = [200, 200, 220];
export const TI_PLACEHOLDER: RGB = [100, 100, 120];

// -- slider --
export const SL_TRACK_COLOR: RGB = [50, 50, 70];
export const SL_FILL_COLOR: RGB = [80, 140, 255];
export const SL_HANDLE_COLOR: RGB = [200, 200, 220];
export const SL_TEXT_COLOR: RGB = [180, 180, 200];
export const SL_WIDTH = 220;
export const SL_HEIGHT = 8;
export const SL_HANDLE_RADIUS = 8;
export const SL_FONT_SIZE = 16;

// -- checkbox --
export const CB_BOX: RGB = [35, 35, 50];
export const CB_CHECK: RGB = [80, 255, 120];
export const CB_BORDER: RGB = [80, 80, 110];
export const CB_DISABLED: RGB = [60, 60, 70];

// -- toggle group --
export const TG_ACTIVE: RGB = [80, 140, 255];
export const TG_INACTIVE: RGB = [40, 40, 55];
export const TG_BORDER: RGB = [70, 70, 100];
export const TG_TEXT: RGB = [220, 220, 240];
export const TG_FONT_SIZE = 16;

// -- content / headings --
export const CONTENT_TEXT: RGB = [200, 200, 220];
export const CONTENT_HEADING: RGB = [220, 220, 240];
export const CONTENT_FONT_SIZE = 16;
export const HEADING_FONT_SIZE = 24;

// -- create-lobby panels (from screens/create_lobby.py) --
export const PANEL_BG: RGB = [18, 18, 28];
export const PANEL_BORDER: RGB = [42, 42, 62];
export const HDR_COLOR: RGB = [160, 160, 185];
export const ONLINE_COLOR: RGB = [100, 255, 140];

// -- player colors (matches config PLAYER_COLORS) --
export const PLAYER_COLORS: RGB[] = [
  [80, 140, 255],
  [80, 220, 160],
  [255, 80, 80],
  [255, 160, 60],
  [180, 80, 220],
  [80, 220, 220],
  [220, 220, 80],
  [220, 80, 160],
];

// -- background animation (main menu) --
export const BG_DOT_RADIUS = 4;
export const BG_DOT_SPEED = 20;
export const BG_DOT_COUNT = 30;

// Font family used for all canvas text. pygame uses SysFont(None, size); a
// system sans-serif stack is the closest faithful match in the browser.
export const FONT_FAMILY =
  'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
