# tests/gui_functional/conftest.py
"""
Спільна інфраструктура для функціональних GUI-тестів (pytest-qt).
=================================================================

Стратегія:
  • Всі Qt-віджети — РЕАЛЬНІ (QPushButton, QSlider, QListWidget тощо).
  • cnc (MachineController) — MagicMock: тести перевіряють реакцію UI,
    а не логіку CNC-шару.
  • StyleManager — реальний або мінімальний stub (рядкові CSS не тестуємо).
  • Кожна fixture будує мінімальний набір реальних Qt-об'єктів,
    необхідних для конкретного менеджера.

Залежності:
  pip install pytest-qt PyQt5
"""

import pytest
from unittest.mock import MagicMock, patch
from PyQt5 import QtWidgets, QtCore


# ---------------------------------------------------------------------------
# Спільні helpers
# ---------------------------------------------------------------------------

def base_states(**overrides):
    """Повний набір станів зі safe defaults для реальних Qt-тестів."""
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


def make_cnc(**kwargs):
    """Створює мінімальний mock MachineController."""
    cnc = MagicMock()
    cnc.get_last_file.return_value = None
    cnc.reload_needed = False
    cnc.limits = {
        i: {"min": -180.0, "max": 180.0} for i in range(6)
    }
    for k, v in kwargs.items():
        setattr(cnc, k, v)
    return cnc


# ---------------------------------------------------------------------------
# StyleManager stub — повертає нейтральні рядки, не кидає AttributeError
# ---------------------------------------------------------------------------

class _StyleStub:
    """Мінімальний замінник StyleManager для GUI-тестів."""
    def __getattr__(self, name):
        return f"stub_{name}"
    def __call__(self, *a, **kw):
        return self
    # Виклики _set_*_styles() — no-op
    def _set_gcode_button_styles(self): pass
    def _set_logger_styles(self):       pass
    def _set_jogging_styles(self):      pass
    def _set_emergency_stop_styles(self): pass
    def _set_power_styles(self):          pass
    def _set_homing_styles(self):         pass
    def _set_panel_styles(self):          pass


@pytest.fixture(autouse=True)
def patch_style_manager():
    """Патчить StyleManager у всіх UI-менеджерах глобально."""
    stub = _StyleStub()
    targets = [
        "managers.ui.gcode_display.StyleManager",
        "managers.ui.motion_display.StyleManager",
        "managers.ui.panel_manager.StyleManager",
        "managers.ui.logger_display.StyleManager",
        "managers.ui.tool_display.StyleManager",
    ]
    patchers = [patch(t, return_value=stub) for t in targets]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()
