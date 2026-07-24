// Orchestrates the in-game world view: camera, extrapolation, selection, and
// input -> commands, plus the swappable WorldRenderer. Ports the world-input
// half of screens/client_game.py (selection, right-click move/attack/fight,
// hotkeys). The HUD and chat/esc chrome live in the screen + Hud module.

import type { Connection } from "../net/Connection";
import type { StaticConfig } from "../config/StaticConfig";
import type {
  AnyEntity,
  CCEntity,
  ChatEvent,
  DeathEvent,
  GameStart,
  Laser,
  MEEntity,
  Obstacle,
  RGBTuple,
  Splash,
  StateFrame,
  UnitEntity,
} from "../net/MessageTypes";
import type { Input } from "../core/Input";
import { Camera } from "../render/Camera";
import { Canvas2DRenderer } from "../render/Canvas2DRenderer";
import type {
  BurstFx,
  CameraView,
  FloatingChatFx,
  FogMode,
  FragmentFx,
  RenderFrame,
  WorldLabelFx,
  WorldRenderer,
} from "../render/WorldRenderer";
import { Extrapolation } from "./Extrapolation";
import { Commander } from "./Commands";
import { audio } from "../audio/AudioEngine";
import { assets } from "../assets/Assets";

export interface GameArea {
  x: number;
  y: number;
  w: number;
  h: number;
}

const BUILD_KEYS = ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"];
const PATH_MIN_DIST = 2.5;

// Client-side VFX constants (ported from entities/effects.py + client_game.py
// + systems/chat.py — keep in sync with the desktop client).
const WARP_IN_DURATION = 3.0;
const EXPLODE_DURATION = 3.0;
const MAX_DEATH_BURSTS = 200;
const BURST_DURATION = 0.55;
const FLOAT_TEXT_DURATION = 4.0;
const FLOAT_TEXT_RISE = 30;
const ACTION_FLASH_DURATION = 0.25;

interface DeathBurst {
  x: number;
  y: number;
  color: RGBTuple;
  ttl: number;
  // Each particle: [ox, oy, vx, vy, size]
  particles: [number, number, number, number, number][];
}

interface Fragment {
  pts: [number, number][]; // triangle, relative to (cx, cy)
  cx: number;
  cy: number;
  vx: number;
  vy: number;
  angle: number;
  rotSpeed: number;
  color: RGBTuple;
}

interface FloatingChat {
  x: number;
  y: number; // spawn position (already offset above the CC)
  text: string;
  color: RGBTuple;
  ttl: number;
}

export class GameView {
  private cfg: StaticConfig;
  private renderer: WorldRenderer;
  private extrap: Extrapolation;
  private commander: Commander;
  camera: Camera;

  private mapW: number;
  private mapH: number;
  private obstacles: Obstacle[];
  myTeam: number;
  private fogOfWar: boolean;
  enableT2: boolean;

  private entities: AnyEntity[] = [];
  private lasers: Laser[] = [];
  private splashes: Splash[] = [];
  tick = 0;
  srvTps = 0;
  srvMs = 0;

  // Per-team T2 display sets (mirrors client_game.py _refresh_t2_display)
  t2Upgrades = new Map<number, Set<string>>();
  t2Researching = new Map<number, Set<string>>();

  // team id -> display name (from game_start), for CC labels
  private teamNames = new Map<number, string>();

  // Client-side VFX state
  private phase: "warp_in" | "playing" | "explode" = "warp_in";
  private animTimer = 0;
  private bursts: DeathBurst[] = [];
  private fragments: Fragment[] = [];
  private floatingChats: FloatingChat[] = [];
  // Last-seen CC visuals so the explosion can fragment CCs that died in the
  // same frame the winner was decided (they may be gone from `entities`).
  private ccCache = new Map<number, { x: number; y: number; pts: [number, number][]; c: RGBTuple; tm: number }>();
  // CCs that fragmented in the explosion — filtered out of `entities` so the
  // intact hull doesn't keep rendering underneath its own debris.
  private explodedCCIds = new Set<number>();
  // HUD action buttons briefly highlight after their command fires (keyed by
  // action name -> clock time of the press).
  private actionFlashes = new Map<string, number>();

  // selection + command state
  selectedIds = new Set<number>();
  attackMode = false;
  fightMode = false;

  private dragging = false;
  private dragStart: [number, number] = [0, 0];
  private dragEnd: [number, number] = [0, 0];
  private rdragging = false;
  private rpath: [number, number][] = [];
  private clock = 0;
  private lastClickTime = -1;
  private lastClickPos: [number, number] = [0, 0];

  // camera pan state
  private panActive = false;
  private panLastX = 0;
  private panLastY = 0;

  constructor(ctx: CanvasRenderingContext2D, conn: Connection, cfg: StaticConfig, area: GameArea) {
    this.cfg = cfg;
    const gs = conn.gameStart as GameStart;
    this.mapW = gs.map_width;
    this.mapH = gs.map_height;
    this.obstacles = gs.obstacles ?? [];
    this.fogOfWar = gs.fog_of_war;
    this.enableT2 = gs.enable_t2;
    this.myTeam = gs.player_team?.[String(conn.playerId)] ?? 0;

    // team -> player name for the CC labels (client_game.py _draw_team_labels)
    const pteam = gs.player_team ?? {};
    for (const [pid, name] of Object.entries(gs.player_names ?? {})) {
      const tm = pteam[pid] ?? Number(pid);
      if (!this.teamNames.has(tm)) this.teamNames.set(tm, name);
    }

    this.camera = new Camera(area.w, area.h, this.mapW, this.mapH, cfg.maxZoom);
    this.extrap = new Extrapolation(cfg);
    this.commander = new Commander(conn, () => this.tick);
    this.renderer = new Canvas2DRenderer();
    this.renderer.init(ctx, cfg);
    assets.loadNebula();
  }

  onState(frame: StateFrame): void {
    this.entities = this.explodedCCIds.size
      ? frame.entities.filter((e) => !this.explodedCCIds.has(e.id))
      : frame.entities;
    this.lasers = frame.lasers ?? [];
    this.splashes = frame.splashes ?? [];
    this.tick = frame.tick;
    this.srvTps = frame.srv_tps;
    this.srvMs = frame.srv_ms;
    this.extrap.update(frame.entities, frame.tick);
    if (frame.sounds) for (const s of frame.sounds) audio.play(s);

    this.refreshT2Display();
    for (const e of frame.entities) {
      if (e.t === "CC" && !e.ghost) {
        const cc = e as CCEntity;
        this.ccCache.set(cc.id, { x: cc.x, y: cc.y, pts: cc.pts ?? [], c: cc.c, tm: cc.tm });
      }
    }
    if (frame.deaths) this.spawnDeathBursts(frame.deaths);
    if (frame.winner !== 0 && this.phase !== "explode") this.startExplosion(frame.winner);
  }

  /** Rebuild per-team T2 display sets from the latest entities. */
  private refreshT2Display(): void {
    const done = new Map<number, Set<string>>();
    const wip = new Map<number, Set<string>>();
    for (const e of this.entities) {
      if (e.t !== "ME") continue;
      const me = e as MEEntity;
      if (!me.rut) continue;
      const target = me.us === "research_lab" ? done : me.us === "upgrading_lab" ? wip : null;
      if (!target) continue;
      let set = target.get(me.tm);
      if (!set) target.set(me.tm, (set = new Set()));
      set.add(me.rut);
    }
    this.t2Upgrades = done;
    this.t2Researching = wip;
  }

  // -- client-side VFX ----------------------------------------------------

  private spawnDeathBursts(events: DeathEvent[]): void {
    if (this.phase !== "playing") return;
    for (const ev of events) {
      const scale = Math.max(0.5, (ev.r ?? 6) / 6);
      const particles: DeathBurst["particles"] = [];
      for (let i = 0; i < 8; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = (45 + Math.random() * 50) * scale;
        particles.push([
          0,
          0,
          Math.cos(angle) * speed,
          Math.sin(angle) * speed,
          (1.6 + Math.random() * 1.4) * scale,
        ]);
      }
      this.bursts.push({ x: ev.x, y: ev.y, color: ev.c ?? [200, 200, 200], ttl: BURST_DURATION, particles });
    }
    const overflow = this.bursts.length - MAX_DEATH_BURSTS;
    if (overflow > 0) this.bursts.splice(0, overflow);
  }

  /** Begin the CC explosion animation for the losing side(s). */
  startExplosion(winner: number): void {
    if (this.phase === "explode") return;
    this.phase = "explode";
    this.animTimer = 0;
    for (const [ccId, cc] of this.ccCache) {
      if (winner !== -1 && cc.tm === winner) continue;
      this.explodedCCIds.add(ccId);
      const pts = cc.pts;
      for (let i = 0; i < pts.length; i++) {
        const p1 = pts[i];
        const p2 = pts[(i + 1) % pts.length];
        const tri: [number, number][] = [[0, 0], [p1[0], p1[1]], [p2[0], p2[1]]];
        let outX = (p1[0] + p2[0]) / 2;
        let outY = (p1[1] + p2[1]) / 2;
        const dist = Math.hypot(outX, outY) || 1;
        outX /= dist;
        outY /= dist;
        const speed = 40 + Math.random() * 80;
        this.fragments.push({
          pts: tri,
          cx: cc.x,
          cy: cc.y,
          vx: outX * speed + (Math.random() * 40 - 20),
          vy: outY * speed + (Math.random() * 40 - 20),
          angle: 0,
          rotSpeed: Math.random() * 8 - 4,
          color: cc.c,
        });
      }
    }
    if (this.explodedCCIds.size) {
      this.entities = this.entities.filter((e) => !this.explodedCCIds.has(e.id));
    }
  }

  /** True once the explosion animation has finished playing. */
  get explosionDone(): boolean {
    return this.phase === "explode" && this.animTimer >= EXPLODE_DURATION;
  }

  get exploding(): boolean {
    return this.phase === "explode";
  }

  /** Spawn floating chat texts above the sender's CC (systems/chat.py port). */
  addChats(chats: ChatEvent[]): void {
    for (const c of chats) {
      let cc: CCEntity | null = null;
      for (const e of this.entities) {
        if (e.t === "CC" && (e as CCEntity).pid === c.pid) {
          cc = e as CCEntity;
          break;
        }
      }
      if (!cc) continue;
      const colors = this.cfg.playerColors;
      const idx = colors.length ? (((c.pid - 1) % colors.length) + colors.length) % colors.length : 0;
      const color = colors.length ? colors[idx] : ([255, 255, 255] as RGBTuple);
      let text = `${c.name}: ${c.msg}`;
      if (text.length > 50) text = text.slice(0, 50) + "…";
      this.floatingChats.push({ x: cc.x, y: cc.y - 60, text, color, ttl: FLOAT_TEXT_DURATION });
    }
  }

  resetCamera(): void {
    this.camera.reset();
  }

  get mapWidth(): number {
    return this.mapW;
  }

  get mapHeight(): number {
    return this.mapH;
  }

  hasSelectedOwnCC(): boolean {
    return this.entities.some(
      (e) => e.t === "CC" && e.tm === this.myTeam && this.selectedIds.has(e.id),
    );
  }

  selectedUnits(): UnitEntity[] {
    return this.entities.filter(
      (e) => e.t === "U" && this.selectedIds.has(e.id),
    ) as UnitEntity[];
  }

  private screenToWorld(sx: number, sy: number, area: GameArea): [number, number] {
    return this.camera.screenToWorld(sx - area.x, sy - area.y);
  }

  // -- camera + command input -------------------------------------------

  update(dt: number, input: Input, area: GameArea, blockWorld: boolean, winH?: number): void {
    this.clock += dt;
    this.camera.setViewport(area.w, area.h);
    const mx = input.mouseX - area.x;
    const my = input.mouseY - area.y;
    const inArea = mx >= 0 && mx <= area.w && my >= 0 && my <= area.h;

    // Wheel zoom at cursor
    if (inArea && !blockWorld && input.wheel !== 0) {
      const factor = input.wheel > 0 ? 1 / this.cfg.zoomStep : this.cfg.zoomStep;
      this.camera.zoomAt(mx, my, factor);
    }

    // Middle-drag pan
    if (input.middleDown) {
      if (this.panActive) this.camera.pan(input.mouseX - this.panLastX, input.mouseY - this.panLastY);
      this.panActive = true;
      this.panLastX = input.mouseX;
      this.panLastY = input.mouseY;
    } else {
      this.panActive = false;
    }

    // Edge pan (window edges — the bottom threshold sits at the window edge,
    // NOT the game-area edge, so hovering the HUD doesn't drag the camera).
    if (!input.middleDown) {
      const m = this.cfg.edgePanMargin;
      const s = this.cfg.edgePanSpeed * dt;
      const bottom = (winH ?? area.y + area.h) - m;
      let dx = 0;
      let dy = 0;
      if (input.mouseX <= m) dx = s;
      else if (input.mouseX >= area.x + area.w - m) dx = -s;
      if (input.mouseY <= m) dy = s;
      else if (input.mouseY >= bottom) dy = -s;
      if (dx !== 0 || dy !== 0) this.camera.pan(dx, dy);
    }

    if (!blockWorld) this.handleCommandInput(input, area, inArea);

    this.extrap.tick(dt);

    // -- VFX simulation --
    if (this.phase === "warp_in") {
      this.animTimer += dt;
      if (this.animTimer >= WARP_IN_DURATION) {
        this.phase = "playing";
        this.animTimer = 0;
      }
    } else if (this.phase === "explode") {
      this.animTimer += dt;
      for (const f of this.fragments) {
        f.cx += f.vx * dt;
        f.cy += f.vy * dt;
        f.angle += f.rotSpeed * dt;
      }
    }
    if (this.bursts.length) {
      const damp = Math.exp(-3.2 * dt);
      this.bursts = this.bursts.filter((b) => {
        b.ttl -= dt;
        for (const p of b.particles) {
          p[0] += p[2] * dt;
          p[1] += p[3] * dt;
          p[2] *= damp;
          p[3] *= damp;
        }
        return b.ttl > 0;
      });
    }
    if (this.floatingChats.length) {
      this.floatingChats = this.floatingChats.filter((fc) => {
        fc.ttl -= dt;
        return fc.ttl > 0;
      });
    }
  }

  private handleCommandInput(input: Input, area: GameArea, inArea: boolean): void {
    // -- left button: drag-select --
    if (input.pressed && inArea) {
      this.dragging = true;
      this.dragStart = [input.mouseX, input.mouseY];
      this.dragEnd = [input.mouseX, input.mouseY];
    }
    if (this.dragging) this.dragEnd = [input.mouseX, input.mouseY];
    if (input.released && this.dragging) {
      this.dragging = false;
      this.handleSelection(this.dragEnd, area, input.shift);
    }

    // -- right button: command path --
    if (input.rightPressed && inArea) {
      this.rdragging = true;
      this.rpath = [this.screenToWorld(input.mouseX, input.mouseY, area)];
    } else if (this.rdragging && input.rightDown) {
      const [wx, wy] = this.screenToWorld(input.mouseX, input.mouseY, area);
      const last = this.rpath[this.rpath.length - 1];
      if (!last || Math.hypot(wx - last[0], wy - last[1]) >= PATH_MIN_DIST) this.rpath.push([wx, wy]);
    }
    if (input.rightReleased && this.rdragging) {
      this.rdragging = false;
      const [wx, wy] = this.screenToWorld(input.mouseX, input.mouseY, area);
      if (!this.rpath.length) this.rpath = [[wx, wy]];
      else if (Math.hypot(wx - this.rpath[this.rpath.length - 1][0], wy - this.rpath[this.rpath.length - 1][1]) > 1)
        this.rpath.push([wx, wy]);
      this.sendMoveCommands(input.shift);
      this.rpath = [];
      this.fightMode = false;
      this.attackMode = false;
    }

    // -- hotkeys --
    for (const ev of input.keysPressed) {
      const k = ev.key.toLowerCase();
      if (k === "z" && ev.ctrl) this.selectOwnCC();
      else if (ev.key === "Tab") this.selectAllArmy();
      else if (k === "c" && ev.ctrl) this.expandSelectionByType();
      else if (k === "s") this.cmdStop();
      else if (k === "f") this.fightMode = true;
      else if (k === "a") this.attackMode = true;
      else if (k === "h") this.cmdToggleHoldFire();
      else if (BUILD_KEYS.includes(k)) this.cmdBuildHotkey(BUILD_KEYS.indexOf(k));
    }
  }

  // -- selection --------------------------------------------------------

  private handleSelection(pos: [number, number], area: GameArea, additive: boolean): void {
    const [sx, sy] = this.dragStart;
    const dragR = Math.hypot(pos[0] - sx, pos[1] - sy);
    if (dragR < 5) {
      const isDbl =
        this.clock - this.lastClickTime < 0.4 &&
        Math.hypot(pos[0] - this.lastClickPos[0], pos[1] - this.lastClickPos[1]) < 10;
      this.lastClickTime = this.clock;
      this.lastClickPos = pos;
      const [wx, wy] = this.screenToWorld(pos[0], pos[1], area);
      if (!additive) this.selectedIds.clear();
      let bestId: number | null = null;
      let bestDist = Infinity;
      let bestUt: string | null = null;
      for (const e of this.entities) {
        if (e.tm !== this.myTeam) continue;
        if (e.t !== "U" && e.t !== "CC" && e.t !== "ME") continue;
        const d = Math.hypot(e.x - wx, e.y - wy);
        if (d <= (e.r ?? 5) + 5 && d < bestDist) {
          bestDist = d;
          bestId = e.id;
          bestUt = (e as { ut?: string }).ut ?? null;
        }
      }
      if (bestId !== null) {
        this.selectedIds.add(bestId);
        if (isDbl && bestUt) {
          const vp = this.camera.getWorldViewportRect();
          for (const e of this.entities) {
            if (
              e.tm === this.myTeam &&
              e.t === "U" &&
              (e as UnitEntity).ut === bestUt &&
              e.x >= vp.x &&
              e.x <= vp.x + vp.w &&
              e.y >= vp.y &&
              e.y <= vp.y + vp.h
            ) {
              this.selectedIds.add(e.id);
            }
          }
        }
      }
    } else {
      if (!additive) this.selectedIds.clear();
      const army: number[] = [];
      const buildings: number[] = [];
      const [wx1, wy1] = this.screenToWorld(this.dragStart[0], this.dragStart[1], area);
      const [wx2, wy2] = this.screenToWorld(pos[0], pos[1], area);
      const rx = Math.min(wx1, wx2);
      const ry = Math.min(wy1, wy2);
      const rw = Math.abs(wx2 - wx1);
      const rh = Math.abs(wy2 - wy1);
      const rcx = rx + rw / 2;
      const rcy = ry + rh / 2;
      const hw = rw / 2;
      const hh = rh / 2;
      for (const e of this.entities) {
        if (e.tm !== this.myTeam) continue;
        if (e.t !== "U" && e.t !== "CC" && e.t !== "ME") continue;
        const er = e.r ?? 5;
        if (Math.abs(e.x - rcx) <= hw + er && Math.abs(e.y - rcy) <= hh + er) {
          if (e.t === "U") army.push(e.id);
          else buildings.push(e.id);
        }
      }
      const targets = army.length ? army : buildings;
      for (const id of targets) this.selectedIds.add(id);
    }
  }

  private selectOwnCC(): void {
    this.selectedIds.clear();
    for (const e of this.entities) {
      if (e.t === "CC" && e.tm === this.myTeam) this.selectedIds.add(e.id);
    }
  }

  private selectAllArmy(): void {
    this.selectedIds.clear();
    for (const e of this.entities) {
      if (e.t === "U" && e.tm === this.myTeam) this.selectedIds.add(e.id);
    }
  }

  private expandSelectionByType(): void {
    const types = new Set<string>();
    for (const e of this.entities) {
      if (e.t === "U" && this.selectedIds.has(e.id)) types.add((e as UnitEntity).ut);
    }
    if (!types.size) return;
    for (const e of this.entities) {
      if (e.t === "U" && e.tm === this.myTeam && types.has((e as UnitEntity).ut)) this.selectedIds.add(e.id);
    }
  }

  // -- commands ---------------------------------------------------------

  private cmdStop(): void {
    const ids = this.selectedUnits().map((u) => u.id);
    if (ids.length) {
      this.commander.stop(ids);
      this.actionFlashes.set("stop", this.clock);
    }
  }

  /** True while an action button should show its brief "command fired" flash. */
  actionFlashing(action: string): boolean {
    const t = this.actionFlashes.get(action);
    return t !== undefined && this.clock - t < ACTION_FLASH_DURATION;
  }

  private cmdToggleHoldFire(): void {
    const units = this.selectedUnits();
    if (!units.length) return;
    const anyNotHeld = units.some((u) => !u.hf);
    this.commander.setFireMode(units.map((u) => u.id), anyNotHeld ? "hold_fire" : "free_fire");
  }

  cmdBuildHotkey(idx: number): void {
    if (!this.hasSelectedOwnCC()) return;
    const spawnable = this.cfg.spawnableTypes;
    if (idx < spawnable.length) this.commander.setSpawnType(spawnable[idx]);
  }

  setSpawnType(ut: string): void {
    this.commander.setSpawnType(ut);
  }

  /** HUD action-button dispatch (mirrors the S/A/M/F/H hotkeys). */
  hudAction(action: string): void {
    if (action === "stop") this.cmdStop();
    else if (action === "attack") this.attackMode = true;
    else if (action === "move") {
      this.attackMode = false;
      this.fightMode = false;
    } else if (action === "fight") this.fightMode = true;
    else if (action === "hold_fire") this.cmdToggleHoldFire();
  }

  private entityAtWorld(wx: number, wy: number): AnyEntity | null {
    let best: AnyEntity | null = null;
    let bestDist = Infinity;
    for (const e of this.entities) {
      if (e.t !== "U" && e.t !== "CC" && e.t !== "ME") continue;
      const d = Math.hypot(e.x - wx, e.y - wy);
      if (d <= (e.r ?? 5) + 5 && d < bestDist) {
        bestDist = d;
        best = e;
      }
    }
    return best;
  }

  private sendMoveCommands(shiftHeld: boolean): void {
    const selected = this.selectedUnits();
    if (!selected.length || !this.rpath.length) {
      // Rally point on a selected CC
      if (this.rpath.length && this.hasSelectedOwnCC()) {
        this.commander.setRally(this.rpath[this.rpath.length - 1]);
      }
      return;
    }

    // Attack mode, single point: target entity under cursor
    if (this.attackMode && this.rpath.length === 1) {
      const target = this.entityAtWorld(this.rpath[0][0], this.rpath[0][1]);
      if (target) {
        if (target.tm !== this.myTeam) {
          for (const u of selected) this.commander.attack(u.id, target.id, shiftHeld);
          return;
        }
        // Ally: medics heal (attack), others attack-move to point
        const medics: number[] = [];
        const others: number[] = [];
        for (const u of selected) {
          const w = this.cfg.unitTypes[u.ut]?.weapon as { hits_only_friendly?: boolean } | undefined;
          if (w?.hits_only_friendly) medics.push(u.id);
          else others.push(u.id);
        }
        for (const mid of medics) this.commander.attack(mid, target.id, shiftHeld);
        if (others.length) {
          const p = this.rpath[0];
          this.commander.attackMove(others, others.map(() => p), shiftHeld);
        }
        return;
      }
    }

    // Build unit_ids + targets
    let unitIds: number[];
    let targets: [number, number][];
    if (this.rpath.length === 1) {
      const p = this.rpath[0];
      unitIds = selected.map((u) => u.id);
      targets = unitIds.map(() => p);
    } else {
      const goals = this.resamplePath(selected.length);
      const assigned = new Set<number>();
      unitIds = [];
      targets = [];
      for (const [gx, gy] of goals) {
        let bestIdx = -1;
        let bestDist = Infinity;
        for (let i = 0; i < selected.length; i++) {
          if (assigned.has(i)) continue;
          const d = Math.hypot(selected[i].x - gx, selected[i].y - gy);
          if (d < bestDist) {
            bestDist = d;
            bestIdx = i;
          }
        }
        if (bestIdx >= 0) {
          unitIds.push(selected[bestIdx].id);
          targets.push([gx, gy]);
          assigned.add(bestIdx);
        }
      }
    }
    if (!unitIds.length) return;
    if (this.attackMode) this.commander.attackMove(unitIds, targets, shiftHeld);
    else if (this.fightMode) this.commander.fight(unitIds, targets, shiftHeld);
    else this.commander.move(unitIds, targets, shiftHeld);
  }

  private resamplePath(n: number): [number, number][] {
    const path = this.rpath;
    if (n <= 0 || path.length < 2) return path.slice(0, n);
    let total = 0;
    for (let i = 1; i < path.length; i++) total += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]);
    if (total < 1e-6) return Array.from({ length: n }, () => path[0]);
    if (n === 1) return [path[Math.floor(path.length / 2)]];
    const spacing = total / (n - 1);
    const points: [number, number][] = [path[0]];
    let accumulated = 0;
    let seg = 1;
    let segStart = path[0];
    for (let i = 1; i < n - 1; i++) {
      const targetDist = i * spacing;
      let placed = false;
      while (seg < path.length) {
        const [px, py] = segStart;
        const [ex, ey] = path[seg];
        const segLen = Math.hypot(ex - px, ey - py);
        if (accumulated + segLen >= targetDist) {
          const frac = segLen > 0 ? (targetDist - accumulated) / segLen : 0;
          points.push([px + (ex - px) * frac, py + (ey - py) * frac]);
          placed = true;
          break;
        }
        accumulated += segLen;
        segStart = path[seg];
        seg++;
      }
      if (!placed) points.push(path[path.length - 1]);
    }
    points.push(path[path.length - 1]);
    return points;
  }

  // -- chrome-driven commands (chat / surrender / HUD actions) ----------

  sendChat(message: string, mode: "all" | "team"): void {
    this.commander.chat(message, mode);
  }

  surrender(): void {
    this.commander.surrender();
  }

  upgradeExtractor(entityId: number, path: "outpost" | "research_lab"): void {
    this.commander.upgradeExtractor(entityId, path);
  }

  setResearchType(entityId: number, unitType: string): void {
    this.commander.setResearchType(entityId, unitType);
  }

  // -- rendering --------------------------------------------------------

  private fogMode(): FogMode {
    return this.fogOfWar ? "soft" : "none";
  }

  private collectLosCircles(entities: AnyEntity[]): [number, number, number][] {
    if (this.myTeam === 0) return [];
    const out: [number, number, number][] = [];
    for (const e of entities) {
      if (e.t !== "U" && e.t !== "CC" && e.t !== "ME") continue;
      if (e.tm !== this.myTeam) continue;
      if (e.ghost) continue;
      const ut = (e as { ut?: string }).ut ?? "soldier";
      const los = this.cfg.losFor(ut, (e as { los?: number }).los, (e as { us?: string }).us);
      if (los > 0) out.push([e.x, e.y, los]);
    }
    return out;
  }

  render(dpr: number, area: GameArea): void {
    const entities = this.extrap.apply(this.entities);
    const cam: CameraView = {
      cx: this.camera.cx,
      cy: this.camera.cy,
      zoom: this.camera.zoom,
      vpW: area.w,
      vpH: area.h,
      gx: area.x,
      gy: area.y,
    };
    const fogMode = this.fogMode();

    // Drag-selection shape (world coords)
    let dragRect: { x: number; y: number; w: number; h: number } | null = null;
    if (this.dragging) {
      const [wx1, wy1] = this.screenToWorld(this.dragStart[0], this.dragStart[1], area);
      const [wx2, wy2] = this.screenToWorld(this.dragEnd[0], this.dragEnd[1], area);
      if (Math.hypot(this.dragEnd[0] - this.dragStart[0], this.dragEnd[1] - this.dragStart[1]) >= 5) {
        dragRect = { x: Math.min(wx1, wx2), y: Math.min(wy1, wy2), w: Math.abs(wx2 - wx1), h: Math.abs(wy2 - wy1) };
      }
    }

    // Flatten VFX simulations into render-ready snapshots
    let burstsFx: BurstFx[] | undefined;
    if (this.bursts.length) {
      burstsFx = [];
      for (const b of this.bursts) {
        const frac = Math.max(0, b.ttl / BURST_DURATION);
        const alpha = (230 / 255) * frac;
        if (alpha <= 0) continue;
        for (const [ox, oy, , , size] of b.particles) {
          burstsFx.push({
            x: b.x + ox,
            y: b.y + oy,
            r: Math.max(1, size * (0.55 + 0.45 * frac)),
            color: b.color,
            alpha,
          });
        }
      }
    }
    let fragmentsFx: FragmentFx[] | undefined;
    if (this.phase === "explode" && this.fragments.length) {
      const t = Math.min(this.animTimer / EXPLODE_DURATION, 1);
      const alpha = 1 - t;
      if (alpha > 0) {
        fragmentsFx = this.fragments.map((f) => {
          const cos = Math.cos(f.angle);
          const sin = Math.sin(f.angle);
          return {
            pts: f.pts.map(([px, py]) => [px * cos - py * sin + f.cx, px * sin + py * cos + f.cy]) as [
              number,
              number,
            ][],
            color: f.color,
            alpha,
          };
        });
      }
    }
    // Team names above CCs + ME spawn-bonus labels
    const labels: WorldLabelFx[] = [];
    for (const e of entities) {
      if (e.ghost) continue;
      if (e.t === "CC") {
        const cc = e as CCEntity;
        let text = this.teamNames.get(cc.tm) ?? `Team ${cc.tm}`;
        const bp = cc.bp ?? 0;
        if (bp > 0) text += ` (+${bp}%)`;
        labels.push({ x: cc.x, y: cc.y - 40, text, color: cc.c ?? [255, 255, 255], size: 20 });
      } else if (e.t === "ME") {
        const me = e as MEEntity;
        const meb = me.meb ?? 0;
        if (meb > 0) {
          labels.push({
            x: me.x,
            y: me.y - (me.r ?? 10) - this.cfg.healthBarOffset - 12,
            text: `+${meb}%`,
            color: [255, 255, 255],
            size: 14,
          });
        }
      }
    }

    let chatsFx: FloatingChatFx[] | undefined;
    if (this.floatingChats.length) {
      chatsFx = this.floatingChats.map((fc) => {
        const frac = Math.max(0, fc.ttl / FLOAT_TEXT_DURATION);
        return {
          x: fc.x,
          y: fc.y - (1 - frac) * FLOAT_TEXT_RISE,
          text: fc.text,
          color: fc.color,
          alpha: (220 / 255) * frac,
        };
      });
    }

    const frame: RenderFrame = {
      cam,
      dpr,
      mapW: this.mapW,
      mapH: this.mapH,
      obstacles: this.obstacles,
      entities,
      lasers: this.lasers,
      splashes: this.splashes,
      fogMode,
      losCircles: fogMode !== "none" ? this.collectLosCircles(entities) : [],
      selectedIds: this.selectedIds,
      rpath: this.rdragging ? this.rpath : undefined,
      dragRect,
      dragCircle: null,
      warpT: this.phase === "warp_in" ? Math.min(this.animTimer / WARP_IN_DURATION, 1) : undefined,
      bursts: burstsFx,
      fragments: fragmentsFx,
      floatingChats: chatsFx,
      labels: labels.length ? labels : undefined,
    };
    this.renderer.draw(frame);
  }

  /** Find the closest selectable own CC (for rally/HUD), or null. */
  getEntities(): AnyEntity[] {
    return this.entities;
  }

  getSelectedCC(): CCEntity | null {
    for (const e of this.entities) {
      if (e.t === "CC" && e.tm === this.myTeam && this.selectedIds.has(e.id)) return e as CCEntity;
    }
    return null;
  }

  /** The single selected own metal extractor, or null (mirrors the desktop
   *  rule: the ME panel only shows for a lone-ME selection). */
  getSelectedME(): MEEntity | null {
    if (this.selectedIds.size !== 1) return null;
    for (const e of this.entities) {
      if (e.t === "ME" && e.tm === this.myTeam && this.selectedIds.has(e.id)) return e as MEEntity;
    }
    return null;
  }
}
