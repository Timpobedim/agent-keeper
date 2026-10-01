"""Цикл присмотра: проверить, перезапустить, а если агент безнадёжен — перестать дёргать.

Правило простое: падение или молчание — перезапуск с растущей паузой (2, 4, 8 секунд…). Если подряд
случилось больше `restart_limit` неудач, цепь размыкается: агент больше не перезапускается, а в
журнал и в уведомление уходит «цепь разомкнута». Иначе присмотр превращается в бесконечный цикл
«упал — поднял», который никто не замечает.

Состояние цепи живёт в памяти присмотра, а события — в журнале.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from keeper import journal as log
from keeper import process as proc
from keeper.config import Agent, Settings
from keeper.journal import Journal, now
from keeper.notify import Notifier

RECOVERY = timedelta(seconds=60)  # столько агент должен прожить, чтобы счётчик неудач обнулился
Clock = Callable[[], datetime]


@dataclass
class State:
    agent: Agent
    running: proc.Running | None = None
    failures: int = 0  # неудач подряд
    restarts: int = 0  # всего перезапусков
    next_try: datetime | None = None
    broken: bool = False  # цепь разомкнута
    last_reason: str = ""
    history: list[str] = field(default_factory=list)

    @property
    def condition(self) -> str:
        if self.broken:
            return "цепь разомкнута"
        if self.running is not None and self.running.alive:
            return "работает"
        return "ждёт перезапуска" if self.next_try else "остановлен"


class Keeper:
    """Присмотр за агентами из настроек. Всё время работает в одном потоке и одном цикле."""

    def __init__(
        self,
        settings: Settings,
        journal: Journal,
        notifier: Notifier,
        *,
        clock: Clock = now,
        recovery: timedelta = RECOVERY,
    ) -> None:
        self.settings = settings
        self.journal = journal
        self.notifier = notifier
        self.states = [State(agent) for agent in settings.agents]
        self._clock = clock
        self._recovery = recovery

    def state(self, name: str) -> State | None:
        return next((state for state in self.states if state.agent.name == name), None)

    async def start_all(self) -> None:
        for state in self.states:
            await self._start(state, log.STARTED)

    async def _start(self, state: State, kind: str) -> None:
        try:
            state.running = proc.start(state.agent)
        except proc.ProcessError as exc:
            state.running = None
            state.failures += 1
            state.last_reason = str(exc)
            self.journal.write(state.agent.name, log.CRASHED, str(exc), self._clock())
            await self._maybe_break(state)
            return
        state.next_try = None
        if kind == log.RESTARTED:
            state.restarts += 1
        self.journal.write(state.agent.name, kind, " ".join(state.agent.command), self._clock())

    async def _maybe_break(self, state: State) -> None:
        if state.failures <= state.agent.restart_limit:
            state.next_try = self._clock() + timedelta(seconds=state.agent.pause(state.failures))
            return
        state.broken = True
        state.next_try = None
        self.journal.write(state.agent.name, log.OPENED, f"неудач подряд: {state.failures}", self._clock())
        await self._notify(f"«{state.agent.name}» не поднимается: {state.failures} неудач подряд. Присмотр остановлен.")

    async def _notify(self, text: str) -> None:
        delivered = await self.notifier.send(text)
        self.journal.write("присмотр", log.NOTIFIED, text if delivered else f"не доставлено: {text}", self._clock())

    async def tick(self) -> None:
        """Один проход по всем агентам."""
        moment = self._clock()
        for state in self.states:
            if state.broken:
                continue
            if state.running is None:
                if state.next_try is None or moment >= state.next_try:
                    await self._start(state, log.RESTARTED if state.restarts or state.failures else log.STARTED)
                continue
            reason = proc.check(state.running, moment)
            if reason is None:
                if state.failures and moment - state.running.started >= self._recovery:
                    state.failures = 0
                    self.journal.write(state.agent.name, log.RECOVERED, "работает стабильно", moment)
                continue
            kind = log.STUCK if reason.startswith("молчит") else log.CRASHED
            tail = "; ".join(state.running.tail(3))
            proc.stop(state.running)
            state.running = None
            state.failures += 1
            state.last_reason = reason
            state.history.append(reason)
            self.journal.write(state.agent.name, kind, f"{reason}. Последнее: {tail}" if tail else reason, moment)
            if kind == log.STUCK:
                await self._notify(f"«{state.agent.name}» {reason} — перезапускаю.")
            if state.agent.restart_limit == 0:
                state.broken = True
                self.journal.write(state.agent.name, log.OPENED, "перезапуск запрещён настройками", moment)
                continue
            await self._maybe_break(state)

    async def run(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        stop_when: Callable[[], bool] = lambda: False,
    ) -> None:
        await self.start_all()
        while not stop_when():
            await sleep(self.settings.check_every)
            await self.tick()

    def shutdown(self) -> None:
        for state in self.states:
            if state.running is not None:
                code = proc.stop(state.running)
                self.journal.write(state.agent.name, log.STOPPED, f"код {code}", self._clock())
                state.running = None
