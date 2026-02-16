# logic/managers/file_manager.py
import os
import subprocess
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtCore import QStringListModel
from config import STYLES

class FileManager:
    def __init__(self, machine_controller, widgets):
        self.cnc = machine_controller
        self.widgets = widgets
        self.STYLE_GCODE_WARN = STYLES.get('GCODE_WARN', '')

    def connect_file_buttons(self):
        mapping = {
            'btn_file_open': self.on_btn_file_open_clicked,
            'btn_file_save_as': self.on_btn_file_save_as_clicked,
            'btn_file_reload': self.on_btn_file_reload_clicked,
            'btn_file_edit': self.on_btn_file_edit_clicked
        }
        for btn_name, handler in mapping.items():
            btn = getattr(self.widgets, btn_name, None)
            if btn: btn.clicked.connect(handler)

    def on_btn_file_open_clicked(self):
        """Відкриває діалог вибору файлу"""
        default_dir = os.path.expanduser("~/linuxcnc-dev/configs/sim/axis/nc_files")
        file_path, _ = QFileDialog.getOpenFileName(
            None, "Open G-Code File", default_dir,
            "G-Code Files (*.ngc *.txt *.gcode);;All Files (*)"
        )
    
        if file_path:
            try:
                # Використовуємо метод контролера (там всередині poll() і open)
                self.cnc.open_program(file_path)
                # Після успішного відкриття в CNC, завантажуємо в UI
                self._load_gcode_to_view(file_path)
            except Exception as e:
                print(f"ERROR: Не вдалося завантажити файл: {e}")

    def on_btn_file_save_as_clicked(self):
        """Збереження вмісту в'юхи у новий файл"""
        if not self.cnc.is_interpreter_idle():
            print("WARNING: Переривання: інтерпретатор зайнятий")
            return

        model = self.widgets.list_gcode_view.model() if hasattr(self.widgets, 'list_gcode_view') else None
        if not model or model.rowCount() == 0:
            return

        initial_path = os.path.dirname(self.cnc.get_last_file()) if self.cnc.get_last_file() else os.path.expanduser("~")
        new_filepath, _ = QFileDialog.getSaveFileName(None, "Save G-Code as...", initial_path, "G-Code Files (*.ngc *.txt)")

        if new_filepath:
            try:
                if not new_filepath.endswith(('.ngc', '.txt')): new_filepath += '.ngc'
                
                # Збираємо дані
                content = [model.index(i, 0).data() for i in range(model.rowCount())]
                with open(new_filepath, 'w', encoding='utf-8') as f:
                    f.write("\n".join(content))

                # Повідомляємо CNC про новий файл
                self.cnc.open_program(new_filepath)
                self._load_gcode_to_view(new_filepath)
                print(f"DEBUG: Збережено та завантажено: {new_filepath}")
            except Exception as e:
                print(f"ERROR: Помилка збереження: {e}")

    def on_btn_file_reload_clicked(self):
        """Оновлення поточного файлу"""
        last_file = self.cnc.get_last_file()
        if not last_file or not self.cnc.is_interpreter_idle():
            print("WARNING: Reload неможливий (файл не знайдено або станок працює)")
            return

        try:
            self.cnc.open_program(last_file)
            self._load_gcode_to_view(last_file)
            self.cnc.reload_needed = False
            
            # Повертаємо нормальний стиль кнопці
            if hasattr(self.widgets, 'btn_file_reload'):
                self.widgets.btn_file_reload.setStyleSheet("")
                
            print(f"DEBUG: {os.path.basename(last_file)} оновлено")
        except Exception as e:
            print(f"ERROR: Помилка релоаду: {e}")

    def on_btn_file_edit_clicked(self):
        """Відкриття у зовнішньому редакторі"""
        last_file = self.cnc.get_last_file()
        if not last_file or not self.cnc.is_interpreter_idle():
            return

        editors = ['gedit', 'mousepad', 'leafpad', 'xed', 'nano']
        for editor in editors:
            if subprocess.call(['which', editor], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                subprocess.Popen([editor, last_file])
                self.cnc.reload_needed = True
                if hasattr(self.widgets, 'btn_file_reload'):
                    self.widgets.btn_file_reload.setStyleSheet(self.STYLE_GCODE_WARN)
                return

    def _load_gcode_to_view(self, filepath):
        """Візуальне завантаження тексту у QListView для PyQt5"""
        if not os.path.exists(filepath):
            print(f"ERROR: Файл не знайдено: {filepath}")
            return

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = [line.strip() for line in f.readlines()]
        
            # Створюємо модель
            model = QStringListModel()
            model.setStringList(lines)
        
            if hasattr(self.widgets, 'list_gcode_view'):
                view = self.widgets.list_gcode_view
            
                # 1. Спершу встановлюємо модель
                view.setModel(model)
            
                # 2. Тільки ПІСЛЯ встановлення моделі налаштовуємо тригери
                # В PyQt5 використовуємо пряме звернення до констант
                triggers = QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                view.setEditTriggers(triggers)
            
                # 3. Підключаємо сигнал (робимо це саме до моделі)
                # Важливо: модель належить View, тому ми маємо бути впевнені, 
                # що працюємо з актуальним об'єктом моделі.
                model.dataChanged.connect(self._on_gcode_edited)

            # Оновлюємо лейбли
            if hasattr(self.widgets, 'lbl_filename'):
                self.widgets.lbl_filename.setText(os.path.basename(filepath))
        
            if hasattr(self.widgets, 'lbl_progress_percent'):
                self.widgets.lbl_progress_percent.setText("0%")
            
            print(f"DEBUG: G-code loaded into view: {len(lines)} lines")
            
        except Exception as e:
            print(f"ERROR: _load_gcode_to_view: {e}")

    def _on_gcode_edited(self, topLeft, bottomRight, roles):
        """
        Викликається автоматично після завершення редагування рядка в UI.
        Зберігає зміни у файл та оновлює стан контролера.
        """
        # 1. Перевірка станів перед записом
        if not self.cnc.is_interpreter_idle():
            print("WARNING: Редагування заблоковано: програма виконується")
            return

        last_file = self.cnc.get_last_file()
        if not last_file or not os.path.exists(last_file):
            return

        try:
            # 2. Отримуємо актуальну модель з віджета
            model = self.widgets.list_gcode_view.model()
            if not model:
                return
                
            # Збираємо всі рядки тексту з моделі
            all_lines = model.stringList()
        
            # 3. Перезаписуємо фізичний файл на диску
            with open(last_file, 'w', encoding='utf-8') as f:
                # Додаємо символ нового рядка в кінці, щоб LinuxCNC коректно зчитав останній рядок
                f.write("\n".join(all_lines) + "\n")
        
            # 4. Повідомляємо LinuxCNC, що файл змінився (синхронізація)
            self.cnc.open_program(last_file)
            
            # Оскільки ми щойно самі синхронізували файл, reload вже не потрібен
            self.cnc.reload_needed = False
            
            # Скидаємо стиль кнопки, якщо він був встановлений
            if hasattr(self.widgets, 'btn_file_reload'):
                self.widgets.btn_file_reload.setStyleSheet("")
                
            print(f"DEBUG: Зміни збережено у файл та синхронізовано з LinuxCNC: {os.path.basename(last_file)}")
        
        except Exception as e:
            print(f"ERROR: Не вдалося автоматично зберегти зміни: {e}")