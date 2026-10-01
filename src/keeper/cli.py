"""Командная строка: присматривать, сделать один проход, показать отчёт, показать демо.

keeper run --config keeper.toml
keeper once --config keeper.toml
keeper status --config keeper.toml --hours 24
keeper demo
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from keeper.config import ConfigError, Settings, load
from keeper.demo import prepare
from keeper.journal import Journal
from keeper.notify import build
from keeper.process import ProcessError
from keeper.status import report, table
from keeper.supervisor import Keeper

DEMO_SECONDS = 12.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keeper", description="Присмотр за фоновыми агентами")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("run", "запустить агентов и присматривать за ними"),
        ("once", "один проход проверки — для планировщика"),
        ("status", "показать состояние и журнал"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--config", type=Path, default=Path("keeper.toml"), help="файл настроек")
        if name == "status":
            command.add_argument("--hours", type=float, default=24.0, help="за сколько часов показать события")
    demo = commands.add_parser("demo", help="показать присмотр на трёх игрушечных агентах")
    demo.add_argument("--seconds", type=float, default=DEMO_SECONDS, help="сколько секунд наблюдать")
    return parser


async def _run(settings: Settings, *, once: bool = False) -> int:
    journal = Journal(settings.journal)
    keeper = Keeper(settings, journal, build(settings.webhook))
    try:
        if once:
            await keeper.start_all()
            await keeper.tick()
            print(table(keeper.states))
            return 0
        print(f"Присмотр за агентами: {', '.join(agent.name for agent in settings.agents)}. Ctrl+C — остановить.")
        await keeper.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nОстанавливаю агентов…")
    finally:
        keeper.shutdown()
        journal.close()
    return 0


async def _demo(seconds: float) -> int:
    folder = Path(tempfile.mkdtemp(prefix="keeper-demo-"))
    demo = prepare(folder)
    journal = Journal(demo.settings.journal)
    keeper = Keeper(demo.settings, journal, build(""))
    deadline = time.monotonic() + seconds
    try:
        await keeper.run(stop_when=lambda: time.monotonic() >= deadline)
    finally:
        keeper.shutdown()
    print()
    print(report(journal, keeper.states, hours=1))
    journal.close()
    print(f"\nЖурнал и скрипты агентов: {folder}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo":
            return asyncio.run(_demo(args.seconds))
        settings = load(args.config)
        if args.command == "status":
            journal = Journal(settings.journal)
            try:
                print(report(journal, [], hours=args.hours))
            finally:
                journal.close()
            return 0
        return asyncio.run(_run(settings, once=args.command == "once"))
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ProcessError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
