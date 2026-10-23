"""Dashboard desktop. Captura, persistência e análise pertencem ao controller."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .region_selector import RegionSelector
from .settings_dialog import SettingsDialog
from .widgets import DistributionChart, HistoryGrid, StatCard, TimelineChart, TransitionChart

SIDES = {"P": "Player", "B": "Banker", "T": "Tie"}
COLORS = {"P": "#4089ff", "B": "#ff6178", "T": "#33cf9b"}
STATES = {"IDLE": "Em espera", "CALIBRATING": "Calibrando", "OBSERVING": "Observando",
          "WAITING_CONFIRMATION": "Aguardando confirmação", "PROCESSING": "Processando",
          "ERROR": "Verificação necessária", "PAUSED": "Pausado"}


def label(text: str, style: str = "", wrap: bool = False) -> QLabel:
    result = QLabel(text)
    if style:
        result.setObjectName(style)
    result.setWordWrap(wrap)
    return result


def panel(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    layout.addWidget(label(title, "sectionTitle"))
    if subtitle:
        layout.addWidget(label(subtitle, "muted", True))
    return frame, layout


class ImagePanel(QLabel):
    sample_requested = Signal(int, int)

    def __init__(self, empty: str):
        super().__init__(empty)
        self.original = QPixmap()
        self.setMinimumSize(240, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#0b1019; border:1px solid #2c374c; border-radius:8px; color:#8191ac;")

    def set_image(self, image) -> None:
        if image is None:
            return
        import cv2
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        self.original = QPixmap.fromImage(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0],
                                               QImage.Format.Format_RGB888).copy())
        self.fit()

    def fit(self) -> None:
        if not self.original.isNull():
            self.setPixmap(self.original.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit()

    def mousePressEvent(self, event) -> None:
        if self.original.isNull() or self.pixmap().isNull():
            return
        displayed = self.pixmap()
        left, top = (self.width() - displayed.width()) / 2, (self.height() - displayed.height()) / 2
        x, y = event.position().x() - left, event.position().y() - top
        if 0 <= x < displayed.width() and 0 <= y < displayed.height():
            self.sample_requested.emit(int(x * self.original.width() / displayed.width()),
                                       int(y * self.original.height() / displayed.height()))


class MainWindow(QMainWindow):
    def __init__(self, config, controller, *, suppress_welcome: bool = False):
        super().__init__()
        self.config = config
        self.controller = controller
        self.snapshot: dict = {}
        self.raw_image = None
        self.display_records = []
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(lambda: self.update_dashboard(self.snapshot))
        self.setWindowTitle("BAC BO ANALYTICS PRO")
        self.resize(1440, 940)
        self.setMinimumSize(1020, 700)
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)
        root_layout.addWidget(self.build_sidebar())
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(26, 22, 26, 14)
        main_layout.setSpacing(17)
        root_layout.addWidget(main, 1)

        header = QHBoxLayout()
        headings = QVBoxLayout()
        headings.addWidget(label("MONITORAMENTO ESTATÍSTICO", "eyebrow"))
        headings.addWidget(label("Visão geral", "heading"))
        self.heading = headings.itemAt(1).widget()
        header.addLayout(headings)
        header.addStretch()
        self.mode = label("SEM FONTE ATIVA", "badge")
        self.status = label("●  Em espera", "status")
        header.addWidget(self.mode)
        header.addSpacing(10)
        header.addWidget(self.status)
        main_layout.addLayout(header)

        controls = QHBoxLayout()
        self.observe_button = QPushButton("◉  Iniciar observação")
        self.observe_button.setObjectName("primary")
        self.observe_button.clicked.connect(self.start_observation)
        controls.addWidget(self.observe_button)
        self.demo_button = QPushButton("▶  Demonstração")
        self.demo_button.clicked.connect(lambda: self.safe(self.controller.start_demo))
        controls.addWidget(self.demo_button)
        pause = QPushButton("Ⅱ  Pausar")
        pause.clicked.connect(lambda: self.safe(self.controller.pause))
        controls.addWidget(pause)
        stop = QPushButton("■  Encerrar")
        stop.clicked.connect(lambda: self.safe(self.controller.stop))
        controls.addWidget(stop)
        controls.addStretch()
        export = QPushButton("↗  Exportar CSV")
        export.clicked.connect(self.export_data)
        controls.addWidget(export)
        main_layout.addLayout(controls)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_dashboard())
        self.pages.addWidget(self.build_analysis())
        self.pages.addWidget(self.build_history())
        self.pages.addWidget(self.build_capture())
        main_layout.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        self.integrity = label("Integridade: aguardando dados", "muted")
        footer.addWidget(self.integrity)
        footer.addStretch()
        self.last_confirmed = label("Nenhuma rodada confirmada", "muted")
        footer.addWidget(self.last_confirmed)
        main_layout.addLayout(footer)
        self.statusBar().showMessage("Pronto • estatísticas descritivas, sem operação de apostas")
        controller.state_changed.connect(self.update_state)
        controller.updated.connect(self.schedule_dashboard)
        controller.diagnostic.connect(self.update_diagnostic)
        controller.alert.connect(self.append_alert)
        controller.failed.connect(self.handle_failure)
        if hasattr(controller, "refresh"):
            QTimer.singleShot(0, controller.refresh)
        if config.first_run and not suppress_welcome:
            QTimer.singleShot(350, self.first_run)

    def build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(222)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 25, 18, 22)
        layout.setSpacing(8)
        brand = label("◈  BAC BO", "brand")
        layout.addWidget(brand)
        subtitle = label("ANALYTICS PRO", "eyebrow")
        subtitle.setContentsMargins(27, 0, 0, 20)
        layout.addWidget(subtitle)
        self.nav_buttons = []
        for index, (title, heading) in enumerate((("▦  Visão geral", "Visão geral"), ("⌁  Análises", "Análise estatística"),
                                                 ("≡  Histórico", "Histórico auditável"), ("◎  Captura e calibração", "Diagnóstico visual"))):
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, i=index, text=heading: self.navigate(i, text))
            self.nav_buttons.append(button)
            layout.addWidget(button)
        layout.addSpacing(22)
        layout.addWidget(label("FERRAMENTAS", "eyebrow"))
        for title, handler in (("Importar histórico", self.import_data), ("Experimento simulado", self.simulation_dialog),
                               ("Configurações", self.settings), ("Guia de primeira execução", self.first_run)):
            button = QPushButton(title)
            button.setObjectName("nav")
            button.clicked.connect(handler)
            layout.addWidget(button)
        layout.addStretch()
        note = label("HISTÓRICO ≠ PREVISÃO\n\nDados independentes não ficam previsíveis por formar sequências.\n\nObservação local. Nenhuma aposta é realizada.", "muted", True)
        layout.addWidget(note)
        layout.addSpacing(12)
        layout.addWidget(label("DESKTOP · v1.0", "eyebrow"))
        return sidebar

    def navigate(self, index: int, title: str) -> None:
        self.pages.setCurrentIndex(index)
        self.heading.setText(title)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(index == position)
        if self.snapshot:
            self.update_dashboard(self.snapshot)

    @staticmethod
    def scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 7, 0)
        layout.setSpacing(16)
        scroll.setWidget(content)
        return scroll, layout

    def build_dashboard(self) -> QWidget:
        scroll, layout = self.scroll_page()
        cards = QHBoxLayout()
        self.total_card = StatCard("RODADAS REGISTRADAS", "0", "Fonte selecionada", "#93a8c9")
        self.player_card = StatCard("PLAYER", "0", "Azul · referência 44,37%", COLORS["P"])
        self.banker_card = StatCard("BANKER", "0", "Vermelho · referência 44,37%", COLORS["B"])
        self.tie_card = StatCard("TIE", "0", "Empate · referência 11,27%", COLORS["T"])
        for card in (self.total_card, self.player_card, self.banker_card, self.tie_card):
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        beads, beads_layout = panel("Histórico de resultados", "Ordem cronológica • esquerda → direita • cada empate permanece como uma rodada")
        self.history_grid = HistoryGrid(max_results=120)
        beads_layout.addWidget(self.history_grid)
        layout.addWidget(beads)
        charts = QHBoxLayout()
        distribution, dist_layout = panel("Distribuição observada", "Comparação com quatro dados justos e independentes")
        self.distribution = DistributionChart()
        dist_layout.addWidget(self.distribution)
        timeline, time_layout = panel("Evolução da amostra", "Contagem acumulada na janela analítica")
        self.timeline = TimelineChart()
        time_layout.addWidget(self.timeline)
        charts.addWidget(distribution, 1)
        charts.addWidget(timeline, 1)
        layout.addLayout(charts)
        bottom = QHBoxLayout()
        pattern, pattern_layout = panel("Leitura do histórico")
        self.pattern_title = label("Aguardando resultados", "sectionTitle", True)
        self.pattern_title.setStyleSheet("color:#92bbff; font-size:19px;")
        self.pattern_evidence = label("Os padrões descrevem o histórico observado.", "muted", True)
        self.pattern_numbers = label("Sequência atual —  ·  Maior sequência —  ·  Alternância —", "muted", True)
        pattern_layout.addWidget(self.pattern_title)
        pattern_layout.addWidget(self.pattern_evidence)
        pattern_layout.addWidget(self.pattern_numbers)
        pattern_layout.addStretch()
        alerts, alerts_layout = panel("Monitor de eventos", "Resultados, integridade e diagnósticos")
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.setMaximumBlockCount(160)
        self.events.setMinimumHeight(130)
        alerts_layout.addWidget(self.events)
        bottom.addWidget(pattern, 1)
        bottom.addWidget(alerts, 1)
        layout.addLayout(bottom)
        return scroll

    def build_analysis(self) -> QWidget:
        scroll, layout = self.scroll_page()
        layout.addWidget(label("SEM EVIDÊNCIA SUFICIENTE DE PREVISIBILIDADE.", "warning", True))
        top = QHBoxLayout()
        transitions, trans_layout = panel("Matriz de transição", "Contagens históricas incluindo empates")
        self.transition_chart = TransitionChart()
        trans_layout.addWidget(self.transition_chart)
        summary, summary_layout = panel("Estatística da amostra", "Intervalos de confiança e testes respeitam condições e tamanho amostral")
        self.stat_summary = QPlainTextEdit()
        self.stat_summary.setReadOnly(True)
        self.stat_summary.setMinimumHeight(290)
        summary_layout.addWidget(self.stat_summary)
        top.addWidget(transitions, 1)
        top.addWidget(summary, 1)
        layout.addLayout(top)
        self.windows_table = QTableWidget(0, 5)
        self.windows_table.setHorizontalHeaderLabels(["Janela", "Amostra", "Player", "Banker", "Tie"])
        self.windows_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.windows_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        window_panel, window_layout = panel("Comparação entre janelas", "Percentuais descritivos da janela analítica carregada")
        window_layout.addWidget(self.windows_table)
        layout.addWidget(window_panel)
        hypothesis, hypothesis_layout = panel("Validação cronológica de hipóteses", "Desenvolvimento → validação → teste. Sem utilizar o futuro para criar entradas passadas.")
        self.hypothesis_text = QPlainTextEdit()
        self.hypothesis_text.setReadOnly(True)
        self.hypothesis_text.setMinimumHeight(240)
        hypothesis_layout.addWidget(self.hypothesis_text)
        layout.addWidget(hypothesis)
        return scroll

    def build_history(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.history_note = label("Histórico persistente. Correções são auditadas e as estatísticas são recalculadas.", "muted", True)
        layout.addWidget(self.history_note)
        toolbar = QHBoxLayout()
        self.source_selector = QComboBox()
        for title, source in (("Demonstração", "demo"), ("Observação", "observation"), ("Importado", "import"), ("Manual", "manual")):
            self.source_selector.addItem(title, source)
        self.source_selector.setToolTip("Consultar uma fonte preserva a separação entre dados observados e simulados; pausa a captura.")
        self.source_selector.currentIndexChanged.connect(self.select_source)
        toolbar.addWidget(self.source_selector)
        for title, callback in (("Corrigir resultado", self.correct_record), ("Validar seleção", self.validate_record),
                                ("Excluir seleção", self.delete_record), ("Importar CSV", self.import_data)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(["Resultado", "Data e hora local", "Fonte", "Leitura visual", "Validação", "Sessão", "ID"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.doubleClicked.connect(lambda index: self.correct_record())
        layout.addWidget(self.history_table, 1)
        layout.addWidget(label("A tabela mostra o histórico recente em memória; a exportação inclui todos os registros da fonte selecionada.\nConfiança visual é qualidade de classificação de imagem, não probabilidade de prever o próximo resultado.", "muted", True))
        return container

    def build_capture(self) -> QWidget:
        scroll, layout = self.scroll_page()
        actions = QHBoxLayout()
        for title, callback in (("Selecionar região", self.select_region), ("Recalibrar grade", self.calibrate),
                                ("Testar captura", self.test_capture)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.region_label = label(self.region_description(), "muted", True)
        layout.addWidget(self.region_label)
        self.capture_note = label("A primeira grade estável cria uma referência: resultados já presentes não são inseridos.\nMudanças ambíguas suspendem a leitura. Recalibrar cria uma nova referência sem inventar rodadas.", "warning", True)
        layout.addWidget(self.capture_note)
        row = QHBoxLayout()
        raw, raw_layout = panel("Imagem capturada", "Clique numa cor para calibrar o centro de matiz HSV")
        self.raw_view = ImagePanel("Nenhuma captura disponível")
        self.raw_view.sample_requested.connect(self.sample_color)
        raw_layout.addWidget(self.raw_view)
        interpretation, interpretation_layout = panel("Interpretação do algoritmo", "P · Player   B · Banker   T · Tie   ? · desconhecida   ∅ · vazia")
        self.annotated_view = ImagePanel("As células classificadas aparecerão aqui")
        interpretation_layout.addWidget(self.annotated_view)
        row.addWidget(raw, 1)
        row.addWidget(interpretation, 1)
        layout.addLayout(row)
        diagnostics, diagnostic_layout = panel("Diagnóstico da leitura")
        self.diagnostic_text = QPlainTextEdit()
        self.diagnostic_text.setReadOnly(True)
        self.diagnostic_text.setMaximumBlockCount(100)
        self.diagnostic_text.setMinimumHeight(190)
        diagnostic_layout.addWidget(self.diagnostic_text)
        layout.addWidget(diagnostics)
        return scroll

    def region_description(self) -> str:
        region = self.config.region
        if not region:
            return "Região não configurada • selecione a grade antes de observar"
        return f"Região física: x={region[0]}, y={region[1]}, {region[2]} × {region[3]} px  |  Grade: {self.config.rows} × {self.config.columns}"

    def safe(self, operation, *args) -> None:
        try:
            operation(*args)
        except Exception as error:
            self.handle_failure(str(error))

    def update_state(self, state: str) -> None:
        self.status.setText("●  " + STATES.get(state, state))
        self.observe_button.setEnabled(state not in ("OBSERVING", "PROCESSING"))
        self.statusBar().showMessage(STATES.get(state, state))

    def schedule_dashboard(self, payload: dict) -> None:
        # Coalescer atualizações: mil resultados não significam mil redesenhos.
        self.snapshot = payload
        if not self.render_timer.isActive():
            self.render_timer.start(150)

    def update_dashboard(self, payload: dict) -> None:
        self.snapshot = payload
        counts = payload.get("counts", {})
        total = payload.get("total", sum(counts.values()))
        source = payload.get("source", "")
        index = self.source_selector.findData(source)
        if index >= 0 and index != self.source_selector.currentIndex():
            self.source_selector.blockSignals(True)
            self.source_selector.setCurrentIndex(index)
            self.source_selector.blockSignals(False)
        self.mode.setText({"demo": "DEMONSTRAÇÃO · DADOS SIMULADOS", "observation": "OBSERVAÇÃO VISUAL", "import": "HISTÓRICO IMPORTADO", "manual": "EDIÇÃO MANUAL"}.get(source, "SEM FONTE ATIVA"))
        self.total_card.set_value(f"{total:,}".replace(",", "."), f"Fonte: {source or 'não selecionada'}")
        for side, card in (("P", self.player_card), ("B", self.banker_card), ("T", self.tie_card)):
            value = counts.get(side, 0)
            percent = f"{100 * value / total:.1f}% da amostra" if total else "Aguardando amostra"
            card.set_value(str(value), percent)
        records = payload.get("records", [])
        results = [record.result for record in records]
        self.history_grid.set_results(results)
        self.distribution.set_counts(counts)
        self.timeline.set_results(results[-self.config.stats_window:])
        self.integrity.setText("Integridade: " + str(payload.get("integrity", "aguardando dados")))
        if records:
            self.last_confirmed.setText(f"Última confirmada: {records[-1].timestamp_local}")
        patterns = payload.get("patterns", {})
        self.pattern_title.setText(str(patterns.get("current_pattern", "Aguardando amostra")))
        self.pattern_evidence.setText(str(patterns.get("evidence", "")) + f"\nOcorrências similares: {patterns.get('similar_occurrences', 0)}")
        run = patterns.get("current_run", {})
        alternations = patterns.get("alternations", {})
        self.pattern_numbers.setText(f"Sequência atual: {run.get('side', '—')} × {run.get('length', 0)}  ·  "
                                    f"Maior: {patterns.get('longest_run', 0)}  ·  Alternâncias: {alternations.get('total', 0)}")
        if self.pages.currentIndex() == 1:
            self.transition_chart.set_matrix(patterns.get("transitions", {}))
            self.render_statistics(payload.get("stats", {}), patterns, payload.get("hypotheses", {}))
        if self.pages.currentIndex() == 2:
            self.fill_history(records)

    def render_statistics(self, stats: dict, patterns: dict, hypotheses: dict) -> None:
        lines = [f"Amostra analítica: {stats.get('n', 0)} rodadas", str(self.snapshot.get('stats_scope', 'Janela da sessão contígua atual')),
                 "Os cartões de distribuição incluem toda a fonte selecionada.",
                 f"Entropia: {stats.get('entropy', 0):.4f} bits" if isinstance(stats.get("entropy"), (float, int)) else "Entropia: —", ""]
        for side, interval in stats.get("confidence_intervals", {}).items():
            if interval:
                lines.append(f"{SIDES.get(side, side)} · IC 95%: {interval[0]:.2%} a {interval[1]:.2%}")
        for key, title in (("goodness_of_fit", "Ajuste à referência"), ("independence", "Independência")):
            test = stats.get(key, {})
            lines.extend(["", f"{title}: {test.get('status', 'amostra insuficiente')}"])
            if test.get("p_value") is not None:
                lines.append(f"p = {test['p_value']:.4f}")
            if test.get("adjusted_p_value") is not None:
                lines.append(f"p ajustado = {test['adjusted_p_value']:.4f}")
        gaps = patterns.get("tie_intervals", {})
        lines.extend(["", f"Intervalos completos entre empates: {len(gaps.get('intervals', []))}",
                      f"Média: {gaps.get('mean', '—')}  |  Mediana: {gaps.get('median', '—')}",
                      f"Distância atual sem empate: {gaps.get('current_gap', 0)}", "",
                      str(stats.get("conclusion", "SEM EVIDÊNCIA SUFICIENTE DE PREVISIBILIDADE.")),
                      str(stats.get("warning", ""))])
        self.stat_summary.setPlainText("\n".join(lines))
        windows = patterns.get("windows", {})
        self.windows_table.setRowCount(len(windows))
        for row, (name, window) in enumerate(windows.items()):
            relative = window.get("relative", {})
            values = ["Completa" if name == "all" else f"Últimas {name}", str(window.get("n", 0))]
            values.extend(f"{relative.get(side, 0):.1%}" for side in "PBT")
            for column, value in enumerate(values):
                self.windows_table.setItem(row, column, QTableWidgetItem(value))
        hypothesis_lines = [str(hypotheses.get("status", "SEM EVIDÊNCIA SUFICIENTE DE PREVISIBILIDADE.")), ""]
        for name, partition in hypotheses.get("partitions", {}).items():
            hypothesis_lines.append(f"{name}: {partition.get('n', 0)} observações cronológicas")
        for name, partitions in hypotheses.get("hypotheses", {}).items():
            hypothesis_lines.extend(["", name.replace("_", " ").upper()])
            for partition_name, experiment in partitions.items():
                n = experiment.get("n", 0)
                frequency, expected = experiment.get("frequency"), experiment.get("expected")
                rate = f"{frequency:.1%}" if frequency is not None else "—"
                baseline = f"{expected:.1%}" if expected is not None else "—"
                hypothesis_lines.append(f"{partition_name}: n={n}; observado {rate}; referência {baseline}")
        hypothesis_lines.extend(["", str(hypotheses.get("warning", "Hipóteses fixas; resultados retrospectivos não garantem desempenho futuro."))])
        self.hypothesis_text.setPlainText("\n".join(hypothesis_lines))

    def fill_history(self, records: list) -> None:
        self.display_records = list(reversed(records[-500:]))
        self.history_table.setRowCount(len(self.display_records))
        for row, record in enumerate(self.display_records):
            confidence = f"{record.confidence:.0%}" if record.source == "observation" else "Não se aplica"
            values = [SIDES.get(record.result, record.result), str(record.timestamp_local), str(record.source),
                      confidence, str(record.validation), str(record.session_id)[:12], str(record.id)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setForeground(QColor(COLORS.get(record.result, "#dce7fa")))
                self.history_table.setItem(row, column, item)
        self.history_note.setText(f"{len(self.display_records)} registros recentes na tabela. Correções, validações e exclusões são persistidas e recalculadas.")

    def update_diagnostic(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("image") is not None:
            self.raw_image = payload["image"]
            self.raw_view.set_image(self.raw_image)
        if payload.get("annotated") is not None:
            self.annotated_view.set_image(payload["annotated"])
        cells = payload.get("cells", [])
        self.diagnostic_text.appendPlainText(str(payload.get("message", "Leitura recebida")))
        if cells:
            self.diagnostic_text.appendPlainText("Células: " + " · ".join(map(str, cells)))
        confidence = payload.get("confidence")
        if confidence is not None:
            self.diagnostic_text.appendPlainText(f"Confiança visual agregada: {confidence:.1%} (não é previsão)")

    def append_alert(self, message: str) -> None:
        self.events.appendPlainText(message)
        self.statusBar().showMessage(message, 8000)

    def handle_failure(self, message: str) -> None:
        self.append_alert("⚠ " + message)
        self.diagnostic_text.appendPlainText("⚠ " + message)
        self.status.setText("●  Verificação necessária")

    def start_observation(self) -> None:
        if not self.config.region:
            self.select_region()
            if not self.config.region:
                return
        self.safe(self.controller.start_observation)

    def apply_configuration(self, config) -> None:
        config.save()
        self.controller.apply_config(config)
        self.config = config
        self.region_label.setText(self.region_description())
        self.append_alert("Configuração salva. A leitura visual será sincronizada novamente.")

    def select_region(self) -> None:
        self.safe(self.controller.pause)
        was_visible = self.isVisible()
        self.hide()
        # Aguardar o compositor sem bloquear o event loop: a screenshot não pode
        # conter o dashboard escondendo o histórico em computadores de um monitor.
        settle = QEventLoop(self)
        QTimer.singleShot(300, settle.quit)
        settle.exec()
        try:
            dialog = RegionSelector(self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.region:
                self.safe(self.apply_configuration, dataclasses.replace(self.config, region=dialog.region))
        finally:
            if was_visible:
                self.show()
                self.activateWindow()

    def settings(self) -> None:
        self.safe(self.controller.pause)
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.safe(self.apply_configuration, dialog.result_config)

    def calibrate(self) -> None:
        self.safe(self.controller.pause)
        dialog = SettingsDialog(self.config, self, calibration=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.safe(self.apply_configuration, dialog.result_config)
            self.safe(self.controller.recalibrate)
            self.navigate(3, "Diagnóstico visual")

    def test_capture(self) -> None:
        if not self.config.region:
            self.select_region()
            if not self.config.region:
                return
        self.navigate(3, "Diagnóstico visual")
        # O worker executa captura e reconhecimento; pause manual após conferir.
        self.safe(self.controller.start_observation)
        self.append_alert("Teste iniciado: aguarde quadros estáveis. A primeira grade cria apenas uma referência.")

    def sample_color(self, x: int, y: int) -> None:
        if self.raw_image is None:
            return
        side, accepted = QInputDialog.getItem(self, "Calibrar matiz", "Qual resultado corresponde à cor selecionada?", ["P · Player", "B · Banker", "T · Tie"], 0, False)
        if not accepted:
            return
        try:
            from bacbo_analytics.capture.color_detector import ColorDetector
            patch = self.raw_image[max(0, y-3):y+4, max(0, x-3):x+4]
            hue = ColorDetector.sample_hue(patch)
            if hue is None:
                raise ValueError("A amostra não contém cor suficientemente saturada")
            colors = dict(self.config.colors)
            colors[side[0]] = float(hue)
            self.apply_configuration(dataclasses.replace(self.config, colors=colors))
            self.append_alert(f"Matiz de {side[0]} calibrado: H={hue:.1f}. Teste a grade completa antes de observar.")
        except Exception as error:
            QMessageBox.warning(self, "Amostra inválida", str(error))

    def selected_record(self):
        row = self.history_table.currentRow()
        return self.display_records[row] if 0 <= row < len(self.display_records) else None

    def select_source(self, index: int) -> None:
        if hasattr(self.controller, "select_source"):
            self.safe(self.controller.select_source, self.source_selector.itemData(index))

    def correct_record(self) -> None:
        record = self.selected_record()
        if not record:
            return
        choices = ["P · Player", "B · Banker", "T · Tie"]
        value, accepted = QInputDialog.getItem(self, "Corrigir resultado", "Resultado observado corretamente:", choices, "PBT".index(record.result), False)
        if accepted:
            self.safe(self.controller.correct_record, record.id, value[0])

    def validate_record(self) -> None:
        record = self.selected_record()
        if record:
            self.safe(self.controller.validate_record, record.id)

    def delete_record(self) -> None:
        record = self.selected_record()
        if record and QMessageBox.question(self, "Excluir registro", "Excluir este registro do histórico? A alteração ficará na auditoria.") == QMessageBox.StandardButton.Yes:
            self.safe(self.controller.delete_record, record.id)

    def import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar histórico CSV", str(self.config.export_dir), "Histórico CSV (*.csv)")
        if path:
            self.safe(self.controller.import_csv, path)

    def export_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar histórico da fonte selecionada", str(Path(self.config.export_dir) / "bacbo-historico.csv"), "CSV (*.csv)")
        if path:
            self.safe(self.controller.export_csv, path)

    def simulation_dialog(self) -> None:
        count, accepted = QInputDialog.getInt(self, "Experimento reproduzível", "Quantidade de rodadas simuladas:", 5000, 100, 100000, 100)
        if not accepted:
            return
        seed, accepted = QInputDialog.getInt(self, "Semente da simulação", "Semente para repetir o experimento:", 42, 0, 2147483647)
        if accepted and hasattr(self.controller, "simulate_batch"):
            self.safe(self.controller.simulate_batch, count, seed)

    def first_run(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Bem-vindo • Assistente de configuração")
        dialog.resize(640, 440)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Prepare sua primeira observação", "heading"))
        layout.addWidget(label("Você pode explorar a demonstração imediatamente. Para observar uma mesa, configure a região e confira a leitura visual antes de registrar resultados novos.", "muted", True))
        steps = [("1  Selecionar região da grade", self.select_region),
                 ("2  Calibrar linhas, colunas e cores", self.calibrate),
                 ("3  Testar captura no diagnóstico", self.test_capture)]
        for title, operation in steps:
            button = QPushButton(title)
            def perform(checked=False, callback=operation):
                dialog.hide()
                callback()
                dialog.show()
            button.clicked.connect(perform)
            layout.addWidget(button)
        layout.addWidget(label("A primeira captura estável é uma referência. O programa não reconstrói rodadas ausentes.\nGrades não suportadas, mudanças de escala ou sobreposição ambígua exigem verificação manual.", "warning", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()
        self.safe(self.apply_configuration, dataclasses.replace(self.config, first_run=False))

    def closeEvent(self, event) -> None:
        self.controller.close()
        event.accept()
