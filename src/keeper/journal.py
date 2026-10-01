"""Журнал событий: что случилось с агентами и когда.

Чтобы ответить «почему сборщик отчётов простоял ночь», нужен не хвост консоли, а записанные события:
запуск, падение, зависание, перезапуск, размыкание цепи. Поэтому SQLite, а не print в файл.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STARTED = "запуск"
STOPPED = "остановка"
CRASHED = "падение"
STUCK = "зависание"
RESTARTED = "перезапуск"
OPENED = "цепь разомкнута"
RECOVERED = "восстановлен"
NOTIFIED = "уведомление"
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_agent ON events(agent, id);
"""


@dataclass(frozen=True)
class Event:
    id: int
    at: datetime
    agent: str
    kind: str
    detail: str = ""

    def line(self) -> str:
        tail = f" — {self.detail}" if self.detail else ""
        return f"{self.at.astimezone():%d.%m %H:%M:%S}  {self.agent}: {self.kind}{tail}"


def now() -> datetime:
    return datetime.now(UTC)


class Journal:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def write(self, agent: str, kind: str, detail: str = "", at: datetime | None = None) -> Event:
        moment = at or now()
        cursor = self.connection.execute(
            "INSERT INTO events (at, agent, kind, detail) VALUES (?, ?, ?, ?)",
            (moment.isoformat(), agent, kind, detail),
        )
        return Event(int(cursor.lastrowid or 0), moment, agent, kind, detail)

    def events(self, agent: str | None = None, limit: int = 50) -> list[Event]:
        if agent is None:
            rows = self.connection.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM events WHERE agent = ? ORDER BY id DESC LIMIT ?", (agent, limit)
            ).fetchall()
        return [
            Event(
                int(row["id"]),
                datetime.fromisoformat(str(row["at"])),
                str(row["agent"]),
                str(row["kind"]),
                str(row["detail"]),
            )
            for row in rows
        ]

    def counts(self, since: datetime) -> Sequence[tuple[str, str, int]]:
        rows = self.connection.execute(
            "SELECT agent, kind, COUNT(*) AS number FROM events WHERE at >= ?"
            " GROUP BY agent, kind ORDER BY agent, kind",
            (since.astimezone(UTC).isoformat(),),  # в базе время в UTC: сравниваем строки одного вида
        ).fetchall()
        return [(str(row["agent"]), str(row["kind"]), int(row["number"])) for row in rows]

    def last(self, agent: str, kind: str) -> Event | None:
        found = [event for event in self.events(agent, limit=200) if event.kind == kind]
        return found[0] if found else None
