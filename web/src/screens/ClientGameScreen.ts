// In-game screen (M3): renders the live world via GameView, routes input to
// selection/commands, draws the HUD (minimap, unit summary, build/action
// panel), header, chat, and an escape menu. Fully playable vs AI.

import { Screen, type Transition } from "../app/Screen";
import type { App } from "../app/App";
import { StaticConfig } from "../config/StaticConfig";
import { GameView, type GameArea } from "../game/GameView";
import { Hud } from "../game/Hud";
import type { ChatEvent } from "../net/MessageTypes";
import { CONTENT_TEXT, HDR_COLOR, MENU_BG, rgb } from "../ui/theme";
import { drawText, measure } from "../ui/Text";

const HEADER_H = 40;
const MAX_MSG_LEN = 200;

export class ClientGameScreen extends Screen {
  private view: GameView | null = null;
  private hud: Hud | null = null;

  // chrome state
  private chatActive = false;
  private chatText = "";
  private chatMode: "all" | "team" = "all";
  private chatLog: ChatEvent[] = [];
  private escOpen = false;
  private warpClock = 0;
  private showPerf = false;
  // Game-over is deferred until the CC explosion animation finishes.
  private pendingResult: { winner: number; stats: unknown } | null = null;
  private pendingClock = 0;
  private fps = 0;
  private fpsAccum = 0;
  private fpsFrames = 0;

  constructor(app: App, _data: Record<string, unknown>) {
    super(app);
  }

  private gameArea(): GameArea {
    const hudH = Hud.height(this.ui.h);
    return { x: 0, y: HEADER_H, w: this.ui.w, h: this.ui.h - HEADER_H - hudH };
  }

  private ensure(): boolean {
    if (this.view) return true;
    const conn = this.app.conn;
    if (!conn || !conn.gameStart) return false;
    const cfg = new StaticConfig(conn.serverConfig);
    this.view = new GameView(this.ui.ctx, conn, cfg, this.gameArea());
    this.hud = new Hud(cfg, this.view, conn.gameStart.obstacles ?? []);
    return true;
  }

  render(dt: number): Transition | null {
    const { ui } = this;
    const ctx = ui.ctx;
    const conn = this.app.conn;
    if (!conn) return { next: "main_menu" };

    const ready = this.ensure();
    const area = this.gameArea();

    // -- ingest state + events --
    const next = conn.pollState();
    if (next && this.view) {
      this.view.onState(next);
      if (next.chats) {
        for (const c of next.chats) this.chatLog.push(c);
        if (this.chatLog.length > 8) this.chatLog = this.chatLog.slice(-8);
        this.view.addChats(next.chats);
      }
    }
    for (const ev of conn.pollEvents()) {
      if (ev.kind === "game_over") {
        // Hold on this screen while the CC explosion plays out.
        this.pendingResult = { winner: ev.winner, stats: ev.stats ?? null };
        this.pendingClock = 0;
        this.view?.startExplosion(ev.winner);
      } else if (ev.kind === "rejected") {
        return { next: "main_menu" };
      } else if (ev.kind === "return_to_lobby" && !this.pendingResult) {
        return { next: "main_menu" };
      }
    }
    if (this.pendingResult) {
      this.pendingClock += dt;
      const explosionOver = this.view ? this.view.explosionDone : true;
      if (explosionOver || this.pendingClock > 3.5) {
        const myTeam = this.view?.myTeam ?? 0;
        return {
          next: "results",
          data: { winner: this.pendingResult.winner, myTeam, stats: this.pendingResult.stats },
        };
      }
    }

    // FPS counter (for the F3 overlay)
    this.fpsAccum += dt;
    this.fpsFrames++;
    if (this.fpsAccum >= 0.5) {
      this.fps = this.fpsFrames / this.fpsAccum;
      this.fpsAccum = 0;
      this.fpsFrames = 0;
    }

    // -- chat input handling (consumes keys) --
    if (this.chatActive) {
      for (const ev of ui.input.keysPressed) {
        const k = ev.key;
        if (k === "Escape") {
          this.chatActive = false;
          this.chatText = "";
        } else if (k === "Enter") {
          if (this.chatText.trim() && this.view) this.view.sendChat(this.chatText, this.chatMode);
          this.chatActive = false;
          this.chatText = "";
        } else if (k === "Tab") {
          this.chatMode = this.chatMode === "all" ? "team" : "all";
        } else if (k === "Backspace") {
          this.chatText = this.chatText.slice(0, -1);
        }
      }
      if (ui.input.chars) this.chatText = (this.chatText + ui.input.chars).slice(0, MAX_MSG_LEN);
    } else {
      // global keys
      for (const ev of ui.input.keysPressed) {
        if (ev.key === "Enter" && !this.escOpen) {
          this.chatActive = true;
          this.chatText = "";
        } else if (ev.key === "Escape") {
          this.escOpen = !this.escOpen;
        } else if (ev.key === "F3") {
          this.showPerf = !this.showPerf;
        }
      }
    }

    const blockWorld = this.chatActive || this.escOpen;

    // -- update + render world --
    if (ready && this.view && this.hud) {
      this.view.update(dt, ui.input, area, blockWorld);
      this.view.render(ui.dpr, area);
      this.hud.render(ui);
      if (!blockWorld) this.hud.handleClick(ui);
    } else {
      drawText(ctx, "Loading…", ui.w / 2, ui.h / 2, { size: 22, color: CONTENT_TEXT, align: "center" });
    }

    // Warp-in countdown (server holds tick at 0 for the first ~3s).
    if (this.view && this.view.tick === 0) {
      this.warpClock += dt;
      const n = Math.max(1, Math.ceil(3 - this.warpClock));
      drawText(ctx, String(n), ui.w / 2, area.y + area.h / 2, {
        size: 96,
        color: CONTENT_TEXT,
        align: "center",
        baseline: "middle",
        bold: true,
      });
    }

    this.drawHeader(conn);
    this.drawChat(area);
    this.drawConnOverlay(conn, area);
    if (this.showPerf) this.drawPerf();

    if (this.escOpen) {
      const t = this.drawEscMenu();
      if (t) return t;
    }
    return null;
  }

  private drawHeader(conn: NonNullable<App["conn"]>): void {
    const { ui } = this;
    const ctx = ui.ctx;
    ctx.fillStyle = rgb(MENU_BG);
    ctx.fillRect(0, 0, ui.w, HEADER_H);
    ctx.strokeStyle = "rgb(50,50,65)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, HEADER_H - 0.5);
    ctx.lineTo(ui.w, HEADER_H - 0.5);
    ctx.stroke();

    const myTeam = this.view?.myTeam ?? 0;
    drawText(ctx, `Team ${myTeam}`, 12, HEADER_H / 2, { size: 16, color: CONTENT_TEXT, baseline: "middle" });

    if (this.view) {
      const secs = Math.floor(this.view.tick / 60);
      const time = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
      drawText(ctx, time, ui.w / 2, HEADER_H / 2, { size: 18, color: CONTENT_TEXT, align: "center", baseline: "middle" });
      const pingMs = conn.pings[conn.playerId];
      const diag = `${this.view.srvTps.toFixed(0)} tps   ${this.view.srvMs.toFixed(1)} ms${
        pingMs ? `   ${pingMs} ping` : ""
      }`;
      drawText(ctx, diag, ui.w - 170, HEADER_H / 2, { size: 14, color: HDR_COLOR, baseline: "middle" });
    }

    if (ui.button("game.menu", ui.w - 150, 6, 70, 28, "Menu", { fontSize: 14 })) {
      this.escOpen = true;
    }
  }

  private drawChat(area: GameArea): void {
    const { ui } = this;
    const ctx = ui.ctx;
    const x = area.x + 10;
    let y = area.y + area.h - 28;
    // recent messages (bottom-up)
    for (let i = this.chatLog.length - 1; i >= 0; i--) {
      const c = this.chatLog[i];
      const txt = `[${c.mode === "team" ? "Team" : "All"}] ${c.name}: ${c.msg}`;
      y -= 18;
      drawText(ctx, txt, x, y, { size: 13, color: c.mode === "team" ? [150, 220, 150] : HDR_COLOR });
      if (y < area.y + 40) break;
    }
    // input box
    if (this.chatActive) {
      const by = area.y + area.h - 24;
      ctx.fillStyle = "rgba(0,0,0,0.6)";
      ctx.fillRect(x - 4, by - 2, 420, 22);
      const prefix = this.chatMode === "team" ? "[Team] " : "[All] ";
      const line = prefix + this.chatText;
      drawText(ctx, line, x, by + 9, { size: 14, color: CONTENT_TEXT, baseline: "middle" });
      // caret
      const cx = x + measure(ctx, line, 14) + 2;
      if (Math.floor(ui.time * 2) % 2 === 0) {
        ctx.strokeStyle = rgb(CONTENT_TEXT);
        ctx.beginPath();
        ctx.moveTo(cx, by + 1);
        ctx.lineTo(cx, by + 17);
        ctx.stroke();
      }
      drawText(ctx, "Enter: send   Tab: all/team   Esc: cancel", x, by - 16, { size: 11, color: HDR_COLOR });
    }
  }

  /** Banner shown while the WebSocket is down mid-game. */
  private drawConnOverlay(conn: NonNullable<App["conn"]>, area: GameArea): void {
    let text: string | null = null;
    if (conn.reconnecting) {
      const dots = ".".repeat(1 + (Math.floor(this.ui.time * 2) % 3));
      text = `Connection lost — reconnecting${dots}`;
    } else if (conn.connectionLost) {
      text = "Connection lost (press Esc to leave)";
    }
    if (!text) return;
    const { ui } = this;
    const ctx = ui.ctx;
    const w = 380;
    const h = 40;
    const x = area.x + (area.w - w) / 2;
    const y = area.y + 24;
    ctx.fillStyle = "rgba(0,0,0,0.7)";
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = "rgb(200,90,90)";
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    drawText(ctx, text, x + w / 2, y + h / 2, {
      size: 15,
      color: [255, 150, 150],
      align: "center",
      baseline: "middle",
    });
  }

  private drawPerf(): void {
    const { ui } = this;
    const ctx = ui.ctx;
    const x = 10;
    const y = HEADER_H + 8;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(x, y, 150, 60);
    const lines = [
      `FPS ${this.fps.toFixed(0)}`,
      `srv ${this.view?.srvMs.toFixed(2) ?? "0"} ms`,
      `tps ${this.view?.srvTps.toFixed(1) ?? "0"}`,
    ];
    let yy = y + 6;
    for (const ln of lines) {
      drawText(ctx, ln, x + 8, yy, { size: 13, color: [180, 255, 180] });
      yy += 18;
    }
  }

  private drawEscMenu(): Transition | null {
    const { ui } = this;
    const ctx = ui.ctx;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(0, 0, ui.w, ui.h);
    const cx = ui.w / 2;
    let y = ui.h / 2 - 80;
    drawText(ctx, "Paused", cx, y, { size: 32, color: CONTENT_TEXT, align: "center", bold: true });
    y += 60;
    const bw = 240;
    if (ui.button("esc.resume", cx - bw / 2, y, bw, 44, "Resume")) {
      this.escOpen = false;
    }
    y += 54;
    if (ui.button("esc.surrender", cx - bw / 2, y, bw, 44, "Surrender")) {
      this.view?.surrender();
      this.escOpen = false;
    }
    y += 54;
    if (ui.button("esc.leave", cx - bw / 2, y, bw, 44, "Leave to Menu")) {
      this.view?.surrender();
      return { next: "main_menu" };
    }
    return null;
  }
}
