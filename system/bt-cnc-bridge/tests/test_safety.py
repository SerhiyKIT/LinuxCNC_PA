# system/bt-cnc-bridge/tests/test_safety.py
import pytest

from bridge_constants import E_AUTH, E_BUSY, E_LOCKED, E_OWNER, LOCKOUT_SEC, MAX_PIN_FAILS
from protocol import ProtocolError
from safety import Safety


@pytest.fixture
def safety(clock):
    return Safety(pin="1234", watchdog_ms=500, max_jog_vel=20.0,
                  on_disconnect="pause", clock=clock)


def test_login_and_lockout(safety, clock):
    for _ in range(MAX_PIN_FAILS - 1):
        with pytest.raises(ProtocolError) as exc:
            safety.login("a", "0000")
        assert exc.value.code == E_AUTH
    with pytest.raises(ProtocolError) as exc:
        safety.login("a", "0000")
    assert exc.value.code == E_LOCKED
    # навіть правильний PIN під час блокування не приймається
    with pytest.raises(ProtocolError) as exc:
        safety.login("b", "1234")
    assert exc.value.code == E_LOCKED
    clock.advance(LOCKOUT_SEC + 1)
    safety.login("b", "1234")
    assert safety.is_authed("b") and not safety.is_authed("a")


def test_empty_pin_means_open_access(clock):
    s = Safety("", 500, 20.0, "pause", clock)
    assert s.is_authed("anyone")


def test_access_matrix(safety):
    for cmd in ("pin", "help", "ver"):
        safety.check_access("a", cmd)
    with pytest.raises(ProtocolError) as exc:
        safety.check_access("a", "status")
    assert exc.value.code == E_AUTH

    safety.login("a", "1234")
    safety.login("b", "1234")
    safety.check_access("a", "status")
    safety.check_access("b", "estop")        # аварійна зупинка доступна всім
    with pytest.raises(ProtocolError) as exc:
        safety.check_access("a", "jog")
    assert exc.value.code == E_OWNER

    safety.take("a")
    safety.check_access("a", "jog")
    with pytest.raises(ProtocolError) as exc:
        safety.take("b")
    assert exc.value.code == E_BUSY
    with pytest.raises(ProtocolError) as exc:
        safety.check_access("b", "run")
    assert exc.value.code == E_OWNER


def test_release_stops_jogs(safety):
    safety.take("a")
    safety.start_jogc(2)
    assert safety.release("a") == [2]
    assert safety.owner is None
    with pytest.raises(ProtocolError):
        safety.release("a")


def test_watchdog_expires_without_ping(safety, clock):
    safety.start_jogc(0)
    clock.advance(0.4)
    assert safety.expired() == []
    clock.advance(0.2)                        # 600 мс без ping
    assert safety.expired() == [0]
    assert safety.expired() == []             # вже зупинено


def test_ping_keeps_jog_alive(safety, clock):
    safety.start_jogc(1)
    for _ in range(10):
        clock.advance(0.3)
        safety.ping()
        assert safety.expired() == []
    clock.advance(0.6)
    assert safety.expired() == [1]


def test_stop_jog_single_and_all(safety):
    safety.start_jogc(0)
    safety.start_jogc(3)
    assert safety.stop_jog(3) == [3]
    assert safety.stop_jog(None) == [0]


def test_clamp_velocity(safety):
    assert safety.clamp_velocity(50, None) == 20
    assert safety.clamp_velocity(50, 5) == 5
    assert safety.clamp_velocity(3, 30) == 3
    assert safety.clamp_velocity(-50, None) == 20


def test_owner_disconnect(safety):
    safety.login("a", "1234")
    safety.take("a")
    safety.start_jogc(4)
    actions = safety.disconnect("a", program_running=True)
    assert actions.released and actions.stop_jogs == [4] and actions.program == "pause"
    assert safety.owner is None and not safety.is_authed("a")


def test_owner_disconnect_abort_policy(clock):
    s = Safety("1", 500, 20.0, "abort", clock)
    s.take("a")
    assert s.disconnect("a", program_running=True).program == "abort"


def test_non_owner_disconnect_changes_nothing(safety):
    safety.login("a", "1234")
    safety.login("b", "1234")
    safety.take("a")
    safety.start_jogc(0)
    actions = safety.disconnect("b", program_running=True)
    assert not actions.released and actions.program is None
    assert safety.owner == "a" and safety.jogging
