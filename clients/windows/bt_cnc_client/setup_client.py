# clients/windows/bt_cnc_client/setup_client.py
"""
Клієнт Wi-Fi-конфігуратора робота (system/bt-wifi-setup, сервіс CNC-Setup
по Bluetooth LE, Nordic UART). Без Qt і без bleak: транспорт — async-функція
запису байтів, вхідні байти подаються в feed().

Конфігуратор відповідає людським текстом (для терміналу на телефоні), тому
відповідь вважається завершеною, коли в ній з'явилась очікувана фраза і
після цього SETTLE_SEC не надходило нових даних.
"""
from __future__ import annotations

import asyncio
import codecs
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

# Nordic UART Service (system/bt-wifi-setup/bt_wifi_setup.py)
SETUP_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
SETUP_RX_UUID      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # клієнт -> Pi
SETUP_TX_UUID      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # Pi -> клієнт
SETUP_DEVICE_NAME  = "CNC-Setup"

SETTLE_SEC      = 0.4
REPLY_TIMEOUT   = 10.0
SCAN_TIMEOUT    = 30.0
CONNECT_TIMEOUT = 75.0      # nmcli --wait 30 + перевірка статусу

_SCAN_LINE = re.compile(r"^\s*(\d+)% (.*) \[([^\]]*)\]\s*$")
_IP_LINE = re.compile(r"^IP (\S+): ([\d.]+)\s*$")
_CONN_LINE = re.compile(r"^(wl\S*): (\S+)(?: \((.*)\))?\s*$")


class SetupError(Exception):
    """Помилка, зрозуміла людині (показується в майстрі як є)."""


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int
    security: str

    @property
    def secured(self) -> bool:
        return self.security.strip().lower() not in ("", "open", "--")


@dataclass
class SetupStatus:
    hostname: str = ""
    ips: dict[str, str] = field(default_factory=dict)   # пристрій -> IPv4
    wifi_state: str = ""
    wifi_network: str = ""

    @property
    def ip(self) -> str:
        """IP для підключення: спершу Wi-Fi, потім будь-який інший."""
        for dev, ip in self.ips.items():
            if dev.startswith("wl"):
                return ip
        return next(iter(self.ips.values()), "")


@dataclass
class ConnectResult:
    connected: bool
    message: str
    status: SetupStatus | None = None


def parse_networks(text: str) -> list[WifiNetwork]:
    nets = []
    for line in text.splitlines():
        m = _SCAN_LINE.match(line)
        if m:
            nets.append(WifiNetwork(m.group(2), int(m.group(1)), m.group(3)))
    return nets


def parse_status(text: str) -> SetupStatus:
    st = SetupStatus()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Ім'я: "):
            st.hostname = line[len("Ім'я: "):]
        elif m := _IP_LINE.match(line):
            st.ips[m.group(1)] = m.group(2)
        elif (m := _CONN_LINE.match(line)) and not st.wifi_state:
            st.wifi_state, st.wifi_network = m.group(2), m.group(3) or ""
    return st


class SetupClient:
    def __init__(self, write: Callable[[bytes], Awaitable[None]]) -> None:
        self._write = write
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.text = ""
        self._last_rx = 0.0
        self._event = asyncio.Event()
        self._lock = asyncio.Lock()

    # --- вхід ---------------------------------------------------------------

    def feed(self, data: bytes) -> None:
        self.text += self._decoder.decode(data)
        self._last_rx = time.monotonic()
        self._event.set()

    # --- обмін ----------------------------------------------------------------

    async def _exchange(self, line: str, done: Callable[[str], bool],
                        timeout: float = REPLY_TIMEOUT) -> str:
        """Надсилає рядок і чекає, поки відповідь задовольнить done() і стихне."""
        async with self._lock:
            start = len(self.text)
            await self._write((line + "\n").encode("utf-8"))
            deadline = time.monotonic() + timeout
            while True:
                reply = self.text[start:]
                if "Зачекайте, попередня команда" in reply:
                    raise SetupError("Робот ще виконує попередню дію, спробуйте за кілька секунд")
                if "Спершу введіть: pin" in reply:
                    raise SetupError("Потрібен PIN")
                if done(reply) and time.monotonic() - self._last_rx >= SETTLE_SEC:
                    return reply
                left = deadline - time.monotonic()
                if left <= 0:
                    raise SetupError("Робот не відповів вчасно")
                self._event.clear()
                try:
                    await asyncio.wait_for(self._event.wait(), min(left, SETTLE_SEC))
                except asyncio.TimeoutError:
                    pass

    async def login(self, pin: str) -> None:
        reply = await self._exchange(f"pin {pin}", lambda r: any(k in r for k in (
            "OK.", "Невірний PIN", "Забагато спроб", "PIN не налаштовано")))
        if "Невірний PIN" in reply:
            raise SetupError("Невірний PIN. Перевірте наліпку на роботі")
        if "Забагато спроб" in reply:
            raise SetupError("Забагато невдалих спроб PIN. Зачекайте хвилину")

    async def status(self) -> SetupStatus:
        reply = await self._exchange("status", lambda r: "SSH: ssh" in r or "IP-адреси немає" in r)
        return parse_status(reply)

    async def scan(self) -> list[WifiNetwork]:
        reply = await self._exchange("scan", lambda r: any(k in r for k in (
            "Мережі:", "Мереж не знайдено", "Помилка сканування")), SCAN_TIMEOUT)
        if "Помилка сканування" in reply:
            raise SetupError("Робот не зміг знайти мережі. Спробуйте ще раз")
        return sorted(parse_networks(reply), key=lambda n: -n.signal)

    async def connect_wifi(self, ssid: str, password: str | None) -> ConnectResult:
        """
        Зберігає мережу на роботі і підключає. password=None — відкрита мережа.
        ssid/pass окремими командами: так назви й паролі з лапками і пробілами
        передаються без екранування.
        """
        if "\n" in ssid or (password and "\n" in password):
            raise SetupError("Назва або пароль містять перенос рядка")
        await self._exchange(f"ssid {ssid}", lambda r: "Тепер: pass" in r or "Використання" in r)
        reply = await self._exchange(
            "open" if password is None else f"pass {password}",
            lambda r: any(k in r for k in (
                "Підключено до", "збережено, але", "Невірна назва", "Пароль WPA",
                "Не вдалося зберегти", "Помилка:")),
            CONNECT_TIMEOUT)
        if "Пароль WPA" in reply:
            return ConnectResult(False, "Пароль Wi-Fi має містити від 8 до 63 символів")
        if "Невірна назва" in reply:
            return ConnectResult(False, "Некоректна назва мережі")
        if "Не вдалося зберегти" in reply or "Помилка:" in reply:
            return ConnectResult(False, "Робот не зміг зберегти мережу. Спробуйте ще раз")
        if "збережено, але" in reply:
            return ConnectResult(False, "Не вдалося підключитись. Найчастіше — неправильний пароль "
                                        "або мережа задалеко від робота")
        status = parse_status(reply)
        if not status.ip:
            status = await self.status()
        return ConnectResult(True, f"Робот підключився до «{ssid}»", status)
