"""Отчёт: что сейчас с агентами и что было в журнале."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from keeper.journal import Journal
from keeper.supervisor import State

COLUMNS = ("Агент", "Состояние", "Перезапусков", "Неудач подряд", "Последняя причина")


def table(states: Sequence[State]) -> str:
    rows = [
        (state.agent.name, state.condition, str(state.restarts), str(state.failures), state.last_reason or "—")
        for state in states
    ]
    widths = [
        max(len(COLUMNS[number]), *(len(row[number]) for row in rows)) if rows else len(COLUMNS[number])
        for number in range(len(COLUMNS))
    ]
    lines = ["  ".join(title.ljust(width) for title, width in zip(COLUMNS, widths, strict=True))]
    lines.extend("  ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)) for row in rows)
    return "\n".join(line.rstrip() for line in lines)


def summary(journal: Journal, since: datetime, limit: int = 15) -> str:
    counts = journal.counts(since)
    lines = ["", f"События с {since.astimezone():%d.%m %H:%M}:"]
    if counts:
        lines.extend(f"  {agent}: {kind} — {number}" for agent, kind, number in counts)
    else:
        lines.append("  ничего не происходило")
    events = journal.events(limit=limit)
    if events:
        lines.append("")
        lines.append("Последние события:")
        lines.extend(f"  {event.line()}" for event in reversed(events))
    return "\n".join(lines)


def report(journal: Journal, states: Sequence[State], hours: float = 24.0, now: datetime | None = None) -> str:
    moment = now or max((event.at for event in journal.events(limit=1)), default=datetime.now().astimezone())
    return table(states) + "\n" + summary(journal, moment - timedelta(hours=hours))
