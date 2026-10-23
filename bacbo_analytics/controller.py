"""Orquestra captura/estatística em workers; SQLite pertence à thread da interface."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal

from .analysis.hypothesis_engine import HypothesisEvaluationEngine
from .analysis.simulation_engine import SimulationEngine
from .analysis.statistical_engine import StatisticalAnalysisEngine
from .analysis.strategy_engine import StrategyEngine
from .capture import CaptureCalibration, GridTrackingEngine, ImageProcessor, ScreenCaptureEngine
from .config import AppConfig
from .data_engine import DataEngine
from .models import AppState, RoundRecord
from .notifications import NotificationEngine
from .storage import Database

LOG = logging.getLogger(__name__)


class AcquisitionWorker(QThread):
    batch = Signal(object)
    diagnostic_ready = Signal(object)
    status_ready = Signal(str, str)
    error = Signal(str)

    def __init__(self, config: AppConfig, mode: str, epoch: str, session: str,
                 batch_count: int = 0, seed: int | None = None):
        super().__init__()
        self.config, self.mode, self.epoch, self.session = config, mode, epoch, session
        self.halt = Event()
        self.batch_count, self.seed = batch_count, seed

    def run(self):
        capture = None
        try:
            if self.mode == "demo":
                simulator = SimulationEngine(self.seed)
                index = 0
                if self.batch_count:
                    records = []
                    for result, dice in simulator.generate(self.batch_count):
                        if self.halt.is_set():
                            return
                        index += 1
                        records.append(RoundRecord.create(result, self.session, "demo", dice=dice,
                                                         event_key=f"{self.session}:{index}"))
                    self.batch.emit({"epoch": self.epoch, "records": records})
                    return
                while not self.halt.is_set():
                    result, dice = simulator.next_result()
                    index += 1
                    record = RoundRecord.create(result, self.session, "demo", dice=dice,
                                                event_key=f"{self.session}:{index}")
                    self.batch.emit({"epoch": self.epoch, "records": [record]})
                    self.halt.wait(self.config.demo_interval_ms / 1000)
                return
            fields = CaptureCalibration.__dataclass_fields__
            options = {key: value for key, value in asdict(self.config).items() if key in fields}
            if self.config.colors:
                options["hue_profiles"] = {"P": 110.0, "B": 0.0, "T": 60.0, **self.config.colors}
            calibration = CaptureCalibration(**options)
            processor, tracker = ImageProcessor(calibration), GridTrackingEngine(calibration)
            capture = ScreenCaptureEngine(self.config.region)
            signature = capture.screen_signature()
            index = 0
            failures = 0
            while not self.halt.is_set():
                try:
                    if capture.screen_signature() != signature:
                        self.status_ready.emit("RECALIBRATE", "Geometria dos monitores alterada; recalibre")
                        return
                    image = capture.capture()
                    observation = processor.process(image)
                    tracked = tracker.update(observation)
                    failures = 0
                except Exception:
                    failures += 1
                    LOG.exception("Falha de captura; nenhuma rodada inserida")
                    self.error.emit("Falha de captura; histórico preservado. Aguardando nova referência.")
                    tracker.reset()  # após interrupção, não presumir continuidade invisível
                    self.session = str(uuid4())  # novo segmento: nunca formar padrões através da lacuna
                    if failures >= 3:
                        return
                    self.halt.wait(1)
                    continue
                self.diagnostic_ready.emit({"epoch": self.epoch, "image": image,
                    "annotated": observation.annotated, "cells": list(observation.cells),
                    "message": tracked.message, "confidence": observation.confidence,
                    "status": tracked.status, "discarded": tracker.discarded_reads,
                    "duplicates": tracker.duplicates_avoided})
                self.status_ready.emit(tracked.status, tracked.message)
                if tracked.status in ("RECALIBRATE", "UNSUPPORTED"):
                    return
                if tracked.new_results:
                    records = []
                    image_path = None
                    if self.config.retention_images:
                        import cv2
                        folder = self.config.data_dir / "images"
                        folder.mkdir(parents=True, exist_ok=True)
                        reference = folder / f"{self.session}-{index + 1:08d}.png"
                        if cv2.imwrite(str(reference), image):
                            image_path = str(reference)
                        for stale in sorted(folder.glob("*.png"), key=lambda p: p.stat().st_mtime)[:-self.config.retention_images]:
                            stale.unlink(missing_ok=True)
                    for result in tracked.new_results:
                        index += 1
                        records.append(RoundRecord.create(result, self.session, "observation",
                            confidence=observation.confidence, image_path=image_path,
                            event_key=f"{self.session}:{index}"))
                    self.batch.emit({"epoch": self.epoch, "records": records})
                self.halt.wait(self.config.refresh_ms / 1000)
        except Exception:
            LOG.exception("Worker interrompido")
            self.error.emit("Não foi possível iniciar a fonte; revise região, calibração e permissões de tela.")
        finally:
            if capture:
                capture.close()


class AnalysisWorker(QThread):
    ready = Signal(object)
    error = Signal(str)

    def __init__(self, records, config, revision):
        super().__init__()
        self.records, self.config, self.revision = records, config, revision

    def run(self):
        try:
            results = [r.result for r in self.records]
            patterns = StrategyEngine(self.config.surf_trigger, self.config.chess_trigger).analyze(results)
            stats = StatisticalAnalysisEngine().analyze(self.records)
            hypotheses = HypothesisEvaluationEngine(self.config.surf_trigger, self.config.chess_trigger).evaluate(results)
            self.ready.emit({"patterns": patterns, "stats": stats, "hypotheses": hypotheses,
                             "revision": self.revision})
        except Exception:
            LOG.exception("Falha na análise estatística")
            self.error.emit("Falha no cálculo estatístico; os dados persistidos foram preservados")


class AnalyticsController(QObject):
    state_changed = Signal(str)
    updated = Signal(dict)
    diagnostic = Signal(object)
    alert = Signal(str)
    failed = Signal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        config.validate()
        self.config = config
        self.database = Database(config.data_dir / "history.sqlite3")
        self.data = DataEngine(self.database, config.history_max)
        self.state = AppState.IDLE.value
        self.source = "demo"
        self.session_id = str(uuid4())
        self.epoch = str(uuid4())
        self.worker = None
        self.analysis_worker = None
        self.revision = 0
        self.analysis_revision = -1
        self.analysis_cache = {}
        self.stats_count = 0
        self.integrity = "Histórico preservado; demonstração isolada da observação"
        self.notifications = NotificationEngine()
        self.notifications.enabled = config.notifications
        self.data.select_source(self.source)
        self.closed = False

    def _state(self, state: str):
        if self.state != state:
            LOG.info("state %s -> %s", self.state, state)
            self.state = state
            self.state_changed.emit(state)

    def _notice(self, text):
        self.alert.emit(text)
        self.notifications.notify(text)

    def _halt_worker(self):
        self.epoch = str(uuid4())  # descarta sinais enfileirados da execução anterior
        if self.worker is not None:
            self.worker.halt.set()
            self.worker.wait()  # Event interrompe o intervalo; captura MSS local é limitada
            self.worker = None

    def _start(self, source, batch_count=0, seed=None):
        if self.closed:
            return
        self._halt_worker()
        self.source = source
        self.data.select_source(source)
        self.analysis_cache = {}
        self.revision += 1
        self.session_id = str(uuid4())
        self.worker = AcquisitionWorker(self.config, source, self.epoch, self.session_id, batch_count, seed)
        epoch = self.epoch
        self.worker.batch.connect(self._receive)
        self.worker.diagnostic_ready.connect(self._diagnostic)
        self.worker.status_ready.connect(lambda status, message: self._status(epoch, status, message))
        self.worker.error.connect(lambda message: self._error(epoch, message))
        if batch_count:
            self.worker.finished.connect(lambda: self._batch_finished(epoch))
        self.worker.start()
        self._state(AppState.OBSERVING.value)
        self._notice("🔍 ANALISANDO HISTÓRICO — " + ("DEMONSTRAÇÃO" if source == "demo" else "OBSERVAÇÃO VISUAL"))
        self.refresh()

    def start_demo(self):
        self._start("demo")

    def select_source(self, source: str):
        if source not in ("demo", "observation", "import", "manual"):
            self.failed.emit("Fonte de histórico inválida")
            return
        self.pause()
        self.source = source
        self.data.select_source(source)
        self.analysis_cache = {}
        self.revision += 1
        self.refresh()

    def simulate_batch(self, count: int, seed: int = 42):
        if type(count) is not int or not 1 <= count <= 100000:
            self.failed.emit("Experimento deve conter entre 1 e 100.000 rodadas")
            return
        self._start("demo", count, seed)

    def start_observation(self):
        if self.config.region is None:
            self._state(AppState.CALIBRATING.value)
            self.failed.emit("Selecione primeiro a região da grade")
            return
        self._start("observation")

    def _batch_finished(self, epoch):
        if epoch == self.epoch:
            self._state(AppState.PAUSED.value)
            self._notice("Experimento simulado concluído. Dados salvos separadamente da observação.")

    def pause(self):
        self._halt_worker()
        self._state(AppState.PAUSED.value)
        self.integrity = "Pausado; retomada visual exige nova referência, sem preencher a lacuna"
        self.refresh()

    def stop(self):
        self._halt_worker()
        self._state(AppState.IDLE.value)
        self.refresh()

    def recalibrate(self):
        self._halt_worker()
        self._state(AppState.CALIBRATING.value)
        self.integrity = "Aguardando calibração e nova referência; histórico preservado"
        self._notice("⚠️ Recalibre a grade; resultados invisíveis não serão reconstruídos")
        self.refresh()

    def apply_config(self, config):
        self.pause()
        config.validate()
        config.save()
        self.config = config
        self.notifications.enabled = config.notifications
        self.data.history = deque(maxlen=config.history_max)
        self.data.select_source(self.source)
        self.revision += 1
        self.refresh()

    def _receive(self, batch):
        if self.closed or batch["epoch"] != self.epoch:
            return
        records = batch["records"]
        try:
            count = self.database.add_many(records)
        except Exception:
            LOG.exception("Transação de rodadas rejeitada")
            self.pause()
            self.failed.emit("Não foi possível salvar as rodadas; captura pausada")
            return
        self.data.select_source(self.source)
        if records:
            self.session_id = records[-1].session_id
        self.revision += 1
        if records and count:
            record = records[-1]
            label = {"P": "🔵 PLAYER", "B": "🔴 BANKER", "T": "🟢 TIE"}[record.result]
            self._notice(f"NOVO RESULTADO CONFIRMADO: {label} | {self.source} | +{count}")
        self.refresh()

    def _diagnostic(self, payload):
        if not self.closed and payload.get("epoch") == self.epoch:
            self.diagnostic.emit(payload)

    def _status(self, epoch, status, message):
        if self.closed or epoch != self.epoch:
            return
        self.integrity = message
        if status in ("RECALIBRATE", "UNSUPPORTED"):
            self._state(AppState.CALIBRATING.value)
            self.database.event(self.session_id, "gap", message)
            self._notice("⚠️ LEITURA INCERTA: " + message)
        elif status == "WAITING_CONFIRMATION":
            self._state(AppState.WAITING_CONFIRMATION.value)
        else:
            self._state(AppState.OBSERVING.value)
        if status == "RECOVERED":
            self.database.event(self.session_id, "recovered_visible", message)
        self._emit_snapshot()

    def _error(self, epoch, message):
        if self.closed or epoch != self.epoch:
            return
        self._state(AppState.ERROR.value)
        self.integrity = message
        self.failed.emit(message)

    def records(self):
        return list(self.data.history)

    def _emit_snapshot(self):
        if self.closed:
            return
        counts = self.database.counts(self.source)
        self.updated.emit({"counts": counts, "total": sum(counts.values()),
            "records": self.records(), "stats": self.analysis_cache.get("stats", {}),
            "patterns": self.analysis_cache.get("patterns", {}),
            "hypotheses": self.analysis_cache.get("hypotheses", {}),
            "stats_count": self.stats_count,
            "stats_scope": "Último segmento contínuo da fonte; pausas/lacunas não formam transições",
            "integrity": self.integrity, "source": self.source, "session_id": self.session_id,
            "analysis_pending": self.analysis_revision != self.revision})

    def refresh(self):
        self._emit_snapshot()
        self._request_analysis()

    def _request_analysis(self):
        if self.closed or self.analysis_revision == self.revision:
            return
        if self.analysis_worker is not None:
            return
        records = self.database.records(self.source, self.config.stats_window)
        # Contagens globais não exigem adjacência. Padrões e inferências exigem:
        # somente o sufixo da sessão mais recente, sem unir lacunas de observação.
        if records:
            latest_session = records[-1].session_id
            start = len(records) - 1
            while start > 0 and records[start - 1].session_id == latest_session:
                start -= 1
            records = records[start:]
        self.stats_count = len(records)
        self.analysis_worker = AnalysisWorker(records, self.config, self.revision)
        self.analysis_worker.ready.connect(self._analysis_ready)
        self.analysis_worker.error.connect(self._analysis_failed)
        self.analysis_worker.finished.connect(self._analysis_finished)
        self.analysis_worker.start()

    def _analysis_failed(self, message):
        # Não repetir automaticamente um cálculo com as mesmas entradas após erro.
        if self.analysis_worker:
            self.analysis_revision = self.analysis_worker.revision
        self.failed.emit(message)

    def _analysis_ready(self, result):
        if self.closed:
            return
        if result["revision"] == self.revision:
            self.analysis_revision = result["revision"]
            self.analysis_cache = result
            self._emit_snapshot()

    def _analysis_finished(self):
        if self.analysis_worker:
            self.analysis_worker.deleteLater()
            self.analysis_worker = None
        if not self.closed:
            self._request_analysis()

    def _edit(self, record_id, **kwargs):
        try:
            self.database.edit(record_id, **kwargs)
            self.data.select_source(self.source)
            self.revision += 1
            self.refresh()
        except Exception:
            LOG.exception("Edição rejeitada")
            self.failed.emit("Não foi possível editar a rodada; verifique o registro selecionado")

    def correct_record(self, record_id, result):
        self._edit(record_id, result=result)

    def delete_record(self, record_id):
        self._edit(record_id, delete=True)

    def validate_record(self, record_id):
        self._edit(record_id, validate=True)

    def import_csv(self, path):
        self.pause()
        try:
            count = self.database.import_csv(Path(path))
            self.source = "import"
            self.data.select_source(self.source)
            self.analysis_cache = {}
            self.revision += 1
            self._notice(f"{count} rodadas importadas; fonte isolada da observação")
            self.refresh()
        except Exception as exc:
            self.failed.emit(f"Importação rejeitada: {exc}")

    def export_csv(self, path):
        try:
            count = self.database.export_csv(Path(path), self.source)
            self._notice(f"{count} rodadas exportadas para CSV")
        except Exception:
            LOG.exception("Exportação rejeitada")
            self.failed.emit("Não foi possível exportar; confira permissão na pasta")

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._halt_worker()
        if self.analysis_worker:
            self.analysis_worker.wait()
            self.analysis_worker = None
        self.notifications.close()
        self.database.close()
