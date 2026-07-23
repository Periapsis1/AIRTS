// Pre-renders unit sprites (circle body + polygon symbol) to offscreen canvases
// at world resolution, keyed by (unit_type, color, radius). Mirrors
// core/sprite_cache.py — the world transform scales them by zoom, matching the
// pygame client's "draw to world surface, then scale" behavior.

import type { StaticConfig } from "../config/StaticConfig";
import { rgb, type RGB } from "../ui/theme";

export class UnitSpriteCache {
  private cfg: StaticConfig;
  private cache = new Map<string, HTMLCanvasElement>();

  constructor(cfg: StaticConfig) {
    this.cfg = cfg;
  }

  get(ut: string, color: RGB, radius: number): HTMLCanvasElement {
    const key = `${ut}|${color[0]},${color[1]},${color[2]}|${radius}`;
    let c = this.cache.get(key);
    if (!c) {
      c = this.render(ut, color, radius);
      this.cache.set(key, c);
    }
    return c;
  }

  private render(ut: string, color: RGB, radius: number): HTMLCanvasElement {
    const pad = 2;
    const size = radius * 2 + pad * 2;
    const cv = document.createElement("canvas");
    cv.width = size;
    cv.height = size;
    const g = cv.getContext("2d")!;
    const cx = size / 2;
    const cy = size / 2;
    const stat = this.cfg.unitTypes[ut];

    if (stat?.hollow) {
      const lw = Math.max(1, Math.floor(radius / 2));
      g.strokeStyle = rgb(color);
      g.lineWidth = lw;
      g.beginPath();
      g.arc(cx, cy, Math.max(1, radius - lw / 2), 0, Math.PI * 2);
      g.stroke();
    } else {
      g.fillStyle = rgb(color);
      g.beginPath();
      g.arc(cx, cy, radius, 0, Math.PI * 2);
      g.fill();
    }

    const symbol = stat?.symbol;
    if (symbol && symbol.length) {
      const scale = radius / 16;
      g.beginPath();
      symbol.forEach(([px, py], i) => {
        const X = cx + px * scale;
        const Y = cy + py * scale;
        if (i === 0) g.moveTo(X, Y);
        else g.lineTo(X, Y);
      });
      g.closePath();
      g.fillStyle = "rgb(0,0,0)";
      g.fill();
      g.strokeStyle = rgb(color);
      g.lineWidth = 1;
      g.stroke();
    }
    return cv;
  }
}
