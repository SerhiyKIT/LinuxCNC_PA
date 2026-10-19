// clients/android/tests/e2e_browser.mjs
// Справжній додаток у headless Chrome з емуляцією телефона (через DevTools Protocol):
// підключення, керування, jog утриманням пальця, запис точок. Запуск — з run_e2e.py.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const HTTP = process.env.E2E_HTTP;
const SHOTS = process.env.E2E_SHOTS;
const port = 9300 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(path.join(tmpdir(), "cnc-chrome-"));
const chrome = spawn("google-chrome", [
  "--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "about:blank",
], { stdio: "ignore" });
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

async function pageSocket() {
  for (let i = 0; i < 100; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await tick(100);
  }
  throw new Error("Chrome не запустився");
}

let id = 0;
const waiting = new Map();
const ws = new WebSocket(await pageSocket());
await new Promise((r) => { ws.onopen = r; });
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && waiting.has(msg.id)) {
    waiting.get(msg.id)(msg);
    waiting.delete(msg.id);
  }
};
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const n = ++id;
    waiting.set(n, (m) => (m.error ? reject(new Error(`${method}: ${m.error.message}`)) : resolve(m.result)));
    ws.send(JSON.stringify({ id: n, method, params }));
  });
}
async function js(expr) {
  const r = await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`JS: ${r.exceptionDetails.text} у ${expr}`);
  return r.result.value;
}
async function waitFor(expr, what, ms = 5000) {
  for (let t = 0; t < ms; t += 50) {
    if (await js(expr)) return;
    await tick(50);
  }
  throw new Error(`не дочекались: ${what}; журнал:\n${await js('document.getElementById("log").textContent')}`);
}
async function shot(name) {
  if (!SHOTS) return;
  const { data } = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(path.join(SHOTS, `${name}.png`), Buffer.from(data, "base64"));
}
const click = (sel) => js(`document.querySelector(${JSON.stringify(sel)}).click()`);

async function touchHold(selector, ms) {
  const box = await js(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  await cdp("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x, y: box.y }] });
  await tick(ms);
  await cdp("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

try {
  await cdp("Emulation.setDeviceMetricsOverride", { width: 412, height: 915, deviceScaleFactor: 2, mobile: true });
  await cdp("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Page.navigate", { url: HTTP });
  await waitFor('document.readyState === "complete" && !!document.getElementById("jog").children.length', "завантаження");
  assert.equal(await js('document.getElementById("host").value'), new URL(HTTP).host);   // адреса підставилась сама
  await shot("1-link");

  await js(`document.getElementById("pin").value = ${JSON.stringify(process.env.E2E_PIN)}`);
  await click("#connect");
  await waitFor('!document.getElementById("take").disabled', "підключення");
  await click("#take");
  await waitFor('document.getElementById("take").classList.contains("on")', "взяти керування");
  if (process.env.E2E_READONLY) {
    // Живий робот: лише підключення, статус і списки — жодного руху
    await waitFor('document.getElementById("state").textContent !== "Не підключено"', "статус");
    await shot("live-control");
    await click('.tabs button[data-tab="programs"]');
    await click("#ls");
    await tick(500);
    await shot("live-programs");
    await click("#take");                       // віддати керування
    await waitFor('!document.getElementById("take").classList.contains("on")', "віддати керування");
    console.log("OK LIVE: стан", await js('document.getElementById("state").textContent'),
                "| J:", await js('[...document.querySelectorAll(".jog-val")].map(e => e.textContent).join(" ")'));
    process.exitCode = 0;
  } else {
  await waitFor('document.getElementById("state").textContent === "Увімкнено"', "статус On");
  assert.equal(await js('document.querySelector(".tabs button.active").dataset.tab'), "control");
  console.log("OK UI: підключення за PIN, керування, статус «Увімкнено»");

  // Утримання «+» для J1 пальцем: має піти jogc, потім jogstop
  await touchHold('.jog-row[data-index="1"] .jog-btn[data-dir="1"]', 400);
  await waitFor('document.getElementById("log").textContent.includes("jogstop J1")', "jogstop після відпускання");
  console.log("OK UI: jog J1 утриманням пальця і зупинка при відпусканні");

  await click("#space-w");
  await waitFor('document.querySelector(\'.jog-row[data-index="0"] .jog-name\').textContent.startsWith("X")', "світові осі");
  await shot("2-control-world");

  await click('.tabs button[data-tab="teach"]');
  await click("#rec-j");
  await click("#rec-l");
  await waitFor('document.querySelectorAll("#steps li").length === 2', "2 записані точки");
  await click("#steps li:first-child");
  await shot("3-teach");
  assert.equal(await js('document.getElementById("st-goto").disabled'), false);
  console.log("OK UI: записано MoveJ і MoveL, «Перейти до точки» доступна");

  await click("#prog-run");
  await waitFor('document.getElementById("log").textContent.includes("▶ Запущено")', "запуск програми");
  console.log("OK UI: програму завантажено і запущено з телефона");

  await click('.tabs button[data-tab="programs"]');
  await click("#ls");
  await waitFor('document.querySelectorAll("#files li").length >= 1', "список програм");
  await shot("4-programs");
  console.log("OK UI: список програм на роботі");
  }
} finally {
  ws.close();
  chrome.kill();
  await tick(300);
  rmSync(profile, { recursive: true, force: true });
}
