# logic/managers/ui/gcode_display.py
"""
GCodeDisplayManager – оновлення UI панелей G-коду.

Відповідальність:
  • update_cycle_buttons()   – активація кнопок циклу (Start/Pause/Stop…)
  • update_file_buttons()    – активація кнопок файлових операцій
  • update_active_gcodes()   – рядок активних G/M-кодів
  • update_gcode_display()   – делегує у GCodeEditorManager

НЕ відповідає за:
  • створення FileManager (це HandlerClass)
  • створення GCodeEditorManager (це HandlerClass.initialized__)
  • підключення кнопок (це HandlerClass._connect_file_buttons)

editor_manager встановлюється ззовні через:
    gcode_display_manager.editor_manager = editor_manager
після виклику initialized__().
"""
from __future__ import annotations

from PyQt5.QtCore import QCoreApplication

from managers.style_manager import StyleManager
from config import CYCLE_BUTTONS, FILE_BUTTONS


class GCodeDisplayManager:
    def __init__(self, machine_controller, widgets, cycle_manager=None):
        self.cnc     = machine_controller
        self.widgets = widgets

        self.cycle_buttons = CYCLE_BUTTONS
        self.file_buttons  = FILE_BUTTONS

        self.style_manager = StyleManager()
        self.style_manager._set_gcode_button_styles()

        # Встановлюється з HandlerClass.initialized__()
        # після того як loadUi завершено і list_gcode_edit існує
        self.editor_manager = None

    # ------------------------------------------------------------------
    # Допоміжний: чи є контент у редакторі
    # ------------------------------------------------------------------

    def _editor_has_content(self) -> bool:
        if self.editor_manager is None:
            return False
        try:
            return bool(self.editor_manager._editor.toPlainText().strip())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Cycle buttons
    # ------------------------------------------------------------------

    def update_cycle_buttons(self, states: dict) -> None:
        """Активація кнопок циклу залежно від стану станка і вмісту редактора."""
        ready      = states.get('is_ready', False) and states.get('all_homed', False)
        is_idle    = states.get('is_idle',    False)
        is_paused  = states.get('is_paused',  False)
        is_running = states.get('is_running', False)

        # has_file: файл завантажений у LinuxCNC АБО є вміст у редакторі
        has_file = states.get('has_file', False) or self._editor_has_content()

        conditions = {
            'btn_cycle_start':    is_idle and has_file and ready,
            'btn_cycle_pause':    is_running and ready,
            'btn_cycle_continue': is_paused and not is_running,
            'btn_cycle_stop':     (is_running or is_paused) and ready,
            'btn_cycle_step':     has_file and ready and (is_idle or is_paused or is_running),
        }

        for btn_name in self.cycle_buttons:
            self._set_btn_state(btn_name, conditions.get(btn_name, False))

    # ------------------------------------------------------------------
    # File buttons
    # ------------------------------------------------------------------

    def update_file_buttons(self, states: dict) -> None:
        """Активація кнопок файлових операцій."""
        is_idle  = states.get('is_idle', True)
        is_ready = states.get('is_ready', False)

        has_file    = bool(self.cnc.get_last_file()) or self._editor_has_content()
        has_content = self._editor_has_content()

        conditions = {
            # btn_file_open: доступна коли станок не рухається
            # (не прив'язуємо до is_ready — файл можна відкрити без homing)
            'btn_file_open':    is_idle,
            'btn_file_edit':    is_idle and has_file and is_ready,
            'btn_file_reload':  is_idle and has_file and is_ready,
            'btn_file_save_as': is_idle and has_content,
        }

        for btn_name in ('btn_file_open', 'btn_file_edit',
                         'btn_file_reload', 'btn_file_save_as'):
            btn = getattr(self.widgets, btn_name, None)
            if not btn:
                continue

            is_enabled = conditions.get(btn_name, False)
            if btn.isEnabled() != is_enabled:
                btn.setEnabled(is_enabled)

            if not is_enabled:
                target = self.style_manager.STYLE_GCODE_INACTIVE
            elif btn_name == 'btn_file_reload' and getattr(self.cnc, 'reload_needed', False):
                target = self.style_manager.STYLE_GCODE_WARN
            else:
                target = self.style_manager.STYLE_GCODE_ACTIVE

            if btn.styleSheet() != target:
                btn.setStyleSheet(target)

    # ------------------------------------------------------------------
    # Active G-code status bar
    # ------------------------------------------------------------------

    def update_active_gcodes(self, states: dict) -> None:
        status_bar = getattr(self.widgets, 'txt_gcodeStatusBar', None)
        if not status_bar:
            return

        gcodes = " ".join(
            f"G{c / 10.0:g}" for c in states.get('gcodes', []) if c != -1
        )
        mcodes = " ".join(
            f"M{m}" for m in states.get('mcodes', []) if m != -1
        )
        settings = states.get('settings', [0, 0, 0])
        text = f"{gcodes} | {mcodes} | F{settings[1]:.0f} S{settings[2]:.0f}"

        if status_bar.text() != text:
            status_bar.setText(text)

    # ------------------------------------------------------------------
    # G-code display – делегує у GCodeEditorManager
    # ------------------------------------------------------------------

    def update_gcode_display(self, states: dict) -> None:
        if self.editor_manager is None:
            return

        self.editor_manager.update(states)

        lbl = getattr(self.widgets, 'lbl_progress_percent', None)
        if not lbl:
            return

        is_idle     = states.get('is_idle', True)
        motion_line = states.get('motion_line', 0)
        total       = self.editor_manager._editor.document().blockCount()

        if total > 0:
            if is_idle and motion_line <= 0:
                pct = 0
            elif is_idle and motion_line >= total - 2:
                pct = 100
            else:
                pct = min(100, max(0, int(((motion_line + 1) / total) * 100)))
        else:
            pct = 0

        text = QCoreApplication.translate(
            "MainWindow", "PROGRESS %1%"
        ).replace("%1", str(pct))
        if lbl.text() != text:
            lbl.setText(text)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _set_btn_state(self, btn_name: str, is_enabled: bool) -> None:
        btn = getattr(self.widgets, btn_name, None)
        if btn:
            btn.setEnabled(is_enabled)
            btn.setStyleSheet(
                self.style_manager.STYLE_GCODE_ACTIVE
                if is_enabled
                else self.style_manager.STYLE_GCODE_INACTIVE
            )