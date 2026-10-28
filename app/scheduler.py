"""The minute tick: alarm pushes, nagging reminders, high-priority overdue pushes, digests, the spoken fallback.

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
import json
import logging
from datetime import datetime, timedelta

from . import digest, voices
from .bot import Bot
from .config import Config
from .ha import HomeAssistant
from .shopping import Shopping
from .store import Store
from .tasks import TaskError, Tasks, occurrence_key

log = logging.getLogger("tasks.scheduler")
CATCH_UP = timedelta(hours=3)
QUIET_STATE_TTL = timedelta(minutes=5)   # older than this -> fall back to the clock window
MAX_DIGEST_BUTTONS = 10
TIDY_DAYS = 7   # Telegram messages older than this keep their buttons when a task closes


class Scheduler:
    def __init__(self, cfg: Config, store: Store, tasks: Tasks, shopping: Shopping, ha: HomeAssistant, bot: Bot):
        self.cfg, self.store, self.tasks, self.shopping, self.ha, self.bot = cfg, store, tasks, shopping, ha, bot
        self.last_tick: str = ""
        self.loop: asyncio.AbstractEventLoop | None = None
        self._p0_lock = asyncio.Lock()   # the minute tick and the dog-alarm hook both run p0_push
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

    def with_announcement(self, t: dict) -> bool:
        """Alarms at the default time go out with the evening feed-the-dogs
        announcement; a task with a time of its own keeps it."""
        return (t["schedule"]["due_time"] or self.cfg.p0_default_time) in (self.cfg.p0_default_time, self.cfg.default_due_time)

    def announcement_due(self, now: datetime) -> bool:
        """True once today's first feeding announcement has played (HA called
        /hooks/dog-alarm), or from SPOKEN_FALLBACK (20:30) on days it never
        plays; never while quiet."""
        if self.quiet(now):
            return False
        if self.sent(0, "dog_alarm_heard", now.date().isoformat(), "hook"):
            return True
        return bool(self.cfg.spoken_fallback) and self._due_slot(now, self.cfg.spoken_fallback, whole_day=True)

    def _target(self, t: dict, default: str) -> str:
        p = self.cfg.person(t["assignee"])
        return p.send_to if p else default

    def _buttons(self, t: dict, snooze: bool = True, label: str = "Done", snooze_label: str = "Snooze a day") -> list[dict]:
        occ = occurrence_key(t)
        out = [{"task_id": t["id"], "occurrence": occ, "label": label, "op": "done"}]
        if snooze:
            out.append({"task_id": t["id"], "occurrence": occ, "label": snooze_label, "op": "snooze"})
        return out

    def voice(self, now: datetime) -> voices.Today:
        """The house's voice today, with one-off tasks' stored lines."""
        return voices.Today(now.date(), self.store)

    def _switch_entity(self, t: dict) -> str | None:
        return next((e for e, src in self.cfg.switch_tasks.items() if src == t["source"]), None)

    async def _telegram(self, kind: str, bucket: str, title: str, text: str, buttons: list[dict], task_ids: list[int]):
        mid = await self.bot.send(title, text, buttons)
        with self.store.tx() as db:
            db.execute("INSERT OR REPLACE INTO telegram_messages(message_id, kind, bucket, task_ids, sent_at, buttons)"
                       " VALUES (?,?,?,?,?,?)",
                       (mid, kind, bucket, ",".join(map(str, task_ids)), self.tasks.now().isoformat(timespec="seconds"),
                        json.dumps(buttons)))
        return f"message {mid}"

    def _live(self, b: dict) -> bool:
        """Would this button still work? Its task is open at the same occurrence and not snoozed."""
        try:
            t = self.tasks.get(int(b["task_id"]))
        except TaskError:
            return False
        return (t["status"] == "open" and t["occurrence"] == b["occurrence"]
                and not (t["snoozed_until"] and t["snoozed_until"] > self.tasks.today().isoformat()))

    def _offering(self, task_id: int) -> list[dict]:
        """Recent Telegram messages whose stored buttons include this task."""
        since = (self.tasks.now() - timedelta(days=TIDY_DAYS)).isoformat(timespec="seconds")
        rows = self.store.all("SELECT message_id, buttons FROM telegram_messages"
                              " WHERE buttons IS NOT NULL AND buttons != '[]' AND sent_at >= ?", (since,))
        return [r for r in rows if any(b["task_id"] == task_id for b in json.loads(r["buttons"]))]

    async def _tidy_telegram(self, event: str, task: dict, rows: list[dict]) -> str:
        """Take a task closed elsewhere off the Telegram messages that still offer it:
        each keeps only the buttons that still work, plus a line saying who closed
        it and where. Editing is silent (nothing pushes or rings), so night mode
        doesn't hold it. The message a button tap came from is ingest-bot's to edit."""
        line, edited, failed = digest.closed_line(event, task), [], []
        for r in rows:
            live = [b for b in json.loads(r["buttons"]) if self._live(b)]
            try:
                await self.bot.update(r["message_id"], live, line, task["id"])
            except Exception as e:
                failed.append(f"{r['message_id']}: {e}")
                continue
            with self.store.tx() as db:
                db.execute("UPDATE telegram_messages SET buttons=? WHERE message_id=?", (json.dumps(live), r["message_id"]))
            edited.append(str(r["message_id"]))
        if failed:
            raise RuntimeError(f"edited {edited or 'none'}; failed {'; '.join(failed)}")
        return f"edited message {', '.join(edited)}"

    # ------------------------------------------------------------ jobs
    async def p0_push(self, now: datetime, force=False, dry=None, only_task=None, to=None) -> list[dict]:
        async with self._p0_lock:
            return await self._p0_push(now, force, dry, only_task, to)

    async def _p0_push(self, now: datetime, force=False, dry=None, only_task=None, to=None) -> list[dict]:
        today, out = now.date().isoformat(), []
        for t in self.tasks.open_tasks():
            if not t["alarm"] or t["state"] not in ("due", "overdue") or (only_task and t["id"] != only_task):
                continue
            if not force and not (self.announcement_due(now) if self.with_announcement(t)
                                  else self._due_slot(now, t["schedule"]["due_time"], whole_day=True)):
                continue
            v = self.voice(now)
            title, msg = digest.p0_push(t, now.date(), v)
            send_to = to or self._target(t, self.cfg.p0_send_to)
            occ = occurrence_key(t)
            actions = [{"action": f"TASK_DONE_{t['id']}_{occ}", "title": v.done},
                       {"action": f"TASK_SNOOZE_{t['id']}_{occ}", "title": v.snooze}]
            out.append(await self.deliver(t["id"], "p0_push", today, "ha_push",
                                          lambda: self.ha.notify(send_to, title, msg, "critical", f"task-{t['id']}", actions),
                                          f"{title}: {msg} → {send_to}", force, dry))
            out.append(await self.deliver(t["id"], "p0_telegram", today, "telegram",
                                          lambda: self._telegram("p0", today, "", msg, self._buttons(t, label=v.done, snooze_label=v.snooze),
                                                                 [t["id"]]),
                                          msg, force, dry))
            if entity := self._switch_entity(t):
                out.append(await self.deliver(t["id"], "switch_on", today, "ha_switch",
                                              lambda: self.ha.set_switch(entity, True), f"{entity} on", force, dry))
        return out

    def nag_step(self, t: dict, now: datetime) -> tuple[bool, int, datetime, int] | None:
        """Where a nagging task stands now: (escalated?, step, slot, minutes since due),
        or None when it has nothing to say. Only the current slot is ever sent, so
        slots missed in an outage are skipped rather than sent in a burst."""
        n, due_time = t["nag"], t["schedule"]["due_time"] or self.cfg.default_due_time
        if not n or t["state"] != "due" or t["eff_due"] != now.date().isoformat():
            return None
        start = self._at(now, due_time)
        if now < start:
            return None
        esc = self._at(now, n["escalate_at"]) if n["escalate_at"] else None
        escalated = bool(esc and now >= esc)
        base, every = (max(esc, start), n["escalate_every"]) if escalated else (start, n["every"])
        step = int((now - base).total_seconds() // (every * 60)) if every else 0
        slot = base + timedelta(minutes=(every or 0) * step)
        return escalated, step, slot, int((slot - start).total_seconds() // 60)

    async def nag_push(self, now: datetime, force=False, dry=None, only_task=None, to=None) -> list[dict]:
        """Nagging tasks: from the due time, the assignee's phone and the Telegram group
        every nag.every minutes, each line more passive-aggressive than the last (in a
        house voice picked for the day); from
        nag.escalate_at, a critical push to nag.escalate_to and the group every
        nag.escalate_every minutes, until someone taps Done. Night mode holds the
        repeats but not the escalation: that is a critical alert and goes anyway."""
        out = []
        dry = (not self.cfg.notify_enabled) if dry is None else dry
        for t in self.tasks.open_tasks():
            if only_task and t["id"] != only_task:
                continue
            where = self.nag_step(t, now)
            if not where:
                continue
            escalated, step, slot, late = where
            if not escalated and self.quiet(now) and not force:
                continue
            kind, bucket = ("escalate" if escalated else "nag"), slot.isoformat(timespec="minutes")
            channels = (("push", "ha_push"), ("telegram", "telegram"))
            if not force and all(self.sent(t["id"], f"{kind}_{k}", bucket, f"dry-{c}" if dry else c) for k, c in channels):
                continue
            ids = t["nag"]["escalate_to"] if escalated else ([t["assignee"]] if t["assignee"] else [p.id for p in self.cfg.people])
            people = [p for p in map(self.cfg.person, ids) if p]
            words = digest.nag(t, step, late, escalated, [p.name for p in people], self.voice(now))
            send_to = to or [p.send_to for p in people] or self._target(t, self.cfg.digest_send_to)
            level = "critical" if escalated else "time-sensitive"
            occ = occurrence_key(t)
            actions = [{"action": f"TASK_DONE_{t['id']}_{occ}", "title": words["done"]}]
            out.append(await self.deliver(t["id"], f"{kind}_push", bucket, "ha_push",
                                          lambda: self.ha.notify(send_to, words["title"], words["line"], level, f"task-{t['id']}", actions),
                                          f"{words['title']}: {words['line']} → {send_to}", force, dry))
            # the group gets the line alone, no task name
            out.append(await self.deliver(t["id"], f"{kind}_telegram", bucket, "telegram",
                                          lambda: self._telegram(kind, bucket, "", words["telegram"],
                                                                 self._buttons(t, snooze=False, label=words["done"]), [t["id"]]),
                                          words["telegram"], force, dry))
        return out

    def _lines_needed(self, t: dict, now: datetime) -> list[tuple[str, int, str, dict]]:
        """The lines a one-off task will need today: (kind, step, situation, fill)."""
        today, out = now.date().isoformat(), []
        n = t["days_overdue"] if t["overdue"] else 0
        late = {"late": voices.late_text(n)}
        if t["alarm"] and t["state"] in ("due", "overdue"):
            when = f"It is {late['late']} overdue; this alarm repeats daily until it's done." if n else "It is due today."
            out.append(("alarm", voices.alarm_step(n), when, late))
            out.append(("spoken", 1 if n else 0, when, late))
        if t["priority"] == 1 and not t["alarm"] and t["overdue"]:
            out.append(("overdue", voices.overdue_step(n), f"It is {late['late']} overdue (high priority).", late))
        if t["nag"] and t["eff_due"] == today and t["state"] == "due":
            due = t["schedule"]["due_time"] or self.cfg.default_due_time
            ids = [t["assignee"]] if t["assignee"] else [p.id for p in self.cfg.people]
            who = {"who": t["assignee_name"] or "everyone"}
            for step in range(len(voices.VOICES[voices.voice_of_day(today)]["nag"])):
                el = digest.elapsed_text(step * (t["nag"]["every"] or 0))
                out.append(("nag", step, f"It was due at {due}; it's now {el} later and still not done."
                            if step else f"It's due now ({due}).", {**who, "elapsed": el}))
            if t["nag"]["escalate_at"]:
                names = [p.name for p in map(self.cfg.person, t["nag"]["escalate_to"]) if p]
                ev = {"everyone": digest._names(names), "have": "has" if len(names) == 1 else "have"}
                for step in range(2):
                    el = "hours" if not step else "even longer"
                    out.append(("escalate", step, f"It's been ignored for {el} since {due}, so {ev['everyone']} "
                                f"{ev['have']} been pulled in: this is a critical alert.", {**who, **ev, "elapsed": el}))
        return out

    async def prepare_lines(self, now: datetime, force=False) -> list[dict]:
        """Once a day from 05:00: HA's persona script writes today's lines for
        one-off tasks, in the day's voice, and they're stored for the sends to
        use. Recurring tasks keep the fixed lines. Nothing is sent here, and a
        failure only means the fixed lines are used."""
        today = now.date().isoformat()
        if not (self.cfg.voice_text_script and self.ha and self.ha.enabled):
            return []
        if not force and (now.hour < 5 or self.sent(0, "voice_prep", today, "ha")):
            return []
        v, out, failed = self.voice(now), [], ""
        with self.store.tx() as db:
            db.execute("DELETE FROM voice_lines WHERE day < ?", ((now.date() - timedelta(days=7)).isoformat(),))
        for t in self.tasks.open_tasks():
            if t["repeats"]:
                continue
            for kind, step, situation, fill in self._lines_needed(t, now):
                if failed or v.stored(t["id"], kind, step):
                    continue
                fixed = v.fixed(kind, step, title=t["title"], **fill)
                try:
                    text, fell_back = await self.ha.era_text(self.cfg.voice_text_script,
                                                             voices.prompt(v, t, kind, step, situation, fill), fixed, v.era)
                except Exception as e:
                    failed = f"{type(e).__name__}: {e}"
                    log.warning("voice lines: HA failed (%s); the fixed lines stand in today", failed)
                    continue
                text = " ".join(text.replace('"', "").split())
                naming = t["title"].lower() in text.lower()
                if fell_back or not text or len(text) > 300 or (kind in ("nag", "escalate") and naming):
                    continue
                with self.store.tx() as db:
                    db.execute("INSERT OR REPLACE INTO voice_lines(day, task_id, kind, step, text) VALUES (?,?,?,?,?)",
                               (today, t["id"], kind, step, text))
                out.append({"task_id": t["id"], "kind": kind, "step": step, "text": text})
        # recorded as done even when HA failed: one try a day, so a down HA can't stall the tick
        self.record(0, "voice_prep", today, "ha", True, (f"failed: {failed}; " if failed else "") + f"{len(out)} lines, {v.name}")
        log.info("voice lines for %s: %d written (%s)%s", today, len(out), v.name, f", stopped: {failed}" if failed else "")
        return out

    def roll_over(self, now: datetime) -> list[dict]:
        """A nagging task's day that ended without a Done is skipped, so the next day
        starts again at its due time instead of nagging all night; History shows it
        as missed."""
        out = []
        for t in self.tasks.open_tasks():
            if t["nag"] and t["repeats"] and t["overdue"]:
                done = self.tasks.skip(t["id"], done_by="Tasks", source="missed", occurrence=t["occurrence"],
                                       note="Not done that day")
                log.info("rolled over task=%s: %s missed, next %s", t["id"], t["nominal_due"], done["eff_due"])
                out.append({"task_id": t["id"], "missed": t["nominal_due"], "next": done["eff_due"]})
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
            v = self.voice(now)
            title, msg = digest.p1_overdue_push(t, v)
            send_to = to or self._target(t, self.cfg.digest_send_to)
            occ = occurrence_key(t)
            actions = [{"action": f"TASK_DONE_{t['id']}_{occ}", "title": v.done},
                       {"action": f"TASK_SNOOZE_{t['id']}_{occ}", "title": v.snooze}]
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
        v = self.voice(now)
        head, body = digest.render(secs, now.date(), kind, voice=v)
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
            ph, pb = digest.render(secs, now.date(), kind, p.id, voice=v)
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
        said = digest.dog_alarm(self.tasks.open_tasks(), first_today=True, voice=self.voice(now))
        if not said["text"]:
            return []
        return [await self.deliver(0, "spoken_fallback", today, "spoken",
                                   lambda: self.ha.announce(said["text"], said["verbatim"]), said["text"], force, dry)]

    async def tick(self, now: datetime | None = None):
        now = now or self.tasks.now()
        self.last_tick = now.isoformat(timespec="seconds")
        await self.read_quiet(now)
        for name, job in (("roll_over", lambda: asyncio.to_thread(self.roll_over, now)),
                          ("prepare_lines", lambda: self.prepare_lines(now)),
                          ("p0_push", lambda: self.p0_push(now)), ("nag_push", lambda: self.nag_push(now)),
                          ("p1_overdue", lambda: self.p1_overdue(now)),
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
        if job == "nag_push":
            return await self.nag_push(now, force, dry, only_task, to)
        if job in ("digest_morning", "digest_evening"):
            return await self.digest_job(now, job.split("_")[1], force, dry, to)
        if job == "spoken_fallback":
            return await self.spoken_fallback(now, force, dry)
        if job == "prepare_lines":
            return await self.prepare_lines(now, force)
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
        if event == "undone" and task.get("area") != "homelab":
            asyncio.run_coroutine_threadsafe(self._after_undo(task), self.loop)

    async def _after_undo(self, task: dict):
        """A done taken back: the switch goes on again if today's alarm had already
        turned it on (the ledger won't let p0_push do it twice). Pushes it cleared
        are not sent again."""
        entity = self._switch_entity(task)
        if not (entity and task["alarm"] and task["state"] in ("due", "overdue")):
            return
        today = self.tasks.today().isoformat()
        if not any(self.sent(task["id"], "switch_on", today, key) for key in ("ha_switch", "dry-ha_switch")):
            return
        await self.deliver(task["id"], "switch_on_undo", self.tasks.now().isoformat(timespec="minutes"), "ha_switch",
                           lambda: self.ha.set_switch(entity, True), f"{entity} on")

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
        if rows := self._offering(task["id"]):
            await self.deliver(task["id"], f"telegram_tidy_{event}", bucket, "telegram",
                               lambda: self._tidy_telegram(event, task, rows),
                               f"{digest.closed_line(event, task)} → messages {', '.join(str(r['message_id']) for r in rows)}",
                               dry=dry)
