# tests/gui/conftest.py
"""
Спільні fixtures і helpers для всіх GUI unit-тестів.
Автоматично підхоплюється pytest для всіх файлів у директорії.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_cnc():
    cnc = MagicMock()
    cnc.get_last_file.return_value = None
    cnc.reload_needed = False
    cnc.limits = {
        0: {"min": -180.0, "max": 180.0},
        1: {"min": -90.0,  "max": 90.0},
        2: {"min": -45.0,  "max": 45.0},
        3: {"min": -180.0, "max": 180.0},
        4: {"min": -90.0,  "max": 90.0},
        5: {"min": -180.0, "max": 180.0},
    }
    return cnc


@pytest.fixture
def mock_widgets():
    return MagicMock()


def base_states(**overrides):
    """Повний набір станів з safe defaults. Використовується у всіх тест-файлах."""
    base = {
        "power_on":        True,
        "estop_off":       True,
        "is_ready":        True,
        "all_homed":       True,
        "is_idle":         True,
        "is_paused":       False,
        "is_running":      False,
        "has_file":        True,
        "actual_position": [0.0] * 9,
        "joint_position":  [0.0] * 6,
        "gcodes":          [200, 900, -1, -1],
        "mcodes":          [5, -1, -1],
        "settings":        [0.0, 100.0, 500.0],
        "current_file":    "/tmp/test.ngc",
        "motion_line":     0,
        "manual_mode":     "axis",
    }
    base.update(overrides)
    return base
