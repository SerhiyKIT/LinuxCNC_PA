// clients/android/js/program.js
// Програма навчання і генерація G-коду.
// Порт clients/windows/bt_cnc_client/robot_program.py — вихід має бути
// ідентичним (перевіряє tests/parity.test.mjs), формат JSON сумісний зі Studio.

export const FORMAT_ID = "cnc-robot-program";
export const FORMAT_VERSION = 1;
export const AXES = "XYZABC";
export const JOINTS = 6;

export const KIND_TITLES = {
  movej: "Рух по joints",
  movel: "Лінійний рух",
  movep: "Швидкий рух",
  wait: "Пауза",
  dout: "Вихід",
  comment: "Коментар",
};

export const DEFAULT_JOINT_SPEED = 10.0;   // град/с
export const DEFAULT_LINEAR_SPEED = 0.2;   // од./с
const MAX_DOUT = 63;
const WORLD = "world";
const JOINT = "joint";

export class ProgramError extends Error {}

export function makeStep(kind, fields = {}) {
  return {
    kind, joints: [], pose: [], speed: 0, seconds: 0, output: 0, state: true, text: "",
    ...fields,
  };
}

export function makeProgram(fields = {}) {
  return {
    name: "program", units: "in",
    joint_speed: DEFAULT_JOINT_SPEED, linear_speed: DEFAULT_LINEAR_SPEED,
    steps: [], ...fields,
  };
}

export function programToJson(program) {
  return JSON.stringify({ format: FORMAT_ID, version: FORMAT_VERSION, ...program }, null, 2);
}

export function programFromJson(text) {
  const data = JSON.parse(text);
  if (data.format !== FORMAT_ID) throw new ProgramError("це не файл програми CNC-Robot");
  if ((data.version ?? 0) > FORMAT_VERSION) throw new ProgramError("файл створено новішою версією");
  const keys = Object.keys(makeStep(""));
  const steps = (data.steps || []).map((s) =>
    makeStep(s.kind, Object.fromEntries(Object.entries(s).filter(([k]) => keys.includes(k)))));
  return makeProgram({
    name: data.name ?? "program", units: data.units ?? "in",
    joint_speed: Number(data.joint_speed ?? DEFAULT_JOINT_SPEED),
    linear_speed: Number(data.linear_speed ?? DEFAULT_LINEAR_SPEED), steps,
  });
}

/** Ім'я .ngc для PROJECTS_DIR: лише безпечні символи (як у Python). */
export function fileName(program) {
  let base = program.name.trim().replace(/[^\p{L}\p{N}\p{M}_\-]+/gu, "_");
  base = base.replace(/^[_.]+|[_.]+$/g, "");
  return Array.from(base || "program").slice(0, 60).join("") + ".ngc";
}

export function stepSummary(step, units = "in") {
  const f = (v, d) => Number(v).toFixed(d);
  if (step.kind === "movej") return step.joints.map((v, i) => `J${i} ${f(v, 2)}°`).join("  ");
  if (step.kind === "movel" || step.kind === "movep") {
    const lin = [0, 1, 2].map((i) => `${AXES[i]} ${f(step.pose[i], 3)}`).join("  ");
    const ang = [3, 4, 5].map((i) => `${AXES[i]} ${f(step.pose[i], 1)}°`).join("  ");
    return `${lin} ${units}   ${ang}`;
  }
  if (step.kind === "wait") return `${step.seconds} с`;
  if (step.kind === "dout") return `вихід ${step.output} = ${step.state ? "1" : "0"}`;
  return step.text;
}

// --- G-код --------------------------------------------------------------------

function num(v) {
  let text = Number(v).toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return text === "-0" || text === "" ? "0" : text;
}

const coords = (values) => values.map((v, i) => `${AXES[i]}${num(v)}`).join(" ");

function comment(text) {
  const clean = text.replace(/[()\r\n;]/g, " ").trim();
  return clean ? `(${clean})` : "";
}

function checkValues(values, what, index) {
  if (!Array.isArray(values) || values.length !== JOINTS)
    throw new ProgramError(`крок ${index}: потрібно 6 значень ${what}`);
  for (const v of values)
    if (typeof v !== "number" || !Number.isFinite(v))
      throw new ProgramError(`крок ${index}: некоректне значення ${what}`);
}

function switchKins(lines, current, wanted) {
  if (current === wanted) return current;
  if (wanted === JOINT)
    lines.push("M129 (ліміти осей = ліміти joints)", "M429 (кінематика identity: X..C = J0..J5)");
  else
    lines.push("M128 (ліміти осей з INI)", "M428 (кінематика genserkins)");
  return wanted;
}

function stepGcode(step, program, index, lines, mode) {
  switch (step.kind) {
    case "movej": {
      checkValues(step.joints, "joints", index);
      mode = switchKins(lines, mode, JOINT);
      const speed = step.speed || program.joint_speed;
      lines.push(`G53 G1 ${coords(step.joints)} F${num(speed * 60)}`);
      break;
    }
    case "movel":
    case "movep": {
      checkValues(step.pose, "координат", index);
      mode = switchKins(lines, mode, WORLD);
      if (step.kind === "movep") lines.push(`G53 G0 ${coords(step.pose)}`);
      else lines.push(`G53 G1 ${coords(step.pose)} F${num((step.speed || program.linear_speed) * 60)}`);
      break;
    }
    case "wait":
      if (step.seconds < 0) throw new ProgramError(`крок ${index}: пауза не може бути від'ємною`);
      lines.push(`G4 P${num(step.seconds)}`);
      break;
    case "dout":
      if (!(step.output >= 0 && step.output <= MAX_DOUT))
        throw new ProgramError(`крок ${index}: вихід має бути 0..${MAX_DOUT}`);
      lines.push(`${step.state ? "M64" : "M65"} P${step.output}`);
      break;
    case "comment": {
      const text = comment(step.text);
      if (text) lines.push(text);
      break;
    }
    default:
      throw new ProgramError(`крок ${index}: невідомий тип '${step.kind}'`);
  }
  return mode;
}

/** G-код програми (або лише вказаних кроків — для «Перейти до точки»). */
export function toGcode(program, steps = null) {
  steps = steps ?? program.steps;
  if (!steps.some((s) => ["movej", "movel", "movep", "wait", "dout"].includes(s.kind)))
    throw new ProgramError("у програмі немає жодного кроку з дією");
  const lines = [
    comment(`CNC-Robot Studio: ${program.name}`),
    "(Згенеровано автоматично; редагуйте програму в Studio)",
    (program.units === "mm" ? "G21" : "G20") + " G90 G94",
    "M428 (кінематика genserkins)",
  ];
  let mode = WORLD;
  steps.forEach((step, i) => {
    const index = i + 1;
    if (step.text && step.kind !== "comment") {
      const label = comment(`${index}: ${step.text}`);
      if (label) lines.push(label);
    }
    mode = stepGcode(step, program, index, lines, mode);
  });
  switchKins(lines, mode, WORLD);
  lines.push("M2");
  return lines.filter((l) => l).join("\n") + "\n";
}
