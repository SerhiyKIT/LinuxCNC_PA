# logic/managers/auth/auth_manager.py
"""
AuthManager — фасад системи автентифікації.

Відповідає за:
  • Ініціалізацію БД при першому запуску
  • Показ LoginDialog при старті і після виходу
  • Заповнення lbl_user_name і combo_user_role після входу
  • Меню профілю (lbl_user_icon / btn_user_icon)
  • Скидання ProjectManager при виході/зміні користувача
"""
from __future__ import annotations
import logging
from PyQt5.QtCore    import QCoreApplication, Qt
from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QMenu, QWidget

from .auth_constants  import ROLES, STYLE_MENU
from .auth_db         import AuthDB
from .auth_dialogs    import (
    ConfirmPassDialog, LoginDialog, UserAdminDialog,
)
from .auth_session    import AuthSession

logger = logging.getLogger(__name__)


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class AuthManager:
    """Фасад автентифікації. Підключається до HandlerClass."""

    def __init__(self, widgets: object) -> None:
        self.widgets          = widgets
        self._w               = lambda n: getattr(self.widgets, n, None)
        self._project_manager = None
        self._overlay: QWidget | None = None

        # Ініціалізація БД (створює файл і суперадміна якщо потрібно)
        AuthDB.init()

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_project_manager(self, pm) -> None:
        self._project_manager = pm

    def start(self) -> None:
        """
        Показати головне вікно заблокованим, потім відкрити LoginDialog.
        Викликати з initialized__() після повної ініціалізації UI.
        """
        # Спочатку показуємо головне вікно — щоб воно було видне під діалогом
        main_window = self._get_main_window()
        if main_window is not None:
            main_window.show()

        self._lock_main_window(True)
        self._show_login()

    def connect_profile_button(self) -> None:
        """Підключити btn_user_icon і lbl_user_name до меню профілю."""
        btn = self._w("btn_user_icon")
        if btn is not None:
            try:
                btn.clicked.disconnect()
            except TypeError:
                pass
            btn.clicked.connect(self._show_profile_menu)

        lbl = self._w("lbl_user_name")
        if lbl is not None:
            lbl.setCursor(__import__(
                'PyQt5.QtCore', fromlist=['Qt']).Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda _: self._show_profile_menu_for(lbl)

    def _show_profile_menu_for(self, anchor) -> None:
        """Показати меню прив'язане до довільного віджета."""
        self._build_profile_menu().exec_(
            anchor.mapToGlobal(anchor.rect().bottomLeft())
        )

    # ------------------------------------------------------------------
    # Логін / Логаут
    # ------------------------------------------------------------------

    def _show_login(self) -> None:
        """Показати LoginDialog поверх головного вікна."""
        parent = self._get_main_window()
        dlg    = LoginDialog(parent)
        result = dlg.exec_()
        if result != QDialog.Accepted:
            self._show_login()
            return
        self._lock_main_window(False)
        self._populate_user_ui()
        logger.info("Вхід: %s [%s]",
                    AuthSession.user().login, AuthSession.active_role())

    def _logout(self) -> None:
        """Скинути сесію, проект і показати LoginDialog знову."""
        self._reset_project()
        AuthSession.logout()
        self._lock_main_window(True)
        self._show_login()

    # ------------------------------------------------------------------
    # UI після входу
    # ------------------------------------------------------------------

    def _populate_user_ui(self) -> None:
        """Заповнити lbl_user_name і combo_user_role після входу."""
        user = AuthSession.user()
        if user is None:
            return

        # Ім'я користувача
        lbl = self._w("lbl_user_name")
        if lbl is not None:
            lbl.setText(user.login)

        # ComboBox ролей
        combo: QComboBox = self._w("combo_user_role")
        if combo is None:
            return

        # Розширюємо існуючий стиль — додаємо лише правила для
        # випадаючого списку і недоступних елементів.
        # Оригінальний стиль (#combo_user_role) залишається у .ui файлі.
        combo.setStyleSheet(
            combo.styleSheet() +
            "QComboBox QAbstractItemView::item{"
            "  color:#F1F1F1;"
            "}"
            "QComboBox QAbstractItemView::item:disabled{"
            "  background:#111111; color:#444444;"
            "}"
        )

        combo.blockSignals(True)
        combo.clear()

        default_role = user.default_role()
        default_idx  = 0

        for i, (col, label) in enumerate(ROLES):
            combo.addItem(label)
            has_role = getattr(user, col)
            if not has_role:
                item = combo.model().item(i)
                if item:
                    from PyQt5.QtGui import QBrush, QColor
                    item.setEnabled(False)
                    item.setForeground(QBrush(QColor("#5B5B5B")))
                    item.setBackground(QBrush(QColor("#1A1A1A")))
            else:
                if label == default_role:
                    default_idx = i

        combo.setCurrentIndex(default_idx)
        combo.currentTextChanged.connect(AuthSession.set_active_role)
        combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Меню профілю
    # ------------------------------------------------------------------

    def _show_profile_menu(self) -> None:
        btn = self._w("btn_user_icon")
        if btn is None:
            return
        self._build_profile_menu().exec_(
            btn.mapToGlobal(btn.rect().bottomLeft())
        )

    def _build_profile_menu(self) -> QMenu:
        """Побудувати меню профілю."""
        menu = QMenu()
        menu.setStyleSheet(STYLE_MENU)

        if AuthSession.active_role() == "Admin":
            act_admin = menu.addAction(_tr("User Management"))
            act_admin.triggered.connect(self._open_admin_panel)
            menu.addSeparator()

        act_switch = menu.addAction(_tr("Switch User"))
        act_switch.triggered.connect(self._on_switch_user)

        menu.addSeparator()
        act_logout = menu.addAction(_tr("Logout"))
        act_logout.triggered.connect(self._logout)

        return menu

    def _open_admin_panel(self) -> None:
        dlg = UserAdminDialog(parent=self._w("btn_user_icon"))
        dlg.exec_()

    def _on_switch_user(self) -> None:
        """Запитати поточний пароль, потім перейти до LoginDialog."""
        confirm = ConfirmPassDialog(parent=self._w("btn_user_icon"))
        if confirm.exec_() != QDialog.Accepted:
            return
        self._logout()

    # ------------------------------------------------------------------
    # Хелпери
    # ------------------------------------------------------------------

    def _get_main_window(self):
        """Знайти головне вікно програми."""
        central = self._w("centralwidget") or self._w("central_widget")
        if central is not None:
            return central.window()
        for w in QApplication.topLevelWidgets():
            if w.__class__.__name__ not in (
                "LoginDialog", "ConfirmPassDialog", "UserAdminDialog"
            ):
                return w
        return None

    def _lock_main_window(self, locked: bool) -> None:
        """Заблокувати вікно і показати напівпрозорий overlay."""
        central = self._w("centralwidget") or self._w("central_widget")
        if central is None:
            _skip = {"LoginDialog", "ConfirmPassDialog"}
            for w in QApplication.topLevelWidgets():
                if w.__class__.__name__ not in _skip:
                    central = w
                    break

        if central is None:
            return

        central.setEnabled(not locked)

        if locked:
            self._show_overlay(central)
        else:
            self._hide_overlay()

    def _show_overlay(self, parent: QWidget) -> None:
        """Створити і показати напівпрозорий overlay поверх вікна."""
        self._hide_overlay()
        self._overlay = QWidget(parent)
        self._overlay.setObjectName("auth_overlay")
        self._overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._overlay.setStyleSheet(
            "QWidget#auth_overlay{"
            "  background-color: rgba(30, 30, 30, 150);"
            "}"
        )
        self._overlay.setGeometry(parent.rect())
        self._overlay.raise_()
        self._overlay.show()

    def _hide_overlay(self) -> None:
        """Прибрати overlay."""
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

    def _reset_project(self) -> None:
        """Закрити поточний проект при виході."""
        pm = self._project_manager
        if pm is None:
            return
        try:
            pm._set_initial_state()
            lbl = getattr(pm.widgets, "lbl_project_name", None)
            if lbl:
                lbl.setText("Project")
        except Exception as exc:
            logger.warning("_reset_project: %s", exc)