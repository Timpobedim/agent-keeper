from __future__ import annotations

from pathlib import Path

import pytest

from keeper.config import MAX_BACKOFF, Agent, ConfigError, load, parse

GOOD = {
    "keeper": {"journal": "журнал.sqlite", "check_every": 2, "webhook": "https://chat.example/hook"},
    "agent": [
        {"name": "сборщик", "command": "python -m worker --queue reports", "idle_timeout": 30},
        {"name": "почта", "command": ["python", "-m", "worker", "--queue", "mail"], "restart_limit": 0},
    ],
}


def test_settings_are_read(tmp_path: Path) -> None:
    settings = parse(GOOD, tmp_path)
    assert [agent.name for agent in settings.agents] == ["сборщик", "почта"]
    assert settings.agents[0].command == ("python", "-m", "worker", "--queue", "reports")
    assert settings.agents[0].idle_timeout == 30
    assert settings.agents[1].command == ("python", "-m", "worker", "--queue", "mail")
    assert settings.agents[1].restart_limit == 0
    assert settings.check_every == 2
    assert settings.journal == tmp_path / "журнал.sqlite"
    assert settings.agent("почта") is not None
    assert settings.agent("нет такого") is None


def test_backoff_grows_and_stops_growing() -> None:
    agent = Agent(name="а", command=("python",), backoff=2)
    assert [agent.pause(number) for number in (1, 2, 3, 4)] == [2, 4, 8, 16]
    assert agent.pause(20) == MAX_BACKOFF


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        ({"agent": []}, "хотя бы один агент"),
        ({"agent": [{"command": "python"}]}, "нужно имя"),
        ({"agent": [{"name": "а"}]}, "«command» — строка или список"),
        ({"agent": [{"name": "а", "command": ""}]}, "пустая команда"),
        ({"agent": [{"name": "а", "command": "python", "idle_timeout": -1}]}, "положительное число"),
        ({"agent": [{"name": "а", "command": "python", "restart_limit": -2}]}, "«restart_limit» — целое"),
        ({"agent": [{"name": "а", "command": "python", "environment": {"x": 1}}]}, "«environment»"),
        ({"agent": [{"name": "а", "command": "python", "cwd": "нет-такой"}]}, "не существует"),
        ({"agent": [{"name": "а", "command": "python"}, {"name": "а", "command": "python"}]}, "повторяются"),
        ({"keeper": [], "agent": [{"name": "а", "command": "python"}]}, "таблица настроек"),
    ],
)
def test_mistakes_are_explained(broken: dict[str, object], message: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=message):
        parse(broken, tmp_path)


def test_file_is_read_and_checked(tmp_path: Path) -> None:
    path = tmp_path / "keeper.toml"
    path.write_text(
        '[keeper]\ncheck_every = 3\n\n[[agent]]\nname = "сборщик"\ncommand = "python -m worker"\n', encoding="utf-8"
    )
    settings = load(path)
    assert settings.check_every == 3
    assert settings.agents[0].cwd == tmp_path

    broken = tmp_path / "плохой.toml"
    broken.write_text("[keeper\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Не удалось прочитать"):
        load(broken)
    with pytest.raises(ConfigError, match="Не удалось прочитать"):
        load(tmp_path / "нет-файла.toml")
