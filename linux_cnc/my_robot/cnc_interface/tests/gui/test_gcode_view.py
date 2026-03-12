import pytest
from PyQt5.QtWidgets import QMainWindow, QLabel, QListView, QWidget, QAbstractItemView
from PyQt5.QtCore import QCoreApplication, QStringListModel

class TestGCodeView:
    @pytest.fixture
    def manager(self, qtbot):
        class MockFileManager:
            def __init__(self):
                self.loaded_file = None
            def _load_gcode_to_view(self, filename):
                self.loaded_file = filename

        class MockManager:
            def __init__(self):
                self.widgets = type('Widgets', (), {})()
                self.widgets.list_gcode_view = QListView()
                self.widgets.lbl_filename = QLabel("initial")
                self.widgets.lbl_progress_percent = QLabel("0%")
                
                self.last_loaded_file = "old_file.ngc"
                self.file_manager = MockFileManager()

            def update_gcode_display(self, states):
                current_file = states.get('current_file')
                is_idle = states.get('is_idle', True)
                motion_line = states.get('motion_line', 0)
                gcode_view = getattr(self.widgets, 'list_gcode_view', None)

                # 1. Логіка зміни файлу
                if not current_file:
                    if self.last_loaded_file is not None:
                        self.last_loaded_file = None
                        lbl = getattr(self.widgets, 'lbl_filename', None)
                        if lbl: lbl.setText("No file")
                        if gcode_view: gcode_view.setModel(None)
                elif current_file != self.last_loaded_file:
                    self.last_loaded_file = current_file
                    if hasattr(self, 'file_manager'):
                        self.file_manager._load_gcode_to_view(current_file)

                # 2. Поведінка View та виділення
                if gcode_view:
                    model = gcode_view.model()
                    if model and model.rowCount() > 0:
                        if is_idle:
                            # Використовуємо коректний модуль QtWidgets для тригерів
                            triggers = QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed
                        else:
                            triggers = QAbstractItemView.NoEditTriggers
                        gcode_view.setEditTriggers(triggers)
                        
                        if not is_idle:
                            if 0 <= motion_line < model.rowCount():
                                index = model.index(motion_line, 0)
                                gcode_view.setCurrentIndex(index)

                        # 3. Розрахунок прогресу
                        lbl_progress = getattr(self.widgets, 'lbl_progress_percent', None)
                        if lbl_progress:
                            total_lines = model.rowCount()
                            current_line = motion_line + 1
                            if is_idle and motion_line <= 0:
                                percent = 0
                            elif is_idle and motion_line >= total_lines - 2:
                                percent = 100
                            else:
                                percent = int((current_line / total_lines) * 100)
                                percent = min(100, max(0, percent))
                            
                            template = QCoreApplication.translate("MainWindow", "PROGRESS %1%")
                            lbl_progress.setText(template.replace("%1", str(percent)))

        mgr = MockManager()
        qtbot.addWidget(mgr.widgets.list_gcode_view)
        return mgr

    def test_clear_display_when_no_file(self, manager):
        manager.widgets.list_gcode_view.setModel(QStringListModel(["G0 X0"]))
        manager.update_gcode_display({'current_file': None})
        assert manager.last_loaded_file is None
        assert manager.widgets.lbl_filename.text() == "No file"
        assert manager.widgets.list_gcode_view.model() is None

    def test_edit_triggers_lock_during_execution(self, manager):
        model = QStringListModel(["G1 X10", "G1 X20"])
        manager.widgets.list_gcode_view.setModel(model)
        
        # Виконання (is_idle=False) -> Редагування заборонено
        manager.update_gcode_display({'current_file': 'f.ngc', 'is_idle': False})
        assert manager.widgets.list_gcode_view.editTriggers() == QAbstractItemView.NoEditTriggers
        
        # Очікування (is_idle=True) -> Редагування дозволено
        manager.update_gcode_display({'current_file': 'f.ngc', 'is_idle': True})
        assert manager.widgets.list_gcode_view.editTriggers() != QAbstractItemView.NoEditTriggers

    def test_progress_calculation_logic(self, manager):
        lines = [f"G1 X{i}" for i in range(10)]
        manager.widgets.list_gcode_view.setModel(QStringListModel(lines))
        
        # 5-й рядок (index 4) з 10 -> (4+1)/10 = 50%
        manager.update_gcode_display({'is_idle': False, 'motion_line': 4, 'current_file': 'f.ngc'})
        assert "50%" in manager.widgets.lbl_progress_percent.text()