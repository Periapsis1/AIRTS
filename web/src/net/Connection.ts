// WebSocket connection to the Python GameHost. Mirrors networking/client.py:
// drives the handshake, answers pings, exposes lobby state, queues outbound
// commands, and provides frame-skip polling of the latest state frame.

import type {
  AiChoices,
  GameOver,
  GameStart,
  LobbyStatus,
  SerializedCommand,
  ServerMessage,
  StateFrame,
  StatsPayload,
} from "./MessageTypes";

export type ConnEvent =
  | { kind: "game_over"; winner: number; stats?: StatsPayload }
  | { kind: "return_to_lobby" }
  | { kind: "rejected"; reason: string };

const RECONNECT_RETRY_MS = 1500;
const RECONNECT_GIVE_UP_MS = 45_000; // server holds the slot for 60s

export class Connection {
  readonly url: string;
  readonly playerName: string;

  private ws: WebSocket | null = null;

  connected = false;
  error: string | null = null;

  // Mid-game reconnect state
  private reconnectToken: string | null = null;
  private closedByUs = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectStarted = 0;
  reconnecting = false;
  /** Set once a reconnect attempt has permanently failed. */
  connectionLost = false;

  // Lobby/handshake state
  playerId = 0;
  hostName = "";
  aiChoices: AiChoices | null = null;
  serverConfig: Record<string, unknown> | null = null;
  lobbyStatus: LobbyStatus | null = null;
  lobbySettings: Record<string, unknown> | null = null;
  pings: Record<number, number> = {};

  // Game state
  gameStart: GameStart | null = null;
  gameStarted = false;
  gameOver: GameOver | null = null;

  private latestState: StateFrame | null = null;
  private stateDirty = false;
  private events: ConnEvent[] = [];

  constructor(url: string, playerName: string) {
    this.url = url;
    this.playerName = playerName;
  }

  connect(): void {
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      this.error = `Failed to open WebSocket: ${(e as Error).message}`;
      return;
    }
    this.ws.onopen = () => {
      this.connected = true;
      this.reconnecting = false;
    };
    this.ws.onclose = () => {
      this.connected = false;
      if (this.canReconnect()) {
        this.scheduleReconnect();
      } else if (!this.reconnecting && !this.error) {
        this.error = "Connection closed";
      }
    };
    this.ws.onerror = () => {
      if (!this.reconnecting && !this.error) this.error = "Connection error";
    };
    this.ws.onmessage = (ev) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      this.handle(msg);
    };
  }

  // -- mid-game reconnect -------------------------------------------------

  private canReconnect(): boolean {
    return (
      !this.closedByUs &&
      !this.connectionLost &&
      this.reconnectToken !== null &&
      this.gameStarted &&
      this.gameOver === null
    );
  }

  private scheduleReconnect(): void {
    if (!this.reconnecting) {
      this.reconnecting = true;
      this.reconnectStarted = Date.now();
    }
    if (Date.now() - this.reconnectStarted > RECONNECT_GIVE_UP_MS) {
      this.reconnecting = false;
      this.connectionLost = true;
      this.error = "Connection lost";
      return;
    }
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.canReconnect()) return;
      // Fresh socket; on lobby_info we re-join with the reconnect token and
      // the server rebinds our old slot, then state frames resume.
      this.connect();
    }, RECONNECT_RETRY_MS);
  }

  private send(obj: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  private handle(msg: ServerMessage): void {
    switch (msg.msg) {
      case "lobby_info":
        // On reconnect the first lobby_info carries a provisional id (0 when
        // the server is "full" with our held slot); the post-rebind resend
        // carries the real one — accept whichever is latest and non-zero.
        if (msg.client_player_id || !this.reconnectToken) this.playerId = msg.client_player_id;
        this.hostName = msg.host_name;
        if (msg.ai_choices) this.aiChoices = msg.ai_choices;
        // Reply with join immediately (matches client.py). Include the
        // reconnect token when we have one so the server can rebind us.
        this.send({
          msg: "join",
          player_name: this.playerName,
          ...(this.reconnectToken ? { reconnect_token: this.reconnectToken } : {}),
        });
        break;
      case "session":
        this.reconnectToken = msg.token;
        break;
      case "server_config":
        this.serverConfig = msg.config;
        break;
      case "lobby_status":
        this.lobbyStatus = msg;
        break;
      case "lobby_settings": {
        const { msg: _m, ...rest } = msg;
        void _m;
        this.lobbySettings = rest;
        break;
      }
      case "ping":
        this.send({ msg: "pong", id: msg.id });
        break;
      case "pings": {
        const table: Record<number, number> = {};
        for (const [k, v] of Object.entries(msg.pings)) table[Number(k)] = v;
        this.pings = table;
        break;
      }
      case "game_start":
        this.gameStart = msg;
        this.gameStarted = true;
        break;
      case "state":
        // Frame-skip: keep only the newest frame; render polls it.
        this.latestState = msg;
        this.stateDirty = true;
        break;
      case "game_over":
        this.gameOver = msg;
        this.events.push({ kind: "game_over", winner: msg.winner, stats: msg.stats });
        break;
      case "return_to_lobby":
        this.gameStarted = false;
        this.events.push({ kind: "return_to_lobby" });
        break;
      case "rejected":
        this.error = msg.reason;
        if (this.reconnecting) {
          this.reconnecting = false;
          this.connectionLost = true;
        }
        this.events.push({ kind: "rejected", reason: msg.reason });
        break;
    }
  }

  /** Latest state frame since the last poll, or null if nothing new. */
  pollState(): StateFrame | null {
    if (!this.stateDirty) return null;
    this.stateDirty = false;
    return this.latestState;
  }

  /** Drain queued non-state events (game_over / return_to_lobby / rejected). */
  pollEvents(): ConnEvent[] {
    const out = this.events;
    this.events = [];
    return out;
  }

  sendCommand(cmd: SerializedCommand): void {
    this.send({ msg: "command", command: JSON.stringify(cmd) });
  }

  sendStartGame(config: Record<string, unknown>): void {
    this.send({ msg: "start_game", config });
  }

  sendLobbySettings(settings: Record<string, unknown>): void {
    this.send({ msg: "lobby_settings", ...settings });
  }

  close(): void {
    this.closedByUs = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnecting = false;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
  }
}
