import sys
from unittest.mock import MagicMock

# Створюємо підроблені модулі, щоб тести не шукали реальний linuxcnc
mock_modules = ['linuxcnc', 'core', 'config', 'styles']

for mod_name in mock_modules:
    if mod_name not in sys.modules:
        mock = MagicMock()
        # Додаємо атрибути, які найчастіше використовуються, щоб не було AttributeError
        if mod_name == 'linuxcnc':
            mock.MODE_AUTO = 1
            mock.MODE_MANUAL = 2
            mock.INTERP_IDLE = 1
        sys.modules[mod_name] = mock

import pytest
from PyQt5 import QtWidgets

@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app