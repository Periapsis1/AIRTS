// Two-human lobby e2e: host + guest in separate browser contexts connect to
// the same server, verify roster sync, host removes the AI slot and starts,
// and both clients must enter the game on their own teams (nobody spectates).
// Requires the game server (ws 7778) and a page server (BASE) running.

import { chromium } from "playwright";

const BASE = process.env.BASE || "http://localhost:4444";
const W = 1280;
const H = 800;

const errors = [];
const browser = await chromium.launch({ channel: "chrome", headless: true });

async function newClient(tag) {
  const ctx = await browser.newContext({ viewport: { width: W, height: H } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${tag} PAGEERROR: ` + e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`${tag} CONSOLE: ` + m.text());
  });
  await page.goto(BASE, { waitUntil: "load" });
  await page.waitForTimeout(500);
  // Main menu -> Create Lobby
  await page.mouse.click(W / 2, Math.floor(H / 2) - 20 + 22);
  await page.waitForTimeout(300);
  // Connect screen: set a distinct player name (field prefilled "Player").
  await page.mouse.click(W / 2, 288); // name input
  await page.waitForTimeout(150);
  for (let i = 0; i < 8; i++) await page.keyboard.press("Backspace");
  await page.waitForTimeout(150); // let the last backspace frame flush
  await page.keyboard.type(tag, { delay: 30 });
  await page.mouse.click(W / 2, 366); // Connect
  await page.waitForTimeout(1500);
  return page;
}

const host = await newClient("Host");
await host.screenshot({ path: "shots/mp_01_host_alone.png" });

const guest = await newClient("Guest");
await guest.waitForTimeout(800); // roster + settings relay round-trip
await host.screenshot({ path: "shots/mp_02_host_sees_guest.png" });
await guest.screenshot({ path: "shots/mp_03_guest_view.png" });

// Host: remove the AI slot (row 3 after humans-first sort) -> clean 1v1.
// The × sits after the team/handicap/spectator columns: x = 551..577, y ≈ 197.
await host.mouse.click(564, 197);
await host.waitForTimeout(500);
await host.screenshot({ path: "shots/mp_04_host_1v1.png" });
await guest.screenshot({ path: "shots/mp_05_guest_1v1.png" });

// Host starts the game.
await host.mouse.click(776, H - 58 + 22);
await host.waitForTimeout(2500);
await host.screenshot({ path: "shots/mp_06_host_ingame.png" });
await guest.screenshot({ path: "shots/mp_07_guest_ingame.png" });

// Let the warp-in finish and units spawn on both.
await host.waitForTimeout(6000);
await host.screenshot({ path: "shots/mp_08_host_units.png" });
await guest.screenshot({ path: "shots/mp_09_guest_units.png" });

console.log("ERRORS:", errors.length);
for (const e of errors) console.log("  " + e);
await browser.close();
process.exit(errors.length ? 1 : 0);
