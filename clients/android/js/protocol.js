// clients/android/js/protocol.js
// Клієнт протоколу v1 bt-cnc-bridge (див. system/bt-cnc-bridge/README.md).
// Порт clients/windows/bt_cnc_client/protocol_client.py без UI:
// транспорт — функція write(bytes), вхідні байти подаються в feed().

export const PROTOCOL_VERSION = 1;
export const COMMAND_TIMEOUT = 5000;   // мс
export const PING_INTERVAL = 200;      // мс, heartbeat під час утримання jog
const RX_LINE_MAX = 4096;

export class CommandError extends Error {
  constructor(code, text) {
    super(`${code}: ${text}`);
    this.code = code;
    this.text = text;
  }
}

export function emptyStatus() {
  return { st: "nocnc", mode: "", homed: [], j: [], prog: "", line: 0, run: "idle",
           fo: 100, ro: 100, ctl: 0, w: [], u: "in" };
}

export const isOn = (s) => s.st === "on";
export const allHomed = (s) => s.homed.length > 0 && s.homed.every(Boolean);

export function parseLine(line) {
  const sp = line.indexOf(" ");
  const head = sp < 0 ? line : line.slice(0, sp);
  const rest = sp < 0 ? "" : line.slice(sp + 1);
  const split = (s) => { const i = s.indexOf(" "); return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)]; };
  if (head === "OK") {
    const [cmd, data] = split(rest);
    return { kind: "reply", reply: { ok: true, cmd, data, code: "" } };
  }
  if (head === "ERR") {
    const [code, text] = split(rest);
    return { kind: "reply", reply: { ok: false, cmd: "", data: text, code } };
  }
  if (head === "EVT") {
    const [kind, payload] = split(rest);
    if (kind === "S") {
      try {
        return { kind: "status", status: { ...emptyStatus(), ...JSON.parse(payload) } };
      } catch {
        return { kind: "unknown", text: line };
      }
    }
    if (kind === "E") return { kind: "error", text: payload };
  }
  return { kind: "unknown", text: line };
}

/** Збирає байти (Uint8Array) у рядки до '\n', не розриваючи UTF-8. */
export class LineAssembler {
  constructor() {
    this.decoder = new TextDecoder();
    this.buf = "";
  }

  feed(bytes) {
    this.buf += this.decoder.decode(bytes, { stream: true });
    const parts = this.buf.split("\n");
    this.buf = parts.pop();
    if (this.buf.length > RX_LINE_MAX) this.buf = "";
    return parts.map((l) => l.replace(/\r$/, "")).filter((l) => l);
  }
}

/**
 * Відправка команд і зіставлення відповідей (FIFO: міст відповідає по
 * одному OK/ERR на команду в порядку надходження).
 */
export class CncClient {
  constructor(write, { onStatus = () => {}, onEventError = () => {}, onLine = () => {} } = {}) {
    this.write = write;
    this.onStatus = onStatus;
    this.onEventError = onEventError;
    this.onLine = onLine;
    this.assembler = new LineAssembler();
    this.pending = [];
    this.status = emptyStatus();
    this.encoder = new TextEncoder();
  }

  feed(bytes) {
    for (const line of this.assembler.feed(bytes)) this.handle(line);
  }

  handle(line) {
    const msg = parseLine(line);
    if (msg.kind === "status") {
      this.status = msg.status;
      this.onStatus(msg.status);
      return;
    }
    if (!(msg.kind === "reply" && msg.reply.cmd === "ping")) this.onLine("<", line);
    if (msg.kind === "error") this.onEventError(msg.text);
    else if (msg.kind === "reply") {
      const entry = this.pending.shift();
      if (entry) entry.resolve(msg.reply);
    }
  }

  connectionLost() {
    for (const entry of this.pending.splice(0)) entry.reject(new CommandError("link", "з'єднання розірвано"));
    this.assembler = new LineAssembler();
  }

  command(line, timeout = COMMAND_TIMEOUT) {
    const name = line.split(" ", 1)[0].toLowerCase();
    return new Promise((resolve, reject) => {
      const entry = { name };
      const timer = setTimeout(() => {
        this.pending = this.pending.filter((e) => e !== entry);   // не зсуваємо чергу
        reject(new CommandError("timeout", `немає відповіді на '${name}'`));
      }, timeout);
      entry.resolve = (reply) => {
        clearTimeout(timer);
        reply.ok ? resolve(reply.data) : reject(new CommandError(reply.code, reply.data));
      };
      entry.reject = (err) => { clearTimeout(timer); reject(err); };
      this.pending.push(entry);
      if (name !== "ping") this.onLine(">", name === "pin" ? "pin ****" : line);
      try {
        this.write(this.encoder.encode(line + "\n"));
      } catch (err) {
        this.pending = this.pending.filter((e) => e !== entry);
        clearTimeout(timer);
        reject(new CommandError("link", String(err.message || err)));
      }
    });
  }

  // Тонкі обгортки, щоб UI не складав рядки протоколу сам
  version() { return this.command("ver").then(Number); }
  login(pin) { return this.command(`pin ${pin}`); }
  take() { return this.command("take"); }
  release() { return this.command("release"); }
  requestStatus() { return this.command("status"); }
  estop(on) { return this.command(on ? "estop on" : "estop off"); }
  power(on) { return this.command(on ? "power on" : "power off"); }
  homeAll() { return this.command("home all"); }
  ping() { return this.command("ping", 1000); }
  jogStep(target, step) {
    const s = `${step > 0 ? "+" : ""}${step}`;
    return typeof target === "string" ? this.command(`jogw ${target} ${s}`) : this.command(`jog J${target} ${s}`);
  }
  jogContinuous(target, dir, vel) {
    const d = dir > 0 ? "+" : "-";
    return typeof target === "string" ? this.command(`jogwc ${target} ${d} ${vel}`)
                                      : this.command(`jogc J${target} ${d} ${vel}`);
  }
  jogStop(target = null) {
    if (target === null) return this.command("jogstop");
    return this.command(`jogstop ${typeof target === "string" ? target : "J" + target}`);
  }
  mdi(code) { return this.command(`mdi ${code}`); }
  async listPrograms() { return JSON.parse((await this.command("ls")) || "[]"); }
  openProgram(name) { return this.command(`open ${name}`); }
  run(line = 0) { return this.command(line ? `run ${line}` : "run"); }
  pause() { return this.command("pause"); }
  resume() { return this.command("resume"); }
  stop() { return this.command("stop"); }
  feedOverride(pct) { return this.command(`fo ${Math.round(pct)}`); }
  deleteProgram(name) { return this.command(`rm ${name}`); }

  /** Передає файл рядками (file begin/data/end); при помилці — file abort. */
  async uploadProgram(name, text, progress = () => {}) {
    const lines = text.replace(/\n+$/, "").split("\n");
    await this.command(`file begin ${name}`);
    try {
      for (let i = 0; i < lines.length; i++) {
        await this.command(`file data ${lines[i]}`);
        progress(i + 1, lines.length);
      }
      return await this.command("file end");
    } catch (err) {
      try { await this.command("file abort"); } catch {}
      throw err;
    }
  }
}

/**
 * Безперервний jog, поки палець на кнопці: jogc/jogwc + ping кожні 200 мс,
 * відпускання — jogstop. Покоління захищає від відпускання до відповіді на jogc.
 */
export class JogHold {
  constructor(client, onError = () => {}, interval = PING_INTERVAL) {
    this.client = client;
    this.onError = onError;
    this.interval = interval;
    this.target = null;
    this.timer = null;
    this.generation = 0;
  }

  get active() { return this.target !== null; }

  async start(target, dir, vel) {
    await this.stop();
    const generation = this.generation;
    this.target = target;
    try {
      await this.client.jogContinuous(target, dir, vel);
    } catch (err) {
      if (this.generation === generation) this.target = null;
      throw err;
    }
    if (this.generation !== generation) return;   // уже відпустили — stop відправив jogstop
    this.timer = setInterval(async () => {
      try {
        await this.client.ping();
      } catch (err) {
        this.onError(`jog зупинено: ${err.text || err.message}`);
        await this.stop();
      }
    }, this.interval);
  }

  /** Обрив зв'язку: забути jog без команд (міст зупинить сам). */
  reset() {
    this.generation++;
    this.target = null;
    clearInterval(this.timer);
    this.timer = null;
  }

  async stop() {
    this.generation++;
    clearInterval(this.timer);
    this.timer = null;
    const target = this.target;
    this.target = null;
    if (target !== null) {
      try {
        await this.client.jogStop(target);
      } catch (err) {
        this.onError(`jogstop: ${err.text || err.message}`);   // міст однаково зупинить watchdog'ом
      }
    }
  }
}
