"""Seleção visual em pixels físicos, independente da escala lógica do Windows."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class RegionCanvas(QWidget):
    """Desenha screenshot com letterbox e converte seleção para sua resolução nativa."""

    def __init__(self) -> None:
        super().__init__()
        self.pixmap = QPixmap()
        self.origin = QPoint()
        self.cursor = QPoint()
        self.selection = QRect()
        self.dragging = False
        self.setMinimumSize(640, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap
        self.selection = QRect()
        self.update()

    def image_rect(self) -> QRect:
        if self.pixmap.isNull():
            return QRect()
        size = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2,
                     size.width(), size.height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#090d14"))
        target = self.image_rect()
        if self.pixmap.isNull():
            painter.setPen(QColor("#91a0b9"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Atualize a imagem do monitor para selecionar a grade")
            return
        painter.drawPixmap(target, self.pixmap)
        if not self.selection.isNull():
            painter.setPen(QPen(QColor("#65a8ff"), 2))
            painter.drawRect(self.selection)
            painter.setPen(QColor("#dcecff"))
            native = self.native_selection()
            painter.drawText(self.selection.topLeft() + QPoint(5, -7), f"{native[2]} × {native[3]} px")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position().toPoint()):
            self.origin = event.position().toPoint()
            self.dragging = True
            self.selection = QRect(self.origin, self.origin)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging:
            target = self.image_rect()
            point = event.position().toPoint()
            point.setX(max(target.left(), min(target.right(), point.x())))
            point.setY(max(target.top(), min(target.bottom(), point.y())))
            self.selection = QRect(self.origin, point).normalized()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)
            self.dragging = False

    def native_selection(self) -> tuple[int, int, int, int]:
        target = self.image_rect()
        if target.isEmpty() or self.selection.isEmpty():
            return (0, 0, 0, 0)
        sx, sy = self.pixmap.width() / target.width(), self.pixmap.height() / target.height()
        x = round((self.selection.left() - target.left()) * sx)
        y = round((self.selection.top() - target.top()) * sy)
        return x, y, round(self.selection.width() * sx), round(self.selection.height() * sy)


class RegionSelector(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selecionar região • pixels físicos")
        self.resize(1020, 710)
        self.region: tuple[int, int, int, int] | None = None
        self.monitors: list[dict] = []
        self.canvas = RegionCanvas()
        self.monitor = QComboBox()
        layout = QVBoxLayout(self)
        title = QLabel("Selecione somente a grade cronológica")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        description = QLabel("Abra o histórico no monitor desejado. Atualize a imagem e arraste sobre a grade completa, incluindo células vazias.\nA captura usa a resolução física do monitor; a escala do Windows é compensada pela seleção na imagem.")
        description.setWordWrap(True)
        description.setObjectName("muted")
        layout.addWidget(description)
        row = QHBoxLayout()
        row.addWidget(self.monitor, 1)
        refresh = QPushButton("Atualizar imagem")
        refresh.clicked.connect(self.refresh_image)
        row.addWidget(refresh)
        layout.addLayout(row)
        layout.addWidget(self.canvas, 1)
        self.info = QLabel("Nenhuma região selecionada")
        layout.addWidget(self.info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        try:
            import mss
            with mss.mss() as capture:
                self.monitors = [dict(m) for m in capture.monitors[1:]]
            for i, monitor in enumerate(self.monitors):
                self.monitor.addItem(f"Monitor {i + 1} — {monitor['width']} × {monitor['height']} px ({monitor['left']}, {monitor['top']})")
            self.monitor.currentIndexChanged.connect(self.refresh_image)
            self.refresh_image()
        except Exception as error:
            self.info.setText(f"Captura indisponível neste ambiente: {type(error).__name__}")

    def refresh_image(self) -> None:
        if self.isVisible():
            # O modal não deve aparecer dentro da própria imagem capturada.
            self.showMinimized()
            QTimer.singleShot(300, self.capture_and_restore)
            return
        self.capture_image()

    def capture_and_restore(self) -> None:
        self.capture_image()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def capture_image(self) -> None:
        if not self.monitors:
            return
        try:
            import mss
            with mss.mss() as capture:
                shot = capture.grab(self.monitors[self.monitor.currentIndex()])
            image = QImage(shot.rgb, shot.width, shot.height, shot.width * 3, QImage.Format.Format_RGB888).copy()
            self.canvas.set_image(QPixmap.fromImage(image))
            self.info.setText("Arraste para delimitar a grade. A imagem é estática; confirme após selecionar.")
        except Exception as error:
            self.info.setText(f"Falha ao capturar monitor: {type(error).__name__}")

    def accept_selection(self) -> None:
        x, y, width, height = self.canvas.native_selection()
        if width < 20 or height < 20:
            QMessageBox.warning(self, "Seleção insuficiente", "Selecione uma área de pelo menos 20 × 20 pixels.")
            return
        monitor = self.monitors[self.monitor.currentIndex()]
        self.region = (monitor["left"] + x, monitor["top"] + y, width, height)
        self.accept()
