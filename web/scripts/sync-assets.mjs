// Copies the web client's runtime assets from the repo's canonical folders
// (sounds/, sprites/) into public/, which `vite build` then bundles into
// dist/. Runs automatically via the npm "prebuild" hook. Sources are
// optional: in a web-only checkout the committed copies in public/ are kept.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..");

const MAPPING = [
  ["sounds/laser.mp3", "public/sounds/laser.mp3"],
  ["sounds/fast_laser.mp3", "public/sounds/fast_laser.mp3"],
  ["sprites/music/freemusicforvideo-space-ambient-446647.mp3", "public/music/ambient1.mp3"],
  ["sprites/music/sigmamusicart-space-ambient-background-music-462074.mp3", "public/music/ambient2.mp3"],
  ["sprites/background_tiles/blue/Blue Nebula 1 - 1024x1024.png", "public/tiles/nebula1.png"],
  ["sprites/background_tiles/blue/Blue Nebula 3 - 1024x1024.png", "public/tiles/nebula2.png"],
  ["sprites/background_tiles/blue/Blue Nebula 5 - 1024x1024.png", "public/tiles/nebula3.png"],
];

let copied = 0;
let missing = 0;
for (const [src, dest] of MAPPING) {
  const from = join(repoRoot, src);
  if (!existsSync(from)) {
    missing += 1;
    continue;
  }
  const to = join(webRoot, dest);
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(from, to);
  copied += 1;
}
console.log(
  `sync-assets: copied ${copied}/${MAPPING.length}` +
    (missing ? ` (${missing} sources missing — keeping committed public/ copies)` : ""),
);
