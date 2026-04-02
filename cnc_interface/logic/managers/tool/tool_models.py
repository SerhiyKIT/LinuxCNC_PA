# logic/managers/tool/tool_models.py
"""
Tool — dataclass інструмента з валідацією та серіалізацією.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ToolDimensions:
    length_x: float = 0.0
    width_y:  float = 0.0
    height_z: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolDimensions":
        return cls(
            length_x=float(d.get("length_x", 0.0)),
            width_y= float(d.get("width_y",  0.0)),
            height_z=float(d.get("height_z", 0.0)),
        )


@dataclass
class Tool:
    id:         str            = ""
    name:       str            = ""
    type:       str            = "Gripper"
    pocket:     int            = 0
    status:     str            = "Ready"
    mass:       float          = 0.0
    offset:     float          = 0.0
    dimensions: ToolDimensions = field(default_factory=ToolDimensions)

    # ------------------------------------------------------------------
    # Серіалізація
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "name":       self.name,
            "type":       self.type,
            "pocket":     self.pocket,
            "status":     self.status,
            "mass":       self.mass,
            "offset":     self.offset,
            "dimensions": self.dimensions.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Tool":
        return cls(
            id=         str(d.get("id", "")),
            name=       str(d.get("name", "")),
            type=       str(d.get("type", "Gripper")),
            pocket=     int(d.get("pocket", 0)),
            status=     str(d.get("status", "Ready")),
            mass=       float(d.get("mass", 0.0)),
            offset=     float(d.get("offset", 0.0)),
            dimensions= ToolDimensions.from_dict(d.get("dimensions", {})),
        )

    def copy(self) -> "Tool":
        return Tool.from_dict(self.to_dict())

    # ------------------------------------------------------------------
    # Валідація
    # ------------------------------------------------------------------

    @staticmethod
    def validate(data: dict) -> list[str]:
        """
        Перевірити поля форми. Повертає список рядків помилок.
        Порожній список — дані коректні.
        """
        errors: list[str] = []
        if not str(data.get("id", "")).strip():
            errors.append("ID не може бути порожнім")
        if not str(data.get("name", "")).strip():
            errors.append("Name не може бути порожнім")
        try:
            if float(data.get("mass", 0)) < 0:
                errors.append("Mass не може бути від'ємним")
        except (ValueError, TypeError):
            errors.append("Mass: невірне числове значення")
        for key in ("length_x", "width_y", "height_z"):
            try:
                if float(data.get(key, 0)) < 0:
                    errors.append(f"{key} не може бути від'ємним")
            except (ValueError, TypeError):
                errors.append(f"{key}: невірне числове значення")
        try:
            float(data.get("offset", 0))   # offset може бути від'ємним
        except (ValueError, TypeError):
            errors.append("Offset: невірне числове значення")
        try:
            if int(data.get("pocket", 0)) < 0:
                errors.append("Pocket не може бути від'ємним")
        except (ValueError, TypeError):
            errors.append("Pocket: невірне ціле число")
        return errors
