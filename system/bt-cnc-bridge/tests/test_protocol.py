# system/bt-cnc-bridge/tests/test_protocol.py
import json

import pytest

from bridge_constants import E_ARGS, E_OVERFLOW, E_PATH, E_UNKNOWN
from protocol import (
    Command, LineAssembler, ProtocolError, format_err, format_event_error,
    format_ok, format_status, parse, split_payload,
)


@pytest.mark.parametrize("line, expected", [
    ("ver", Command("ver")),
    ("HELP", Command("help")),
    ("pin 0000", Command("pin", ("0000",))),
    ("take", Command("take")),
    ("release", Command("release")),
    ("status", Command("status")),
    ("ping", Command("ping")),
    ("ls", Command("ls")),
    ("estop on", Command("estop", (True,))),
    ("estop OFF", Command("estop", (False,))),
    ("power on", Command("power", (True,))),
    ("home all", Command("home", (-1,))),
    ("home J3", Command("home", (3,))),
    ("home 5", Command("home", (5,))),
    ("unhome all", Command("unhome", (-1,))),
    ("jog J0 +5", Command("jog", (0, 5.0))),
    ("jog j2 -0.5", Command("jog", (2, -0.5))),
    ("jogc J1 + 10", Command("jogc", (1, 1, 10.0))),
    ("jogc J1 - 2.5", Command("jogc", (1, -1, 2.5))),
    ("jogstop", Command("jogstop", (None,))),
    ("jogstop J4", Command("jogstop", (4,))),
    ("mdi G0 X1 Y2", Command("mdi", ("G0 X1 Y2",))),
    ("open part.ngc", Command("open", ("part.ngc",))),
    ("open Деталь 2.nc", Command("open", ("Деталь 2.nc",))),
    ("run", Command("run", (0,))),
    ("run 12", Command("run", (12,))),
    ("pause", Command("pause")),
    ("resume", Command("resume")),
    ("stop", Command("stop")),
    ("step", Command("step")),
    ("fo 150", Command("fo", (150.0,))),
    ("ro 0", Command("ro", (0.0,))),
    ("  status  \r", Command("status")),
])
def test_parse_valid(line, expected):
    assert parse(line) == expected


@pytest.mark.parametrize("line, code", [
    ("", E_ARGS),
    ("fly", E_UNKNOWN),
    ("ver 2", E_ARGS),
    ("pin", E_ARGS),
    ("estop maybe", E_ARGS),
    ("power", E_ARGS),
    ("home", E_ARGS),
    ("home J6", E_ARGS),
    ("home Jx", E_ARGS),
    ("jog J0", E_ARGS),
    ("jog J0 0", E_ARGS),
    ("jog J0 abc", E_ARGS),
    ("jog J0 nan", E_ARGS),
    ("jog J0 inf", E_ARGS),
    ("jogc J0 10", E_ARGS),
    ("jogc J0 * 10", E_ARGS),
    ("jogc J0 + 0", E_ARGS),
    ("jogc J0 + -5", E_ARGS),
    ("jogstop J0 J1", E_ARGS),
    ("mdi", E_ARGS),
    ("run -1", E_ARGS),
    ("run abc", E_ARGS),
    ("fo 151", E_ARGS),
    ("fo -1", E_ARGS),
    ("ro 101", E_ARGS),
    ("fo", E_ARGS),
])
def test_parse_invalid(line, code):
    with pytest.raises(ProtocolError) as exc:
        parse(line)
    assert exc.value.code == code


@pytest.mark.parametrize("name", [
    "../secret.ngc", "..\\secret.ngc", "/etc/passwd", "sub/part.ngc",
    "..", ".hidden.ngc", "part..ngc", "notes.txt", "", "part.ngc\0.ngc",
])
def test_open_rejects_unsafe_names(name):
    with pytest.raises(ProtocolError) as exc:
        parse("open " + name)
    assert exc.value.code in (E_PATH, E_ARGS)


def test_format_helpers():
    assert format_ok("take") == "OK take"
    assert format_ok("ver", "1") == "OK ver 1"
    assert format_err("state", "спершу\nhome all") == "ERR state спершу home all"
    assert format_event_error("a\nb") == "EVT E a b"
    line = format_status({"st": "on", "j": [1.5, 0.0]})
    assert line.startswith("EVT S ") and "\n" not in line
    assert json.loads(line[6:]) == {"st": "on", "j": [1.5, 0.0]}


def test_assembler_lines_and_crlf():
    a = LineAssembler()
    assert a.feed(b"pi") == []
    assert a.feed(b"ng\r\nstat") == ["ping"]
    assert a.feed(b"us\n\n") == ["status"]


def test_assembler_overflow_then_recovers():
    a = LineAssembler(limit=8)
    out = a.feed(b"x" * 20)
    assert len(out) == 1 and isinstance(out[0], ProtocolError)
    assert out[0].code == E_OVERFLOW
    # хвіст довгого рядка відкидається до '\n', далі все працює
    assert a.feed(b"yyy\nping\n") == ["ping"]


def test_split_payload_keeps_utf8_and_newline():
    text = "OK ls [\"Деталь 2.nc\",\"part.ngc\"]"
    chunks = split_payload(text, 20)
    assert all(len(c) <= 20 for c in chunks)
    for c in chunks:
        c.decode("utf-8")                     # жоден пакет не рве символ
    assert b"".join(chunks).decode() == text + "\n"


# --- світові осі і файли --------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("jogw x +0.5", Command("jogw", ("X", 0.5))),
    ("jogw C -10", Command("jogw", ("C", -10.0))),
    ("jogwc Z - 0.2", Command("jogwc", ("Z", -1, 0.2))),
    ("jogstop A", Command("jogstop", ("A",))),
    ("jogstop J2", Command("jogstop", (2,))),
    ("file begin teach.ngc", Command("file", ("begin", "teach.ngc"))),
    ("file data G53 G1 X1 Y2 F60", Command("file", ("data", "G53 G1 X1 Y2 F60"))),
    ("file data", Command("file", ("data", ""))),
    ("file end", Command("file", ("end",))),
    ("file abort", Command("file", ("abort",))),
    ("rm teach.ngc", Command("rm", ("teach.ngc",))),
])
def test_parse_world_and_file(line, expected):
    assert parse(line) == expected


@pytest.mark.parametrize("line, code", [
    ("jogw Q 1", E_ARGS), ("jogw X 0", E_ARGS), ("jogwc X * 1", E_ARGS),
    ("jogwc X + 0", E_ARGS), ("file", E_ARGS), ("file end now", E_ARGS),
    ("file begin ../x.ngc", E_PATH), ("file begin notes.txt", E_PATH), ("rm /etc/passwd", E_PATH),
])
def test_parse_world_and_file_invalid(line, code):
    with pytest.raises(ProtocolError) as exc:
        parse(line)
    assert exc.value.code == code
