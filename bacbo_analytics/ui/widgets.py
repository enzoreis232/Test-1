"""Componentes visuais reutilizáveis, sem acesso à captura ou ao banco de dados.

Todos os valores vêm do controlador. Os widgets nunca inventam dados para ocupar
estados vazios e as referências teóricas são rotuladas como tal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

BACKGROUND = "#171c28"
TEXT = "#eaf0fa"
MUTED = "#8e9bb1"
COLORS = {"P": "#4089ff", "B": "#ff6178", "T": "#33cf9b"}
NAMES = {"P": "Player", "B": "Banker", "T": "Tie"}
THEORY = {"P": 575 / 1296, "B": 575 / 1296, "T": 146 / 1296}


def _label(text: str, size: int = 12, color: str = MUTED) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {color}; font-size: {size}px; background: transparent;")
    return label


class StatCard(QFrame):
    """Cartão de indicador com texto secundário e cor de identificação."""

    def __init__(self, title: str, value: str = "—", subtitle: str = "",
                 accent: str = "#4089ff", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumWidth(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            "QFrame#statCard {background: #171c28; border: 1px solid #252d3f; "
            f"border-top: 2px solid {accent}; border-radius: 13px;}}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(6)
        self.title_label = _label(title.upper(), 10)
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.value_label = _label(str(value), 29, TEXT)
        self.value_label.setFont(QFont("Segoe UI", 25, QFont.Weight.DemiBold))
        self.subtitle_label = _label(subtitle, 11)
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.subtitle_label)

    def set_value(self, value: object, subtitle: str | None = None) -> None:
        self.value_label.setText(str(value))
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)


class HistoryGrid(QWidget):
    """Grade cronológica ilustrativa: esquerda → direita, de cima para baixo.

    Não imita um roadmap de sequências. Cada bolinha representa exatamente um
    registro, inclusive cada empate consecutivo. O recorte é apenas visual.
    """

    def __init__(self, parent: QWidget | None = None, max_results: int = 120):
        super().__init__(parent)
        self.max_results = max(1, int(max_results))
        self.results: list[str] = []
        self.offset = 0
        self._columns = 1
        self._cell = 28
        self._margin = 10
        self.setMouseTracking(True)
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_results(self, results: Sequence[str]) -> None:
        if any(result not in COLORS for result in results):
            raise ValueError("A grade aceita somente resultados P, B ou T")
        self.offset = max(0, len(results) - self.max_results)
        self.results = list(results[-self.max_results:])
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        self._columns = max(1, (self.width() - self._margin * 2) // self._cell)
        rows = max(3, math.ceil(len(self.results) / self._columns))
        self.setMinimumHeight(rows * self._cell + self._margin * 2 + 25)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._update_size()
        super().resizeEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(520, self.minimumHeight())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.results:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "O histórico aparecerá aqui após os primeiros registros.")
            return
        rows = max(3, math.ceil(len(self.results) / self._columns))
        for row in range(rows):
            for column in range(self._columns):
                x = self._margin + column * self._cell
                y = self._margin + row * self._cell
                painter.setPen(QPen(QColor("#283043"), 1))
                painter.setBrush(QColor("#111621"))
                painter.drawEllipse(QRectF(x + 4, y + 4, 20, 20))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        for index, result in enumerate(self.results):
            row, column = divmod(index, self._columns)
            x = self._margin + column * self._cell
            y = self._margin + row * self._cell
            rect = QRectF(x + 3, y + 3, 22, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS[result]))
            painter.drawEllipse(rect)
            painter.setPen(QColor("#07111f" if result == "T" else "#ffffff"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, result)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(MUTED))
        caption = f"{len(self.results)} registros recentes · ordem cronológica → · cada T é preservado"
        painter.drawText(self._margin, rows * self._cell + self._margin + 18, caption)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = event.position()
        column = int((point.x() - self._margin) // self._cell)
        row = int((point.y() - self._margin) // self._cell)
        index = row * self._columns + column
        if (0 <= column < self._columns and row >= 0
                and 0 <= index < len(self.results)):
            result = self.results[index]
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"Registro {self.offset + index + 1} · {NAMES[result]}", self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)


def _plot() -> pg.PlotWidget:
    plot = pg.PlotWidget(background=BACKGROUND)
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=False)
    plot.hideButtons()
    plot.showGrid(x=False, y=True, alpha=0.12)
    for name in ("bottom", "left"):
        axis = plot.getAxis(name)
        axis.setPen(pg.mkPen("#39445a"))
        axis.setTextPen(pg.mkPen(MUTED))
        axis.setStyle(tickFont=QFont("Segoe UI", 8))
    return plot


class DistributionChart(QWidget):
    """Compara a frequência empírica à referência dos quatro dados justos."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.plot = _plot()
        self.plot.setMinimumHeight(210)
        self.plot.setLabel("left", "Frequência", units="%", color=MUTED)
        self.plot.getAxis("bottom").setTicks([[(0, "Player"), (1, "Banker"), (2, "Tie")]])
        self.plot.setYRange(0, 100, padding=0)
        self.plot.setXRange(-0.6, 2.6, padding=0)
        self.caption = _label("Sem registros · barras vazias representam apenas a referência teórica", 10)
        self.caption.setWordWrap(True)
        layout.addWidget(self.plot)
        layout.addWidget(self.caption)
        self.set_counts({"P": 0, "B": 0, "T": 0})

    def set_counts(self, counts: dict[str, int]) -> None:
        values = [max(0, int(counts.get(key, 0))) for key in "PBT"]
        total = sum(values)
        self.plot.clear()
        for index, key in enumerate("PBT"):
            reference = pg.BarGraphItem(
                x=[index + 0.16], height=[THEORY[key] * 100], width=0.24,
                brush=pg.mkBrush(0, 0, 0, 0), pen=pg.mkPen(COLORS[key], width=1.5,
                                                       style=Qt.PenStyle.DashLine))
            self.plot.addItem(reference)
            if total:
                bar = pg.BarGraphItem(x=[index - 0.16], height=[values[index] / total * 100],
                                      width=0.25, brush=COLORS[key], pen=None)
                self.plot.addItem(bar)
        self.caption.setText(
            f"n = {total:,} · preenchido: observado · contorno: referência teórica"
            if total else "Sem registros · contornos: referência teórica; sem frequência observada")


class TransitionChart(QWidget):
    """Matriz de transição com normalização por resultado de origem."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cells: list[list[QLabel]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.grid = QGridLayout()
        self.grid.setSpacing(7)
        self.grid.addWidget(_label("DE  /  PARA", 9), 0, 0)
        for column, key in enumerate("PBT", 1):
            label = _label(NAMES[key], 11, COLORS[key])
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, 0, column)
        for row, key in enumerate("PBT", 1):
            label = _label(NAMES[key], 11, COLORS[key])
            self.grid.addWidget(label, row, 0)
            cells = []
            for column in range(1, 4):
                cell = QLabel("—")
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setMinimumSize(58, 48)
                cell.setStyleSheet("background:#1d2534; color:#8e9bb1; border-radius:8px;")
                self.grid.addWidget(cell, row, column)
                cells.append(cell)
            self._cells.append(cells)
        layout.addLayout(self.grid)
        caption = _label("Frequência condicional histórica · cada linha soma 100% quando observada", 10)
        caption.setWordWrap(True)
        layout.addWidget(caption)

    def set_matrix(self, matrix: Sequence[Sequence[float]] | dict) -> None:
        if isinstance(matrix, dict):
            # Aceita tanto {'P': {'P': n, ...}} quanto {'PP': n, ...}.
            matrix = [[matrix.get(a, {}).get(b, 0) if isinstance(matrix.get(a), dict)
                       else matrix.get(a + b, matrix.get(f"{a}->{b}", 0))
                       for b in "PBT"] for a in "PBT"]
        data = np.asarray(matrix, dtype=float)
        if data.shape != (3, 3) or not np.isfinite(data).all() or (data < 0).any():
            raise ValueError("A matriz de transição deve ser 3x3, finita e não negativa")
        for row in range(3):
            total = float(data[row].sum())
            for column in range(3):
                cell = self._cells[row][column]
                if total == 0:
                    cell.setText("—")
                    cell.setToolTip("Nenhuma transição observada para esta origem")
                    cell.setStyleSheet("background:#1d2534; color:#8e9bb1; border-radius:8px;")
                else:
                    probability = float(data[row, column]) / total
                    cell.setText(f"{probability * 100:.1f}%")
                    cell.setToolTip(f"Valor fornecido: {data[row, column]:g} · soma da linha: {total:g}")
                    blue = round(43 + probability * 80)
                    cell.setStyleSheet(
                        f"background:rgb(25,{round(35 + probability * 35)},{blue}); "
                        "color:#eaf0fa; font-weight:600; border-radius:8px;")


class TimelineChart(QWidget):
    """Contagens acumuladas descritivas, sem extrapolação de rodadas futuras."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot = _plot()
        self.plot.setMinimumHeight(210)
        self.plot.setLabel("bottom", "Ordem dos registros", color=MUTED)
        self.plot.setLabel("left", "Contagem acumulada", color=MUTED)
        legend = self.plot.addLegend(offset=(10, 8), labelTextColor=TEXT,
                                     brush=pg.mkBrush(23, 28, 40, 210), pen=None)
        legend.setLabelTextSize("9pt")
        layout.addWidget(self.plot)
        self.caption = _label("Sem registros · nenhuma trajetória calculada", 10)
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

    def set_results(self, results: Sequence[str]) -> None:
        if any(result not in COLORS for result in results):
            raise ValueError("A trajetória aceita somente P, B e T")
        self.plot.clear()
        if not results:
            self.caption.setText("Sem registros · nenhuma trajetória calculada")
            return
        values = np.asarray(results)
        # Decimação visual inclui o último ponto; os cálculos usam todo o histórico.
        stride = max(1, len(values) // 1500)
        indices = np.unique(np.r_[np.arange(0, len(values), stride), len(values) - 1])
        x = indices + 1
        for key in "PBT":
            cumulative = np.cumsum(values == key)
            self.plot.plot(x, cumulative[indices], pen=pg.mkPen(COLORS[key], width=2),
                           name=NAMES[key])
        self.plot.enableAutoRange()
        self.caption.setText(f"{len(results):,} registros · linhas representam observações, não previsões")
