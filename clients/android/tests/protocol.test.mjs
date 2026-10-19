// clients/android/tests/protocol.test.mjs — логіка протоколу без браузера
import assert from "node:assert/strict";
import { test } from "node:test";

import { CncClient, CommandError, JogHold, LineAssembler, allHomed, parseLine } from "../js/protocol.js";

const enc = new TextEncoder();
const dec = new TextDecoder();
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));

test("розбір рядків", () => {
  assert.deepEqual(parseLine("OK jog J1 5 @5").reply, { ok: true, cmd: "jog", data: "J1 5 @5", code: "" });
  const err = parseLine("ERR state спершу home all").reply;
  assert.equal(err.ok, false);
  assert.equal(err.code, "state");
  assert.equal(err.data, "спершу home all");
  const st = parseLine('EVT S {"st":"on","homed":[1,1],"w":[1,2,3,4,5,6],"new":1}');
  assert.equal(st.kind, "status");
  assert.equal(st.status.st, "on");
  assert.equal(st.status.u, "in");                       // типові поля доповнюються
  assert.ok(allHomed(st.status));
  assert.equal(parseLine("EVT E watchdog J0").text, "watchdog J0");
  assert.equal(parseLine("EVT S {bad").kind, "unknown");
});

test("збирання UTF-8 з дрібних пакетів", () => {
  const a = new LineAssembler();
  const bytes = enc.encode('OK ls ["Деталь.ngc"]\r\nEVT E x\n');
  const lines = [];
  for (let i = 0; i < bytes.length; i += 7) lines.push(...a.feed(bytes.slice(i, i + 7)));
  assert.deepEqual(lines, ['OK ls ["Деталь.ngc"]', "EVT E x"]);
});

function loopback() {
  const sent = [];
  const client = new CncClient((b) => sent.push(dec.decode(b)));
  return { client, sent };
}

test("черга відповідей і помилки", async () => {
  const { client, sent } = loopback();
  const events = [];
  client.onEventError = (t) => events.push(t);
  const a = client.take();
  const b = client.power(true);
  assert.deepEqual(sent, ["take\n", "power on\n"]);
  client.feed(enc.encode("EVT E something\nOK take\nERR state estop off\n"));
  assert.equal(await a, "");
  await assert.rejects(b, (e) => e instanceof CommandError && e.code === "state" && e.text === "estop off");
  assert.deepEqual(events, ["something"]);
});

test("тайм-аут не зсуває чергу", async () => {
  const { client } = loopback();
  await assert.rejects(client.command("status", 10), (e) => e.code === "timeout");
  const v = client.version();
  client.feed(enc.encode("OK ver 1\n"));
  assert.equal(await v, 1);
});

test("обрив з'єднання відхиляє очікування; PIN не потрапляє в журнал", async () => {
  const { client } = loopback();
  const lines = [];
  client.onLine = (d, t) => lines.push(t);
  const p = client.login("123456");
  client.connectionLost();
  await assert.rejects(p, (e) => e.code === "link");
  assert.ok(!lines.join(" ").includes("123456"));
});

function autoReply(delay = 0) {
  const sent = [];
  let client;
  client = new CncClient((b) => {
    const line = dec.decode(b).replace(/\n$/, "");
    sent.push(line);
    setTimeout(() => client.feed(enc.encode(`OK ${line.split(" ")[0]}\n`)), delay);
  });
  return { client, sent };
}

test("утримання jog: ping до відпускання, потім jogstop", async () => {
  const { client, sent } = autoReply();
  const jog = new JogHold(client, () => {}, 20);
  await jog.start("Z", 1, 0.3);
  await tick(95);
  await jog.stop();
  await tick(10);
  assert.equal(sent[0], "jogwc Z + 0.3");
  assert.ok(sent.filter((s) => s === "ping").length >= 3);
  assert.equal(sent.at(-1), "jogstop Z");
  assert.equal(jog.active, false);
});

test("відпускання до відповіді на jogc не запускає heartbeat", async () => {
  const { client, sent } = autoReply(30);
  const jog = new JogHold(client, () => {}, 10);
  const press = jog.start(0, -1, 5);
  await tick(5);
  await jog.stop();
  await press;
  await tick(60);
  assert.deepEqual(sent, ["jogc J0 - 5", "jogstop J0"]);
  assert.equal(jog.timer, null);
});

test("jog кроком: joint і світова вісь", async () => {
  const { client, sent } = autoReply();
  await client.jogStep(2, -0.5);
  await client.jogStep("X", 1);
  assert.deepEqual(sent, ["jog J2 -0.5", "jogw X +1"]);
});

test("завантаження програми рядками", async () => {
  const { client, sent } = autoReply();
  const progress = [];
  await client.uploadProgram("p.ngc", "G20\n\nM2\n", (i, n) => progress.push([i, n]));
  assert.deepEqual(sent, ["file begin p.ngc", "file data G20", "file data ", "file data M2", "file end"]);
  assert.deepEqual(progress.at(-1), [3, 3]);
});
