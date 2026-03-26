# logic/managers/project/project_manager.py
"""
ProjectManager – фасад менеджера проектів LinuxCNC.

Підключення:
    pm = ProjectManager(widgets)
    pm.connect_buttons()

Очікувані імена віджетів у .ui:
    btn_open_project, btn_create_new_project, btn_clone_repository,
    btn_property_project, text_edit_search_project, tree_view_project,
    line, line_3, lbl_project_name,
    txt_project_name, txt_author, txt_created, txt_last_modified
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
    DEFAULT_OPEN_FILE, PROJECTS_ROOT, PROJECT_ROOT_FILES,
    PROJECT_STRUCTURE, STYLE_MENU,
)
from .project_dialogs    import _DeleteProjectDialog, _NewProjectDialog, _OpenProjectDialog
from .project_file_ops   import (
    build_project_tree_context_menu,
    on_new_file, on_open_file, on_rename, on_delete_file,
    clipboard_op, on_paste, show_error, unique_path,
)
from .project_tree       import setup_project_tree, rebuild_fs_model
from .project_watcher    import (
    clear_project_info, flush_modified_update,
    load_project_info, on_dir_changed, on_file_changed,
    start_watcher, stop_watcher, write_config,
)

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class ProjectManager:
    """
    Управляє станом панелі Project Manager.
    Делегує файлові операції, watcher і дерево до окремих модулів.
    """

    def __init__(self, widgets: object) -> None:
        self.widgets = widgets
        self._current_project: Optional[Path] = None
        self._w = lambda name: getattr(self.widgets, name, None)

        # FileWatcher
        self._watcher = QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self._on_project_dir_changed)
        self._watcher.fileChanged.connect(self._on_project_file_changed)

        # Debounce last_modified
        self._modified_timer = QTimer()
        self._modified_timer.setSingleShot(True)
        self._modified_timer.setInterval(2000)
        self._modified_timer.timeout.connect(self._flush_modified_update)

        setup_project_tree(self)
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
        for name in ("btn_open_project", "btn_create_new_project",
                     "btn_clone_repository", "text_edit_search_project",
                     "line", "line_3"):
            w = self._w(name)
            if w:
                w.setVisible(True)

        tree = self._w("tree_view_project")
        if tree is not None:
            tree.setVisible(True)
        self._project_tree.hide()

        stop_watcher(self)

        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.clear_editor()

        ldm = getattr(self, "_logger_display_manager", None)
        if ldm is not None:
            ldm.set_project(None)

        clear_project_info(self)
        self._populate_project_list()

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

    def _open_project(self, project_path: Path) -> None:
        if not project_path.is_dir():
            logger.error("Проєкт не знайдено: %s", project_path)
            return

        self._current_project = project_path

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

        rebuild_fs_model(self, project_path)
        self._project_tree.show()
        self._project_tree.raise_()

        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.set_project_active(True)

        pl = getattr(self, "_project_logger", None)
        if pl is not None:
            pl.set_project(project_path)

        ldm = getattr(self, "_logger_display_manager", None)
        if ldm is not None:
            ldm.set_project(project_path)

        default_file = project_path / DEFAULT_OPEN_FILE
        if default_file.is_file():
            self._on_open_file(default_file, read_only=True)

        load_project_info(self, project_path)
        start_watcher(self, project_path)

        logger.info("Відкрито проєкт: %s", project_path.name)

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
            for folder, files in PROJECT_STRUCTURE.items():
                folder_path = path / folder
                folder_path.mkdir()
                for fname in files:
                    (folder_path / fname).touch()
            for fname in PROJECT_ROOT_FILES:
                (path / fname).touch()
            write_config(path, created=True)
            if dlg.init_repo:
                self._init_git_repo(path)
            self._open_project(path)
            logger.info("Створено проєкт: %s", name)
        except FileExistsError:
            show_error(self, _tr(f'Проєкт "{name}" вже існує.'))
        except Exception as exc:
            show_error(self, _tr(f"Помилка створення проєкту: {exc}"))

    def _on_clone_repository(self) -> None:
        show_error(self, _tr("Клонування репозиторію ще не реалізовано."))

    def _on_property_menu(self) -> None:
        btn = self._w("btn_property_project")
        if btn is None:
            return
        menu = QMenu()
        menu.setStyleSheet(STYLE_MENU)
        menu.addAction(_tr("Відкрити проєкт"),  self._on_open_project)
        menu.addAction(_tr("Новий проєкт"),     self._on_create_project)
        menu.addSeparator()
        act_del = menu.addAction(_tr("Видалити проєкт..."))
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
            logger.info("Видалено проєкт: %s", name)
        except Exception as exc:
            show_error(self, _tr(f"Помилка видалення: {exc}"))
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
    # Пошук
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self._list_proxy.setFilterFixedString(text)

    # ------------------------------------------------------------------
    # Контекстні меню дерев
    # ------------------------------------------------------------------

    def _on_tree_context_menu(self, pos) -> None:
        pass  # список проектів — без файлових операцій

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

    def _on_project_tree_double_click(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        src_index     = self._tree_proxy.mapToSource(index)
        file_path_str = self._fs_model.filePath(src_index)
        if not file_path_str:
            return
        path = Path(file_path_str)
        if path.is_file():
            self._on_open_file(path, read_only=True)

    def _on_project_tree_context_menu(self, pos) -> None:
        build_project_tree_context_menu(self, pos)

    # ------------------------------------------------------------------
    # Делегати файлових операцій
    # ------------------------------------------------------------------

    def _on_new_file(self, context_path: Optional[Path]) -> None:
        on_new_file(self, context_path)

    def _on_open_file(self, path: Path, read_only: bool) -> None:
        on_open_file(self, path, read_only)

    def _on_rename(self, path: Path, index: QModelIndex) -> None:
        on_rename(self, path, index)

    def _on_delete_file(self, path: Path) -> None:
        on_delete_file(self, path)

    def _clipboard_op(self, path: Path, cut: bool) -> None:
        clipboard_op(self, path, cut)

    def _on_paste(self, context_path: Optional[Path]) -> None:
        on_paste(self, context_path)

    def _unique_path(self, dest: Path) -> Path:
        return unique_path(dest)

    # ------------------------------------------------------------------
    # Делегати watcher і config
    # ------------------------------------------------------------------

    def _start_watcher(self, project_path: Path) -> None:
        start_watcher(self, project_path)

    def _stop_watcher(self) -> None:
        stop_watcher(self)

    def _on_project_dir_changed(self, path: str) -> None:
        on_dir_changed(self, path)

    def _on_project_file_changed(self, path: str) -> None:
        on_file_changed(self, path)

    def _flush_modified_update(self) -> None:
        flush_modified_update(self)

    def _write_config(self, project_path: Path, created: bool = False) -> None:
        write_config(project_path, created)

    def _load_project_info(self, project_path: Path) -> None:
        load_project_info(self, project_path)

    def _clear_project_info(self) -> None:
        clear_project_info(self)

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

    # ------------------------------------------------------------------
    # "Open or Create" посилання після видалення
    # ------------------------------------------------------------------

    def _show_open_or_create_link(self) -> None:
        from PyQt5.QtWidgets import QTreeView
        self._list_model.clear()
        item = QStandardItem(_tr("Відкрийте або Створіть Новий Проєкт"))
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

    def _rebuild_fs_model(self, project_path: Path) -> None:
        rebuild_fs_model(self, project_path)

    def _setup_tree(self) -> None:
        setup_project_tree(self)

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
        from PyQt5.QtCore    import QFileInfo
        return QFileIconProvider().icon(QFileIconProvider.Folder)

    def _show_error(self, message: str) -> None:
        show_error(self, message)

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}"
                f"(project={self._current_project!r})")
