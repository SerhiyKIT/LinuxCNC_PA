#!/usr/bin/env python3
import os
import sys
import subprocess
from datetime import datetime

# Модулі LinuxCNC
import linuxcnc

# Регулювання імпортів Qt (PyQt5 за замовчуванням для LinuxCNC)
try:
    from PyQt5 import QtCore, QtWidgets, QtGui
    from PyQt5.QtCore import Qt, QTimer, QSize, QStringListModel
    from PyQt5.QtWidgets import QMessageBox, QFileDialog, QLabel, QVBoxLayout, QWidget, QFrame
    from PyQt5.QtGui import QTextCursor, QIcon
    from PyQt5.QtOpenGL import QGLWidget
    
    QT_VERSION = 5
except ImportError:
    try:
        from PyQt6 import QtCore, QtWidgets, QtGui
        from PyQt6.QtCore import Qt, QTimer, QSize, QStringListModel
        from PyQt6.QtWidgets import QMessageBox, QFileDialog, QLabel, QVBoxLayout, QWidget, QFrame
        from PyQt6.QtGui import QTextCursor, QIcon
        class QGLWidget: pass 
        
        QT_VERSION = 6
    except ImportError:
        class QGLWidget: pass
        QT_VERSION = 0

class HandlerClass:
    def __init__(self, halcomp, widgets, paths):
        self.halcomp = halcomp
        self.widgets = widgets
        self.status = linuxcnc.stat()
        self.command = linuxcnc.command()
        
        # Параметри руху
        self.SPEED = 1000.0  # Одиниці за хвилину
        
        # Ліміти суглобів (Joint Limits) згідно з налаштуваннями INI
        self.JOINT_LIMITS = {
            0: {"min": -360.0, "max": 360.0}, # JOINT_0
            1: {"min": -360.0, "max": 360.0}, # JOINT_1
            2: {"min": -215.0, "max": 35.0},  # JOINT_2
            3: {"min": -360.0, "max": 360.0}, # JOINT_3
            4: {"min": -360.0, "max": 360.0}, # JOINT_4
            5: {"min": -360.0, "max": 360.0}  # JOINT_5
        }
        
        # Ініціалізація зв'язку з LinuxCNC
        try:
            self.status = linuxcnc.stat()
            self.command = linuxcnc.command()
            print("DEBUG: Підключення до LinuxCNC успішне")
            self.log_message(f"Successfully connected to LinuxCNC", "info")
        except Exception as e:
            print(f"ERROR: Помилка підключення до LinuxCNC: {e}")
            self.log_message(f"Error connecting to LinuxCNC: {e}", "error")
        
        # Налаштування для сумісності з genserkins
        self.TELEOP_ENABLE_VAL = int(0) 
        self.JOG_CMD_FLAG = int(1) 
        
        # Сховище для відстеження змін позиції
        self.last_joint_pos = {}
        
        # Прапорець для вікна при завершенні хомінгу
        self.homing_complete_shown = False
        
        # Список кнопок G-code панелі
        self.gcode_buttons = [
            'btn_file_open', 'btn_file_reload', 'btn_file_save_as', 
            'btn_cycle_start', 'btn_cycle_continue'
        ]
        
        self.manual_panel_selection = "axis"
        
        self.last_loaded_file = None
        
        self.reload_needed = False
        
        # Константи стилів
        self._set_styles()

    def _set_styles(self):
        self.STYLE_ESTOP_OFF = "QPushButton { background-color: #FF0000; color: #FFFFFF; padding: 10px; border-radius: 10px; border: none; font-weight: bold; } QPushButton:hover { background-color: rgb(245, 0, 0); }"
        self.STYLE_ESTOP_ON = "QPushButton { background-color: #FF6161; color: white; padding: 10px; border-radius: 10px; border: none; font-weight: bold; } QPushButton:hover { background-color: #ff4d4d; }"
        self.STYLE_POWER_OFF = "QToolButton { background-color: #333333; color: #9E9E9E; padding: 10px; border-radius: 10px; border: none; } QToolButton:hover { background-color: rgb(91, 91, 91); color: rgb(241, 241, 241); }"
        self.STYLE_POWER_ON = "QToolButton { background-color: #FE5C0D; color: white; padding: 10px; border-radius: 10px; border: none; } QToolButton:hover { background-color: rgb(254, 81, 13); color: rgb(241, 241, 241); }"
        self.STYLE_HOME_INACTIVE = "QToolButton { background-color: #333333; color: #9E9E9E; padding: 10px; border-radius: 10px; border: 3px solid #333333; }"
        self.STYLE_HOME_READY = "QToolButton { background-color: #333333; color: #9E9E9E; padding: 10px; border-radius: 10px; border: 3px solid #FE5C0D; } QToolButton:hover { background-color: rgb(91, 91, 91); color: rgb(241, 241, 241); }"
        
        # Стилі для кнопок джога (Active/Inactive)
        self.STYLE_JOG_ACTIVE = """
            QPushButton { background-color: #FE5C0D; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; }
            QPushButton:hover { background-color: rgb(254, 81, 13); border: 2px solid rgb(254, 174, 13); }
        """
        self.STYLE_JOG_LIMITED = """
            QPushButton { background-color: #333333; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; }
        """

        # Стилі для кнопок G-code
        self.STYLE_GCODE_INACTIVE = "QPushButton { background-color: #333333; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; }"
        self.STYLE_GCODE_ACTIVE = "QPushButton { background-color: #FE5C0D; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; } QPushButton:hover { background-color: #ff7533; }"
        self.STYLE_GCODE_WARN = "QPushButton { background-color: #FF0000; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; } QPushButton:hover { background-color: rgb(245, 0, 0); }"
        
        self.PANEL_FRAME_INACTIVE = "border-radius: 10px; border: 3px solid #333333;"
        self.PANEL_FRAME_ACTIVE = "border-radius: 10px; border: 3px solid #FE5C0D;"
        self.PANEL_LABEL_INACTIVE = "border: none; color: #9E9E9E;"
        self.PANEL_LABEL_ACTIVE = "border: none; color: #FE5C0D;"
        
        self.STYLE_MSGBOX = """
            QMessageBox { background-color: #2D2D2D; border: 2px solid #FE5C0D; border-radius: 10px; } 
            QMessageBox QLabel { color: white; font-size: 13px; padding: 5px; } 
            QPushButton { background-color: #3D3D3D; color: white; min-width: 80px; padding: 6px; border-radius: 5px; border: 1px solid #555555; }
            QPushButton:hover { background-color: #FE5C0D; border: 1px solid white; }
        """
        
        # Додайте це в метод _set_styles
        self.STYLE_GCODE_LIST = """
            QListView {
                color: #FFFFFF;
                outline: none;
                background-color: #161616;
                border: none;
                padding: 0px;
            }
            QListView::item {
                padding: 4px;
            }
            QListView::item:selected {
                background-color: #FE5C0D;
                color: white;
                border-radius: 3px;
            }
            QListView::item:hover {
                background-color: #333333;
            }
            QScrollBar:vertical {
                background: #333333;
                width: 12px;
                margin: 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #FE5C0D;
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QListView QLineEdit {
                background-color: #2D2D2D;
                color: #FE5C0D; /* Текст стає помаранчевим при редагуванні */
                border: 1px solid #FE5C0D;
                border-radius: 2px;
                font-style: italic; /* Курсив для візуального акценту */
            }
        """
        
        self.STYLE_OUTPUT_VIEW = """
            QListWidget {
                background-color: #121212;
                border: 1px solid #2D2D2D;
                border-radius: 5px;
                outline: none;
                padding: 0px;
            }
            QListWidget::item {
                background-color: transparent;
                padding: 0px;
                margin: 0px;
                border: none;
            }
            QListWidget::item:selected {
                background-color: #1A1A1A;
            }
        """
        
        # Стилі для серво-захвата (Cyan/Blue акцент)
        self.STYLE_TOOL_ARMED = "QPushButton { background-color: #FE5C0D; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; } QPushButton:hover { background-color: #ff7533; }"
        self.STYLE_TOOL_DISARMED = "QPushButton { background-color: #333333; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; }"
        self.STYLE_GRIP_ACTIVE = "QPushButton { background-color: #FE5C0D; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; } QPushButton:hover { background-color: #ff7533; }"
        self.STYLE_GRIP_INACTIVE = "QPushButton { background-color: #333333; color: #FFFFFF; padding: 5px; border-radius: 10px; border: none; }"

    def initialized__(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update__)
        self.timer.start(100)
        
        self.error_channel = linuxcnc.error_channel()
        self.msg_timer = QTimer()
        self.msg_timer.timeout.connect(self.check_system_messages)
        self.msg_timer.start(100) # Перевіряти кожні 100 мс
        
        if hasattr(self.widgets, 'list_output_view'):
            self.setup_output_panel()
        
        # Сигнали панелі інструменту (Gripper)
        if hasattr(self.widgets, 'btn_tool_arm'):
            self.widgets.btn_tool_arm.setCheckable(True)
            self.widgets.btn_tool_arm.clicked.connect(self.on_btn_tool_arm_clicked)

        if hasattr(self.widgets, 'btn_tool_action'):
            self.widgets.btn_tool_action.setCheckable(True)
            self.widgets.btn_tool_action.clicked.connect(self.on_btn_tool_action_clicked)

        if hasattr(self.widgets, 'sld_tool_power'):
            self.widgets.sld_tool_power.setMinimum(10) # Мінімум 10%, щоб не впустити деталь
            self.widgets.sld_tool_power.setMaximum(100)
            self.widgets.sld_tool_power.valueChanged.connect(self.on_sld_tool_power_changed)
        
        # Налаштування діапазонів та підключення сигналів
        override_configs = {
            'sld_feed_override': (0, 200, self.on_sld_feed_override_changed),
            'sld_rapid_override': (0, 100, self.on_sld_rapid_override_changed),
            'sld_spindle_override': (0, 200, self.on_sld_spindle_override_changed),
            'sld_linear_jog_speed': (1, 593000, self.on_sld_linear_changed), # множимо на 1000 для точності float
            'sld_angular_jog_speed': (1, 605900, self.on_sld_angular_changed),
            'sld_max_velocity': (0, 600, self.on_sld_max_velocity_changed)
        }

        for name, (min_v, max_v, callback) in override_configs.items():
            if hasattr(self.widgets, name):
                slider = getattr(self.widgets, name)
                slider.setMinimum(min_v)
                slider.setMaximum(max_v)
                slider.valueChanged.connect(callback)
        
        if hasattr(self.widgets, 'btn_file_save_as'):
            self.widgets.btn_file_save_as.clicked.connect(self.on_btn_file_save_as_clicked)
            self.widgets.btn_file_save_as.setStyleSheet(self.STYLE_GCODE_INACTIVE)
            
        if hasattr(self.widgets, 'btn_file_reload'):
            self.widgets.btn_file_reload.clicked.connect(self.on_btn_file_reload_clicked)
            self.widgets.btn_file_reload.setStyleSheet(self.STYLE_GCODE_INACTIVE)
        
        if hasattr(self.widgets, 'btn_file_edit'):
            self.widgets.btn_file_edit.clicked.connect(self.on_btn_file_edit_clicked)
            # Встановлюємо початковий стиль (активна, якщо є файл)
            self.widgets.btn_file_edit.setStyleSheet(self.STYLE_GCODE_INACTIVE)
        
        if hasattr(self.widgets, 'btn_cycle_start'):
            self.widgets.btn_cycle_start.clicked.connect(self.on_btn_cycle_start_clicked)

        if hasattr(self.widgets, 'btn_cycle_continue'):
            self.widgets.btn_cycle_continue.clicked.connect(self.on_btn_cycle_continue_clicked)

        if hasattr(self.widgets, 'btn_cycle_pause'):
            self.widgets.btn_cycle_pause.clicked.connect(self.on_btn_cycle_pause_clicked)

        if hasattr(self.widgets, 'btn_cycle_stop'):
            self.widgets.btn_cycle_stop.clicked.connect(self.on_btn_cycle_stop_clicked)
    
        if hasattr(self.widgets, 'btn_cycle_step'):
            self.widgets.btn_cycle_step.clicked.connect(self.on_btn_cycle_step_clicked)
        
        # Підключення кнопки відкриття файлу G-code
        if hasattr(self.widgets, 'btn_file_open'):
            self.widgets.btn_file_open.clicked.connect(self.on_btn_file_open_clicked)
            
        # У метод initialized__
        if hasattr(self.widgets, 'list_gcode_view'):
            self.widgets.list_gcode_view.setStyleSheet(self.STYLE_GCODE_LIST)
            
        if hasattr(self.widgets, 'list_gcode_view'):
            # Дозволяє почати друкувати одразу після виділення рядка
            self.widgets.list_gcode_view.setEditTriggers(
            self.widgets.list_gcode_view.AnyKeyPressed | 
            self.widgets.list_gcode_view.DoubleClicked
        )
        
        # Ініціалізація ComboBox режимів джога
        if hasattr(self.widgets, 'combo_joint_mode'):
            self.widgets.combo_joint_mode.clear()
            self.widgets.combo_joint_mode.addItems(["Continuous", "0.1000", "0.0100", "0.0010", "0.0001"])
            
        # Ініціалізація ComboBox режимів джога для осей
        if hasattr(self.widgets, 'combo_axis_mode'):
            self.widgets.combo_axis_mode.clear()
            self.widgets.combo_axis_mode.addItems(["Continuous", "0.1000", "0.0100", "0.0010", "0.0001"])
            
        # Додайте це в кінець методу initialized__
        if hasattr(self.widgets, 'joint_control_overlay'):
            self.widgets.joint_control_overlay.mousePressEvent = lambda e: self._on_overlay_clicked("joint")
        if hasattr(self.widgets, 'axis_control_overlay'):
            self.widgets.axis_control_overlay.mousePressEvent = lambda e: self._on_overlay_clicked("axis")
            
        self._connect_all_axis_buttons()
        
        if hasattr(self.widgets, 'btn_estop'):
            self.widgets.btn_estop.clicked.connect(self.on_btn_estop_clicked)
        if hasattr(self.widgets, 'btn_power_off'):
            self.widgets.btn_power_off.clicked.connect(self.on_btn_power_off_clicked)
        if hasattr(self.widgets, 'btn_home_all'):
            self.widgets.btn_home_all.clicked.connect(self.on_btn_home_all_clicked)

        
        self._connect_all_jog_buttons()
        print("DEBUG: Обробник готовий до роботи")
    
    def setup_output_panel(self):
        # Встановлюємо стилі
        self.widgets.list_output_view.setStyleSheet(self.STYLE_OUTPUT_VIEW)
        
        # Обнуляємо все на рівні об'єкта
        self.widgets.list_output_view.setSpacing(0)
        self.widgets.list_output_view.setContentsMargins(0, 0, 0, 0)
        
        # Вимикаємо внутрішні відступи контейнера даних
        if hasattr(self.widgets.list_output_view, 'viewport'):
            self.widgets.list_output_view.viewport().setContentsMargins(0, 0, 0, 0)
            
        self.widgets.list_output_view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.widgets.list_output_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        
    def log_message(self, message, level="info"):
        if not hasattr(self.widgets, 'list_output_view'):
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {"info": "#00FFFF", "warning": "#FFCC00", "error": "#FF5555"}
        color = colors.get(level, "#FFFFFF")
        
        # Формуємо повний текст для буфера обміну: [12:00:01] INFO: Повідомлення
        full_log_text = f"[{timestamp}] {level.upper()}: {message}"

        item = QtWidgets.QListWidgetItem(self.widgets.list_output_view)
        
        container = QtWidgets.QWidget()
        container.setObjectName("logContainer")
        container.setStyleSheet("#logContainer { background: transparent; border: none; }")
        
        v_layout = QtWidgets.QVBoxLayout(container)
        v_layout.setContentsMargins(5, 2, 5, 2)
        v_layout.setSpacing(0)

        h_layout = QtWidgets.QHBoxLayout()
        h_layout.setSpacing(10)

        # Візуальний текст (HTML)
        label = QtWidgets.QLabel(
            f'<span style="color: #666666;">[{timestamp}]</span> '
            f'<b style="color: {color};">{level.upper()}:</b> {message}'
        )
        label.setWordWrap(True)
        # Динамічно обмежуємо ширину, щоб WordWrap працював коректно
        label.setFixedWidth(self.widgets.list_output_view.width() - 60)
        label.setStyleSheet("color: #DCDCDC; font-size: 12px; border: none; background: transparent;")
        
        btn_copy = QtWidgets.QPushButton("📋")
        btn_copy.setFixedSize(24, 24)
        btn_copy.setCursor(QtCore.Qt.PointingHandCursor)
        btn_copy.setToolTip("Копіювати повний лог")
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #2A2A2A;
                color: #DCDCDC;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover { background-color: #3A3A3A; color: #FE5C0D; }
        """)
        
        # Передаємо full_log_text замість просто message
        btn_copy.clicked.connect(lambda: self._copy_to_clipboard(full_log_text, btn_copy))

        h_layout.addWidget(label, 1)
        h_layout.addWidget(btn_copy, 0)
        v_layout.addLayout(h_layout)

        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #333333; border: none; margin-top: 4px;")
        v_layout.addWidget(line)

        self.widgets.list_output_view.addItem(item)
        self.widgets.list_output_view.setItemWidget(item, container)
        
        # Використовуємо автоматичний розрахунок висоти контейнера
        item.setSizeHint(container.sizeHint())
        self.widgets.list_output_view.scrollToBottom()

    def _copy_to_clipboard(self, text, button):
        """Копіює текст та дає візуальний фідбек на кнопці"""
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        
        # Візуальне підтвердження: міняємо іконку на галочку на 1 секунду
        old_text = button.text()
        button.setText("✓")
        button.setStyleSheet("background-color: #1A4A1A; color: #00FF00; border-radius: 4px;")
        
        # Повертаємо назад через 1000 мс
        QtCore.QTimer.singleShot(1000, lambda: self._reset_copy_button(button, old_text))

    def _reset_copy_button(self, button, old_text):
        button.setText(old_text)
        button.setStyleSheet("""
            QPushButton {
                background-color: #2A2A2A;
                color: #DCDCDC;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover { background-color: #3A3A3A; color: #FE5C0D; }
        """)
    
    def toggle_output_message(self, item):
        """Метод для розгортання/згортання довгих повідомлень (за потреби)"""
        widget = self.widgets.list_output_view.itemWidget(item)
        current_hint = item.sizeHint()
        
        if current_hint.height() < 50:
            # Розгортаємо до повного розміру контенту
            item.setSizeHint(widget.sizeHint())
        else:
            # Згортаємо до одного рядка (приблизно 35px)
            item.setSizeHint(QtCore.QSize(0, 35))
    
    def check_system_messages(self):
        """Опитування системного каналу помилок LinuxCNC"""
        error = self.error_channel.poll()
        if error:
            # error[0] - це тип (NML_ERROR, NML_TEXT, OPERATOR_ERROR)
            # error[1] - це текст помилки
            kind, text = error
        
            # Визначаємо рівень важливості для log_message
            level = "info"
            if kind in (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR):
                level = "error"
            elif kind == linuxcnc.NML_TEXT:
                level = "warning"
            
            # Виводимо у ваш красивий список
            self.log_message(text, level)
    
    def show_message(self, title, message, icon_type="info"):
        """
        Універсальний метод для виведення діалогових вікон.
        icon_type: "info", "warning", "error"
        """
        msg = QtWidgets.QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
    
        # Вибір іконки
        if icon_type == "warning":
            msg.setIcon(QtWidgets.QMessageBox.Warning)
            print(f"DEBUG: [UI WARNING] {message}") # Дублюємо в консоль
        elif icon_type == "error":
            msg.setIcon(QtWidgets.QMessageBox.Critical)
            print(f"DEBUG: [UI ERROR] {message}")
        else:
            msg.setIcon(QtWidgets.QMessageBox.Information)
            print(f"DEBUG: [UI INFO] {message}")
        
        msg.exec_()
    
    def send_mdi(self, code):
        self.status.poll()
        # Запам'ятовуємо поточний режим перед перемиканням
        previous_mode = self.status.task_mode
        
        # Якщо ми вже не в MDI, перемикаємося
        if previous_mode != linuxcnc.MODE_MDI:
            self.command.mode(linuxcnc.MODE_MDI)
            self.command.wait_complete()
        
        # Виконуємо команду
        self.command.mdi(code)
        self.command.wait_complete() # Чекаємо завершення виконання команди
        
        # Повертаємо попередній режим (наприклад, Manual)
        if previous_mode != linuxcnc.MODE_MDI:
            self.command.mode(previous_mode)
            self.command.wait_complete()
            print(f"Виконано: {code} (повернено в попередній режим)")
    
    def on_btn_tool_arm_clicked(self):
        """Активація живлення серво-захвата (Safety Arm)"""
        is_armed = self.widgets.btn_tool_arm.isChecked()
        state_text = "ARMED" if is_armed else "DISARMED"
        
        # DEBUG LOG
        print(f"DEBUG: [GRIPPER] Safety Lock changed to: {state_text}")
        
        self.widgets.btn_tool_arm.setText(state_text)
        self.widgets.btn_tool_arm.setStyleSheet(self.STYLE_TOOL_ARMED if is_armed else self.STYLE_TOOL_DISARMED)
        
        if not is_armed:
            print("DEBUG: [GRIPPER] Safety Trigger: Forcing Release due to Disarm")
            self.widgets.btn_tool_action.setChecked(False)
            self.on_btn_tool_action_clicked()
            self.widgets.lbl_tool_status.setText("STATUS: LOCKED")
        else:
            self.widgets.lbl_tool_status.setText("STATUS: READY")
            
    def on_btn_tool_action_clicked(self):
        """Керування через кастомні команди: M101 (GRIP) та M102 (RELEASE)"""
        # Перевірка Arming (Safety Lock)
        if not self.widgets.btn_tool_arm.isChecked():
            print("DEBUG: [GRIPPER] Access Denied: Arm Tool first!")
            self.widgets.btn_tool_action.setChecked(False)
            return

        is_grip = self.widgets.btn_tool_action.isChecked()
        
        if is_grip:
            # Викликаємо M101 (Стиснення)
            self.send_mdi("M101")
            print("DEBUG: [GRIPPER] Executing MDI Command: M101 (GRIP)")
            
            self.widgets.btn_tool_action.setText("RELEASE")
            self.widgets.btn_tool_action.setStyleSheet(self.STYLE_GRIP_ACTIVE)
            self.widgets.lbl_tool_status.setText("STATUS: HOLDING")
        else:
            # Викликаємо M102 (Розтиснення)
            self.send_mdi("M102")
            print("DEBUG: [GRIPPER] Executing MDI Command: M102 (RELEASE)")
            
            self.widgets.btn_tool_action.setText("GRIP")
            self.widgets.btn_tool_action.setStyleSheet(self.STYLE_GRIP_INACTIVE)
            self.widgets.lbl_tool_status.setText("STATUS: OPEN")
            
    def on_sld_tool_power_changed(self, value):
        """Оновлення зусилля стискання (Force/Torque Limit)"""
        force_float = value / 100.0
        
        # Відправляємо сигнал у LinuxCNC
        # Analog Out 1: значення від 0.1 до 1.0
        self.command.set_analog_output(1, force_float)
        
        # DEBUG LOG (тільки при зміні на кожні 5 одиниць, щоб не спамити)
        if value % 5 == 0:
            print(f"DEBUG: [GRIPPER] Force Limit adjusted: {value}% | HAL Pin: motion.analog-out-01 = {force_float}")
        
        if hasattr(self.widgets, 'lbl_tool_power_val'):
            self.widgets.lbl_tool_power_val.setText(f"{value} %")
    
    def on_sld_feed_override_changed(self, value):
        """Feedrate Override (0-200%)"""
        # LinuxCNC приймає float, де 1.0 = 100%
        self.command.feedrate(value / 100.0)
        if hasattr(self.widgets, 'val_feed_override'):
            self.widgets.val_feed_override.setText(f"{value} %")

    def on_sld_rapid_override_changed(self, value):
        """Rapid Override (0-100%)"""
        # 1.0 = 100%
        self.command.rapidrate(value / 100.0)
        if hasattr(self.widgets, 'val_rapid_override'):
            self.widgets.val_rapid_override.setText(f"{value} %")

    def on_sld_spindle_override_changed(self, value):
        """Spindle Override (0-200%)"""
        self.command.spindleoverride(value / 100.0)
        if hasattr(self.widgets, 'val_spindle_override'):
            self.widgets.val_spindle_override.setText(f"{value} %")

    def on_sld_linear_changed(self, value):
        """Швидкість лінійного ручного переміщення (Jog)"""
        actual_value = value / 1000.0  # повертаємо до float
        # Цей параметр зазвичай зберігається локально в UI для команд jog
        self.linear_jog_speed = actual_value 
        if hasattr(self.widgets, 'val_linear_jog_speed'):
            self.widgets.val_linear_jog_speed.setText(f"{actual_value:.3f} in/min")

    def on_sld_angular_changed(self, value):
        """Швидкість кутового ручного переміщення"""
        actual_value = value / 100.0
        self.angular_jog_speed = actual_value
        if hasattr(self.widgets, 'val_angular_jog_speed'):
            self.widgets.val_angular_jog_speed.setText(f"{actual_value:.2f} deg/min")

    def on_sld_max_velocity_changed(self, value):
        """Обмеження максимальної швидкості (Max Velocity)"""
        try:
            # У LinuxCNC API команда називається maxvel
            # Значення передається в одиницях за секунду (мм/сек або дюйм/сек)
            self.command.maxvel(float(value))
        
            if hasattr(self.widgets, 'val_max_velocity'):
                self.widgets.val_max_velocity.setText(f"{value} in/min")
            
        except Exception as e:
            print(f"ERROR: Не вдалося встановити Max Velocity: {e}")
    
    def on_btn_file_save_as_clicked(self):
        """Збереження поточного G-коду у новий файл"""
        self.status.poll()
    
        # 1. Базові перевірки
        if not hasattr(self.widgets, 'list_gcode_view'):
            return
    
        model = self.widgets.list_gcode_view.model()
        if not model or model.rowCount() == 0:
            print("WARNING: Немає даних для збереження")
            return

        if self.status.interp_state != linuxcnc.INTERP_IDLE:
            print("WARNING: Неможливо зберегти файл під час виконання програми")
            return

        # 2. Відкриваємо діалог "Зберегти як"
        options = QFileDialog.Options()
        # Початковий шлях — папка поточного файлу або домашня директорія
        initial_path = os.path.dirname(self.last_loaded_file) if self.last_loaded_file else os.path.expanduser("~")
    
        new_filepath, _ = QFileDialog.getSaveFileName(
            None, 
            "Зберегти G-код як...", 
            initial_path, 
            "G-Code Files (*.ngc *.txt);;All Files (*)", 
            options=options
        )

        if new_filepath:
            try:
                # Якщо користувач не вказав розширення, додаємо .ngc
                if not new_filepath.endswith(('.ngc', '.txt')):
                    new_filepath += '.ngc'

                # 3. Збираємо текст із моделі
                gcode_content = []
                for i in range(model.rowCount()):
                    gcode_content.append(model.index(i, 0).data())

                # 4. Записуємо у файл
                with open(new_filepath, 'w', encoding='utf-8') as f:
                    f.write("\n".join(gcode_content))

                print(f"DEBUG: Файл збережено: {new_filepath}")

                # 5. Автоматично завантажуємо новий файл у LinuxCNC
                self.command.program_open(new_filepath)
                self.last_loaded_file = new_filepath
                self._load_gcode_to_view(new_filepath)
            
            except Exception as e:
                print(f"ERROR: Не вдалося зберегти файл: {e}")
    
    def on_btn_file_reload_clicked(self):
        """Перевантаження поточного файлу для оновлення змін"""
        self.status.poll()
    
        if not self.last_loaded_file:
            print("WARNING: Немає файлу для оновлення")
            return
        
        if self.status.interp_state != linuxcnc.INTERP_IDLE:
            print("WARNING: Неможливо оновити файл під час роботи!")
            return

        try:
            # 1. Скидаємо прапорець, щоб _update_gcode_display "подумав", що файл новий
            temp_path = self.last_loaded_file
            self.last_loaded_file = None 
        
            # 2. Перевідкриваємо файл у LinuxCNC
            self.command.program_open(temp_path)
        
            # 3. Примусово завантажуємо новий текст у в'юху
            self._load_gcode_to_view(temp_path)
            
            self.reload_needed = False
        
            print(f"DEBUG: Файл {os.path.basename(temp_path)} успішно оновлено")
        except Exception as e:
            print(f"ERROR: Помилка оновлення: {e}")
    
    def on_btn_file_edit_clicked(self):
        """Відкриття G-коду у текстовому редакторі (з обходом помилки асоціації файлів)"""
        self.status.poll()
    
        if not self.last_loaded_file or not os.path.exists(self.last_loaded_file):
            print("WARNING: Файл не знайдено")
            return

        if self.status.interp_state != linuxcnc.INTERP_IDLE:
            print("WARNING: Редагування заборонено під час виконання")
            return

        # Список редакторів для перевірки (від найбільш ймовірних у LinuxCNC збірках)
        editors = ['gedit', 'mousepad', 'leafpad', 'xed', 'nano']
    
        editor_found = False
        for editor in editors:
            # Перевіряємо, чи встановлений редактор у системі
            if subprocess.call(['which', editor], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                try:
                    subprocess.Popen([editor, self.last_loaded_file])
                    print(f"DEBUG: Відкрито через {editor}: {os.path.basename(self.last_loaded_file)}")
                    editor_found = True
                    break
                except Exception:
                    continue
    
        if not editor_found:
            print("ERROR: Не вдалося знайти встановлений текстовий редактор")
            
        if editor_found:
            self.reload_needed = True  # Активуємо прапорець
            if hasattr(self.widgets, 'btn_file_reload'):
                self.widgets.btn_file_reload.setStyleSheet(self.STYLE_GCODE_WARN)
            
    
    def on_btn_cycle_start_clicked(self):
        """Запуск програми (Виправлено для актуального LinuxCNC Python API)"""
        self.status.poll()
        if not self.status.file:
            print("WARNING: Файл не завантажено")
            return

        if not all(self.status.homed[:3]):
            print("WARNING: Виконайте Home All перед запуском програми")
            return

        try:
            # 1. Перемикаємо режим на AUTO
            self.command.mode(linuxcnc.MODE_AUTO)
            self.command.wait_complete()
        
            # 2. Використовуємо метод auto з константою AUTO_RUN
            # Параметр 0 — це номер рядка, з якого починати
            self.command.auto(linuxcnc.AUTO_RUN, 0)
        
            print(f"DEBUG: Запуск успішний: {os.path.basename(self.status.file)}")
        except Exception as e:
            print(f"ERROR: Помилка запуску: {e}")
    
    def on_btn_cycle_continue_clicked(self):
        """Відновлення руху після паузи (виправлено)"""
        self.status.poll()
    
        # Перевіряємо, чи ми дійсно на паузі
        if self.status.interp_state == linuxcnc.INTERP_PAUSED:
            try:
                # Важливо: НЕ перемикаємо режим на AUTO ще раз, якщо ми вже в ньому,
                # оскільки це може призвести до скидання (abort) виконання.
                if self.status.task_mode != linuxcnc.MODE_AUTO:
                    self.command.mode(linuxcnc.MODE_AUTO)
                    self.command.wait_complete()

                # Використовуємо AUTO_RESUME
                self.command.auto(linuxcnc.AUTO_RESUME)
                print("DEBUG: Виконання продовжено")
            except Exception as e:
                print(f"ERROR: Помилка відновлення: {e}")
        else:
            # Якщо ми не на паузі, але програма завантажена — можливо, треба просто Start?
            print("DEBUG: Станок не в стані PAUSE, команда RESUME ігнорується")

    def on_btn_cycle_pause_clicked(self):
        """Призупинення"""
        self.status.poll()
        if self.status.interp_state != linuxcnc.INTERP_IDLE:
            self.command.auto(linuxcnc.AUTO_PAUSE)
            print("DEBUG: Пауза (Feed Hold)")

    def on_btn_cycle_stop_clicked(self):
        """Повна зупинка з очищенням черги команд"""
        self.command.abort()
        self.command.wait_complete()
        self.command.mode(linuxcnc.MODE_MANUAL)
        print("DEBUG: Програму зупинено оператором")

    def on_btn_cycle_step_clicked(self):
        """Покрокове виконання (Step)"""
        self.status.poll()
    
        # Базові перевірки
        if not self.status.file:
            print("WARNING: Файл не завантажено")
            return
        if self.status.task_state != linuxcnc.STATE_ON:
            print("WARNING: Увімкніть живлення")
            return
        if not all(self.status.homed[:3]):
            print("WARNING: Виконайте Home All перед запуском програми")
            return


        try:
            # Перемикаємо в AUTO, якщо ми в іншому режимі
            if self.status.task_mode != linuxcnc.MODE_AUTO:
                self.command.mode(linuxcnc.MODE_AUTO)
                self.command.wait_complete()

            # Якщо програма стоїть (IDLE), Step працює як Start для першого рядка
            # Якщо програма на паузі або виконується, AUTO_STEP виконує наступний рядок
            self.command.auto(linuxcnc.AUTO_STEP)
            print("DEBUG: Виконано один крок (Step)")
        
        except Exception as e:
            print(f"ERROR: Помилка покрокового виконання: {e}")
    
    def _on_gcode_edited(self, topLeft, bottomRight, roles):
        # Додаємо перевірку стану перед записом
        self.status.poll()
        if self.status.interp_state != linuxcnc.INTERP_IDLE:
            print("WARNING: Спроба збереження під час роботи заблокована!")
            return

        if not self.last_loaded_file or not os.path.exists(self.last_loaded_file):
            return
        
        """Викликається автоматично після натискання Enter у рядку"""
        if not self.last_loaded_file or not os.path.exists(self.last_loaded_file):
            return

        try:
            model = self.widgets.list_gcode_view.model()
            all_lines = model.stringList()
        
            # Перезаписуємо файл
            with open(self.last_loaded_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(all_lines) + "\n")
        
            # Перевантажуємо файл у LinuxCNC, щоб він побачив зміни
            self.command.program_open(self.last_loaded_file)
            print(f"DEBUG: Файл {os.path.basename(self.last_loaded_file)} оновлено та збережено")
        
        except Exception as e:
            print(f"ERROR: Не вдалося зберегти зміни: {e}")
        
    def on_btn_file_open_clicked(self):
        """Відкриває діалог вибору файлу та передає його в LinuxCNC"""
        default_dir = os.path.expanduser("~/linuxcnc-dev/configs/sim/axis/nc_files")
        file_path, _ = QFileDialog.getOpenFileName(
            self.widgets.main_window if hasattr(self.widgets, 'main_window') else None,
            "Open G-Code File",
            default_dir,
            "G-Code Files (*.ngc *.txt *.gcode);;All Files (*)"
        )
    
        if file_path:
            try:
                self.command.program_open(file_path)
            except Exception as e:
                print(f"ERROR: Не вдалося завантажити файл: {e}")
    
    def _load_gcode_to_view(self, filepath):
        """Зчитує текст файлу та оновлює модель QListView"""
        if not os.path.exists(filepath):
            print(f"ERROR: Шлях {filepath} не знайдено")
            return

        # 1. Оновлюємо лейбл назви файлу
        if hasattr(self.widgets, 'lbl_filename'):
            self.widgets.lbl_filename.setText(os.path.basename(filepath))

        # 2. Оновлюємо вміст через модель
        if hasattr(self.widgets, 'list_gcode_view'):
            try:
                # Читаємо файл заново з диска
                with open(filepath, 'r', encoding='utf-8') as f:
                    # Очищуємо кожен рядок від зайвих символів перенесення
                    lines = [line.strip() for line in f.readlines()]
            
                # Створюємо нову модель зі свіжими даними
                model = QStringListModel()
                model.setStringList(lines)
            
                # Встановлюємо модель для в'юхи
                self.widgets.list_gcode_view.setModel(model)
            
                # Підключаємо сигнал редагування заново (якщо ви використовуєте збереження при правці в списку)
                model.dataChanged.connect(self._on_gcode_edited)
            
                print(f"DEBUG: Вікно G-коду оновлено ({len(lines)} рядків)")
            
            except Exception as e:
                print(f"ERROR: Помилка завантаження G-коду в модель: {e}")

    def _on_overlay_clicked(self, panel_type):
        # Перемикання дозволено лише якщо система готова і хомінг виконано
        homed_status = self.status.homed
        all_homed = all(homed_status[i] for i in range(min(6, len(homed_status))))
    
        if self.is_ready() and all_homed:
            self.manual_panel_selection = panel_type
            print(f"DEBUG: Користувач обрав панель: {panel_type}")
            self._update_panel_access() # Оновлюємо вигляд негайно

    def _connect_all_axis_buttons(self):
        """Підключення кнопок руху по осях (X, Y, Z, A, B, C)"""
        axes = ['x', 'y', 'z', 'a', 'b', 'c']
        for i, axis in enumerate(axes):
            btn_p = getattr(self.widgets, f"btn_{axis}_plus", None)
            if btn_p:
                btn_p.pressed.connect(self._make_axis_jog_handler(i, 1))
                btn_p.released.connect(self._make_axis_stop_handler(i))
            
            btn_m = getattr(self.widgets, f"btn_{axis}_minus", None)
            if btn_m:
                btn_m.pressed.connect(self._make_axis_jog_handler(i, -1))
                btn_m.released.connect(self._make_axis_stop_handler(i))

    def _make_axis_jog_handler(self, axis_idx, direction):
        return lambda: self.start_axis_jog(axis_idx, direction)

    def _make_axis_stop_handler(self, axis_idx):
        return lambda: self.stop_axis_jog(axis_idx)

    
    def start_axis_jog(self, axis_idx, direction):
        if not self.is_ready():
            return
            
        # Для руху по осях (World Mode) ТЕЛЕОП має бути включений
        try:
            self.status.poll()
            if self.status.task_mode != linuxcnc.MODE_MANUAL:
                self.command.mode(linuxcnc.MODE_MANUAL)
            
            # Вмикаємо телеоп режим (World Mode)
            self.command.teleop_enable(1)
            self.command.wait_complete()
        except Exception as e:
            print(f"ERROR Axis Sync: {e}")

        mode_text = "Continuous"
        if hasattr(self.widgets, 'combo_axis_mode'):
            mode_text = self.widgets.combo_axis_mode.currentText()

        try:
            if mode_text == "Continuous":
                vel = float(direction) * (self.SPEED / 60.0)
                self.command.jog(linuxcnc.JOG_CONTINUOUS, 0, axis_idx, vel)
            else:
                increment = float(mode_text)
                vel = (self.SPEED / 60.0)
                self.command.jog(linuxcnc.JOG_INCREMENT, 0, axis_idx, float(direction) * vel, increment)
        except Exception as e:
            print(f"ERROR Axis Jog: {e}")
            
    def stop_axis_jog(self, axis_idx):
        mode_text = "Continuous"
        if hasattr(self.widgets, 'combo_axis_mode'):
            mode_text = self.widgets.combo_axis_mode.currentText()
            
        if mode_text != "Continuous":
            return

        try:
            self.command.jog(linuxcnc.JOG_STOP, 0, axis_idx)
        except Exception as e:
            print(f"ERROR Axis Stop: {e}")
    
    def _connect_all_jog_buttons(self):
        """Автоматичне підключення кнопок руху за шаблоном назв у UI"""
        for j in range(6):
            btn_p = getattr(self.widgets, f"btn_j{j}_plus", None)
            if btn_p:
                btn_p.pressed.connect(self._make_jog_handler(j, 1))
                btn_p.released.connect(self._make_stop_handler(j))
            
            btn_m = getattr(self.widgets, f"btn_j{j}_minus", None)
            if btn_m:
                btn_m.pressed.connect(self._make_jog_handler(j, -1))
                btn_m.released.connect(self._make_stop_handler(j))

    def _make_jog_handler(self, joint, direction):
        return lambda: self.start_jog(int(joint), direction)

    def _make_stop_handler(self, joint):
        return lambda: self.stop_jog(int(joint))

    def is_ready(self):
        try:
            self.status.poll()
            return not self.status.estop and (self.status.task_state == linuxcnc.STATE_ON)
        except:
            return False

    def sync_modes(self):
        try:
            self.status.poll()
            if self.status.task_mode != linuxcnc.MODE_MANUAL:
                self.command.mode(linuxcnc.MODE_MANUAL)
                self.command.wait_complete()
            
            self.command.teleop_enable(self.TELEOP_ENABLE_VAL)
            self.command.wait_complete()
        except Exception as e:
            print(f"ERROR: Помилка синхронізації режимів: {e}")

    def start_jog(self, joint, direction):
        if not self.is_ready():
            return
            
        self.sync_modes()
        
        # Визначення режиму джога з ComboBox
        mode_text = "Continuous"
        if hasattr(self.widgets, 'combo_joint_mode'):
            mode_text = self.widgets.combo_joint_mode.currentText()

        try:
            if mode_text == "Continuous":
                # Безперервний рух
                vel = float(direction) * (self.SPEED / 60.0)
                self.command.jog(linuxcnc.JOG_CONTINUOUS, self.JOG_CMD_FLAG, int(joint), vel)
            else:
                # Інкрементальний рух (крок)
                increment = float(mode_text)
                vel = (self.SPEED / 60.0)
                self.command.jog(linuxcnc.JOG_INCREMENT, self.JOG_CMD_FLAG, int(joint), float(direction) * vel, increment)
                
            print(f"DEBUG: JOG J{joint} | Mode: {mode_text} | Dir: {direction}")
        except Exception as e:
            print(f"ERROR: Помилка джога J{joint}: {e}")

    def stop_jog(self, joint):
        # Зупинку викликаємо ТІЛЬКИ для безперервного режиму.
        # В інкрементальному режимі LinuxCNC сам завершить крок.
        mode_text = "Continuous"
        if hasattr(self.widgets, 'combo_joint_mode'):
            mode_text = self.widgets.combo_joint_mode.currentText()
            
        if mode_text != "Continuous":
            return

        try:
            self.command.jog(linuxcnc.JOG_STOP, self.JOG_CMD_FLAG, int(joint))
            print(f"DEBUG: Зупинка J{joint} (Continuous mode)")
        except Exception as e:
            print(f"ERROR: Помилка зупинки джога J{joint}: {e}")
    
    def update__(self):
        try:
            self.status.poll()
            self._update_coordinates()
            self._update_machine_state()
            self._update_panel_access()
            self._update_status_display()
            self._update_joint_positions()
            self._handle_joint_soft_limits() 
            self._update_gcode_display()
            self._update_cycle_buttons()
            self._update_file_buttons()
            self._update_settings_display()
            self._update_active_gcodes()
        except Exception as e:
            pass

    def _update_active_gcodes(self):
        """Оновлення G/M кодів та значень F/S у статусбарі"""
        if hasattr(self.widgets, 'txt_gcodeStatusBar'):
            self.status.poll()
        
            # 1. Збір G-кодів
            active_codes = []
            for code in self.status.gcodes:
                if code == -1: continue
                g_prefix = f"G{code/10.0:g}" if code >= 0 else ""
                if g_prefix: active_codes.append(g_prefix)
        
            # 2. Збір M-кодів
            active_m_codes = []
            for m_code in self.status.mcodes:
                if m_code == -1: continue
                active_m_codes.append(f"M{m_code}")

            # 3. Отримання значень F та S
            # Встановлена подача (задана в G-коді)
            f_set = self.status.settings[1] 
            # Встановлені оберти шпинделя
            s_set = self.status.settings[2]
        
            # Формуємо рядок параметрів
            fs_status = f"F{f_set:.0f} S{s_set:.0f}"

            # 4. Формування фінального рядка
            # Вигляд: G1 G17 G54 | M3 M8 | F1000 S2500
            full_status = f"{' '.join(active_codes)} {' '.join(active_m_codes)} {fs_status}"
        
            # Оновлюємо текст тільки якщо він змінився
            if self.widgets.txt_gcodeStatusBar.text() != full_status:
                self.widgets.txt_gcodeStatusBar.setText(full_status)
    
    def _update_settings_display(self):
        """Зчитування поточних налаштувань з LinuxCNC та оновлення UI"""
        self.status.poll()
    
        # Оновлення Feed Override
        f_ovr = int(self.status.feedrate * 100)
        if hasattr(self.widgets, 'sld_feed_override') and not self.widgets.sld_feed_override.isSliderDown():
            self.widgets.sld_feed_override.setValue(f_ovr)
    
        # Оновлення Spindle Override
        s_ovr = int(self.status.spindle[0]['override'] * 100)
        if hasattr(self.widgets, 'sld_spindle_override') and not self.widgets.sld_spindle_override.isSliderDown():
            self.widgets.sld_spindle_override.setValue(s_ovr)

        # Оновлення Rapid Override
        r_ovr = int(self.status.rapidrate * 100)
        if hasattr(self.widgets, 'sld_rapid_override') and not self.widgets.sld_rapid_override.isSliderDown():
            self.widgets.sld_rapid_override.setValue(r_ovr)
    
    def _update_file_buttons(self):
        """Оновлення станів та стилів кнопок керування файлами"""
        self.status.poll()
        is_idle = (self.status.interp_state == linuxcnc.INTERP_IDLE)
        has_file = bool(self.status.file)

        # 1. Кнопка RELOAD (з підтримкою статусу попередження)
        if hasattr(self.widgets, 'btn_file_reload'):
            can_reload = is_idle and has_file
            self.widgets.btn_file_reload.setEnabled(can_reload)
        
            # Пріоритет стилів: 
            # Якщо потрібне оновлення -> WARN
            # Якщо просто доступна -> ACTIVE
            # Якщо недоступна -> INACTIVE
            if can_reload and getattr(self, 'reload_needed', False):
                style = self.STYLE_GCODE_WARN
            elif can_reload:
                style = self.STYLE_GCODE_ACTIVE
            else:
                style = self.STYLE_GCODE_INACTIVE
            
            self.widgets.btn_file_reload.setStyleSheet(style)

        # 2. Кнопка EDIT
        if hasattr(self.widgets, 'btn_file_edit'):
            can_edit = is_idle and has_file
            self.widgets.btn_file_edit.setEnabled(can_edit)
            self.widgets.btn_file_edit.setStyleSheet(
                self.STYLE_GCODE_ACTIVE if can_edit else self.STYLE_GCODE_INACTIVE
            )

        # 3. Кнопка SAVE AS
        if hasattr(self.widgets, 'btn_file_save_as'):
            has_content = False
            if hasattr(self.widgets, 'list_gcode_view'):
                model = self.widgets.list_gcode_view.model()
                has_content = model is not None and model.rowCount() > 0
            
            can_save = is_idle and has_content
            self.widgets.btn_file_save_as.setEnabled(can_save)
            self.widgets.btn_file_save_as.setStyleSheet(
                self.STYLE_GCODE_ACTIVE if can_save else self.STYLE_GCODE_INACTIVE
            )
        
    def _update_gcode_display(self):
        """Комплексне оновлення G-коду"""
        self.status.poll()
        current_file = self.status.file

        # 1. ПЕРЕВІРКА ЗМІНИ ФАЙЛУ
        if not current_file:
            if self.last_loaded_file is not None:
                self.last_loaded_file = None
                if hasattr(self.widgets, 'lbl_filename'): self.widgets.lbl_filename.setText("No file")
                if hasattr(self.widgets, 'list_gcode_view'): self.widgets.list_gcode_view.setModel(None)
    
        # Видаляємо жорстку перевірку elif, яка блокувала Reload
        elif current_file != self.last_loaded_file:
            self.last_loaded_file = current_file
            self._load_gcode_to_view(current_file)

        # 2. ЛОГІКА ВІДОБРАЖЕННЯ ТА ПІДСВІЧУВАННЯ
        if hasattr(self.widgets, 'list_gcode_view'):
            model = self.widgets.list_gcode_view.model()
            if not model: return # Якщо моделі немає, далі йти не треба
        
            is_idle = (self.status.interp_state == linuxcnc.INTERP_IDLE)

            # Редагування дозволено тільки в IDLE
            self.widgets.list_gcode_view.setEditTriggers(
                (self.widgets.list_gcode_view.DoubleClicked | self.widgets.list_gcode_view.AnyKeyPressed) 
                if is_idle else self.widgets.list_gcode_view.NoEditTriggers
            )

            # Підсвічування активного рядка
            if not is_idle:
                line_number = self.status.motion_line
                if 0 <= line_number < model.rowCount():
                    index = model.index(line_number, 0)
                    # scroll_to та setCurrentIndex працюють плавно
                    self.widgets.list_gcode_view.setCurrentIndex(index)
                    self.widgets.list_gcode_view.scrollTo(index)
        
        # РОЗРАХУНОК ПРОГРЕСУ
        if hasattr(self.widgets, 'lbl_progress_percent') and hasattr(self.widgets, 'list_gcode_view'):
            model = self.widgets.list_gcode_view.model()
        
            if model and model.rowCount() > 0:
                total_lines = model.rowCount()
                # Додаємо +1 до поточного рядка, бо індексація з 0
                # Тобто коли ми на останньому рядку (total_lines - 1), 
                # з додаванням +1 ми отримаємо total_lines / total_lines = 100%
                current_line = self.status.motion_line + 1
            
                # Якщо станок в IDLE і програма не була запущена (motion_line <= 0)
                if self.status.interp_state == linuxcnc.INTERP_IDLE and self.status.motion_line <= 0:
                    percent = 0
                # Якщо станок завершив програму (IDLE) і був на останніх рядках
                elif self.status.interp_state == linuxcnc.INTERP_IDLE and self.status.motion_line >= total_lines - 2:
                    percent = 100
                else:
                    percent = int((current_line / total_lines) * 100)
                    percent = min(100, max(0, percent))
            
                self.widgets.lbl_progress_percent.setText(f"PROGRESS {percent}%")
            else:
                self.widgets.lbl_progress_percent.setText("PROGRESS 0%")
                
    def _load_gcode_to_view(self, filepath):
        if hasattr(self.widgets, 'lbl_filename'):
            self.widgets.lbl_filename.setText(os.path.basename(filepath))

        if hasattr(self.widgets, 'list_gcode_view'):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = [line.strip() for line in f.readlines()]
            
                model = QStringListModel()
                model.setStringList(lines)
                self.widgets.list_gcode_view.setModel(model)
            
                # Дозволяємо редагування подвійним кліком або Enter
                self.widgets.list_gcode_view.setEditTriggers(
                    self.widgets.list_gcode_view.DoubleClicked | 
                    self.widgets.list_gcode_view.EditKeyPressed
                )
                # Підключаємо сигнал завершення редагування
                model.dataChanged.connect(self._on_gcode_edited)
            
            except Exception as e:
                print(f"ERROR: Reading G-code failed: {e}")
                
        if hasattr(self.widgets, 'lbl_progress_percent'):
            self.widgets.lbl_progress_percent.setText("PROGRESS 0%")
    
    def _handle_joint_soft_limits(self):
        """Перевірка лімітів суглобів та блокування відповідних кнопок"""
        if not self.is_ready():
            return

        j_pos = self.status.joint_actual_position
        for i in range(min(6, len(j_pos))):
            limits = self.JOINT_LIMITS.get(i)
            if not limits: continue
            
            curr_pos = j_pos[i]
            btn_plus = getattr(self.widgets, f"btn_j{i}_plus", None)
            btn_minus = getattr(self.widgets, f"btn_j{i}_minus", None)
            
            # Перевірка для кнопки Плюс (+)
            if btn_plus:
                at_max = curr_pos >= limits["max"]
                btn_plus.setEnabled(not at_max)
                btn_plus.setStyleSheet(self.STYLE_JOG_LIMITED if at_max else self.STYLE_JOG_ACTIVE)
                
            # Перевірка для кнопки Мінус (-)
            if btn_minus:
                at_min = curr_pos <= limits["min"]
                btn_minus.setEnabled(not at_min)
                btn_minus.setStyleSheet(self.STYLE_JOG_LIMITED if at_min else self.STYLE_JOG_ACTIVE)

    def _update_joint_positions(self):
        try:
            j_pos = self.status.joint_actual_position
            for i in range(min(6, len(j_pos))):
                label = getattr(self.widgets, f"txt_j{i}_pos", None)
                if label:
                    label.setText(f"{j_pos[i]:.4f}")
                
                curr = j_pos[i]
                prev = self.last_joint_pos.get(i, 0.0)
                if abs(curr - prev) > 0.0005:
                    self.last_joint_pos[i] = curr
        except:
            pass

    def _update_coordinates(self):
        p = self.status.actual_position
        j = self.status.joint_actual_position
        axes = ['x', 'y', 'z', 'a', 'b', 'c']
        for i, axis in enumerate(axes):
            w = getattr(self.widgets, f'txt_{axis}_pos', None)
            if w and i < len(p): w.setText(f"{p[i]:.4f}")
        for i in range(6):
            w = getattr(self.widgets, f"txt_j{i}_pos", None)
            if w: 
                val = j[i] if i < len(j) else 0.0
                w.setText(f"{val:.4f}")

    def _update_machine_state(self):
        estop = (self.status.estop == linuxcnc.STATE_ESTOP)
        power_on = (self.status.task_state == linuxcnc.STATE_ON)
        
        if hasattr(self.widgets, 'btn_estop'):
            self.widgets.btn_estop.setStyleSheet(self.STYLE_ESTOP_ON if estop else self.STYLE_ESTOP_OFF)
        
        if hasattr(self.widgets, 'btn_power_off'):
            btn = self.widgets.btn_power_off
            btn.setEnabled(not estop)
            btn.setStyleSheet(self.STYLE_POWER_ON if power_on and not estop else self.STYLE_POWER_OFF)
            btn.setText("ON" if power_on else "OFF")
        
        # Приклад логіки для кнопок циклу
        is_auto = (self.status.task_mode == linuxcnc.MODE_AUTO)
        is_running = (self.status.interp_state != linuxcnc.INTERP_IDLE)

        if hasattr(self.widgets, 'btn_cycle_start'):
            # Кнопка Start активна тільки якщо ми не в процесі руху або на паузі
            can_start = self.status.interp_state in [linuxcnc.INTERP_IDLE, linuxcnc.INTERP_PAUSED]
            self.widgets.btn_cycle_start.setEnabled(can_start)

    def _update_panel_access(self):
        """Оновлення доступу до панелей залежно від стану станка та виконання програми"""
        self.status.poll()
        power_on = (self.status.task_state == linuxcnc.STATE_ON)
        estop_off = (self.status.estop != linuxcnc.STATE_ESTOP)
        homed_status = self.status.homed
        all_homed = all(homed_status[i] for i in range(min(6, len(homed_status))))
        is_ready = power_on and estop_off
        
        # Перевірка, чи виконується зараз програма або вона на паузі
        is_running = (self.status.interp_state != linuxcnc.INTERP_IDLE)

        # ЛОГІКА БЛОКУВАННЯ:
        if not is_ready or is_running:
            # Якщо станок не готовий АБО виконується G-код — блокуємо обидві панелі
            show_joints = False
            show_axis = False
        elif not all_homed:
            # Якщо готові, але не захомлені — тільки Joint
            show_joints = True
            show_axis = False
        else:
            # Якщо все готово і захомлено — повертаємо панель, яку обрав користувач
            show_joints = (self.manual_panel_selection == "joint")
            show_axis = (self.manual_panel_selection == "axis")

        if hasattr(self.widgets, 'btn_home_all'):
            self.widgets.btn_home_all.setEnabled(is_ready)
            self.widgets.btn_home_all.setStyleSheet(self.STYLE_HOME_READY if is_ready else self.STYLE_HOME_INACTIVE)
        
        # Оновлення інтерфейсу та оверлеїв для Joint
        self._apply_panel_style('joint_control', show_joints)
        if hasattr(self.widgets, 'joint_control_overlay'):
            self.widgets.joint_control_overlay.setVisible(not show_joints)

        # Оновлення інтерфейсу та оверлеїв для Axis
        self._apply_panel_style('axis_control', show_axis)
        if hasattr(self.widgets, 'axis_control_overlay'):
            self.widgets.axis_control_overlay.setVisible(not show_axis)

        # Керування панеллю G-code (доступна тільки в готовності)
        self._apply_panel_style('gcode_control', is_ready)
        if hasattr(self.widgets, 'gcode_control_overlay'):
            self.widgets.gcode_control_overlay.setVisible(not is_ready)
        
        # Блокування окремих кнопок G-code (опціонально, якщо потрібно блокувати Edit під час роботи)
        for btn_name in self.gcode_buttons:
            btn = getattr(self.widgets, btn_name, None)
            if btn:
                btn.setEnabled(is_ready)
                btn.setStyleSheet(self.STYLE_GCODE_ACTIVE if is_ready else self.STYLE_GCODE_INACTIVE)
                
        # Логіка для панелі інструменту
        tool_ready = power_on and estop_off and all_homed
        
        # Якщо E-STOP натиснуто — скидаємо все в нуль
        if not estop_off:
            if self.widgets.btn_tool_arm.isChecked():
                self.widgets.btn_tool_arm.setChecked(False)
                self.on_btn_tool_arm_clicked()
        
        # Блокуємо зміну захвата під час виконання G-коду (якщо не активовано Override)
        can_manual_grip = tool_ready and not is_running
        self.widgets.btn_tool_action.setEnabled(can_manual_grip)
        self.widgets.sld_tool_power.setEnabled(can_manual_grip)

    def _update_cycle_buttons(self):
        self.status.poll()
        state = self.status.interp_state
    
        is_idle = (state == linuxcnc.INTERP_IDLE)
        is_paused = (state == linuxcnc.INTERP_PAUSED)
        is_running = (state == linuxcnc.INTERP_READING or state == linuxcnc.INTERP_WAITING)
    
        has_file = bool(self.status.file)
        is_ready = (self.status.task_state == linuxcnc.STATE_ON and 
                self.status.estop != linuxcnc.STATE_ESTOP)

        # Логіка для Step: активна завжди, коли є файл і живлення, 
        # незалежно від того, чи ми стоїмо, чи на паузі.
        can_step = has_file and is_ready
        self._set_btn_state('btn_cycle_step', can_step)

        # Решта кнопок (за вашим запитом)
        self._set_btn_state('btn_cycle_start', is_idle and has_file and is_ready)
        self._set_btn_state('btn_cycle_continue', is_paused and is_ready)
        self._set_btn_state('btn_cycle_pause', is_running and is_ready)
        self._set_btn_state('btn_cycle_stop', (is_running or is_paused) and is_ready)
    
    def _set_btn_state(self, btn_name, is_active):
        """Допоміжний метод для застосування стилів"""
        btn = getattr(self.widgets, btn_name, None)
        if btn:
            btn.setEnabled(is_active)
            btn.setStyleSheet(self.STYLE_GCODE_ACTIVE if is_active else self.STYLE_GCODE_INACTIVE)
    
    def _update_status_display(self):
        if not hasattr(self.widgets, 'txt_status_display'): return
        msg = "SYSTEM READY"
        if self.status.estop == linuxcnc.STATE_ESTOP:
            msg = "EMERGENCY STOP"
        elif self.status.task_state != linuxcnc.STATE_ON:
            msg = "POWER OFF"
        elif not all(self.status.homed[i] for i in range(min(6, len(self.status.homed)))):
            msg = "HOMING REQUIRED"
        self.widgets.txt_status_display.setText(msg)

    def on_btn_home_all_clicked(self):
        if self.status.task_state != linuxcnc.STATE_ON: return
        
        homed_status = self.status.homed
        all_homed = all(homed_status[i] for i in range(min(6, len(homed_status))))
        
        if all_homed:
            msg = QMessageBox(self.widgets.main_window if hasattr(self.widgets, 'main_window') else None)
            msg.setWindowTitle("Warning")
            msg.setText("Joint is already homed, are you sure you want to re-home?")
            msg.setInformativeText("This will reset current coordinates and may cause unexpected motion.")
            msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            msg.setDefaultButton(QMessageBox.Cancel)
            msg.setStyleSheet(self.STYLE_MSGBOX)
            
            reply = msg.exec_()
            if reply == QMessageBox.Cancel:
                return 

        self.command.mode(linuxcnc.MODE_MANUAL)
        self.command.teleop_enable(0)
        self.command.home(int(-1)) 

    def _apply_panel_style(self, prefix, is_active):
        lbl = getattr(self.widgets, f"lbl_{prefix}", None)
        frm = getattr(self.widgets, f"frm_{prefix}", None)
        if lbl: lbl.setStyleSheet(self.PANEL_LABEL_ACTIVE if is_active else self.PANEL_LABEL_INACTIVE)
        if frm: frm.setStyleSheet(self.PANEL_FRAME_ACTIVE if is_active else self.PANEL_FRAME_INACTIVE)

    def on_btn_estop_clicked(self):
        self.status.poll()
        if self.status.estop == linuxcnc.STATE_ESTOP:
            self.command.state(linuxcnc.STATE_ESTOP_RESET)
        else:
            self.command.state(linuxcnc.STATE_ESTOP)

    def on_btn_power_off_clicked(self):
        self.status.poll()
        if self.status.task_state == linuxcnc.STATE_ON:
            self.command.state(linuxcnc.STATE_OFF)
            self.homing_complete_shown = False 
        else:
            self.command.state(linuxcnc.STATE_ON)

def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]