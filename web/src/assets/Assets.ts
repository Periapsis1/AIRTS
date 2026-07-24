// Lightweight async image assets. The nebula background tile loads in the
// background; the renderer uses it once `complete`, falling back to a flat
// fill until then (so first frames never block).

// Base-relative so tiles resolve at any mount point (see `base` in vite.config.ts).
const BASE = (import.meta as { env?: Record<string, string> }).env?.BASE_URL ?? "/";

const NEBULA_URLS = [
  `${BASE}tiles/nebula1.png`,
  `${BASE}tiles/nebula2.png`,
  `${BASE}tiles/nebula3.png`,
];

class AssetStore {
  nebula: HTMLImageElement | null = null;

  /** Begin loading a nebula tile (idempotent). */
  loadNebula(): void {
    if (this.nebula) return;
    const idx = Math.floor(performance.now() / 1000) % NEBULA_URLS.length;
    const img = new Image();
    img.src = NEBULA_URLS[idx];
    this.nebula = img;
  }
}

export const assets = new AssetStore();
