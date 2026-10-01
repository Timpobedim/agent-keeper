"""Демо: три игрушечных агента — надёжный, падающий и зависающий — под присмотром, но быстро.

Настройки те же, что в рабочем файле, только время сжато: проверка раз в полсекунды, зависанием
считается молчание две секунды. За десяток секунд видно всё: перезапуски, растущие паузы и
размыкание цепи.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from keeper.config import Agent, Settings

STEADY = """
import sys, time
for number in range(1000):
    print(f"обработал пакет {number}", flush=True)
    time.sleep(0.4)
"""
FAILING = """
import sys, time
print("начал работу", flush=True)
time.sleep(0.6)
print("не смог подключиться к очереди", flush=True)
sys.exit(1)
"""
STUCK = """
import time
print("начал работу", flush=True)
time.sleep(600)
"""
AGENTS = (("надёжный", STEADY), ("падающий", FAILING), ("зависающий", STUCK))


@dataclass(frozen=True)
class Demo:
    settings: Settings
    folder: Path


def prepare(folder: Path) -> Demo:
    """Пишет скрипты агентов и собирает настройки со сжатым временем."""
    folder.mkdir(parents=True, exist_ok=True)
    agents = []
    for name, source in AGENTS:
        script = folder / f"{name}.py"
        script.write_text(source.strip() + "\n", encoding="utf-8")
        agents.append(
            Agent(
                name=name,
                command=(sys.executable, str(script)),
                cwd=folder,
                restart_limit=2 if name == "падающий" else 5,
                backoff=0.4,
                idle_timeout=2.0,
            )
        )
    settings = Settings(tuple(agents), journal=folder / "журнал.sqlite", check_every=0.5)
    return Demo(settings, folder)
