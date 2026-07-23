// The wire contract between the browser client and the Python GameHost.
//
// Keys mirror the compact field names produced by systems/replay.py's
// _entity_visual / _laser_visual / etc. and host.py's message builders — do
// NOT rename them; keeping them identical makes the contract auditable against
// the server. Over WebSocket these arrive as JSON text frames (no length
// prefix, no manual zlib — the WS layer + permessage-deflate handle framing
// and compression).

export type RGBTuple = [number, number, number];

// -- entity visuals (inside a `state` frame) --------------------------------

export type EntityType = "U" | "CC" | "ME" | "MS";

export interface Ability {
  n: string; // name
  a: boolean; // active
  s?: number; // stacks
  ms?: number; // max stacks
  tm?: number; // timer (seconds)
}

export interface QueuedCmd {
  t: "move" | "fight" | "attack_move" | "attack";
  x?: number;
  y?: number;
}

export interface BaseEntity {
  id: number;
  t: EntityType;
  x: number;
  y: number;
  r: number;
  tm: number; // team id
  hp: number;
  mhp: number;
  ghost?: boolean;
}

export interface UnitEntity extends BaseEntity {
  t: "U";
  ut: string; // unit_type
  pid: number; // player_id
  fa: number; // facing angle
  c: RGBTuple; // color
  t2: boolean;
  los?: number;
  rng?: number;
  hf?: boolean; // hold-fire mode
  chx?: number; // charge target x
  chy?: number; // charge target y
  chp?: number; // charge progress 0..1
  abs?: Ability[];
  tx?: number; // move target
  ty?: number;
  am?: boolean; // attack-move
  fm?: boolean; // fight-move
  atx?: number; // attack target
  aty?: number;
  cq?: QueuedCmd[];
  sel?: boolean;
}

export interface CCEntity extends BaseEntity {
  t: "CC";
  ut: "command_center";
  pid: number;
  c: RGBTuple;
  pts: [number, number][]; // hull polygon
  st: string; // spawn type
  spt: number; // spawn progress 0..1
  bp: number; // bonus percent
  rx?: number; // rally point
  ry?: number;
}

export interface MEEntity extends BaseEntity {
  t: "ME";
  ut: "metal_extractor";
  pid: number;
  rot: number;
  us: string; // upgrade_state
  utt: number; // upgrade timer progress
  rut: string; // researched unit type ("" = none)
  ifr: boolean; // is fully reinforced
  rst: number; // reinforce stacks
  rsp: number; // reinforce progress
  meb: number; // metal bonus %
}

export interface MSEntity extends BaseEntity {
  t: "MS";
  ow: number | null; // owner team or null
  cp: Record<string, number>; // capture progress per team id
}

export type AnyEntity = UnitEntity | CCEntity | MEEntity | MSEntity;

// laser: [x1, y1, x2, y2, color, width]
export type Laser = [number, number, number, number, RGBTuple, number];

export interface Splash {
  x: number;
  y: number;
  r: number;
  p: number; // progress 0..1
}

// death event: unit death burst origin (from Unit.on_death)
export interface DeathEvent {
  x: number;
  y: number;
  c: RGBTuple;
  r: number;
}

export interface ChatEvent {
  pid: number;
  name: string;
  tid: number;
  msg: string;
  mode: "all" | "team";
  tick: number;
}

// -- server -> client messages ----------------------------------------------

export interface AiChoices {
  choices: [string, string][]; // [ai_id, ai_name]
  deprecated: string[];
}

export interface LobbyInfo {
  msg: "lobby_info";
  client_player_id: number;
  host_name: string;
  ai_choices?: AiChoices;
}

export interface ServerConfigMsg {
  msg: "server_config";
  config: Record<string, unknown>;
}

export interface LobbyStatus {
  msg: "lobby_status";
  players: Record<string, { name: string; ready: boolean }>;
  max_players: number;
  host_name: string;
}

export interface Obstacle {
  shape: "rect" | "circle";
  x: number;
  y: number;
  w?: number;
  h?: number;
  r?: number;
  c: RGBTuple;
}

export interface GameStart {
  msg: "game_start";
  obstacles: Obstacle[];
  map_width: number;
  map_height: number;
  enable_t2: boolean;
  fog_of_war: boolean;
  player_team?: Record<string, number>;
  player_names?: Record<string, string>;
  team_colors?: Record<string, RGBTuple>;
  spectators?: number[];
}

export interface StateFrame {
  msg: "state";
  tick: number;
  entities: AnyEntity[];
  lasers: Laser[];
  winner: number;
  srv_ms: number;
  srv_cpu_ms: number;
  srv_tps: number;
  splashes?: Splash[];
  sounds?: string[];
  deaths?: DeathEvent[];
  chats?: ChatEvent[];
}

// Post-game stats payload (systems/stats.py GameStats.finalize()).
export interface TeamStatsSeries {
  cc_health?: number[];
  army_count?: number[];
  units_killed?: number[];
  damage_dealt?: number[];
  healing_done?: number[];
  metal_spots?: number[];
  apm?: number[];
  apm_inst?: number[];
}

export interface StatsPayload {
  timestamps?: number[];
  teams?: Record<string, TeamStatsSeries>;
  final?: Record<string, Record<string, unknown>>;
  game_duration_seconds?: number;
  step_ms?: number[];
  subsystem_ms?: Record<string, number[]>;
}

export interface GameOver {
  msg: "game_over";
  winner: number;
  stats?: StatsPayload;
}

export interface LobbySettings {
  msg: "lobby_settings";
  [key: string]: unknown;
}

export interface PingMsg {
  msg: "ping";
  id: number;
}
export interface PingsMsg {
  msg: "pings";
  pings: Record<string, number>;
}
export interface ReturnToLobby {
  msg: "return_to_lobby";
}
export interface Rejected {
  msg: "rejected";
  reason: string;
}
/** Reconnect token issued after a successful WS join (browser-only). */
export interface SessionMsg {
  msg: "session";
  token: string;
}

export type ServerMessage =
  | LobbyInfo
  | ServerConfigMsg
  | LobbyStatus
  | GameStart
  | StateFrame
  | GameOver
  | LobbySettings
  | PingMsg
  | PingsMsg
  | ReturnToLobby
  | Rejected
  | SessionMsg;

// -- client -> server messages ----------------------------------------------

export interface SerializedCommand {
  type: string;
  player_id: number;
  tick: number;
  data: Record<string, unknown>;
}
