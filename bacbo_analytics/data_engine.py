from collections import deque

from .models import RoundRecord
from .storage import Database


class DataEngine:
    def __init__(self, database: Database, history_max: int = 1000):
        self.database = database
        self.history: deque[RoundRecord] = deque(maxlen=history_max)

    def select_source(self, source: str):
        self.history.clear()
        self.history.extend(self.database.records(source, self.history.maxlen))

    def confirm(self, record: RoundRecord) -> bool:
        if self.database.add(record):
            self.history.append(record)
            return True
        return False
