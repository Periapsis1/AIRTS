// Zoom & pan viewport into the world — port of core/camera.py.
// Coordinates are in CSS pixels; the renderer composes DPR on top.

export interface WorldRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export class Camera {
  viewportW: number;
  viewportH: number;
  worldW: number;
  worldH: number;
  minZoom: number;
  maxZoom: number;
  zoom: number;
  cx: number;
  cy: number;

  constructor(viewportW: number, viewportH: number, worldW: number, worldH: number, maxZoom = 3.0) {
    this.viewportW = viewportW;
    this.viewportH = viewportH;
    this.worldW = worldW;
    this.worldH = worldH;
    this.minZoom = Math.min(viewportW / worldW, viewportH / worldH);
    if (this.minZoom > 1.0) this.minZoom = 1.0;
    this.maxZoom = maxZoom;
    this.zoom = this.minZoom < 1.0 ? this.minZoom : 1.0;
    this.cx = worldW / 2;
    this.cy = worldH / 2;
    this.clamp();
  }

  /** Update the on-screen viewport size (e.g. on window resize). */
  setViewport(w: number, h: number): void {
    this.viewportW = w;
    this.viewportH = h;
    this.minZoom = Math.min(w / this.worldW, h / this.worldH);
    if (this.minZoom > 1.0) this.minZoom = 1.0;
    if (this.zoom < this.minZoom) this.zoom = this.minZoom;
    this.clamp();
  }

  pan(dxScreen: number, dyScreen: number): void {
    this.cx -= dxScreen / this.zoom;
    this.cy -= dyScreen / this.zoom;
    this.clamp();
  }

  zoomAt(screenX: number, screenY: number, factor: number): void {
    const [wx, wy] = this.screenToWorld(screenX, screenY);
    let nz = this.zoom * factor;
    nz = Math.max(this.minZoom, Math.min(this.maxZoom, nz));
    this.zoom = nz;
    this.cx = wx + (this.viewportW / 2 - screenX) / this.zoom;
    this.cy = wy + (this.viewportH / 2 - screenY) / this.zoom;
    this.clamp();
  }

  centerOn(wx: number, wy: number): void {
    this.cx = wx;
    this.cy = wy;
    this.clamp();
  }

  reset(): void {
    this.zoom = this.minZoom < 1.0 ? this.minZoom : 1.0;
    this.cx = this.worldW / 2;
    this.cy = this.worldH / 2;
    this.clamp();
  }

  screenToWorld(sx: number, sy: number): [number, number] {
    const wx = this.cx - this.viewportW / (2 * this.zoom) + sx / this.zoom;
    const wy = this.cy - this.viewportH / (2 * this.zoom) + sy / this.zoom;
    return [wx, wy];
  }

  worldToScreen(wx: number, wy: number): [number, number] {
    const sx = (wx - this.cx) * this.zoom + this.viewportW / 2;
    const sy = (wy - this.cy) * this.zoom + this.viewportH / 2;
    return [sx, sy];
  }

  getWorldViewportRect(): WorldRect {
    const halfW = this.viewportW / (2 * this.zoom);
    const halfH = this.viewportH / (2 * this.zoom);
    return { x: this.cx - halfW, y: this.cy - halfH, w: halfW * 2, h: halfH * 2 };
  }

  private clamp(): void {
    this.cx = Math.max(0, Math.min(this.worldW, this.cx));
    this.cy = Math.max(0, Math.min(this.worldH, this.cy));
  }
}
