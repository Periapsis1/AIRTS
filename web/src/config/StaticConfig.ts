// Typed view of the server's `server_config` message (built by
// networking/static_config.py). Keeps the browser's display constants in sync
// with the Python `config/` without hand-copying them. Falls back to sane
// defaults if a field is missing so rendering never crashes.

import type { RGB } from "../ui/theme";

export interface UnitStat {
  hp: number;
  speed: number;
  radius: number;
  symbol: [number, number][] | null;
  can_attack: boolean;
  fov: number;
  turn_rate: number;
  los: number;
  hollow?: boolean;
  is_building?: boolean;
  is_t2?: boolean;
  spawn_count?: number;
  weapon?: Record<string, unknown>;
}

export interface OutpostStats {
  hp_bonus: number;
  heal_per_sec: number;
  los: number;
  laser_damage: number;
  laser_range: number;
  laser_cooldown: number;
}

export interface ReinforceStats {
  max_stacks: number;
  stack_interval: number;
  hp_bonus: number;
  bonus_multiplier: number;
}

export class StaticConfig {
  raw: Record<string, unknown>;
  unitTypes: Record<string, UnitStat>;
  t2Names: Record<string, string>;
  spawnableTypes: string[];
  playerColors: RGB[];
  teamColors: Record<number, RGB>;
  selectedColor: RGB;
  broadcastInterval: number;
  fixedDt: number;
  ccRadius: number;
  ccHp: number;
  ccLaserRange: number;
  outpostLaserRange: number;
  metalCaptureRadius: number;
  metalExtractorHp: number;
  outpostLos: number;
  zoomStep: number;
  maxZoom: number;
  edgePanMargin: number;
  edgePanSpeed: number;
  healthBarWidth: number;
  healthBarHeight: number;
  healthBarOffset: number;
  outpostUpgradeDuration: number;
  researchLabUpgradeDuration: number;
  t2SpawnBonus: number;
  outpost: OutpostStats;
  researchLabHpBonus: number;
  reinforce: ReinforceStats;
  abilityDescriptions: Record<string, string>;

  constructor(raw: Record<string, unknown> | null) {
    this.raw = raw ?? {};
    const r = this.raw;
    this.unitTypes = (r.unit_types as Record<string, UnitStat>) ?? {};
    this.t2Names = (r.t2_names as Record<string, string>) ?? {};
    this.spawnableTypes = (r.spawnable_types as string[]) ?? [];
    this.playerColors = ((r.player_colors as number[][]) ?? []).map(
      (c) => [c[0], c[1], c[2]] as RGB,
    );
    this.teamColors = {};
    const tc = (r.team_colors as Record<string, number[]>) ?? {};
    for (const [k, v] of Object.entries(tc)) {
      this.teamColors[Number(k)] = [v[0], v[1], v[2]] as RGB;
    }
    const sc = (r.selected_color as number[]) ?? [0, 255, 100];
    this.selectedColor = [sc[0], sc[1], sc[2]];
    this.broadcastInterval = (r.broadcast_interval as number) ?? 6;
    const timing = (r.timing as Record<string, number>) ?? {};
    this.fixedDt = timing.fixed_dt ?? 1 / 60;
    const cc = (r.command_center as Record<string, number>) ?? {};
    this.ccRadius = cc.radius ?? 10;
    this.ccHp = cc.hp ?? 1000;
    this.ccLaserRange = cc.laser_range ?? 75;
    this.outpostLaserRange = 75;
    const metal = (r.metal as Record<string, number>) ?? {};
    this.metalCaptureRadius = metal.capture_radius ?? 15;
    this.metalExtractorHp = 200;
    const up = (r.upgrades as Record<string, unknown>) ?? {};
    this.outpostUpgradeDuration = (up.outpost_duration as number) ?? 30;
    this.researchLabUpgradeDuration = (up.research_lab_duration as number) ?? 60;
    this.t2SpawnBonus = (up.t2_spawn_bonus as number) ?? 0.2;
    const op = (up.outpost as Partial<OutpostStats>) ?? {};
    this.outpost = {
      hp_bonus: op.hp_bonus ?? 50,
      heal_per_sec: op.heal_per_sec ?? 1,
      los: op.los ?? 140,
      laser_damage: op.laser_damage ?? 15,
      laser_range: op.laser_range ?? 75,
      laser_cooldown: op.laser_cooldown ?? 2,
    };
    this.researchLabHpBonus =
      ((up.research_lab as Record<string, number>) ?? {}).hp_bonus ?? 100;
    const rf = (up.reinforce as Partial<ReinforceStats>) ?? {};
    this.reinforce = {
      max_stacks: rf.max_stacks ?? 4,
      stack_interval: rf.stack_interval ?? 15,
      hp_bonus: rf.hp_bonus ?? 100,
      bonus_multiplier: rf.bonus_multiplier ?? 2,
    };
    this.abilityDescriptions = (r.ability_descriptions as Record<string, string>) ?? {};
    this.outpostLos = this.outpost.los;
    this.outpostLaserRange = this.outpost.laser_range;
    const cam = (r.camera as Record<string, number>) ?? {};
    this.zoomStep = cam.zoom_step ?? 1.1;
    this.maxZoom = cam.max_zoom ?? 3.0;
    this.edgePanMargin = cam.edge_pan_margin ?? 10;
    this.edgePanSpeed = cam.edge_pan_speed ?? 500;
    const hb = (r.health_bar as Record<string, number>) ?? {};
    this.healthBarWidth = hb.width ?? 24;
    this.healthBarHeight = hb.height ?? 3;
    this.healthBarOffset = hb.offset ?? 4;
  }

  teamColor(team: number): RGB {
    return this.teamColors[team] ?? this.playerColors[(team - 1) % Math.max(1, this.playerColors.length)] ?? [255, 255, 255];
  }

  /** Live LOS for an entity: prefer server-sent los, else unit-type base. */
  losFor(ut: string, sentLos: number | undefined, upgradeState?: string): number {
    if (ut === "metal_extractor" && upgradeState === "outpost") return this.outpostLos;
    if (sentLos !== undefined) return sentLos;
    return this.unitTypes[ut]?.los ?? 100;
  }

  speedFor(ut: string): number {
    return this.unitTypes[ut]?.speed ?? 0;
  }
}
