# logic/managers/project_manager.py
"""
ProjectManager – менеджер проектів LinuxCNC.

Класи:
  _NewProjectDialog    – модальний діалог створення нового проекту
  _OpenProjectDialog   – модальний діалог відкриття проекту
  _DeleteProjectDialog – модальний діалог підтвердження видалення
  ProjectManager       – фасад: управляє станом панелі project manager

Підключення до UI:
  У HandlerClass.initialized__() створити екземпляр ProjectManager
  і викликати connect_buttons().

Очікувані імена віджетів у .ui файлі:
  btn_open_project, btn_create_new_project, btn_clone_repository,
  btn_property_project, text_edit_search_project,
  tree_view_project, line, line_3
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import (
    QDir, QModelIndex, Qt, QSortFilterProxyModel, pyqtSignal,
)
from PyQt5.QtGui  import QColor, QFont, QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QAbstractItemView, QAction, QCheckBox, QDialog,
    QFileSystemModel, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QTreeView,
    QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константи
# ---------------------------------------------------------------------------

_PROJECTS_ROOT = Path.home() / "ProjectLinuxCNC"

# Структура нового проекту — папки та їх файли за замовчуванням
_PROJECT_STRUCTURE: dict[str, list[str]] = {
    "src":  ["program.txt"],    # сирці (редагує користувач)
    "bin":  ["main.parl"],      # виконавчі файли (генерує система)
    "data": ["points.xml"],     # точки та параметри
    "logs": ["execution.json"],  # звіти про виконання
}
_PROJECT_ROOT_FILES = ["config.ini"]          # файли в корені проекту
_DEFAULT_OPEN_FILE  = Path("src") / "program.txt"  # відкривається при відкритті проекту
_EDITABLE_EXTS      = (".txt", ".ini", ".xml", ".json", ".parl")  # типи що можна редагувати
_HIDDEN_FOLDERS     = {"bin", "logs"}         # папки що існують але не відображаються

_STYLE_DIALOG = """
QDialog          { background:#121212; color:#FFFFFF; }
QLabel           { color:#F1F1F1; }
QLineEdit        { background:#2D2D2D; color:#FFFFFF;
                   border:1px solid #333333; border-radius:10px;
                   padding:4px 8px; }
QLineEdit:focus  { border-color:#FE5C0D; }
QLineEdit[invalid="true"] { border-color:#FF0000; }
QPushButton      { background:#333333; color:#F1F1F1; border:none;
                   border-radius:10px; padding:5px 16px; min-height:28px; }
QPushButton:hover    { background:#5B5B5B; }
QPushButton:disabled { background:#1A1A1A; color:#9E9E9E; }
QPushButton#btn_confirm { background:#FE5C0D; color:#FFFFFF; font-weight:bold; }
QPushButton#btn_confirm:hover    { background:#FF7533; }
QPushButton#btn_confirm:disabled { background:#333333; color:#9E9E9E; }
QPushButton#btn_delete_confirm   { background:#FF0000; color:#FFFFFF; font-weight:bold; }
QPushButton#btn_delete_confirm:hover    { background:#F50000; }
QPushButton#btn_delete_confirm:disabled { background:#333333; color:#9E9E9E; }
QCheckBox        { color:#F1F1F1; spacing:6px; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #333333;
                        border-radius:10px; background:#2D2D2D; }
QCheckBox::indicator:checked { background:#FE5C0D; border-color:#FEAE0D; }
QTreeView        { background:#161616; color:#F1F1F1;
                   border:1px solid #333333; border-radius:10px; }
QTreeView::item:selected { background:#FE5C0D; color:#FFFFFF; }
QTreeView::item:hover    { background:#2D2D2D; }
"""

_STYLE_TREE = """
QTreeView        { background:#161616; color:#F1F1F1; border:none;
                   outline:none; font-size:16px; padding: 10px;}
QTreeView::item  { padding:3px 4px; }
QTreeView::item:selected { background:#FE5C0D; color:#FFFFFF; }
QTreeView::item:hover    { background:#2D2D2D; color:#FFFFFF; }
QTreeView::branch { background:#161616; }
"""

_STYLE_MENU = (
    "QMenu{background:#1A1A1A;color:#F1F1F1;"
    "border:1px solid #333333;border-radius:10px;}"
    "QMenu::item{padding:5px 20px 5px 12px;}"
    "QMenu::item:selected{background:#FE5C0D;color:#FFFFFF;}"
    "QMenu::separator{height:1px;background:#333333;margin:3px 0;}"
)


# ===========================================================================
# 1. Діалог створення нового проекту
# ===========================================================================

class _NewProjectDialog(QDialog):
    """Модальний діалог для створення нового проекту."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новий проєкт")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setStyleSheet(_STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # Назва проекту
        root.addWidget(QLabel("Назва проєкту:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("my_project")
        self._name_edit.textChanged.connect(self._validate)
        root.addWidget(self._name_edit)

        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color:#FF6161; font-size:12px;")
        root.addWidget(self._lbl_error)

        # Опція ініціалізації репозиторію
        self._chk_repo = QCheckBox("Ініціалізувати git-репозиторій")
        root.addWidget(self._chk_repo)

        root.addStretch()

        # Кнопки
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton("Скасувати")
        self._btn_cancel.setAutoDefault(False)
        self._btn_cancel.setDefault(False)
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_create = QPushButton("Створити")
        self._btn_create.setObjectName("btn_confirm")
        self._btn_create.setAutoDefault(False)
        self._btn_create.setDefault(False)
        self._btn_create.setEnabled(False)
        self._btn_create.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_create)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _validate(self) -> None:
        name = self._name_edit.text().strip()
        error = ""

        if not name:
            error = ""
        elif any(c in name for c in r'\/:*?"<>|'):
            error = "Назва містить недопустимі символи"
        elif (_PROJECTS_ROOT / name).exists():
            error = f'Проєкт "{name}" вже існує'

        self._lbl_error.setText(error)
        self._name_edit.setProperty("invalid", "true" if error else "")
        self._name_edit.style().unpolish(self._name_edit)
        self._name_edit.style().polish(self._name_edit)
        self._btn_create.setEnabled(bool(name) and not error)

    # ------------------------------------------------------------------

    @property
    def project_name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def init_repo(self) -> bool:
        return self._chk_repo.isChecked()


# ===========================================================================
# 2. Діалог відкриття проекту
# ===========================================================================

class _OpenProjectDialog(QDialog):
    """Діалог вибору існуючого проекту із /home/ProjectLinuxCNC."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Відкрити проєкт")
        self.setMinimumSize(400, 480)
        self.setModal(True)
        self.setStyleSheet(_STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 16, 16, 16)

        # Незмінний рядок шляху
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Шлях:"))
        lbl_path = QLineEdit(str(_PROJECTS_ROOT))
        lbl_path.setReadOnly(True)
        lbl_path.setStyleSheet("color:#9E9E9E; background:#161616;")
        path_row.addWidget(lbl_path)
        root.addLayout(path_row)

        # Дерево проектів (лише кореневі папки)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["Проєкти:"])
        self._tree  = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setStyleSheet(_STYLE_TREE)
        self._tree.setHeaderHidden(False)
        self._tree.setRootIsDecorated(False)   # без розгортання — лише папки
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.selectionModel().selectionChanged.connect(self._on_selection)
        self._tree.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._tree)

        # Кнопки
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Скасувати")
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)

        self._btn_ok = QPushButton("ОК")
        self._btn_ok.setObjectName("btn_confirm")
        self._btn_ok.setAutoDefault(False)
        self._btn_ok.setDefault(False)
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_ok)
        root.addLayout(btn_row)

        self._populate()

    # ------------------------------------------------------------------

    def _populate(self) -> None:
        self._model.removeRows(0, self._model.rowCount())
        if not _PROJECTS_ROOT.exists():
            return
        for entry in sorted(_PROJECTS_ROOT.iterdir()):
            if entry.is_dir():
                item = QStandardItem(entry.name)
                item.setData(str(entry), Qt.UserRole)
                item.setEditable(False)
                self._model.appendRow(item)

    def _on_selection(self) -> None:
        self._btn_ok.setEnabled(
            bool(self._tree.selectionModel().selectedIndexes())
        )

    def _on_double_click(self, _: QModelIndex) -> None:
        if self._btn_ok.isEnabled():
            self.accept()

    # ------------------------------------------------------------------

    @property
    def selected_path(self) -> Optional[Path]:
        indexes = self._tree.selectionModel().selectedIndexes()
        if not indexes:
            return None
        data = self._model.itemFromIndex(indexes[0]).data(Qt.UserRole)
        return Path(data) if data else None


# ===========================================================================
# 3. Діалог підтвердження видалення
# ===========================================================================

class _DeleteProjectDialog(QDialog):
    """Діалог підтвердження видалення проекту з ручним введенням назви."""

    def __init__(self, project_name: str, parent=None):
        super().__init__(parent)
        self._project_name = project_name
        self.setWindowTitle("Видалення проєкту")
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setStyleSheet(_STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # Попередження
        warn = QLabel(
            f'⚠  Ви збираєтесь <b>назавжди видалити</b> проєкт '
            f'<span style="color:#FF6161; font-size:12px;">{project_name}</span> '
            f'та весь його вміст з диска. Цю дію неможливо скасувати.'
        )
        warn.setTextFormat(Qt.RichText)
        warn.setWordWrap(True)
        root.addWidget(warn)

        # Поле підтвердження назви
        root.addWidget(QLabel(f'Введіть назву проєкту для підтвердження:'))
        self._confirm_edit = QLineEdit()
        self._confirm_edit.setPlaceholderText(project_name)
        self._confirm_edit.textChanged.connect(self._validate)
        root.addWidget(self._confirm_edit)

        # Чекбокс підтвердження
        self._chk = QCheckBox("Я розумію що видалення незворотнє")
        self._chk.stateChanged.connect(self._validate)
        root.addWidget(self._chk)

        root.addStretch()

        # Кнопки
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Скасувати")
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)

        self._btn_delete = QPushButton("Видалити назавжди")
        self._btn_delete.setObjectName("btn_delete_confirm")
        self._btn_delete.setAutoDefault(False)
        self._btn_delete.setDefault(False)
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_delete)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _validate(self) -> None:
        name_ok = self._confirm_edit.text().strip() == self._project_name
        chk_ok  = self._chk.isChecked()
        self._btn_delete.setEnabled(name_ok and chk_ok)


# ===========================================================================
# 4. ProjectManager – фасад
# ===========================================================================

# ===========================================================================
# Проксі-модель: приховування системних папок від користувача
# ===========================================================================

class _HiddenFoldersProxy(QSortFilterProxyModel):
    """
    Фільтрує QFileSystemModel: приховує вказані папки у дереві проекту.
    Папки існують на диску, але не відображаються користувачу.
    """

    def __init__(self, hidden: set[str], parent=None):
        super().__init__(parent)
        self._hidden = {name.lower() for name in hidden}

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        name  = model.fileName(index).lower()
        # Ховаємо лише папки зі списку — файли показуємо завжди
        if model.isDir(index) and name in self._hidden:
            return False
        return True


class ProjectManager:
    """
    Управляє станом панелі Project Manager.

    Підключення:
        pm = ProjectManager(widgets)
        pm.connect_buttons()
    """

    def __init__(self, widgets: object) -> None:
        self.widgets = widgets
        self._current_project: Optional[Path] = None

        # Ім'я атрибута у widgets → Qt-об'єкт
        self._w = lambda name: getattr(self.widgets, name, None)

        # Налаштування tree_view_project
        self._setup_tree()

        # Початковий стан — режим "вибору проекту"
        self._set_initial_state()

    # ------------------------------------------------------------------
    # Підключення кнопок
    # ------------------------------------------------------------------

    def connect_buttons(self) -> None:
        self._connect(self._w("btn_open_project"),        self._on_open_project)
        self._connect(self._w("btn_create_new_project"),  self._on_create_project)
        self._connect(self._w("btn_clone_repository"),    self._on_clone_repository)
        self._connect(self._w("btn_property_project"),    self._on_property_menu)

        # Пошук у реальному часі
        # text_edit_search_project може бути QLineEdit або QPlainTextEdit
        search = self._w("text_edit_search_project")
        if search is not None:
            if hasattr(search, "textChanged") and hasattr(search, "text"):
                # QLineEdit — textChanged(str)
                search.textChanged.connect(self._on_search_changed)
            elif hasattr(search, "textChanged"):
                # QPlainTextEdit / QTextEdit — textChanged без аргументу
                search.textChanged.connect(
                    lambda: self._on_search_changed(search.toPlainText())
                )

    @staticmethod
    def _connect(btn, handler) -> None:
        """Безпечно підключити сигнал кнопки до обробника."""
        if btn is None:
            return
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(handler)

    # ------------------------------------------------------------------
    # Ініціалізація дерева
    # ------------------------------------------------------------------

    def _setup_tree(self) -> None:
        # ── tree_view_project (з .ui) — лише для списку проектів ─────────
        tree: QTreeView = self._w("tree_view_project")
        if tree is not None:
            tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tree.setContextMenuPolicy(Qt.CustomContextMenu)
            tree.customContextMenuRequested.connect(self._on_tree_context_menu)
            tree.doubleClicked.connect(self._on_tree_double_click)

        # Модель списку проектів + proxy для пошуку
        self._list_model = QStandardItemModel()
        self._list_proxy = QSortFilterProxyModel()
        self._list_proxy.setSourceModel(self._list_model)
        self._list_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._list_proxy.setFilterKeyColumn(0)

        if tree is not None:
            tree.setModel(self._list_proxy)
            tree.setHeaderHidden(True)
            tree.setRootIsDecorated(False)

        # ── _project_tree — новий QTreeView лише для режиму відкритого проекту
        # Створюємо програмно і прикріплюємо до батька tree_view_project
        parent_widget = tree.parent() if tree is not None else None
        self._project_tree = QTreeView(parent_widget)
        self._project_tree.setGeometry(20, 70, 260, 520)
        self._project_tree.setStyleSheet(_STYLE_TREE)
        self._project_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._project_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._project_tree.customContextMenuRequested.connect(
            self._on_project_tree_context_menu
        )
        self._project_tree.doubleClicked.connect(self._on_project_tree_double_click)
        self._project_tree.setHeaderHidden(True)
        self._project_tree.setRootIsDecorated(True)
        self._project_tree.hide()   # прихований до відкриття проекту

        # Файлова модель для _project_tree
        self._fs_model = QFileSystemModel()
        self._fs_model.setReadOnly(False)
        # Фільтр: ховаємо папки bin/ і logs/ від користувача
        self._fs_model.setNameFilterDisables(False)
        self._project_tree.setModel(self._fs_model)
        for col in (1, 2, 3):
            self._project_tree.setColumnHidden(col, True)

        # Встановлюємо проксі-модель для приховування системних папок
        self._tree_proxy = _HiddenFoldersProxy(
            hidden=_HIDDEN_FOLDERS,
            parent=self._project_tree,
        )
        self._tree_proxy.setSourceModel(self._fs_model)
        self._project_tree.setModel(self._tree_proxy)

    def _rebuild_fs_model(self, project_path: Path) -> None:
        """
        Повністю замінити QFileSystemModel і _HiddenFoldersProxy.

        QFileSystemModel кешує структуру директорій і не скидає кеш
        навіть при setRootPath(""). Єдиний надійний спосіб отримати
        свіжу структуру — знищити стару модель і створити нову.
        Викликається при кожному відкритті проекту.
        """
        # Від'єднуємо стару модель від дерева перед знищенням
        self._project_tree.setModel(None)

        # Знищуємо стару модель і проксі (Qt видалить дочірні об'єкти)
        if hasattr(self, "_tree_proxy") and self._tree_proxy is not None:
            self._tree_proxy.setSourceModel(None)
            self._tree_proxy.deleteLater()
        if hasattr(self, "_fs_model") and self._fs_model is not None:
            self._fs_model.deleteLater()

        # Створюємо нову файлову модель
        self._fs_model = QFileSystemModel()
        self._fs_model.setReadOnly(False)
        self._fs_model.setNameFilterDisables(False)

        # Встановлюємо кореневий шлях до встановлення моделі на дерево
        self._fs_model.setRootPath(str(project_path))

        # Новий проксі для приховування системних папок
        self._tree_proxy = _HiddenFoldersProxy(
            hidden=_HIDDEN_FOLDERS,
            parent=self._project_tree,
        )
        self._tree_proxy.setSourceModel(self._fs_model)

        # Підключаємо нову модель до дерева
        self._project_tree.setModel(self._tree_proxy)
        for col in (1, 2, 3):
            self._project_tree.setColumnHidden(col, True)

        # Встановлюємо кореневий індекс через проксі
        src_root = self._fs_model.index(str(project_path))
        self._project_tree.setRootIndex(self._tree_proxy.mapFromSource(src_root))

    def _set_initial_state(self) -> None:
        """Показати елементи пошуку/кнопок і список проектів."""
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

        # Очистити редактор — без активного проекту жодні дії неможливі
        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.clear_editor()

        self._populate_project_list()

    def _populate_project_list(self) -> None:
        """Заповнити список проектів з _PROJECTS_ROOT."""
        self._list_model.clear()
        _PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

        for entry in sorted(_PROJECTS_ROOT.iterdir()):
            if entry.is_dir():
                item = QStandardItem(entry.name)
                item.setData(str(entry), Qt.UserRole)
                item.setEditable(False)
                item.setIcon(self._folder_icon())
                self._list_model.appendRow(item)

    # ------------------------------------------------------------------
    # Режим відкритого проекту
    # ------------------------------------------------------------------

    def _open_project(self, project_path: Path) -> None:
        """Перевести інтерфейс у режим відкритого проекту."""
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

        # Перебудовуємо модель з нуля — гарантовано свіжа структура
        self._rebuild_fs_model(project_path)
        self._project_tree.show()
        self._project_tree.raise_()

        # Повідомити editor_manager що проект активний
        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.set_project_active(True)

        # Повідомити ProjectLogger про новий активний проект
        pl = getattr(self, "_project_logger", None)
        if pl is not None:
            pl.set_project(project_path)

        # Відкрити src/program.txt у режимі читання за замовчуванням
        default_file = project_path / _DEFAULT_OPEN_FILE
        if default_file.is_file():
            self._on_open_file(default_file, read_only=True)

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
        path = _PROJECTS_ROOT / name
        try:
            path.mkdir(parents=True, exist_ok=False)

            # Створюємо підпапки та порожні файли у них
            for folder, files in _PROJECT_STRUCTURE.items():
                folder_path = path / folder
                folder_path.mkdir()
                for fname in files:
                    (folder_path / fname).touch()

            # Файли в корені проекту
            for fname in _PROJECT_ROOT_FILES:
                (path / fname).touch()

            if dlg.init_repo:
                self._init_git_repo(path)

            self._open_project(path)
            logger.info("Створено проєкт: %s", name)
        except FileExistsError:
            self._show_error(f'Проєкт "{name}" вже існує.')
        except Exception as exc:
            self._show_error(f"Помилка створення проєкту: {exc}")

    def _on_clone_repository(self) -> None:
        """Заглушка — реалізація залежить від вимог до git-інтеграції."""
        self._show_error("Клонування репозиторію ще не реалізовано.")

    def _on_property_menu(self) -> None:
        btn = self._w("btn_property_project")
        if btn is None:
            return

        menu = QMenu()
        menu.setStyleSheet(_STYLE_MENU)

        menu.addAction("Відкрити проєкт",  self._on_open_project)
        menu.addAction("Новий проєкт",   self._on_create_project)
        menu.addSeparator()

        act_del = menu.addAction("Видалити проєкт...")
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
            # Від'єднуємо logger ДО видалення — чекаємо flush черги,
            # потім обнуляємо шлях. Запобігає запису у вже видалену папку.
            pl = getattr(self, "_project_logger", None)
            if pl is not None:
                pl.detach_project(name)

            shutil.rmtree(self._current_project)
            logger.info("Видалено проєкт: %s", name)
        except Exception as exc:
            self._show_error(f"Помилка видалення: {exc}")
            return

        # Очистити редактор і заблокувати — до скидання стану UI
        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.clear_editor()

        # Скинути мітку назви проекту
        lbl = self._w("lbl_project_name")
        if lbl is not None:
            lbl.setText("Project")

        # Повернути до початкового стану
        self._set_initial_state()
        self._show_open_or_create_link()

    # ------------------------------------------------------------------
    # Пошук
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        """Фільтрувати список проектів у реальному часі."""
        self._list_proxy.setFilterFixedString(text)

    # ------------------------------------------------------------------
    # Контекстне меню дерева
    # ------------------------------------------------------------------

    def _on_tree_context_menu(self, pos) -> None:
        """Контекстне меню для tree_view_project (список проектів).
        У початковому режимі немає файлових операцій."""
        pass

    # ------------------------------------------------------------------
    # Операції з файлами
    # ------------------------------------------------------------------

    def _on_tree_double_click(self, index: QModelIndex) -> None:
        """Подвійний клік у tree_view_project (список проектів)."""
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
        """Подвійний клік у _project_tree — відкрити файл у режимі читання."""
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
        """Контекстне меню для _project_tree (режим відкритого проекту)."""
        if self._current_project is None:
            return

        proxy_index = self._project_tree.indexAt(pos)
        path: Optional[Path] = None
        index = proxy_index   # для rename (потрібен proxy index для edit())
        if proxy_index.isValid():
            src_index = self._tree_proxy.mapToSource(proxy_index)
            fp = self._fs_model.filePath(src_index)
            if fp:
                path = Path(fp)

        menu = QMenu(self._project_tree)
        menu.setStyleSheet(_STYLE_MENU)

        # Новий файл — завжди доступний
        act_new = menu.addAction("Новий файл")
        act_new.triggered.connect(lambda: self._on_new_file(path))
        menu.addSeparator()

        if path is not None:
            if path.is_file():
                menu.addAction("Відкрити (читання)").triggered.connect(
                    lambda: self._on_open_file(path, read_only=True))
                menu.addAction("Відкрити (редагування)").triggered.connect(
                    lambda: self._on_open_file(path, read_only=False))
                menu.addSeparator()

            # Перейменувати і Видалити — для файлів і папок
            menu.addAction("Перейменувати").triggered.connect(
                lambda: self._on_rename(path, index))
            menu.addAction("Видалити").triggered.connect(
                lambda: self._on_delete_file(path))
            menu.addSeparator()

            # Вирізати і Копіювати — для файлів і папок
            menu.addAction("Вирізати").triggered.connect(
                lambda: self._clipboard_op(path, cut=True))
            menu.addAction("Копіювати").triggered.connect(
                lambda: self._clipboard_op(path, cut=False))

        # Вставити — завжди видимий якщо є щось у буфері
        clipboard_src = getattr(self, "_clipboard_path", None)
        if clipboard_src is not None:
            if path is not None:
                menu.addSeparator()
            paste_label = (
                f"Вставити  [{clipboard_src.name}]"
                + ("  (вирізано)" if getattr(self, "_clipboard_cut", False) else "  (копія)")
            )
            menu.addAction(paste_label).triggered.connect(
                lambda: self._on_paste(path))

        menu.exec_(self._project_tree.viewport().mapToGlobal(pos))

    def _on_new_file(self, context_path: Optional[Path]) -> None:
        parent_dir = (
            context_path.parent if context_path and context_path.is_file()
            else (context_path if context_path and context_path.is_dir()
                  else self._current_project)
        )
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self._w("tree_view_project"), "Новий файл", "Назва файлу:"
        )
        if not ok or not name.strip():
            return
        # Copy Numbering — якщо файл з такою назвою вже існує
        dest = self._unique_path(parent_dir / name.strip())
        try:
            dest.touch()
        except Exception as exc:
            self._show_error(f"Помилка створення файлу: {exc}")

    def _on_open_file(self, path: Path, read_only: bool) -> None:
        """
        Відкрити файл проекту у редакторі коду.
        Використовує editor_manager напряму якщо зареєстровано,
        інакше — callback (зворотна сумісність).
        """
        em = getattr(self, "_editor_manager", None)
        if em is not None:
            em.load_file(str(path), read_only=read_only)
            return

        if hasattr(self, "_open_file_callback") and self._open_file_callback:
            self._open_file_callback(str(path), read_only)
        else:
            logger.warning("_on_open_file: немає editor_manager і callback")

    def set_open_file_callback(self, callback) -> None:
        """Fallback callback якщо editor_manager не зареєстровано."""
        self._open_file_callback = callback

    def set_editor_manager(self, editor_manager) -> None:
        """
        Зареєструвати GCodeEditorManager.
        Викликати з HandlerClass.initialized__() після його створення.
        """
        self._editor_manager = editor_manager

    def set_project_logger(self, project_logger) -> None:
        """
        Зареєструвати ProjectLogger для запису подій у JSON файл.
        Викликати з HandlerClass.initialized__() після його створення.
        """
        self._project_logger = project_logger

    def _on_rename(self, path: Path, index: QModelIndex) -> None:
        self._project_tree.edit(index)

    def _on_delete_file(self, path: Path) -> None:
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self._w("tree_view_project"),
            "Видалити файл",
            f'Видалити "{path.name}"?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

            # Якщо видалений файл зараз відкритий у редакторі — очищаємо
            em = getattr(self, "_editor_manager", None)
            if em is not None and em._current_file == str(path):
                em.clear_editor()

        except Exception as exc:
            self._show_error(f"Помилка видалення: {exc}")

    # ------------------------------------------------------------------
    # Copy Numbering — розумне перейменування при конфлікті
    # ------------------------------------------------------------------

    @staticmethod
    def _unique_path(dest: Path) -> Path:
        """
        Повернути унікальний шлях використовуючи стратегію Copy Numbering.

        Якщо *dest* не існує — повертає його без змін.
        Інакше додає числовий суфікс за патерном Windows/macOS:

          file.txt        → file (2).txt → file (3).txt → …
          report          → report (2)   → report (3)   → …
          archive.tar.gz  → archive (2).tar.gz → …

        Лічильник починається з 2 (як у Finder і Explorer) і
        збільшується поки не знайде вільне ім'я.
        """
        if not dest.exists():
            return dest

        # Розбиваємо ім'я: stem + суфікс (враховуємо .tar.gz тощо)
        name   = dest.name
        parent = dest.parent

        # Знаходимо перше розширення (або порожній рядок для папок)
        if dest.is_dir() or '.' not in name:
            stem, ext = name, ""
        else:
            # Path.stem/suffix не обробляє .tar.gz, тому шукаємо вручну
            dot_idx = name.index('.')
            stem    = name[:dot_idx]
            ext     = name[dot_idx:]   # ".tar.gz", ".txt", тощо

        counter = 2
        while True:
            candidate = parent / f"{stem} ({counter}){ext}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _clipboard_op(self, path: Path, cut: bool) -> None:
        """
        Запам'ятати файл/папку для подальшої вставки.
        Зберігаємо абсолютний шлях і режим (cut/copy).
        Фізичне переміщення або копіювання відбувається лише при Paste.
        """
        self._clipboard_path = path.resolve()
        self._clipboard_cut  = cut
        action = "Вирізано" if cut else "Скопійовано"
        logger.debug("%s: %s", action, self._clipboard_path)

    def _on_paste(self, context_path: Optional[Path]) -> None:
        """
        Вставити файл/папку зі збереженого буфера.

        Визначення папки-призначення:
          - клік на папку  → вставляємо всередину неї
          - клік на файл   → вставляємо в ту саму папку що й файл
          - порожнє місце  → корінь відкритого проекту

        При конфлікті імен використовується Copy Numbering:
          file.txt → file (2).txt → file (3).txt → …
        """
        src = getattr(self, "_clipboard_path", None)
        if src is None or not src.exists():
            self._show_error("Буфер порожній або файл більше не існує.")
            self._clipboard_path = None
            return

        # Визначаємо папку призначення
        if context_path is None:
            dest_dir = self._current_project
        elif context_path.is_dir():
            dest_dir = context_path
        else:
            dest_dir = context_path.parent

        # Перевірка збігу джерела і призначення:
        # — для Cut (переміщення) в ту саму папку — блокуємо, це no-op
        # — для Copy в ту саму папку — дозволяємо, Copy Numbering додасть суфікс
        base_dest = dest_dir / src.name
        if base_dest == src:
            if self._clipboard_cut:
                self._show_error("Джерело і призначення збігаються.")
                return
            # Copy в ту саму папку — одразу переходимо до нумерації

        # Copy Numbering — знаходимо унікальне ім'я автоматично.
        # Для Cut ім'я не змінюємо — якщо в dest_dir вже є файл
        # з таким іменем (і це не src), це реальна помилка файлової системи.
        if self._clipboard_cut:
            dest = base_dest
        else:
            dest = self._unique_path(base_dest)

        # Копіюємо або переміщуємо
        try:
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
        except Exception as exc:
            self._show_error(f"Помилка вставки: {exc}")
            return

        # Для Cut — видаляємо оригінал лише після успішного копіювання
        if self._clipboard_cut:
            try:
                if src.is_dir():
                    shutil.rmtree(src)
                else:
                    src.unlink()
            except Exception as exc:
                self._show_error(
                    f"Файл скопійовано, але не вдалося видалити оригінал: {exc}"
                )
            self._clipboard_path = None
            self._clipboard_cut  = False

        logger.debug("Вставлено: %s → %s", src, dest)

    # ------------------------------------------------------------------
    # Після видалення — посилання "Open or Create"
    # ------------------------------------------------------------------

    def _show_open_or_create_link(self) -> None:
        """Показати синій клікабельний текст у tree_view після видалення."""
        self._list_model.clear()
        item = QStandardItem("Відкрийте або Створіть Новий Проєкт")
        item.setForeground(QColor("#FE5C0D"))
        font = item.font()
        font.setPixelSize(14)
        font.setUnderline(True)
        item.setFont(font)
        item.setEditable(False)
        item.setData("__link__", Qt.UserRole)
        self._list_model.appendRow(item)

        # Одноразовий обробник кліку на посилання
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
        from PyQt5.QtCore    import QFileInfo
        return QFileIconProvider().icon(QFileIconProvider.Folder)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(
            self._w("tree_view_project"), "Помилка", message
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(project={self._current_project!r})"
        )