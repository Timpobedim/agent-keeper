from __future__ import annotations

import sys
from pathlib import Path

import pytest
from conftest import STEADY, script

from keeper.cli import main


def config_for(tmp_path: Path) -> Path:
    path = script(tmp_path, "надёжный", STEADY)
    config = tmp_path / "keeper.toml"
    config.write_text(
        "[keeper]\n"
        'journal = "журнал.sqlite"\n'
        "check_every = 0.2\n\n"
        "[[agent]]\n"
        'name = "надёжный"\n'
        f"command = [{sys.executable.replace(chr(92), '/')!r}, {str(path).replace(chr(92), '/')!r}]\n"
        "idle_timeout = 30\n",
        encoding="utf-8",
    )
    return config


def test_once_starts_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["once", "--config", str(config_for(tmp_path))]) == 0
    printed = capsys.readouterr().out
    assert "надёжный" in printed
    assert "работает" in printed


def test_status_shows_the_journal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = config_for(tmp_path)
    assert main(["once", "--config", str(config)]) == 0
    capsys.readouterr()
    assert main(["status", "--config", str(config), "--hours", "1"]) == 0
    printed = capsys.readouterr().out
    assert "События" in printed
    assert "надёжный: запуск" in printed


@pytest.mark.slow
def test_demo_shows_restarts_and_broken_circuit(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", "--seconds", "6"]) == 0
    printed = capsys.readouterr().out
    assert "надёжный" in printed
    assert "падающий" in printed
    assert "зависающий" in printed
    assert "перезапуск" in printed


def test_bad_config_is_explained(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "keeper.toml"
    broken.write_text('[[agent]]\nname = "без команды"\n', encoding="utf-8")
    assert main(["run", "--config", str(broken)]) == 2
    assert "«command»" in capsys.readouterr().err
    assert main(["status", "--config", str(tmp_path / "нет.toml")]) == 2
