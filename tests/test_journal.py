from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from keeper import journal as log
from keeper.journal import Journal

MOMENT = datetime(2026, 9, 12, 8, 0, tzinfo=UTC)


def test_events_are_written_and_read_back(journal: Journal) -> None:
    journal.write("сборщик", log.STARTED, "python -m worker", MOMENT)
    journal.write("сборщик", log.CRASHED, "завершился с кодом 1", MOMENT + timedelta(seconds=30))
    journal.write("почта", log.STARTED, at=MOMENT + timedelta(seconds=40))
    assert [event.kind for event in journal.events()] == [log.STARTED, log.CRASHED, log.STARTED]
    assert [event.agent for event in journal.events("сборщик")] == ["сборщик", "сборщик"]
    last = journal.last("сборщик", log.CRASHED)
    assert last is not None
    assert last.detail == "завершился с кодом 1"
    assert journal.last("почта", log.CRASHED) is None
    assert "сборщик: запуск — python -m worker" in journal.events("сборщик")[-1].line()


def test_counts_are_limited_by_time(journal: Journal) -> None:
    journal.write("сборщик", log.CRASHED, at=MOMENT - timedelta(days=2))
    journal.write("сборщик", log.CRASHED, at=MOMENT)
    journal.write("сборщик", log.RESTARTED, at=MOMENT)
    assert sorted(journal.counts(MOMENT - timedelta(hours=1))) == [
        ("сборщик", log.CRASHED, 1),
        ("сборщик", log.RESTARTED, 1),
    ]
    assert sorted(journal.counts(MOMENT - timedelta(days=7))) == [
        ("сборщик", log.CRASHED, 2),
        ("сборщик", log.RESTARTED, 1),
    ]


def test_journal_is_a_file_that_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "журнал.sqlite"
    first = Journal(path)
    first.write("сборщик", log.STARTED, at=MOMENT)
    first.close()
    second = Journal(path)
    try:
        assert [event.kind for event in second.events()] == [log.STARTED]
    finally:
        second.close()
