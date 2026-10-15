# clients/windows/bt_cnc_client/main_window.py
"""
Головне вікно клієнта (PyQt5). Уся логіка протоколу — у protocol_client.py,
тут лише віджети і виклик async-методів через qasync.
"""
from __future__ import annotations

import asyncio
import logging

from PyQt5 import QtCore, QtWidgets

import ui_constants as ui
from ble_transport import BleTransport, scan
from protocol_client import CncClient, CommandError, JogHold, JOINTS, Status

logger = logging.getLogger(__name__)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(ui.WINDOW_TITLE)
        self.resize(*ui.WINDOW_SIZE)

        self.transport = BleTransport(on_data=self._on_data, on_disconnect=self._on_link_lost)
        self.client = CncClient(self.transport.write, on_status=self.show_status,
                                on_event_error=lambda t: self.log(f"⚠ {t}"),
                                on_line=lambda d, t: self.log(f"{d} {t}"))
        self.jog = JogHold(self.client, on_error=lambda t: self.log(f"⚠ {t}"))
        self.owner = False

        self._build()
        self.set_connected(False)
        QtWidgets.QApplication.instance().applicationStateChanged.connect(self._on_app_state)

    # -----------------------------------------------------------------------
    # Побудова інтерфейсу
    # -----------------------------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central)
        root.addLayout(self._build_connection())

        body = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        left.addWidget(self._build_safety())
        left.addWidget(self._build_status())
        left.addWidget(self._build_jog())
        body.addLayout(left, 3)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(self._build_program())
        right.addWidget(self._build_mdi())
        right.addWidget(self._build_log(), 1)
        body.addLayout(right, 2)

        root.addLayout(body, 1)
        self.setCentralWidget(central)

    def _build_connection(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.device_box = QtWidgets.QComboBox()
        self.device_box.setMinimumWidth(260)
        self.scan_btn = QtWidgets.QPushButton("Пошук")
        self.connect_btn = QtWidgets.QPushButton("Підключити")
        self.pin_edit = QtWidgets.QLineEdit()
        self.pin_edit.setPlaceholderText("PIN")
        self.pin_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pin_edit.setMaximumWidth(100)
        self.take_btn = QtWidgets.QPushButton("Взяти керування")
        self.take_btn.setCheckable(True)
        self.link_label = QtWidgets.QLabel()

        self.scan_btn.clicked.connect(lambda: self.run(self.do_scan()))
        self.connect_btn.clicked.connect(lambda: self.run(self.do_connect_toggle()))
        self.pin_edit.returnPressed.connect(lambda: self.run(self.do_connect_toggle()))
        self.take_btn.clicked.connect(lambda checked: self.run(self.do_take(checked)))

        for w in (QtWidgets.QLabel("Пристрій:"), self.device_box, self.scan_btn,
                  self.pin_edit, self.connect_btn, self.take_btn, self.link_label):
            row.addWidget(w)
        row.addStretch(1)
        return row

    def _build_safety(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Безпека і живлення")
        grid = QtWidgets.QGridLayout(box)
        self.estop_btn = QtWidgets.QPushButton("E-STOP")
        self.estop_btn.setStyleSheet(ui.ESTOP_STYLE)
        self.reset_btn = QtWidgets.QPushButton("Скинути E-stop")
        self.reset_btn.setStyleSheet(ui.RESET_STYLE)
        self.power_btn = QtWidgets.QPushButton("Power On")
        self.home_btn = QtWidgets.QPushButton("Home All")

        self.estop_btn.clicked.connect(lambda: self.run(self.do_estop()))
        self.reset_btn.clicked.connect(lambda: self.run(self.client.estop(False)))
        self.power_btn.clicked.connect(lambda: self.run(self.client.power(not self.client.status.is_on)))
        self.home_btn.clicked.connect(lambda: self.run(self.client.home_all()))

        grid.addWidget(self.estop_btn, 0, 0, 2, 1)
        grid.addWidget(self.reset_btn, 0, 1, 2, 1)
        grid.addWidget(self.power_btn, 0, 2)
        grid.addWidget(self.home_btn, 1, 2)
        grid.setColumnStretch(0, 2)
        return box

    def _build_status(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Стан")
        lay = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.state_label = QtWidgets.QLabel()
        self.mode_label = QtWidgets.QLabel()
        self.run_label = QtWidgets.QLabel()
        for w in (self.state_label, self.mode_label, self.run_label):
            row.addWidget(w)
        row.addStretch(1)
        lay.addLayout(row)

        self.joint_table = QtWidgets.QTableWidget(JOINTS, 2)
        self.joint_table.setHorizontalHeaderLabels(["Позиція, °", "Home"])
        self.joint_table.setVerticalHeaderLabels(ui.JOINT_NAMES)
        self.joint_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.joint_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.joint_table.setMaximumHeight(230)
        for r in range(JOINTS):
            for c in range(2):
                item = QtWidgets.QTableWidgetItem("—")
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.joint_table.setItem(r, c, item)
        lay.addWidget(self.joint_table)
        return box

    def _build_jog(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Jog")
        lay = QtWidgets.QVBoxLayout(box)
        opts = QtWidgets.QHBoxLayout()
        self.jog_mode = QtWidgets.QComboBox()
        self.jog_mode.addItems([ui.MODE_CONTINUOUS, ui.MODE_STEP])
        self.jog_vel = QtWidgets.QDoubleSpinBox()
        self.jog_vel.setRange(*ui.JOG_VEL_RANGE)
        self.jog_vel.setValue(ui.JOG_VEL_DEFAULT)
        self.jog_vel.setSuffix(" °/с")
        self.jog_step = QtWidgets.QDoubleSpinBox()
        self.jog_step.setRange(*ui.JOG_STEP_RANGE)
        self.jog_step.setValue(ui.JOG_STEP_DEFAULT)
        self.jog_step.setSuffix(" °")
        for w in (QtWidgets.QLabel("Режим:"), self.jog_mode, QtWidgets.QLabel("Швидкість:"),
                  self.jog_vel, QtWidgets.QLabel("Крок:"), self.jog_step):
            opts.addWidget(w)
        opts.addStretch(1)
        lay.addLayout(opts)

        grid = QtWidgets.QGridLayout()
        self.jog_buttons = []
        for j in range(JOINTS):
            minus = QtWidgets.QPushButton("−")
            plus = QtWidgets.QPushButton("+")
            for btn, direction in ((minus, -1), (plus, 1)):
                btn.setStyleSheet(ui.JOG_BUTTON_STYLE)
                btn.pressed.connect(lambda j=j, d=direction: self.run(self.do_jog_press(j, d)))
                btn.released.connect(lambda: self.run(self.do_jog_release()))
                self.jog_buttons.append(btn)
            grid.addWidget(QtWidgets.QLabel(ui.JOINT_NAMES[j]), j // 3, (j % 3) * 3)
            grid.addWidget(minus, j // 3, (j % 3) * 3 + 1)
            grid.addWidget(plus, j // 3, (j % 3) * 3 + 2)
        lay.addLayout(grid)
        return box

    def _build_program(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Програма")
        lay = QtWidgets.QVBoxLayout(box)
        self.prog_label = QtWidgets.QLabel("Файл: —")
        lay.addWidget(self.prog_label)
        self.files = QtWidgets.QListWidget()
        self.files.setMaximumHeight(150)
        self.files.itemDoubleClicked.connect(lambda item: self.run(self.client.open_program(item.text())))
        lay.addWidget(self.files)

        row = QtWidgets.QHBoxLayout()
        self.ls_btn = QtWidgets.QPushButton("Оновити")
        self.open_btn = QtWidgets.QPushButton("Відкрити")
        self.ls_btn.clicked.connect(lambda: self.run(self.do_list()))
        self.open_btn.clicked.connect(lambda: self.run(self.do_open()))
        row.addWidget(self.ls_btn)
        row.addWidget(self.open_btn)
        lay.addLayout(row)

        row = QtWidgets.QHBoxLayout()
        self.cycle_buttons = []
        for text, coro in (("▶ Run", self.client.run), ("⏸ Pause", self.client.pause),
                           ("⏵ Resume", self.client.resume), ("⏹ Stop", self.client.stop),
                           ("Step", self.client.step)):
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(lambda _=False, c=coro: self.run(c()))
            row.addWidget(btn)
            self.cycle_buttons.append(btn)
        lay.addLayout(row)

        row = QtWidgets.QHBoxLayout()
        self.fo_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.fo_slider.setRange(*ui.FO_RANGE)
        self.fo_slider.setValue(100)
        self.fo_label = QtWidgets.QLabel("Feed 100%")
        self.fo_slider.valueChanged.connect(lambda v: self.fo_label.setText(f"Feed {v}%"))
        self.fo_slider.sliderReleased.connect(
            lambda: self.run(self.client.feed_override(self.fo_slider.value())))
        row.addWidget(self.fo_label)
        row.addWidget(self.fo_slider, 1)
        lay.addLayout(row)
        return box

    def _build_mdi(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("MDI")
        row = QtWidgets.QHBoxLayout(box)
        self.mdi_edit = QtWidgets.QLineEdit()
        self.mdi_edit.setPlaceholderText("G0 X0 Y0")
        self.mdi_btn = QtWidgets.QPushButton("Виконати")
        self.mdi_edit.returnPressed.connect(lambda: self.run(self.do_mdi()))
        self.mdi_btn.clicked.connect(lambda: self.run(self.do_mdi()))
        row.addWidget(self.mdi_edit, 1)
        row.addWidget(self.mdi_btn)
        return box

    def _build_log(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Журнал")
        lay = QtWidgets.QVBoxLayout(box)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        lay.addWidget(self.log_view)
        return box

    # -----------------------------------------------------------------------
    # Допоміжне
    # -----------------------------------------------------------------------

    def run(self, coro) -> None:
        """Запускає корутину з обробкою помилок протоколу."""
        async def wrapper():
            try:
                await coro
            except CommandError as exc:
                self.log(f"✖ {exc.code}: {exc.text}")
            except Exception as exc:
                logger.exception("помилка")
                self.log(f"✖ {exc}")
        asyncio.ensure_future(wrapper())

    def log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def set_connected(self, connected: bool) -> None:
        self.connect_btn.setText("Відключити" if connected else "Підключити")
        self.link_label.setText("🟢 підключено" if connected else "⚪ не підключено")
        self.scan_btn.setEnabled(not connected)
        self.device_box.setEnabled(not connected)
        self.pin_edit.setEnabled(not connected)
        self.take_btn.setEnabled(connected)
        # E-stop доступний одразу після PIN, навіть без take
        self.estop_btn.setEnabled(connected)
        self.ls_btn.setEnabled(connected)
        if not connected:
            self.owner = False
            self.take_btn.setChecked(False)
            self.show_status(Status())
        self.set_owner(self.owner)

    def set_owner(self, owner: bool) -> None:
        self.owner = owner
        self.take_btn.setChecked(owner)
        self.take_btn.setText("Віддати керування" if owner else "Взяти керування")
        for w in ([self.reset_btn, self.power_btn, self.home_btn, self.open_btn, self.mdi_btn,
                   self.mdi_edit, self.fo_slider, self.jog_mode, self.jog_vel, self.jog_step]
                  + self.jog_buttons + self.cycle_buttons):
            w.setEnabled(owner)

    def show_status(self, s: Status) -> None:
        color = ui.COLORS.get(s.st, ui.COLORS["nocnc"])
        self.state_label.setText(ui.STATE_TEXT.get(s.st, s.st))
        self.state_label.setStyleSheet(ui.STATE_LABEL_STYLE.format(color=color))
        self.mode_label.setText(f"Режим: {s.mode or '—'}")
        line = f", рядок {s.line}" if s.line else ""
        self.run_label.setText(f"Програма: {ui.RUN_TEXT.get(s.run, s.run)}{line}")
        self.prog_label.setText(f"Файл: {s.prog or '—'}")
        self.power_btn.setText("Power Off" if s.is_on else "Power On")
        if not self.fo_slider.isSliderDown():
            self.fo_slider.blockSignals(True)
            self.fo_slider.setValue(s.fo)
            self.fo_slider.blockSignals(False)
            self.fo_label.setText(f"Feed {s.fo}%")
        for j in range(JOINTS):
            pos = f"{s.j[j]:.3f}" if j < len(s.j) else "—"
            homed = j < len(s.homed) and s.homed[j]
            self.joint_table.item(j, 0).setText(pos)
            item = self.joint_table.item(j, 1)
            item.setText("✔" if homed else "—")
            item.setForeground(QtCore.Qt.darkGreen if homed else QtCore.Qt.gray)

    # -----------------------------------------------------------------------
    # Дії
    # -----------------------------------------------------------------------

    async def do_scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.log("Пошук пристроїв...")
        try:
            devices = await scan()
        finally:
            self.scan_btn.setEnabled(not self.transport.connected)
        self.device_box.clear()
        for d in devices:
            self.device_box.addItem(f"{d.name}  ({d.address}, {d.rssi} dBm)", d.address)
        self.log(f"Знайдено: {len(devices)}" if devices else "CNC-Robot не знайдено")

    async def do_connect_toggle(self) -> None:
        if self.transport.connected:
            await self.jog.stop()
            await self.transport.disconnect()
            self.client.connection_lost()
            self.set_connected(False)
            self.log("Відключено")
            return
        address = self.device_box.currentData()
        if not address:
            self.log("Спершу знайдіть пристрій (Пошук)")
            return
        self.log(f"Підключення до {address}...")
        await self.transport.connect(address)
        try:
            version = await self.client.version()
            if version != 1:
                self.log(f"⚠ протокол v{version}, клієнт розрахований на v1")
            await self.client.login(self.pin_edit.text().strip())
            await self.client.request_status()
        except CommandError:
            await self.transport.disconnect()
            self.client.connection_lost()
            raise
        self.set_connected(True)
        self.log("Підключено. Натисніть «Взяти керування»")

    async def do_take(self, checked: bool) -> None:
        try:
            if checked:
                await self.client.take()
            else:
                await self.jog.stop()
                await self.client.release()
            self.set_owner(checked)
        except CommandError:
            self.set_owner(not checked)
            raise

    async def do_estop(self) -> None:
        await self.jog.stop()
        await self.client.estop(True)

    async def do_jog_press(self, joint: int, direction: int) -> None:
        if self.jog_mode.currentText() == ui.MODE_STEP:
            await self.client.jog_step(joint, direction * self.jog_step.value())
        else:
            await self.jog.start(joint, direction, self.jog_vel.value())

    async def do_jog_release(self) -> None:
        if self.jog.active:
            await self.jog.stop()

    async def do_list(self) -> None:
        names = await self.client.list_programs()
        self.files.clear()
        self.files.addItems(names)

    async def do_open(self) -> None:
        item = self.files.currentItem()
        if item is None:
            self.log("Виберіть файл")
            return
        await self.client.open_program(item.text())

    async def do_mdi(self) -> None:
        code = self.mdi_edit.text().strip()
        if code:
            await self.client.mdi(code)

    # -----------------------------------------------------------------------
    # Події
    # -----------------------------------------------------------------------

    def _on_data(self, data: bytes) -> None:
        self.client.feed(data)

    def _on_link_lost(self) -> None:
        # Міст сам зупинить jog і поставить програму на паузу
        self.jog.reset()
        self.client.connection_lost()
        self.set_connected(False)
        self.log("⚠ З'єднання втрачено")

    def _on_app_state(self, state) -> None:
        # Вікно втратило фокус під час утримання — кнопку могли "не відпустити"
        if state != QtCore.Qt.ApplicationActive and self.jog.active:
            self.run(self.jog.stop())

    def closeEvent(self, event) -> None:
        if self.transport.connected:
            self.run(self._shutdown())
        super().closeEvent(event)

    async def _shutdown(self) -> None:
        await self.jog.stop()
        if self.owner:
            try:
                await self.client.release()
            except CommandError:
                pass
        await self.transport.disconnect()
