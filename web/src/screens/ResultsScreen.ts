// Post-game results: Victory / Defeat / Draw plus the multi-line stat graphs
// (a port of screens/results.py + ui/widgets.py MultiLineGraph): tabbed
// per-team time series with a clickable legend and hover tooltip.

import { Screen, type Transition } from "../app/Screen";
import type { App } from "../app/App";
import type { StatsPayload, TeamStatsSeries } from "../net/MessageTypes";
import { HDR_COLOR, BTN_HEIGHT, BTN_WIDTH, rgb, type RGB } from "../ui/theme";
import { drawText, measure } from "../ui/Text";

// ui/theme.py GRAPH_LINE_COLORS
const GRAPH_LINE_COLORS: RGB[] = [
  [80, 160, 255],
  [255, 90, 90],
  [80, 220, 160],
  [255, 165, 60],
  [180, 100, 255],
  [80, 220, 220],
  [220, 220, 80],
  [220, 80, 160],
];
const GRID_COLOR = "rgba(70,70,90,0.5)";
const AXIS_TEXT: RGB = [140, 140, 165];
const PANEL_BG: RGB = [16, 16, 24];
const PANEL_BORDER: RGB = [60, 60, 80];

const TABS: [keyof TeamStatsSeries | "step_ms", string][] = [
  ["cc_health", "CC HP"],
  ["army_count", "Army Size"],
  ["units_killed", "Kills"],
  ["damage_dealt", "Damage"],
  ["healing_done", "Healing"],
  ["metal_spots", "Build %"],
  ["apm", "APM"],
  ["step_ms", "Step ms"],
];

interface Series {
  name: string;
  data: number[];
  color: RGB;
}

function lighten(c: RGB, amount = 0.5): RGB {
  return [
    Math.min(255, Math.round(c[0] + (255 - c[0]) * amount)),
    Math.min(255, Math.round(c[1] + (255 - c[1]) * amount)),
    Math.min(255, Math.round(c[2] + (255 - c[2]) * amount)),
  ];
}

function fmtTime(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export class ResultsScreen extends Screen {
  private winner: number;
  private myTeam: number;
  private stats: StatsPayload | null;
  private tab = 0;
  private hidden = new Set<string>();
  private teamIds: number[] = [];
  private teamNames = new Map<number, string>();
  private ccHp = 1000;

  constructor(app: App, data: Record<string, unknown>) {
    super(app);
    this.winner = (data.winner as number) ?? 0;
    this.myTeam = (data.myTeam as number) ?? 0;
    this.stats = (data.stats as StatsPayload | null) ?? null;

    if (this.stats?.teams) {
      this.teamIds = Object.keys(this.stats.teams)
        .map(Number)
        .filter((n) => !Number.isNaN(n))
        .sort((a, b) => a - b);
    }
    // Team labels from the lobby roster (fall back to "Team N")
    const gs = app.conn?.gameStart;
    const names = gs?.player_names ?? {};
    const teams = gs?.player_team ?? {};
    for (const tid of this.teamIds) {
      const members = Object.entries(teams)
        .filter(([, t]) => t === tid)
        .map(([pid]) => names[pid])
        .filter(Boolean);
      this.teamNames.set(tid, members.length ? `${members.join(", ")}` : `Team ${tid}`);
    }
    const cc = (app.conn?.serverConfig?.command_center as Record<string, number> | undefined) ?? {};
    this.ccHp = cc.hp ?? 1000;
  }

  render(_dt: number): Transition | null {
    const { ui } = this;
    const ctx = ui.ctx;
    const cx = ui.w / 2;
    const hasStats = !!(this.stats?.timestamps?.length && this.teamIds.length);

    let title: string;
    let color: RGB;
    if (this.winner === -1) {
      title = "Draw";
      color = [200, 200, 200];
    } else if (this.winner === this.myTeam) {
      title = "Victory!";
      color = [80, 255, 120];
    } else {
      title = "Defeat";
      color = [255, 80, 80];
    }

    if (!hasStats) {
      // Simple fallback view (no stats payload)
      drawText(ctx, title, cx, ui.h / 2 - 80, { size: 72, color, align: "center", bold: true });
      const sub = this.winner > 0 ? `Team ${this.winner} wins` : this.winner === -1 ? "No survivors" : "";
      if (sub) drawText(ctx, sub, cx, ui.h / 2, { size: 24, color: HDR_COLOR, align: "center" });
    } else {
      drawText(ctx, title, cx, 18, { size: 40, color, align: "center", bold: true });
      const sub = this.winner > 0 ? `Team ${this.winner} wins` : this.winner === -1 ? "No survivors" : "";
      if (sub) drawText(ctx, sub, cx, 64, { size: 16, color: HDR_COLOR, align: "center" });

      // Tabs
      const tabY = 92;
      const tabW = 86;
      const tabH = 28;
      const totalW = TABS.length * (tabW + 4) - 4;
      let tx = cx - totalW / 2;
      for (let i = 0; i < TABS.length; i++) {
        const active = i === this.tab;
        const hover = !ui.pressConsumed && this.inRect(tx, tabY, tabW, tabH);
        ui.fillRect(tx, tabY, tabW, tabH, active ? [60, 90, 150] : hover ? [50, 50, 66] : [36, 36, 48]);
        ctx.strokeStyle = rgb(PANEL_BORDER);
        ctx.lineWidth = 1;
        ctx.strokeRect(tx + 0.5, tabY + 0.5, tabW - 1, tabH - 1);
        drawText(ctx, TABS[i][1], tx + tabW / 2, tabY + tabH / 2, {
          size: 12,
          color: active ? [235, 235, 245] : [170, 170, 190],
          align: "center",
          baseline: "middle",
        });
        if (hover && ui.input.released) {
          this.tab = i;
          ui.pressConsumed = true;
        }
        tx += tabW + 4;
      }

      // Graph panel
      const gx = 30;
      const gy = tabY + tabH + 12;
      const gw = ui.w - 60;
      const gh = Math.max(200, ui.h - gy - 140);
      this.drawGraph(gx, gy, gw, gh);
    }

    if (
      ui.button("results.menu", cx - BTN_WIDTH / 2, ui.h - 90, BTN_WIDTH, BTN_HEIGHT, "Back to Menu")
    ) {
      return { next: "main_menu" };
    }
    return null;
  }

  private inRect(x: number, y: number, w: number, h: number): boolean {
    const { mouseX: mx, mouseY: my } = this.ui.input;
    return mx >= x && mx <= x + w && my >= y && my <= y + h;
  }

  private buildSeries(): Series[] {
    const key = TABS[this.tab][0];
    const stats = this.stats!;
    const out: Series[] = [];
    if (key === "step_ms") {
      out.push({ name: "Step ms", data: stats.step_ms ?? [], color: GRAPH_LINE_COLORS[0] });
      return out;
    }
    const teams = stats.teams ?? {};
    for (const tid of this.teamIds) {
      const ts = teams[String(tid)] ?? {};
      const data = (ts[key] as number[] | undefined) ?? [];
      const color = GRAPH_LINE_COLORS[(tid - 1 + GRAPH_LINE_COLORS.length * 8) % GRAPH_LINE_COLORS.length];
      const name = this.teamNames.get(tid) ?? `Team ${tid}`;
      if (key === "apm") {
        out.push({ name: `${name} avg`, data, color });
        out.push({ name: `${name} now`, data: ts.apm_inst ?? [], color: lighten(color, 0.5) });
      } else {
        out.push({ name, data, color });
      }
    }
    return out;
  }

  /** MultiLineGraph port: grid, ticks, lines, clickable legend, hover tooltip. */
  private drawGraph(x: number, y: number, w: number, h: number): void {
    const { ui } = this;
    const ctx = ui.ctx;
    const key = TABS[this.tab][0];
    const timestamps = this.stats!.timestamps ?? [];
    const series = this.buildSeries();

    ui.fillRect(x, y, w, h, PANEL_BG);
    ctx.strokeStyle = rgb(PANEL_BORDER);
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);

    // Layout: plot area + right legend
    const legendW = 170;
    const padL = 52;
    const padR = 14;
    const padT = 14;
    const padB = 26;
    const px = x + padL;
    const py = y + padT;
    const pw = w - padL - padR - legendW;
    const ph = h - padT - padB;
    if (pw <= 10 || ph <= 10) return;

    const visible = series.filter((s) => !this.hidden.has(s.name) && s.data.length > 0);
    const n = timestamps.length;

    // Y range
    let yMax = 1;
    if (key === "cc_health") yMax = this.ccHp;
    else {
      for (const s of visible) for (const v of s.data) if (v > yMax) yMax = v;
      yMax *= 1.05;
    }
    const integerTicks = ["army_count", "units_killed", "apm", "damage_dealt", "healing_done"].includes(key);
    const ySuffix = key === "metal_spots" ? "%" : "";
    if (key === "metal_spots") yMax = Math.max(yMax, 100);

    // Grid + Y ticks
    const yTicks = 5;
    ctx.strokeStyle = GRID_COLOR;
    ctx.lineWidth = 1;
    for (let i = 0; i <= yTicks; i++) {
      const ty = py + ph - (ph * i) / yTicks;
      ctx.beginPath();
      ctx.moveTo(px, ty);
      ctx.lineTo(px + pw, ty);
      ctx.stroke();
      let val = (yMax * i) / yTicks;
      if (integerTicks) val = Math.round(val);
      const label = (key === "step_ms" ? val.toFixed(2) : String(Math.round(val))) + ySuffix;
      drawText(ctx, label, px - 6, ty - 6, { size: 10, color: AXIS_TEXT, align: "right" });
    }

    // X ticks (m:ss)
    const duration = n ? timestamps[n - 1] : 0;
    const xTicks = Math.min(6, Math.max(1, n - 1));
    for (let i = 0; i <= xTicks; i++) {
      const tx = px + (pw * i) / xTicks;
      ctx.beginPath();
      ctx.moveTo(tx, py);
      ctx.lineTo(tx, py + ph);
      ctx.stroke();
      const t = (duration * i) / xTicks;
      drawText(ctx, fmtTime(t), tx, py + ph + 6, { size: 10, color: AXIS_TEXT, align: "center" });
    }

    // Series lines
    const xFor = (i: number): number => (n > 1 ? px + (pw * timestamps[i]) / (duration || 1) : px);
    const yFor = (v: number): number => py + ph - Math.min(1, v / yMax) * ph;
    ctx.save();
    ctx.beginPath();
    ctx.rect(px, py, pw, ph);
    ctx.clip();
    for (const s of visible) {
      const m = Math.min(s.data.length, n);
      if (m < 2) continue;
      ctx.strokeStyle = rgb(s.color);
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < m; i++) {
        const lx = xFor(i);
        const ly = yFor(s.data[i]);
        if (i === 0) ctx.moveTo(lx, ly);
        else ctx.lineTo(lx, ly);
      }
      ctx.stroke();
    }
    ctx.restore();

    // Legend (right side, clickable to toggle series)
    let ly = py + 4;
    const lx = px + pw + 16;
    for (const s of series) {
      const isHidden = this.hidden.has(s.name);
      const rowH = 18;
      const hover = !ui.pressConsumed && this.inRect(lx, ly, legendW - 8, rowH);
      if (hover && ui.input.released) {
        if (isHidden) this.hidden.delete(s.name);
        else this.hidden.add(s.name);
        ui.pressConsumed = true;
      }
      ctx.fillStyle = isHidden ? "rgba(120,120,130,0.5)" : rgb(s.color);
      ctx.fillRect(lx, ly + 4, 12, 4);
      const label = s.name.length > 20 ? s.name.slice(0, 19) + "…" : s.name;
      drawText(ctx, label, lx + 18, ly, {
        size: 11,
        color: isHidden ? [110, 110, 120] : [190, 190, 205],
      });
      if (isHidden) {
        ctx.strokeStyle = "rgba(150,150,160,0.8)";
        ctx.beginPath();
        ctx.moveTo(lx + 18, ly + 6);
        ctx.lineTo(lx + 18 + measure(ctx, label, 11), ly + 6);
        ctx.stroke();
      }
      ly += rowH;
    }

    // Hover: vertical line + dots + tooltip
    const { mouseX: mx, mouseY: my } = ui.input;
    if (n > 1 && mx >= px && mx <= px + pw && my >= py && my <= py + ph) {
      // Nearest sample index by time
      const tAt = ((mx - px) / pw) * (duration || 1);
      let idx = 0;
      let best = Infinity;
      for (let i = 0; i < n; i++) {
        const d = Math.abs(timestamps[i] - tAt);
        if (d < best) {
          best = d;
          idx = i;
        }
      }
      const hx = xFor(idx);
      ctx.strokeStyle = "rgba(200,200,220,0.5)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(hx, py);
      ctx.lineTo(hx, py + ph);
      ctx.stroke();

      const lines: [string, string, RGB][] = [[fmtTime(timestamps[idx]), "", [200, 200, 220]]];
      for (const s of visible) {
        if (idx >= s.data.length) continue;
        const v = s.data[idx];
        ctx.fillStyle = rgb(s.color);
        ctx.beginPath();
        ctx.arc(hx, yFor(v), 3, 0, Math.PI * 2);
        ctx.fill();
        const valStr = key === "step_ms" ? v.toFixed(2) : String(Math.round(v)) + ySuffix;
        lines.push([s.name, valStr, s.color]);
      }

      // Tooltip box
      let ttW = 0;
      for (const [name, val] of lines) ttW = Math.max(ttW, measure(ctx, `${name}  ${val}`, 11) + 16);
      const ttH = lines.length * 16 + 8;
      let ttX = hx + 12;
      if (ttX + ttW > px + pw) ttX = hx - ttW - 12;
      let ttY = Math.min(my, py + ph - ttH);
      ui.fillRect(ttX, ttY, ttW, ttH, [18, 18, 26]);
      ctx.strokeStyle = rgb(PANEL_BORDER);
      ctx.strokeRect(ttX + 0.5, ttY + 0.5, ttW - 1, ttH - 1);
      let lineY = ttY + 5;
      for (const [name, val, c] of lines) {
        drawText(ctx, val ? `${name}  ${val}` : name, ttX + 8, lineY, { size: 11, color: c });
        lineY += 16;
      }
    }
  }
}
