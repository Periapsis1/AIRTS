// Bottom HUD bar — minimap, selected-unit summary, and the build/action panel.
// A functional port of gui.py's draw_hud + handle_hud_click + minimap click,
// including the M4 parity pieces: ME upgrade/research UI, ability panel, and
// hover tooltips (unit stats + upgrade details).

import type { UI } from "../ui/Widgets";
import type { GameView } from "./GameView";
import type { StaticConfig, UnitStat } from "../config/StaticConfig";
import type { Ability, AnyEntity, CCEntity, MEEntity, Obstacle, UnitEntity } from "../net/MessageTypes";
import { rgb, type RGB } from "../ui/theme";
import { drawText, measure } from "../ui/Text";

const SECTION_BG: RGB = [22, 22, 30];
const MINIMAP_BG: RGB = [10, 10, 15];
const DIVIDER: RGB = [50, 50, 65];
const TITLE_COLOR: RGB = [210, 210, 230];
const STAT_LABEL: RGB = [130, 130, 155];
const STAT_VALUE: RGB = [200, 200, 220];
const BTN_NORMAL: RGB = [45, 45, 55];
const BTN_HOVER: RGB = [60, 60, 80];
const BTN_SELECTED: RGB = [60, 200, 120];
const BTN_PRESSED: RGB = [32, 82, 56];
const HOTKEY_COLOR: RGB = [255, 255, 255];
const BTN_DISABLED_BG: RGB = [38, 38, 48];
const BTN_DISABLED_TEXT: RGB = [110, 110, 125];
const OBSTACLE_MM: RGB = [80, 80, 80];
const TT_BG: RGB = [18, 18, 26];
const TT_BORDER: RGB = [70, 70, 90];
const DIFF_GOOD: RGB = [100, 255, 100];
const DIFF_BAD: RGB = [255, 100, 100];

const BUILD_BTN_SIZE = 38;
const BUILD_BTN_GAP = 4;
const ACTION_BTN_SIZE = 38;
const ACTION_BTN_GAP = 4;
const HDR = 22;
const PAD = 8;
const UPGRADE_BTN_W = 90;
const UPGRADE_BTN_H = 30;
const UPGRADE_BTN_GAP = 6;
const TT_PAD = 8;
const TT_LINE_H = 18;
const BUILD_HOTKEY_LETTERS = ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"];
const ACTIONS: [string, string, string][] = [
  ["stop", "S", "Stop"],
  ["attack", "A", "Attack"],
  ["move", "M", "Move"],
  ["fight", "F", "Fight"],
  ["hold_fire", "H", "Hold Fire"],
];
const ACTION_DESCRIPTIONS: Record<string, string> = {
  stop: "Halt the selected units immediately and clear their current orders.",
  attack: "Attack: right-click an enemy to attack it, or a point to attack-move — advancing and engaging anything met on the way.",
  move: "Move: plain move order — units travel to the point without stopping to engage.",
  fight: "Fight: move toward a point, pausing to engage enemies that come into range along the way.",
  hold_fire: "Hold Fire: toggle — units will not shoot until hold fire is released.",
};

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export class Hud {
  private cfg: StaticConfig;
  private view: GameView;
  obstacles: Obstacle[];

  constructor(cfg: StaticConfig, view: GameView, obstacles: Obstacle[]) {
    this.cfg = cfg;
    this.view = view;
    this.obstacles = obstacles;
  }

  static height(h: number): number {
    return Math.max(120, Math.min(200, Math.round(h * 0.2)));
  }

  private sections(w: number, h: number, hudH: number): { minimap: Rect; display: Rect; action: Rect } {
    const y = h - hudH;
    const minimapW = hudH;
    const actionW = Math.max(220, Math.round(w * 0.2));
    const displayW = w - minimapW - actionW;
    return {
      minimap: { x: 0, y, w: minimapW, h: hudH },
      display: { x: minimapW, y, w: displayW, h: hudH },
      action: { x: w - actionW, y, w: actionW, h: hudH },
    };
  }

  private buildBtnRects(ar: Rect): { rect: Rect; ut: string }[] {
    const types = this.cfg.spawnableTypes;
    const iw = ar.w - PAD * 2;
    const cols = Math.max(1, Math.floor((iw + BUILD_BTN_GAP) / (BUILD_BTN_SIZE + BUILD_BTN_GAP)));
    const out: { rect: Rect; ut: string }[] = [];
    types.forEach((ut, i) => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      out.push({
        rect: {
          x: ar.x + PAD + c * (BUILD_BTN_SIZE + BUILD_BTN_GAP),
          y: ar.y + PAD + HDR + r * (BUILD_BTN_SIZE + BUILD_BTN_GAP),
          w: BUILD_BTN_SIZE,
          h: BUILD_BTN_SIZE,
        },
        ut,
      });
    });
    return out;
  }

  private actionBtnRects(ar: Rect): { rect: Rect; action: string; key: string; label: string }[] {
    return ACTIONS.map(([action, key, label], i) => ({
      rect: {
        x: ar.x + PAD + i * (ACTION_BTN_SIZE + ACTION_BTN_GAP),
        y: ar.y + PAD + HDR,
        w: ACTION_BTN_SIZE,
        h: ACTION_BTN_SIZE,
      },
      action,
      key,
      label,
    }));
  }

  private upgradeBtnRects(ar: Rect): { rect: Rect; path: "outpost" | "research_lab"; label: string }[] {
    const options: ["outpost" | "research_lab", string][] = [
      ["outpost", "Outpost"],
      ["research_lab", "Research Lab"],
    ];
    return options.map(([path, label], i) => ({
      rect: {
        x: ar.x + PAD,
        y: ar.y + PAD + HDR + i * (UPGRADE_BTN_H + UPGRADE_BTN_GAP),
        w: UPGRADE_BTN_W,
        h: UPGRADE_BTN_H,
      },
      path,
      label,
    }));
  }

  /** Research grid uses the same layout as the CC build grid. */
  private researchBtnRects(ar: Rect): { rect: Rect; ut: string }[] {
    return this.buildBtnRects(ar);
  }

  /** Returns true if the pointer is over the HUD (so world input is blocked). */
  pointerOver(ui: UI): boolean {
    const hudH = Hud.height(ui.h);
    return ui.input.mouseY >= ui.h - hudH;
  }

  render(ui: UI): void {
    const ctx = ui.ctx;
    const w = ui.w;
    const h = ui.h;
    const hudH = Hud.height(h);
    const { minimap, display, action } = this.sections(w, h, hudH);

    // panel backdrops
    ui.fillRect(display.x, display.y, display.w, display.h, SECTION_BG);
    ui.fillRect(action.x, action.y, action.w, action.h, SECTION_BG);
    // dividers
    ctx.strokeStyle = rgb(DIVIDER);
    ctx.lineWidth = 1;
    for (const r of [minimap, display]) {
      ctx.beginPath();
      ctx.moveTo(r.x + r.w - 0.5, r.y);
      ctx.lineTo(r.x + r.w - 0.5, r.y + r.h);
      ctx.stroke();
    }

    this.drawMinimap(ui, minimap);
    this.drawDisplay(ui, display);
    this.drawActions(ui, action);
  }

  // -- minimap ----------------------------------------------------------

  private minimapTransform(r: Rect): { ox: number; oy: number; scale: number } {
    const pad = 4;
    const innerW = r.w - pad * 2;
    const innerH = r.h - pad * 2;
    const scale = Math.min(innerW / this.view.mapWidth, innerH / this.view.mapHeight);
    const mw = this.view.mapWidth * scale;
    const mh = this.view.mapHeight * scale;
    return { ox: r.x + pad + (innerW - mw) / 2, oy: r.y + pad + (innerH - mh) / 2, scale };
  }

  private drawMinimap(ui: UI, r: Rect): void {
    const ctx = ui.ctx;
    ui.fillRect(r.x, r.y, r.w, r.h, MINIMAP_BG);
    const { ox, oy, scale } = this.minimapTransform(r);
    const w2m = (wx: number, wy: number): [number, number] => [ox + wx * scale, oy + wy * scale];

    ctx.save();
    ctx.beginPath();
    ctx.rect(r.x, r.y, r.w, r.h);
    ctx.clip();

    // obstacles
    ctx.fillStyle = rgb(OBSTACLE_MM);
    for (const o of this.obstacles) {
      const [mx, my] = w2m(o.x, o.y);
      if (o.shape === "rect") {
        const ow = Math.max(1, (o.w ?? 10) * scale);
        const oh = Math.max(1, (o.h ?? 10) * scale);
        ctx.fillRect(mx - ow / 2, my - oh / 2, ow, oh);
      } else {
        ctx.beginPath();
        ctx.arc(mx, my, Math.max(1, (o.r ?? 5) * scale), 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // entities
    for (const e of this.view.getEntities()) {
      const [mx, my] = w2m(e.x, e.y);
      if (e.t === "MS") {
        const ms = e as { ow: number | null };
        ctx.fillStyle = ms.ow == null ? "rgb(255,255,255)" : rgb(this.cfg.teamColor(ms.ow));
        const s = Math.max(2, 4 * scale);
        ctx.beginPath();
        ctx.moveTo(mx, my - s);
        ctx.lineTo(mx - s, my + s);
        ctx.lineTo(mx + s, my + s);
        ctx.closePath();
        ctx.fill();
      } else {
        const col = (e as { c?: RGB }).c ?? this.cfg.teamColor(e.tm);
        ctx.fillStyle = rgb(col);
        const size = e.t === "CC" ? 4 : e.t === "ME" ? 3 : 2;
        ctx.fillRect(mx - size / 2, my - size / 2, size, size);
      }
    }

    // camera viewport rect
    const vp = this.view.camera.getWorldViewportRect();
    const [vx, vy] = w2m(vp.x, vp.y);
    ctx.strokeStyle = "rgb(220,220,220)";
    ctx.lineWidth = 1;
    ctx.strokeRect(vx, vy, vp.w * scale, vp.h * scale);
    ctx.restore();
  }

  // -- selected-unit display -------------------------------------------

  private drawDisplay(ui: UI, r: Rect): void {
    const ctx = ui.ctx;
    const sel = this.view.selectedIds;
    const selected: AnyEntity[] = this.view.getEntities().filter((e) => sel.has(e.id));
    if (!selected.length) {
      drawText(ctx, "No selection", r.x + 12, r.y + r.h / 2, {
        size: 14,
        color: STAT_LABEL,
        baseline: "middle",
      });
      return;
    }
    if (selected.length === 1) {
      this.drawSingleInfo(ui, r, selected[0]);
      return;
    }
    // Group: counts per unit type
    const counts = new Map<string, { n: number; color: RGB; t2: boolean }>();
    for (const e of selected) {
      if (e.t !== "U") continue;
      const u = e as UnitEntity;
      const key = u.ut + (u.t2 ? "_t2" : "");
      const cur = counts.get(key);
      if (cur) cur.n++;
      else counts.set(key, { n: 1, color: u.c, t2: u.t2 });
    }
    drawText(ctx, `${selected.length} selected`, r.x + 12, r.y + 8, { size: 14, color: TITLE_COLOR });
    let bx = r.x + 12;
    const by = r.y + 32;
    for (const [key, info] of counts) {
      const ut = info.t2 ? key.slice(0, -3) : key;
      ctx.fillStyle = rgb(info.color);
      ctx.beginPath();
      ctx.arc(bx + 6, by + 8, 6, 0, Math.PI * 2);
      ctx.fill();
      const label = `${this.unitName(ut, info.t2)} ×${info.n}`;
      drawText(ctx, label, bx + 16, by + 2, { size: 13, color: STAT_LABEL });
      bx += 16 + measure(ctx, label, 13) + 18;
      if (bx > r.x + r.w - 80) break;
    }
  }

  /** Single-selection info panel: name, HP bar, stat rows, plating bar.
   *  Ports gui.py's _draw_unit_info stat rows for network entities. */
  private drawSingleInfo(ui: UI, r: Rect, e: AnyEntity): void {
    const ctx = ui.ctx;
    const left = r.x + 12;
    let y = r.y + 8;
    const ut = (e as { ut?: string }).ut ?? e.t;
    const isT2 = e.t === "U" && (e as UnitEntity).t2;
    drawText(ctx, this.unitName(ut, isT2), left, y, { size: 16, color: TITLE_COLOR });
    y += 22;

    // HP bar + numeric
    const bw = Math.min(r.w - 24, 150);
    const bh = 6;
    const ratio = e.mhp > 0 ? e.hp / e.mhp : 0;
    ui.fillRect(left, y, bw, bh, [60, 0, 0]);
    ui.fillRect(left, y, bw * ratio, bh, ratio > 0.35 ? [0, 220, 0] : [220, 0, 0]);
    drawText(ctx, `${Math.round(e.hp)}/${Math.round(e.mhp)}`, left + bw + 6, y - 3, {
      size: 12,
      color: STAT_VALUE,
    });
    y += bh + 6;

    // Stat rows (2 columns)
    const rows: [string, string][] = [];
    const stat = this.cfg.unitTypes[ut];
    if (stat && stat.speed > 0) rows.push(["Speed", String(Math.round(stat.speed))]);
    const weapon = stat?.weapon as
      | { damage?: number; range?: number; cooldown?: number; hits_only_friendly?: boolean }
      | undefined;
    if (weapon && stat?.can_attack !== false) {
      const dmg = weapon.damage ?? 0;
      rows.push(dmg < 0 ? ["Heal", String(Math.abs(dmg))] : ["Dmg", String(dmg)]);
      const baseRange = Math.round(weapon.range ?? 0);
      const liveRange = Math.round((e as UnitEntity).rng ?? baseRange);
      rows.push(["Range", liveRange > baseRange ? `${baseRange} (+${liveRange - baseRange})` : String(baseRange)]);
      const cd = weapon.cooldown ?? 0;
      rows.push(["CD", Number.isInteger(cd) ? `${cd}s` : `${cd.toFixed(1)}s`]);
    }
    const baseLos = Math.round(stat?.los ?? 0);
    const liveLos = Math.round((e as UnitEntity).los ?? baseLos);
    if (liveLos > 0) {
      rows.push(["LOS", liveLos > baseLos ? `${baseLos} (+${liveLos - baseLos})` : String(baseLos)]);
    }
    if (e.t === "CC") {
      const bp = (e as CCEntity).bp ?? 0;
      if (bp > 0) rows.push(["Bonus", `+${bp}%`]);
    }
    if (e.t === "ME") {
      const me = e as MEEntity;
      rows.push(["Bonus", `+${me.meb ?? 0}%`]);
      if (me.us.startsWith("upgrading")) {
        const dur = me.us === "upgrading_outpost" ? this.cfg.outpostUpgradeDuration : this.cfg.researchLabUpgradeDuration;
        const secs = Math.max(0, Math.ceil((1 - (me.utt ?? 0)) * dur));
        rows.push(["Upgrade", `${secs}s`]);
      } else if (me.us === "choosing_research") {
        rows.push(["Status", "Select unit"]);
      } else if (me.us === "research_lab" && me.rut) {
        rows.push(["Research", this.unitName(me.rut, true)]);
      }
    }
    // Ability summary rows (units only; ME reinforce has its own bar below)
    if (e.t === "U") {
      for (const ab of (e as UnitEntity).abs ?? []) {
        const name = this.displayName(ab.n);
        rows.push([name, this.abilityStatus(ab) || "—"]);
      }
    }

    const colW = 95;
    let lastRowY = y;
    for (let i = 0; i < rows.length; i++) {
      const c = i % 2;
      const ro = Math.floor(i / 2);
      const sy = y + ro * 16;
      if (sy + 16 > r.y + r.h) break;
      const sx = left + c * colW;
      const [label, value] = rows[i];
      drawText(ctx, `${label}: `, sx, sy, { size: 12, color: STAT_LABEL });
      drawText(ctx, value, sx + measure(ctx, `${label}: `, 12), sy, { size: 12, color: STAT_VALUE });
      lastRowY = sy + 16;
    }

    // Reinforce plating progress bar (metal extractors)
    if (e.t === "ME") {
      const me = e as MEEntity;
      const maxStacks = this.cfg.reinforce.max_stacks;
      const stacks = me.rst ?? 0;
      const full = stacks >= maxStacks;
      const progress = full ? 1 : (stacks + (me.rsp ?? 0)) / maxStacks;
      const labelY = lastRowY + 4;
      const barW = Math.min(r.w - 24, 150);
      const barH = 8;
      if (labelY + 16 + barH <= r.y + r.h) {
        drawText(ctx, full ? "Plating: Reinforced" : `Plating: ${stacks}/${maxStacks}`, left, labelY, {
          size: 12,
          color: STAT_LABEL,
        });
        const barY = labelY + 16;
        ui.fillRect(left, barY, barW, barH, [40, 40, 50]);
        ui.fillRect(left, barY, barW * progress, barH, full ? [100, 255, 140] : [200, 200, 60]);
        ctx.strokeStyle = "rgb(20,20,28)";
        ctx.lineWidth = 1;
        for (let i = 1; i < maxStacks; i++) {
          const tx = left + (barW * i) / maxStacks;
          ctx.beginPath();
          ctx.moveTo(tx, barY);
          ctx.lineTo(tx, barY + barH - 1);
          ctx.stroke();
        }
      }
    }
  }

  private abilityStatus(ab: Ability): string {
    if (ab.a) return "Active";
    if (ab.s !== undefined && ab.ms !== undefined) return `${ab.s}/${ab.ms}`;
    if (ab.tm !== undefined && ab.tm > 0) return `${ab.tm.toFixed(1)}s`;
    return "";
  }

  private displayName(ut: string): string {
    return ut.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  private unitName(ut: string, t2: boolean): string {
    if (t2) return this.cfg.t2Names[ut] ?? `${this.displayName(ut)} T2`;
    return this.displayName(ut);
  }

  // -- action / build panel --------------------------------------------

  private drawActions(ui: UI, ar: Rect): void {
    const ctx = ui.ctx;
    const cc = this.view.getSelectedCC();
    const me = this.view.getSelectedME();
    if (cc) {
      drawText(ctx, "Build", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
      const current = cc.st;
      const teamT2 = this.view.t2Upgrades.get(this.view.myTeam) ?? new Set<string>();
      const rects = this.buildBtnRects(ar);
      let hoveredType: string | null = null;
      for (let i = 0; i < rects.length; i++) {
        const { rect, ut } = rects[i];
        const selected = ut === current;
        const hover = !ui.pressConsumed && this.inRect(ui, rect);
        if (hover) hoveredType = ut;
        this.drawButton(ui, rect, "", BUILD_HOTKEY_LETTERS[i] ?? "", false);
        this.drawUnitSymbol(ui, rect, ut, cc.c ?? this.cfg.teamColor(cc.tm));
        if (selected) {
          // Producing: green border instead of a filled button, so the unit
          // icon keeps its team color rather than turning into a cutout.
          ctx.strokeStyle = rgb(BTN_SELECTED);
          ctx.lineWidth = 2;
          ctx.strokeRect(rect.x + 1, rect.y + 1, rect.w - 2, rect.h - 2);
        }
        if (teamT2.has(ut)) this.drawT2Chevron(ui, rect.x + rect.w - 7, rect.y + 7);
      }
      if (hoveredType) this.drawUnitTooltip(ui, ar, hoveredType, teamT2.has(hoveredType));
    } else if (me && this.view.enableT2) {
      this.drawExtractorActions(ui, ar, me);
    } else {
      drawText(ctx, "Actions", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
      let btnBottom = ar.y + PAD + HDR;
      const units = this.view.selectedUnits();
      let hoveredAction: { action: string; key: string; label: string } | null = null;
      for (const btn of this.actionBtnRects(ar)) {
        const { rect, action, key, label } = btn;
        const active =
          (action === "attack" && this.view.attackMode) ||
          (action === "fight" && this.view.fightMode) ||
          this.view.actionFlashing(action);
        // Hold fire renders as a held-down toggle while the selection has it on.
        const pressed = action === "hold_fire" && units.length > 0 && units.every((u) => u.hf);
        if (!ui.pressConsumed && this.inRect(ui, rect)) hoveredAction = btn;
        this.drawButton(ui, rect, label, key, active, pressed, 9);
        btnBottom = Math.max(btnBottom, rect.y + rect.h);
      }
      // Abilities panel for a single selected unit
      const sel = this.view.selectedIds;
      if (units.length === 1 && sel.size === 1) {
        this.drawAbilitiesPanel(ui, ar, units[0], btnBottom + 8);
      }
      if (hoveredAction) this.drawActionTooltip(ui, ar, hoveredAction);
    }
  }

  /** Small green chevron marking a unit type as T2 for the player's team. */
  private drawT2Chevron(ui: UI, x: number, y: number, size = 5): void {
    const ctx = ui.ctx;
    ctx.strokeStyle = "rgb(100,255,140)";
    ctx.lineWidth = 2;
    for (const dy of [0, 4]) {
      ctx.beginPath();
      ctx.moveTo(x - size, y + dy + size / 2);
      ctx.lineTo(x, y + dy - size / 2);
      ctx.lineTo(x + size, y + dy + size / 2);
      ctx.stroke();
    }
  }

  /** Abilities list below the action buttons (gui.py _draw_abilities_panel). */
  private drawAbilitiesPanel(ui: UI, ar: Rect, unit: UnitEntity, y: number): void {
    const ctx = ui.ctx;
    const abilities = unit.abs ?? [];
    if (!abilities.length) return;
    const innerW = ar.w - PAD * 2;
    if (y + 18 > ar.y + ar.h) return;

    drawText(ctx, "Abilities", ar.x + PAD, y, { size: 13, color: TITLE_COLOR });
    y += 17;

    for (const ab of abilities) {
      if (y >= ar.y + ar.h - 4) break;
      const status = this.abilityStatus(ab);
      const nameLine = this.displayName(ab.n) + (status ? ` - ${status}` : "");
      drawText(ctx, nameLine, ar.x + PAD, y, { size: 13, color: STAT_VALUE });
      // Hover highlight on the name line
      const nameW = measure(ctx, nameLine, 13);
      if (this.inRect(ui, { x: ar.x + PAD, y, w: nameW, h: 15 })) {
        ctx.strokeStyle = rgb(TITLE_COLOR);
        ctx.lineWidth = 1;
        ctx.strokeRect(ar.x + PAD - 2 + 0.5, y - 1 + 0.5, nameW + 4, 16);
      }
      y += 16;
      const desc = this.cfg.abilityDescriptions[ab.n] ?? "";
      if (desc) {
        for (const line of this.wrapText(ctx, desc, 11, innerW)) {
          if (y + 13 > ar.y + ar.h - 2) break;
          drawText(ctx, line, ar.x + PAD, y, { size: 11, color: STAT_LABEL });
          y += 13;
        }
      }
      y += 4;
    }
  }

  /** ME upgrade/research panel (gui.py _draw_extractor_actions). */
  private drawExtractorActions(ui: UI, ar: Rect, me: MEEntity): void {
    const ctx = ui.ctx;
    const us = me.us;

    if (us === "base") {
      const disabled = !me.ifr;
      drawText(ctx, "Upgrade", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
      let hoveredPath: "outpost" | "research_lab" | null = null;
      for (const { rect, path, label } of this.upgradeBtnRects(ar)) {
        const hover = !ui.pressConsumed && this.inRect(ui, rect);
        if (hover) hoveredPath = path;
        const bg = disabled ? BTN_DISABLED_BG : hover ? BTN_HOVER : BTN_NORMAL;
        ui.fillRect(rect.x, rect.y, rect.w, rect.h, bg);
        ctx.strokeStyle = rgb(disabled ? ([60, 60, 75] as RGB) : DIVIDER);
        ctx.lineWidth = 1;
        ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.w - 1, rect.h - 1);
        drawText(ctx, label, rect.x + rect.w / 2, rect.y + rect.h / 2, {
          size: 12,
          color: disabled ? BTN_DISABLED_TEXT : TITLE_COLOR,
          align: "center",
          baseline: "middle",
        });
      }
      if (hoveredPath) {
        const missing = this.cfg.reinforce.max_stacks - (me.rst ?? 0);
        this.drawUpgradeTooltip(ui, ar, hoveredPath, disabled, missing);
      }
    } else if (us === "choosing_research") {
      drawText(ctx, "Select Research", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
      const teamT2 = new Set([
        ...(this.view.t2Upgrades.get(me.tm) ?? []),
        ...(this.view.t2Researching.get(me.tm) ?? []),
      ]);
      let hoveredType: string | null = null;
      for (const { rect, ut } of this.researchBtnRects(ar)) {
        const alreadyT2 = teamT2.has(ut);
        const hover = !ui.pressConsumed && this.inRect(ui, rect);
        if (hover) hoveredType = ut;
        ui.fillRect(rect.x, rect.y, rect.w, rect.h, hover && !alreadyT2 ? BTN_HOVER : BTN_NORMAL);
        ctx.strokeStyle = rgb(DIVIDER);
        ctx.lineWidth = 1;
        ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.w - 1, rect.h - 1);
        this.drawUnitSymbol(ui, rect, ut, alreadyT2 ? [60, 60, 70] : this.cfg.teamColor(me.tm));
      }
      if (hoveredType) this.drawUnitTooltip(ui, ar, hoveredType, true);
    } else if (us.startsWith("upgrading")) {
      drawText(ctx, "Upgrading...", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
      const dur = us === "upgrading_outpost" ? this.cfg.outpostUpgradeDuration : this.cfg.researchLabUpgradeDuration;
      const progress = me.utt ?? 0;
      const secs = Math.max(0, Math.ceil((1 - progress) * dur));
      drawText(ctx, `${secs}s remaining`, ar.x + PAD, ar.y + 26, { size: 12, color: STAT_VALUE });
      const barW = Math.min(ar.w - 16, 180);
      ui.fillRect(ar.x + PAD, ar.y + 46, barW, 8, [40, 40, 50]);
      ui.fillRect(ar.x + PAD, ar.y + 46, barW * progress, 8, [200, 200, 60]);
    } else if (us === "outpost") {
      drawText(ctx, "Outpost", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
    } else if (us === "research_lab") {
      drawText(ctx, "Research Lab", ar.x + PAD, ar.y + 4, { size: 14, color: TITLE_COLOR });
      if (me.rut) {
        drawText(ctx, `Producing: ${this.unitName(me.rut, true)}`, ar.x + PAD, ar.y + 26, {
          size: 12,
          color: STAT_VALUE,
        });
      }
    }
  }

  /** Draw a unit-type symbol polygon centered in a button rect. */
  private drawUnitSymbol(ui: UI, rect: Rect, ut: string, color: RGB): void {
    const ctx = ui.ctx;
    const cx = rect.x + rect.w / 2;
    const cy = rect.y + rect.h / 2;
    const sym = this.cfg.unitTypes[ut]?.symbol;
    ctx.fillStyle = rgb(color);
    ctx.strokeStyle = rgb(color);
    ctx.lineWidth = 1;
    if (sym && sym.length) {
      const sc = 0.9;
      ctx.beginPath();
      sym.forEach(([px, py], i) => {
        if (i === 0) ctx.moveTo(cx + px * sc, cy + py * sc);
        else ctx.lineTo(cx + px * sc, cy + py * sc);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.arc(cx, cy, 7, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // -- tooltips ----------------------------------------------------------

  private wrapText(ctx: CanvasRenderingContext2D, text: string, size: number, maxW: number): string[] {
    const lines: string[] = [];
    let cur = "";
    for (const word of text.split(/\s+/)) {
      const test = (cur + " " + word).trim();
      if (measure(ctx, test, size) <= maxW) cur = test;
      else {
        if (cur) lines.push(cur);
        cur = word;
      }
    }
    if (cur) lines.push(cur);
    return lines;
  }

  /** Unit stats tooltip above the action panel (gui.py _draw_tooltip).
   *  With showT2, shows the T2 variant's values with colored diffs vs T1. */
  private drawUnitTooltip(ui: UI, ar: Rect, ut: string, showT2: boolean): void {
    const ctx = ui.ctx;
    const t1: UnitStat | undefined = this.cfg.unitTypes[ut];
    if (!t1) return;
    const stats = showT2 ? this.cfg.unitTypes[`${ut}_t2`] ?? t1 : t1;

    type Row = [string, string, string, RGB | null];
    const rows: Row[] = [];
    const diff = (v2: number, v1: number): [string, RGB | null] => {
      if (!showT2 || v2 === v1) return ["", null];
      const d = v2 - v1;
      return [` (${d > 0 ? "+" : ""}${d})`, d > 0 ? DIFF_GOOD : DIFF_BAD];
    };

    const [hpD, hpC] = diff(stats.hp, t1.hp);
    rows.push(["HP", String(stats.hp), hpD, hpC]);
    const [spD, spC] = diff(stats.speed, t1.speed);
    rows.push(["Speed", String(stats.speed), spD, spC]);

    const wpn = stats.weapon as { damage?: number; range?: number; cooldown?: number } | undefined;
    const t1w = t1.weapon as { damage?: number; range?: number; cooldown?: number } | undefined;
    if (wpn) {
      const dmg = wpn.damage ?? 0;
      const label = dmg < 0 ? "Heal/pulse" : "Damage";
      const val = Math.abs(dmg);
      const t1val = t1w ? Math.abs(t1w.damage ?? dmg) : val;
      const [dD, dC] = diff(val, t1val);
      rows.push([label, String(val), dD, dC]);
      const [rD, rC] = t1w ? diff(Math.round(wpn.range ?? 0), Math.round(t1w.range ?? 0)) : ["", null] as [string, RGB | null];
      rows.push(["Range", String(Math.round(wpn.range ?? 0)), rD, rC]);
      const cd = wpn.cooldown ?? 0;
      const t1cd = t1w?.cooldown ?? cd;
      let cdD = "";
      let cdC: RGB | null = null;
      if (showT2 && cd !== t1cd) {
        const d = cd - t1cd;
        cdD = ` (${d > 0 ? "+" : ""}${d.toFixed(1)}s)`;
        cdC = d > 0 ? DIFF_BAD : DIFF_GOOD; // longer cooldown is bad
      }
      rows.push(["Cooldown", Number.isInteger(cd) ? `${cd}s` : `${cd.toFixed(1)}s`, cdD, cdC]);
    }

    const name = this.unitName(ut, showT2);
    const ttW = 180 + (showT2 ? 50 : 0);
    const ttH = TT_PAD + TT_LINE_H + 4 + rows.length * TT_LINE_H + TT_PAD;
    const ttX = ar.x + 10;
    const ttY = ar.y - ttH - 6;

    ui.fillRect(ttX, ttY, ttW, ttH, TT_BG);
    ctx.strokeStyle = rgb(TT_BORDER);
    ctx.lineWidth = 1;
    ctx.strokeRect(ttX + 0.5, ttY + 0.5, ttW - 1, ttH - 1);

    drawText(ctx, name, ttX + TT_PAD, ttY + TT_PAD, { size: 15, color: [220, 220, 240] });
    let ry = ttY + TT_PAD + TT_LINE_H + 4;
    for (const [label, value, diffText, diffColor] of rows) {
      drawText(ctx, label, ttX + TT_PAD, ry, { size: 12, color: [140, 140, 165] });
      const vx = ttX + TT_PAD + 80;
      drawText(ctx, value, vx, ry, { size: 12, color: STAT_VALUE });
      if (diffText && diffColor) {
        drawText(ctx, diffText, vx + measure(ctx, value, 12), ry, { size: 12, color: diffColor });
      }
      ry += TT_LINE_H;
    }
  }

  /** Outpost / Research Lab upgrade tooltip (gui.py _draw_upgrade_tooltip). */
  private drawUpgradeTooltip(
    ui: UI,
    ar: Rect,
    path: "outpost" | "research_lab",
    disabled: boolean,
    missingStacks: number,
  ): void {
    const ctx = ui.ctx;
    let title: string;
    let desc: string;
    let duration: number;
    let rows: [string, string, RGB | null][];
    if (path === "outpost") {
      const op = this.cfg.outpost;
      title = "Outpost";
      desc = "Fortifies the extractor with a defensive laser, extended vision, and self-repair.";
      duration = this.cfg.outpostUpgradeDuration;
      rows = [
        ["HP", `+${op.hp_bonus}`, DIFF_GOOD],
        ["Spawn bonus", `${Math.round(this.cfg.t2SpawnBonus * 100)}%`, DIFF_GOOD],
        ["Self-heal", `${op.heal_per_sec} HP/s`, DIFF_GOOD],
        ["Vision", `${Math.round(op.los)} px`, DIFF_GOOD],
        ["Weapon", `${op.laser_damage} dmg`, null],
        ["Range", `${Math.round(op.laser_range)} px`, null],
        ["Cooldown", `${op.laser_cooldown}s`, null],
      ];
    } else {
      title = "Research Lab";
      desc = "Unlocks T2 production for one chosen unit type. Affected CCs spawn the T2 variant.";
      duration = this.cfg.researchLabUpgradeDuration;
      rows = [
        ["HP", `+${this.cfg.researchLabHpBonus}`, DIFF_GOOD],
        ["Spawn bonus", `${Math.round(this.cfg.t2SpawnBonus * 100)}%`, DIFF_GOOD],
        ["Unlocks", "T2 unit research", DIFF_GOOD],
      ];
    }

    const ttW = 240;
    const innerW = ttW - TT_PAD * 2;
    const descLines = this.wrapText(ctx, desc, 12, innerW);
    const titleH = TT_LINE_H + 4;
    const descH = descLines.length * (TT_LINE_H - 2) + 4;
    const rowsH = rows.length * TT_LINE_H;
    const footerH = TT_LINE_H + 2;
    const reqH = disabled ? TT_LINE_H + 2 : 0;
    const ttH = TT_PAD + titleH + descH + rowsH + footerH + reqH + TT_PAD;
    const ttX = ar.x + 10;
    const ttY = ar.y - ttH - 6;

    ui.fillRect(ttX, ttY, ttW, ttH, TT_BG);
    ctx.strokeStyle = rgb(TT_BORDER);
    ctx.lineWidth = 1;
    ctx.strokeRect(ttX + 0.5, ttY + 0.5, ttW - 1, ttH - 1);

    drawText(ctx, title, ttX + TT_PAD, ttY + TT_PAD, { size: 15, color: [220, 220, 240] });
    let y = ttY + TT_PAD + titleH;
    for (const line of descLines) {
      drawText(ctx, line, ttX + TT_PAD, y, { size: 12, color: [160, 160, 180] });
      y += TT_LINE_H - 2;
    }
    y += 4;
    for (const [label, value, color] of rows) {
      drawText(ctx, label, ttX + TT_PAD, y, { size: 12, color: [140, 140, 165] });
      drawText(ctx, value, ttX + TT_PAD + 100, y, { size: 12, color: color ?? STAT_VALUE });
      y += TT_LINE_H;
    }
    drawText(ctx, `Build time: ${Math.round(duration)}s`, ttX + TT_PAD, y, {
      size: 12,
      color: [200, 200, 100],
    });
    y += TT_LINE_H;
    if (disabled) {
      const plural = missingStacks !== 1 ? "s" : "";
      drawText(ctx, `Requires ${missingStacks} more plating${plural} to upgrade`, ttX + TT_PAD, y, {
        size: 12,
        color: [255, 110, 110],
      });
    }
  }

  private drawButton(
    ui: UI,
    rect: Rect,
    label: string,
    key: string,
    selected: boolean,
    pressed = false,
    labelSize = 13,
  ): void {
    const ctx = ui.ctx;
    const hover = !ui.pressConsumed && this.inRect(ui, rect);
    const bg = selected ? BTN_SELECTED : pressed ? BTN_PRESSED : hover ? BTN_HOVER : BTN_NORMAL;
    ui.fillRect(rect.x, rect.y, rect.w, rect.h, bg);
    ctx.strokeStyle = rgb(pressed ? BTN_SELECTED : DIVIDER);
    ctx.lineWidth = 1;
    ctx.strokeRect(rect.x + 0.5, rect.y + 0.5, rect.w - 1, rect.h - 1);
    drawText(ctx, this.ellipsize(ctx, label, labelSize, rect.w - 4), rect.x + rect.w / 2, rect.y + rect.h / 2, {
      size: labelSize,
      color: selected ? [20, 20, 20] : TITLE_COLOR,
      align: "center",
      baseline: "middle",
    });
    if (key) drawText(ctx, key, rect.x + 3, rect.y + 2, { size: 10, color: HOTKEY_COLOR });
  }

  private ellipsize(ctx: CanvasRenderingContext2D, text: string, size: number, maxW: number): string {
    if (!text || measure(ctx, text, size) <= maxW) return text;
    let t = text;
    while (t.length > 1 && measure(ctx, t + "…", size) > maxW) t = t.slice(0, -1);
    return t.trimEnd() + "…";
  }

  /** Hover tooltip for an action button: full command name, hotkey, and a
   *  brief description of what the command does. */
  private drawActionTooltip(ui: UI, ar: Rect, btn: { action: string; key: string; label: string }): void {
    const ctx = ui.ctx;
    const desc = ACTION_DESCRIPTIONS[btn.action] ?? "";
    const ttW = 240;
    const innerW = ttW - TT_PAD * 2;
    const descLines = desc ? this.wrapText(ctx, desc, 12, innerW) : [];
    const ttH = TT_PAD + TT_LINE_H + 4 + descLines.length * (TT_LINE_H - 2) + TT_PAD;
    const ttX = ar.x + 10;
    const ttY = ar.y - ttH - 6;

    ui.fillRect(ttX, ttY, ttW, ttH, TT_BG);
    ctx.strokeStyle = rgb(TT_BORDER);
    ctx.lineWidth = 1;
    ctx.strokeRect(ttX + 0.5, ttY + 0.5, ttW - 1, ttH - 1);

    drawText(ctx, btn.label, ttX + TT_PAD, ttY + TT_PAD, { size: 15, color: [220, 220, 240] });
    drawText(ctx, `[${btn.key}]`, ttX + TT_PAD + measure(ctx, btn.label, 15) + 8, ttY + TT_PAD + 2, {
      size: 12,
      color: STAT_LABEL,
    });
    let y = ttY + TT_PAD + TT_LINE_H + 4;
    for (const line of descLines) {
      drawText(ctx, line, ttX + TT_PAD, y, { size: 12, color: [160, 160, 180] });
      y += TT_LINE_H - 2;
    }
  }

  private inRect(ui: UI, r: Rect): boolean {
    const { mouseX: mx, mouseY: my } = ui.input;
    return mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h;
  }

  /** Handle a click in the HUD (call when pointer released over HUD). */
  handleClick(ui: UI): void {
    if (!ui.input.released) return;
    const hudH = Hud.height(ui.h);
    const { minimap, action } = this.sections(ui.w, ui.h, hudH);

    // Minimap click -> center camera
    if (this.inRect(ui, minimap)) {
      const { ox, oy, scale } = this.minimapTransform(minimap);
      const wx = (ui.input.mouseX - ox) / scale;
      const wy = (ui.input.mouseY - oy) / scale;
      this.view.camera.centerOn(wx, wy);
      ui.pressConsumed = true;
      return;
    }

    // Action panel clicks
    const cc = this.view.getSelectedCC();
    const me = this.view.getSelectedME();
    if (cc) {
      for (const { rect, ut } of this.buildBtnRects(action)) {
        if (this.inRect(ui, rect)) {
          this.view.setSpawnType(ut);
          ui.pressConsumed = true;
          return;
        }
      }
    } else if (me && this.view.enableT2) {
      if (me.us === "base" && me.ifr) {
        for (const { rect, path } of this.upgradeBtnRects(action)) {
          if (this.inRect(ui, rect)) {
            this.view.upgradeExtractor(me.id, path);
            ui.pressConsumed = true;
            return;
          }
        }
      } else if (me.us === "choosing_research") {
        const teamT2 = new Set([
          ...(this.view.t2Upgrades.get(me.tm) ?? []),
          ...(this.view.t2Researching.get(me.tm) ?? []),
        ]);
        for (const { rect, ut } of this.researchBtnRects(action)) {
          if (this.inRect(ui, rect) && !teamT2.has(ut)) {
            this.view.setResearchType(me.id, ut);
            ui.pressConsumed = true;
            return;
          }
        }
      }
    } else {
      for (const { rect, action: act } of this.actionBtnRects(action)) {
        if (this.inRect(ui, rect)) {
          this.view.hudAction(act);
          ui.pressConsumed = true;
          return;
        }
      }
    }
  }
}
