"""Integração Qt sem tela: worker responsivo, histórico e encerramento seguro."""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from bacbo_analytics.config import AppConfig
from bacbo_analytics.controller import AnalyticsController
from bacbo_analytics.models import RoundRecord


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def controller(qapp, tmp_path):
    config = AppConfig(data_dir=tmp_path, demo_interval_ms=10, first_run=False)
    item = AnalyticsController(config)
    yield item
    item.close()
    qapp.processEvents()


def wait_for(qapp, predicate, timeout=15000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail("Tempo limite aguardando processamento Qt")
        qapp.processEvents()
        QTest.qWait(10)
    qapp.processEvents()


def test_simulated_batch_keeps_event_loop_alive_and_persists(controller, qapp):
    heartbeats = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: heartbeats.append(1))
    timer.start()
    errors = []
    controller.failed.connect(errors.append)
    try:
        controller.simulate_batch(5000, seed=123)
        wait_for(qapp, lambda: sum(controller.database.counts("demo").values()) == 5000)
        wait_for(qapp, lambda: controller.state == "PAUSED")
        assert len(heartbeats) >= 2
        assert not errors
        assert len(controller.records()) == controller.config.history_max
        assert controller.database.counts("observation") == {"P": 0, "B": 0, "T": 0}
    finally:
        timer.stop()


def test_pause_resume_preserves_history_and_discards_late_events(controller, qapp):
    controller.start_demo()
    wait_for(qapp, lambda: len(controller.records()) >= 3)
    controller.pause()
    previous = controller.database.records("demo")
    stale_epoch = "old-worker-epoch"
    late = RoundRecord.create("T", "late-session", "demo")
    controller._receive({"epoch": stale_epoch, "records": [late]})
    assert controller.database.records("demo") == previous
    QTest.qWait(40)
    qapp.processEvents()
    assert controller.database.records("demo") == previous
    controller.start_demo()
    wait_for(qapp, lambda: len(controller.database.records("demo")) > len(previous))
    controller.pause()
    restored = controller.database.records("demo")
    assert [r.id for r in restored[:len(previous)]] == [r.id for r in previous]


def test_manual_edit_updates_persisted_data_and_analysis_revision(controller, qapp):
    snapshots = []
    controller.updated.connect(snapshots.append)
    controller.simulate_batch(80, seed=42)
    wait_for(qapp, lambda: sum(controller.database.counts("demo").values()) == 80)
    wait_for(qapp, lambda: controller.analysis_revision == controller.revision)
    target = controller.records()[0]
    replacement = "B" if target.result != "B" else "P"
    old_revision = controller.revision
    controller.correct_record(target.id, replacement)
    assert controller.revision > old_revision
    wait_for(qapp, lambda: controller.analysis_revision == controller.revision)
    assert controller.database.records("demo")[0].result == replacement
    assert controller.database.records("demo")[0].validation == "manual"
    assert snapshots[-1]["counts"] == controller.database.counts("demo")
    assert not snapshots[-1]["analysis_pending"]
    controller.validate_record(target.id)
    assert controller.database.records("demo")[0].validation == "validated"
    controller.delete_record(target.id)
    assert len(controller.database.records("demo")) == 79


def test_close_stops_all_workers_and_is_idempotent(controller, qapp):
    controller.start_demo()
    wait_for(qapp, lambda: len(controller.records()) >= 2)
    acquisition = controller.worker
    analysis = controller.analysis_worker
    controller.close()
    assert controller.closed
    assert controller.worker is None
    assert controller.analysis_worker is None
    assert not acquisition.isRunning()
    if analysis is not None:
        assert not analysis.isRunning()
    controller.close()
    qapp.processEvents()  # Sinais já enfileirados não devem acessar SQLite fechado.


def test_database_reopens_after_controller_close(qapp, tmp_path):
    config = AppConfig(data_dir=tmp_path, first_run=False)
    first = AnalyticsController(config)
    first.simulate_batch(40, seed=7)
    try:
        wait_for(qapp, lambda: sum(first.database.counts("demo").values()) == 40)
        ids = [record.id for record in first.records()]
    finally:
        first.close()
        qapp.processEvents()
    second = AnalyticsController(config)
    try:
        assert [record.id for record in second.records()] == ids
    finally:
        second.close()
        qapp.processEvents()


def test_analysis_does_not_invent_transitions_across_sessions(controller, qapp):
    # O último Player da sessão A não precede de forma observada o Banker de B.
    records = [RoundRecord.create("P", "session-A", "demo") for _ in range(30)]
    records += [RoundRecord.create("B", "session-B", "demo") for _ in range(10)]
    controller.database.add_many(records)
    controller.data.select_source("demo")
    controller.revision += 1
    controller.refresh()
    wait_for(qapp, lambda: controller.analysis_revision == controller.revision)
    assert controller.database.counts("demo") == {"P": 30, "B": 10, "T": 0}
    assert controller.stats_count == 10
    assert controller.analysis_cache["stats"]["n"] == 10
    assert controller.analysis_cache["stats"]["frequencies"] == {"P": 0, "B": 10, "T": 0}


def test_failed_analysis_is_not_retried_with_unchanged_inputs(controller, qapp, monkeypatch):
    class FailingAnalysis(QThread):
        ready = Signal(object)
        error = Signal(str)

        def __init__(self, records, config, revision):
            super().__init__()
            self.revision = revision

        def run(self):
            self.error.emit("falha controlada")

    monkeypatch.setattr("bacbo_analytics.controller.AnalysisWorker", FailingAnalysis)
    failures = []
    controller.failed.connect(failures.append)
    controller.refresh()
    wait_for(qapp, lambda: controller.analysis_worker is None)
    QTest.qWait(50)
    qapp.processEvents()
    assert failures == ["falha controlada"]
    controller.refresh()
    QTest.qWait(50)
    qapp.processEvents()
    assert failures == ["falha controlada"]
    controller.revision += 1
    controller.refresh()
    wait_for(qapp, lambda: controller.analysis_worker is None)
    assert failures == ["falha controlada"] * 2
