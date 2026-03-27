# logic/managers/ui/editor/editor_snippets.py
"""
Шаблони вставки команд для контекстного меню редактора.

Структура:
  SNIPPETS — ієрархічний словник:
    { "Категорія": { "Назва команди": "шаблон\nкоду" } }

Шаблони використовують ${N} для позицій курсора (для майбутнього TabStop),
і [ПАРАМЕТР] для необов'язкових параметрів.
"""
from __future__ import annotations
from PyQt5.QtCore import QCoreApplication


def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


# ---------------------------------------------------------------------------
# Шаблони вставки
# ---------------------------------------------------------------------------

def get_snippets() -> dict[str, dict[str, str]]:
    """
    Повернути словник категорій → команд → шаблонів.
    Викликається при побудові меню щоб рядки були перекладені.
    """
    return {
        _tr("Команди руху"): {
            "PTP": "PTP {X 0.0, Y 0.0, Z 0.0, A 0.0, B 0.0, C 0.0} VEL 100.0 ACC 100.0 TOOL 1 BASE 0;",
            "LIN": "LIN {X 0.0, Y 0.0, Z 0.0, A 0.0, B 0.0, C 0.0} VEL 100.0 ACC 100.0 TOOL 1 BASE 0;",
            "CIRC": (
                "CIRC {X 0.0, Y 0.0, Z 0.0, A 0.0, B 0.0, C 0.0}"
                " {X 0.0, Y 0.0, Z 0.0, A 0.0, B 0.0, C 0.0}"
                " VEL 100.0 ACC 100.0 TOOL 1 BASE 0;"
            ),
        },

        _tr("Затримки та зупинки"): {
            "WAIT":  "WAIT 1.0;",
            "PAUSE": "PAUSE;",
            "STOP":  "STOP;",
        },

        _tr("Координати та зміщення"): {
            "OFFSET": "OFFSET (X 0.0, Y 0.0, Z 0.0);",
        },

        _tr("Умовний перехід"): {
            _tr("IF ... ENDIF"): (
                "IF [condition]\n"
                "    \n"
                "ENDIF"
            ),
            _tr("IF ... ELSE ... ENDIF"): (
                "IF [condition]\n"
                "    \n"
                "ELSE\n"
                "    \n"
                "ENDIF"
            ),
            _tr("IF ... ELSEIF ... ELSE ... ENDIF"): (
                "IF [condition]\n"
                "    \n"
                "ELSEIF [condition]\n"
                "    \n"
                "ELSE\n"
                "    \n"
                "ENDIF"
            ),
        },

        _tr("Цикли"): {
            _tr("WHILE ... ENDWHILE"): (
                "WHILE [condition]\n"
                "    \n"
                "ENDWHILE"
            ),
            _tr("FOR ... ENDFOR"): (
                "FOR [var] = [start] TO [end]\n"
                "    \n"
                "ENDFOR"
            ),
            _tr("REPEAT ... ENDREPEAT"): (
                "REPEAT [count]\n"
                "    \n"
                "ENDREPEAT"
            ),
        },

        _tr("Взаємодія з I/O"): {
            "SET_DO":  "SET_DO [Pin] [Value];",
            "GET_DI":  "GET_DI [Pin];",
            "WAIT_DI": "WAIT_DI [Pin] [Value];",
        },

        _tr("Підпрограми"): {
            _tr("DEF"): (
                "DEF MyRoutine()\n"
                "    \n"
                "END DEF"
            ),
            _tr("CALL"): "CALL MyRoutine();",
        },
    }
