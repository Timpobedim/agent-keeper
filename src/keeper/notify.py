"""Уведомления: в консоль всегда, в вебхук — если он задан.

Сбой уведомления не должен ронять присмотр: если вебхук недоступен, об этом печатается строка, а
агенты продолжают работать: отправка отделена от управления агентами.
"""

from __future__ import annotations

from typing import Protocol

import httpx

TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class Notifier(Protocol):
    name: str

    async def send(self, text: str) -> bool: ...


class ConsoleNotifier:
    name = "консоль"

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> bool:
        self.sent.append(text)
        print(f"! {text}")
        return True


class WebhookNotifier:
    """POST {"text": "…"} на заданный адрес. Неудача — не исключение, а False и строка в консоли."""

    def __init__(self, url: str, client: httpx.AsyncClient | None = None) -> None:
        self.name = f"вебхук {url}"
        self.url = url
        self._client = client

    async def send(self, text: str) -> bool:
        own = self._client is None
        session = self._client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await session.post(self.url, json={"text": text})
            if response.status_code >= 400:
                print(f"! уведомление не доставлено ({response.status_code}): {text}")
                return False
            return True
        except httpx.HTTPError as exc:
            print(f"! уведомление не доставлено ({exc.__class__.__name__}): {text}")
            return False
        finally:
            if own:
                await session.aclose()


def build(webhook: str, client: httpx.AsyncClient | None = None) -> Notifier:
    return WebhookNotifier(webhook, client) if webhook else ConsoleNotifier()
