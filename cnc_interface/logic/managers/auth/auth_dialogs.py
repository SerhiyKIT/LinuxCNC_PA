# logic/managers/auth/auth_dialogs.py
"""
LoginDialog        — вікно входу.
ConfirmPassDialog  — підтвердження поточного пароля.
UserEditDialog     — створення/редагування користувача.
UserAdminDialog    — панель адміністрування користувачів.
"""
from __future__ import annotations
import logging
from PyQt5.QtCore    import QCoreApplication, Qt
from PyQt5.QtGui     import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog,
    QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView, QWidget,
)
from .auth_constants import (
    ROLES, STYLE_BTN_PRIMARY,
    STYLE_BTN_SECONDARY, STYLE_DIALOG, STYLE_MSGBOX,
)
from .auth_db    import AuthDB, User
from .auth_session import AuthSession

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


def _msgbox(parent, title: str, text: str,
            icon=QMessageBox.Information) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setStyleSheet(STYLE_MSGBOX)
    box.exec_()


def _question(parent, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    box.setStyleSheet(STYLE_MSGBOX)
    return box.exec_() == QMessageBox.Yes


# ===========================================================================
# LoginDialog
# ===========================================================================

class LoginDialog(QDialog):
    """Модальне вікно входу. Закривається лише при успішній автентифікації."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Sign In"))
        self.setFixedSize(360, 260)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowTitleHint |
            Qt.CustomizeWindowHint
        )

        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(32, 32, 32, 32)

        # Заголовок
        title = QLabel(_tr("Authorization"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size:20px;font-weight:bold;color:#FE5C0D; background: none;")
        root.addWidget(title)

        # Форма
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._login_edit = QLineEdit()
        self._login_edit.setPlaceholderText(_tr("Login"))
        self._pass_edit  = QLineEdit()
        self._pass_edit.setPlaceholderText(_tr("Password"))
        self._pass_edit.setEchoMode(QLineEdit.Password)

        form.addRow(_tr("Login:"),    self._login_edit)
        form.addRow(_tr("Password:"), self._pass_edit)
        root.addLayout(form)

        # Повідомлення про помилку
        self._lbl_error = QLabel("")
        self._lbl_error.setAlignment(Qt.AlignCenter)
        self._lbl_error.setStyleSheet("color:#f38ba8;font-size:12px; background: none;")
        root.addWidget(self._lbl_error)

        root.addStretch()

        # Кнопка
        self._btn_login = QPushButton(_tr("Sign In"))
        self._btn_login.setObjectName("btn_confirm")
        self._btn_login.setStyleSheet(STYLE_BTN_PRIMARY)
        self._btn_login.clicked.connect(self._on_login)
        self._pass_edit.returnPressed.connect(self._on_login)
        self._login_edit.returnPressed.connect(self._pass_edit.setFocus)
        root.addWidget(self._btn_login)

    def _on_login(self) -> None:
        login    = self._login_edit.text().strip()
        password = self._pass_edit.text()
        if not login or not password:
            self._lbl_error.setText(_tr("Enter login and password"))
            return
        user = AuthDB.authenticate(login, password)
        if user is None:
            self._lbl_error.setText(_tr("Incorrect login or password"))
            self._pass_edit.clear()
            self._pass_edit.setFocus()
            return
        AuthSession.login(user)
        self.accept()


# ===========================================================================
# ConfirmPassDialog
# ===========================================================================

class ConfirmPassDialog(QDialog):
    """Запит поточного пароля перед зміною користувача."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Confirm Password"))
        self.setFixedSize(320, 180)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 24, 24, 24)

        root.addWidget(QLabel(_tr("Enter your current password to continue:")))

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        self._pass_edit.setPlaceholderText(_tr("Current password"))
        root.addWidget(self._pass_edit)

        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color:#f38ba8;font-size:12px;")
        root.addWidget(self._lbl_error)

        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton(_tr("Cancel"))
        btn_cancel.setStyleSheet(STYLE_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton(_tr("Confirm"))
        btn_ok.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_ok.clicked.connect(self._on_confirm)
        self._pass_edit.returnPressed.connect(self._on_confirm)

        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        root.addLayout(row)

    def _on_confirm(self) -> None:
        user = AuthSession.user()
        if user is None:
            self.reject()
            return
        if AuthDB.verify_password(user.id, self._pass_edit.text()):
            self.accept()
        else:
            self._lbl_error.setText(_tr("Incorrect password"))
            self._pass_edit.clear()


# ===========================================================================
# FirstRunDialog
# ===========================================================================

class FirstRunDialog(QDialog):
    """Вікно створення першого адміністратора при першому запуску."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("Initial Setup"))
        self.setFixedSize(400, 320)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint | Qt.CustomizeWindowHint
        )

        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(32, 32, 32, 32)

        title = QLabel(_tr("Create Administrator"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size:20px;font-weight:bold;color:#FE5C0D;background:none;")
        root.addWidget(title)

        desc = QLabel(_tr(
            "No users found. Create the first administrator account."))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color:#9E9E9E;font-size:12px;background:none;")
        root.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._login_edit = QLineEdit()
        self._login_edit.setPlaceholderText(_tr("Admin login"))
        form.addRow(_tr("Login:"), self._login_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        self._pass_edit.setPlaceholderText(_tr("Password"))
        form.addRow(_tr("Password:"), self._pass_edit)

        self._pass_confirm = QLineEdit()
        self._pass_confirm.setEchoMode(QLineEdit.Password)
        self._pass_confirm.setPlaceholderText(_tr("Confirm password"))
        form.addRow(_tr("Confirm:"), self._pass_confirm)

        root.addLayout(form)

        self._lbl_error = QLabel("")
        self._lbl_error.setAlignment(Qt.AlignCenter)
        self._lbl_error.setStyleSheet("color:#f38ba8;font-size:12px;background:none;")
        root.addWidget(self._lbl_error)

        root.addStretch()

        btn_create = QPushButton(_tr("Create"))
        btn_create.setObjectName("btn_confirm")
        btn_create.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_create.clicked.connect(self._on_create)
        self._pass_confirm.returnPressed.connect(self._on_create)
        self._login_edit.returnPressed.connect(self._pass_edit.setFocus)
        self._pass_edit.returnPressed.connect(self._pass_confirm.setFocus)
        root.addWidget(btn_create)

    def _on_create(self) -> None:
        login    = self._login_edit.text().strip()
        password = self._pass_edit.text()
        confirm  = self._pass_confirm.text()

        if not login:
            self._lbl_error.setText(_tr("Login cannot be empty"))
            return
        if not password:
            self._lbl_error.setText(_tr("Password cannot be empty"))
            return
        if password != confirm:
            self._lbl_error.setText(_tr("Passwords do not match"))
            self._pass_confirm.clear()
            self._pass_confirm.setFocus()
            return

        if AuthDB.create_superadmin(login, password):
            user = AuthDB.authenticate(login, password)
            if user is not None:
                AuthSession.login(user)
            self.accept()
        else:
            self._lbl_error.setText(_tr("Failed to create administrator"))


# ===========================================================================
# RoleEscalationDialog
# ===========================================================================

class RoleEscalationDialog(QDialog):
    """Запит пароля при підвищенні рівня доступу (перехід знизу вгору)."""

    def __init__(self, target_role: str, parent=None):
        super().__init__(parent)
        self._target_role = target_role
        self.setWindowTitle(_tr("Elevate Access"))
        self.setFixedSize(340, 200)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 24, 24, 24)

        msg = QLabel(_tr(f'Enter password to switch to "{target_role}":'))
        msg.setWordWrap(True)
        root.addWidget(msg)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        self._pass_edit.setPlaceholderText(_tr("Password"))
        root.addWidget(self._pass_edit)

        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color:#f38ba8;font-size:12px;")
        root.addWidget(self._lbl_error)

        row = QHBoxLayout()
        row.addStretch()

        btn_cancel = QPushButton(_tr("Cancel"))
        btn_cancel.setStyleSheet(STYLE_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton(_tr("Confirm"))
        btn_ok.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_ok.clicked.connect(self._on_confirm)
        self._pass_edit.returnPressed.connect(self._on_confirm)

        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        root.addLayout(row)

    def _on_confirm(self) -> None:
        user = AuthSession.user()
        if user is None:
            self.reject()
            return
        if AuthDB.verify_password(user.id, self._pass_edit.text()):
            self.accept()
        else:
            self._lbl_error.setText(_tr("Incorrect password"))
            self._pass_edit.clear()


# ===========================================================================
# UserEditDialog
# ===========================================================================

class UserEditDialog(QDialog):
    """Діалог створення або редагування користувача."""

    def __init__(self, user: User | None = None, parent=None):
        super().__init__(parent)
        self._user = user
        is_edit    = user is not None

        self.setWindowTitle(
            _tr("Edit User") if is_edit else _tr("Add User"))
        self.setFixedSize(360, 360)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(24, 24, 24, 24)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self._login_edit = QLineEdit(user.login if is_edit else "")
        self._login_edit.setPlaceholderText("username")
        form.addRow(_tr("Login:"), self._login_edit)

        self._pass_edit = QLineEdit(user.password if is_edit else "")
        self._pass_edit.setPlaceholderText(_tr("Password"))
        form.addRow(_tr("Password:"), self._pass_edit)
        root.addLayout(form)

        # Ролі
        roles_box = QGroupBox(_tr("Roles"))
        roles_lay = QVBoxLayout(roles_box)
        roles_lay.setSpacing(6)
        self._role_checks: dict[str, QCheckBox] = {}

        for col, label in ROLES:
            cb = QCheckBox(label)
            cb.setChecked(getattr(user, col) if is_edit else False)
            # Суперадмін: role_admin завжди увімкнена і заблокована
            if is_edit and user.is_superadmin and col == "role_admin":
                cb.setChecked(True)
                cb.setEnabled(False)
            self._role_checks[col] = cb
            roles_lay.addWidget(cb)
        root.addWidget(roles_box)

        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color:#f38ba8;font-size:12px;")
        root.addWidget(self._lbl_error)

        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton(_tr("Cancel"))
        btn_cancel.setStyleSheet(STYLE_BTN_SECONDARY)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton(_tr("Save"))
        btn_save.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_save.clicked.connect(self._on_save)

        row.addWidget(btn_cancel)
        row.addWidget(btn_save)
        root.addLayout(row)

    def _on_save(self) -> None:
        login    = self._login_edit.text().strip()
        password = self._pass_edit.text()

        if not login:
            self._lbl_error.setText(_tr("Login cannot be empty"))
            return
        if not password:
            self._lbl_error.setText(_tr("Password cannot be empty"))
            return

        roles = {col: cb.isChecked() for col, cb in self._role_checks.items()}

        # Якщо жодної ролі не обрано — автоматично призначити Operator
        if not any(roles.values()):
            roles["role_operator"] = True
            self._role_checks["role_operator"].setChecked(True)

        if self._user is None:
            ok = AuthDB.create(login, password, **roles)
            if not ok:
                self._lbl_error.setText(_tr("Login already exists"))
                return
        else:
            ok = AuthDB.update(self._user.id, login, password, **roles)
            if not ok:
                self._lbl_error.setText(_tr("Login already taken"))
                return

        self.accept()


# ===========================================================================
# UserAdminDialog
# ===========================================================================

class UserAdminDialog(QDialog):
    """Панель адміністрування — список користувачів з діями."""

    _COL_ID    = 0
    _COL_LOGIN = 1
    _COL_ROLES = 2
    _COL_EDIT  = 3
    _COL_DEL   = 4

    # Стиль кнопок-іконок — без фону, без відступів
    _STYLE_ICON_BTN = (
        "QPushButton{"
        "  background:transparent; border:none;"
        "  padding:0px; margin:0px;"
        "  qproperty-iconSize: 32px 32px;"
        "}"
        "QPushButton:disabled{ opacity:0.3; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("User Management"))
        self.setMinimumSize(600, 400)
        self.setModal(True)
        self.setStyleSheet(STYLE_DIALOG)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # Заголовок + кнопка Add
        top = QHBoxLayout()
        lbl = QLabel(_tr("Users"))
        lbl.setStyleSheet("font-size:15px;font-weight:bold;color:#FE5C0D;")
        top.addWidget(lbl)
        top.addStretch()
        btn_add = QPushButton(_tr("+ Add User"))
        btn_add.setStyleSheet(STYLE_BTN_PRIMARY)
        btn_add.clicked.connect(self._on_add)
        top.addWidget(btn_add)
        root.addLayout(top)

        # Таблиця
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "ID", _tr("Login"), _tr("Roles"), "", ""
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(
            self._COL_LOGIN, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            self._COL_ROLES, QHeaderView.Stretch)
        for col in (self._COL_ID, self._COL_EDIT, self._COL_DEL):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.Fixed)
        self._table.setColumnWidth(self._COL_ID,  40)
        self._table.setColumnWidth(self._COL_EDIT, 64)
        self._table.setColumnWidth(self._COL_DEL,  64)

        # Зміна іконок при виборі рядка
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self._table)

        # Закрити
        btn_close = QPushButton(_tr("Close"))
        btn_close.setStyleSheet(STYLE_BTN_SECONDARY)
        btn_close.clicked.connect(self.accept)
        root.addWidget(btn_close, alignment=Qt.AlignRight)

        self._refresh()

    # ------------------------------------------------------------------

    def _make_icon_label(self, icon_name: str,
                          enabled: bool = True) -> QLabel:
        """Створити QLabel з іконкою, відцентрований у комірці."""
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(QIcon(f":/icons/{icon_name}.png").pixmap(24, 24))
        if not enabled:
            lbl.setEnabled(False)
            lbl.setStyleSheet("opacity:0.3;")
        return lbl

    def _centered_widget(self, widget: QWidget) -> QWidget:
        """Обгортка що центрує віджет у комірці."""
        container = QWidget()
        container.setStyleSheet("background:transparent; border:none;")
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(widget)
        return container

    def _refresh(self) -> None:
        self._users: list[User] = AuthDB.get_all()
        self._table.setRowCount(0)
        for user in self._users:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # ID
            id_item = QTableWidgetItem(str(user.id))
            id_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, self._COL_ID, id_item)

            # Login
            self._table.setItem(row, self._COL_LOGIN, QTableWidgetItem(
                user.login + (" ★" if user.is_superadmin else "")))

            # Roles
            roles = ", ".join(
                label for col, label in ROLES if getattr(user, col))
            self._table.setItem(
                row, self._COL_ROLES, QTableWidgetItem(roles))

            # Edit — QLabel з іконкою
            lbl_edit = self._make_icon_label("edit")
            self._table.setCellWidget(
                row, self._COL_EDIT, self._centered_widget(lbl_edit))

            # Delete — QLabel з іконкою (заблокована для суперадміна)
            lbl_del = self._make_icon_label(
                "trash", enabled=not user.is_superadmin)
            self._table.setCellWidget(
                row, self._COL_DEL, self._centered_widget(lbl_del))

    def _on_cell_clicked(self, row: int, col: int) -> None:
        """Обробити клік на комірку Edit або Delete."""
        if row < 0 or row >= len(self._users):
            return
        user = self._users[row]
        if col == self._COL_EDIT:
            self._on_edit(user)
        elif col == self._COL_DEL and not user.is_superadmin:
            self._on_delete(user)

    def _on_selection_changed(self) -> None:
        """Міняємо іконки — active (білі) для обраного рядка."""
        selected_rows = {
            idx.row()
            for idx in self._table.selectionModel().selectedRows()
        }
        for row in range(self._table.rowCount()):
            is_selected = row in selected_rows
            suffix = "-active" if is_selected else ""
            is_super = row < len(self._users) and self._users[row].is_superadmin

            lbl_edit = self._get_label(row, self._COL_EDIT)
            lbl_del  = self._get_label(row, self._COL_DEL)

            if lbl_edit is not None:
                lbl_edit.setPixmap(
                    QIcon(f":/icons/edit{suffix}.png").pixmap(24, 24))
            if lbl_del is not None and not is_super:
                lbl_del.setPixmap(
                    QIcon(f":/icons/trash{suffix}.png").pixmap(24, 24))

    def _get_label(self, row: int, col: int) -> QLabel | None:
        """Дістати QLabel з контейнера-обгортки комірки."""
        container = self._table.cellWidget(row, col)
        if container is None:
            return None
        return container.findChild(QLabel)

    def _on_add(self) -> None:
        dlg = UserEditDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._refresh()

    def _on_edit(self, user: User) -> None:
        dlg = UserEditDialog(user=user, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._refresh()

    def _on_delete(self, user: User) -> None:
        if not _question(
            self,
            _tr("Delete User"),
            _tr(f'Delete user "{user.login}"? This cannot be undone.'),
        ):
            return
        if AuthDB.delete(user.id):
            self._refresh()
        else:
            _msgbox(self, _tr("Error"),
                    _tr("Failed to delete user."), QMessageBox.Critical)