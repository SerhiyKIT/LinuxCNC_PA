# clients/windows/bt_cnc_client/__main__.py
"""Запуск: python -m bt_cnc_client (з каталогу clients/windows)."""
import asyncio
import logging
import os
import sys

# Модулі пакета імпортуються як верхньорівневі (як у bt-cnc-bridge)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qasync                                    # noqa: E402
from PyQt5 import QtWidgets                      # noqa: E402

from main_window import MainWindow               # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QtWidgets.QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    closed = asyncio.Event()
    app.aboutToQuit.connect(closed.set)
    with loop:
        loop.run_until_complete(closed.wait())
        # Дати завершитись відключенню (release + disconnect) після закриття вікна
        loop.run_until_complete(asyncio.sleep(0.5))


if __name__ == "__main__":
    main()
