// The render seam. GameView builds a RenderFrame (in world coordinates) each
// frame and hands it to a WorldRenderer. Canvas2DRenderer implements this now;
// a PixiWorldRenderer could implement the same interface later if large-battle
// performance demands a WebGL backend — GameView/HUD/input never change.

import type { StaticConfig } from "../config/StaticConfig";
import type { AnyEntity, Laser, Obstacle, RGBTuple, Splash } from "../net/MessageTypes";

/** Pre-simulated visual effects, in world coordinates. GameView owns the
 *  simulation; renderers just draw the snapshots. */
export interface BurstFx {
  x: number;
  y: number;
  r: number;
  color: RGBTuple;
  alpha: number; // 0..1
}

export interface FragmentFx {
  pts: [number, number][]; // absolute world coords (already rotated/translated)
  color: RGBTuple;
  alpha: number; // 0..1
}

export interface FloatingChatFx {
  x: number;
  y: number;
  text: string;
  color: RGBTuple;
  alpha: number; // 0..1
}

export interface CameraView {
  cx: number;
  cy: number;
  zoom: number;
  vpW: number; // game-area width (CSS px)
  vpH: number; // game-area height (CSS px)
  gx: number; // game-area screen origin x (CSS px)
  gy: number;
}

export type FogMode = "none" | "hard" | "soft";

export interface RenderFrame {
  cam: CameraView;
  dpr: number;
  mapW: number;
  mapH: number;
  obstacles: Obstacle[];
  entities: AnyEntity[];
  lasers: Laser[];
  splashes: Splash[];
  fogMode: FogMode;
  /** LOS circles in world coords [x, y, radius] for the fog cut-outs. */
  losCircles: [number, number, number][];
  selectedIds: Set<number>;
  /** Live right-drag command path (world coords). */
  rpath?: [number, number][];
  /** In-progress drag selection (world coords). */
  dragRect?: { x: number; y: number; w: number; h: number } | null;
  dragCircle?: { x: number; y: number; r: number } | null;
  /** Warp-in progress 0..1; while < 1, CCs draw scaled-in with a glow ring. */
  warpT?: number;
  /** Death-burst particle snapshots. */
  bursts?: BurstFx[];
  /** CC explosion fragments (game-over animation). */
  fragments?: FragmentFx[];
  /** Floating chat texts above sender CCs. */
  floatingChats?: FloatingChatFx[];
}

export interface WorldRenderer {
  init(ctx: CanvasRenderingContext2D, cfg: StaticConfig): void;
  draw(frame: RenderFrame): void;
}
