# conftest.py
import sys
from unittest.mock import MagicMock

# Створюємо заглушки для LinuxCNC
mock_lcnc = MagicMock()
mock_lcnc.STATE_ESTOP = 1
mock_lcnc.STATE_ESTOP_RESET = 2
mock_lcnc.STATE_ON = 2
mock_lcnc.STATE_OFF = 1
mock_lcnc.ini.return_value.find.return_value = "100"

# Підміняємо модулі в системі
sys.modules["linuxcnc"] = mock_lcnc
sys.modules["key_config"] = MagicMock()