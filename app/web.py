"""Household Tasks: API, hooks, calendar feed and the React pages.

Run one worker: ``uvicorn app.web:create_app --factory --host 0.0.0.0 --port 8040``.
Reachable on the LAN address and the tailnet only. Writes need either the
bearer token (ingest-bot, Home Assistant, scripts) or a same-origin browser
request carrying X-Tasks-Request (the pages), as in the finance review UI.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import config, digest, ics
from . import schedule as sch
from .bot import Bot
from .ha import HomeAssistant
from .scheduler import Scheduler
from .shopping import Lists, Shopping
from .store import Store
from .tasks import TaskError, Tasks

ROOT = Path(__file__).resolve().parents[1]
OPEN_PATHS = {"/api/health", "/calendar.ics", "/calendar-reminders.ics"}
log = logging.getLogger("tasks")


def create_app(cfg=None, store=None, clock=None, start_scheduler=True):
    cfg = cfg or config.load()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    store = store or Store(cfg.db_path)
    tasks = Tasks(store, cfg, clock)
    shopping = Shopping(store, tasks.now)
    categories = Lists(store, "categories", "tasks", "category", "status='open'")
    ha = HomeAssistant(cfg.ha_url, cfg.ha_token)
    bot = Bot(cfg.bot_url, cfg.bot_token)
    sched = Scheduler(cfg, store, tasks, shopping, ha, bot)

    @asynccontextmanager
    async def lifespan(_app):
        sched.loop = asyncio.get_running_loop()
        runner = asyncio.create_task(sched.run()) if start_scheduler else None
        log.info("tasks up: notify_enabled=%s ha=%s bot=%s", cfg.notify_enabled, ha.enabled, bot.enabled)
        yield
        if runner:
            runner.cancel()
        await ha.close()
        await bot.close()
        store.close()

    app = FastAPI(title="Household tasks", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.tasks, app.state.scheduler, app.state.shopping = tasks, sched, shopping

    def bearer_ok(request: Request) -> bool:
        got = request.headers.get("authorization", "")
        return hmac.compare_digest(got.encode(), f"Bearer {cfg.api_token}".encode())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/hooks/") and not bearer_ok(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        if path.startswith("/api/") and path not in OPEN_PATHS and not bearer_ok(request):
            origin = request.headers.get("origin")
            if (request.headers.get("x-tasks-request") != "1"
                    or request.headers.get("sec-fetch-site") == "cross-site"
                    or (origin and (urlsplit(origin).scheme not in ("http", "https")
                                    or urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()))):
                return JSONResponse({"detail": "Open Tasks in its own browser window to make this request."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if path.startswith(("/api/", "/hooks/")) else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(TaskError)
    async def task_error(_request, exc: TaskError):
        body = {"detail": exc.message}
        if exc.task:
            body["task"] = exc.task
        return JSONResponse(body, status_code=exc.status)

    # ------------------------------------------------------------ meta
    @app.get("/api/health")
    def health():
        return {"ok": True, "open": len(tasks.open_tasks()), "scheduler_tick": sched.last_tick,
                "notify_enabled": cfg.notify_enabled, "quiet_now": sched.quiet(tasks.now()), "ha_configured": ha.enabled, "bot_configured": bot.enabled,
                "last_ha_error": ha.last_error, "last_bot_error": bot.last_error}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"categories": categories.all(), "shopping_lists": shopping.lists.all(),
                "people": [{"id": p.id, "name": p.name} for p in cfg.people],
                "tz": cfg.tz_name, "today": tasks.today().isoformat(), "notify_enabled": cfg.notify_enabled,
                "settings": {"digest_morning": cfg.digest_morning, "digest_evening": cfg.digest_evening,
                             "p0_default_time": cfg.p0_default_time, "p1_overdue_push": cfg.p1_overdue_push,
                             "p1_overdue_push_time": cfg.p1_overdue_push_time, "spoken_fallback": cfg.spoken_fallback}}

    # ------------------------------------------------------------ tasks
    @app.get("/api/tasks")
    def list_tasks(status: str = "open", category: str | None = None, assignee: str | None = None,
                   source: str | None = None, q: str | None = None, window: str = "all", kind: str | None = None,
                   done_days: int | None = None):
        return {"tasks": tasks.list(status, category, assignee, source, q, window, kind, done_days=done_days)}

    @app.post("/api/tasks")
    def create_task(body: dict = Body(...)):
        return {"task": tasks.create(body)}

    @app.post("/api/tasks/parse-schedule")
    def parse_schedule(body: dict = Body(...)):
        try:
            if body.get("text"):
                s = sch.parse_phrase(body["text"])
            else:
                s = {k: body.get(k) for k in ("kind", "rrule", "interval_n", "interval_unit", "flex", "due_time")}
            anchor = date.fromisoformat(body["anchor_date"]) if body.get("anchor_date") else tasks.today()
            kind = s.get("kind") or "none"
            if kind == "rrule":
                s["rrule"] = sch.normalize_rrule(s["rrule"] or "", anchor)
            first = sch.next_nominal(kind, anchor=anchor, cursor=None, rrule=s.get("rrule"),
                                     interval_n=int(s.get("interval_n") or 0) or None, interval_unit=s.get("interval_unit"))
            flex = s.get("flex") or "exact"
            nexts, cur = [], None
            if kind == "rrule":
                nexts = [sch.apply_flex(d, flex) for d in sch.occurrences(kind, anchor=anchor, cursor=None, rrule=s["rrule"],
                                                                          start=anchor, end=anchor + timedelta(days=800), limit=4)]
            elif kind == "interval" and first:
                d = first
                for _ in range(4):
                    nexts.append(sch.apply_flex(d, flex))
                    d = sch.add_interval(d, int(s["interval_n"]), s["interval_unit"])
            elif first:
                nexts = [sch.apply_flex(first, flex)]
        except (sch.ScheduleError, ValueError, TypeError, KeyError) as e:
            raise TaskError(400, str(e)) from None
        today = tasks.today()
        return {"schedule": {**s, "kind": kind}, "first_due": first.isoformat() if first else None,
                "next": [d.isoformat() for d in nexts], "next_text": [sch.fmt_date(d, today) for d in nexts],
                "text": sch.describe_rule(kind, s.get("rrule"), s.get("interval_n"), s.get("interval_unit"), flex)}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: int):
        return {"task": tasks.get(task_id), "completions": tasks.completions(task_id, 20)}

    @app.patch("/api/tasks/{task_id}")
    def patch_task(task_id: int, body: dict = Body(...)):
        return {"task": tasks.patch(task_id, body)}

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int):
        return {"task": tasks.archive(task_id)}

    @app.post("/api/tasks/{task_id}/complete")
    def complete_task(task_id: int, body: dict = Body(default={})):
        return {"task": tasks.complete(task_id, body.get("done_by", ""), body.get("source", "api"),
                                       body.get("occurrence"), body.get("done_at"), body.get("note", ""))}

    @app.post("/api/tasks/{task_id}/skip")
    def skip_task(task_id: int, body: dict = Body(default={})):
        return {"task": tasks.skip(task_id, body.get("done_by", ""), body.get("source", "api"),
                                   body.get("occurrence"), body.get("note", ""))}

    @app.post("/api/tasks/{task_id}/undo")
    def undo_task(task_id: int, body: dict = Body(...)):
        try:
            completion_id = int(body.get("completion_id"))
        except (TypeError, ValueError):
            raise TaskError(400, "completion_id is the id a done or skip returned.") from None
        return {"task": tasks.undo(task_id, completion_id)}

    @app.post("/api/tasks/{task_id}/snooze")
    def snooze_task(task_id: int, body: dict = Body(default={})):
        return {"task": tasks.snooze(task_id, body.get("until"), body.get("days"), body.get("occurrence"),
                                     body.get("done_by", ""), body.get("source", "api"))}

    @app.get("/api/history")
    def history(limit: int = 100, task_id: int | None = None):
        return {"completions": tasks.completions(task_id, min(limit, 500))}

    @app.get("/api/summary")
    def summary():
        return tasks.summary()

    @app.get("/api/upcoming")
    async def upcoming(days: int = 7, calendar: int = 1, start: str | None = None):
        today = tasks.today()
        first = date.fromisoformat(start) if start else today
        last = first + timedelta(days=max(1, min(days, 120)) - 1)
        proj = await asyncio.to_thread(tasks.projected, first, last)
        events, error = [], ""
        if calendar and ha.enabled and cfg.upcoming_calendars:
            try:
                events = await ha.get_events(list(cfg.upcoming_calendars),
                                             datetime.combine(first, time(), cfg.tz).isoformat(),
                                             datetime.combine(last + timedelta(days=1), time(), cfg.tz).isoformat())
            except Exception as e:
                error = str(e)
        out = []
        for i in range((last - first).days + 1):
            d = first + timedelta(days=i)
            ds = d.isoformat()
            day_events = [e for e in events if e["start"][:10] <= ds and (e["end"][:10] > ds or e["start"][:10] == ds)]
            day_events.sort(key=lambda e: (not e["all_day"], e["start"]))
            out.append({"date": ds, "label": digest.day_label(d, today), "is_weekend": d.weekday() >= 4,
                        "tasks": [p["task"] | {"projected_overdue": p["overdue"]} for p in proj if p["date"] == d],
                        "events": day_events})
        return {"days": out, "calendar_error": error, "text": digest.upcoming_text(out)}

    # ------------------------------------------------------------ categories and shopping
    @app.get("/api/categories")
    def list_categories():
        return {"categories": categories.all()}

    @app.post("/api/categories")
    def create_category(body: dict = Body(...)):
        return {"category": categories.create(body.get("name", ""), body.get("hint", ""), area=body.get("area"))}

    @app.patch("/api/categories/{name}")
    def update_category(name: str, body: dict = Body(...)):
        return {"category": categories.update(name, body.get("name"), body.get("hint"))}

    @app.delete("/api/categories/{name}")
    def archive_category(name: str):
        return {"category": categories.archive(name)}

    @app.get("/api/shopping/lists")
    def list_shopping_lists():
        return {"lists": shopping.lists.all()}

    @app.post("/api/shopping/lists")
    def create_shopping_list(body: dict = Body(...)):
        return {"list": shopping.lists.create(body.get("name", ""), body.get("hint", ""))}

    @app.patch("/api/shopping/lists/{name}")
    def update_shopping_list(name: str, body: dict = Body(...)):
        return {"list": shopping.lists.update(name, body.get("name"), body.get("hint"))}

    @app.delete("/api/shopping/lists/{name}")
    def archive_shopping_list(name: str):
        return {"list": shopping.lists.archive(name)}

    @app.get("/api/shopping")
    def list_items(list: str | None = None, bought: int = 0):
        return {"items": shopping.items(list, bool(bought))}

    @app.post("/api/shopping")
    def add_items(body: dict = Body(...)):
        items = body.get("items") or ([body] if body.get("title") else [])
        return {"items": shopping.add(items)}

    @app.post("/api/shopping/reorder")
    def reorder_items(body: dict = Body(...)):
        return {"items": shopping.reorder(body.get("list", ""), body.get("ids") or [])}

    @app.patch("/api/shopping/{item_id}")
    def patch_item(item_id: int, body: dict = Body(...)):
        return {"item": shopping.patch(item_id, body)}

    @app.post("/api/shopping/{item_id}/buy")
    def buy_item(item_id: int, body: dict = Body(default={})):
        return {"item": shopping.buy(item_id, body.get("by", ""))}

    @app.post("/api/shopping/{item_id}/unbuy")
    def unbuy_item(item_id: int):
        return {"item": shopping.unbuy(item_id)}

    @app.delete("/api/shopping/{item_id}")
    def delete_item(item_id: int):
        return {"item": shopping.delete(item_id)}

    # ------------------------------------------------------------ digests and admin
    @app.get("/api/digest/preview")
    def digest_preview(kind: str = "morning"):
        today = tasks.today()
        open_tasks = tasks.open_tasks()
        if kind == "dog_alarm":
            first = not sched.sent(0, "dog_alarm_digest", today.isoformat(), "spoken")
            return digest.dog_alarm(open_tasks, first)
        if kind == "p0":
            return {"pushes": [dict(zip(("title", "message"), digest.p0_push(t, today))) for t in open_tasks
                               if t["alarm"] and t["state"] in ("due", "overdue")]}
        if kind not in ("morning", "evening"):
            raise TaskError(400, "kind is morning, evening, dog_alarm or p0.")
        secs = digest.sections(open_tasks, today, kind)
        head, body = digest.render(secs, today, kind)
        return {"title": head, "text": body,
                "per_person": {p.id: digest.render(secs, today, kind, p.id)[1] for p in cfg.people},
                "sections": [{"title": t, "task_ids": [x["id"] for x in rows]} for t, rows in secs]}

    @app.post("/api/admin/run")
    async def admin_run(body: dict = Body(...)):
        try:
            results = await sched.run_job(body.get("job", ""), bool(body.get("force")),
                                          None if body.get("dry") is None else bool(body["dry"]),
                                          body.get("only_task"), body.get("to"))
        except ValueError as e:
            raise TaskError(400, str(e)) from None
        return {"results": results}

    @app.post("/api/admin/test-notify")
    async def test_notify(body: dict = Body(...)):
        send_to = body.get("send_to") or (cfg.people[0].send_to if cfg.people else "")
        level = body.get("level", "active")
        stamp = tasks.now().strftime("%H%M%S")
        actions = [{"action": f"TASK_DONE_0_{stamp}", "title": "Done"}, {"action": f"TASK_SNOOZE_0_{stamp}", "title": "Snooze a day"}]
        await ha.notify(send_to, "Tasks test", "Test notification from the Tasks service. Tap Done to test the button path.",
                        level, "task-0", actions)
        return {"ok": True, "send_to": send_to, "actions": actions}

    # ------------------------------------------------------------ hooks
    @app.post("/hooks/ha-action")
    async def ha_action(body: dict = Body(...)):
        m = re.fullmatch(r"TASK_(DONE|SNOOZE)_(\d+)_(\d{8}|0|\d{6})", str(body.get("action", "")))
        if not m:
            raise TaskError(400, "Unknown action.")
        op, task_id, occ = m.group(1), int(m.group(2)), m.group(3)
        who = cfg.person(cfg.device_people.get(str(body.get("device") or "")))
        by = who.name if who else "phone"
        if task_id == 0:
            log.info("test notification action %s acknowledged by %s", op, by)
            return {"ok": True, "test": True, "by": by}
        try:
            if op == "DONE":
                task = await asyncio.to_thread(tasks.complete, task_id, by, "ha_push", occ)
            else:
                task = await asyncio.to_thread(tasks.snooze, task_id, None, None, occ, by, "ha_push")
        except TaskError as e:
            if e.status == 409:
                log.info("ha-action %s task=%s occurrence=%s: already done", op, task_id, occ)
                return {"ok": True, "already": True}
            raise
        return {"ok": True, "task": task}

    @app.post("/hooks/dog-alarm")
    def dog_alarm(body: dict = Body(default={})):
        if sched.quiet(tasks.now()):   # night mode on (HA's reminder also stops then): add nothing
            return {"text": "", "verbatim": False, "first_today": False, "p0": [], "due_today": [], "quiet": True}
        today = tasks.today().isoformat()
        # The announcement is playing: alarms at the default time go out now (once a day, by the ledger).
        if not sched.sent(0, "dog_alarm_heard", today, "hook"):
            sched.record(0, "dog_alarm_heard", today, "hook", True, "feeding announcement played")
        if sched.loop:
            asyncio.run_coroutine_threadsafe(sched.p0_push(tasks.now()), sched.loop)
        first = not sched.sent(0, "dog_alarm_digest", today, "spoken")
        said = digest.dog_alarm(tasks.open_tasks(), first)
        if first and said["due_today"]:
            sched.record(0, "dog_alarm_digest", today, "spoken", True, said["text"][:400])
        if said["p0"]:
            sched.record(0, "dog_alarm_nag", today, "spoken", True, said["text"][:400])
        return said

    # ------------------------------------------------------------ calendar and pages
    @app.get("/calendar.ics")
    def calendar():
        today = tasks.today()
        body = ics.render(tasks.projected(today, today + timedelta(days=cfg.calendar_days_ahead)), tasks.now(), cfg.tz)
        return Response(body, media_type="text/calendar; charset=utf-8")

    @app.get("/calendar-reminders.ics")
    def calendar_reminders():
        """Only upcoming tasks with a time of their own (not the 17:30 default), so
        HA's calendar reminders speak them 30 and 10 minutes before; overdue and
        untimed tasks stay off it."""
        today = tasks.today()
        proj = [p for p in tasks.projected(today, today + timedelta(days=cfg.calendar_days_ahead))
                if p["task"]["own_time"] and not p["overdue"]]
        body = ics.render(proj, tasks.now(), cfg.tz, name="Household task reminders")
        return Response(body, media_type="text/calendar; charset=utf-8")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith(("api/", "hooks/")):
            raise HTTPException(404, "Unknown endpoint.")
        directory = (ROOT / "frontend" / "dist").resolve()
        target = (directory / path).resolve()
        if not target.is_relative_to(directory):
            raise HTTPException(404, "File not found.")
        if path and target.is_file():
            return FileResponse(target)
        index = directory / "index.html"
        if not index.is_file():
            raise HTTPException(503, "Build the Tasks frontend before starting the server.")
        return FileResponse(index)

    return app
