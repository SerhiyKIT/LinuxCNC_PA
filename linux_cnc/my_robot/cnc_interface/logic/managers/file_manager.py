# logic/managers/file_manager.py
"""
FileManager – файлові операції G-коду: відкриття, збереження, перезавантаження
та запуск зовнішнього редактора.

Зміни відносно попередньої версії
──────────────────────────────────
• Повністю видалено логіку QListView / QStringListModel:
    - _load_gcode_to_view()  → замінено на _load_into_editor()
    - _sync_line_numbers()   → видалено (вбудована нумерація в GCodeEditorWidget)
    - _on_gcode_edited()     → видалено (auto-save живе в GCodeEditorManager)
    - _get_gcode_model()     → видалено
    - _write_model_to_file() → видалено
    - _EDIT_TRIGGERS         → видалено
• Весь вміст файлу тепер завантажується у віджет ``list_gcode_edit``
  (GCodeEditorWidget / QPlainTextEdit) через його метод ``load_text()``.
• _LineNumScrollForwarder видалено — більше не потрібен.
• connect_file_buttons() підключає лише btn_file_edit (зовнішній редактор);
  btn_file_open / save_as / reload підключає GCodeEditorManager, щоб уникнути
  подвійного з'єднання і конфлікту власника операцій.
• Публічний метод load_file_into_editor() дозволяє GCodeEditorManager або
  будь-якому іншому менеджеру перевикористати I/O-логіку FileManager
  (читання файлу, оновлення міток) не дублюючи код.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QFileDialog

from config import STYLES

if TYPE_CHECKING:
    from logic.core.machine import MachineController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------

_DEFAULT_GCODE_DIR  = os.path.expanduser("~/linuxcnc-dev/configs/sim/axis/nc_files")
_GCODE_FILTER       = "G-Code Files (*.ngc *.txt *.gcode);;All Files (*)"
_SAVE_FILTER        = "G-Code Files (*.ngc *.txt)"
_GCODE_EXTENSIONS   = (".ngc", ".txt", ".gcode")
_FALLBACK_EXTENSION = ".ngc"
_CANDIDATE_EDITORS  = ("gedit", "mousepad", "leafpad", "xed", "nano")


# ---------------------------------------------------------------------------
# FileManager
# ---------------------------------------------------------------------------

class FileManager:
    """
    Управляє файловими операціями G-коду.

    Відповідає за:
      • відкриття файлу через діалог → завантаження у редактор + cnc.open_program()
      • збереження копії (Save As) → збереження з редактора на диск + open_program()
      • перезавантаження останнього файлу з диска → редактор + open_program()
      • відкриття у зовнішньому текстовому редакторі (gedit / mousepad / …)

    НЕ відповідає за:
      • auto-save при редагуванні в редакторі (це GCodeEditorManager)
      • підсвітку синтаксису та нумерацію рядків (це GCodeEditorWidget)
      • підключення btn_file_open / save_as / reload (це GCodeEditorManager)

    Параметри
    ---------
    machine_controller : MachineController
    widgets            : об'єкт-контейнер UI-віджетів
    """

    __slots__ = ("cnc", "widgets", "STYLE_GCODE_WARN", "_editor_widget", "__weakref__")

    def __init__(
        self,
        machine_controller: "MachineController",
        widgets: object,
    ) -> None:
        self.cnc              = machine_controller
        self.widgets          = widgets
        self.STYLE_GCODE_WARN = STYLES.get("GCODE_WARN", "")
        self._editor_widget   = None   # встановлюється з HandlerClass.initialized__

    # ------------------------------------------------------------------
    # Підключення кнопок
    # ------------------------------------------------------------------

    def connect_file_buttons(self) -> None:
        """
        Підключити лише btn_file_edit до on_btn_file_edit_clicked.

        btn_file_open / btn_file_reload / btn_file_save_as підключаються
        окремо через GCodeEditorManager.connect_file_buttons(), щоб уникнути
        подвійного сигналу і чіткіше розмежувати відповідальність.
        """
        btn = getattr(self.widgets, "btn_file_edit", None)
        if btn is not None:
            # Безпечне відключення попередніх з'єднань перед підключенням
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(self.on_btn_file_edit_clicked)

    # ------------------------------------------------------------------
    # Публічні обробники кнопок
    # ------------------------------------------------------------------

    def on_btn_file_open_clicked(self) -> None:
        """
        Відкрити G-код файл через діалог, завантажити у редактор та
        передати LinuxCNC.
        """
        print("DEBUG: on_btn_file_open_clicked ВИКЛИКАНО")
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Відкрити G-код файл",
            _DEFAULT_GCODE_DIR,
            _GCODE_FILTER,
        )
        print(f"DEBUG: вибраний файл: {file_path}")
        if not file_path:
            return

        try:
            self.cnc.open_program(file_path)
            self.load_file_into_editor(file_path)
        except Exception as exc:
            logger.error("Не вдалося завантажити файл: %s", exc)

    def on_btn_file_save_as_clicked(self) -> None:
        """
        Зберегти поточний вміст редактора у новий файл і передати його
        у LinuxCNC.

        Заблоковано якщо інтерпретатор зайнятий або редактор порожній.
        """
        if not self.cnc.is_interpreter_idle():
            logger.warning("Save-as відхилено: інтерпретатор зайнятий")
            return

        content = self._get_editor_content()
        if not content.strip():
            logger.warning("Save-as відхилено: редактор порожній")
            return

        last_file   = self.cnc.get_last_file()
        initial_dir = os.path.dirname(last_file) if last_file else os.path.expanduser("~")

        new_path, _ = QFileDialog.getSaveFileName(
            None, "Зберегти G-код як…", initial_dir, _SAVE_FILTER
        )
        if not new_path:
            return

        if not new_path.endswith(_GCODE_EXTENSIONS):
            new_path += _FALLBACK_EXTENSION

        try:
            self._write(new_path, content)
            self.cnc.open_program(new_path)
            # Оновлюємо мітку імені файлу
            self._set_label("lbl_filename", os.path.basename(new_path))
            logger.debug("Збережено та завантажено: %s", new_path)
        except Exception as exc:
            logger.error("Помилка збереження: %s", exc)

    def on_btn_file_reload_clicked(self) -> None:
        """
        Перезавантажити останній файл з диска у редактор та LinuxCNC.

        Заблоковано якщо файл не записаний або станок зайнятий.
        """
        last_file = self.cnc.get_last_file()
        if not last_file or not self.cnc.is_interpreter_idle():
            logger.warning("Reload неможливий: файл не знайдено або станок працює")
            return

        try:
            self.cnc.open_program(last_file)
            self.load_file_into_editor(last_file)
            self.cnc.reload_needed = False
            self._set_reload_style("")
            logger.debug("Файл перезавантажено: %s", os.path.basename(last_file))
        except Exception as exc:
            logger.error("Помилка перезавантаження: %s", exc)

    def on_btn_file_edit_clicked(self) -> None:
        """
        Відкрити поточний файл у зовнішньому текстовому редакторі.

        Шукає перший доступний редактор із :data:`_CANDIDATE_EDITORS`.
        Встановлює прапорець reload_needed і попереджувальний стиль на
        кнопці Reload.

        Заблоковано якщо файл не записаний або станок зайнятий.
        """
        last_file = self.cnc.get_last_file()
        if not last_file or not self.cnc.is_interpreter_idle():
            return

        editor = self._find_editor()
        if editor is None:
            logger.warning("Жоден редактор не знайдено: %s", _CANDIDATE_EDITORS)
            return

        subprocess.Popen([editor, last_file])
        self.cnc.reload_needed = True
        self._set_reload_style(self.STYLE_GCODE_WARN)
        logger.debug("Файл відкрито в %s: %s", editor, last_file)

    # ------------------------------------------------------------------
    # Публічний метод завантаження у редактор
    # ------------------------------------------------------------------

    def load_file_into_editor(self, filepath: str) -> None:
        """
        Зчитати *filepath* з диска і передати вміст у ``list_gcode_edit``
        (GCodeEditorWidget).

        Також оновлює мітки lbl_filename та lbl_progress_percent.

        Це єдина точка входу для завантаження файлу в UI-редактор.
        Викликається як із обробників кнопок цього класу, так і з
        GCodeEditorManager (через делегування у update()).

        Args:
            filepath: Абсолютний шлях до G-код файлу.
        """
        if not os.path.isfile(filepath):
            logger.error("Файл не знайдено: %s", filepath)
            return

        try:
            text = self._read_text(filepath)
        except OSError as exc:
            logger.error("Помилка читання файлу: %s", exc)
            return

        # ── Передати текст у GCodeEditorWidget (list_gcode_edit) ──────
        editor = self._get_editor_widget()
        if editor is not None:
            # load_text() зупиняє debounce-таймер, тому не тригерить auto-save
            editor.load_text(text)
        else:
            logger.warning(
                "Віджет list_gcode_edit не знайдено або не має методу load_text(). "
                "Переконайтесь, що GCodeEditorWidget правильно встановлено у .ui файлі."
            )

        # ── Оновити допоміжні мітки ───────────────────────────────────
        self._set_label("lbl_filename",        os.path.basename(filepath))
        self._set_label("lbl_progress_percent", "0%")

        logger.debug(
            "G-код завантажено у list_gcode_edit: %s (%d символів)",
            os.path.basename(filepath),
            len(text),
        )

    # ------------------------------------------------------------------
    # Пряме посилання на редактор (встановлюється з HandlerClass)
    # ------------------------------------------------------------------

    def set_editor_widget(self, editor_widget) -> None:
        """
        Зберегти пряме посилання на GCodeEditorWidget.

        Викликати з HandlerClass.initialized__() після створення
        GCodeEditorManager:
            self.file_manager.set_editor_widget(self.editor_manager._editor)

        Гарантує що FileManager завжди пише в той самий екземпляр
        що відображається на екрані, незалежно від того як
        GCodeEditorManager змонтував контейнер у layout.
        """
        self._editor_widget = editor_widget
        logger.debug("FileManager: editor widget зареєстровано: %s", type(editor_widget).__name__)

    # ------------------------------------------------------------------
    # Приватні хелпери – доступ до редактора
    # ------------------------------------------------------------------

    def _get_editor_widget(self):
        """
        Повернути GCodeEditorWidget.

        Пріоритет:
          1. Пряме посилання через set_editor_widget() — найнадійніший спосіб.
          2. Fallback: widgets.list_gcode_edit (якщо set_editor_widget
             ще не було викликано).
        """
        # 1. Пряме посилання
        direct = getattr(self, "_editor_widget", None)
        if direct is not None:
            return direct

        # 2. Fallback через widgets
        widget = getattr(self.widgets, "list_gcode_edit", None)
        if widget is None:
            return None
        if hasattr(widget, "load_text"):
            return widget
        inner = getattr(widget, "editor", None)
        if inner is not None and hasattr(inner, "load_text"):
            return inner
        return None

    def _get_editor_content(self) -> str:
        """Повернути поточний текст із редактора або порожній рядок."""
        editor = self._get_editor_widget()
        if editor is None:
            return ""
        # QPlainTextEdit.toPlainText() → str
        return editor.toPlainText() if hasattr(editor, "toPlainText") else ""

    # ------------------------------------------------------------------
    # Приватні хелпери – віджети
    # ------------------------------------------------------------------

    def _set_label(self, attr: str, text: str) -> None:
        """Встановити текст на мітці, якщо вона існує."""
        label = getattr(self.widgets, attr, None)
        if label is not None:
            label.setText(text)

    def _set_reload_style(self, stylesheet: str) -> None:
        """Застосувати stylesheet до кнопки Reload, якщо вона існує."""
        btn = getattr(self.widgets, "btn_file_reload", None)
        if btn is not None:
            btn.setStyleSheet(stylesheet)

    # ------------------------------------------------------------------
    # Приватні хелпери – файловий I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _read_text(filepath: str) -> str:
        """Прочитати файл повністю та повернути рядок."""
        with open(filepath, encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _write(filepath: str, content: str) -> None:
        """Записати *content* у *filepath*."""
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(content)

    @staticmethod
    def _find_editor() -> str | None:
        """
        Повернути назву першого доступного редактора із
        :data:`_CANDIDATE_EDITORS`, або ``None`` якщо жоден не знайдено.
        """
        for editor in _CANDIDATE_EDITORS:
            result = subprocess.call(
                ["which", editor],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result == 0:
                return editor
        return None

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cnc={self.cnc!r})"