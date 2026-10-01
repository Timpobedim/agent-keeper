"""Агент как обычный процесс: запустить, следить за выводом, понять, что он умер или завис, остановить.

Не tmux и разбор текста панели регулярными выражениями (только Linux, ломается от перерисовки экрана),
а обычный процесс и его вывод:
одинаково на Windows и Linux, и видно, когда агент последний раз подавал признаки жизни.
"""

from __future__ import annotations

import locale
import os
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from keeper.config import Agent
from keeper.journal import now

TAIL = 200  # столько последних строк вывода держим для отчёта
STOP_TIMEOUT = 5.0

# Кодировки, которыми пробуем читать чужой вывод, по порядку.
#
# Надзиратель запускает произвольные программы, а не только Python, поэтому заставить их писать
# в UTF-8 переменными окружения нельзя — разбираться приходится на стороне чтения. Порядок важен:
# UTF-8 строгий и на чужих байтах честно падает, а однобайтовая кодовая страница принимает что
# угодно, поэтому идёт второй. Раньше здесь стояло жёсткое `encoding="utf-8"`, и на русской Windows
# вывод дочернего процесса (он пишет в cp1251) превращался в символы замены: агент рапортовал
# «живу», а в отчёте была каша.
_ENCODINGS = tuple(dict.fromkeys(("utf-8", locale.getpreferredencoding(False).lower(), "cp866", "cp1251")))


class ProcessError(RuntimeError):
    pass


@dataclass
class Running:
    agent: Agent
    process: subprocess.Popen[bytes]
    started: datetime
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_output: datetime = field(default_factory=now)
    _lines: deque[str] = field(default_factory=lambda: deque(maxlen=TAIL))

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def last_output(self) -> datetime:
        with self._lock:
            return self._last_output

    def tail(self, limit: int = 10) -> list[str]:
        with self._lock:
            return list(self._lines)[-limit:]

    def note(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            self._last_output = now()


def start(agent: Agent) -> Running:
    """Запускает агента и включает чтение его вывода в отдельном потоке."""
    environment = {**os.environ, **agent.environment}
    try:
        process = subprocess.Popen(  # noqa: S603 — запуск заданной пользователем команды и есть смысл присмотра
            list(agent.command),
            cwd=agent.cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # Читаем байтами: какой кодировкой пишет чужая программа, заранее неизвестно.
        )
    except (OSError, ValueError) as exc:
        raise ProcessError(f"Не удалось запустить «{agent.name}»: {exc}") from exc
    running = Running(agent, process, now())
    reader = threading.Thread(target=_read, args=(running,), name=f"вывод-{agent.name}", daemon=True)
    reader.start()
    return running


def _decode(raw: bytes) -> str:
    """Строка чужого процесса: пробуем кодировки по порядку, в крайнем случае — с заменой байт."""
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _read(running: Running) -> None:
    stream = running.process.stdout
    if stream is None:  # pragma: no cover — stdout всегда открыт при stdout=PIPE
        return
    for line in stream:
        running.note(_decode(line).rstrip())


def check(running: Running, moment: datetime | None = None) -> str | None:
    """None — агент жив и подаёт признаки жизни; иначе причина, по которой его пора перезапустить."""
    at = moment or now()
    code = running.process.poll()
    if code is not None:
        return f"завершился с кодом {code}" if code else "завершился сам"
    silence = (at - running.last_output).total_seconds()
    if running.agent.idle_timeout and silence > running.agent.idle_timeout:
        return f"молчит {int(silence)} с"
    return None


def stop(running: Running, timeout: float = STOP_TIMEOUT) -> int | None:
    """Мягко просим завершиться, через timeout — убиваем. Возвращает код выхода."""
    if running.process.poll() is None:
        running.process.terminate()
        try:
            running.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            running.process.kill()
            running.process.wait(timeout=timeout)
    stream = running.process.stdout
    if stream is not None and not stream.closed:
        stream.close()
    return running.process.poll()
