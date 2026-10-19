// clients/android/tests/e2e.mjs — протокол через справжній WebSocket -> websockify -> міст.
// Запускається з run_e2e.py (node --experimental-websocket).
import assert from "node:assert/strict";

import { makeProgram, makeStep, toGcode, fileName } from "../js/program.js";
import { CncClient, JogHold } from "../js/protocol.js";

const ws = new WebSocket(process.env.E2E_URL, ["binary"]);
ws.binaryType = "arraybuffer";
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("ws error")); });

const statuses = [];
const client = new CncClient((b) => ws.send(b), { onStatus: (s) => statuses.push(s) });
ws.onmessage = (ev) => client.feed(new Uint8Array(ev.data));
const tick = (ms) => new Promise((r) => setTimeout(r, ms));

assert.equal(await client.version(), 1);
await assert.rejects(client.take(), (e) => e.code === "auth");
await client.login(process.env.E2E_PIN);
await client.take();
await tick(100);
const s = statuses.at(-1);
assert.equal(s.st, "on");
assert.deepEqual(s.w, [17, 5.5, 7.2, 180, 0, 0]);
console.log("OK WS: pin, take, статус", JSON.stringify({ st: s.st, w: s.w, u: s.u }));

const program = makeProgram({ name: "Телефон 1", units: s.u, steps: [
  makeStep("movej", { joints: s.j.slice(0, 6), text: "P1" }),
  makeStep("movel", { pose: s.w.slice(0, 6), text: "P2" }),
] });
const result = await client.uploadProgram(fileName(program), toGcode(program));
assert.match(result, /^Телефон_1\.ngc \d+$/);
assert.deepEqual(await client.listPrograms(), ["Телефон_1.ngc"]);
await client.openProgram("Телефон_1.ngc");
await client.run();
console.log("OK WS: програму завантажено і запущено:", result);

const jog = new JogHold(client, () => {}, 50);
await jog.start("X", 1, 0.2);
await tick(180);
await jog.stop();
await client.release();
ws.close();
console.log("OK WS: jog утриманням X і зупинка");
