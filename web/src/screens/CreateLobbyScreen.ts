// Online lobby: configure players (connected humans + AI opponents), teams,
// colors, and match settings, then send start_game to the server. Ports
// screens/create_lobby.py including multi-human sync: the roster comes from
// the server's lobby_status broadcast, the lowest-pid client is the host, and
// the host's slot/setting edits are relayed to guests via lobby_settings.

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
  onlinePid: number; // server pid for humans; 0 for AI slots (assigned at start)
  name: string; // display name for humans (from the roster)
  aiId: string;
  team: number;
  colorIdx: number;
  handicap: number; // percent modifier on ME spawn bonus (create_lobby.py)
  spectator: boolean; // humans only — watch instead of play
}

/** Wire form of the lobby state the host relays to guests. */
interface SyncedSlot {
  h: boolean; // isHuman
  pid: number;
  ai: string;
  team: number;
  color: number;
  hcp: number;
  spec: boolean;
}
interface SyncedLobby {
  slots: SyncedSlot[];
  map: number;
  obs: number;
  metal: number;
  time: number;
  t2: boolean;
  fog: boolean;
}

/** Guest -> host change request (relayed via lobby_settings). */
interface LobbyRequest {
  pid: number;
  team: number;
  spec: boolean;
  n: number; // nonce so repeat requests aren't ignored / stale ones reapplied
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
// Label is just the number — the dropdown is narrow and "Team N" gets clipped.
const TEAM_CHOICES: Choice[] = Array.from({ length: 8 }, (_, i) => [String(i + 1), String(i + 1)]);

const MAX_SLOTS = 8;
const MIN_SLOTS = 2;
const SLOT_ROW_H = 38;
const SYNC_MIN_INTERVAL = 0.2; // seconds between host lobby_settings broadcasts
// Percent modifiers on the metal-extractor spawn bonus (create_lobby.py).
const HANDICAP_STEPS = [-100, -75, -50, -25, 0, 25, 50, 75, 100, 150, 200];

function handicapLabel(pct: number): string {
  if (pct === 0) return "Handicap";
  return `Handicap ${pct > 0 ? "+" : ""}${pct}%`;
}

function cycleHandicap(current: number): number {
  let i = HANDICAP_STEPS.indexOf(current);
  if (i < 0) {
    i = 0;
    for (let j = 1; j < HANDICAP_STEPS.length; j++) {
      if (Math.abs(HANDICAP_STEPS[j] - current) < Math.abs(HANDICAP_STEPS[i] - current)) i = j;
    }
  }
  return HANDICAP_STEPS[(i + 1) % HANDICAP_STEPS.length];
}

export class CreateLobbyScreen extends Screen {
  private slots: Slot[] = [];
  private showOutdated = false;

  // settings
  private mapIdx = 0;
  private obstacles = 0;
  private metalSpots = 0;
  private timeLimit = 15;
  private enableT2 = true;
  private fog = true;

  private starting = false;

  // host -> guest sync bookkeeping
  private lastSentJson = "";
  private lastSentAt = -1;

  // guest -> host request bookkeeping
  private reqCounter = 0;
  private lastReqKey = ""; // host: last processed request key (pid:nonce)

  constructor(app: App) {
    super(app);
    const conn = app.conn;
    const localPid = conn?.playerId ?? 1;
    const firstAi = this.activeChoices()[0]?.[0] ?? "wander";
    // Slot 0: the local human; slot 1: one AI opponent on team 2. Additional
    // humans are merged in from the roster as they connect.
    this.slots = [
      {
        isHuman: true,
        onlinePid: localPid,
        name: conn?.playerName ?? "You",
        aiId: "human",
        team: 1,
        colorIdx: 0,
        handicap: 0,
        spectator: false,
      },
      {
        isHuman: false,
        onlinePid: 0,
        name: "",
        aiId: firstAi,
        team: 2,
        colorIdx: 1,
        handicap: 0,
        spectator: false,
      },
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

  // -- multi-human sync ----------------------------------------------------

  /** Connected humans from the server roster, sorted by pid. */
  private roster(): { pid: number; name: string }[] {
    const players = this.app.conn?.lobbyStatus?.players ?? {};
    return Object.entries(players)
      .map(([pid, p]) => ({ pid: Number(pid), name: p.name || `Player ${pid}` }))
      .sort((a, b) => a.pid - b.pid);
  }

  /** The lowest connected pid runs the lobby (first joiner on a dedicated
   *  server). Before the roster arrives, assume we're it. */
  private isHost(): boolean {
    const r = this.roster();
    if (!r.length) return true;
    return r[0].pid === (this.app.conn?.playerId ?? 0);
  }

  private nextFreeColor(exclude: Slot | null): number {
    const used = new Set(this.slots.filter((s) => s !== exclude).map((s) => s.colorIdx));
    for (let i = 0; i < PLAYER_COLORS.length; i++) if (!used.has(i)) return i;
    return this.slots.length % PLAYER_COLORS.length;
  }

  /** Merge the server roster into the slot list: add newly connected humans,
   *  drop departed ones, refresh names. */
  private syncRoster(): void {
    const roster = this.roster();
    if (!roster.length) return; // roster not received yet
    const rosterPids = new Set(roster.map((r) => r.pid));
    this.slots = this.slots.filter((s) => !s.isHuman || rosterPids.has(s.onlinePid));
    for (const { pid, name } of roster) {
      const existing = this.slots.find((s) => s.isHuman && s.onlinePid === pid);
      if (existing) {
        existing.name = name;
        continue;
      }
      const humanCount = this.slots.filter((s) => s.isHuman).length;
      this.slots.push({
        isHuman: true,
        onlinePid: pid,
        name,
        aiId: "human",
        team: Math.min(8, humanCount + 1),
        colorIdx: this.nextFreeColor(null),
        handicap: 0,
        spectator: false,
      });
    }
    // Humans first (by pid), then AI slots, so rows are stable on all clients.
    this.slots.sort((a, b) => {
      if (a.isHuman !== b.isHuman) return a.isHuman ? -1 : 1;
      return a.onlinePid - b.onlinePid;
    });
  }

  private serialize(): SyncedLobby {
    return {
      slots: this.slots.map((s) => ({
        h: s.isHuman,
        pid: s.onlinePid,
        ai: s.aiId,
        team: s.team,
        color: s.colorIdx,
        hcp: s.handicap,
        spec: s.spectator,
      })),
      map: this.mapIdx,
      obs: this.obstacles,
      metal: this.metalSpots,
      time: this.timeLimit,
      t2: this.enableT2,
      fog: this.fog,
    };
  }

  /** Host: relay lobby state to guests when it changes (rate-limited). */
  private broadcastIfChanged(): void {
    const conn = this.app.conn;
    if (!conn) return;
    const state = this.serialize();
    const json = JSON.stringify(state);
    if (json === this.lastSentJson) return;
    if (this.ui.time - this.lastSentAt < SYNC_MIN_INTERVAL) return;
    conn.sendLobbySettings({ cfg: state });
    this.lastSentJson = json;
    this.lastSentAt = this.ui.time;
  }

  /** Guest: adopt the host's relayed lobby state (AI slots, teams, colors,
   *  settings). Human names still come from the roster. */
  private applyRemote(): void {
    const cfg = this.app.conn?.lobbySettings?.cfg as SyncedLobby | undefined;
    if (!cfg || !Array.isArray(cfg.slots)) return;
    const names = new Map(this.roster().map((r) => [r.pid, r.name]));
    const rebuilt: Slot[] = [];
    for (const ss of cfg.slots) {
      if (ss.h && !names.has(ss.pid)) continue; // departed human
      rebuilt.push({
        isHuman: ss.h,
        onlinePid: ss.pid,
        name: ss.h ? names.get(ss.pid) ?? `Player ${ss.pid}` : "",
        aiId: ss.ai,
        team: ss.team,
        colorIdx: ss.color,
        handicap: ss.hcp ?? 0,
        spectator: ss.spec ?? false,
      });
    }
    if (rebuilt.length) this.slots = rebuilt;
    this.mapIdx = cfg.map ?? this.mapIdx;
    this.obstacles = cfg.obs ?? this.obstacles;
    this.metalSpots = cfg.metal ?? this.metalSpots;
    this.timeLimit = cfg.time ?? this.timeLimit;
    this.enableT2 = cfg.t2 ?? this.enableT2;
    this.fog = cfg.fog ?? this.fog;
  }

  /** Guest: ask the host to change our own team / spectator status. */
  private sendRequest(team: number, spec: boolean): void {
    const conn = this.app.conn;
    if (!conn) return;
    const req: LobbyRequest = { pid: conn.playerId, team, spec, n: ++this.reqCounter };
    conn.sendLobbySettings({ req });
  }

  /** Host: apply a pending guest request (once per nonce). */
  private processRequests(): void {
    const req = this.app.conn?.lobbySettings?.req as LobbyRequest | undefined;
    if (!req || typeof req.pid !== "number") return;
    const key = `${req.pid}:${req.n}`;
    if (key === this.lastReqKey) return;
    this.lastReqKey = key;
    const slot = this.slots.find((s) => s.isHuman && s.onlinePid === req.pid);
    if (!slot) return;
    if (typeof req.team === "number" && req.team >= 1 && req.team <= 8) slot.team = req.team;
    if (typeof req.spec === "boolean") slot.spectator = req.spec;
  }

  private addSlot(): void {
    if (this.slots.length >= MAX_SLOTS) return;
    const firstAi = this.activeChoices()[0]?.[0] ?? "wander";
    this.slots.push({
      isHuman: false,
      onlinePid: 0,
      name: "",
      aiId: firstAi,
      team: 2,
      colorIdx: this.nextFreeColor(null),
      handicap: 0,
      spectator: false,
    });
  }

  private removeSlot(i: number): void {
    if (this.slots.length <= MIN_SLOTS) return;
    if (this.slots[i].isHuman) return; // humans leave by disconnecting
    this.slots.splice(i, 1);
  }

  /** Build the start_game config — mirrors create_lobby._send_online_start.
   *  Includes every connected human, not just the local player. */
  private buildConfig(): Record<string, unknown> {
    const conn = this.app.conn!;
    const playerTeam: Record<string, number> = {};
    const playerAi: Record<string, string> = {};
    const playerColors: Record<string, number> = {};
    const playerHandicaps: Record<string, number> = {};
    const spectators: number[] = [];

    for (const s of this.slots) {
      if (!s.isHuman || !s.onlinePid) continue;
      if (s.spectator) {
        spectators.push(s.onlinePid);
        continue;
      }
      playerTeam[String(s.onlinePid)] = s.team;
      playerColors[String(s.onlinePid)] = s.colorIdx;
      playerHandicaps[String(s.onlinePid)] = s.handicap;
    }
    // Safety net: any roster human missing from the slots still gets a team.
    const specSet = new Set(spectators);
    for (const { pid } of this.roster()) {
      if (!specSet.has(pid) && !(String(pid) in playerTeam)) playerTeam[String(pid)] = 1;
    }
    if (!specSet.has(conn.playerId) && !(String(conn.playerId) in playerTeam)) {
      playerTeam[String(conn.playerId)] = 1;
    }

    // AI slots get non-conflicting pids after the humans.
    const used = new Set<number>([...Object.keys(playerTeam).map(Number), ...spectators]);
    let nextPid = Math.max(0, ...used) + 1;
    for (const s of this.slots) {
      if (s.isHuman) continue;
      while (used.has(nextPid)) nextPid++;
      playerTeam[String(nextPid)] = s.team;
      playerAi[String(nextPid)] = s.aiId;
      playerColors[String(nextPid)] = s.colorIdx;
      playerHandicaps[String(nextPid)] = s.handicap;
      used.add(nextPid);
      nextPid++;
    }

    const [mw, mh] = MAP_SIZES[MAP_PRESETS[this.mapIdx][0]];
    return {
      player_ai_ids: playerAi,
      player_team: playerTeam,
      player_colors: playerColors,
      player_handicaps: playerHandicaps,
      spectators: spectators.sort((a, b) => a - b),
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

    // The server started the game (whoever clicked Start) — go.
    if (conn.gameStarted && conn.gameStart) {
      return { next: "game" };
    }
    if (this.starting) {
      drawText(ctx, "Starting game…", w / 2, h / 2, {
        size: 22,
        color: CONTENT_TEXT,
        align: "center",
      });
      return null;
    }

    const host = this.isHost();
    this.syncRoster();
    if (host) this.processRequests();
    else this.applyRemote();

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
    drawText(ctx, host ? "Settings" : "Settings (host controls)", rpX + 14, 64, {
      size: 18,
      color: CONTENT_TEXT,
    });

    // -- left: player slots --
    const labelX = lpX + 14;
    const aiX = labelX + 44;
    const aiW = 155;
    const teamX = aiX + aiW + 8;
    const teamW = 56;
    const hcpX = teamX + teamW + 6;
    const hcpW = 112;
    const specX = hcpX + hcpW + 6;
    const specW = 106;
    const removeX = specX + specW + 6;
    const slotYStart = 104;
    const aiChoices = this.activeChoices();

    drawText(ctx, "Team", teamX + 6, 86, { size: 13, color: HDR_COLOR });

    let removeRequest = -1;
    for (let i = 0; i < this.slots.length; i++) {
      const s = this.slots[i];
      const y = slotYStart + i * SLOT_ROW_H;
      const color = PLAYER_COLORS[s.colorIdx % PLAYER_COLORS.length];

      // color dot (host: click to cycle)
      const dotCx = labelX + 6;
      const dotCy = y + DD_HEIGHT / 2;
      ctx.beginPath();
      ctx.arc(dotCx, dotCy, 5, 0, Math.PI * 2);
      ctx.fillStyle = rgb(color);
      ctx.fill();
      if (host) {
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
      }

      drawText(ctx, `P${i + 1}`, labelX + 16, dotCy, {
        size: 16,
        color: CONTENT_TEXT,
        baseline: "middle",
      });

      const isYou = s.isHuman && s.onlinePid === conn.playerId;
      if (s.isHuman) {
        let label = isYou ? `${s.name} (You)` : s.name;
        if (s.spectator) label += " — spectating";
        drawText(ctx, label, aiX + 4, dotCy, {
          size: 16,
          color: s.spectator ? HDR_COLOR : ONLINE_COLOR,
          baseline: "middle",
        });
      } else if (host) {
        // AI dropdown (host only)
        const selIdx = Math.max(
          0,
          aiChoices.findIndex(([id]) => id === s.aiId),
        );
        const newIdx = ui.dropdown(`lobby.ai.${i}`, aiX, y, aiW, aiChoices, selIdx, {
          maxVisible: 6,
        });
        if (aiChoices[newIdx]) s.aiId = aiChoices[newIdx][0];
        if (this.slots.length > MIN_SLOTS) {
          if (ui.button(`lobby.rm.${i}`, removeX, y + (DD_HEIGHT - 26) / 2, 26, 26, "×")) {
            removeRequest = i;
          }
        }
      } else {
        // Guests see the AI name read-only.
        const aiName =
          this.app.conn?.aiChoices?.choices.find(([id]) => id === s.aiId)?.[1] ?? s.aiId;
        drawText(ctx, aiName, aiX + 4, dotCy, { size: 15, color: CONTENT_TEXT, baseline: "middle" });
      }

      // team: dropdown for the host and for a guest's own row (relayed as a
      // request the host applies), read-only label otherwise
      const teamEditable = (host || isYou) && !s.spectator;
      if (teamEditable) {
        const teamSel = Math.max(0, s.team - 1);
        const newTeam =
          ui.dropdown(`lobby.team.${i}`, teamX, y, teamW, TEAM_CHOICES, teamSel, {
            maxVisible: 8,
          }) + 1;
        if (host) s.team = newTeam;
        else if (newTeam !== s.team) this.sendRequest(newTeam, s.spectator);
      } else {
        drawText(ctx, s.spectator ? "—" : String(s.team), teamX + 6, dotCy, {
          size: 15,
          color: CONTENT_TEXT,
          baseline: "middle",
        });
      }

      // handicap: cycling button for the host, label for guests
      if (!s.spectator) {
        if (host) {
          if (ui.button(`lobby.hcp.${i}`, hcpX, y, hcpW, DD_HEIGHT, handicapLabel(s.handicap), { fontSize: 12 })) {
            s.handicap = cycleHandicap(s.handicap);
          }
        } else if (s.handicap !== 0) {
          drawText(ctx, handicapLabel(s.handicap), hcpX + 4, dotCy, {
            size: 14,
            color: CONTENT_TEXT,
            baseline: "middle",
          });
        }
      }

      // spectator toggle: host for anyone, guests for themselves
      if (s.isHuman && (host || isYou)) {
        const specLabel = s.spectator ? "Join Game" : "Join Spectator";
        if (ui.button(`lobby.spec.${i}`, specX, y, specW, DD_HEIGHT, specLabel, { fontSize: 11 })) {
          if (host) s.spectator = !s.spectator;
          else this.sendRequest(s.team, !s.spectator);
        }
      }
    }
    if (removeRequest >= 0) this.removeSlot(removeRequest);

    // add-player button (host only)
    if (host && this.slots.length < MAX_SLOTS) {
      const addY = slotYStart + this.slots.length * SLOT_ROW_H + 5;
      if (ui.button("lobby.add", aiX, addY, 150, 28, "+ Add AI", { fontSize: 14 })) {
        this.addSlot();
      }
    }

    // -- right: settings --
    const rx = rpX + 14;
    const ry = slotYStart;
    if (host) {
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
    } else {
      const rows: [string, string][] = [
        ["Map Size", MAP_PRESETS[this.mapIdx]?.[1] ?? "?"],
        ["Obstacles", String(this.obstacles)],
        ["Metal Spots / Side", this.metalSpots ? String(this.metalSpots) : "Random"],
        ["Time Limit", this.timeLimit ? `${this.timeLimit} min` : "Off"],
        ["T2 Units", this.enableT2 ? "On" : "Off"],
        ["Fog of War", this.fog ? "On" : "Off"],
      ];
      let sy = ry + 8;
      for (const [label, value] of rows) {
        drawText(ctx, label, rx, sy, { size: 15, color: HDR_COLOR });
        drawText(ctx, value, rx + 190, sy, { size: 15, color: CONTENT_TEXT });
        sy += 28;
      }
    }

    // Host: relay the current lobby state to guests when it changes.
    if (host) this.broadcastIfChanged();

    // -- bottom buttons --
    const cx = Math.floor(w / 2);
    const btnY = h - 58;
    const gap = 12;
    if (ui.button("lobby.back", cx - BTN_WIDTH - gap / 2, btnY, BTN_WIDTH, BTN_HEIGHT, "Back to Menu")) {
      return { next: "main_menu" };
    }
    if (host) {
      if (ui.button("lobby.start", cx + gap / 2, btnY, BTN_WIDTH, BTN_HEIGHT, "Start Game")) {
        conn.sendStartGame(this.buildConfig());
        this.starting = true;
      }
    } else {
      drawText(ctx, "Waiting for host to start…", cx + gap / 2 + BTN_WIDTH / 2, btnY + BTN_HEIGHT / 2, {
        size: 16,
        color: HDR_COLOR,
        align: "center",
        baseline: "middle",
      });
    }
    return null;
  }
}
