"""Home Assistant REST client: the notification hub, speech, switches, calendars."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("tasks.ha")
LEVEL = {0: "critical", 1: "time-sensitive", 2: "active", 3: "active"}


class HAError(Exception):
    pass


class HomeAssistant:
    def __init__(self, url: str, token: str):
        self.url, self.enabled = url, bool(url and token)
        self.client = httpx.AsyncClient(base_url=url, timeout=20,
                                        headers={"Authorization": f"Bearer {token}"} if token else {})
        self.last_error = ""

    async def _call(self, method: str, path: str, **kw):
        if not self.enabled:
            raise HAError("Home Assistant isn't configured (HA_URL / HA_TOKEN)")
        try:
            r = await self.client.request(method, path, **kw)
        except httpx.HTTPError as e:
            self.last_error = f"{type(e).__name__}: {e}"
            raise HAError(self.last_error) from None
        if r.status_code >= 400:
            self.last_error = f"{method} {path} -> {r.status_code} {r.text[:200]}"
            raise HAError(self.last_error)
        self.last_error = ""
        return r.json() if r.content else None

    async def ping(self) -> bool:
        try:
            await self._call("GET", "/api/config")
            return True
        except HAError:
            return False

    async def state(self, entity_id: str) -> str:
        return (await self._call("GET", f"/api/states/{entity_id}") or {}).get("state", "")

    async def service(self, domain: str, name: str, data: dict, response: bool = False):
        path = f"/api/services/{domain}/{name}" + ("?return_response" if response else "")
        return await self._call("POST", path, json=data)

    async def notify(self, send_to, title: str, message: str, level: str = "active", tag: str | None = None,
                     actions: list | None = None, group: str = "tasks", url: str | None = None,
                     respect_quiet: bool = False):
        data = {"action_type": "send", "send_to": send_to if isinstance(send_to, list) else [send_to],
                "title": title, "message": message, "interruption_level": level, "group": group}
        if level == "critical":
            data["critical_alert_volume"] = 1
        if tag:
            data["tag"] = tag
        if actions:
            data["actions"] = actions
        if url:
            data["url"] = url
        if respect_quiet:   # the hub holds non-critical pushes while night mode is on
            data["respect_quiet_hours"] = True
        await self.service("script", "system_advanced_notification", data)

    async def clear(self, send_to, tag: str):
        await self.service("script", "system_advanced_notification",
                           {"action_type": "clear", "send_to": send_to if isinstance(send_to, list) else [send_to],
                            "tag": tag, "message": "clear_notification"})

    async def write_text(self, script: str, prompt: str, fallback: str) -> str:
        """Ask an HA script (prompt, fallback_text -> {text}) for a line in the house's voice."""
        domain, _, name = script.partition(".")
        resp = await self._call("POST", f"/api/services/{domain}/{name}?return_response",
                                json={"prompt": prompt, "fallback_text": fallback}, timeout=60)
        text = (((resp or {}).get("service_response") or {}).get("text") or "").strip()
        return text or fallback

    async def announce(self, text: str, verbatim: bool):
        await self.service("script", "tasks_announce", {"text": text, "verbatim": verbatim})

    async def set_switch(self, entity_id: str, on: bool):
        domain = entity_id.split(".", 1)[0]
        await self.service(domain, "turn_on" if on else "turn_off", {"entity_id": entity_id})

    async def get_events(self, entity_ids: list[str], start: str, end: str) -> list[dict]:
        if not entity_ids:
            return []
        resp = await self.service("calendar", "get_events",
                                  {"entity_id": entity_ids, "start_date_time": start, "end_date_time": end}, response=True)
        out = []
        for entity, body in ((resp or {}).get("service_response") or {}).items():
            for e in body.get("events", []):
                start_v = str(e.get("start", ""))
                out.append({"summary": e.get("summary") or "Untitled", "start": start_v, "end": str(e.get("end", "")),
                            "all_day": "T" not in start_v, "calendar": entity,
                            "location": e.get("location") or ""})
        return out

    async def close(self):
        await self.client.aclose()
