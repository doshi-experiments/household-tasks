"""The minute tick: alarm pushes, high-priority overdue pushes, digests, the spoken fallback.

(Job and ledger names keep their original p0/p1 spelling so ledger rows stay continuous.)

Every send goes through the notifications ledger (UNIQUE task/kind/bucket/
channel), so a restart never sends twice. A timed job fires once its slot has
passed and no successful row exists for today, for up to CATCH_UP after the
slot; after a longer outage the slot is skipped rather than sent stale.
With NOTIFY_ENABLED=false nothing is sent: jobs log what they would do and
write rows on dry-<channel>, which don't block real sends later.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from . import digest
from .bot import Bot
from .config import Config
from .ha import HomeAssistant
from .shopping import Shopping
from .store import Store
from .tasks import Tasks, occurrence_key

log = logging.getLogger("tasks.scheduler")
CATCH_UP = timedelta(hours=3)
QUIET_STATE_TTL = timedelta(minutes=5)   # older than this -> fall back to the clock window
MAX_DIGEST_BUTTONS = 10


class Scheduler:
    def __init__(self, cfg: Config, store: Store, tasks: Tasks, shopping: Shopping, ha: HomeAssistant, bot: Bot):
        self.cfg, self.store, self.tasks, self.shopping, self.ha, self.bot = cfg, store, tasks, shopping, ha, bot
        self.last_tick: str = ""
        self.loop: asyncio.AbstractEventLoop | None = None
        self._refresh_pending = False
        self.quiet_state: tuple[bool, datetime] | None = None   # (night mode on?, when read)
        tasks.listeners.append(self._on_change)

    # ------------------------------------------------------------ ledger
    def sent(self, task_id: int, kind: str, bucket: str, channel: str) -> bool:
        return bool(self.store.one("SELECT 1 FROM notifications WHERE task_id=? AND kind=? AND bucket=? AND channel=? AND ok=1",
                                   (task_id, kind, bucket, channel)))

    def record(self, task_id: int, kind: str, bucket: str, channel: str, ok: bool, detail: str = ""):
        with self.store.tx() as db:
            db.execute("INSERT INTO notifications(task_id, kind, bucket, channel, sent_at, ok, detail) VALUES (?,?,?,?,?,?,?)"
                       " ON CONFLICT(task_id, kind, bucket, channel) DO UPDATE SET sent_at=excluded.sent_at,"
                       " ok=excluded.ok, detail=excluded.detail",
                       (task_id, kind, bucket, channel, self.tasks.now().isoformat(timespec="seconds"), int(ok), detail[:500]))

    async def deliver(self, task_id: int, kind: str, bucket: str, channel: str, make, summary: str,
                      force: bool = False, dry: bool | None = None) -> dict:
        """Run make() once per ledger key. Returns {channel, status, summary}."""
        dry = (not self.cfg.notify_enabled) if dry is None else dry
        key = f"dry-{channel}" if dry else channel
        if not force and self.sent(task_id, kind, bucket, key):
            return {"channel": channel, "status": "already sent", "summary": summary}
        if dry:
            self.record(task_id, kind, bucket, key, True, "dry-run: " + summary)
            log.info("dry-run %s %s task=%s: %s", kind, channel, task_id, summary.replace("\n", " | ")[:300])
            return {"channel": channel, "status": "dry-run", "summary": summary}
        try:
            detail = await make()
        except Exception as e:
            self.record(task_id, kind, bucket, channel, False, f"{type(e).__name__}: {e}")
            log.warning("send failed %s %s task=%s: %s", kind, channel, task_id, e)
            return {"channel": channel, "status": f"failed: {e}", "summary": summary}
        self.record(task_id, kind, bucket, channel, True, str(detail or ""))
        log.info("sent %s %s task=%s", kind, channel, task_id)
        return {"channel": channel, "status": "sent", "summary": summary}

    # ------------------------------------------------------------ helpers
    def _at(self, now: datetime, hhmm: str) -> datetime:
        hh, mm = map(int, hhmm.split(":"))
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)

    async def read_quiet(self, now: datetime):
        """Read HA night mode once per tick."""
        if not (self.ha.enabled and self.cfg.quiet_entity):
            return
        try:
            self.quiet_state = (await self.ha.state(self.cfg.quiet_entity) == "on", now)
        except Exception as e:
            log.warning("can't read %s (%s); using the %s-%s clock window", self.cfg.quiet_entity, e,
                        self.cfg.quiet_start, self.cfg.quiet_end)

    def quiet(self, when: datetime) -> bool:
        """Quiet while HA night mode is on: nothing is sent, pushed or spoken.
        When HA's state is unknown or stale, the QUIET_START-QUIET_END clock
        window stands in, so an HA outage can't cause a 2 am push."""
        st = self.quiet_state
        if st and abs(when - st[1]) <= QUIET_STATE_TTL:
            return st[0]
        if not (self.cfg.quiet_start and self.cfg.quiet_end):
            return False
        t, start, end = when.strftime("%H:%M"), self.cfg.quiet_start, self.cfg.quiet_end
        return start <= t < end if start < end else (t >= start or t < end)

    def _due_slot(self, now: datetime, hhmm: str, whole_day: bool = False) -> bool:
        """True while a timed send is due and it isn't quiet: from its slot for
        CATCH_UP (or, for P0, the rest of the day, so a dose due while night
        mode is on goes out as soon as it's switched off that day)."""
        if self.quiet(now):
            return False
        slot = self._at(now, hhmm)
        return slot <= now and (whole_day or now < slot + CATCH_UP)

    def _target(self, t: dict, default: str) -> str:
        p = self.cfg.person(t["assignee"])
        return p.send_to if p else default

    def _buttons(self, t: dict, snooze: bool = True, label: str = "Done") -> list[dict]:
        occ = occurrence_key(t)
        out = [{"task_id": t["id"], "occurrence": occ, "label": label, "op": "done"}]
        if snooze:
            out.append({"task_id": t["id"], "occurrence": occ, "label": "Snooze a day", "op": "snooze"})
        return out

    def _switch_entity(self, t: dict) -> str | None:
        return next((e for e, src in self.cfg.switch_tasks.items() if src == t["source"]), None)

    async def _telegram(self, kind: str, bucket: str, title: str, text: str, buttons: list[dict], task_ids: list[int]):
        mid = await self.bot.send(title, text, buttons)
        with self.store.tx() as db:
            db.execute("INSERT OR REPLACE INTO telegram_messages(message_id, kind, bucket, task_ids, sent_at) VALUES (?,?,?,?,?)",
                       (mid, kind, bucket, ",".join(map(str, task_ids)), self.tasks.now().isoformat(timespec="seconds")))
        return f"message {mid}"

    # ------------------------------------------------------------ jobs
    async def p0_push(self, now: datetime, force=False, dry=None, only_task=None, to=None) -> list[dict]:
        today, out = now.date().isoformat(), []
        for t in self.tasks.open_tasks():
            if not t["alarm"] or t["state"] not in ("due", "overdue") or (only_task and t["id"] != only_task):
                continue
            if not force and not self._due_slot(now, t["schedule"]["due_time"] or self.cfg.p0_default_time, whole_day=True):
                continue
            title, msg = digest.p0_push(t, now.date())
            send_to = to or self._target(t, self.cfg.p0_send_to)
            occ = occurrence_key(t)
            actions = [{"action": f"TASK_DONE_{t['id']}_{occ}", "title": "Done"},
                       {"action": f"TASK_SNOOZE_{t['id']}_{occ}", "title": "Snooze a day"}]
            out.append(await self.deliver(t["id"], "p0_push", today, "ha_push",
                                          lambda: self.ha.notify(send_to, title, msg, "critical", f"task-{t['id']}", actions),
                                          f"{title}: {msg} → {send_to}", force, dry))
            out.append(await self.deliver(t["id"], "p0_telegram", today, "telegram",
                                          lambda: self._telegram("p0", today, title, msg, self._buttons(t), [t["id"]]),
                                          f"{title}: {msg}", force, dry))
            if entity := self._switch_entity(t):
                out.append(await self.deliver(t["id"], "switch_on", today, "ha_switch",
                                              lambda: self.ha.set_switch(entity, True), f"{entity} on", force, dry))
        return out

    async def p1_overdue(self, now: datetime, force=False, dry=None, only_task=None, to=None) -> list[dict]:
        if not self.cfg.p1_overdue_push and not force:
            return []
        if not force and not self._due_slot(now, self.cfg.p1_overdue_push_time):
            return []
        today, out = now.date().isoformat(), []
        for t in self.tasks.open_tasks():
            if t["priority"] != 1 or t["alarm"] or not t["overdue"] or (only_task and t["id"] != only_task):
                continue
            title, msg = digest.p1_overdue_push(t)
            send_to = to or self._target(t, self.cfg.digest_send_to)
            occ = occurrence_key(t)
            actions = [{"action": f"TASK_DONE_{t['id']}_{occ}", "title": "Done"},
                       {"action": f"TASK_SNOOZE_{t['id']}_{occ}", "title": "Snooze a day"}]
            out.append(await self.deliver(t["id"], "p1_overdue_push", today, "ha_push",
                                          lambda: self.ha.notify(send_to, title, msg, "time-sensitive", f"task-{t['id']}", actions, respect_quiet=True),
                                          f"{title}: {msg} → {send_to}", force, dry))
        return out

    async def digest_job(self, now: datetime, kind: str, force=False, dry=None, to=None) -> list[dict]:
        slot = self.cfg.digest_morning if kind == "morning" else self.cfg.digest_evening
        if not force and not self._due_slot(now, slot):
            return []
        today, out = now.date().isoformat(), []
        if not force and self.sent(0, f"digest_{kind}", today, "empty"):
            return []   # this slot already ran with nothing to say; never send it later
        open_tasks = self.tasks.open_tasks()
        secs = digest.sections(open_tasks, now.date(), kind)
        job = f"digest_{kind}"
        head, body = digest.render(secs, now.date(), kind)
        if not body:
            # Nothing to say: still mark the slot so nothing fires later today.
            self.record(0, job, today, "empty", True, "nothing due")
            return [{"channel": "all", "status": "empty", "summary": "nothing due"}]
        listed = [t for _, rows in secs for t in rows]
        buttons = [b for t in listed[:MAX_DIGEST_BUTTONS] for b in self._buttons(t, snooze=False, label=f"Done: {t['title'][:32]}")]
        text = body + (f"\n…and {len(listed) - MAX_DIGEST_BUTTONS} more in Tasks" if len(listed) > MAX_DIGEST_BUTTONS else "")
        out.append(await self.deliver(0, job, today, "telegram",
                                      lambda: self._telegram(job, today, head, text, buttons, [t["id"] for t in listed]),
                                      f"{head}\n{body}", force, dry))
        people = [p for p in self.cfg.people if not to or p.send_to == to]
        for p in people:
            ph, pb = digest.render(secs, now.date(), kind, p.id)
            out.append(await self.deliver(0, job, today, f"ha_push:{p.id}",
                                          lambda p=p, ph=ph, pb=pb: self.ha.notify(p.send_to, ph, pb, "active", "tasks-digest", respect_quiet=True),
                                          f"{ph} → {p.send_to}", force, dry))
        return out

    async def spoken_fallback(self, now: datetime, force=False, dry=None) -> list[dict]:
        if not self.cfg.spoken_fallback or (not force and not self._due_slot(now, self.cfg.spoken_fallback)):
            return []
        today = now.date().isoformat()
        if not force and (self.sent(0, "dog_alarm_digest", today, "spoken") or self.sent(0, "dog_alarm_nag", today, "spoken")):
            return []
        said = digest.dog_alarm(self.tasks.open_tasks(), first_today=True)
        if not said["text"]:
            return []
        return [await self.deliver(0, "spoken_fallback", today, "spoken",
                                   lambda: self.ha.announce(said["text"], said["verbatim"]), said["text"], force, dry)]

    async def tick(self, now: datetime | None = None):
        now = now or self.tasks.now()
        self.last_tick = now.isoformat(timespec="seconds")
        await self.read_quiet(now)
        for name, job in (("p0_push", lambda: self.p0_push(now)), ("p1_overdue", lambda: self.p1_overdue(now)),
                          ("digest_morning", lambda: self.digest_job(now, "morning")),
                          ("digest_evening", lambda: self.digest_job(now, "evening")),
                          ("spoken_fallback", lambda: self.spoken_fallback(now))):
            try:
                await job()
            except Exception:
                log.exception("job %s failed", name)
        if now.hour == 0 and now.minute == 5:
            # Overdue tasks are placed on "today" in the feed; let HA see the new day.
            await self.refresh_calendar()
        if now.hour == 3 and now.minute == 30:
            n = await asyncio.to_thread(self.shopping.prune)
            if n:
                log.info("pruned %d bought items older than 90 days", n)

    async def run_job(self, job: str, force=False, dry=None, only_task=None, to=None) -> list[dict]:
        now = self.tasks.now()
        if job == "p0_push":
            return await self.p0_push(now, force, dry, only_task, to)
        if job == "p1_overdue":
            return await self.p1_overdue(now, force, dry, only_task, to)
        if job in ("digest_morning", "digest_evening"):
            return await self.digest_job(now, job.split("_")[1], force, dry, to)
        if job == "spoken_fallback":
            return await self.spoken_fallback(now, force, dry)
        raise ValueError(f"Unknown job {job!r}")

    async def run(self):
        self.loop = asyncio.get_running_loop()
        while True:
            now = self.tasks.now()
            await asyncio.sleep(60 - now.second - now.microsecond / 1e6 + 0.05)
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")

    # ------------------------------------------------------------ side effects of changes
    async def refresh_calendar(self, delay: float = 0):
        """Ask HA to re-read calendar.ics now; Remote Calendar's own polling is slow."""
        if not (self.ha.enabled and self.cfg.ha_calendar_entity):
            return
        if delay:
            if self._refresh_pending:
                return
            self._refresh_pending = True
            await asyncio.sleep(delay)
            self._refresh_pending = False
        try:
            await self.ha.service("homeassistant", "update_entity", {"entity_id": self.cfg.ha_calendar_entity})
        except Exception as e:
            log.warning("calendar refresh failed: %s", e)

    def _on_change(self, event: str, task: dict):
        """Called from request threads after a commit; schedules async follow-ups."""
        if not self.loop:
            return
        asyncio.run_coroutine_threadsafe(self.refresh_calendar(delay=15), self.loop)
        # (the calendar refresh stays: a task moved into homelab must leave HA's calendar)
        if event in ("completed", "skipped", "snoozed", "archived") and task.get("area") != "homelab":
            asyncio.run_coroutine_threadsafe(self._after_close(event, task), self.loop)

    async def _after_close(self, event: str, task: dict):
        bucket = self.tasks.now().isoformat(timespec="minutes")
        dry = not self.cfg.notify_enabled
        # Phones only: the tablet's TTS notifier would read the clear command aloud.
        phones = [p.send_to for p in self.cfg.people]
        await self.deliver(task["id"], f"clear_{event}", bucket, "ha_push",
                           lambda: self.ha.clear(phones, f"task-{task['id']}"), f"clear task-{task['id']}", dry=dry)
        if entity := self._switch_entity(task):
            await self.deliver(task["id"], f"switch_off_{event}", bucket, "ha_switch",
                               lambda: self.ha.set_switch(entity, False), f"{entity} off", dry=dry)
