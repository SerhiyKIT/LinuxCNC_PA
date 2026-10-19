# clients/windows/bt_cnc_client/teach_panel.py
"""
Вкладка «Навчання»: програма робота без написання коду.

Оператор ставить робота jog'ом у потрібне положення і натискає
«Записати» — поточні кути joints (MoveJ) або світова позиція (MoveL/MoveP)
стають кроком програми. Кроки можна впорядковувати, правити, додавати
паузи, виходи і коментарі; далі — G-код, завантаження на робот і запуск.
Логіка програми і G-код — у robot_program.py (без Qt).
"""
from __future__ import annotations

import copy
import logging
from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets

import ui_constants as ui
from protocol_client import CncClient, Status
from robot_program import KIND_TITLES, Program, ProgramError, Step, to_gcode

logger = logging.getLogger(__name__)

COLUMNS = ["#", "Тип", "Назва", "Ціль / параметри", "Швидкість"]


class TeachPanel(QtWidgets.QWidget):
    def __init__(self, client: CncClient, run: Callable, log: Callable[[str], None]) -> None:
        super().__init__()
        self.client = client
        self.run = run
        self.log = log
        self.status = Status()
        self.program = Program()
        self.path: str | None = None
        self.dirty = False
        self.owner = False
        self._editing = False          # блокує зворотні сигнали при заповненні редактора

        self._build()
        self.refresh_table()
        self.set_owner(False)

    # -----------------------------------------------------------------------
    # Побудова
    # -----------------------------------------------------------------------

    def _build(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        # --- файл і типові швидкості
        top = QtWidgets.QHBoxLayout()
        self.name_edit = QtWidgets.QLineEdit(self.program.name)
        self.name_edit.setMaximumWidth(220)
        self.name_edit.textEdited.connect(self._on_name)
        top.addWidget(QtWidgets.QLabel("Програма:"))
        top.addWidget(self.name_edit)
        for text, slot in (("Нова", self.new_program), ("Відкрити…", self.open_program),
                           ("Зберегти", self.save_program), ("Зберегти як…", self.save_program_as)):
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(slot)
            top.addWidget(btn)
        top.addSpacing(20)
        self.joint_speed = self._spin(ui.SPEED_JOINT_RANGE, self.program.joint_speed, " °/с", 1)
        self.joint_speed.setMinimum(0.5)
        self.linear_speed = self._spin(ui.SPEED_LINEAR_RANGE, self.program.linear_speed, " од./с", 3)
        self.linear_speed.setMinimum(0.001)
        self.joint_speed.valueChanged.connect(self._on_default_speeds)
        self.linear_speed.valueChanged.connect(self._on_default_speeds)
        top.addWidget(QtWidgets.QLabel("Типова швидкість joints:"))
        top.addWidget(self.joint_speed)
        top.addWidget(QtWidgets.QLabel("лінійна:"))
        top.addWidget(self.linear_speed)
        top.addStretch(1)
        root.addLayout(top)

        # --- запис кроків
        rec = QtWidgets.QHBoxLayout()
        self.record_buttons = []
        for text, kind, tip in (
                ("● Записати MoveJ", "movej", "Поточні кути J0–J5 → рух по joints"),
                ("● Записати MoveL", "movel", "Поточна позиція X…C → лінійний рух (потрібен Home)"),
                ("● Записати MoveP", "movep", "Поточна позиція X…C → швидкий рух G0 (потрібен Home)")):
            btn = QtWidgets.QPushButton(text)
            btn.setStyleSheet(ui.RECORD_STYLE)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, k=kind: self.record(k))
            rec.addWidget(btn)
            self.record_buttons.append(btn)
        rec.addSpacing(20)
        for text, kind in (("+ Пауза", "wait"), ("+ Вихід", "dout"), ("+ Коментар", "comment")):
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(lambda _=False, k=kind: self.add_step(Step(k, seconds=1.0 if k == "wait" else 0.0,
                                                                         text="" if k != "comment" else "Коментар")))
            rec.addWidget(btn)
        rec.addStretch(1)
        root.addLayout(rec)

        # --- таблиця + редактор кроку
        body = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        for col in (0, 1, 2, 4):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        left.addWidget(self.table, 1)

        ops = QtWidgets.QHBoxLayout()
        self.row_buttons = []
        for text, slot, tip in (("▲", lambda: self.move_step(-1), "Вище"),
                                ("▼", lambda: self.move_step(1), "Нижче"),
                                ("Дублювати", self.duplicate_step, ""),
                                ("Видалити", self.delete_step, ""),
                                ("Оновити позицію", self.update_position,
                                 "Записати в крок поточне положення робота")):
            btn = QtWidgets.QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            ops.addWidget(btn)
            self.row_buttons.append(btn)
        self.goto_btn = QtWidgets.QPushButton("➜ Перейти до точки")
        self.goto_btn.setToolTip("Робот поїде до вибраної точки (окрема коротка програма)")
        self.goto_btn.clicked.connect(lambda: self.run(self.goto_step()))
        ops.addStretch(1)
        ops.addWidget(self.goto_btn)
        left.addLayout(ops)
        body.addLayout(left, 3)

        body.addWidget(self._build_editor(), 2)
        root.addLayout(body, 1)

        # --- G-код і виконання
        bottom = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton("Переглянути G-код")
        self.upload_btn = QtWidgets.QPushButton("Завантажити на робот")
        self.run_btn = QtWidgets.QPushButton("▶ Запустити програму")
        self.run_btn.setStyleSheet(ui.RECORD_STYLE)
        self.preview_btn.clicked.connect(self.preview_gcode)
        self.upload_btn.clicked.connect(lambda: self.run(self.upload()))
        self.run_btn.clicked.connect(lambda: self.run(self.run_program()))
        self.progress = QtWidgets.QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        for w in (self.preview_btn, self.upload_btn, self.run_btn, self.progress):
            bottom.addWidget(w)
        bottom.addStretch(1)
        root.addLayout(bottom)

    def _spin(self, rng, value, suffix="", decimals=3) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(*rng)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        return spin

    def _build_editor(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Крок")
        form = QtWidgets.QFormLayout(box)
        self.ed_kind = QtWidgets.QLabel("—")
        self.ed_name = QtWidgets.QLineEdit()
        self.ed_name.setPlaceholderText("напр. Підхід, Захват")
        self.ed_name.textEdited.connect(self._on_edit)
        form.addRow("Тип:", self.ed_kind)
        form.addRow("Назва:", self.ed_name)

        self.ed_values, self.ed_value_labels = [], []
        for i in range(6):
            spin = self._spin(ui.VALUE_RANGE, 0.0, decimals=4)
            spin.valueChanged.connect(self._on_edit)
            label = QtWidgets.QLabel(ui.JOINT_NAMES[i])
            form.addRow(label, spin)
            self.ed_values.append(spin)
            self.ed_value_labels.append(label)

        self.ed_speed = self._spin(ui.SPEED_JOINT_RANGE, 0.0, decimals=3)
        self.ed_speed.setSpecialValueText("типова")
        self.ed_speed.valueChanged.connect(self._on_edit)
        self.ed_seconds = self._spin(ui.WAIT_RANGE, 1.0, " с", 2)
        self.ed_seconds.valueChanged.connect(self._on_edit)
        self.ed_output = QtWidgets.QSpinBox()
        self.ed_output.setRange(0, 63)
        self.ed_output.valueChanged.connect(self._on_edit)
        self.ed_state = QtWidgets.QCheckBox("увімкнути")
        self.ed_state.toggled.connect(self._on_edit)
        self.ed_text = QtWidgets.QLineEdit()
        self.ed_text.textEdited.connect(self._on_edit)

        self.row_speed = ("Швидкість:", self.ed_speed)
        form.addRow(*self.row_speed)
        form.addRow("Тривалість:", self.ed_seconds)
        form.addRow("Вихід №:", self.ed_output)
        form.addRow("Стан:", self.ed_state)
        form.addRow("Текст:", self.ed_text)
        self.form = form
        self.editor_box = box
        self._show_editor(None)
        return box

    # -----------------------------------------------------------------------
    # Зовнішні події
    # -----------------------------------------------------------------------

    def set_status(self, status: Status) -> None:
        self.status = status

    def set_owner(self, owner: bool) -> None:
        """Рух робота (перейти, запустити, завантажити) — лише з керуванням."""
        self.owner = owner
        for w in (self.upload_btn, self.run_btn):
            w.setEnabled(owner)
        self._on_select()                 # «Перейти» залежить і від вибраного кроку

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QtWidgets.QMessageBox.question(
            self, "Незбережена програма", "Програму змінено. Відкинути зміни?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        return answer == QtWidgets.QMessageBox.Yes

    # -----------------------------------------------------------------------
    # Таблиця
    # -----------------------------------------------------------------------

    def selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _speed_text(self, step: Step) -> str:
        if step.kind == "movej":
            return f"{step.speed:g} °/с" if step.speed else f"типова ({self.program.joint_speed:g})"
        if step.kind == "movel":
            return f"{step.speed:g} од./с" if step.speed else f"типова ({self.program.linear_speed:g})"
        if step.kind == "movep":
            return "макс. (G0)"
        return ""

    def _fill_row(self, row: int) -> None:
        step = self.program.steps[row]
        values = [str(row + 1), KIND_TITLES.get(step.kind, step.kind),
                  step.text if step.kind != "comment" else "",
                  step.summary(self.program.units), self._speed_text(step)]
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QtWidgets.QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(value)
            if step.kind == "comment":
                item.setForeground(QtGui.QColor("#757575"))

    def refresh_table(self, select: int | None = None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.program.steps))
        for row in range(len(self.program.steps)):
            self._fill_row(row)
        self.table.blockSignals(False)
        if select is not None and 0 <= select < len(self.program.steps):
            self.table.selectRow(select)
        self._on_select()

    def _mark_dirty(self) -> None:
        self.dirty = True
        title = self.program.name + " *"
        self.editor_box.setTitle(f"Крок — {title}")

    # -----------------------------------------------------------------------
    # Запис і редагування кроків
    # -----------------------------------------------------------------------

    def record(self, kind: str) -> None:
        s = self.status
        if s.st == "nocnc" or not s.j:
            self.log("✖ немає даних про положення — LinuxCNC не підключений")
            return
        if kind == "movej":
            step = Step("movej", joints=list(s.j[:6]))
        else:
            if not s.all_homed:
                self.log("✖ світова позиція визначена лише після Home All")
                return
            step = Step(kind, pose=list(s.w[:6]))
        if not self.program.steps:
            self.program.units = s.u or "in"
        step.text = f"P{sum(1 for x in self.program.steps if x.kind in ('movej', 'movel', 'movep')) + 1}"
        self.add_step(step)
        self.log(f"Записано {step.text}: {step.summary(self.program.units)}")

    def add_step(self, step: Step) -> None:
        row = self.selected_row()
        index = row + 1 if row >= 0 else len(self.program.steps)
        self.program.steps.insert(index, step)
        self._mark_dirty()
        self.refresh_table(select=index)

    def move_step(self, delta: int) -> None:
        row = self.selected_row()
        new = row + delta
        if row < 0 or not 0 <= new < len(self.program.steps):
            return
        steps = self.program.steps
        steps[row], steps[new] = steps[new], steps[row]
        self._mark_dirty()
        self.refresh_table(select=new)

    def duplicate_step(self) -> None:
        row = self.selected_row()
        if row >= 0:
            self.program.steps.insert(row + 1, copy.deepcopy(self.program.steps[row]))
            self._mark_dirty()
            self.refresh_table(select=row + 1)

    def delete_step(self) -> None:
        row = self.selected_row()
        if row >= 0:
            del self.program.steps[row]
            self._mark_dirty()
            self.refresh_table(select=min(row, len(self.program.steps) - 1))

    def update_position(self) -> None:
        row = self.selected_row()
        if row < 0:
            return
        step = self.program.steps[row]
        s = self.status
        if step.kind == "movej" and s.j:
            step.joints = list(s.j[:6])
        elif step.kind in ("movel", "movep") and s.w and s.all_homed:
            step.pose = list(s.w[:6])
        else:
            self.log("✖ для цього кроку немає поточної позиції (потрібен Home для X…C)")
            return
        self._mark_dirty()
        self.refresh_table(select=row)
        self.log(f"Оновлено крок {row + 1}")

    def _show_editor(self, step: Step | None) -> None:
        kind = step.kind if step else None
        has_values = kind in ("movej", "movel", "movep")
        visible = {
            self.ed_name: step is not None and kind != "comment",
            self.ed_speed: kind in ("movej", "movel"),
            self.ed_seconds: kind == "wait",
            self.ed_output: kind == "dout",
            self.ed_state: kind == "dout",
            self.ed_text: kind == "comment",
        }
        for spin, label in zip(self.ed_values, self.ed_value_labels):
            visible[spin] = has_values
            label.setVisible(has_values)
        for widget, show in visible.items():
            widget.setVisible(show)
            label = self.form.labelForField(widget)
            if label is not None:
                label.setVisible(show)
        self.ed_kind.setText(KIND_TITLES.get(kind, "—") if kind else "виберіть крок")

    def _on_select(self) -> None:
        row = self.selected_row()
        step = self.program.steps[row] if row >= 0 else None
        for btn in self.row_buttons:
            btn.setEnabled(step is not None)
        self.goto_btn.setEnabled(self.owner and step is not None
                                 and step.kind in ("movej", "movel", "movep"))
        self._editing = True
        try:
            self._show_editor(step)
            if step is None:
                return
            self.ed_name.setText(step.text if step.kind != "comment" else "")
            joint = step.kind == "movej"
            values = step.joints if joint else step.pose
            for i, (spin, label) in enumerate(zip(self.ed_values, self.ed_value_labels)):
                label.setText(ui.JOINT_NAMES[i] + ", °" if joint else
                              ui.AXIS_NAMES[i] + (f", {self.program.units}" if i < 3 else ", °"))
                spin.setValue(values[i] if i < len(values) else 0.0)
            if joint:
                self.ed_speed.setRange(*ui.SPEED_JOINT_RANGE)
                self.ed_speed.setSuffix(" °/с")
            else:
                self.ed_speed.setRange(*ui.SPEED_LINEAR_RANGE)
                self.ed_speed.setSuffix(" од./с")
            self.ed_speed.setValue(step.speed)
            self.ed_seconds.setValue(step.seconds)
            self.ed_output.setValue(step.output)
            self.ed_state.setChecked(step.state)
            self.ed_text.setText(step.text if step.kind == "comment" else "")
        finally:
            self._editing = False

    def _on_edit(self, *_args) -> None:
        if self._editing:
            return
        row = self.selected_row()
        if row < 0:
            return
        step = self.program.steps[row]
        if step.kind in ("movej", "movel", "movep"):
            values = [spin.value() for spin in self.ed_values]
            if step.kind == "movej":
                step.joints = values
            else:
                step.pose = values
            step.text = self.ed_name.text().strip()
        step.speed = self.ed_speed.value() if step.kind in ("movej", "movel") else 0.0
        if step.kind == "wait":
            step.seconds = self.ed_seconds.value()
            step.text = self.ed_name.text().strip()
        if step.kind == "dout":
            step.output = self.ed_output.value()
            step.state = self.ed_state.isChecked()
            step.text = self.ed_name.text().strip()
        if step.kind == "comment":
            step.text = self.ed_text.text()
        self._mark_dirty()
        self._fill_row(row)

    def _on_name(self, text: str) -> None:
        self.program.name = text.strip() or "program"
        self._mark_dirty()

    def _on_default_speeds(self, *_args) -> None:
        self.program.joint_speed = self.joint_speed.value()
        self.program.linear_speed = self.linear_speed.value()
        self._mark_dirty()
        self.refresh_table(select=self.selected_row())

    # -----------------------------------------------------------------------
    # Файли
    # -----------------------------------------------------------------------

    def _load(self, program: Program, path: str | None) -> None:
        self.program, self.path, self.dirty = program, path, False
        self.name_edit.setText(program.name)
        for spin, value in ((self.joint_speed, program.joint_speed),
                            (self.linear_speed, program.linear_speed)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.editor_box.setTitle("Крок")
        self.refresh_table(select=0 if program.steps else None)

    def new_program(self) -> None:
        if self.confirm_discard():
            self._load(Program(units=self.status.u or "in"), None)

    def open_program(self) -> None:
        if not self.confirm_discard():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Відкрити програму", "",
                                                        ui.PROGRAM_FILE_FILTER)
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                self._load(Program.from_json(f.read()), path)
            self.log(f"Відкрито {path}")
        except (OSError, ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self, "Помилка", f"Не вдалося відкрити файл:\n{exc}")

    def save_program(self) -> bool:
        if not self.path:
            return self.save_program_as()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(self.program.to_json())
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Помилка", f"Не вдалося зберегти:\n{exc}")
            return False
        self.dirty = False
        self.editor_box.setTitle("Крок")
        self.log(f"Збережено {self.path}")
        return True

    def save_program_as(self) -> bool:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Зберегти програму", self.program.name + ui.PROGRAM_SUFFIX, ui.PROGRAM_FILE_FILTER)
        if not path:
            return False
        if not path.endswith(".json"):
            path += ui.PROGRAM_SUFFIX
        self.path = path
        return self.save_program()

    # -----------------------------------------------------------------------
    # G-код і робот
    # -----------------------------------------------------------------------

    def _gcode(self, steps: list[Step] | None = None) -> str | None:
        try:
            return to_gcode(self.program, steps)
        except ProgramError as exc:
            QtWidgets.QMessageBox.warning(self, "Програма", str(exc))
            return None

    def preview_gcode(self) -> None:
        gcode = self._gcode()
        if gcode is None:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"G-код: {self.program.file_name()}")
        dialog.resize(640, 560)
        lay = QtWidgets.QVBoxLayout(dialog)
        view = QtWidgets.QPlainTextEdit(gcode)
        view.setReadOnly(True)
        view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        lay.addWidget(view)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        lay.addWidget(buttons)
        dialog.exec_()

    async def _upload(self, name: str, gcode: str) -> None:
        self.progress.setVisible(True)
        self.progress.setValue(0)

        def progress(i, n):
            self.progress.setMaximum(n)
            self.progress.setValue(i)
        try:
            await self.client.upload_program(name, gcode, progress)
        finally:
            self.progress.setVisible(False)

    async def upload(self) -> None:
        gcode = self._gcode()
        if gcode is None:
            return
        name = self.program.file_name()
        await self._upload(name, gcode)
        self.log(f"Програму {name} завантажено на робот")

    def _check_ready(self) -> bool:
        s = self.status
        if not (s.is_on and s.all_homed):
            self.log("✖ для руху потрібні Power On і Home All")
            return False
        if s.run != "idle":
            self.log("✖ дочекайтесь завершення поточної програми")
            return False
        return True

    async def run_program(self) -> None:
        gcode = self._gcode()
        if gcode is None or not self._check_ready():
            return
        name = self.program.file_name()
        await self._upload(name, gcode)
        await self.client.open_program(name)
        await self.client.run()
        self.log(f"▶ Запущено {name}")

    async def goto_step(self) -> None:
        row = self.selected_row()
        if row < 0 or not self._check_ready():
            return
        step = self.program.steps[row]
        gcode = self._gcode([step])
        if gcode is None:
            return
        await self._upload(ui.GOTO_FILE, gcode)
        await self.client.open_program(ui.GOTO_FILE)
        await self.client.run()
        self.log(f"➜ Рух до кроку {row + 1} ({step.text or KIND_TITLES[step.kind]})")
