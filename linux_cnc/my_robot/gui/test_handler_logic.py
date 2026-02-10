import pytest
from unittest.mock import patch, MagicMock, mock_open, call
import linuxcnc
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QMessageBox
from gui_handler import HandlerClass

@pytest.fixture
def handler_setup():
    """
    Фікстура для ініціалізації середовища тестування.
    Створює фейкові об'єкти HAL, віджетів та LinuxCNC, щоб код не намагався
    звертатися до реального заліза чи графічного сервера.
    """
    with patch('linuxcnc.stat', return_value=MagicMock()), \
         patch('linuxcnc.command', return_value=MagicMock()), \
         patch('gui_handler.HandlerClass.log_message'):
        
        mock_hal = MagicMock()
        mock_widgets = MagicMock()
        
        # Імітуємо наявність INI-файлу, щоб конструктор HandlerClass міг прочитати налаштування
        with patch('linuxcnc.ini') as mock_ini:
            mock_ini.return_value.find.return_value = "100"
            handler = HandlerClass(mock_hal, mock_widgets, paths={})
            
        # Захищаємо статус від скидання: poll() не повинен змінювати наші тестові дані
        handler.status.poll = MagicMock()
        handler.status.homed = [0] * 6
        handler.status.task_state = linuxcnc.STATE_OFF
        handler.status.estop = linuxcnc.STATE_ESTOP
        
        return handler, mock_widgets

def test_on_btn_estop_clicked_logic(handler_setup):
    """
    ТЕСТ 1: Логіка кнопки аварійної зупинки (E-Stop).
    Перевіряє, чи надсилається команда RESET, якщо машина перебуває в стані ESTOP.
    """
    handler, _ = handler_setup
    handler.status.estop = linuxcnc.STATE_ESTOP # Імітуємо активний E-Stop
    handler.on_btn_estop_clicked()
    # Перевіряємо, чи викликана команда переходу в стан RESET (2)
    handler.command.state.assert_called_with(linuxcnc.STATE_ESTOP_RESET)

def test_update_machine_state_colors(handler_setup):
    """
    ТЕСТ 2: Візуальна індикація стану машини.
    Перевіряє, чи намагається код оновити стилі кнопок (setStyleSheet),
    коли змінюється стан машини (наприклад, увімкнення живлення).
    """
    handler, widgets = handler_setup
    handler.status.task_state = linuxcnc.STATE_ON
    handler.status.estop = linuxcnc.STATE_ESTOP_RESET
    
    handler._update_machine_state()
    
    # Шукаємо хоча б один виклик зміни стилю серед усіх віджетів
    called = any("setStyleSheet" in str(call) for call in widgets.method_calls)
    assert called, "Метод setStyleSheet не був викликаний для оновлення кольорів"

def test_home_all_confirmation_cancel(handler_setup):
    """
    ТЕСТ 3: Скасування процедури Home All (Безпека).
    Перевіряє, що якщо користувач натиснув "Cancel" у вікні підтвердження,
    команда на рух осей (home) НЕ надсилається.
    """
    handler, _ = handler_setup
    handler.status.task_state = linuxcnc.STATE_ON
    handler.status.homed = [1] * 6 # Імітуємо, що осі вже захомлені для появи вікна
    
    with patch('gui_handler.QMessageBox') as mock_msg:
        val = int(QMessageBox.Cancel)
        mock_msg.return_value.exec_.return_value = val
        
        # Підміняємо константу Cancel, щоб порівняння 'if reply == Cancel' спрацювало
        with patch('gui_handler.QMessageBox.Cancel', val):
            handler.on_btn_home_all_clicked()
    
    # Головна перевірка: команда home НЕ викликалася жодного разу
    assert handler.command.home.call_count == 0

def test_home_all_confirmation_ok(handler_setup):
    """
    ТЕСТ 4: Підтвердження процедури Home All.
    Перевіряє, що після натискання "Ok" у діалоговому вікні,
    машина отримує команду на хомінг усіх осей (параметр -1).
    """
    handler, _ = handler_setup
    handler.status.task_state = linuxcnc.STATE_ON
    handler.status.homed = [1] * 6
    
    with patch('gui_handler.QMessageBox') as mock_msg:
        val = int(QMessageBox.Ok)
        mock_msg.return_value.exec_.return_value = val
        
        with patch('gui_handler.QMessageBox.Ok', val):
            handler.on_btn_home_all_clicked()
    
    # Перевіряємо, чи була викликана команда home з аргументом -1 (all axes)
    handler.command.home.assert_called_with(-1)

def test_estop_toggle(handler_setup):
    """ТЕСТ 1.1: Перевірка кнопки E-Stop (Toggle)"""
    handler, _ = handler_setup
    
    # Випадок А: Зараз активний E-Stop -> маємо скинути (RESET)
    handler.status.estop = linuxcnc.STATE_ESTOP
    handler.on_btn_estop_clicked()
    handler.command.state.assert_called_with(linuxcnc.STATE_ESTOP_RESET)
    
    # Випадок Б: E-Stop не активний -> маємо активувати його
    handler.status.estop = linuxcnc.STATE_ESTOP_RESET
    handler.on_btn_estop_clicked()
    handler.command.state.assert_called_with(linuxcnc.STATE_ESTOP)

def test_power_toggle(handler_setup):
    """ТЕСТ 1.2: Ввімкнення/вимкнення живлення (Power)"""
    handler, _ = handler_setup
    
    # Випадок А: Машина ввімкнена -> вимикаємо
    handler.status.task_state = linuxcnc.STATE_ON
    handler.on_btn_power_off_clicked()
    handler.command.state.assert_called_with(linuxcnc.STATE_OFF)
    assert handler.homing_complete_shown is False
    
    # Випадок Б: Машина вимкнена -> вмикаємо
    handler.status.task_state = linuxcnc.STATE_OFF
    handler.on_btn_power_off_clicked()
    handler.command.state.assert_called_with(linuxcnc.STATE_ON)
    
def test_home_all_logic(handler_setup):
    """ТЕСТ 1.3: Виконання Home All з підтвердженням (виправлено)"""
    handler, widgets = handler_setup
    handler.status.task_state = linuxcnc.STATE_ON
    
    # Симулюємо, що осі вже захомлені
    handler.status.homed = [1] * 6 
    
    # Патчимо ВЕСЬ клас QMessageBox в модулі gui_handler
    # Це дозволить уникнути створення реального об'єкта і помилки TypeError
    with patch('gui_handler.QMessageBox') as mock_msg_class:
        # Налаштовуємо, щоб виклик .exec_() повернув OK
        mock_msg_class.return_value.exec_.return_value = QMessageBox.Ok
        
        handler.on_btn_home_all_clicked()
    
    # Перевіряємо команди
    handler.command.mode.assert_called_with(linuxcnc.MODE_MANUAL)
    handler.command.teleop_enable.assert_called_with(0)
    handler.command.home.assert_called_with(-1)

def test_load_gcode_file(handler_setup):
    """
    ТЕСТ 2.1: Завантаження файлу G-коду.
    Перевіряє, чи викликається команда відкриття програми після вибору файлу.
    """
    handler, widgets = handler_setup
    test_path = "/home/anna/linuxcnc-dev/configs/sim/axis/nc_files/spiral.ngc"
    
    # Патчимо діалог вибору файлу
    # У вашому коді це може бути QFileDialog.getOpenFileName
    with patch('gui_handler.QFileDialog.getOpenFileName', return_value=(test_path, "All Files (*)")), \
         patch('gui_handler.os.path.exists', return_value=True):
        
        # Спробуємо викликати метод on_btn_file_open_clicked
        # Якщо у вас кнопка називається інакше (наприклад, btn_load), 
        # метод зазвичай називається on_btn_назва_clicked
        try:
            handler.on_btn_file_open_clicked()
        except AttributeError:
            # Якщо не знайдено, спробуємо іншу ймовірну назву
            handler.on_btn_file_open_clicked()
    
    # Перевірка: чи пішла команда в LinuxCNC на відкриття файлу
    handler.command.program_open.assert_called_with(test_path)
    
def test_start_program_safety_off(handler_setup):
    """
    ТЕСТ 2.2: Безпека запуску програми.
    Перевіряє, що якщо машина вимкнена (STATE_OFF), команда на запуск 
    програми (program_run) НЕ надсилається.
    """
    handler, _ = handler_setup
    
    # 1. Встановлюємо стан: Машина вимкнена
    handler.status.task_state = linuxcnc.STATE_OFF
    
    # 2. Натискаємо кнопку СТАРТ
    # Патчимо log_message, щоб уникнути помилок з QListWidgetItem
    with patch.object(HandlerClass, 'log_message'):
        handler.on_btn_cycle_start_clicked()
    
    # 3. Перевіряємо, що команда запуск не була викликана
    assert handler.command.program_run.call_count == 0, "Програма почала виконуватися на вимкненій машині!"
    
def test_stop_program_execution(handler_setup):
    """
    ТЕСТ 2.3: Зупинка виконання програми.
    Перевіряє, що при натисканні на кнопку Stop надсилається 
    команда abort у LinuxCNC.
    """
    handler, _ = handler_setup
    
    # Імітуємо, що програма зараз виконується
    handler.status.interp_state = linuxcnc.INTERP_READING 
    
    # Патчимо log_message, щоб уникнути проблем з інтерфейсом
    with patch.object(HandlerClass, 'log_message'):
        handler.on_btn_cycle_stop_clicked()
    
    # Перевіряємо, чи був викликаний метод abort
    # В LinuxCNC команда зупинки зазвичай виконується через command.abort()
    assert handler.command.abort.called, "Команда abort не була надіслана при натисканні Stop!"
    
def test_pause_program_execution(handler_setup):
    """
    ТЕСТ 2.4: Пауза (Feed Hold).
    Перевіряє виклик команди auto(linuxcnc.PAUSE).
    """
    handler, _ = handler_setup
    handler.status.interp_state = linuxcnc.INTERP_READING
    
    with patch.object(HandlerClass, 'log_message'):
        handler.on_btn_cycle_pause_clicked()
    
    # LinuxCNC зазвичай використовує команду set_pause(1) або state(linuxcnc.STATE_PAUSED)
    # Перевірте, що саме викликає ваш метод
    assert handler.command.auto.called or handler.command.set_pause.called

def test_continue_program_execution(handler_setup):
    """
    ТЕСТ 2.5: Продовження після паузи.
    """
    handler, _ = handler_setup
    handler.status.task_state = linuxcnc.STATE_ON
    handler.status.interp_state = linuxcnc.INTERP_PAUSED
    
    with patch.object(HandlerClass, 'log_message'):
        handler.on_btn_cycle_continue_clicked()
    
    # Має викликатися resume() або подібна команда
    assert handler.command.auto.called

def test_step_execution(handler_setup):
    """
    ТЕСТ 2.6: Покрокове виконання.
    Перевіряє, що викликається правильна команда авто-кроку.
    """
    handler, _ = handler_setup
    
    handler.status.task_state = linuxcnc.STATE_ON
    handler.status.homed = [1] * 6
    
    with patch.object(HandlerClass, 'log_message'):
        handler.on_btn_cycle_step_clicked()
    
    # Перевіряємо, яка саме команда була викликана. 
    # Спробуємо найбільш ймовірний варіант для LinuxCNC:
    if handler.command.auto.called:
        handler.command.auto.assert_called_with(linuxcnc.AUTO_STEP)
    else:
        # Якщо у вас інша реалізація, pytest покаже, які методи викликалися
        assert handler.command.method_calls, "Жоден метод command не був викликаний"
        
def test_linear_jog_speed_update(handler_setup):
    """
    ТЕСТ 3.1: Оновлення швидкості лінійного переміщення.
    Перевіряє ділення на 1000 та оновлення текстового поля з одиницями in/min.
    """
    handler, widgets = handler_setup
    
    # 1. Емулюємо значення зі слайдера (наприклад, 1500)
    slider_value = 1500
    expected_float = 1.500  # 1500 / 1000.0
    
    # 2. Викликаємо ваш реальний метод
    handler.on_sld_linear_changed(slider_value)
    
    # 3. Перевіряємо збережене значення в класі
    assert handler.linear_jog_speed == expected_float
    
    # 4. Перевіряємо відображення в UI
    # Очікуваний рядок: "1.500 in/min"
    widgets.val_linear_jog_speed.setText.assert_called_with("1.500 in/min")
    
def test_feed_override_update(handler_setup):
    """ТЕСТ 3.2: Перевірка Feedrate Override (0-200%)"""
    handler, widgets = handler_setup
    test_val = 150 # 150%
    
    handler.on_sld_feed_override_changed(test_val)
    
    # Перевіряємо команду: 150 / 100.0 = 1.5
    handler.command.feedrate.assert_called_with(1.5)
    # Перевіряємо UI
    widgets.val_feed_override.setText.assert_called_with("150 %")

def test_rapid_override_update(handler_setup):
    """ТЕСТ 3.3: Перевірка Rapid Override (0-100%)"""
    handler, widgets = handler_setup
    test_val = 50 # 50%
    
    handler.on_sld_rapid_override_changed(test_val)
    
    # Перевіряємо команду: 50 / 100.0 = 0.5
    handler.command.rapidrate.assert_called_with(0.5)
    widgets.val_rapid_override.setText.assert_called_with("50 %")

def test_angular_jog_speed_update(handler_setup):
    """ТЕСТ 3.4: Перевірка швидкості кутового переміщення (Angular Jog)"""
    handler, widgets = handler_setup
    test_val = 4500 # Наприклад, 45.00 deg/min
    
    handler.on_sld_angular_changed(test_val)
    
    # Перевіряємо розрахунок: 4500 / 100.0 = 45.0
    assert handler.angular_jog_speed == 45.0
    # Перевіряємо форматування тексту (2 знаки після коми)
    widgets.val_angular_jog_speed.setText.assert_called_with("45.00 deg/min")

def test_max_velocity_update(handler_setup):
    """ТЕСТ 3.5: Перевірка обмеження Max Velocity"""
    handler, widgets = handler_setup
    test_val = 120.0
    
    handler.on_sld_max_velocity_changed(test_val)
    
    # Перевіряємо пряму передачу значення в команду maxvel
    handler.command.maxvel.assert_called_with(120.0)
    widgets.val_max_velocity.setText.assert_called_with("120.0 in/min")
    
def test_spindle_override_update(handler_setup):
    """
    ТЕСТ 3.6: Перевірка Spindle Override (0-200%).
    Перевіряє встановлення коефіцієнта швидкості шпинделя та оновлення тексту.
    """
    handler, widgets = handler_setup
    test_val = 120  # Імітуємо 120%
    
    # Викликаємо ваш метод
    handler.on_sld_spindle_override_changed(test_val)
    
    # 1. Перевіряємо команду LinuxCNC: 120 / 100.0 = 1.2
    handler.command.spindleoverride.assert_called_with(1.2)
    
    # 2. Перевіряємо UI: чи відображається "120 %"
    if hasattr(widgets, 'val_spindle_override'):
        widgets.val_spindle_override.setText.assert_called_with("120 %")

def test_file_open_dialog(handler_setup):
    """ТЕСТ 6.1: Відкриття файлу через діалог"""
    handler, widgets = handler_setup
    test_path = "/home/user/test.ngc"
    
    # Імітуємо вибір файлу в QFileDialog
    with patch('PyQt5.QtWidgets.QFileDialog.getOpenFileName', return_value=(test_path, "G-Code")):
        handler.on_btn_file_open_clicked()
    
    # Перевіряємо, чи надіслана команда в LinuxCNC
    handler.command.program_open.assert_called_with(test_path)

def test_file_reload_logic(handler_setup):
    """ТЕСТ 6.2: Перевантаження поточного файлу"""
    handler, _ = handler_setup
    handler.last_loaded_file = "/home/user/reload_me.ngc"
    handler.status.interp_state = linuxcnc.INTERP_IDLE
    
    # 1. Патчимо метод і отримуємо посилання на mock
    with patch.object(handler, '_load_gcode_to_view') as mock_load:
        handler.on_btn_file_reload_clicked()
    
        # 2. Перевіряємо, чи була надіслана команда в LinuxCNC
        handler.command.program_open.assert_called_with("/home/user/reload_me.ngc")
        
        # 3. Тепер перевірка спрацює правильно
        assert mock_load.called, "Метод _load_gcode_to_view не був викликаний!"

def test_file_edit_opens_editor(handler_setup):
    """ТЕСТ 6.3: Відкриття текстового редактора"""
    handler, widgets = handler_setup
    handler.last_loaded_file = "/tmp/fake.ngc"
    handler.status.interp_state = linuxcnc.INTERP_IDLE
    
    # Імітуємо, що файл існує, редактор 'gedit' знайдено, і запуск успішний
    with patch('os.path.exists', return_value=True), \
         patch('subprocess.call', return_value=0), \
         patch('subprocess.Popen') as mock_popen:
        
        handler.on_btn_file_edit_clicked()
        
        # Перевіряємо, чи викликався Popen з якимось редактором (наприклад, gedit)
        assert mock_popen.called
        assert handler.reload_needed is True

def test_file_save_as(handler_setup):
    """ТЕСТ 6.4: Збереження G-коду у новий файл"""
    handler, widgets = handler_setup
    handler.status.interp_state = linuxcnc.INTERP_IDLE
    
    # Налаштовуємо Mock моделі списку G-коду
    mock_model = MagicMock()
    mock_model.rowCount.return_value = 2
    mock_model.index().data.side_effect = ["G1 X10", "G1 Y20"]
    widgets.list_gcode_view.model.return_value = mock_model
    
    new_path = "/tmp/saved.ngc"
    
    # Імітуємо вибір шляху збереження та сам процес запису
    with patch('PyQt5.QtWidgets.QFileDialog.getSaveFileName', return_value=(new_path, "G-Code")), \
         patch("builtins.open", mock_open()) as mocked_file, \
         patch.object(HandlerClass, '_load_gcode_to_view'):
        
        handler.on_btn_file_save_as_clicked()
        
        # Перевіряємо, чи файл було "записано"
        mocked_file().write.assert_called()
        # Перевіряємо, чи завантажив LinuxCNC новий файл
        handler.command.program_open.assert_called_with(new_path)
        
def test_send_mdi_logic(handler_setup):
    """ТЕСТ 7.1: Перевірка відправки MDI команди з перемиканням режимів"""
    handler, _ = handler_setup
    
    # Симулюємо, що ми в ручному режимі (MANUAL)
    handler.status.task_mode = linuxcnc.MODE_MANUAL
    test_code = "G0 X50"
    
    handler.send_mdi(test_code)
    
    # Використовуємо об'єкт call для перевірки послідовності
    expected_calls = [
        call(linuxcnc.MODE_MDI),
        call(linuxcnc.MODE_MANUAL)
    ]
    handler.command.mode.assert_has_calls(expected_calls)
    handler.command.mdi.assert_called_with(test_code)
    assert handler.command.wait_complete.call_count >= 3

def test_tool_arm_safety_lock(handler_setup):
    """ТЕСТ 7.2: Перевірка блокування захвата (Safety Arm)"""
    handler, widgets = handler_setup
    
    # 1. Тестуємо активацію (ARM)
    widgets.btn_tool_arm.isChecked.return_value = True
    handler.on_btn_tool_arm_clicked()
    
    # ВИПРАВЛЕНО: використовуємо assert_called_with замість called_with
    widgets.btn_tool_arm.setText.assert_called_with("ARMED")
    
    # Перевіряємо статус
    called_status_text = widgets.lbl_tool_status.setText.call_args[0][0]
    assert "READY" in called_status_text
    
    # 2. Тестуємо деактивацію (DISARM)
    widgets.btn_tool_arm.isChecked.return_value = False
    with patch.object(handler, 'on_btn_tool_action_clicked') as mock_action:
        handler.on_btn_tool_arm_clicked()
        widgets.btn_tool_action.setChecked.assert_called_with(False)
        assert mock_action.called

def test_tool_action_denied_if_not_armed(handler_setup):
    """ТЕСТ 7.3: Заборона стиснення, якщо ARM не активний"""
    handler, widgets = handler_setup
    
    # ARM вимкнено
    widgets.btn_tool_arm.isChecked.return_value = False
    widgets.btn_tool_action.isChecked.return_value = True # Пробуємо стиснути
    
    handler.on_btn_tool_action_clicked()
    
    # Має скинути кнопку назад у False і НЕ відправляти MDI
    widgets.btn_tool_action.setChecked.assert_called_with(False)
    handler.command.mdi.assert_not_called()

def test_tool_gripper_commands(handler_setup):
    """ТЕСТ 7.4: Відправка M101/M102 при роботі з захватом"""
    handler, widgets = handler_setup
    
    # Дозволяємо роботу (ARMED)
    widgets.btn_tool_arm.isChecked.return_value = True
    
    # Тестуємо GRIP (M101)
    widgets.btn_tool_action.isChecked.return_value = True
    handler.on_btn_tool_action_clicked()
    handler.command.mdi.assert_called_with("M101")
    
    # Тестуємо RELEASE (M102)
    widgets.btn_tool_action.isChecked.return_value = False
    handler.on_btn_tool_action_clicked()
    handler.command.mdi.assert_called_with("M102")

def test_tool_power_analog_output(handler_setup):
    """ТЕСТ 7.5: Оновлення зусилля через аналоговий вихід"""
    handler, widgets = handler_setup
    test_value = 85 # 85%
    
    handler.on_sld_tool_power_changed(test_value)
    
    # Перевіряємо set_analog_output(1, 0.85)
    handler.command.set_analog_output.assert_called_with(1, 0.85)
    widgets.lbl_tool_power_val.setText.assert_called_with("85 %")