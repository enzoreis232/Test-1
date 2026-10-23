"""Configuração validada, gravação atômica e diretórios graváveis por usuário."""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def user_data_dir() -> Path:
    override = os.environ.get("BACBO_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "BacBoAnalyticsPro"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "BacBoAnalyticsPro"


@dataclass
class AppConfig:
    data_dir: Path = field(default_factory=user_data_dir)
    region: tuple[int, int, int, int] | None = None
    refresh_ms: int = 1000
    demo_interval_ms: int = 700
    rows: int = 6
    columns: int = 12
    fill_order: str = "column"
    newest_at_end: bool = True
    layout: str = "chronological"
    scroll_mode: str = "scroll"
    confirmations: int = 3
    min_overlap: int = 3
    confidence_threshold: float = .65
    cell_padding: float = .15
    hue_tolerance: float = 15.0
    min_saturation: int = 100
    min_value: int = 55
    min_color_fraction: float = .12
    max_empty_color_fraction: float = .02
    tie_behavior: str = "separate"
    history_max: int = 1000
    stats_window: int = 1000
    surf_trigger: int = 4
    chess_trigger: int = 4
    language: str = "pt-BR"
    theme: str = "dark"
    export_dir: str = ""
    retention_images: int = 20
    notifications: bool = False
    first_run: bool = True
    colors: dict = field(default_factory=dict)

    def validate(self) -> None:
        self.data_dir = Path(self.data_dir)
        bounds = {"refresh_ms": (100, 60000), "demo_interval_ms": (10, 60000),
                  "rows": (1, 30), "columns": (1, 100), "confirmations": (2, 20),
                  "min_overlap": (1, 3000), "history_max": (100, 100000),
                  "stats_window": (10, 10000), "surf_trigger": (2, 100),
                  "chess_trigger": (2, 100), "retention_images": (0, 1000)}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name}: informe inteiro entre {low} e {high}")
        if self.rows * self.columns > 3000:
            raise ValueError("Grade muito grande")
        if self.region is not None:
            if len(self.region) != 4 or any(type(v) is not int for v in self.region):
                raise ValueError("Região deve conter x, y, largura e altura inteiros")
            if min(self.region[2:]) < 8 or max(self.region[2:]) > 16000:
                raise ValueError("Dimensões da região inválidas")
            self.region = tuple(self.region)
        if self.fill_order not in ("column", "row"):
            raise ValueError("Sentido de preenchimento inválido")
        if self.layout not in ("chronological", "sequence"):
            raise ValueError("Modelo de grade inválido")
        if self.scroll_mode not in ("scroll", "fixed"):
            raise ValueError("Comportamento de deslocamento inválido")
        if self.tie_behavior != "separate":
            raise ValueError("Esta versão exige empates em células separadas")
        if type(self.hue_tolerance) not in (int, float) or not math.isfinite(self.hue_tolerance) or not 0 < self.hue_tolerance < 45:
            raise ValueError("Tolerância HSV inválida")
        if any(type(v) is not int or not 0 <= v <= 255 for v in (self.min_saturation, self.min_value)):
            raise ValueError("Saturação/brilho devem estar entre 0 e 255")
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in
                (self.max_empty_color_fraction, self.min_color_fraction))
                or not 0 <= self.max_empty_color_fraction < self.min_color_fraction <= 1):
            raise ValueError("Limiares de preenchimento da célula inválidos")
        for name in ("confidence_threshold", "cell_padding"):
            value = getattr(self, name)
            high = 1 if name == "confidence_threshold" else .45
            if (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= high
                    or (name == "cell_padding" and value == high)):
                raise ValueError(f"{name}: limiar inválido")
        for name in ("newest_at_end", "notifications", "first_run"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name}: esperado booleano")
        if self.language != "pt-BR" or self.theme != "dark":
            raise ValueError("Esta versão oferece português e tema escuro")
        if not isinstance(self.colors, dict):
            raise ValueError("Perfis de cor inválidos")
        for label, hue in self.colors.items():
            if label not in "PBT" or len(label) != 1:
                raise ValueError("Perfil de cor deve mapear P/B/T para matizes HSV")
            if type(hue) not in (int, float) or not math.isfinite(hue) or not 0 <= hue <= 179:
                raise ValueError("Matizes HSV devem estar entre 0 e 179")

    def save(self) -> None:
        self.validate()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["data_dir"] = str(self.data_dir)
        path = self.data_dir / "settings.json"
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(path)

    @classmethod
    def load(cls, data_dir: Path | None = None) -> AppConfig:
        directory = Path(data_dir) if data_dir is not None else user_data_dir()
        path = directory / "settings.json"
        if not path.exists():
            return cls(data_dir=directory)
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__) - {"data_dir"}
        config = cls(data_dir=directory, **{k: v for k, v in data.items() if k in allowed})
        config.validate()
        return config
