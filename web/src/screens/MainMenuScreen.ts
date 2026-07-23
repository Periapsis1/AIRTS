// Title screen with wandering background dots and navigation buttons —
// ported from screens/main_menu.py. In the browser, both "Create Lobby" and
// "Multiplayer" route to the Connect screen (a browser always needs a hosted
// server); other buttons are placeholders pending later milestones.

import { Screen, type Transition } from "../app/Screen";
import type { App } from "../app/App";
import {
  BG_DOT_COUNT,
  BG_DOT_RADIUS,
  BG_DOT_SPEED,
  BTN_HEIGHT,
  BTN_WIDTH,
  PLAYER_COLORS,
  SUBTITLE_COLOR,
  SUBTITLE_FONT_SIZE,
  TITLE_COLOR,
  TITLE_FONT_SIZE,
  TITLE_SHADOW_COLOR,
  rgb,
  type RGB,
} from "../ui/theme";
import { drawText } from "../ui/Text";

interface Dot {
  x: number;
  y: number;
  tx: number;
  ty: number;
  color: RGB;
}

const MENU_ITEMS: [string, string, boolean][] = [
  ["Create Lobby", "connect", true],
  ["Multiplayer", "connect", true],
  ["AI Arena", "arena", false],
  ["Replays", "replays", false],
  ["Learn to Play", "guides", false],
  ["Options", "options", false],
];

export class MainMenuScreen extends Screen {
  private dots: Dot[] = [];
  private seeded = false;

  constructor(app: App) {
    super(app);
  }

  private seed(w: number, h: number): void {
    const n = PLAYER_COLORS.length || 1;
    const ai = Math.floor(Math.random() * n);
    const bi = (ai + 3) % n;
    const fallback: RGB = [120, 140, 200];
    const colorA = PLAYER_COLORS[ai] ?? fallback;
    const colorB = PLAYER_COLORS[bi] ?? fallback;
    for (let i = 0; i < BG_DOT_COUNT; i++) {
      this.dots.push({
        x: Math.random() * w,
        y: Math.random() * h,
        tx: Math.random() * w,
        ty: Math.random() * h,
        color: i < BG_DOT_COUNT / 2 ? colorA : colorB,
      });
    }
    this.seeded = true;
  }

  render(dt: number): Transition | null {
    const { ui } = this;
    const ctx = ui.ctx;
    const w = ui.w;
    const h = ui.h;
    if (!this.seeded) this.seed(w, h);

    // Background dots
    for (const d of this.dots) {
      const dx = d.tx - d.x;
      const dy = d.ty - d.y;
      const dist = Math.hypot(dx, dy);
      if (dist < 5) {
        d.tx = Math.random() * w;
        d.ty = Math.random() * h;
      } else {
        d.x += (dx / dist) * BG_DOT_SPEED * dt;
        d.y += (dy / dist) * BG_DOT_SPEED * dt;
      }
      const dc = d.color ?? [120, 140, 200];
      ctx.beginPath();
      ctx.arc(d.x, d.y, BG_DOT_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = rgb([dc[0], dc[1], dc[2], 100]);
      ctx.fill();
    }

    // Title + shadow
    drawText(ctx, "AIRTS", w / 2 + 3, 103, {
      size: TITLE_FONT_SIZE,
      color: TITLE_SHADOW_COLOR,
      align: "center",
      bold: true,
    });
    drawText(ctx, "AIRTS", w / 2, 100, {
      size: TITLE_FONT_SIZE,
      color: TITLE_COLOR,
      align: "center",
      bold: true,
    });
    drawText(ctx, "AI Real-Time Strategy", w / 2, 100 + TITLE_FONT_SIZE + 8, {
      size: SUBTITLE_FONT_SIZE,
      color: SUBTITLE_COLOR,
      align: "center",
    });

    // Buttons
    const startY = Math.floor(h / 2) - 20;
    const spacing = BTN_HEIGHT + 10;
    let result: Transition | null = null;
    for (let i = 0; i < MENU_ITEMS.length; i++) {
      const [label, target, enabled] = MENU_ITEMS[i];
      const bx = Math.floor(w / 2 - BTN_WIDTH / 2);
      const by = startY + i * spacing;
      if (ui.button(`menu.${target}.${i}`, bx, by, BTN_WIDTH, BTN_HEIGHT, label, { enabled }) && enabled) {
        result = { next: target };
      }
    }
    return result;
  }
}
