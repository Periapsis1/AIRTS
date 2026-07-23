// Canvas2D implementation of WorldRenderer — ports the world-drawing half of
// screens/client_game.py. Draws the map + entities in a world-space transform
// (scaled by zoom*dpr), then composites the fog overlay in screen space.

import type { StaticConfig } from "../config/StaticConfig";
import type {
  AnyEntity,
  CCEntity,
  Laser,
  MEEntity,
  MSEntity,
  Obstacle,
  Splash,
  UnitEntity,
} from "../net/MessageTypes";
import { rgb, type RGB } from "../ui/theme";
import type { BurstFx, CameraView, FragmentFx, RenderFrame, WorldRenderer } from "./WorldRenderer";
import { UnitSpriteCache } from "./UnitSpriteCache";
import { assets } from "../assets/Assets";

const TAU = Math.PI * 2;
const MAP_BG: RGB = [10, 10, 18];
const DEAD_BG: RGB = [5, 5, 9];
const OBSTACLE_OUTLINE: RGB = [160, 160, 160];
const HB_BG: RGB = [60, 0, 0];
const HB_FG: RGB = [0, 220, 0];
const HB_LOW: RGB = [220, 0, 0];
const CAPTURE_RANGE_FILL = "rgba(180,180,60,0.12)";
const ABILITY_COLORS: Record<string, RGB> = {
  reactive_armor: [200, 180, 60],
  electric_armor: [80, 180, 255],
};

export class Canvas2DRenderer implements WorldRenderer {
  private ctx!: CanvasRenderingContext2D;
  private cfg!: StaticConfig;
  private sprites!: UnitSpriteCache;
  private fogCanvas: HTMLCanvasElement | null = null;
  private selColor: RGB = [0, 255, 100];

  init(ctx: CanvasRenderingContext2D, cfg: StaticConfig): void {
    this.ctx = ctx;
    this.cfg = cfg;
    this.sprites = new UnitSpriteCache(cfg);
    this.selColor = cfg.selectedColor;
  }

  draw(frame: RenderFrame): void {
    const ctx = this.ctx;
    const { cam, dpr } = frame;

    ctx.save();
    // Clip to the game area (screen space) so the world never overdraws chrome.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.beginPath();
    ctx.rect(cam.gx, cam.gy, cam.vpW, cam.vpH);
    ctx.clip();
    // Dead-space fill (beyond the map border).
    ctx.fillStyle = rgb(DEAD_BG);
    ctx.fillRect(cam.gx, cam.gy, cam.vpW, cam.vpH);

    // World transform: world coords -> device pixels.
    const z = cam.zoom * dpr;
    const ex = (cam.gx + cam.vpW / 2 - cam.cx * cam.zoom) * dpr;
    const ey = (cam.gy + cam.vpH / 2 - cam.cy * cam.zoom) * dpr;
    ctx.setTransform(z, 0, 0, z, ex, ey);

    // Map area: tiled nebula if loaded, else flat fill.
    ctx.fillStyle = rgb(MAP_BG);
    ctx.fillRect(0, 0, frame.mapW, frame.mapH);
    this.drawBackgroundTiles(frame);
    this.drawObstacles(frame.obstacles);

    // Entities: buildings/metal first, then units on top (matches draw order).
    const warping = frame.warpT !== undefined && frame.warpT < 1;
    for (const e of frame.entities) {
      if (e.t === "MS") this.drawMetalSpot(e as MSEntity);
    }
    for (const e of frame.entities) {
      if (e.t === "CC") {
        if (warping) this.drawWarpInCC(e as CCEntity, frame.warpT!);
        else this.drawCommandCenter(e as CCEntity, frame.selectedIds);
      } else if (e.t === "ME") this.drawMetalExtractor(e as MEEntity);
    }
    for (const e of frame.entities) {
      if (e.t === "U") this.drawUnit(e as UnitEntity);
    }
    this.drawSplashes(frame.splashes);
    this.drawLasers(frame.lasers);
    if (frame.bursts) this.drawBursts(frame.bursts);
    if (frame.fragments) this.drawFragments(frame.fragments);
    this.drawSelectionAndCommands(frame);

    // Fog overlay (screen space).
    ctx.restore();
    if (frame.fogMode !== "none") this.drawFog(frame);

    // Fixed labels + floating chat text sit above the fog (screen space).
    if (frame.labels?.length) this.drawWorldLabels(frame);
    if (frame.floatingChats?.length) this.drawFloatingChats(frame);
  }

  /** Team names above CCs and ME bonus % labels — screen space so the text
   *  stays crisp at any zoom (client_game.py _draw_team_labels_screen). */
  private drawWorldLabels(frame: RenderFrame): void {
    const ctx = this.ctx;
    const { cam, dpr } = frame;
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.beginPath();
    ctx.rect(cam.gx, cam.gy, cam.vpW, cam.vpH);
    ctx.clip();
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const lb of frame.labels ?? []) {
      const [sx, sy] = this.w2s(cam, lb.x, lb.y);
      if (sx < -100 || sx > cam.vpW + 100 || sy < -40 || sy > cam.vpH + 40) continue;
      ctx.font = `${Math.max(8, Math.round(lb.size * cam.zoom))}px system-ui, sans-serif`;
      ctx.fillStyle = rgb(lb.color);
      ctx.fillText(lb.text, cam.gx + sx, cam.gy + sy);
    }
    ctx.restore();
  }

  /** Warp-in animation: CC polygon scales in with an expanding glow ring. */
  private drawWarpInCC(e: CCEntity, t: number): void {
    const ctx = this.ctx;
    const scale = t * (2 - t); // ease-out
    const color: RGB = e.c ?? [255, 255, 255];
    const pts = e.pts ?? [];
    if (pts.length && scale > 0) {
      ctx.beginPath();
      pts.forEach(([px, py], i) => {
        if (i === 0) ctx.moveTo(e.x + px * scale, e.y + py * scale);
        else ctx.lineTo(e.x + px * scale, e.y + py * scale);
      });
      ctx.closePath();
      ctx.fillStyle = rgb(color);
      ctx.fill();
      ctx.strokeStyle = rgb(color);
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    const glowR = this.cfg.ccRadius * 3 * t;
    const glowAlpha = (120 / 255) * (1 - t);
    if (glowR > 0 && glowAlpha > 0) {
      ctx.strokeStyle = `rgba(${color[0]},${color[1]},${color[2]},${glowAlpha})`;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(e.x, e.y, glowR, 0, TAU);
      ctx.stroke();
    }
  }

  private drawBursts(bursts: BurstFx[]): void {
    const ctx = this.ctx;
    for (const b of bursts) {
      ctx.fillStyle = `rgba(${b.color[0]},${b.color[1]},${b.color[2]},${b.alpha})`;
      ctx.beginPath();
      ctx.arc(b.x, b.y, b.r, 0, TAU);
      ctx.fill();
    }
  }

  private drawFragments(fragments: FragmentFx[]): void {
    const ctx = this.ctx;
    for (const f of fragments) {
      if (f.pts.length < 3 || f.alpha <= 0) continue;
      ctx.fillStyle = `rgba(${f.color[0]},${f.color[1]},${f.color[2]},${f.alpha})`;
      ctx.beginPath();
      f.pts.forEach(([px, py], i) => {
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();
      ctx.fill();
    }
  }

  /** Floating chat text above sender CCs — drawn over the fog in screen
   *  space, with the font scaling with zoom (client_game.py parity). */
  private drawFloatingChats(frame: RenderFrame): void {
    const ctx = this.ctx;
    const { cam, dpr } = frame;
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.beginPath();
    ctx.rect(cam.gx, cam.gy, cam.vpW, cam.vpH);
    ctx.clip();
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    const size = Math.max(9, 20 * cam.zoom);
    ctx.font = `${size}px system-ui, sans-serif`;
    for (const fc of frame.floatingChats ?? []) {
      if (fc.alpha <= 0) continue;
      const [sx, sy] = this.w2s(cam, fc.x, fc.y);
      ctx.fillStyle = `rgba(${fc.color[0]},${fc.color[1]},${fc.color[2]},${fc.alpha})`;
      ctx.fillText(fc.text, cam.gx + sx, cam.gy + sy);
    }
    ctx.restore();
  }

  private drawBackgroundTiles(frame: RenderFrame): void {
    const img = assets.nebula;
    if (!img || !img.complete || img.naturalWidth === 0) return;
    const ctx = this.ctx;
    const tile = 512; // world-units per tile (nebula scaled down from 1024)
    ctx.save();
    // clip to map rect so tiles don't bleed into dead space
    ctx.beginPath();
    ctx.rect(0, 0, frame.mapW, frame.mapH);
    ctx.clip();
    ctx.globalAlpha = 0.7; // dim to ~70% like the pygame client
    for (let y = 0; y < frame.mapH; y += tile) {
      for (let x = 0; x < frame.mapW; x += tile) {
        ctx.drawImage(img, x, y, tile, tile);
      }
    }
    ctx.restore();
  }

  private drawObstacles(obstacles: Obstacle[]): void {
    const ctx = this.ctx;
    for (const o of obstacles) {
      ctx.fillStyle = rgb(o.c);
      ctx.strokeStyle = rgb(OBSTACLE_OUTLINE);
      ctx.lineWidth = 1;
      if (o.shape === "circle") {
        ctx.beginPath();
        ctx.arc(o.x, o.y, o.r ?? 10, 0, TAU);
        ctx.fill();
        ctx.stroke();
      } else {
        const w = o.w ?? 20;
        const h = o.h ?? 20;
        ctx.fillRect(o.x - w / 2, o.y - h / 2, w, h);
        ctx.strokeRect(o.x - w / 2, o.y - h / 2, w, h);
      }
    }
  }

  private arc(x: number, y: number, r: number, start: number, end: number, color: RGB, width: number): void {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.arc(x, y, r, start, end);
    ctx.strokeStyle = rgb(color);
    ctx.lineWidth = width;
    ctx.stroke();
  }

  private drawHealthBar(cx: number, cy: number, offsetY: number, hp: number, mhp: number, barW: number): void {
    const ctx = this.ctx;
    const ratio = mhp > 0 ? hp / mhp : 0;
    const bx = cx - barW / 2;
    const by = cy - offsetY;
    const bh = this.cfg.healthBarHeight;
    ctx.fillStyle = rgb(HB_BG);
    ctx.fillRect(bx, by, barW, bh);
    ctx.fillStyle = rgb(ratio > 0.35 ? HB_FG : HB_LOW);
    ctx.fillRect(bx, by, barW * ratio, bh);
  }

  private drawUnit(e: UnitEntity): void {
    const ctx = this.ctx;
    const x = e.x;
    const y = e.y;
    const color: RGB = e.c ?? [255, 255, 255];
    const r = Math.round(e.r ?? 5);
    const sprite = this.sprites.get(e.ut, color, r);
    ctx.drawImage(sprite, x - sprite.width / 2, y - sprite.height / 2);

    const mhp = e.mhp ?? 100;
    if (e.hp < mhp) this.drawHealthBar(x, y, r + this.cfg.healthBarOffset, e.hp, mhp, this.cfg.healthBarWidth);

    // Ability + hold-fire indicators
    for (const ab of e.abs ?? []) {
      const stacks = ab.s ?? 0;
      if (stacks > 0 && ABILITY_COLORS[ab.n]) {
        const col = ABILITY_COLORS[ab.n];
        const size = ab.n === "electric_armor" ? 2 : 3;
        const spacing = ab.n === "electric_armor" ? 5 : 6;
        const yOff = r + 6;
        const startX = x - ((stacks - 1) * spacing) / 2;
        for (let i = 0; i < stacks; i++) {
          const dcx = startX + i * spacing;
          const dcy = y - yOff;
          ctx.fillStyle = rgb(col);
          ctx.beginPath();
          ctx.moveTo(dcx, dcy - size);
          ctx.lineTo(dcx + size, dcy);
          ctx.lineTo(dcx, dcy + size);
          ctx.lineTo(dcx - size, dcy);
          ctx.closePath();
          ctx.fill();
        }
      } else if (ab.n === "combat_stim" && ab.a) {
        const cy = y - r - 6;
        const s = 3;
        ctx.strokeStyle = "rgb(100,255,100)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x - s, cy + s);
        ctx.lineTo(x, cy - s);
        ctx.lineTo(x + s, cy + s);
        ctx.stroke();
      }
    }
    if (e.hf) {
      const s = 3;
      const hy = y - r - 4;
      ctx.strokeStyle = "rgb(200,60,60)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x - s, hy - s);
      ctx.lineTo(x + s, hy + s);
      ctx.moveTo(x - s, hy + s);
      ctx.lineTo(x + s, hy - s);
      ctx.stroke();
    }
  }

  private drawCommandCenter(e: CCEntity, selected: Set<number>): void {
    const ctx = this.ctx;
    const x = e.x;
    const y = e.y;
    const color: RGB = e.c ?? [255, 255, 255];
    const ghost = e.ghost === true;
    ctx.save();
    if (ghost) ctx.globalAlpha = 0.4;

    const pts = e.pts ?? [];
    if (pts.length) {
      ctx.beginPath();
      pts.forEach(([px, py], i) => {
        if (i === 0) ctx.moveTo(x + px, y + py);
        else ctx.lineTo(x + px, y + py);
      });
      ctx.closePath();
      ctx.fillStyle = rgb(color);
      ctx.fill();
      ctx.strokeStyle = rgb(color);
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    if (!ghost) {
      const arcR = this.cfg.ccRadius + 5;
      const spt = e.spt ?? 0;
      if (spt < 1.0) {
        this.arc(x, y, arcR, Math.PI / 2, Math.PI / 2 + spt * TAU, this.selColor, 2);
      } else {
        this.arc(x, y, arcR, 0, TAU, this.selColor, 2);
      }
      // Rally flag when selected
      if (e.rx !== undefined && selected.has(e.id)) {
        const rx = e.rx;
        const ry = e.ry ?? 0;
        ctx.strokeStyle = rgb(color);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(rx, ry);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(rx, ry);
        ctx.lineTo(rx, ry - 14);
        ctx.stroke();
        ctx.fillStyle = rgb(color);
        ctx.beginPath();
        ctx.moveTo(rx, ry - 14);
        ctx.lineTo(rx + 8, ry - 10);
        ctx.lineTo(rx, ry - 6);
        ctx.closePath();
        ctx.fill();
      }
      const hp = e.hp ?? this.cfg.ccHp;
      if (hp < this.cfg.ccHp) {
        this.drawHealthBar(x, y, this.cfg.ccRadius + this.cfg.healthBarOffset, hp, this.cfg.ccHp, 40);
      }
    }
    ctx.restore();
  }

  private drawMetalExtractor(e: MEEntity): void {
    const ctx = this.ctx;
    const x = e.x;
    const y = e.y;
    const r = e.r ?? 5;
    const rot = e.rot ?? 0;
    const color: RGB = (e as unknown as { c?: RGB }).c ?? this.cfg.teamColor(e.tm);
    const ghost = e.ghost === true;
    ctx.save();
    if (ghost) ctx.globalAlpha = 0.4;

    // Equilateral triangle, rotated by `rot` (complex-multiply port).
    const s = (r * Math.sqrt(3)) / 2;
    const base: [number, number][] = [
      [0, r],
      [-s, -r / 2],
      [s, -r / 2],
    ];
    const cos = Math.cos(rot);
    const sin = Math.sin(rot);
    ctx.beginPath();
    base.forEach(([px, py], i) => {
      const rx = px * cos - py * sin;
      const ry = px * sin + py * cos;
      if (i === 0) ctx.moveTo(x + rx, y + ry);
      else ctx.lineTo(x + rx, y + ry);
    });
    ctx.closePath();
    ctx.fillStyle = rgb(color);
    ctx.fill();
    ctx.strokeStyle = "rgb(0,0,0)";
    ctx.lineWidth = 1;
    ctx.stroke();

    if (!ghost) {
      const rst = e.rst ?? 0;
      if (rst > 0) {
        const arcR = this.cfg.metalCaptureRadius;
        const span = (87.5 * Math.PI) / 180;
        const half = span / 2;
        const cardinals = [Math.PI / 2, 0, (3 * Math.PI) / 2, Math.PI];
        for (let i = 0; i < Math.min(rst, 4); i++) {
          this.arc(x, y, arcR, cardinals[i] - half, cardinals[i] + half, color, 2);
        }
      }
      const mhp = e.mhp ?? this.cfg.metalExtractorHp;
      if (e.hp < mhp) this.drawHealthBar(x, y, r + this.cfg.healthBarOffset, e.hp, mhp, this.cfg.healthBarWidth);
    }
    ctx.restore();
  }

  private drawMetalSpot(e: MSEntity): void {
    const ctx = this.ctx;
    const x = e.x;
    const y = e.y;
    const r = e.r ?? 5;
    const cr = this.cfg.metalCaptureRadius;
    // Capture-range translucent disc
    ctx.fillStyle = CAPTURE_RANGE_FILL;
    ctx.beginPath();
    ctx.arc(x, y, cr, 0, TAU);
    ctx.fill();

    const color: RGB = e.ow == null ? [255, 200, 60] : this.cfg.teamColor(e.ow);
    ctx.fillStyle = rgb(color);
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fill();

    // Capture progress arcs (only while unowned)
    if (e.ow == null && e.cp) {
      const arcR = cr + 2;
      for (const [teamStr, progress] of Object.entries(e.cp)) {
        if (progress < 0.01) continue;
        const col = this.cfg.teamColor(Number(teamStr));
        this.arc(x, y, arcR, Math.PI / 2, Math.PI / 2 + progress * TAU, col, 2);
      }
    }
  }

  private fovArc(e: AnyEntity): { circle: boolean; r: number; color: string; fovDeg?: number; fa?: number } | null {
    const RANGE = "rgba(255,0,255,0.63)";
    if (e.t === "CC") return { circle: true, r: this.cfg.ccLaserRange, color: RANGE };
    if (e.t === "ME") {
      if ((e as MEEntity).us === "outpost") return { circle: true, r: this.cfg.outpostLaserRange, color: RANGE };
      return null;
    }
    if (e.t !== "U") return null;
    const u = e as UnitEntity;
    const stat = this.cfg.unitTypes[u.ut];
    const weapon = stat?.weapon as { range?: number; hits_only_friendly?: boolean } | undefined;
    if (!weapon) return null;
    const r = u.rng ?? weapon.range ?? 50;
    if (r <= 0) return null;
    let color = RANGE;
    if (u.hf) color = "rgba(120,120,120,0.63)";
    else if (weapon.hits_only_friendly) color = "rgba(100,255,150,0.63)";
    const fovDeg = stat?.fov ?? 90;
    if (fovDeg >= 359) return { circle: true, r, color };
    return { circle: false, r, color, fovDeg, fa: u.fa ?? 0 };
  }

  private drawFovArcs(frame: RenderFrame): void {
    const ctx = this.ctx;
    for (const e of frame.entities) {
      if (!frame.selectedIds.has(e.id)) continue;
      const shape = this.fovArc(e);
      if (!shape) continue;
      ctx.strokeStyle = shape.color;
      ctx.lineWidth = 1;
      if (shape.circle) {
        ctx.beginPath();
        ctx.arc(e.x, e.y, shape.r, 0, TAU);
        ctx.stroke();
      } else {
        const span = ((shape.fovDeg ?? 90) * Math.PI) / 180;
        const fa = shape.fa ?? 0;
        ctx.beginPath();
        ctx.moveTo(e.x, e.y);
        ctx.arc(e.x, e.y, shape.r, fa - span / 2, fa + span / 2);
        ctx.closePath();
        ctx.stroke();
      }
    }
  }

  private drawSelectionAndCommands(frame: RenderFrame): void {
    const ctx = this.ctx;
    const sel = frame.selectedIds;
    if (sel.size) this.drawFovArcs(frame);
    // Selection rings + command feedback lines for selected own units.
    if (sel.size) {
      ctx.strokeStyle = rgb(this.selColor);
      ctx.lineWidth = 1;
      for (const e of frame.entities) {
        if (!sel.has(e.id)) continue;
        ctx.beginPath();
        ctx.arc(e.x, e.y, (e.r ?? 5) + 3, 0, TAU);
        ctx.stroke();
        // Move/attack destination line
        const u = e as UnitEntity;
        let tx = u.tx;
        let ty = u.ty;
        if (tx === undefined || ty === undefined) {
          tx = u.atx;
          ty = u.aty;
        }
        if (tx !== undefined && ty !== undefined) {
          ctx.save();
          ctx.globalAlpha = 0.5;
          ctx.beginPath();
          ctx.moveTo(e.x, e.y);
          ctx.lineTo(tx, ty);
          ctx.stroke();
          ctx.restore();
        }
      }
    }

    // Live right-drag command path
    const rp = frame.rpath;
    if (rp && rp.length) {
      ctx.strokeStyle = "rgba(255,200,60,0.9)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(rp[0][0], rp[0][1]);
      for (let i = 1; i < rp.length; i++) ctx.lineTo(rp[i][0], rp[i][1]);
      ctx.stroke();
      const last = rp[rp.length - 1];
      ctx.fillStyle = "rgba(255,255,100,0.9)";
      ctx.beginPath();
      ctx.arc(last[0], last[1], 2, 0, TAU);
      ctx.fill();
    }

    // Drag-selection rect / circle
    if (frame.dragRect) {
      const d = frame.dragRect;
      ctx.fillStyle = "rgba(0,200,255,0.16)";
      ctx.fillRect(d.x, d.y, d.w, d.h);
      ctx.strokeStyle = "rgb(0,200,255)";
      ctx.lineWidth = 1;
      ctx.strokeRect(d.x, d.y, d.w, d.h);
    }
    if (frame.dragCircle) {
      const d = frame.dragCircle;
      ctx.fillStyle = "rgba(0,200,255,0.16)";
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, TAU);
      ctx.fill();
      ctx.strokeStyle = "rgb(0,200,255)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  private drawLasers(lasers: Laser[]): void {
    const ctx = this.ctx;
    for (const [x1, y1, x2, y2, color, width] of lasers) {
      ctx.strokeStyle = rgb(color);
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }

  private drawSplashes(splashes: Splash[]): void {
    const ctx = this.ctx;
    for (const s of splashes) {
      const p = s.p ?? 0;
      const radius = s.r * Math.max(0.05, p);
      const alpha = Math.max(0, 1 - p);
      ctx.strokeStyle = `rgba(255,90,40,${alpha})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(s.x, s.y, radius, 0, TAU);
      ctx.stroke();
    }
  }

  private drawFog(frame: RenderFrame): void {
    const ctx = this.ctx;
    const { cam, dpr, fogMode } = frame;
    const wpx = Math.round(cam.vpW * dpr);
    const hpx = Math.round(cam.vpH * dpr);
    if (wpx <= 0 || hpx <= 0) return;
    if (!this.fogCanvas) this.fogCanvas = document.createElement("canvas");
    const fc = this.fogCanvas;
    if (fc.width !== wpx || fc.height !== hpx) {
      fc.width = wpx;
      fc.height = hpx;
    }
    const fctx = fc.getContext("2d")!;
    fctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    fctx.globalCompositeOperation = "source-over";
    const alpha = fogMode === "soft" ? 146 / 255 : 200 / 255;
    fctx.clearRect(0, 0, cam.vpW, cam.vpH);
    fctx.fillStyle = `rgba(0,0,0,${alpha})`;
    fctx.fillRect(0, 0, cam.vpW, cam.vpH);

    // Cut holes for LOS circles (viewport-relative screen coords).
    fctx.globalCompositeOperation = "destination-out";
    for (const [wx, wy, wr] of frame.losCircles) {
      const [sx, sy] = this.w2s(cam, wx, wy);
      const rs = Math.max(1, wr * cam.zoom);
      if (sx + rs < 0 || sx - rs > cam.vpW || sy + rs < 0 || sy - rs > cam.vpH) continue;
      if (fogMode === "soft") {
        const EDGE = 4;
        const inner = Math.max(0, (rs - EDGE) / rs);
        const grad = fctx.createRadialGradient(sx, sy, 0, sx, sy, rs);
        grad.addColorStop(0, "rgba(0,0,0,1)");
        grad.addColorStop(inner, "rgba(0,0,0,1)");
        grad.addColorStop(1, "rgba(0,0,0,0)");
        fctx.fillStyle = grad;
        fctx.beginPath();
        fctx.arc(sx, sy, rs, 0, TAU);
        fctx.fill();
      } else {
        fctx.fillStyle = "rgba(0,0,0,1)";
        fctx.beginPath();
        fctx.arc(sx, sy, rs, 0, TAU);
        fctx.fill();
      }
    }
    fctx.globalCompositeOperation = "source-over";

    // Composite the fog over the world (device-pixel blit at the game origin).
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(fc, Math.round(cam.gx * dpr), Math.round(cam.gy * dpr));
    ctx.restore();
  }

  private w2s(cam: CameraView, wx: number, wy: number): [number, number] {
    return [(wx - cam.cx) * cam.zoom + cam.vpW / 2, (wy - cam.cy) * cam.zoom + cam.vpH / 2];
  }
}
