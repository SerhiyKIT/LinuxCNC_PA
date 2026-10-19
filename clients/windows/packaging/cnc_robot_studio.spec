# clients/windows/packaging/cnc_robot_studio.spec
# PyInstaller: CNC-Robot Studio як папка з "CNC-Robot Studio.exe" (без Python на ПК).
# Збірка (з каталогу clients/windows):
#   pyinstaller packaging/cnc_robot_studio.spec --noconfirm
# Результат: dist/CNC-Robot Studio/ — далі його пакує packaging/installer.iss.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))           # noqa: F821 (SPEC задає PyInstaller)
APP_DIR = os.path.normpath(os.path.join(HERE, "..", "bt_cnc_client"))
APP_NAME = "CNC-Robot Studio"

# Модулі Studio імпортуються як верхньорівневі (main_window, protocol_client…),
# тому каталог додається в pathex. Bleak на Windows працює через пакети winrt —
# їх підвантажує динамічно, тож збираємо явно.
hidden = (collect_submodules("bleak") + collect_submodules("qasync")
          + (collect_submodules("winrt") if sys.platform == "win32" else []))

a = Analysis(                                            # noqa: F821
    [os.path.join(APP_DIR, "__main__.py")],
    pathex=[APP_DIR],
    hiddenimports=hidden + ["ble_transport", "tcp_transport", "setup_wizard", "teach_panel"],
    excludes=["tkinter", "pytest", "PyQt5.QtWebEngineWidgets", "PyQt5.QtQml", "PyQt5.QtQuick"],
)
pyz = PYZ(a.pure)                                        # noqa: F821
exe = EXE(                                               # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=os.path.join(HERE, "icon.ico"),
    console=False,                                       # без чорного вікна консолі
)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)  # noqa: F821
