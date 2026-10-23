"""MSS é criado no thread de captura; coordenadas são pixels físicos."""
from __future__ import annotations

from typing import Any

import numpy as np


class ScreenCaptureEngine:
    def __init__(self, region: dict[str, int] | tuple[int, int, int, int] | None = None):
        self.region: dict[str, int] | None = None
        self._mss: Any = None
        if region is not None:
            self.set_region(region)

    def set_region(self, region: dict[str, int] | tuple[int, int, int, int]) -> None:
        if isinstance(region, (list, tuple)):
            if len(region) != 4:
                raise ValueError("Região deve conter left, top, width e height")
            region = dict(zip(("left", "top", "width", "height"), region))
        if not isinstance(region, dict) or set(region) != {"left", "top", "width", "height"}:
            raise ValueError("Região inválida")
        if any(type(value) is not int for value in region.values()):
            raise ValueError("Coordenadas devem ser inteiras")
        if region["width"] < 5 or region["height"] < 5:
            raise ValueError("Região de captura pequena demais")
        self.region = dict(region)

    def _connection(self):
        if self._mss is None:
            import mss
            self._mss = mss.mss()
        return self._mss

    def capture(self, region: dict[str, int] | tuple[int, int, int, int] | None = None) -> np.ndarray:
        if region is not None:
            self.set_region(region)
        if self.region is None:
            raise ValueError("Selecione uma região de captura")
        screenshot = self._connection().grab(self.region)
        return np.asarray(screenshot, dtype=np.uint8)[:, :, :3].copy()

    def grab(self) -> np.ndarray:
        return self.capture()

    def monitors(self) -> list[dict[str, int]]:
        return [dict(item) for item in self._connection().monitors]

    def screen_signature(self) -> tuple[tuple[int, int, int, int], ...]:
        """Consulta fresca da geometria e, em Windows, do DPI reportado pelo SO.

        O controlador deve comparar a assinatura com a da calibração. Zoom de
        navegador não muda necessariamente esta assinatura: permanece requisito
        recalibrar manualmente ao mudar zoom ou organização visual da página.
        """
        import mss
        import sys
        with mss.mss() as connection:
            monitors = [dict(item) for item in connection.monitors]
        signature = [(item["left"], item["top"], item["width"], item["height"])
                     for item in monitors]
        if sys.platform == "win32":
            import ctypes
            try:
                dpi = int(ctypes.windll.user32.GetDpiForSystem())
            except (AttributeError, OSError):
                dpi = 0
            signature.append((-1, -1, dpi, dpi))
        return tuple(signature)

    def close(self) -> None:
        if self._mss is not None:
            self._mss.close()
            self._mss = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
