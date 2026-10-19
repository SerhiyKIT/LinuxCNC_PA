// clients/android/js/app.js
// Мобільний пульт CNC-Robot: WebSocket -> websockify -> bt-cnc-bridge (TCP 8765).
// Логіка протоколу — protocol.js, програма навчання і G-код — program.js.

import { CncClient, CommandError, JogHold, allHomed, emptyStatus, isOn } from "./protocol.js";
import {
  KIND_TITLES, ProgramError, fileName, makeProgram, makeStep, programFromJson,
  programToJson, stepSummary, toGcode,
} from "./program.js";

const JOINT_NAMES = ["J0", "J1", "J2", "J3", "J4", "J5"];
const AXES = ["X", "Y", "Z", "A", "B", "C"];
const STEP_VALUES = [0.01, 0.1, 0.5, 1, 5, 10];
const STATE_TEXT = { nocnc: "LinuxCNC не запущений", estop: "E-STOP", off: "Вимкнено", on: "Увімкнено" };
const RUN_TEXT = { idle: "очікування", run: "виконується", paused: "пауза" };
const GOTO_FILE = "_studio_goto.ngc";
const STORE_PREFIX = "cnc-robot-program:";
const CONNECT_TIMEOUT = 5000;

const $ = (id) => document.getElementById(id);

// --- сховище браузера (лише зручність; може бути недоступне) --------------------
const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch { return false; } },
  keys() { try { return Object.keys(localStorage); } catch { return []; } },
};

// --- транспорт ------------------------------------------------------------------
class WsTransport {
  constructor(onData, onClose) {
    this.onData = onData;
    this.onClose = onClose;
    this.ws = null;
  }

  get connected() { return this.ws !== null && this.ws.readyState === WebSocket.OPEN; }

  connect(url) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url, ["binary"]);
      ws.binaryType = "arraybuffer";
      const timer = setTimeout(() => { ws.close(); reject(new Error("таймаут з'єднання")); }, CONNECT_TIMEOUT);
      ws.onopen = () => { clearTimeout(timer); this.ws = ws; resolve(); };
      ws.onerror = () => { clearTimeout(timer); if (this.ws !== ws) reject(new Error("не вдалося підключитись")); };
      ws.onmessage = (ev) => this.onData(new Uint8Array(ev.data));
      ws.onclose = () => {
        clearTimeout(timer);
        if (this.ws === ws) { this.ws = null; this.onClose(); }
      };
    });
  }

  write(bytes) {
    if (!this.connected) throw new Error("немає з'єднання");
    this.ws.send(bytes);
  }

  close() {
    const ws = this.ws;
    this.ws = null;                 // відключення з нашого боку — не «обрив»
    if (ws) ws.close();
  }
}

// --- стан застосунку -----------------------------------------------------------
const app = {
  status: emptyStatus(),
  owner: false,
  space: "joint",                  // joint | world
  mode: "hold",                    // hold | step
  program: makeProgram(),
  selected: -1,
  fileSelected: null,
};

const transport = new WsTransport((bytes) => client.feed(bytes), onLinkLost);
const client = new CncClient((bytes) => transport.write(bytes), {
  onStatus: showStatus,
  onEventError: (text) => { log(`⚠ ${text}`); toast(text); },
  onLine: (dir, text) => log(`${dir} ${text}`),
});
const jog = new JogHold(client, (text) => { log(`⚠ ${text}`); toast(text); });

// --- допоміжне ------------------------------------------------------------------
function log(text) {
  const el = $("log");
  el.textContent = (el.textContent + text + "\n").split("\n").slice(-300).join("\n");
  el.scrollTop = el.scrollHeight;
}

let toastTimer = null;
function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

/** Виконати дію з показом помилок протоколу. */
async function act(fn) {
  try {
    await fn();
  } catch (err) {
    const text = err instanceof CommandError ? `${err.code}: ${err.text}` : (err.message || String(err));
    log(`✖ ${text}`);
    toast(text);
  }
}

const connected = () => transport.connected;

// --- навігація -----------------------------------------------------------------
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${btn.dataset.tab}`));
  });
});

// --- підключення ---------------------------------------------------------------
function defaultHost() {
  return store.get("cnc-robot-host") || (location.host || "");
}

$("host").value = defaultHost();

$("connect").addEventListener("click", () => act(async () => {
  if (connected()) {
    await jog.stop();
    transport.close();
    client.connectionLost();
    setConnected(false);
    log("Відключено");
    return;
  }
  const host = $("host").value.trim();
  if (!host) { toast("Вкажіть адресу робота"); return; }
  store.set("cnc-robot-host", host);
  const url = /^wss?:\/\//.test(host) ? host : `${location.protocol === "https:" ? "wss" : "ws"}://${host}/`;
  log(`Підключення до ${url}...`);
  await transport.connect(url);
  try {
    const version = await client.version();
    if (version !== 1) log(`⚠ протокол v${version}, додаток розрахований на v1`);
    await client.login($("pin").value.trim());
    await client.requestStatus();
  } catch (err) {
    transport.close();
    client.connectionLost();
    throw err;
  }
  setConnected(true);
  log("Підключено. Натисніть «Взяти керування»");
  document.querySelector('.tabs button[data-tab="control"]').click();
}));

$("pin").addEventListener("keydown", (e) => { if (e.key === "Enter") $("connect").click(); });

function onLinkLost() {
  jog.reset();                     // міст сам зупинить jog і поставить програму на паузу
  client.connectionLost();
  setConnected(false);
  log("⚠ З'єднання втрачено");
  toast("З'єднання втрачено");
}

function setConnected(on) {
  $("connect").textContent = on ? "Відключити" : "Підключити";
  $("host").disabled = on;
  $("pin").disabled = on;
  $("take").disabled = !on;
  $("estop").disabled = !on;      // E-stop доступний одразу після PIN
  $("ls").disabled = !on;
  if (!on) {
    app.owner = false;
    showStatus(emptyStatus());
    $("state").textContent = "Не підключено";
  }
  setOwner(app.owner);
}

$("take").addEventListener("click", () => act(async () => {
  if (app.owner) {
    await jog.stop();
    await client.release();
    setOwner(false);
  } else {
    await client.take();
    setOwner(true);
  }
}));

function setOwner(owner) {
  app.owner = owner;
  const take = $("take");
  take.textContent = owner ? "Віддати керування" : "Взяти керування";
  take.classList.toggle("on", owner);
  for (const id of ["reset", "power", "home", "rec-j", "rec-l", "rec-p", "prog-run", "open", "rm",
                    "c-run", "c-pause", "c-resume", "c-stop", "fo", "mdi", "mdi-go"]) {
    $(id).disabled = !owner;
  }
  document.querySelectorAll(".jog-btn").forEach((b) => { b.disabled = !owner; });
  renderSteps();
}

// --- стан ------------------------------------------------------------------------
function showStatus(s) {
  app.status = s;
  const state = $("state");
  state.textContent = STATE_TEXT[s.st] ?? s.st;
  state.className = `pill state-${s.st in STATE_TEXT ? s.st : "nocnc"}`;
  $("run").textContent = s.st === "nocnc" ? "" : `${s.mode || "—"} · ${RUN_TEXT[s.run] ?? s.run}${s.line ? " · рядок " + s.line : ""}`;
  $("power").textContent = isOn(s) ? "Power Off" : "Power On";
  $("prog-open").textContent = s.prog || "—";
  if (document.activeElement !== $("fo")) {
    $("fo").value = s.fo;
    $("fo-out").textContent = s.fo;
  }
  renderJogValues();
}

// --- безпека й живлення ---------------------------------------------------------
$("estop").addEventListener("click", () => act(async () => {
  await jog.stop();
  await client.estop(true);
}));
$("reset").addEventListener("click", () => act(() => client.estop(false)));
$("power").addEventListener("click", () => act(() => client.power(!isOn(app.status))));
$("home").addEventListener("click", () => act(() => client.homeAll()));

// --- jog ---------------------------------------------------------------------------
function buildJog() {
  const box = $("jog");
  box.innerHTML = "";
  for (let i = 0; i < 6; i++) {
    const row = document.createElement("div");
    row.className = "jog-row";
    row.innerHTML = `<div class="jog-name"></div><div class="jog-val">—</div>
      <button class="btn jog-btn" data-dir="-1" aria-label="мінус">−</button>
      <button class="btn jog-btn" data-dir="1" aria-label="плюс">+</button>`;
    row.dataset.index = i;
    box.appendChild(row);
    row.querySelectorAll(".jog-btn").forEach((btn) => bindJogButton(btn, i, Number(btn.dataset.dir)));
  }
  renderJogValues();
}

function jogTarget(index) {
  return app.space === "world" ? AXES[index] : index;
}

function bindJogButton(btn, index, dir) {
  let down = false;
  const release = () => {
    if (!down) return;
    down = false;
    btn.classList.remove("pressed");
    if (app.mode === "hold") act(() => jog.stop());
  };
  btn.addEventListener("pointerdown", (e) => {
    if (btn.disabled) return;
    e.preventDefault();
    btn.setPointerCapture(e.pointerId);
    down = true;
    btn.classList.add("pressed");
    const target = jogTarget(index);
    if (app.mode === "step") {
      act(() => client.jogStep(target, dir * STEP_VALUES[$("step").value]));
    } else {
      const linear = typeof target === "string" && "XYZ".includes(target);
      act(() => jog.start(target, dir, Number(linear ? $("lin").value : $("vel").value)));
    }
  });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) btn.addEventListener(ev, release);
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
}

function renderJogValues() {
  const s = app.status;
  document.querySelectorAll(".jog-row").forEach((row) => {
    const i = Number(row.dataset.index);
    const world = app.space === "world";
    const name = world ? AXES[i] : JOINT_NAMES[i];
    const homed = s.homed[i] ? "home ✔" : "";
    row.querySelector(".jog-name").innerHTML = `${name}<small>${world ? (i < 3 ? s.u : "°") : "°"} ${homed}</small>`;
    const v = world ? s.w[i] : s.j[i];
    row.querySelector(".jog-val").textContent = v === undefined ? "—" : Number(v).toFixed(world && i < 3 ? 3 : 2);
  });
}

function setSegment(onId, offId) {
  $(onId).classList.add("active");
  $(offId).classList.remove("active");
}

$("space-j").addEventListener("click", () => { app.space = "joint"; setSegment("space-j", "space-w"); updateJogOptions(); });
$("space-w").addEventListener("click", () => { app.space = "world"; setSegment("space-w", "space-j"); updateJogOptions(); });
$("mode-hold").addEventListener("click", () => { app.mode = "hold"; setSegment("mode-hold", "mode-step"); updateJogOptions(); });
$("mode-step").addEventListener("click", () => { app.mode = "step"; setSegment("mode-step", "mode-hold"); updateJogOptions(); });

function updateJogOptions() {
  $("lin-label").hidden = app.space !== "world" || app.mode !== "hold";
  $("step-label").hidden = app.mode !== "step";
  $("vel").closest("label").hidden = app.mode !== "hold";
  renderJogValues();
}

$("vel").addEventListener("input", () => { $("vel-out").textContent = $("vel").value; });
$("lin").addEventListener("input", () => { $("lin-out").textContent = $("lin").value; });
$("step").addEventListener("input", () => { $("step-out").textContent = STEP_VALUES[$("step").value]; });
$("step-out").textContent = STEP_VALUES[$("step").value];

// Згорнули додаток або вимкнули екран під час утримання — зупиняємо
document.addEventListener("visibilitychange", () => { if (document.hidden && jog.active) act(() => jog.stop()); });
window.addEventListener("blur", () => { if (jog.active) act(() => jog.stop()); });

// --- навчання ----------------------------------------------------------------------
function renderSteps() {
  const list = $("steps");
  list.innerHTML = "";
  app.program.steps.forEach((step, i) => {
    const li = document.createElement("li");
    li.className = i === app.selected ? "sel" : "";
    const title = `${i + 1}. ${KIND_TITLES[step.kind] ?? step.kind}${step.text && step.kind !== "comment" ? " — " + step.text : ""}`;
    li.innerHTML = `<div class="k"></div><div class="d"></div>`;
    li.querySelector(".k").textContent = title;
    li.querySelector(".d").textContent = stepSummary(step, app.program.units);
    li.addEventListener("click", () => { app.selected = i === app.selected ? -1 : i; renderSteps(); });
    list.appendChild(li);
  });
  const step = app.program.steps[app.selected];
  const motion = step && ["movej", "movel", "movep"].includes(step.kind);
  $("st-up").disabled = !step || app.selected === 0;
  $("st-down").disabled = !step || app.selected === app.program.steps.length - 1;
  $("st-del").disabled = !step;
  $("st-update").disabled = !motion;
  $("st-goto").disabled = !(motion && app.owner);
  $("prog-run").disabled = !app.owner || app.program.steps.length === 0;
  $("prog-name").value = app.program.name;
}

function insertStep(step) {
  const index = app.selected >= 0 ? app.selected + 1 : app.program.steps.length;
  app.program.steps.splice(index, 0, step);
  app.selected = index;
  renderSteps();
}

function record(kind) {
  const s = app.status;
  if (s.st === "nocnc" || !s.j.length) { toast("Немає даних про положення"); return; }
  if (kind !== "movej" && !allHomed(s)) { toast("Світова позиція — лише після Home All"); return; }
  if (!app.program.steps.length) app.program.units = s.u || "in";
  const points = app.program.steps.filter((x) => ["movej", "movel", "movep"].includes(x.kind)).length;
  const step = kind === "movej" ? makeStep("movej", { joints: s.j.slice(0, 6) })
                                : makeStep(kind, { pose: s.w.slice(0, 6) });
  step.text = `P${points + 1}`;
  insertStep(step);
  log(`Записано ${step.text}: ${stepSummary(step, app.program.units)}`);
}

$("rec-j").addEventListener("click", () => record("movej"));
$("rec-l").addEventListener("click", () => record("movel"));
$("rec-p").addEventListener("click", () => record("movep"));

$("add-wait").addEventListener("click", () => {
  const value = Number(prompt("Пауза, секунд:", "1"));
  if (Number.isFinite(value) && value >= 0) insertStep(makeStep("wait", { seconds: value }));
});
$("add-dout").addEventListener("click", () => {
  const n = Number(prompt("Номер виходу (0–63):", "0"));
  if (!Number.isInteger(n) || n < 0 || n > 63) return;
  const on = confirm(`Вихід ${n}: OK — увімкнути, Скасувати — вимкнути`);
  insertStep(makeStep("dout", { output: n, state: on }));
});
$("add-comment").addEventListener("click", () => {
  const text = prompt("Коментар:", "");
  if (text) insertStep(makeStep("comment", { text }));
});

function moveSelected(delta) {
  const i = app.selected;
  const j = i + delta;
  const steps = app.program.steps;
  if (i < 0 || j < 0 || j >= steps.length) return;
  [steps[i], steps[j]] = [steps[j], steps[i]];
  app.selected = j;
  renderSteps();
}
$("st-up").addEventListener("click", () => moveSelected(-1));
$("st-down").addEventListener("click", () => moveSelected(1));
$("st-del").addEventListener("click", () => {
  if (app.selected < 0) return;
  app.program.steps.splice(app.selected, 1);
  app.selected = Math.min(app.selected, app.program.steps.length - 1);
  renderSteps();
});
$("st-update").addEventListener("click", () => {
  const step = app.program.steps[app.selected];
  const s = app.status;
  if (!step) return;
  if (step.kind === "movej" && s.j.length) step.joints = s.j.slice(0, 6);
  else if (step.kind !== "movej" && allHomed(s)) step.pose = s.w.slice(0, 6);
  else { toast("Немає поточної позиції (для X…C потрібен Home)"); return; }
  renderSteps();
  log(`Оновлено крок ${app.selected + 1}`);
});

$("prog-name").addEventListener("change", () => {
  app.program.name = $("prog-name").value.trim() || "program";
});

function checkReady() {
  const s = app.status;
  if (!(isOn(s) && allHomed(s))) { toast("Потрібні Power On і Home All"); return false; }
  if (s.run !== "idle") { toast("Дочекайтесь завершення програми"); return false; }
  return true;
}

async function uploadAndRun(name, gcode) {
  const bar = $("upload");
  bar.hidden = false;
  try {
    await client.uploadProgram(name, gcode, (i, n) => { bar.max = n; bar.value = i; });
  } finally {
    bar.hidden = true;
  }
  await client.openProgram(name);
  await client.run();
}

$("st-goto").addEventListener("click", () => act(async () => {
  const step = app.program.steps[app.selected];
  if (!step || !checkReady()) return;
  await uploadAndRun(GOTO_FILE, toGcode(app.program, [step]));
  log(`➜ Рух до кроку ${app.selected + 1}`);
}));

$("prog-run").addEventListener("click", () => act(async () => {
  if (!checkReady()) return;
  const name = fileName(app.program);
  await uploadAndRun(name, toGcode(app.program));
  log(`▶ Запущено ${name}`);
}));

// Збереження в браузері + обмін файлами зі Studio (*.robot.json)
function refreshSaved() {
  const select = $("saved");
  const names = store.keys().filter((k) => k.startsWith(STORE_PREFIX)).map((k) => k.slice(STORE_PREFIX.length)).sort();
  select.innerHTML = `<option value="">Збережені…</option>`;
  for (const name of names) select.add(new Option(name, name));   // без innerHTML з даними
}

$("saved").addEventListener("change", () => {
  const name = $("saved").value;
  if (!name) return;
  try {
    app.program = programFromJson(store.get(STORE_PREFIX + name));
    app.selected = -1;
    renderSteps();
    log(`Відкрито ${name}`);
  } catch (err) {
    toast(err.message);
  }
  $("saved").value = "";
});

$("prog-new").addEventListener("click", () => {
  if (app.program.steps.length && !confirm("Почати нову програму? Незбережені зміни зникнуть.")) return;
  app.program = makeProgram({ units: app.status.u || "in" });
  app.selected = -1;
  renderSteps();
});

$("prog-save").addEventListener("click", () => {
  app.program.name = $("prog-name").value.trim() || "program";
  if (store.set(STORE_PREFIX + app.program.name, programToJson(app.program))) {
    refreshSaved();
    toast(`Збережено «${app.program.name}» на телефоні`);
  } else {
    toast("Сховище браузера недоступне — використайте «Експорт»");
  }
});

$("prog-export").addEventListener("click", () => {
  const blob = new Blob([programToJson(app.program)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${app.program.name}.robot.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

$("prog-import").addEventListener("change", async () => {
  const file = $("prog-import").files[0];
  if (!file) return;
  try {
    app.program = programFromJson(await file.text());
    app.selected = -1;
    renderSteps();
    log(`Імпортовано ${file.name}`);
  } catch (err) {
    toast(err instanceof ProgramError ? err.message : "Не вдалося прочитати файл");
  }
  $("prog-import").value = "";
});

// --- програми на роботі ------------------------------------------------------------
function renderFiles(names) {
  const list = $("files");
  list.innerHTML = "";
  for (const name of names) {
    const li = document.createElement("li");
    li.textContent = name;
    li.className = name === app.fileSelected ? "sel" : "";
    li.addEventListener("click", () => { app.fileSelected = name; renderFiles(names); });
    list.appendChild(li);
  }
}

$("ls").addEventListener("click", () => act(async () => renderFiles(await client.listPrograms())));
$("open").addEventListener("click", () => act(async () => {
  if (!app.fileSelected) { toast("Виберіть файл"); return; }
  await client.openProgram(app.fileSelected);
}));
$("rm").addEventListener("click", () => act(async () => {
  if (!app.fileSelected || !confirm(`Видалити ${app.fileSelected} з робота?`)) return;
  await client.deleteProgram(app.fileSelected);
  app.fileSelected = null;
  renderFiles(await client.listPrograms());
}));
$("c-run").addEventListener("click", () => act(() => client.run()));
$("c-pause").addEventListener("click", () => act(() => client.pause()));
$("c-resume").addEventListener("click", () => act(() => client.resume()));
$("c-stop").addEventListener("click", () => act(() => client.stop()));
$("fo").addEventListener("input", () => { $("fo-out").textContent = $("fo").value; });
$("fo").addEventListener("change", () => act(() => client.feedOverride(Number($("fo").value))));
$("mdi-go").addEventListener("click", () => act(async () => {
  const code = $("mdi").value.trim();
  if (code) await client.mdi(code);
}));

// --- старт ---------------------------------------------------------------------------
buildJog();
updateJogOptions();
refreshSaved();
setConnected(false);
renderSteps();
// Спершу — підключення (адреса підставляється сама, якщо сторінку роздає Pi)
document.querySelector('.tabs button[data-tab="link"]').click();
