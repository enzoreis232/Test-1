"""Configuração explícita da grade e dos perfis HSV de reconhecimento."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CaptureCalibration:
    rows: int = 6
    columns: int = 12
    fill_order: str = "column"
    newest_at_end: bool = True
    layout: str = "chronological"
    confirmations: int = 3
    min_overlap: int = 3
    cell_padding: float = 0.15
    confidence_threshold: float = 0.65
    grid_roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    # Presets genéricos HSV, não uma calibração validada de mesa real.
    hue_profiles: dict[str, float] = field(default_factory=lambda: {"P": 110.0, "B": 0.0, "T": 60.0})
    hue_tolerance: float = 15.0
    min_saturation: int = 100
    min_value: int = 55
    min_color_fraction: float = 0.12
    max_empty_color_fraction: float = 0.02
    scroll_mode: str = "scroll"
    tie_behavior: str = "separate"
    max_new_results: int = 24

    def __post_init__(self) -> None:
        for name in ("rows", "columns", "confirmations", "min_overlap", "max_new_results"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name}: informe inteiro positivo")
        if self.rows * self.columns > 5000:
            raise ValueError("Grade excede 5000 células")
        if self.fill_order not in ("column", "row"):
            raise ValueError("Ordem de preenchimento deve ser column ou row")
        if self.scroll_mode not in ("scroll", "fixed"):
            raise ValueError("Deslocamento deve ser scroll ou fixed")
        if self.layout not in ("chronological", "sequence"):
            raise ValueError("Layout desconhecido")
        if self.tie_behavior not in ("separate", "overlay"):
            raise ValueError("Comportamento de empate desconhecido")
        if not 0 <= self.cell_padding < 0.45:
            raise ValueError("Margem de célula deve estar entre 0 e 0.45")
        for name in ("confidence_threshold", "min_color_fraction", "max_empty_color_fraction"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} deve estar entre 0 e 1")
        if self.max_empty_color_fraction >= self.min_color_fraction:
            raise ValueError("Limiar vazio deve ser menor que limiar colorido")
        if not 0 < self.hue_tolerance < 45:
            raise ValueError("Tolerância HSV deve estar entre 0 e 45")
        if any(type(v) is not int or not 0 <= v <= 255 for v in (self.min_saturation, self.min_value)):
            raise ValueError("Saturação e brilho devem estar entre 0 e 255")
        if set(self.hue_profiles) != {"P", "B", "T"}:
            raise ValueError("Perfis devem conter P, B e T")
        if any(not 0 <= float(hue) < 180 for hue in self.hue_profiles.values()):
            raise ValueError("Matiz HSV deve estar entre 0 e 179")
        if len(self.grid_roi) != 4:
            raise ValueError("ROI deve conter x, y, largura e altura normalizados")
        x, y, width, height = self.grid_roi
        if not (0 <= x < 1 and 0 <= y < 1 and width > 0 and height > 0
                and x + width <= 1.000001 and y + height <= 1.000001):
            raise ValueError("ROI deve estar contida na imagem")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "CaptureCalibration":
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})

