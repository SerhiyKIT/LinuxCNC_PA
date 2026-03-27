# logic/managers/project/project_tree.py
"""
_HiddenFoldersProxy – QSortFilterProxyModel що приховує системні папки.
Функції ініціалізації і перебудови дерева файлів проекту.
"""
from __future__ import annotations
from pathlib import Path

from PyQt5.QtCore    import Qt, QSortFilterProxyModel
from PyQt5.QtWidgets import QAbstractItemView, QFileSystemModel, QTreeView

from .project_constants import HIDDEN_FOLDERS, STYLE_TREE


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
        if model.isDir(index) and name in self._hidden:
            return False
        return True


def setup_project_tree(manager) -> None:
    """
    Ініціалізувати tree_view_project (список проектів) і _project_tree
    (дерево файлів відкритого проекту).

    Викликається один раз з ProjectManager.__init__().
    Всі результати зберігаються в атрибути manager.
    """
    from PyQt5.QtCore import QSortFilterProxyModel
    from PyQt5.QtGui  import QStandardItemModel

    tree: QTreeView = manager._w("tree_view_project")
    if tree is not None:
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(manager._on_tree_context_menu)
        tree.doubleClicked.connect(manager._on_tree_double_click)

    manager._list_model = QStandardItemModel()
    manager._list_proxy = QSortFilterProxyModel()
    manager._list_proxy.setSourceModel(manager._list_model)
    manager._list_proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
    manager._list_proxy.setFilterKeyColumn(0)

    if tree is not None:
        tree.setModel(manager._list_proxy)
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(False)

    parent_widget = tree.parent() if tree is not None else None
    manager._project_tree = QTreeView(parent_widget)
    manager._project_tree.setGeometry(5, 70, 275, 420)
    manager._project_tree.setStyleSheet(STYLE_TREE)
    manager._project_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
    manager._project_tree.setContextMenuPolicy(Qt.CustomContextMenu)
    manager._project_tree.customContextMenuRequested.connect(
        manager._on_project_tree_context_menu)
    manager._project_tree.doubleClicked.connect(
        manager._on_project_tree_double_click)
    manager._project_tree.setHeaderHidden(True)
    manager._project_tree.setRootIsDecorated(True)
    manager._project_tree.hide()

    manager._fs_model = QFileSystemModel()
    manager._fs_model.setReadOnly(False)
    manager._fs_model.setNameFilterDisables(False)
    manager._project_tree.setModel(manager._fs_model)
    for col in (1, 2, 3):
        manager._project_tree.setColumnHidden(col, True)

    manager._tree_proxy = _HiddenFoldersProxy(
        hidden=HIDDEN_FOLDERS,
        parent=manager._project_tree,
    )
    manager._tree_proxy.setSourceModel(manager._fs_model)
    manager._project_tree.setModel(manager._tree_proxy)


def rebuild_fs_model(manager, project_path: Path) -> None:
    """
    Повністю замінити QFileSystemModel і _HiddenFoldersProxy.

    QFileSystemModel кешує структуру і не скидає кеш навіть при
    setRootPath(""). Єдиний надійний спосіб — знищити і створити нову.
    Викликається при кожному відкритті проекту.
    """
    manager._project_tree.setModel(None)

    if hasattr(manager, "_tree_proxy") and manager._tree_proxy is not None:
        manager._tree_proxy.setSourceModel(None)
        manager._tree_proxy.deleteLater()
    if hasattr(manager, "_fs_model") and manager._fs_model is not None:
        manager._fs_model.deleteLater()

    manager._fs_model = QFileSystemModel()
    manager._fs_model.setReadOnly(False)
    manager._fs_model.setNameFilterDisables(False)
    manager._fs_model.setRootPath(str(project_path))

    manager._tree_proxy = _HiddenFoldersProxy(
        hidden=HIDDEN_FOLDERS,
        parent=manager._project_tree,
    )
    manager._tree_proxy.setSourceModel(manager._fs_model)
    manager._project_tree.setModel(manager._tree_proxy)

    for col in (1, 2, 3):
        manager._project_tree.setColumnHidden(col, True)

    src_root = manager._fs_model.index(str(project_path))
    manager._project_tree.setRootIndex(
        manager._tree_proxy.mapFromSource(src_root))
