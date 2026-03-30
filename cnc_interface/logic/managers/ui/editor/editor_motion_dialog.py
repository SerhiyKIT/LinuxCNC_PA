# logic/managers/ui/editor/editor_motion_dialog.py
"""
MotionCommandDialog – діалог генерації команди PTP / LIN / CIRC.
_PosGroup           – група полів координат X/Y/Z/A/B/C.
"""
from __future__ import annotations
import logging
from PyQt5.QtCore    import QCoreApplication, Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog,
    QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)
from .editor_colors import DIALOG_STYLE, INSERT_BTN_STYLE, POS_AXES

logger = logging.getLogger(__name__)

def _tr(t: str) -> str:
    return QCoreApplication.translate("MainWindow", t)


class _PosGroup(QGroupBox):
    """Група з 6 полями координат + кнопка зчитування поточної позиції."""

    def __init__(self, title: str, cnc=None,
                 limits: dict | None = None, parent=None):
        super().__init__(title, parent)
        self._cnc    = cnc
        self._limits = limits or {}
        self._fields: dict[str, QLineEdit] = {}

        grid = QHBoxLayout(self)
        grid.setSpacing(8)

        for axis in POS_AXES:
            lo, hi  = self._limits.get(axis, (None, None))
            tooltip = f"{axis}: [{lo}, {hi}]" if lo is not None else axis

            col = QVBoxLayout()
            col.setSpacing(2)
            lbl = QLabel(axis)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setToolTip(tooltip)
            fld = QLineEdit("0.0")
            fld.setAlignment(Qt.AlignRight)
            fld.setToolTip(tooltip)
            fld.setFocusPolicy(Qt.StrongFocus)
            fld.textChanged.connect(lambda _, f=fld, ax=axis: self._mark(f, ax))
            col.addWidget(lbl)
            col.addWidget(fld)
            grid.addLayout(col)
            self._fields[axis] = fld

        btn = QPushButton(_tr("Current coords."))
        btn.setToolTip(_tr("Read current coordinates from LinuxCNC"))
        btn.setAutoDefault(False)
        btn.setDefault(False)
        btn.setEnabled(cnc is not None)
        btn.clicked.connect(self._get_current_pos)
        grid.addWidget(btn)

    def _in_range(self, axis: str, val: float) -> bool:
        lo, hi = self._limits.get(axis, (None, None))
        return True if lo is None else lo <= val <= hi

    def _field_ok(self, fld: QLineEdit, axis: str) -> bool:
        try:
            return self._in_range(axis, float(fld.text()))
        except ValueError:
            return False

    def _mark(self, fld: QLineEdit, axis: str) -> None:
        ok = self._field_ok(fld, axis)
        fld.setProperty("invalid", "" if ok else "true")
        fld.style().unpolish(fld)
        fld.style().polish(fld)

    def _get_current_pos(self) -> None:
        if self._cnc is None:
            return
        try:
            self._cnc.poll()
            pos = self._cnc.status.actual_position
            for i, axis in enumerate(POS_AXES):
                if i < len(pos):
                    self._fields[axis].setText(f"{pos[i]:.4f}")
        except Exception as exc:
            logger.error("Get Current POS: %s", exc)

    def is_valid(self) -> bool:
        return all(self._field_ok(f, ax) for ax, f in self._fields.items())

    def is_empty(self) -> bool:
        return any(not f.text().strip() for f in self._fields.values())

    def to_pos_string(self) -> str:
        parts = ", ".join(f"{ax} {self._fields[ax].text()}" for ax in POS_AXES)
        return "{" + parts + "}"


class MotionCommandDialog(QDialog):
    """
    Модальний діалог генерації команди PTP / LIN / CIRC.
    Enter не закриває діалог. Кнопка Вставити активна лише після валідації.
    """

    _VEL_MIN, _VEL_MAX = 0.0, 100.0
    _ACC_MIN, _ACC_MAX = 0.0, 100.0

    def __init__(self, motion_type: str, cnc=None, parent=None):
        super().__init__(parent)
        self._motion_type = motion_type.upper()

        limits: dict = {}
        if cnc is not None and hasattr(cnc, "limits"):
            raw = cnc.limits
            if isinstance(raw, dict):
                for idx, axis in enumerate(POS_AXES):
                    j = raw.get(idx)
                    if isinstance(j, dict):
                        lo, hi = j.get("min"), j.get("max")
                        if lo is not None and hi is not None:
                            limits[axis] = (float(lo), float(hi))

        self.setWindowTitle(_tr(f"Вставити команду {self._motion_type}"))
        self.setMinimumWidth(720)
        self.setStyleSheet(DIALOG_STYLE)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(14, 14, 14, 14)

        if self._motion_type == "CIRC":
            self._aux_pos    = _PosGroup(_tr("Auxiliary point"), cnc, limits, self)
            self._target_pos = _PosGroup(_tr("Target point"),  cnc, limits, self)
            root.addWidget(self._aux_pos)
            root.addWidget(self._target_pos)
        else:
            self._pos = _PosGroup(_tr("Target point"), cnc, limits, self)
            root.addWidget(self._pos)

        params_box = QGroupBox(_tr("Motion parameters"))
        pf = QFormLayout(params_box)
        pf.setSpacing(8)
        pf.setLabelAlignment(Qt.AlignRight)

        self._cont = QCheckBox(_tr("(do not stop at point)"))
        pf.addRow(_tr("Continuous motion:"), self._cont)

        self._ori_type = None
        if self._motion_type in ("LIN", "CIRC"):
            self._ori_type = QComboBox()
            self._ori_type.addItems(["ORI_VAR", "ORI_CONST"])
            pf.addRow(_tr("Orientation type:"), self._ori_type)

        self._circ_type = None
        if self._motion_type == "CIRC":
            self._circ_type = QComboBox()
            self._circ_type.addItems(["CIRC_PATH", "CIRC_BASE"])
            pf.addRow(_tr("Circular orientation type:"), self._circ_type)

        self._vel = QLineEdit("100.0")
        self._vel.setToolTip(_tr(f"Velocity: {self._VEL_MIN}…{self._VEL_MAX}"))
        pf.addRow(_tr("Velocity:"), self._vel)

        self._acc = QLineEdit("100.0")
        self._acc.setToolTip(_tr(f"Acceleration: {self._ACC_MIN}…{self._ACC_MAX}"))
        pf.addRow(_tr("Acceleration:"), self._acc)

        self._tool = QLineEdit("1")
        self._tool.setToolTip(_tr("Tool number (integer ≥ 0)"))
        pf.addRow(_tr("Tool:"), self._tool)

        self._base = QLineEdit("0")
        self._base.setToolTip(_tr("Coordinate system (integer ≥ 0)"))
        pf.addRow(_tr("Coordinate system:"), self._base)

        root.addWidget(params_box)

        prev_box = QGroupBox(_tr("Result"))
        pv = QVBoxLayout(prev_box)
        self._preview = QLabel("")
        self._preview.setStyleSheet(
            "font-family:Monospace;font-size:12px;color:#F1F1F1;"
            "padding:6px;background:#121212;border-radius:3px;")
        self._preview.setWordWrap(True)
        pv.addWidget(self._preview)
        root.addWidget(prev_box)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_cancel = QPushButton(_tr("Cancel"))
        self._btn_cancel.setAutoDefault(False)
        self._btn_cancel.setDefault(False)
        self._btn_cancel.clicked.connect(self.reject)

        self._btn_insert = QPushButton(_tr("Insert"))
        self._btn_insert.setAutoDefault(False)
        self._btn_insert.setDefault(False)
        self._btn_insert.setEnabled(False)
        self._btn_insert.setStyleSheet(INSERT_BTN_STYLE)
        self._btn_insert.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_insert)
        root.addLayout(btn_row)

        self._connect_signals()
        self._on_changed()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _connect_signals(self) -> None:
        if self._motion_type == "CIRC":
            for f in (*self._aux_pos._fields.values(), *self._target_pos._fields.values()):
                f.textChanged.connect(self._on_changed)
        else:
            for f in self._pos._fields.values():
                f.textChanged.connect(self._on_changed)
        for w in (self._vel, self._acc, self._tool, self._base):
            w.textChanged.connect(self._on_changed)
        if self._ori_type:
            self._ori_type.currentIndexChanged.connect(self._on_changed)
        if self._circ_type:
            self._circ_type.currentIndexChanged.connect(self._on_changed)
        self._cont.stateChanged.connect(self._on_changed)

    def _in_range(self, text: str, lo: float, hi: float) -> bool:
        try:
            return lo < float(text) <= hi
        except ValueError:
            return False

    @staticmethod
    def _is_uint(text: str) -> bool:
        try:
            return int(text) >= 0
        except ValueError:
            return False

    def _mark(self, fld: QLineEdit, ok: bool) -> None:
        fld.setProperty("invalid", "" if ok else "true")
        fld.style().unpolish(fld)
        fld.style().polish(fld)

    def _validate(self) -> bool:
        ok = True
        if self._motion_type == "CIRC":
            if not self._aux_pos.is_valid()    or self._aux_pos.is_empty():    ok = False
            if not self._target_pos.is_valid() or self._target_pos.is_empty(): ok = False
        else:
            if not self._pos.is_valid() or self._pos.is_empty(): ok = False
        for fld, flag in (
            (self._vel,  self._in_range(self._vel.text(),  self._VEL_MIN, self._VEL_MAX)),
            (self._acc,  self._in_range(self._acc.text(),  self._ACC_MIN, self._ACC_MAX)),
            (self._tool, self._is_uint(self._tool.text())),
            (self._base, self._is_uint(self._base.text())),
        ):
            self._mark(fld, flag)
            if not flag:
                ok = False
        return ok

    def build_command(self) -> str:
        parts = [self._motion_type]
        if self._motion_type == "CIRC":
            parts += [self._aux_pos.to_pos_string(), self._target_pos.to_pos_string()]
        else:
            parts.append(self._pos.to_pos_string())
        if self._cont.isChecked():  parts.append("CONT")
        if self._ori_type:          parts.append(self._ori_type.currentText())
        if self._circ_type:         parts.append(self._circ_type.currentText())
        parts += [
            f"VEL {self._vel.text()}",
            f"ACC {self._acc.text()}",
            f"TOOL {self._tool.text()}",
            f"BASE {self._base.text()}",
        ]
        return " ".join(parts) + ";"

    def _on_changed(self) -> None:
        ok = self._validate()
        self._btn_insert.setEnabled(ok)
        self._preview.setText(
            self.build_command() if ok
            else _tr("⚠  Fill in all fields correctly (red fields are out of range)")
        )
