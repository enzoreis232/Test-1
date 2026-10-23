"""SQLite transacional; exclusão lógica e trilha de correções preservam evidências."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import RoundRecord


class Database:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS rounds (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                result TEXT NOT NULL CHECK(result IN ('P','B','T')),
                timestamp_utc TEXT NOT NULL, timestamp_local TEXT NOT NULL,
                session_id TEXT NOT NULL, source TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                validation TEXT NOT NULL, dice TEXT, image_path TEXT,
                event_key TEXT UNIQUE, deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_source_seq ON rounds(source,seq);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, record_id TEXT,
                action TEXT NOT NULL, before_value TEXT, after_value TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, session_id TEXT,
                kind TEXT NOT NULL, message TEXT NOT NULL
            );
        """)
        if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Falha de integridade no banco de dados")

    def _insert(self, record: RoundRecord) -> bool:
        data = record.to_dict()
        data["dice"] = json.dumps(data["dice"]) if data["dice"] is not None else None
        columns = list(data)
        cursor = self.connection.execute(
            f"INSERT INTO rounds ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            "ON CONFLICT DO NOTHING", tuple(data[c] for c in columns))
        return cursor.rowcount == 1

    def add_many(self, records: list[RoundRecord]) -> int:
        with self.connection:
            return sum(self._insert(record) for record in records)

    def add(self, record: RoundRecord) -> bool:
        return bool(self.add_many([record]))

    @staticmethod
    def _decode(row) -> RoundRecord:
        data = dict(row)
        data.pop("seq", None)
        data.pop("deleted", None)
        data["dice"] = tuple(json.loads(data["dice"])) if data["dice"] else None
        return RoundRecord(**data)

    def records(self, source: str | None = None, limit: int | None = None) -> list[RoundRecord]:
        where = "deleted=0"
        params: list = []
        if source:
            where += " AND source=?"
            params.append(source)
        query = f"SELECT * FROM rounds WHERE {where} ORDER BY seq DESC"
        if limit is not None:
            if limit < 0:
                raise ValueError("Limite inválido")
            query += " LIMIT ?"
            params.append(limit)
        return list(reversed([self._decode(r) for r in self.connection.execute(query, params)]))

    def counts(self, source: str) -> dict[str, int]:
        counts = {key: 0 for key in "PBT"}
        for row in self.connection.execute(
                "SELECT result,COUNT(*) n FROM rounds WHERE source=? AND deleted=0 GROUP BY result", (source,)):
            counts[row["result"]] = row["n"]
        return counts

    def edit(self, record_id: str, result: str | None = None, delete: bool = False, validate: bool = False):
        row = self.connection.execute("SELECT * FROM rounds WHERE id=? AND deleted=0", (record_id,)).fetchone()
        if row is None:
            raise ValueError("Rodada não encontrada")
        original = self._decode(row)
        if result is not None and result not in ("P", "B", "T"):
            raise ValueError("Resultado inválido")
        action = "delete" if delete else "validate" if validate else "correct"
        with self.connection:
            if delete:
                self.connection.execute("UPDATE rounds SET deleted=1 WHERE id=?", (record_id,))
            elif validate:
                self.connection.execute("UPDATE rounds SET validation='validated' WHERE id=?", (record_id,))
            else:
                if result is None:
                    raise ValueError("Informe o novo resultado")
                # Não manter dados simulados contraditórios após correção manual.
                self.connection.execute("UPDATE rounds SET result=?,validation='manual',dice=NULL WHERE id=?",
                                        (result, record_id))
            self.connection.execute("INSERT INTO audit(timestamp,record_id,action,before_value,after_value) VALUES(?,?,?,?,?)",
                                    (datetime.now(timezone.utc).isoformat(), record_id, action,
                                     json.dumps(original.to_dict()), result))

    def event(self, session: str, kind: str, message: str):
        with self.connection:
            self.connection.execute("INSERT INTO events(timestamp,session_id,kind,message) VALUES(?,?,?,?)",
                                    (datetime.now(timezone.utc).isoformat(), session, kind, message))

    def export_csv(self, path: Path, source: str) -> int:
        fields = list(RoundRecord.__dataclass_fields__)
        count = 0
        with Path(path).open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for row in self.connection.execute("SELECT * FROM rounds WHERE deleted=0 AND source=? ORDER BY seq", (source,)):
                record = self._decode(row).to_dict()
                record["dice"] = json.dumps(record["dice"]) if record["dice"] else ""
                writer.writerow(record)
                count += 1
        return count

    def import_csv(self, path: Path) -> int:
        # Valida TODO o arquivo antes de inserir; uma linha incorreta aborta o lote.
        if Path(path).stat().st_size > 50_000_000:
            raise ValueError("CSV maior que 50 MB; divida o histórico")
        records = []
        session = str(uuid4())
        with Path(path).open(encoding="utf-8-sig", newline="") as source:
            for line, row in enumerate(csv.DictReader(source), 2):
                try:
                    if not row.get("timestamp_utc"):
                        raise ValueError("timestamp_utc obrigatório; horário real não pode ser inventado")
                    stamp = datetime.fromisoformat(row["timestamp_utc"])
                    local = row.get("timestamp_local") or stamp.astimezone().isoformat()
                    import hashlib
                    event = row.get("event_key") or row.get("id") or hashlib.sha256(
                        f"{line}|{stamp.isoformat()}|{row.get('result')}".encode()).hexdigest()
                    records.append(RoundRecord(
                        result=row["result"], source="import", session_id=session,
                        timestamp_utc=stamp.isoformat(), timestamp_local=local,
                        confidence=float(row.get("confidence") or 1), validation="imported",
                        event_key="import:" + event,
                        dice=tuple(json.loads(row["dice"])) if row.get("dice") else None))
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValueError(f"CSV, linha {line}: {exc}") from exc
        return self.add_many(records)

    def close(self):
        self.connection.close()
