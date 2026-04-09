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
from PyQt5.QtCore    import QCoreApplication, QEvent, Qt, QTimer
from PyQt5.QtGui     import QIcon
from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QMenu, QWidget

from .auth_constants  import INACTIVITY_TIMEOUT_MS, ROLE_ICONS, ROLE_PRIORITY, ROLES, STYLE_MENU
from .auth_db         import AuthDB
from .auth_dialogs    import (
    ConfirmPassDialog, FirstRunDialog, LoginDialog,
    RoleEscalationDialog, UserAdminDialog,
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

        # Ініціалізація БД (створює таблицю якщо потрібно)
        AuthDB.init()

        # Таймер бездіяльності — скидання до Operator
        self._inactivity_timer = QTimer()
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.setInterval(INACTIVITY_TIMEOUT_MS)
        self._inactivity_timer.timeout.connect(self._on_inactivity_timeout)

    # ------------------------------------------------------------------
    # Публічний API
    # ------------------------------------------------------------------

    def set_project_manager(self, pm) -> None:
        self._project_manager = pm

    def start(self) -> None:
        """
        Показати головне вікно заблокованим.
        При першому запуску — FirstRunDialog для створення адміна.
        Інакше — LoginDialog.
        """
        main_window = self._get_main_window()
        if main_window is not None:
            main_window.show()

        self._lock_main_window(True)

        if AuthDB.is_empty():
            self._show_first_run()
        else:
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

    def _show_first_run(self) -> None:
        """Показати діалог створення першого адміністратора."""
        parent = self._get_main_window()
        dlg = FirstRunDialog(parent)
        result = dlg.exec_()
        if result != QDialog.Accepted:
            self._show_first_run()
            return
        self._lock_main_window(False)
        self._populate_user_ui()
        self._sync_current_user()
        self._start_inactivity_tracking()
        logger.info("Перший запуск: створено адміністратора '%s'",
                    AuthSession.user().login)

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
        self._sync_current_user()
        self._start_inactivity_tracking()
        logger.info("Вхід: %s [%s]",
                    AuthSession.user().login, AuthSession.active_role())

    def _logout(self) -> None:
        """Скинути сесію, проект і показати LoginDialog знову."""
        self._stop_inactivity_tracking()
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

        lbl = self._w("lbl_user_name")
        if lbl is not None:
            lbl.setText(user.login)

        combo: QComboBox = self._w("combo_user_role")
        if combo is None:
            return

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

        # Відключити попередній сигнал і підключити новий з контролем ескалації
        try:
            combo.currentTextChanged.disconnect()
        except TypeError:
            pass
        combo.currentTextChanged.connect(self._on_role_change_requested)
        combo.blockSignals(False)

        self._update_role_icon(default_role)

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
        """Закрити поточний проект і скинути автора при виході."""
        pm = self._project_manager
        if pm is None:
            return
        try:
            pm.set_current_user("")
            pm._set_initial_state()
            lbl = getattr(pm.widgets, "lbl_project_name", None)
            if lbl:
                lbl.setText("Project")
        except Exception as exc:
            logger.warning("_reset_project: %s", exc)

    def _sync_current_user(self) -> None:
        """Передати login активного користувача у ProjectManager."""
        pm = self._project_manager
        if pm is None:
            return
        user = AuthSession.user()
        if user is not None:
            pm.set_current_user(user.login)

    # ------------------------------------------------------------------
    # Зміна ролі з контролем ескалації
    # ------------------------------------------------------------------

    def _on_role_change_requested(self, new_role: str) -> None:
        """
        Обробка зміни ролі через ComboBox.
        Вгору (Operator→Admin) — запит пароля.
        Вниз (Admin→Operator) — без запиту.
        """
        current_role = AuthSession.active_role()
        current_prio = ROLE_PRIORITY.get(current_role, 0)
        new_prio     = ROLE_PRIORITY.get(new_role, 0)

        if new_prio > current_prio and new_role != "Operator":
            dlg = RoleEscalationDialog(new_role, parent=self._w("combo_user_role"))
            if dlg.exec_() != QDialog.Accepted:
                # Повернути ComboBox на попереднє значення
                combo = self._w("combo_user_role")
                if combo is not None:
                    combo.blockSignals(True)
                    idx = combo.findText(current_role)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
                return

        AuthSession.set_active_role(new_role)
        self._update_role_icon(new_role)
        self._restart_inactivity_timer()
        logger.info("Роль змінена: %s → %s", current_role, new_role)

    # ------------------------------------------------------------------
    # Іконка ролі
    # ------------------------------------------------------------------

    def _update_role_icon(self, role: str) -> None:
        """Оновити іконку btn_user_icon відповідно до поточної ролі."""
        btn = self._w("btn_user_icon")
        if btn is None:
            return
        icon_path = ROLE_ICONS.get(role, ROLE_ICONS["Operator"])
        btn.setIcon(QIcon(icon_path))

    # ------------------------------------------------------------------
    # Таймер бездіяльності
    # ------------------------------------------------------------------

    def _start_inactivity_tracking(self) -> None:
        """Встановити глобальний фільтр подій і запустити таймер."""
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._get_event_filter())
        self._restart_inactivity_timer()

    def _stop_inactivity_tracking(self) -> None:
        """Зупинити таймер і зняти фільтр подій."""
        self._inactivity_timer.stop()
        app = QApplication.instance()
        if app is not None:
            ef = getattr(self, "_event_filter", None)
            if ef is not None:
                app.removeEventFilter(ef)

    def _restart_inactivity_timer(self) -> None:
        """Перезапустити таймер бездіяльності."""
        self._inactivity_timer.start()

    def _on_inactivity_timeout(self) -> None:
        """Скинути роль до Operator після бездіяльності."""
        current = AuthSession.active_role()
        if current == "Operator":
            return
        user = AuthSession.user()
        if user is None or not user.role_operator:
            return
        AuthSession.set_active_role("Operator")
        combo = self._w("combo_user_role")
        if combo is not None:
            combo.blockSignals(True)
            idx = combo.findText("Operator")
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        self._update_role_icon("Operator")
        logger.info("Бездіяльність: роль скинута до Operator")

    def _get_event_filter(self):
        """Створити або повернути EventFilter для відстеження активності."""
        if not hasattr(self, "_event_filter") or self._event_filter is None:
            self._event_filter = _InactivityFilter(self)
        return self._event_filter


# ---------------------------------------------------------------------------
# EventFilter для відстеження активності користувача
# ---------------------------------------------------------------------------

class _InactivityFilter(QWidget):
    """
    Глобальний фільтр подій — перезапускає таймер
    при будь-якій активності (клавіша, миша, тач).
    """
    _TRACKED_EVENTS = {
        QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
        QEvent.MouseMove, QEvent.KeyPress, QEvent.KeyRelease,
        QEvent.Wheel, QEvent.TouchBegin,
    }

    def __init__(self, auth_manager: AuthManager) -> None:
        super().__init__()
        self._auth_manager = auth_manager

    def eventFilter(self, obj, event) -> bool:
        if event.type() in self._TRACKED_EVENTS:
            self._auth_manager._restart_inactivity_timer()
        return False