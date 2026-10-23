"""Editor centralizado de configurações, sem necessidade de editar arquivos Python."""
from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)


def spin(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setSuffix(suffix)
    return widget


def fraction(value: float, minimum: float = 0.0, maximum: float = 1.0) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(3)
    widget.setSingleStep(0.05)
    widget.setValue(value)
    return widget


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None, calibration: bool = False):
        super().__init__(parent)
        self.config = config
        self.result_config = None
        self.setWindowTitle("Calibração assistida" if calibration else "Configurações")
        self.resize(650, 640)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        grid = QWidget()
        form = QFormLayout(grid)
        note = QLabel("Suporte seguro: grade cronológica com empates em células separadas.\nRoadmaps de sequências ou empates sobrepostos exigem outro adaptador e são recusados.")
        note.setWordWrap(True)
        note.setObjectName("warning")
        form.addRow(note)
        self.rows = spin(1, 30, config.rows)
        self.columns = spin(1, 100, config.columns)
        self.fill_order = QComboBox()
        self.fill_order.addItem("Por coluna (cima → baixo)", "column")
        self.fill_order.addItem("Por linha (esquerda → direita)", "row")
        self.fill_order.setCurrentIndex(max(0, self.fill_order.findData(config.fill_order)))
        self.scroll_mode = QComboBox()
        self.scroll_mode.addItem("Desloca quando a grade fica cheia", "scroll")
        self.scroll_mode.addItem("Grade fixa (cheia exige nova referência)", "fixed")
        self.scroll_mode.setCurrentIndex(max(0, self.scroll_mode.findData(getattr(config, "scroll_mode", "scroll"))))
        self.newest = QCheckBox("Resultado mais recente no final da sequência")
        self.newest.setChecked(config.newest_at_end)
        self.confirmations = spin(2, 20, config.confirmations)
        self.overlap = spin(1, 100, config.min_overlap)
        self.padding = fraction(config.cell_padding, 0, 0.44)
        for name, widget in (("Linhas", self.rows), ("Colunas", self.columns),
                             ("Ordem de preenchimento", self.fill_order), ("Quando a grade fica cheia", self.scroll_mode), ("Orientação", self.newest),
                             ("Quadros estáveis para confirmar", self.confirmations),
                             ("Sobreposição mínima", self.overlap), ("Margem interna da célula", self.padding)):
            form.addRow(name, widget)
        tabs.addTab(grid, "Grade")

        colors = QWidget()
        color_form = QFormLayout(colors)
        caution = QLabel("Os centros HSV iniciais são referências genéricas, não uma calibração da sua mesa.\nAjuste usando a imagem de diagnóstico. T pode ser verde ou dourado (HSV H: 0–179).\nA área precisa incluir exatamente a grade, alinhada às linhas e colunas informadas.")
        caution.setWordWrap(True)
        caution.setObjectName("warning")
        color_form.addRow(caution)
        self.hues = {}
        defaults = {"P": 110, "B": 0, "T": 60}
        profile = config.colors or defaults
        for side, title in (("P", "Player · centro azul"), ("B", "Banker · centro vermelho"), ("T", "Tie · centro verde/dourado")):
            value = profile.get(side, defaults[side])
            if isinstance(value, dict):
                value = value.get("hue", defaults[side])
            self.hues[side] = fraction(float(value), 0, 179)
            color_form.addRow(title, self.hues[side])
        self.tolerance = fraction(getattr(config, "hue_tolerance", 15), 1, 44.9)
        self.saturation = spin(0, 255, getattr(config, "min_saturation", 100))
        self.value = spin(0, 255, getattr(config, "min_value", 55))
        self.color_fraction = fraction(getattr(config, "min_color_fraction", 0.12), 0.01, 0.9)
        self.empty_fraction = fraction(getattr(config, "max_empty_color_fraction", 0.02), 0, 0.2)
        self.confidence = fraction(config.confidence_threshold, 0.5, 1)
        for name, widget in (("Tolerância de matiz", self.tolerance), ("Saturação mínima", self.saturation),
                             ("Brilho mínimo", self.value), ("Fração colorida mínima", self.color_fraction),
                             ("Máximo colorido em célula vazia", self.empty_fraction),
                             ("Limiar de confiança visual", self.confidence)):
            color_form.addRow(name, widget)
        tabs.addTab(colors, "Reconhecimento")

        analysis = QWidget()
        analysis_form = QFormLayout(analysis)
        self.refresh = spin(100, 60000, config.refresh_ms, " ms")
        self.demo_interval = spin(20, 60000, config.demo_interval_ms, " ms")
        self.history = spin(100, 100000, config.history_max)
        self.window = spin(10, 10000, config.stats_window)
        self.surf = spin(2, 100, config.surf_trigger)
        self.chess = spin(2, 100, config.chess_trigger)
        for name, widget in (("Intervalo de captura", self.refresh), ("Intervalo demonstração", self.demo_interval),
                             ("Histórico recente em memória", self.history), ("Janela analítica", self.window),
                             ("Gatilho Surf", self.surf), ("Gatilho Xadrez", self.chess)):
            analysis_form.addRow(name, widget)
        label = QLabel("As frequências e os padrões são descritivos. Detectar uma sequência não estabelece previsão.\nO aplicativo não executa apostas nem envia instruções de entrada.")
        label.setWordWrap(True)
        label.setObjectName("muted")
        analysis_form.addRow(label)
        tabs.addTab(analysis, "Análise e captura")

        general = QWidget()
        general_form = QFormLayout(general)
        self.export_dir = QLineEdit(str(config.export_dir))
        choose = QPushButton("Escolher")
        choose.clicked.connect(self.choose_directory)
        directory_row = QHBoxLayout()
        directory_row.addWidget(self.export_dir)
        directory_row.addWidget(choose)
        general_form.addRow("Diretório de exportação", directory_row)
        self.retention = spin(0, 500, config.retention_images)
        general_form.addRow("Imagens de diagnóstico retidas", self.retention)
        self.notifications = QCheckBox("Ativar relatórios Telegram (variáveis de ambiente)")
        self.notifications.setChecked(config.notifications)
        general_form.addRow(self.notifications)
        privacy = QLabel("Tokens não são salvos nesta tela. Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no sistema.\nO envio requer ativação explícita. Capturas podem conter informações privadas da tela.")
        privacy.setWordWrap(True)
        privacy.setObjectName("muted")
        general_form.addRow(privacy)
        data = QLabel(str(config.data_dir))
        data.setWordWrap(True)
        data.setTextInteractionFlags(data.textInteractionFlags())
        general_form.addRow("Dados, logs e configurações", data)
        tabs.addTab(general, "Geral")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Diretório de exportação", self.export_dir.text())
        if directory:
            self.export_dir.setText(directory)

    def save_settings(self) -> None:
        updates = {
            "rows": self.rows.value(), "columns": self.columns.value(),
            "fill_order": self.fill_order.currentData(), "newest_at_end": self.newest.isChecked(),
            "scroll_mode": self.scroll_mode.currentData(),
            "confirmations": self.confirmations.value(), "min_overlap": self.overlap.value(),
            "cell_padding": self.padding.value(), "confidence_threshold": self.confidence.value(),
            "colors": {side: widget.value() for side, widget in self.hues.items()},
            "hue_tolerance": self.tolerance.value(), "min_saturation": self.saturation.value(),
            "min_value": self.value.value(), "min_color_fraction": self.color_fraction.value(),
            "max_empty_color_fraction": self.empty_fraction.value(),
            "refresh_ms": self.refresh.value(), "demo_interval_ms": self.demo_interval.value(),
            "history_max": self.history.value(), "stats_window": self.window.value(),
            "surf_trigger": self.surf.value(), "chess_trigger": self.chess.value(),
            "export_dir": self.export_dir.text(), "retention_images": self.retention.value(),
            "notifications": self.notifications.isChecked(),
        }
        valid_fields = {field.name for field in dataclasses.fields(self.config)}
        try:
            config = dataclasses.replace(self.config, **{k: v for k, v in updates.items() if k in valid_fields})
            config.validate()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Configuração inválida", str(error))
            return
        self.result_config = config
        self.accept()
