"""ingest-bot client. Telegram allows one poller per bot token, so every
Telegram message goes through the bot's POST /tasks-message endpoint."""
from __future__ import annotations

import httpx


class BotError(Exception):
    pass


class Bot:
    def __init__(self, url: str, token: str):
        self.enabled = bool(url and token)
        self.client = httpx.AsyncClient(base_url=url, timeout=20,
                                        headers={"Authorization": f"Bearer {token}"} if token else {})
        self.last_error = ""

    async def send(self, title: str, text: str, buttons: list[dict] | None = None,
                   edit_message_id: int | None = None) -> int:
        """buttons: [{task_id, occurrence, label, op: done|snooze}] → message_id."""
        if not self.enabled:
            raise BotError("ingest-bot isn't configured (BOT_URL / BOT_TOKEN)")
        body = {"title": title, "text": text, "buttons": buttons or []}
        if edit_message_id:
            body["edit_message_id"] = edit_message_id
        try:
            r = await self.client.post("/tasks-message", json=body)
        except httpx.HTTPError as e:
            self.last_error = f"{type(e).__name__}: {e}"
            raise BotError(self.last_error) from None
        if r.status_code >= 400:
            self.last_error = f"/tasks-message -> {r.status_code} {r.text[:200]}"
            raise BotError(self.last_error)
        self.last_error = ""
        return int(r.json().get("message_id") or 0)

    async def close(self):
        await self.client.aclose()
