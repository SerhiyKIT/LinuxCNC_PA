# clients/windows/bt_cnc_client/tests/test_protocol_client.py
"""Логіка клієнта без Qt, bleak і заліза."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol_client import (  # noqa: E402
    CncClient, CommandError, E_LINK, E_TIMEOUT, JogHold, LineAssembler, Status, parse_line,
)


def test_parse_line_kinds():
    m = parse_line("OK jog J1 5 @5")
    assert m.kind == "reply" and m.reply.ok and m.reply.cmd == "jog" and m.reply.data == "J1 5 @5"
    m = parse_line("ERR state спершу home all")
    assert m.kind == "reply" and not m.reply.ok and m.reply.code == "state"
    assert m.reply.data == "спершу home all"
    m = parse_line('EVT S {"st":"on","homed":[1,0],"j":[1.5,2],"ctl":1,"new":5}')
    assert m.kind == "status" and m.status.st == "on" and m.status.j == [1.5, 2]
    assert parse_line("EVT E watchdog J0").text == "watchdog J0"
    assert parse_line("EVT S {broken").kind == "unknown"
    assert parse_line("hello").kind == "unknown"


def test_status_helpers():
    assert not Status().is_on and not Status().all_homed
    assert Status(st="on", homed=[1, 1]).all_homed


def test_assembler_chunks_and_utf8():
    a = LineAssembler()
    data = "OK ls [\"Деталь.ngc\"]\nEVT E x\n".encode()
    lines = []
    for i in range(0, len(data), 7):          # ріжемо посеред UTF-8
        lines += a.feed(data[i:i + 7])
    assert lines == ['OK ls ["Деталь.ngc"]', "EVT E x"]


class Loopback:
    """Транспорт, що записує надіслане; відповіді подаються вручну."""

    def __init__(self):
        self.sent = []

    async def write(self, data: bytes):
        self.sent.append(data.decode())


def test_fifo_matching_and_errors():
    async def scenario():
        lb = Loopback()
        events = []
        c = CncClient(lb.write, on_event_error=events.append)
        t1 = asyncio.ensure_future(c.command("take"))
        t2 = asyncio.ensure_future(c.command("power on"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert lb.sent == ["take\n", "power on\n"]
        c.feed(b"EVT E something\nOK take\nERR state  estop")
        assert await t1 == ""
        c.feed(b" off\n")
        with pytest.raises(CommandError) as exc:
            await t2
        assert exc.value.code == "state" and exc.value.text == " estop off"
        assert events == ["something"]
    asyncio.run(scenario())


def test_timeout_drops_pending_and_keeps_order():
    async def scenario():
        lb = Loopback()
        c = CncClient(lb.write)
        with pytest.raises(CommandError) as exc:
            await c.command("status", timeout=0.01)
        assert exc.value.code == E_TIMEOUT and not c.pending
        t = asyncio.ensure_future(c.command("ver"))
        await asyncio.sleep(0)
        c.feed(b"OK ver 1\n")
        assert await t == "1"
    asyncio.run(scenario())


def test_connection_lost_fails_pending():
    async def scenario():
        c = CncClient(Loopback().write)
        t = asyncio.ensure_future(c.command("take"))
        await asyncio.sleep(0)
        c.connection_lost()
        with pytest.raises(CommandError) as exc:
            await t
        assert exc.value.code == E_LINK
    asyncio.run(scenario())


def test_pin_hidden_in_log():
    async def scenario():
        lines = []
        c = CncClient(Loopback().write, on_line=lambda d, t: lines.append(t))
        t = asyncio.ensure_future(c.command("pin 123456"))
        await asyncio.sleep(0)
        c.feed(b"OK pin\n")
        await t
        assert "123456" not in " ".join(lines)
    asyncio.run(scenario())


class AutoReply:
    """Відповідає OK на все — для перевірки JogHold."""

    def __init__(self):
        self.sent = []
        self.client = None
        self.delay = 0.0

    async def write(self, data: bytes):
        line = data.decode().strip()
        self.sent.append(line)
        name = line.split()[0]

        async def reply():
            await asyncio.sleep(self.delay)
            self.client.feed(f"OK {name}\n".encode())
        asyncio.ensure_future(reply())


def make_auto():
    t = AutoReply()
    c = CncClient(t.write)
    t.client = c
    return t, c


def test_jog_hold_pings_until_release():
    async def scenario():
        t, c = make_auto()
        jog = JogHold(c, interval=0.02)
        await jog.start(2, -1, 7.5)
        await asyncio.sleep(0.09)
        await jog.stop()
        await asyncio.sleep(0.05)
        assert t.sent[0] == "jogc J2 - 7.5"
        assert t.sent.count("ping") >= 3
        assert t.sent[-1] == "jogstop J2"
        assert not jog.active
    asyncio.run(scenario())


def test_jog_release_before_jogc_reply_does_not_start_heartbeat():
    async def scenario():
        t, c = make_auto()
        t.delay = 0.03                       # відповідь на jogc приходить пізно
        jog = JogHold(c, interval=0.01)
        press = asyncio.ensure_future(jog.start(0, 1, 5))
        await asyncio.sleep(0.005)           # кнопку вже відпустили
        await jog.stop()
        await press
        await asyncio.sleep(0.05)
        assert t.sent == ["jogc J0 + 5", "jogstop J0"]
        assert jog.task is None and not jog.active
    asyncio.run(scenario())


def test_jog_stops_when_ping_fails():
    async def scenario():
        errors = []
        lb = Loopback()
        c = CncClient(lb.write)
        jog = JogHold(c, on_error=errors.append, interval=0.01)
        t = asyncio.ensure_future(jog.start(1, 1, 5))
        await asyncio.sleep(0)
        c.feed(b"OK jogc J1 +5\n")
        await t
        await asyncio.sleep(1.2)             # ping без відповіді -> timeout 1 с
        assert errors and "jog зупинено" in errors[0]
        assert "jogstop J1\n" in lb.sent
        c.connection_lost()
    asyncio.run(scenario())
