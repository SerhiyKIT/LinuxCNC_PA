# logic/managers/project/project_dialogs.py
"""
Модальні діалоги менеджера проектів:
  _NewProjectDialog    – створення нового проекту
  _OpenProjectDialog   – відкриття існуючого проекту
  _DeleteProjectDialog – підтвердження видалення
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt5.QtCore    import QCoreApplication, QModelIndex, Qt
from PyQt5.QtGui     import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog,
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTreeView, QVBoxLayout,
)
from .project_constants import PROJECTS_ROOT, STYLE_DIALOG, STYLE_TREE


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


# ===========================================================================
# Діалог створення нового проекту
# ===========================================================================

class _NewProjectDialog(QDialog):
    """Модальний діалог для створення нового проекту."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("New project"))
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        root.addWidget(QLabel(_tr("Name project:")))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("my_project")
        self._name_edit.textChanged.connect(self._validate)
        root.addWidget(self._name_edit)

        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color:#FF6161; font-size:12px;")
        root.addWidget(self._lbl_error)

        self._chk_repo = QCheckBox(_tr("Initialize Git Repository"))
        root.addWidget(self._chk_repo)
        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton(_tr("Cancel"))
        self._btn_cancel.setAutoDefault(False)
        self._btn_cancel.setDefault(False)
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_create = QPushButton(_tr("Create"))
        self._btn_create.setObjectName("btn_confirm")
        self._btn_create.setAutoDefault(False)
        self._btn_create.setDefault(False)
        self._btn_create.setEnabled(False)
        self._btn_create.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_create)
        root.addLayout(btn_row)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _validate(self) -> None:
        name  = self._name_edit.text().strip()
        error = ""
        if not name:
            error = ""
        elif any(c in name for c in r'\/:*?"<>|'):
            error = _tr("Name contains invalid characters")
        elif (PROJECTS_ROOT / name).exists():
            error = _tr(f'Project "{name}" already exists')

        self._lbl_error.setText(error)
        self._name_edit.setProperty("invalid", "true" if error else "")
        self._name_edit.style().unpolish(self._name_edit)
        self._name_edit.style().polish(self._name_edit)
        self._btn_create.setEnabled(bool(name) and not error)

    @property
    def project_name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def init_repo(self) -> bool:
        return self._chk_repo.isChecked()


# ===========================================================================
# Діалог відкриття проекту
# ===========================================================================

class _OpenProjectDialog(QDialog):
    """Діалог вибору існуючого проекту."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Open project"))
        self.setMinimumSize(400, 480)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(16, 16, 16, 16)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel(_tr("Path:")))
        lbl_path = QLineEdit(str(PROJECTS_ROOT))
        lbl_path.setReadOnly(True)
        lbl_path.setStyleSheet("color:#9E9E9E; background:#161616;")
        path_row.addWidget(lbl_path)
        root.addLayout(path_row)

        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels([_tr("Projects:")])
        self._tree  = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setStyleSheet(STYLE_TREE)
        self._tree.setHeaderHidden(False)
        self._tree.setRootIsDecorated(False)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.selectionModel().selectionChanged.connect(self._on_selection)
        self._tree.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._tree)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(_tr("Cancel"))
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)

        self._btn_ok = QPushButton(_tr("OK"))
        self._btn_ok.setObjectName("btn_confirm")
        self._btn_ok.setAutoDefault(False)
        self._btn_ok.setDefault(False)
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_ok)
        root.addLayout(btn_row)

        self._populate()

    def _populate(self) -> None:
        self._model.removeRows(0, self._model.rowCount())
        if not PROJECTS_ROOT.exists():
            return
        for entry in sorted(PROJECTS_ROOT.iterdir()):
            if entry.is_dir():
                item = QStandardItem(entry.name)
                item.setData(str(entry), Qt.UserRole)
                item.setEditable(False)
                self._model.appendRow(item)

    def _on_selection(self) -> None:
        self._btn_ok.setEnabled(
            bool(self._tree.selectionModel().selectedIndexes()))

    def _on_double_click(self, _: QModelIndex) -> None:
        if self._btn_ok.isEnabled():
            self.accept()

    @property
    def selected_path(self) -> Optional[Path]:
        indexes = self._tree.selectionModel().selectedIndexes()
        if not indexes:
            return None
        data = self._model.itemFromIndex(indexes[0]).data(Qt.UserRole)
        return Path(data) if data else None


# ===========================================================================
# Діалог підтвердження видалення
# ===========================================================================

class _DeleteProjectDialog(QDialog):
    """Діалог підтвердження видалення з ручним введенням назви."""

    def __init__(self, project_name: str, parent=None):
        super().__init__(parent)
        self._project_name = project_name
        self.setWindowTitle(_tr("Delete project"))
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        warn = QLabel(
            _tr(f'⚠  You are about to permanently delete the project '
                f'<span style="color:#FF6161; font-size:12px;">{project_name}</span> '
                f'and all its content from the disk. This action cannot be undone.')
        )
        warn.setTextFormat(Qt.RichText)
        warn.setWordWrap(True)
        root.addWidget(warn)

        root.addWidget(QLabel(_tr("Enter project name to confirm:")))
        self._confirm_edit = QLineEdit()
        self._confirm_edit.setPlaceholderText(project_name)
        self._confirm_edit.textChanged.connect(self._validate)
        root.addWidget(self._confirm_edit)

        self._chk = QCheckBox(_tr("I understand that deletion is irreversible"))
        self._chk.stateChanged.connect(self._validate)
        root.addWidget(self._chk)
        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(_tr("Cancel"))
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)

        self._btn_delete = QPushButton(_tr("Delete permanently"))
        self._btn_delete.setObjectName("btn_delete_confirm")
        self._btn_delete.setAutoDefault(False)
        self._btn_delete.setDefault(False)
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_delete)
        root.addLayout(btn_row)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _validate(self) -> None:
        self._btn_delete.setEnabled(
            self._confirm_edit.text().strip() == self._project_name
            and self._chk.isChecked()
        )
