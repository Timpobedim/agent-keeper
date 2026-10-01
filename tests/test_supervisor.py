"""Присмотр проверяется на настоящих процессах, но со «своим» временем: часы подменяются списком."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import httpx
from conftest import FAILING, SILENT, STEADY, agent, wait_until

from keeper import journal as log
from keeper.config import Settings
from keeper.journal import Journal, now
from keeper.notify import ConsoleNotifier, WebhookNotifier
from keeper.supervisor import Keeper


def keeper_for(tmp_path: Path, journal: Journal, *agents: object, clock: list[datetime] | None = None) -> Keeper:
    settings = Settings(tuple(agents), journal=tmp_path / "журнал.sqlite", check_every=0.05)  # type: ignore[arg-type]
    ticker = clock if clock is not None else [now()]
    return Keeper(settings, journal, ConsoleNotifier(), clock=lambda: ticker[0])


async def test_failing_agent_is_restarted_then_circuit_opens(tmp_path: Path, journal: Journal) -> None:
    clock = [now()]
    keeper = keeper_for(
        tmp_path, journal, agent(tmp_path, "падающий", FAILING, restart_limit=1, backoff=0.1), clock=clock
    )
    await keeper.start_all()
    state = keeper.state("падающий")
    assert state is not None
    for _ in range(6):
        assert wait_until(lambda: state.running is None or not state.running.alive)
        clock[0] += timedelta(seconds=1)
        await keeper.tick()
        if state.broken:
            break
    keeper.shutdown()
    assert state.broken
    assert state.failures > state.agent.restart_limit
    kinds = [event.kind for event in journal.events("падающий")]
    assert log.OPENED in kinds
    assert log.CRASHED in kinds
    assert log.RESTARTED in kinds
    notifier = keeper.notifier
    assert isinstance(notifier, ConsoleNotifier)
    assert any("не поднимается" in text for text in notifier.sent)


async def test_stuck_agent_is_restarted_with_a_notice(tmp_path: Path, journal: Journal) -> None:
    clock = [now()]
    keeper = keeper_for(tmp_path, journal, agent(tmp_path, "зависающий", SILENT, idle_timeout=0.2), clock=clock)
    await keeper.start_all()
    state = keeper.state("зависающий")
    assert state is not None
    assert wait_until(lambda: bool(state.running and state.running.tail()))
    clock[0] += timedelta(seconds=5)
    await keeper.tick()
    assert state.failures == 1
    assert state.last_reason.startswith("молчит")
    assert log.STUCK in [event.kind for event in journal.events("зависающий")]
    notifier = keeper.notifier
    assert isinstance(notifier, ConsoleNotifier)
    assert any("перезапускаю" in text for text in notifier.sent)
    clock[0] += timedelta(seconds=5)
    await keeper.tick()  # пауза прошла — агент поднят заново
    assert state.running is not None
    keeper.shutdown()
    assert log.STOPPED in [event.kind for event in journal.events("зависающий")]


async def test_steady_agent_is_left_alone_and_recovers(tmp_path: Path, journal: Journal) -> None:
    clock = [now()]
    keeper = keeper_for(tmp_path, journal, agent(tmp_path, "надёжный", STEADY), clock=clock)
    await keeper.start_all()
    state = keeper.state("надёжный")
    assert state is not None
    state.failures = 2  # как будто раньше падал
    assert wait_until(lambda: bool(state.running and state.running.tail()))
    await keeper.tick()
    assert state.failures == 2  # ещё рано: не прожил восстановительное окно
    clock[0] += timedelta(minutes=2)
    await keeper.tick()
    assert state.failures == 0
    assert log.RECOVERED in [event.kind for event in journal.events("надёжный")]
    assert state.condition == "работает"
    keeper.shutdown()


async def test_notification_failure_does_not_stop_the_keeper(tmp_path: Path, journal: Journal) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500, text="упал")))
    settings = Settings(
        (agent(tmp_path, "зависающий", SILENT, idle_timeout=0.2),), journal=tmp_path / "журнал.sqlite", check_every=0.05
    )
    clock = [now()]
    keeper = Keeper(settings, journal, WebhookNotifier("https://chat.example/hook", client), clock=lambda: clock[0])
    try:
        await keeper.start_all()
        state = keeper.state("зависающий")
        assert state is not None
        assert wait_until(lambda: bool(state.running and state.running.tail()))
        clock[0] += timedelta(seconds=5)
        await keeper.tick()  # уведомление не доставится, но присмотр продолжает работать
        assert state.failures == 1
        assert any("не доставлено" in event.detail for event in journal.events("присмотр"))
    finally:
        keeper.shutdown()
        await client.aclose()
