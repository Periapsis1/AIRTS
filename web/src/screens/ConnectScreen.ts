// Connect screen: enter the server WebSocket URL + player name, open the
// connection, and advance to the lobby once the handshake (lobby_info +
// ai_choices) has arrived. Plays the role of screens/multiplayer_lobby.py's
// connect step for the browser client.

import { Screen, type Transition } from "../app/Screen";
import type { App } from "../app/App";
import { Connection } from "../net/Connection";
import {
  CONTENT_TEXT,
  HDR_COLOR,
  HEADING_FONT_SIZE,
  BTN_HEIGHT,
  BTN_WIDTH,
} from "../ui/theme";
import { drawText } from "../ui/Text";

function defaultWsUrl(): string {
  // Explicit override baked in at build time, if provided.
  const env = (import.meta as { env?: Record<string, string> }).env;
  if (env?.VITE_WS_URL) return env.VITE_WS_URL;
  const { protocol, hostname, port } = window.location;
  // Served over TLS: the game WS must be wss:// and browsers block plain
  // ws:// (mixed content) — assume the same origin proxies /ws to the
  // GameHost (see the nginx location block in the deploy notes).
  if (protocol === "https:") {
    return `wss://${hostname}${port ? `:${port}` : ""}/ws`;
  }
  // Dev/default: the GameHost WS listener is on 7778.
  return `ws://${hostname || "127.0.0.1"}:7778`;
}

export class ConnectScreen extends Screen {
  private urlText = defaultWsUrl();
  private nameText = "Player";
  private connecting = false;
  private status = "";

  constructor(app: App) {
    super(app);
  }

  render(_dt: number): Transition | null {
    const { ui } = this;
    const ctx = ui.ctx;
    const w = ui.w;
    const cx = Math.floor(w / 2);
    const fieldW = 360;
    const fx = cx - fieldW / 2;

    drawText(ctx, "Connect to Server", cx, 80, {
      size: HEADING_FONT_SIZE,
      color: CONTENT_TEXT,
      align: "center",
      bold: true,
    });

    let y = 180;
    drawText(ctx, "Server (WebSocket URL)", fx, y, { size: 14, color: HDR_COLOR });
    y += 22;
    this.urlText = ui.textInput("connect.url", fx, y, fieldW, this.urlText, { maxLen: 128, h: 34 });
    y += 56;

    drawText(ctx, "Player Name", fx, y, { size: 14, color: HDR_COLOR });
    y += 22;
    this.nameText = ui.textInput("connect.name", fx, y, fieldW, this.nameText, { maxLen: 24, h: 34 });
    y += 64;

    // Connect / Back buttons
    const conn = this.app.conn;
    if (!this.connecting) {
      if (ui.button("connect.go", fx, y, fieldW, BTN_HEIGHT, "Connect")) {
        const name = this.nameText.trim() || "Player";
        const c = new Connection(this.urlText.trim(), name);
        c.connect();
        this.app.conn = c;
        this.connecting = true;
        this.status = "Connecting…";
      }
    } else if (conn) {
      // Advance once the handshake basics are in.
      if (conn.error) {
        this.status = `Error: ${conn.error}`;
        this.connecting = false;
        conn.close();
        this.app.conn = null;
      } else if (conn.connected && conn.playerId > 0 && conn.aiChoices) {
        return { next: "create_lobby" };
      } else {
        this.status = conn.connected ? "Handshaking…" : "Connecting…";
      }
      drawText(ctx, this.status, cx, y + 8, { size: 16, color: HDR_COLOR, align: "center" });
    }

    if (this.status && !this.connecting) {
      drawText(ctx, this.status, cx, y + BTN_HEIGHT + 16, {
        size: 16,
        color: [220, 110, 110],
        align: "center",
      });
    }

    const backY = ui.h - 58;
    if (ui.button("connect.back", cx - BTN_WIDTH / 2, backY, BTN_WIDTH, BTN_HEIGHT, "Back")) {
      if (this.app.conn) {
        this.app.conn.close();
        this.app.conn = null;
      }
      return { next: "main_menu" };
    }
    return null;
  }
}
