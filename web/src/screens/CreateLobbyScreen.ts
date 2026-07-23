// Online lobby: configure players (local human + AI opponents), teams, colors,
// and match settings, then send start_game to the server. A faithful-enough
// port of screens/create_lobby.py for M1 — it produces the same start_game
// config shape that DedicatedServer._run_lobby_then_game consumes. (Spectators,
// handicaps polish, and online multi-human sync are deferred to M4 parity.)

import { Screen, type Transition } from "../app/Screen";
import type { App } from "../app/App";
import type { Choice } from "../ui/Widgets";
import {
  CONTENT_TEXT,
  HDR_COLOR,
  HEADING_FONT_SIZE,
  ONLINE_COLOR,
  PLAYER_COLORS,
  BTN_HEIGHT,
  BTN_WIDTH,
  DD_HEIGHT,
  rgb,
} from "../ui/theme";
import { drawText } from "../ui/Text";

interface Slot {
  isHuman: boolean;
  onlinePid: number; // server pid for the human; 0 for AI slots (assigned at start)
  aiId: string;
  team: number;
  colorIdx: number;
}

const MAP_PRESETS: Choice[] = [
  ["small", "Small"],
  ["medium", "Medium"],
  ["large", "Large"],
];
const MAP_SIZES: Record<string, [number, number]> = {
  small: [800, 600],
  medium: [1200, 800],
  large: [1800, 1200],
};
const TEAM_CHOICES: Choice[] = Array.from({ length: 8 }, (_, i) => [String(i + 1), `Team ${i + 1}`]);

const MAX_SLOTS = 8;
const MIN_SLOTS = 2;
const SLOT_ROW_H = 38;

export class CreateLobbyScreen extends Screen {
  private slots: Slot[] = [];
  private showOutdated = false;

  // settings
  private mapIdx = 0;
  private obstacles = 0;
  private metalSpots = 0;
  private timeLimit = 15;
  private enableT2 = false;
  private fog = false;

  private starting = false;
  private status = "";

  constructor(app: App) {
    super(app);
    const conn = app.conn;
    const localPid = conn?.playerId ?? 1;
    const firstAi = this.activeChoices()[0]?.[0] ?? "wander";
    // Slot 0: the local human; slot 1: one AI opponent on team 2.
    this.slots = [
      { isHuman: true, onlinePid: localPid, aiId: "human", team: 1, colorIdx: 0 },
      { isHuman: false, onlinePid: 0, aiId: firstAi, team: 2, colorIdx: 1 },
    ];
  }

  private activeChoices(): Choice[] {
    const conn = this.app.conn;
    if (!conn?.aiChoices) return [];
    const dep = new Set(conn.aiChoices.deprecated);
    return conn.aiChoices.choices
      .filter(([id]) => this.showOutdated || !dep.has(id))
      .map(([id, name]) => [id, name] as Choice);
  }

  private aiDropdownChoices(): Choice[] {
    return this.activeChoices();
  }

  private nextFreeColor(exclude: Slot | null): number {
    const used = new Set(this.slots.filter((s) => s !== exclude).map((s) => s.colorIdx));
    for (let i = 0; i < PLAYER_COLORS.length; i++) if (!used.has(i)) return i;
    return this.slots.length % PLAYER_COLORS.length;
  }

  private addSlot(): void {
    if (this.slots.length >= MAX_SLOTS) return;
    const firstAi = this.activeChoices()[0]?.[0] ?? "wander";
    this.slots.push({
      isHuman: false,
      onlinePid: 0,
      aiId: firstAi,
      team: 2,
      colorIdx: this.nextFreeColor(null),
    });
  }

  private removeSlot(i: number): void {
    if (this.slots.length <= MIN_SLOTS) return;
    if (this.slots[i].onlinePid) return; // don't remove the human
    this.slots.splice(i, 1);
  }

  /** Build the start_game config — mirrors create_lobby._send_online_start. */
  private buildConfig(): Record<string, unknown> {
    const conn = this.app.conn!;
    const playerTeam: Record<string, number> = {};
    const playerAi: Record<string, string> = {};
    const playerColors: Record<string, number> = {};

    const localPid = conn.playerId;
    // Humans (just the local player here).
    for (const s of this.slots) {
      if (s.onlinePid) {
        playerTeam[String(s.onlinePid)] = s.team;
        playerColors[String(s.onlinePid)] = s.colorIdx;
      }
    }
    if (!(String(localPid) in playerTeam)) {
      playerTeam[String(localPid)] = this.slots[0]?.team ?? 1;
    }

    // AI slots get non-conflicting pids after the human(s).
    const used = new Set<number>(Object.keys(playerTeam).map(Number));
    let nextPid = Math.max(0, ...used) + 1;
    for (const s of this.slots) {
      if (s.onlinePid || s.isHuman) continue;
      while (used.has(nextPid)) nextPid++;
      playerTeam[String(nextPid)] = s.team;
      playerAi[String(nextPid)] = s.aiId;
      playerColors[String(nextPid)] = s.colorIdx;
      used.add(nextPid);
      nextPid++;
    }

    const [mw, mh] = MAP_SIZES[MAP_PRESETS[this.mapIdx][0]];
    return {
      player_ai_ids: playerAi,
      player_team: playerTeam,
      player_colors: playerColors,
      player_handicaps: {},
      spectators: [],
      width: mw,
      height: mh,
      obstacle_count: this.obstacles,
      metal_spots: this.metalSpots,
      time_limit: this.timeLimit,
      enable_t2: this.enableT2,
      fog_of_war: this.fog,
    };
  }

  render(_dt: number): Transition | null {
    const { ui } = this;
    const ctx = ui.ctx;
    const w = ui.w;
    const h = ui.h;
    const conn = this.app.conn;

    if (!conn || conn.error) {
      return { next: "main_menu" };
    }

    // Once we've sent start_game, wait for the server to start the game.
    if (this.starting) {
      if (conn.gameStarted && conn.gameStart) {
        return { next: "game" };
      }
      drawText(ctx, "Starting game…", w / 2, h / 2, {
        size: 22,
        color: CONTENT_TEXT,
        align: "center",
      });
      return null;
    }

    drawText(ctx, "Online Lobby", w / 2, 16, {
      size: HEADING_FONT_SIZE,
      color: CONTENT_TEXT,
      align: "center",
      bold: true,
    });

    // -- two panels --
    const mid = Math.floor(w / 2);
    const lpX = Math.max(16, Math.floor(w * 0.03));
    const lpW = mid - lpX - 12;
    const rpX = mid + 12;
    const rpW = w - rpX - Math.max(16, Math.floor(w * 0.03));
    const panelTop = 56;
    const panelH = h - panelTop - 68;
    ui.panel(lpX, panelTop, lpW, panelH);
    ui.panel(rpX, panelTop, rpW, panelH);

    drawText(ctx, "Players", lpX + 14, 64, { size: 18, color: CONTENT_TEXT });
    drawText(ctx, "Settings", rpX + 14, 64, { size: 18, color: CONTENT_TEXT });

    // -- left: player slots --
    const labelX = lpX + 14;
    const aiX = labelX + 44;
    const aiW = 155;
    const teamX = aiX + aiW + 8;
    const teamW = 72;
    const removeX = teamX + teamW + 6;
    const slotYStart = 104;
    const aiChoices = this.aiDropdownChoices();

    drawText(ctx, "Team", teamX + 14, 86, { size: 13, color: HDR_COLOR });

    let removeRequest = -1;
    for (let i = 0; i < this.slots.length; i++) {
      const s = this.slots[i];
      const y = slotYStart + i * SLOT_ROW_H;
      const color = PLAYER_COLORS[s.colorIdx % PLAYER_COLORS.length];

      // color dot (click to cycle)
      const dotCx = labelX + 6;
      const dotCy = y + DD_HEIGHT / 2;
      ctx.beginPath();
      ctx.arc(dotCx, dotCy, 5, 0, Math.PI * 2);
      ctx.fillStyle = rgb(color);
      ctx.fill();
      const overDot =
        (ui.input.mouseX - dotCx) ** 2 + (ui.input.mouseY - dotCy) ** 2 <= 64;
      if (overDot) {
        ctx.strokeStyle = "rgb(255,255,255)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(dotCx, dotCy, 7, 0, Math.PI * 2);
        ctx.stroke();
        if (!ui.pressConsumed && ui.input.released) {
          s.colorIdx = (s.colorIdx + 1) % PLAYER_COLORS.length;
          ui.pressConsumed = true;
        }
      }

      drawText(ctx, `P${i + 1}`, labelX + 16, dotCy, {
        size: 16,
        color: CONTENT_TEXT,
        baseline: "middle",
      });

      if (s.isHuman) {
        drawText(ctx, `${conn.playerName} (You)`, aiX + 4, dotCy, {
          size: 16,
          color: ONLINE_COLOR,
          baseline: "middle",
        });
      } else {
        // AI dropdown
        const selIdx = Math.max(
          0,
          aiChoices.findIndex(([id]) => id === s.aiId),
        );
        const newIdx = ui.dropdown(`lobby.ai.${i}`, aiX, y, aiW, aiChoices, selIdx, {
          maxVisible: 6,
        });
        if (aiChoices[newIdx]) s.aiId = aiChoices[newIdx][0];
        // remove button
        if (this.slots.length > MIN_SLOTS) {
          if (ui.button(`lobby.rm.${i}`, removeX, y + (DD_HEIGHT - 26) / 2, 26, 26, "×")) {
            removeRequest = i;
          }
        }
      }

      // team dropdown
      const teamSel = Math.max(0, s.team - 1);
      const newTeam = ui.dropdown(`lobby.team.${i}`, teamX, y, teamW, TEAM_CHOICES, teamSel, {
        maxVisible: 8,
      });
      s.team = newTeam + 1;
    }
    if (removeRequest >= 0) this.removeSlot(removeRequest);

    // add-player button
    const addY = slotYStart + this.slots.length * SLOT_ROW_H + 5;
    if (this.slots.length < MAX_SLOTS) {
      if (ui.button("lobby.add", aiX, addY, 150, 28, "+ Add Player", { fontSize: 14 })) {
        this.addSlot();
      }
    }

    // -- right: settings --
    const rx = rpX + 14;
    let ry = slotYStart;
    drawText(ctx, "Map Size", rx, ry + 4, { size: 16, color: HDR_COLOR });
    this.mapIdx = ui.toggleGroup("lobby.map", rx, ry + 20, MAP_PRESETS, this.mapIdx);
    this.obstacles = ui.slider("lobby.obs", rx, ry + 72, Math.min(rpW - 20, 220), "Obstacles", 0, 20, this.obstacles, 1);
    this.metalSpots = ui.slider("lobby.metal", rx, ry + 126, Math.min(rpW - 20, 220), "Metal Spots / Side (0=random)", 0, 8, this.metalSpots, 1);
    this.timeLimit = ui.slider("lobby.time", rx, ry + 180, Math.min(rpW - 20, 220), "Time Limit (min, 0=off)", 0, 60, this.timeLimit, 1);
    if (ui.checkbox("lobby.t2", rx, ry + 236, "Enable T2 Units", this.enableT2)) this.enableT2 = !this.enableT2;
    if (ui.checkbox("lobby.fog", rx, ry + 266, "Fog of War", this.fog)) this.fog = !this.fog;
    if (ui.checkbox("lobby.outdated", rx, ry + 296, "Show Outdated AIs", this.showOutdated)) {
      this.showOutdated = !this.showOutdated;
    }
    void ry;

    // -- bottom buttons --
    const cx = Math.floor(w / 2);
    const btnY = h - 58;
    const gap = 12;
    if (ui.button("lobby.back", cx - BTN_WIDTH - gap / 2, btnY, BTN_WIDTH, BTN_HEIGHT, "Back to Menu")) {
      return { next: "main_menu" };
    }
    if (ui.button("lobby.start", cx + gap / 2, btnY, BTN_WIDTH, BTN_HEIGHT, "Start Game")) {
      conn.sendStartGame(this.buildConfig());
      this.starting = true;
      this.status = "";
    }
    void this.status;
    return null;
  }
}
