"""Integridade do histórico: persistência, auditoria, importação e fontes."""
from __future__ import annotations

import csv
import json
from dataclasses import replace

import pytest

from bacbo_analytics.data_engine import DataEngine
from bacbo_analytics.models import RoundRecord
from bacbo_analytics.storage import Database


def make_record(result="P", source="observation", **kwargs):
    return RoundRecord.create(result, "session-test", source, **kwargs)


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "history.sqlite3")
    yield db
    db.close()


def test_reopen_restores_order_and_consecutive_ties(tmp_path):
    path = tmp_path / "history.sqlite3"
    records = [make_record(value) for value in "PTTBTP"]
    first = Database(path)
    assert first.add_many(records) == 6
    first.close()
    reopened = Database(path)
    try:
        restored = reopened.records("observation")
        assert [item.result for item in restored] == list("PTTBTP")
        assert [item.id for item in restored] == [item.id for item in records]
        assert reopened.connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        reopened.close()


def test_record_id_and_source_event_are_independently_deduplicated(database):
    original = make_record(event_key="session-test:event-1")
    assert database.add(original)
    assert not database.add(original)
    assert not database.add(replace(original, id="another-id"))
    assert not database.add(replace(original, event_key="another-event"))
    assert len(database.records()) == 1


def test_equal_results_with_distinct_events_are_preserved(database):
    for index in range(4):
        assert database.add(make_record("T", event_key=f"tie-{index}"))
    assert [r.result for r in database.records()] == ["T"] * 4


def test_correction_validation_and_soft_deletion_have_audit_trail(database):
    record = make_record("P", source="demo", dice=(6, 6, 1, 1))
    database.add(record)
    database.edit(record.id, result="B")
    corrected = database.records()[0]
    assert corrected.result == "B"
    assert corrected.validation == "manual"
    assert corrected.dice is None  # Não preservar dados contraditórios.
    database.edit(record.id, validate=True)
    assert database.records()[0].validation == "validated"
    database.edit(record.id, delete=True)
    assert database.records() == []
    row = database.connection.execute("SELECT deleted FROM rounds WHERE id=?", (record.id,)).fetchone()
    assert row["deleted"] == 1
    audit = list(database.connection.execute("SELECT * FROM audit ORDER BY id"))
    assert [entry["action"] for entry in audit] == ["correct", "validate", "delete"]
    assert json.loads(audit[0]["before_value"])["result"] == "P"


def test_invalid_correction_does_not_modify_original(database):
    record = make_record()
    database.add(record)
    with pytest.raises(ValueError):
        database.edit(record.id, result="UNKNOWN")
    assert database.records()[0].result == "P"
    assert database.connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0


def test_unknown_record_cannot_be_modified(database):
    with pytest.raises(ValueError, match="não encontrada"):
        database.edit("missing", result="B")


def test_sources_are_isolated_and_recent_history_is_bounded(database):
    engine = DataEngine(database, history_max=3)
    for value in "PTTB":
        assert engine.confirm(make_record(value, source="demo"))
    for value in "BP":
        database.add(make_record(value, source="observation"))
    assert database.counts("demo") == {"P": 1, "B": 1, "T": 2}
    assert database.counts("observation") == {"P": 1, "B": 1, "T": 0}
    engine.select_source("demo")
    assert [record.result for record in engine.history] == list("TTB")
    engine.select_source("observation")
    assert [record.result for record in engine.history] == list("BP")
    assert all(record.source == "observation" for record in engine.history)


def test_duplicate_does_not_update_recent_queue(database):
    engine = DataEngine(database, history_max=3)
    record = make_record()
    assert engine.confirm(record)
    assert not engine.confirm(record)
    assert list(engine.history) == [record]


def test_batch_is_transactional_when_a_later_record_fails(database):
    with pytest.raises(AttributeError):
        database.add_many([make_record(), object()])
    assert database.records() == []


def test_export_import_roundtrip_and_repeated_import_deduplication(database, tmp_path):
    database.add_many([make_record(value, source="demo", event_key=f"demo-{i}")
                       for i, value in enumerate("PTTBTP")])
    database.add(make_record("B", source="observation"))
    csv_path = tmp_path / "export.csv"
    assert database.export_csv(csv_path, "demo") == 6
    assert database.import_csv(csv_path) == 6
    imported = database.records("import")
    assert [record.result for record in imported] == list("PTTBTP")
    assert all(record.validation == "imported" for record in imported)
    assert database.import_csv(csv_path) == 0
    assert len(database.records("demo")) == 6
    assert len(database.records("observation")) == 1


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["result", "timestamp_utc", "timestamp_local"])
        writer.writeheader()
        writer.writerows(rows)


def test_invalid_csv_aborts_entire_import(database, tmp_path):
    path = tmp_path / "invalid.csv"
    stamp = "2026-01-01T12:00:00+00:00"
    write_csv(path, [{"result": "P", "timestamp_utc": stamp},
                     {"result": "UNKNOWN", "timestamp_utc": stamp}])
    with pytest.raises(ValueError, match="linha 3"):
        database.import_csv(path)
    assert database.records() == []


def test_missing_or_naive_timestamp_is_not_invented(database, tmp_path):
    path = tmp_path / "no-timestamp.csv"
    for stamp in ("", "2026-01-01T12:00:00"):
        write_csv(path, [{"result": "T", "timestamp_utc": stamp}])
        with pytest.raises(ValueError):
            database.import_csv(path)
        assert database.records() == []


@pytest.mark.parametrize("kwargs", [
    {"result": "UNKNOWN"},
    {"confidence": float("nan")},
    {"confidence": 1.01},
    {"source": "unrecognized"},
    {"dice": (6, 6, 1, 1), "result": "B"},
    {"dice": (0, 2, 3, 4)},
])
def test_corrupt_rounds_are_rejected(kwargs):
    values = {"result": "P", "source": "observation"}
    values.update(kwargs)
    with pytest.raises(ValueError):
        RoundRecord.create(session_id="session", **values)


def test_default_round_timestamps_describe_same_instant():
    from datetime import datetime
    record = RoundRecord(result="P", session_id="session", source="manual")
    assert datetime.fromisoformat(record.timestamp_local) == datetime.fromisoformat(record.timestamp_utc)
