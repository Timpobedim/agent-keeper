"""Описание агентов — в одном TOML-файле, а не в переменных модуля.

Поэтому несколько агентов живут в одном процессе, а настройки можно проверить и показать целиком.
"""

from __future__ import annotations

import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CHECK = 5.0
DEFAULT_BACKOFF = 2.0
DEFAULT_LIMIT = 5
DEFAULT_IDLE = 300.0
MAX_BACKOFF = 300.0


class ConfigError(ValueError):
    """Файл настроек написан неправильно; текст — для человека."""


@dataclass(frozen=True)
class Agent:
    name: str
    command: tuple[str, ...]
    cwd: Path = Path()
    environment: dict[str, str] = field(default_factory=dict)
    restart_limit: int = DEFAULT_LIMIT  # столько неудач подряд — и цепь размыкается
    backoff: float = DEFAULT_BACKOFF  # первая пауза перед перезапуском, дальше вдвое
    idle_timeout: float = DEFAULT_IDLE  # молчит дольше — считаем зависшим
    restart_always: bool = True  # перезапускать даже после спокойного завершения

    def pause(self, failures: int) -> float:
        """Пауза перед очередным перезапуском: 2, 4, 8… но не больше пяти минут."""
        return min(self.backoff * 2.0 ** max(failures - 1, 0), MAX_BACKOFF)


@dataclass(frozen=True)
class Settings:
    agents: tuple[Agent, ...]
    journal: Path = Path("журнал.sqlite")
    check_every: float = DEFAULT_CHECK
    webhook: str = ""

    def agent(self, name: str) -> Agent | None:
        return next((agent for agent in self.agents if agent.name == name), None)


def _command(raw: object, name: str) -> tuple[str, ...]:
    if isinstance(raw, str):
        parts = tuple(shlex.split(raw, posix=False))
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        parts = tuple(str(item) for item in raw)
    else:
        raise ConfigError(f"Агент «{name}»: «command» — строка или список строк")
    if not parts:
        raise ConfigError(f"Агент «{name}»: пустая команда")
    return parts


def _number(raw: object, name: str, field_name: str, default: float) -> float:
    if raw is None:
        return default
    if not isinstance(raw, int | float) or isinstance(raw, bool) or raw <= 0:
        raise ConfigError(f"Агент «{name}»: «{field_name}» — положительное число")
    return float(raw)


def _agent(raw: object, base: Path) -> Agent:
    if not isinstance(raw, dict) or not raw.get("name"):
        raise ConfigError("У каждого агента нужно имя: [[agent]] name = «сборщик»")
    name = str(raw["name"])
    environment = raw.get("environment", {})
    if not isinstance(environment, dict) or not all(isinstance(value, str) for value in environment.values()):
        raise ConfigError(f"Агент «{name}»: «environment» — пары «имя = значение» строками")
    cwd = base / str(raw.get("cwd", "."))
    if not cwd.exists():
        raise ConfigError(f"Агент «{name}»: папка {cwd} не существует")
    limit = raw.get("restart_limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ConfigError(f"Агент «{name}»: «restart_limit» — целое число, 0 значит «не перезапускать»")
    return Agent(
        name=name,
        command=_command(raw.get("command"), name),
        cwd=cwd,
        environment={str(key): str(value) for key, value in environment.items()},
        restart_limit=limit,
        backoff=_number(raw.get("backoff"), name, "backoff", DEFAULT_BACKOFF),
        idle_timeout=_number(raw.get("idle_timeout"), name, "idle_timeout", DEFAULT_IDLE),
        restart_always=bool(raw.get("restart_always", True)),
    )


def parse(data: dict[str, object], base: Path = Path()) -> Settings:
    agents_raw = data.get("agent")
    if not isinstance(agents_raw, list) or not agents_raw:
        raise ConfigError("Нужен хотя бы один агент: секция [[agent]]")
    keeper = data.get("keeper", {})
    if not isinstance(keeper, dict):
        raise ConfigError("Секция [keeper] — это таблица настроек")
    agents = tuple(_agent(raw, base) for raw in agents_raw)
    names = [agent.name for agent in agents]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ConfigError(f"Имена агентов повторяются: {', '.join(sorted(duplicates))}")
    return Settings(
        agents=agents,
        journal=base / str(keeper.get("journal", "журнал.sqlite")),
        check_every=_number(keeper.get("check_every"), "keeper", "check_every", DEFAULT_CHECK),
        webhook=str(keeper.get("webhook", "")),
    )


def load(path: Path) -> Settings:
    try:
        data = tomllib.loads(path.read_text("utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Не удалось прочитать {path.name}: {exc}") from exc
    return parse(data, path.parent)
