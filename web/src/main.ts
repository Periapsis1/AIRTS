// Bootstrap: size the canvas for HiDPI, build the UI context + App, and run a
// requestAnimationFrame loop that drives one screen render per frame.

import { Input } from "./core/Input";
import { UI } from "./ui/Widgets";
import { App } from "./app/App";
import { MENU_BG, rgb } from "./ui/theme";
import { audio } from "./audio/AudioEngine";

const canvas = document.getElementById("game") as HTMLCanvasElement;
const ctx = canvas.getContext("2d")!;

let cssW = 0;
let cssH = 0;
let dpr = 1;

function resize(): void {
  dpr = window.devicePixelRatio || 1;
  cssW = window.innerWidth;
  cssH = window.innerHeight;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.style.width = `${cssW}px`;
  canvas.style.height = `${cssH}px`;
}

window.addEventListener("resize", resize);
resize();

const input = new Input(canvas);
const ui = new UI(ctx, input);
const app = new App(ui);

// Give the canvas keyboard focus so key events arrive without a click.
canvas.focus();

// Browsers gate audio behind a user gesture — resume on the first interaction.
function unlockAudio(): void {
  audio.resume();
  window.removeEventListener("pointerdown", unlockAudio);
  window.removeEventListener("keydown", unlockAudio);
}
window.addEventListener("pointerdown", unlockAudio);
window.addEventListener("keydown", unlockAudio);
void audio.preload();

let last = performance.now();
const MAX_DT = 0.25;

function frame(now: number): void {
  let dt = (now - last) / 1000;
  last = now;
  if (dt > MAX_DT) dt = MAX_DT;

  // Reset transform each frame, then scale so the UI draws in CSS pixels.
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = rgb(MENU_BG);
  ctx.fillRect(0, 0, cssW, cssH);

  ui.beginFrame(cssW, cssH, dpr, dt);
  app.frame(dt);
  ui.flushPopups();
  ui.endFrame();
  input.endFrame();

  requestAnimationFrame(frame);
}

requestAnimationFrame(frame);
