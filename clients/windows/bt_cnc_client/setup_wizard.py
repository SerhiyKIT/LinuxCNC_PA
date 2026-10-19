# clients/windows/bt_cnc_client/setup_wizard.py
"""
Майстер першого підключення для нетехнічного користувача:

  1. Знайти робота (Bluetooth).
  2. PIN з наліпки.
  3. Вибрати Wi-Fi зі списку і ввести пароль (або залишити поточну мережу).
  4. Перевірити підключення до робота по Wi-Fi і запам'ятати його.

Wi-Fi налаштовується через сервіс CNC-Setup (setup_client.py), керування —
через міст CNC-Robot по Wi-Fi (tcp_transport.py). Транспорти передаються
ззовні, щоб майстер можна було перевірити без справжнього Bluetooth.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from PyQt5 import QtCore, QtWidgets

from protocol_client import TCP_PORT, CncClient, CommandError
from setup_client import SETUP_RX_UUID, SETUP_TX_UUID, SetupClient, SetupError, SetupStatus, WifiNetwork

logger = logging.getLogger(__name__)

TITLE_STYLE = "font-size: 18px; font-weight: 600;"
HINT_STYLE = "color: #4a5560;"
ERROR_STYLE = "color: #c62828;"
OK_STYLE = "color: #2e7d32; font-weight: 600;"


def default_ble_transport(on_data, on_disconnect):
    from ble_transport import BleTransport       # bleak лише коли справді потрібен
    return BleTransport(on_data, on_disconnect, rx_uuid=SETUP_RX_UUID, tx_uuid=SETUP_TX_UUID)


async def default_scan():
    from ble_transport import scan
    return await scan()


def default_tcp_transport(on_data, on_disconnect):
    from tcp_transport import TcpTransport
    return TcpTransport(on_data, on_disconnect)


class SetupWizard(QtWidgets.QDialog):
    """Після успіху надсилає completed(host, pin, remember)."""

    completed = QtCore.pyqtSignal(str, str, bool)

    def __init__(self, parent=None,
                 scan: Callable[[], Awaitable[list]] = default_scan,
                 make_ble: Callable = default_ble_transport,
                 make_tcp: Callable = default_tcp_transport) -> None:
        super().__init__(parent)
        self.setWindowTitle("Перше підключення до робота")
        self.setModal(True)
        self.resize(560, 480)
        self._scan, self._make_ble, self._make_tcp = scan, make_ble, make_tcp
        self.transport = None
        self.setup: SetupClient | None = None
        self.status = SetupStatus()
        self.networks: list[WifiNetwork] = []
        self.pin = ""
        self.busy = False

        root = QtWidgets.QVBoxLayout(self)
        self.steps_label = QtWidgets.QLabel()
        self.steps_label.setStyleSheet(HINT_STYLE)
        root.addWidget(self.steps_label)
        self.stack = QtWidgets.QStackedWidget()
        root.addWidget(self.stack, 1)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        root.addWidget(self.message)

        buttons = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("← Назад")
        self.next_btn = QtWidgets.QPushButton("Далі →")
        self.next_btn.setDefault(True)
        self.cancel_btn = QtWidgets.QPushButton("Скасувати")
        self.back_btn.clicked.connect(self.go_back)
        self.next_btn.clicked.connect(lambda: self.run(self.go_next()))
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        root.addLayout(buttons)

        self.stack.addWidget(self._page_find())
        self.stack.addWidget(self._page_pin())
        self.stack.addWidget(self._page_wifi())
        self.stack.addWidget(self._page_done())
        self.show_page(0)

    # -----------------------------------------------------------------------
    # Сторінки
    # -----------------------------------------------------------------------

    def _page(self, title: str, text: str) -> tuple[QtWidgets.QWidget, QtWidgets.QVBoxLayout]:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        head = QtWidgets.QLabel(title)
        head.setStyleSheet(TITLE_STYLE)
        lay.addWidget(head)
        hint = QtWidgets.QLabel(text)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return page, lay

    def _page_find(self):
        page, lay = self._page(
            "Знайдіть робота",
            "Увімкніть робота і зачекайте 1–2 хвилини. Тримайте комп'ютер поруч "
            "(до 5 метрів) і переконайтеся, що Bluetooth у Windows увімкнений.")
        self.find_btn = QtWidgets.QPushButton("🔍 Знайти робота")
        self.find_btn.clicked.connect(lambda: self.run(self.find_robots()))
        lay.addWidget(self.find_btn)
        self.robot_list = QtWidgets.QListWidget()
        self.robot_list.itemSelectionChanged.connect(self.update_buttons)
        self.robot_list.itemDoubleClicked.connect(lambda _: self.run(self.go_next()))
        lay.addWidget(self.robot_list, 1)
        return page

    def _page_pin(self):
        page, lay = self._page(
            "Введіть PIN",
            "PIN — це 6 цифр з наліпки на роботі (рядок «PIN»).")
        self.pin_edit = QtWidgets.QLineEdit()
        self.pin_edit.setPlaceholderText("напр. 123456")
        self.pin_edit.setMaxLength(32)
        self.pin_edit.setStyleSheet("font-size: 20px; padding: 6px;")
        self.pin_edit.textChanged.connect(self.update_buttons)
        self.pin_edit.returnPressed.connect(lambda: self.run(self.go_next()))
        lay.addWidget(self.pin_edit)
        lay.addStretch(1)
        return page

    def _page_wifi(self):
        page, lay = self._page(
            "Підключіть робота до Wi-Fi",
            "Виберіть мережу, до якої підключений цей комп'ютер, і введіть її пароль.")
        self.current_label = QtWidgets.QLabel()
        self.current_label.setWordWrap(True)
        self.current_label.setStyleSheet(OK_STYLE)
        lay.addWidget(self.current_label)
        self.keep_btn = QtWidgets.QPushButton("Залишити цю мережу")
        self.keep_btn.clicked.connect(lambda: self.run(self.keep_current()))
        lay.addWidget(self.keep_btn)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Мережі поблизу робота:"))
        row.addStretch(1)
        self.rescan_btn = QtWidgets.QPushButton("↻ Оновити")
        self.rescan_btn.clicked.connect(lambda: self.run(self.scan_wifi()))
        row.addWidget(self.rescan_btn)
        lay.addLayout(row)
        self.wifi_list = QtWidgets.QListWidget()
        self.wifi_list.itemSelectionChanged.connect(self._on_wifi_selected)
        lay.addWidget(self.wifi_list, 1)

        form = QtWidgets.QFormLayout()
        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password_edit.textChanged.connect(self.update_buttons)
        self.password_edit.returnPressed.connect(lambda: self.run(self.go_next()))
        self.show_password = QtWidgets.QCheckBox("показати пароль")
        self.show_password.toggled.connect(lambda on: self.password_edit.setEchoMode(
            QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password))
        form.addRow("Пароль Wi-Fi:", self.password_edit)
        form.addRow("", self.show_password)
        lay.addLayout(form)
        return page

    def _page_done(self):
        page, lay = self._page("Майже готово", "")
        self.done_label = lay.itemAt(1).widget()
        self.done_label.setStyleSheet(OK_STYLE)
        form = QtWidgets.QFormLayout()
        self.control_pin = QtWidgets.QLineEdit()
        self.control_pin.setEchoMode(QtWidgets.QLineEdit.Password)
        self.control_pin.textChanged.connect(self.update_buttons)
        form.addRow("PIN керування:", self.control_pin)
        self.remember = QtWidgets.QCheckBox("Запам'ятати робота і підключатися автоматично")
        self.remember.setChecked(True)
        form.addRow("", self.remember)
        lay.addLayout(form)
        hint = QtWidgets.QLabel("Зазвичай PIN керування такий самий. Якщо на наліпці є окремий "
                                "«PIN керування» — введіть його.")
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        lay.addWidget(hint)
        lay.addStretch(1)
        return page

    # -----------------------------------------------------------------------
    # Навігація
    # -----------------------------------------------------------------------

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        names = ["1. Пошук", "2. PIN", "3. Wi-Fi", "4. Готово"]
        self.steps_label.setText("   ".join(f"<b>{n}</b>" if i == index else n for i, n in enumerate(names)))
        self.next_btn.setText("Підключитися до робота" if index == 3 else
                              "Підключити Wi-Fi" if index == 2 else "Далі →")
        self.message.clear()
        self.update_buttons()

    def update_buttons(self) -> None:
        index = self.stack.currentIndex()
        ready = {
            0: bool(self.robot_list.selectedItems()),
            1: bool(self.pin_edit.text().strip()),
            2: self._wifi_ready(),
            3: bool(self.control_pin.text().strip()),
        }[index]
        self.next_btn.setEnabled(ready and not self.busy)
        self.back_btn.setEnabled(index > 0 and not self.busy)
        for w in (self.find_btn, self.rescan_btn, self.keep_btn, self.wifi_list, self.pin_edit):
            w.setEnabled(not self.busy)

    def _selected_network(self) -> WifiNetwork | None:
        items = self.wifi_list.selectedItems()
        return items[0].data(QtCore.Qt.UserRole) if items else None

    def _wifi_ready(self) -> bool:
        net = self._selected_network()
        if net is None:
            return False
        return not net.secured or len(self.password_edit.text()) >= 8

    def _on_wifi_selected(self) -> None:
        net = self._selected_network()
        secured = net is None or net.secured
        self.password_edit.setEnabled(secured)
        self.show_password.setEnabled(secured)
        self.password_edit.setPlaceholderText("" if secured else "відкрита мережа, пароль не потрібен")
        self.update_buttons()

    def say(self, text: str, error: bool = False) -> None:
        self.message.setStyleSheet(ERROR_STYLE if error else HINT_STYLE)
        self.message.setText(text)

    def run(self, coro) -> None:
        async def wrapper():
            self.busy = True
            self.update_buttons()
            try:
                await coro
            except (SetupError, CommandError) as exc:
                self.say(getattr(exc, "text", None) or str(exc), error=True)
            except Exception as exc:
                logger.exception("майстер")
                self.say(f"Помилка зв'язку: {exc}", error=True)
            finally:
                self.busy = False
                self.update_buttons()
        asyncio.ensure_future(wrapper())

    def go_back(self) -> None:
        index = self.stack.currentIndex()
        if index == 1:
            self.run(self._close_ble())
        self.show_page(max(0, index - 1))

    async def go_next(self) -> None:
        if not self.next_btn.isEnabled() and not self.busy:
            return
        index = self.stack.currentIndex()
        if index == 0:
            self.show_page(1)
            self.pin_edit.setFocus()
        elif index == 1:
            await self.login()
        elif index == 2:
            await self.connect_wifi()
        elif index == 3:
            await self.finish()

    # -----------------------------------------------------------------------
    # Дії
    # -----------------------------------------------------------------------

    async def find_robots(self) -> None:
        self.say("Шукаю робота… (до 10 секунд)")
        self.robot_list.clear()
        devices = await self._scan()
        if not devices:
            self.say("Робота не знайдено. Перевірте, що він увімкнений 1–2 хвилини і стоїть поруч, "
                     "а Bluetooth у Windows увімкнений. Потім натисніть «Знайти робота» ще раз.", error=True)
            return
        seen = set()
        for d in devices:
            if d.address in seen:
                continue
            seen.add(d.address)
            item = QtWidgets.QListWidgetItem(f"🤖 Робот  ({d.address})   сигнал: {self._bars(d.rssi)}")
            item.setData(QtCore.Qt.UserRole, d.address)
            self.robot_list.addItem(item)
        self.robot_list.setCurrentRow(0)
        self.say("Знайдено. Натисніть «Далі»." if len(seen) == 1 else
                 "Знайдено кілька роботів — виберіть найближчий (сильніший сигнал).")

    @staticmethod
    def _bars(rssi: int) -> str:
        return "●●●" if rssi > -60 else "●●○" if rssi > -75 else "●○○"

    async def _close_ble(self) -> None:
        transport, self.transport = self.transport, None
        if transport is not None:
            await transport.disconnect()

    async def login(self) -> None:
        address = self.robot_list.selectedItems()[0].data(QtCore.Qt.UserRole)
        self.pin = self.pin_edit.text().strip()
        if self.transport is None:
            self.say("Підключаюсь до робота по Bluetooth…")
            self.setup = None
            transport = self._make_ble(lambda d: self.setup and self.setup.feed(d), self._on_ble_lost)
            self.setup = SetupClient(transport.write)
            await transport.connect(address)
            self.transport = transport
        await self.setup.login(self.pin)
        self.say("Перевіряю мережу робота…")
        self.status = await self.setup.status()
        self.show_page(2)
        self._show_current()
        await self.scan_wifi()

    def _on_ble_lost(self) -> None:
        self.transport = None
        if self.isVisible() and self.stack.currentIndex() in (1, 2):
            self.say("Зв'язок Bluetooth з роботом обірвався. Поверніться на крок «Пошук».", error=True)

    def _show_current(self) -> None:
        st = self.status
        if st.ip:
            name = f"«{st.wifi_network}»" if st.wifi_network else "мережі"
            self.current_label.setText(f"✔ Робот уже підключений до {name} (адреса {st.ip}).")
        self.current_label.setVisible(bool(st.ip))
        self.keep_btn.setVisible(bool(st.ip))

    async def scan_wifi(self) -> None:
        self.say("Робот шукає Wi-Fi мережі… (до 15 секунд)")
        self.networks = await self.setup.scan()
        self.wifi_list.clear()
        for net in self.networks:
            lock = "🔒" if net.secured else "🔓"
            item = QtWidgets.QListWidgetItem(f"{lock}  {net.ssid}    {net.signal}%")
            item.setData(QtCore.Qt.UserRole, net)
            self.wifi_list.addItem(item)
        self.say("Виберіть мережу зі списку." if self.networks else
                 "Робот не бачить жодної мережі. Перевірте роутер і натисніть «Оновити».",
                 error=not self.networks)

    async def keep_current(self) -> None:
        self._to_done()

    async def connect_wifi(self) -> None:
        net = self._selected_network()
        password = self.password_edit.text() if net.secured else None
        self.say(f"Підключаю робота до «{net.ssid}»… Це може тривати до хвилини.")
        result = await self.setup.connect_wifi(net.ssid, password)
        if not result.connected:
            self.say(result.message, error=True)
            return
        self.status = result.status
        self._to_done()

    def _to_done(self) -> None:
        st = self.status
        network = f"«{st.wifi_network}»" if st.wifi_network else "Wi-Fi"
        self.done_label.setText(f"✔ Робот у мережі {network}, адреса {st.ip}.\n"
                                "Залишилось перевірити підключення до робота.")
        self.control_pin.setText(self.pin)
        self.show_page(3)

    async def finish(self) -> None:
        host = f"{self.status.ip}:{TCP_PORT}"
        pin = self.control_pin.text().strip()
        self.say(f"Перевіряю підключення до {self.status.ip}…")
        client = None
        transport = self._make_tcp(lambda d: client.feed(d), lambda: None)
        client = CncClient(transport.write)
        try:
            await transport.connect(host)
        except (OSError, asyncio.TimeoutError):
            self.say("Комп'ютер не бачить робота в мережі. Переконайтеся, що комп'ютер підключений "
                     "до тієї ж Wi-Fi мережі, що й робот, і спробуйте ще раз.", error=True)
            return
        try:
            await client.version()
            await client.login(pin)
        except CommandError as exc:
            if exc.code in ("auth", "locked"):
                self.say("PIN керування не підійшов. Введіть «PIN керування» з наліпки.", error=True)
                return
            raise
        finally:
            await transport.disconnect()
        await self._close_ble()
        self.completed.emit(host, pin, self.remember.isChecked())
        self.accept()

    def done(self, result: int) -> None:            # закриття будь-яким способом
        if self.transport is not None:
            asyncio.ensure_future(self._close_ble())
        super().done(result)
