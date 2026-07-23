// DPR-aware text helpers with width caching. pygame uses SysFont(None, size);
// we approximate with a system sans-serif at the same pixel size.

import { FONT_FAMILY, type RGB, type RGBA, rgb } from "./theme";

const widthCache = new Map<string, number>();

export function fontStr(size: number, bold = false): string {
  return `${bold ? "bold " : ""}${size}px ${FONT_FAMILY}`;
}

export function measure(ctx: CanvasRenderingContext2D, text: string, size: number, bold = false): number {
  const key = `${size}|${bold ? 1 : 0}|${text}`;
  const cached = widthCache.get(key);
  if (cached !== undefined) return cached;
  ctx.font = fontStr(size, bold);
  const w = ctx.measureText(text).width;
  widthCache.set(key, w);
  return w;
}

export interface TextOpts {
  size?: number;
  color?: RGB | RGBA;
  align?: CanvasTextAlign; // default "left"
  baseline?: CanvasTextBaseline; // default "top"
  bold?: boolean;
}

export function drawText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  opts: TextOpts = {},
): void {
  const size = opts.size ?? 16;
  ctx.font = fontStr(size, opts.bold ?? false);
  ctx.fillStyle = rgb(opts.color ?? [220, 220, 240]);
  ctx.textAlign = opts.align ?? "left";
  ctx.textBaseline = opts.baseline ?? "top";
  ctx.fillText(text, Math.round(x), Math.round(y));
}
