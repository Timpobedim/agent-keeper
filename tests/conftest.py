from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from keeper.config import Agent
from keeper.journal import Journal

STEADY = """
import time
for number in range(1000):
    print("живу", number, flush=True)
    time.sleep(0.1)
"""
FAILING = """
import sys
print("сейчас упаду", flush=True)
sys.exit(3)
"""
SILENT = """
import time
print("замолчал", flush=True)
time.sleep(60)
"""


def script(folder: Path, name: str, source: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.py"
    path.write_text(source.strip() + "\n", encoding="utf-8")
    return path


def agent(folder: Path, name: str, source: str, **options: object) -> Agent:
    return Agent(name=name, command=(sys.executable, str(script(folder, name, source))), cwd=folder, **options)  # type: ignore[arg-type]


def wait_until(condition: Callable[[], bool], timeout: float = 5.0, step: float = 0.05) -> bool:
    """Ждём событие от настоящего процесса, но не дольше timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(step)
    return condition()


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[Journal]:
    log = Journal(tmp_path / "журнал.sqlite")
    yield log
    log.close()
