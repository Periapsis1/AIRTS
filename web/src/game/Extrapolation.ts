// Client-side movement extrapolation — port of client_game.py's
// _update/_apply_extrapolation + _effective_speed. Smooths unit motion at
// 60fps between ~10Hz server frames: velocity from position delta when the
// command is unchanged, else aim straight at the target on a new command.

import type { StaticConfig } from "../config/StaticConfig";
import type { AnyEntity, UnitEntity } from "../net/MessageTypes";

type Vec = [number, number];
type TargetKey = string; // (tx, ty, hasAttackTarget)

export class Extrapolation {
  private cfg: StaticConfig;
  private lastPositions = new Map<number, Vec>();
  private lastTargets = new Map<number, TargetKey>();
  private velocities = new Map<number, Vec>();
  private lastExtrapTick = 0;
  private extrapDt = 0;

  constructor(cfg: StaticConfig) {
    this.cfg = cfg;
  }

  private effectiveSpeed(e: UnitEntity): number {
    const base = this.cfg.speedFor(e.ut);
    if (base <= 0) return 0;
    let mult = 1;
    for (const ab of e.abs ?? []) {
      if (ab.n === "focus") {
        const timer = ab.tm ?? 0;
        if (timer > 0) {
          const t = timer / 3;
          mult *= 0.25 + 0.75 * (1 - t);
        }
      } else if (ab.n === "electric_armor") {
        mult *= 1 + 0.1 * (ab.s ?? 0);
      } else if (ab.n === "combat_stim" && ab.a) {
        const missing = Math.max(0, (e.mhp ?? 0) - (e.hp ?? 0));
        mult *= 1 + 0.05 * Math.floor(missing / 10);
      }
    }
    return base * mult;
  }

  /** Recompute velocity predictions from a freshly received server frame. */
  update(entities: AnyEntity[], tick: number): void {
    const tickDelta = tick - this.lastExtrapTick;
    const frameDt = tickDelta > 0 ? tickDelta * this.cfg.fixedDt : 0;
    const positions = new Map<number, Vec>();
    const targets = new Map<number, TargetKey>();
    const velocities = new Map<number, Vec>();

    for (const ent of entities) {
      if (ent.t !== "U") continue;
      const e = ent as UnitEntity;
      const id = e.id;
      const ex = e.x;
      const ey = e.y;
      positions.set(id, [ex, ey]);

      let tx = e.tx;
      let ty = e.ty;
      if (tx === undefined || ty === undefined) {
        tx = e.atx;
        ty = e.aty;
      }
      const curKey: TargetKey = `${e.tx ?? "_"},${e.ty ?? "_"},${e.atx !== undefined}`;
      targets.set(id, curKey);

      const prevPos = this.lastPositions.get(id);
      const prevKey = this.lastTargets.get(id);
      const newCommand = prevKey !== undefined && prevKey !== curKey;

      if (prevPos && frameDt > 0 && !newCommand) {
        velocities.set(id, [(ex - prevPos[0]) / frameDt, (ey - prevPos[1]) / frameDt]);
      } else if (tx !== undefined && ty !== undefined) {
        const dx = tx - ex;
        const dy = ty - ey;
        const dist = Math.hypot(dx, dy);
        if (dist > 0.5) {
          const speed = this.effectiveSpeed(e);
          velocities.set(id, [(dx / dist) * speed, (dy / dist) * speed]);
        } else {
          velocities.set(id, [0, 0]);
        }
      } else {
        velocities.set(id, [0, 0]);
      }
    }

    this.lastPositions = positions;
    this.lastTargets = targets;
    this.lastExtrapTick = tick;
    this.velocities = velocities;
    this.extrapDt = 0;
  }

  /** Advance the extrapolation clock by a render dt (seconds). */
  tick(dt: number): void {
    this.extrapDt += dt;
  }

  /** Return entities with unit positions extrapolated forward in place-copy. */
  apply(entities: AnyEntity[]): AnyEntity[] {
    const dt = this.extrapDt;
    if (dt <= 0) return entities;
    const out: AnyEntity[] = [];
    for (const ent of entities) {
      if (ent.t === "U") {
        const v = this.velocities.get(ent.id);
        const base = this.lastPositions.get(ent.id);
        if (v && base && (v[0] !== 0 || v[1] !== 0)) {
          out.push({ ...ent, x: base[0] + v[0] * dt, y: base[1] + v[1] * dt });
          continue;
        }
      }
      out.push(ent);
    }
    return out;
  }

  reset(): void {
    this.lastPositions.clear();
    this.lastTargets.clear();
    this.velocities.clear();
    this.lastExtrapTick = 0;
    this.extrapDt = 0;
  }
}
