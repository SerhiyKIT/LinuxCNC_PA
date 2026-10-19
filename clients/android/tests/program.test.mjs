// clients/android/tests/program.test.mjs
// Генератор G-коду на JS має давати той самий результат, що й Python-версія
// Studio (clients/windows/bt_cnc_client/robot_program.py).
// Запуск: node --test clients/android/tests/   (потрібен python3 у PATH або $PYTHON)
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  ProgramError, fileName, makeProgram, makeStep, programFromJson, programToJson, stepSummary, toGcode,
} from "../js/program.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const studioDir = path.resolve(here, "../../windows/bt_cnc_client");
const python = process.env.PYTHON || "python3";

/** G-код і ім'я файлу від Python-генератора для тієї ж програми (через JSON). */
function pythonReference(program) {
  const code = `
import json, sys
sys.path.insert(0, sys.argv[1])
from robot_program import Program, to_gcode
p = Program.from_json(sys.stdin.read())
print(json.dumps({"gcode": to_gcode(p), "file": p.file_name()}))`;
  const out = execFileSync(python, ["-I", "-c", code, studioDir], { input: programToJson(program) });
  return JSON.parse(out.toString());
}

const J1 = [0, 10, -20, 0, 45, 90];
const P1 = [17, 5.5, 7.2, 180, -0.0, 0.123456];

const fixtures = [
  makeProgram({ name: "demo", steps: [
    makeStep("movej", { joints: J1, speed: 20, text: "P1" }),
    makeStep("movej", { joints: [5.5, 0, 0, 0, 0, 0] }),
    makeStep("wait", { seconds: 1.5 }),
    makeStep("movel", { pose: P1, text: "Підхід (повільно)" }),
    makeStep("dout", { output: 2, state: true, text: "Захват" }),
    makeStep("movep", { pose: P1 }),
    makeStep("dout", { output: 2, state: false }),
    makeStep("comment", { text: "кінець; (тест)" }),
    makeStep("movej", { joints: J1 }),
  ] }),
  makeProgram({ name: "Деталь 1/../x (mm)", units: "mm", joint_speed: 15, linear_speed: 2.5, steps: [
    makeStep("movel", { pose: [100.12345, -50, 0.0001, 90, 0, -45.5] }),
    makeStep("wait", { seconds: 0 }),
  ] }),
  makeProgram({ name: "..", steps: [makeStep("dout", { output: 63 })] }),
];

for (const [i, program] of fixtures.entries()) {
  test(`паритет з Python: програма ${i + 1}`, () => {
    const ref = pythonReference(program);
    assert.equal(toGcode(program), ref.gcode);
    assert.equal(fileName(program), ref.file);
  });
}

test("JSON сумісний зі Studio в обидва боки", () => {
  const program = fixtures[0];
  // Порівнюємо через JSON: -0 після серіалізації стає 0, як і в Python
  const again = programFromJson(programToJson(program));
  assert.equal(programToJson(again), programToJson(program));
  assert.throws(() => programFromJson('{"format":"other"}'), ProgramError);
  assert.throws(() => programFromJson('{"format":"cnc-robot-program","version":9}'), ProgramError);
});

test("помилкові кроки", () => {
  const bad = [
    [makeStep("movej", { joints: [1, 2] }), /6 значень/],
    [makeStep("movel", { pose: [0, 0, 0, 0, 0, NaN] }), /некоректне/],
    [makeStep("wait", { seconds: -1 }), /від'ємною/],
    [makeStep("dout", { output: 64 }), /0\.\.63/],
    [makeStep("teleport"), /невідомий/],
  ];
  for (const [step, re] of bad)
    assert.throws(() => toGcode(makeProgram({ steps: [makeStep("wait"), step] })), re);
  assert.throws(() => toGcode(makeProgram({ steps: [makeStep("comment", { text: "x" })] })), ProgramError);
});

test("опис кроку", () => {
  assert.match(stepSummary(makeStep("movej", { joints: [5.5, 0, 0, 0, 0, 0] })), /^J0 5\.50°/);
  assert.equal(stepSummary(makeStep("dout", { output: 3, state: false })), "вихід 3 = 0");
});
