# logic/managers/project/project_manager.py
"""
ProjectManager – фасад менеджера проектів LinuxCNC.

Проект = папка з одним файлом програми (<project_name>.parl).
Дерево файлів проекту відсутнє — файл одразу відкривається в редакторі.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from PyQt5.QtCore    import QCoreApplication, QFileSystemWatcher, QModelIndex, Qt, QTimer
from PyQt5.QtGui     import QColor, QFont, QStandardItem
from PyQt5.QtWidgets import QDialog, QMenu, QMessageBox

from .project_constants  import (
    PROGRAM_EXT, PROJECTS_ROOT, STYLE_MENU,
)
from .project_dialogs    import _DeleteProjectDialog, _NewProjectDialog, _OpenProjectDialog
from .project_watcher    import (
    clear_project_info, create_project_meta, delete_project_meta,
    flush_modified_update, get_project_id, init_projects_table,
    load_project_info, on_dir_changed, on_file_changed,
    start_watcher, stop_watcher, update_last_modified,
)

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class ProjectManager:
    """
    Управляє станом панелі Project Manager.
    Проект містить один файл програми — відкривається одразу в редакторі.
    """

    def __init__(self, widgets: object) -> None:
        self.widgets = widgets
        self._current_project: Optional[Path] = None
        self._current_project_id: Optional[str] = None
        self._current_author: str = ""
        self._w = lambda name: getattr(self.widgets, name, None)
        self._cnc = None

        # FileWatcher
        self._watcher = QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self._on_project_dir_changed)
        self._watcher.fileChanged.connect(self._on_project_file_changed)

        # Debounce last_modified
        self._modified_timer = QTimer()
        self._modified_timer.setSingleShot(True)
        self._modified_timer.setInterval(2000)
        self._modified_timer.timeout.connect(self._flush_modified_update)

        self._setup_project_list()
        self._set_initial_state()

    # ------------------------------------------------------------------
    # Підключення кнопок
    # ------------------------------------------------------------------

    def connect_buttons(self) -> None:
        self._connect(self._w("btn_open_project"),       self._on_open_project)
        self._connect(self._w("btn_create_new_project"), self._on_create_project)
        self._connect(self._w("btn_clone_repository"),   self._on_clone_repository)
        self._connect(self._w("btn_property_project"),   self._on_property_menu)

        search = self._w("text_edit_search_project")
        if search is not None:
            if hasattr(search, "textChanged") and hasattr(search, "text"):
                search.textChanged.connect(self._on_search_changed)
            elif hasattr(search, "textChanged"):
                search.textChanged.connect(
                    lambda: self._on_search_changed(search.toPlainText()))

    @staticmethod
    def _connect(btn, handler) -> None:
        if btn is None:
            return
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(handler)

    # ------------------------------------------------------------------
    # Стан UI
    # ------------------------------------------------------------------

    def _set_initial_state(self) -> None:
        self._current_project = None
        self._current_project_id = None
        for name in ("btn_open_project", "btn_create_new_project",
                     "btn_clone_repository", "text_edit_search_project",
                     "line", "line_3"):
            w = self._w(name)
            if w:
                w.setVisible(True)

        tree = self._w("tree_view_project")
        if tree is not None:
            tree.setVisible(True)

        stop_watcher(self)

        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.clear_editor()

        ldm = getattr(self, "_logger_display_manager", None)
        if ldm is not None:
            ldm.set_project(None, None)

        pl = getattr(self, "_project_logger", None)
        if pl is not None:
            pl.set_project(None)

        tp = getattr(self, "_tool_panel", None)
        if tp is not None:
            tp.set_project(None)

        clear_project_info(self)
        self._populate_project_list()

    def _setup_project_list(self) -> None:
        """Ініціалізувати модель списку проектів."""
        from PyQt5.QtCore import QSortFilterProxyModel
        from PyQt5.QtGui  import QStandardItemModel

        tree = self._w("tree_view_project")
        if tree is not None:
            from PyQt5.QtWidgets import QAbstractItemView
            tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tree.doubleClicked.connect(self._on_tree_double_click)

        self._list_model = QStandardItemModel()
        self._list_proxy = QSortFilterProxyModel()
        self._list_proxy.setSourceModel(self._list_model)
        self._list_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._list_proxy.setFilterKeyColumn(0)

        if tree is not None:
            tree.setModel(self._list_proxy)
            tree.setHeaderHidden(True)
            tree.setRootIsDecorated(False)

    def _populate_project_list(self) -> None:
        self._list_model.clear()
        PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
        for entry in sorted(PROJECTS_ROOT.iterdir()):
            if entry.is_dir():
                item = QStandardItem(entry.name)
                item.setData(str(entry), Qt.UserRole)
                item.setEditable(False)
                item.setIcon(self._folder_icon())
                self._list_model.appendRow(item)

    def _program_file(self, project_path: Path) -> Path:
        """Шлях до файлу програми проекту."""
        return project_path / f"{project_path.name}{PROGRAM_EXT}"

    def _open_project(self, project_path: Path) -> None:
        if not project_path.is_dir():
            logger.error("Проєкт не знайдено: %s", project_path)
            return

        self._current_project = project_path

        # Отримати id проекту з БД (створити запис якщо немає)
        load_project_info(self, project_path)
        project_id = get_project_id(project_path.name)
        self._current_project_id = project_id

        for name in ("btn_open_project", "btn_create_new_project",
                     "btn_clone_repository", "text_edit_search_project",
                     "line", "line_3"):
            w = self._w(name)
            if w:
                w.setVisible(False)

        tree = self._w("tree_view_project")
        if tree is not None:
            tree.setVisible(False)

        lbl = self._w("lbl_project_name")
        if lbl is not None:
            lbl.setText(project_path.name)

        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.set_project_active(True)
            if hasattr(em, "set_project"):
                em.set_project(project_path)

        pl = getattr(self, "_project_logger", None)
        if pl is not None:
            pl.set_project(project_id)

        ldm = getattr(self, "_logger_display_manager", None)
        if ldm is not None:
            ldm.set_project(project_id, project_path.name)

        tp = getattr(self, "_tool_panel", None)
        if tp is not None:
            tp.set_project(project_id)

        # Відкрити файл програми в режимі редагування
        program = self._program_file(project_path)
        if program.is_file():
            self._open_program_in_editor(program)

        start_watcher(self, project_path)
        logger.info("Відкрито проєкт: %s", project_path.name)

    def _open_program_in_editor(self, path: Path) -> None:
        """Відкрити файл програми в редакторі в режимі редагування."""
        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.load_file(str(path), read_only=False)
            return
        cb = getattr(self, "_open_file_callback", None)
        if cb:
            cb(str(path), False)

    # ------------------------------------------------------------------
    # Обробники кнопок
    # ------------------------------------------------------------------

    def _on_open_project(self) -> None:
        dlg = _OpenProjectDialog(self._w("tree_view_project"))
        if dlg.exec_() == QDialog.Accepted and dlg.selected_path:
            self._open_project(dlg.selected_path)

    def _on_create_project(self) -> None:
        dlg = _NewProjectDialog(self._w("tree_view_project"))
        if dlg.exec_() != QDialog.Accepted:
            return
        name = dlg.project_name
        path = PROJECTS_ROOT / name
        try:
            path.mkdir(parents=True, exist_ok=False)
            # Створити єдиний файл програми
            program = path / f"{name}{PROGRAM_EXT}"
            program.touch()
            create_project_meta(name, self._current_author)
            if dlg.init_repo:
                self._init_git_repo(path)
            self._open_project(path)
            logger.info("Створено проєкт: %s", name)
        except FileExistsError:
            self._show_error(_tr(f'Проєкт "{name}" вже існує.'))
        except Exception as exc:
            self._show_error(_tr(f"Помилка створення проєкту: {exc}"))

    def _on_clone_repository(self) -> None:
        self._show_error(_tr("Клонування репозиторію ще не реалізовано."))

    def _on_property_menu(self) -> None:
        btn = self._w("btn_property_project")
        if btn is None:
            return
        menu = QMenu()
        menu.setStyleSheet(STYLE_MENU)
        menu.addAction(_tr("Open project"),  self._on_open_project)
        menu.addAction(_tr("New project"),     self._on_create_project)
        menu.addSeparator()
        act_del = menu.addAction(_tr("Delete project..."))
        act_del.setEnabled(self._current_project is not None)
        act_del.triggered.connect(self._on_delete_project)
        menu.exec_(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_delete_project(self) -> None:
        if self._current_project is None:
            return
        name = self._current_project.name
        dlg  = _DeleteProjectDialog(name, self._w("tree_view_project"))
        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            pl = getattr(self, "_project_logger", None)
            if pl is not None:
                pl.detach_project(name)
            shutil.rmtree(self._current_project)
            delete_project_meta(name)
            logger.info("Видалено проєкт: %s", name)
        except Exception as exc:
            self._show_error(_tr(f"Помилка видалення: {exc}"))
            return

        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.clear_editor()

        lbl = self._w("lbl_project_name")
        if lbl is not None:
            lbl.setText("Project")

        self._set_initial_state()
        self._show_open_or_create_link()

    # ------------------------------------------------------------------
    # Пошук і подвійний клік по списку проектів
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self._list_proxy.setFilterFixedString(text)

    def _on_tree_double_click(self, index: QModelIndex) -> None:
        src_index = self._list_proxy.mapToSource(index)
        item = self._list_model.itemFromIndex(src_index)
        if item is None:
            return
        user_data = item.data(Qt.UserRole)
        if user_data == "__link__":
            return
        path = Path(user_data) if user_data else None
        if path and path.is_dir():
            self._open_project(path)

    # ------------------------------------------------------------------
    # Контекстне меню редактора — Insert Variable / Teach Point
    # ------------------------------------------------------------------

    def build_editor_context_menu(self, menu: QMenu) -> None:
        """
        Розширити контекстне меню редактора коду.
        Викликається з editor_manager при побудові контекстного меню.
        """
        if self._current_project is None:
            return
        menu.addSeparator()
        menu.addAction(_tr("Insert Variable"), self._on_insert_variable)
        menu.addAction(_tr("Teach Point"),     self._on_teach_point)

    def _on_insert_variable(self) -> None:
        """Вставити шаблон оголошення змінної."""
        em = getattr(self, "_editor_manager", None)
        if em is None:
            return
        em.insert_text_at_cursor("[name] = [value]")

    def _on_teach_point(self) -> None:
        """Вставити поточні координати з контролера."""
        em = getattr(self, "_editor_manager", None)
        if em is None:
            return
        cnc = self._cnc
        if cnc is None:
            self._show_error(_tr("Machine controller not available"))
            return
        try:
            pos = cnc.get_position()
            coords = " ".join(
                f"{axis}{val:.3f}" for axis, val in zip("XYZABC", pos)
                if val is not None
            )
            em.insert_text_at_cursor(coords)
        except Exception as exc:
            self._show_error(_tr(f"Failed to read position: {exc}"))

    # ------------------------------------------------------------------
    # Делегати watcher
    # ------------------------------------------------------------------

    def _on_project_dir_changed(self, path: str) -> None:
        on_dir_changed(self, path)

    def _on_project_file_changed(self, path: str) -> None:
        on_file_changed(self, path)

    def _flush_modified_update(self) -> None:
        flush_modified_update(self)

    # ------------------------------------------------------------------
    # Реєстрація залежностей
    # ------------------------------------------------------------------

    def set_open_file_callback(self, callback) -> None:
        self._open_file_callback = callback

    def set_editor_manager(self, editor_manager) -> None:
        self._editor_manager = editor_manager

    def set_project_logger(self, project_logger) -> None:
        self._project_logger = project_logger

    def set_logger_display_manager(self, logger_display_manager) -> None:
        self._logger_display_manager = logger_display_manager

    def set_tool_panel(self, tool_panel) -> None:
        self._tool_panel = tool_panel

    def set_current_user(self, login: str) -> None:
        """Встановити автора для нових проектів (login активного користувача)."""
        self._current_author = login

    def set_machine_controller(self, cnc) -> None:
        """Встановити MachineController для Teach Point."""
        self._cnc = cnc

    # ------------------------------------------------------------------
    # "Open or Create" посилання після видалення
    # ------------------------------------------------------------------

    def _show_open_or_create_link(self) -> None:
        from PyQt5.QtWidgets import QTreeView
        self._list_model.clear()
        item = QStandardItem(_tr("Open or Create a New Project"))
        item.setForeground(QColor("#FE5C0D"))
        font = item.font()
        font.setPixelSize(14)
        font.setUnderline(True)
        item.setFont(font)
        item.setEditable(False)
        item.setData("__link__", Qt.UserRole)
        self._list_model.appendRow(item)

        tree: QTreeView = self._w("tree_view_project")
        if tree:
            def _on_link_clicked(index: QModelIndex):
                src = self._list_proxy.mapToSource(index)
                it  = self._list_model.itemFromIndex(src)
                if it and it.data(Qt.UserRole) == "__link__":
                    self._populate_project_list()
                    try:
                        tree.clicked.disconnect(_on_link_clicked)
                    except TypeError:
                        pass
            tree.clicked.connect(_on_link_clicked)

    # ------------------------------------------------------------------
    # Допоміжні
    # ------------------------------------------------------------------

    @staticmethod
    def _init_git_repo(path: Path) -> None:
        import subprocess
        try:
            subprocess.run(["git", "init", str(path)],
                           check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            logger.info("git init: %s", path)
        except Exception as exc:
            logger.warning("git init не вдався: %s", exc)

    @staticmethod
    def _folder_icon():
        from PyQt5.QtWidgets import QFileIconProvider
        return QFileIconProvider().icon(QFileIconProvider.Folder)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(
            self._w("tree_view_project"), _tr("Error"), message)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}"
                f"(project={self._current_project!r})")