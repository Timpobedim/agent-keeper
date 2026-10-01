"""Проверки на настоящих процессах: игрушечные скрипты запускаются и падают взаправду."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from conftest import FAILING, SILENT, STEADY, agent, wait_until

from keeper.config import Agent
from keeper.journal import now
from keeper.process import ProcessError, check, start, stop


def test_running_agent_is_alive_and_talks(tmp_path: Path) -> None:
    running = start(agent(tmp_path, "надёжный", STEADY))
    try:
        assert wait_until(lambda: bool(running.tail()))
        assert check(running) is None
        assert any("живу" in line for line in running.tail())
    finally:
        stop(running)
    assert not running.alive


def test_crash_is_noticed(tmp_path: Path) -> None:
    running = start(agent(tmp_path, "падающий", FAILING))
    try:
        assert wait_until(lambda: not running.alive)
        assert check(running) == "завершился с кодом 3"
    finally:
        stop(running)


def test_silence_is_noticed(tmp_path: Path) -> None:
    running = start(agent(tmp_path, "зависающий", SILENT, idle_timeout=0.3))
    try:
        assert wait_until(lambda: bool(running.tail()))
        assert check(running) is None
        later = now() + timedelta(seconds=5)
        reason = check(running, later)
        assert reason is not None
        assert reason.startswith("молчит")
    finally:
        stop(running)


def test_stop_kills_a_long_running_agent(tmp_path: Path) -> None:
    running = start(agent(tmp_path, "долгий", SILENT))
    assert running.alive
    code = stop(running)
    assert code is not None
    assert not running.alive


def test_unknown_command_is_explained(tmp_path: Path) -> None:
    broken = Agent(name="нет такого", command=("этой-программы-точно-нет",), cwd=tmp_path)
    with pytest.raises(ProcessError, match="Не удалось запустить"):
        start(broken)
