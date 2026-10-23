from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class AppState(str, Enum):
    IDLE = "IDLE"
    CALIBRATING = "CALIBRATING"
    OBSERVING = "OBSERVING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    PROCESSING = "PROCESSING"
    ERROR = "ERROR"
    PAUSED = "PAUSED"


@dataclass(frozen=True)
class RoundRecord:
    result: str
    session_id: str
    source: str
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    timestamp_local: str = ""
    confidence: float = 1.0
    validation: str = "confirmed"
    dice: tuple[int, int, int, int] | None = None
    image_path: str | None = None
    event_key: str | None = None

    def __post_init__(self):
        import math
        if not self.timestamp_local:
            object.__setattr__(self, "timestamp_local", datetime.fromisoformat(self.timestamp_utc).astimezone().isoformat())
        if self.result not in ("P", "B", "T"):
            raise ValueError("Resultado deve ser P, B ou T")
        if self.source not in ("demo", "observation", "import", "manual"):
            raise ValueError("Fonte inválida")
        if not self.id or not self.session_id:
            raise ValueError("Identificadores ausentes")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Confiança inválida")
        for text in (self.timestamp_utc, self.timestamp_local):
            stamp = datetime.fromisoformat(text)
            if stamp.utcoffset() is None:
                raise ValueError("Horário deve conter fuso explícito")
        if datetime.fromisoformat(self.timestamp_utc).utcoffset().total_seconds() != 0:
            raise ValueError("timestamp_utc deve estar em UTC")
        if datetime.fromisoformat(self.timestamp_local) != datetime.fromisoformat(self.timestamp_utc):
            raise ValueError("Horários UTC e local devem representar o mesmo instante")
        if self.validation not in ("confirmed", "manual", "validated", "imported"):
            raise ValueError("Estado de validação inválido")
        if self.dice is not None:
            if len(self.dice) != 4 or any(type(v) is not int or not 1 <= v <= 6 for v in self.dice):
                raise ValueError("Dados inválidos")
            p, b = sum(self.dice[:2]), sum(self.dice[2:])
            expected = "P" if p > b else "B" if b > p else "T"
            if expected != self.result:
                raise ValueError("Resultado incompatível com os dados")

    @classmethod
    def create(cls, result: str, session_id: str, source: str, **kwargs):
        now = datetime.now(timezone.utc)
        return cls(result=result, session_id=session_id, source=source,
                   timestamp_utc=now.isoformat(), timestamp_local=now.astimezone().isoformat(), **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)
