// Builds and sends GameCommands (the exact types from systems/commands.py).
// The server overrides player_id to the connection's slot for security, so the
// value sent here is advisory; tick is the latest state tick.

import type { Connection } from "../net/Connection";
import type { SerializedCommand } from "../net/MessageTypes";

export class Commander {
  private conn: Connection;
  private getTick: () => number;

  constructor(conn: Connection, getTick: () => number) {
    this.conn = conn;
    this.getTick = getTick;
  }

  private send(type: string, data: Record<string, unknown>): void {
    const cmd: SerializedCommand = {
      type,
      player_id: this.conn.playerId,
      tick: this.getTick(),
      data,
    };
    this.conn.sendCommand(cmd);
  }

  move(unitIds: number[], targets: [number, number][], queue = false): void {
    const data: Record<string, unknown> = { unit_ids: unitIds, targets };
    if (queue) data.queue = true;
    this.send("move", data);
  }

  fight(unitIds: number[], targets: [number, number][], queue = false): void {
    const data: Record<string, unknown> = { unit_ids: unitIds, targets };
    if (queue) data.queue = true;
    this.send("fight", data);
  }

  attackMove(unitIds: number[], targets: [number, number][], queue = false): void {
    const data: Record<string, unknown> = { unit_ids: unitIds, targets };
    if (queue) data.queue = true;
    this.send("attack_move", data);
  }

  attack(unitId: number, targetId: number, queue = false): void {
    const data: Record<string, unknown> = { unit_id: unitId, target_id: targetId };
    if (queue) data.queue = true;
    this.send("attack", data);
  }

  stop(unitIds: number[]): void {
    this.send("stop", { unit_ids: unitIds });
  }

  setFireMode(unitIds: number[], mode: "hold_fire" | "free_fire" | "target_fire"): void {
    this.send("set_fire_mode", { unit_ids: unitIds, mode });
  }

  setRally(pos: [number, number]): void {
    this.send("set_rally", { position: pos });
  }

  setSpawnType(unitType: string): void {
    this.send("set_spawn_type", { unit_type: unitType });
  }

  upgradeExtractor(entityId: number, path: "outpost" | "research_lab"): void {
    this.send("upgrade_extractor", { entity_id: entityId, path });
  }

  setResearchType(entityId: number, unitType: string): void {
    this.send("set_research_type", { entity_id: entityId, unit_type: unitType });
  }

  chat(message: string, mode: "all" | "team"): void {
    this.send("chat", { message, mode });
  }

  surrender(): void {
    this.send("surrender", {});
  }
}
