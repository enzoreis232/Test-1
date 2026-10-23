#!/usr/bin/env python3
"""Ponto de entrada gráfico e smoke test reproduzível para o executável Windows."""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import sqlite3
import sys
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from bacbo_analytics.config import AppConfig
from bacbo_analytics.controller import AnalyticsController
from bacbo_analytics.ui.main_window import MainWindow
from bacbo_analytics.ui.styles import STYLESHEET


def main() -> int:
    parser = argparse.ArgumentParser(description="BAC BO ANALYTICS PRO • aplicativo desktop")
    parser.add_argument("--data-dir", type=Path, default=None, help="Diretório alternativo para dados e configurações")
    parser.add_argument("--smoke-test", action="store_true", help="Verifica interface, demonstração e persistência; encerra automaticamente")
    parser.add_argument("--screenshot", type=Path, default=None, help="Salva screenshot da interface antes de encerrar o smoke test")
    args = parser.parse_args()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0]])
    app.setOrganizationName("BacBoAnalyticsPro")
    app.setApplicationName("BAC BO ANALYTICS PRO")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    try:
        config = AppConfig.load(args.data_dir)
        config.data_dir.mkdir(parents=True, exist_ok=True)
        logs = config.data_dir / "logs"
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(logs / "analytics.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=[handler])
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        if args.smoke_test:
            config = dataclasses.replace(config, first_run=False, notifications=False, demo_interval_ms=10)
        config.save()
        controller = AnalyticsController(config)
        window = MainWindow(config, controller, suppress_welcome=args.smoke_test)
    except Exception:
        detail = traceback.format_exc()
        logging.error("Falha ao iniciar aplicação\n%s", detail)
        if not args.smoke_test:
            QMessageBox.critical(None, "Não foi possível iniciar", "Falha ao abrir o aplicativo. Verifique permissões da pasta de dados e o arquivo de log.\n\n" + detail[-2000:])
        return 1

    exit_status = [0]
    errors: list[str] = []
    controller.failed.connect(errors.append)

    def unhandled(error_type, error, trace) -> None:
        logging.error("Erro na interface", exc_info=(error_type, error, trace))
        errors.append(error_type.__name__)
        exit_status[0] = 1
        if args.smoke_test:
            app.quit()

    sys.excepthook = unhandled
    window.show()

    if args.smoke_test:
        def finish_smoke() -> None:
            report = {"ok": False, "platform": platform.platform(), "frozen": bool(getattr(sys, "frozen", False)),
                      "checks": {}, "errors": errors}
            try:
                controller.pause()
                records = controller.records()
                report["checks"]["interface_visible"] = window.isVisible()
                report["checks"]["demo_records"] = len(records)
                report["checks"]["ties_preserved"] = sum(record.result == "T" for record in records)
                report["checks"]["source_is_demo"] = all(record.source == "demo" for record in records)
                if sys.platform == "win32":
                    import mss
                    from bacbo_analytics.capture import ScreenCaptureEngine
                    with mss.mss() as screen:
                        monitor = screen.monitors[1]
                        region = (monitor["left"], monitor["top"],
                                  min(128, monitor["width"]), min(128, monitor["height"]))
                    capture = ScreenCaptureEngine(region)
                    try:
                        frame = capture.capture()
                        report["checks"]["screen_capture_shape"] = list(frame.shape)
                        report["checks"]["screen_capture_shape_nonempty"] = bool(frame.size and frame.ndim == 3)
                    finally:
                        capture.close()
                else:
                    report["checks"]["screen_capture"] = "Não executado no smoke Linux offscreen; requer desktop real"
                connection = sqlite3.connect(config.data_dir / "history.sqlite3")
                try:
                    report["checks"]["database_integrity"] = connection.execute("PRAGMA quick_check").fetchone()[0]
                    report["checks"]["database_records"] = connection.execute("SELECT COUNT(*) FROM rounds WHERE deleted=0 AND source='demo'").fetchone()[0]
                finally:
                    connection.close()
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    report["checks"]["screenshot_saved"] = window.grab().save(str(args.screenshot))
                report["ok"] = (not errors and window.isVisible() and len(records) >= 25
                                and report["checks"]["database_integrity"] == "ok"
                                and report["checks"]["database_records"] >= len(records)
                                and (sys.platform != "win32" or report["checks"].get("screen_capture_shape_nonempty") is True))
                report["limitations"] = ["Reconhecimento validado por testes sintéticos; mesa real requer calibração.",
                                          "Este smoke não mede precisão visual nem previsibilidade estatística."]
            except Exception as error:
                logging.exception("Smoke test falhou")
                report["errors"].append(type(error).__name__)
            finally:
                (config.data_dir / "smoke-test.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                exit_status[0] = 0 if report["ok"] else 1
                window.close()
                app.quit()
        QTimer.singleShot(0, controller.start_demo)
        QTimer.singleShot(2200, finish_smoke)
    try:
        result = app.exec()
    finally:
        controller.close()
    return exit_status[0] or result


if __name__ == "__main__":
    raise SystemExit(main())
