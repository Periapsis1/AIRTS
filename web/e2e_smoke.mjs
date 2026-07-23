// End-to-end UI smoke test: drives the built client in Chrome through
// menu -> connect -> lobby -> start -> in-game stub, screenshotting each step
// and failing on any uncaught JS/console error. Requires the game server
// (ws 7778) and a preview server (BASE) to be running.

import { chromium } from "playwright";

const BASE = process.env.BASE || "http://localhost:4444";
const W = 1280;
const H = 800;

const errors = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: W, height: H } });
page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));
page.on("console", (m) => {
  if (m.type() === "error") errors.push("CONSOLE: " + m.text());
});

async function shot(name) {
  await page.screenshot({ path: `shots/${name}.png` });
}

await page.goto(BASE, { waitUntil: "load" });
await page.waitForTimeout(700);
await shot("01_menu");

// "Create Lobby" — first menu button, centered.
const startY = Math.floor(H / 2) - 20;
await page.mouse.click(W / 2, startY + 22);
await page.waitForTimeout(400);
await shot("02_connect");

// Connect (URL + name are prefilled). Connect button center ≈ (W/2, 366).
await page.mouse.click(W / 2, 366);
await page.waitForTimeout(2000);
await shot("03_lobby");

// Optionally enable Fog of War (checkbox at ≈ (675, 379)) to test fog render.
if (process.env.FOG) {
  await page.mouse.click(675, 379);
  await page.waitForTimeout(200);
}

// Start Game — bottom-right button, center ≈ (776, 764).
await page.mouse.click(776, 764);
// Warp-in countdown is shown for the first ~3s.
await page.waitForTimeout(1400);
await shot("04_warp");

// Let units spawn + advance; the nebula background should be loaded.
await page.waitForTimeout(7600);
await page.mouse.move(W / 2, H / 2);
await shot("05_game"); // nebula + units + HUD

// Select the command center (Ctrl+Z) -> build panel.
await page.mouse.click(W / 2, 300);
await page.keyboard.down("Control");
await page.keyboard.press("z");
await page.keyboard.up("Control");
await page.waitForTimeout(300);
await shot("06_build");

// Select all army (Tab) -> FOV/range arcs + selection rings.
await page.keyboard.press("Tab");
await page.waitForTimeout(200);
await shot("07_fov");

// Right-click move.
await page.mouse.click(W / 2 + 120, H / 2 + 60, { button: "right" });
await page.waitForTimeout(300);
// Toggle the F3 perf overlay.
await page.keyboard.press("F3");
await page.waitForTimeout(200);
await shot("08_perf");

// Send a chat message -> floating text above our CC + log line.
await page.keyboard.press("Enter");
await page.waitForTimeout(250); // let the chat input open before typing
await page.keyboard.type("gg wp", { delay: 40 });
await page.waitForTimeout(150);
await page.keyboard.press("Enter");
await page.waitForTimeout(500);
await shot("09_chat");

// Open the escape menu and Surrender -> CC explosion, then results screen.
await page.keyboard.press("Escape");
await page.waitForTimeout(200);
await page.mouse.click(W / 2, H / 2 + 56); // Surrender button
await page.waitForTimeout(1200);
await shot("10_explode"); // losing CC fragments flying out
await page.waitForTimeout(3000); // explosion finishes (~3s) -> results
await shot("11_results"); // stat graph tabs + legend
// Click through a couple of graph tabs.
await page.mouse.click(W / 2 + 40, 106); // a middle tab
await page.waitForTimeout(300);
await page.mouse.move(W / 2, 300); // hover the plot -> tooltip
await page.waitForTimeout(200);
await shot("12_results_tab");

console.log("ERRORS:", errors.length);
for (const e of errors) console.log("  " + e);
await browser.close();
process.exit(errors.length ? 1 : 0);
