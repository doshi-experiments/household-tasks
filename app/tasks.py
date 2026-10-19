"""Task operations: create, edit, complete, skip, snooze, and read views.

Everything date-related comes from schedule.py; this module owns the rows.
Listeners get (event, task) after each committed change so the web layer can
clear phone notifications, flip HA switches and so on.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable

from . import schedule as sch
from .config import Config
from .store import Store

# High/Medium/Low. "critical" (and the old P0) is High with the alarm on.
PRIORITY_NAMES = {"high": 1, "medium": 2, "normal": 2, "low": 3, "p1": 1, "p2": 2, "p3": 3}
ALARM_WORDS = {"critical", "urgent", "p0", "alarm"}
PRIORITY_LABELS = {1: "High", 2: "Medium", 3: "Low"}
SCHEDULE_FIELDS = ("schedule_kind", "rrule", "anchor_date", "interval_n", "interval_unit", "flex", "due_time")
EDITABLE = ("title", "notes", "category", "priority", "assignee", "source", "added_by")
# Homelab tasks move through these stages on their board; done is the task's status.
STAGES = ("idea", "next", "doing")


class TaskError(Exception):
    def __init__(self, status: int, message: str, task: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.task = status, message, task


def parse_priority(value, default: int = 2) -> tuple[int, bool]:
    """-> (priority 1-3, alarm?). 'critical' / 'p0' mean High with the alarm on."""
    if value is None or value == "":
        return default, False
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 0:
            return 1, True
        if 1 <= value <= 3:
            return value, False
        raise TaskError(400, "Priority is high, medium or low.")
    word = str(value).strip().lower()
    if word in ALARM_WORDS:
        return 1, True
    p = PRIORITY_NAMES.get(word)
    if p is None:
        raise TaskError(400, f"Unknown priority {value!r}; use high, medium or low.")
    return p, False


def _d(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise TaskError(400, f"{v!r} isn't a date (use YYYY-MM-DD).") from None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def occurrence_key(task: dict) -> str:
    """Compact occurrence id for buttons: YYYYMMDD of nominal_due, or 0."""
    return (task.get("nominal_due") or "").replace("-", "") or "0"


def weekend_window(today: date) -> tuple[date, date]:
    """The Fri-Sun weekend containing today, or the coming one."""
    if today.weekday() >= 4:
        start = today - timedelta(days=today.weekday() - 4)
    else:
        start = today + timedelta(days=4 - today.weekday())
    return start, start + timedelta(days=2)


class Tasks:
    def __init__(self, store: Store, cfg: Config, clock: Callable[[], datetime] | None = None):
        self.store, self.cfg = store, cfg
        self.clock = clock or (lambda: datetime.now(cfg.tz))
        self.listeners: list[Callable[[str, dict], None]] = []

    # ------------------------------------------------------------ helpers
    def now(self) -> datetime:
        return self.clock()

    def today(self) -> date:
        return self.now().date()

    def _emit(self, event: str, task: dict):
        for fn in self.listeners:
            try:
                fn(event, task)
            except Exception:   # a listener must never undo a committed change
                pass

    def _row(self, task_id: int) -> dict:
        row = self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row:
            raise TaskError(404, f"No task {task_id}.")
        return row

    def serialize(self, row: dict, today: date | None = None) -> dict:
        today = today or self.today()
        due, snoozed = _d(row["due"]), _d(row["snoozed_until"])
        eff = sch.effective_due(due, snoozed)
        st = "done" if row["status"] != "open" else sch.state(eff, row["flex"], today)
        person = self.cfg.person(row["assignee"])
        return {
            **{k: row[k] for k in ("id", "title", "notes", "category", "priority", "assignee", "nominal_due", "due",
                                   "snoozed_until", "last_done_at", "status", "source", "added_by", "created_at",
                                   "updated_at", "cursor", "position", "area", "stage")},
            "alarm": bool(row["alarm"]),
            "priority_label": PRIORITY_LABELS.get(row["priority"], "Medium"),
            "assignee_name": person.name if person else "",
            "schedule": {"kind": row["schedule_kind"], "rrule": row["rrule"], "anchor_date": row["anchor_date"],
                         "interval_n": row["interval_n"], "interval_unit": row["interval_unit"],
                         "flex": row["flex"], "due_time": row["due_time"]},
            "schedule_text": sch.describe_rule(row["schedule_kind"], row["rrule"], row["interval_n"],
                                               row["interval_unit"], row["flex"]),
            "repeats": row["schedule_kind"] != "none",
            "eff_due": _iso(eff),
            "due_text": sch.fmt_date(eff, today) if eff else "no date",
            "state": st,
            "overdue": st == "overdue",
            "days_overdue": sch.days_overdue(eff, row["flex"], today) if st == "overdue" else 0,
            "occurrence": occurrence_key(row),
        }

    # ------------------------------------------------------------ schedule input
    def _schedule_fields(self, body: dict, current: dict | None, alarm: bool) -> dict:
        """Validated schedule columns from a create/patch body (current = existing row)."""
        sched = dict(body.get("schedule") or {})
        if body.get("repeat") and not sched:   # bot convenience: a phrase
            sched = {"phrase": body["repeat"]}
        if sched.get("phrase"):
            try:
                parsed = sch.parse_phrase(sched.pop("phrase"))
            except sch.ScheduleError as e:
                raise TaskError(400, str(e)) from None
            sched = {**parsed, **{k: v for k, v in sched.items() if v not in (None, "")}}
        cur = current or {}
        f = {k: cur.get(k) for k in SCHEDULE_FIELDS}
        if not current:
            f.update(schedule_kind="none", flex="exact")
        if "kind" in sched:
            f["schedule_kind"] = sched["kind"] or "none"
        for k in ("rrule", "interval_n", "interval_unit", "flex", "due_time", "anchor_date"):
            if k in sched:
                f[k] = sched[k]
        kind = f["schedule_kind"]
        if kind not in ("none", "rrule", "interval"):
            raise TaskError(400, "Schedule kind is none, rrule or interval.")
        if f["flex"] not in ("exact", "weekend"):
            raise TaskError(400, "Flex is exact or weekend.")
        if f["due_time"] in ("", None):
            f["due_time"] = None
        elif not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(f["due_time"])):
            raise TaskError(400, "Due time is HH:MM.")
        if not current and not f["due_time"]:
            # a new task without a time is due at the default time (17:30), not "whenever"
            f["due_time"] = self.cfg.p0_default_time if alarm else self.cfg.default_due_time
        if alarm and not f["due_time"]:
            f["due_time"] = self.cfg.p0_default_time
        today = self.today()
        due_given = "due" in body
        anchor = _d(body.get("due")) if due_given else _d(f["anchor_date"])
        if kind == "none":
            f.update(rrule=None, interval_n=None, interval_unit=None)
        else:
            anchor = anchor or today
            if kind == "rrule":
                try:
                    f["rrule"] = sch.normalize_rrule(f["rrule"] or "", anchor)
                except sch.ScheduleError as e:
                    raise TaskError(400, str(e)) from None
                f.update(interval_n=None, interval_unit=None)
            else:
                try:
                    f["interval_n"] = int(f["interval_n"] or 0)
                except (TypeError, ValueError):
                    raise TaskError(400, "The interval must be a whole number.") from None
                if f["interval_n"] < 1 or f["interval_unit"] not in sch.UNITS:
                    raise TaskError(400, "An interval needs a number of days, weeks, months or years.")
                f["rrule"] = None
        f["anchor_date"] = _iso(anchor)
        return f

    def _derive(self, f: dict, cursor: str | None) -> tuple[str | None, str | None]:
        nominal = sch.next_nominal(f["schedule_kind"], anchor=_d(f["anchor_date"]), cursor=_d(cursor),
                                   rrule=f["rrule"], interval_n=f["interval_n"], interval_unit=f["interval_unit"])
        return _iso(nominal), _iso(sch.apply_flex(nominal, f["flex"]))

    def _category(self, name) -> tuple[str, str]:
        """-> (category name, its area: household or homelab)."""
        name = (name or "Inbox").strip()
        row = self.store.one("SELECT name, area FROM categories WHERE lower(name)=lower(?) AND archived=0", (name,))
        if not row:
            raise TaskError(400, f"No category {name!r}.")
        return row["name"], row["area"]

    @staticmethod
    def _stage(value) -> str:
        v = str(value or "").strip().lower()
        if v not in STAGES:
            raise TaskError(400, "Stage is idea, next or doing.")
        return v

    def _assignee(self, value) -> str | None:
        if value in (None, "", "none", "everyone"):
            return None
        v = str(value).strip().lower()
        p = next((p for p in self.cfg.people if v in (p.id, p.name.lower())), None)
        if not p:
            raise TaskError(400, f"Unknown person {value!r}.")
        return p.id

    # ------------------------------------------------------------ writes
    def create(self, body: dict) -> dict:
        title = str(body.get("title") or "").strip()
        if not title:
            raise TaskError(400, "A task needs a title.")
        priority, alarm = parse_priority(body.get("priority"))
        alarm = bool(body.get("alarm", alarm))
        category, area = self._category(body.get("category"))
        stage = None
        if area == "homelab":
            # homelab work never reminds anyone: no alarm, and no default due time
            alarm, stage = False, self._stage(body.get("stage") or "idea")
        f = self._schedule_fields(body, None, alarm)
        if area == "homelab" and not (body.get("schedule") or {}).get("due_time"):
            f["due_time"] = None
        nominal, due = self._derive(f, None)
        now = self.now().isoformat(timespec="seconds")
        with self.store.tx() as db:
            # new tasks go to the bottom of their column on the board
            top = db.execute("SELECT coalesce(max(position), 0) FROM tasks").fetchone()[0]
            cur = db.execute(
                "INSERT INTO tasks(title, notes, category, area, stage, priority, alarm, position, assignee, schedule_kind,"
                " rrule, anchor_date, interval_n, interval_unit, flex, due_time, nominal_due, due, source, added_by,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (title[:300], str(body.get("notes") or ""), category, area, stage, priority,
                 int(alarm), top + 1024.0,
                 self._assignee(body.get("assignee")), f["schedule_kind"], f["rrule"], f["anchor_date"],
                 f["interval_n"], f["interval_unit"], f["flex"], f["due_time"], nominal, due,
                 str(body.get("source") or ""), str(body.get("added_by") or ""), now, now))
            task_id = cur.lastrowid
        task = self.get(task_id)
        self._emit("created", task)
        return task

    def patch(self, task_id: int, body: dict) -> dict:
        row = self._row(task_id)
        updates = {}
        if "title" in body:
            if not str(body["title"] or "").strip():
                raise TaskError(400, "A task needs a title.")
            updates["title"] = str(body["title"]).strip()[:300]
        if "notes" in body:
            updates["notes"] = str(body["notes"] or "")
        area = row["area"]
        if "category" in body:
            updates["category"], area = self._category(body["category"])
            if area != row["area"]:
                updates["area"] = area
                updates["stage"] = "idea" if area == "homelab" else None
        if "stage" in body:
            if area != "homelab":
                raise TaskError(400, "Only homelab tasks have a stage.")
            updates["stage"] = self._stage(body["stage"])
        if "priority" in body and body["priority"] not in (None, ""):
            updates["priority"], alarm_word = parse_priority(body["priority"])
            if alarm_word:
                updates["alarm"] = 1
        if "alarm" in body:
            updates["alarm"] = int(bool(body["alarm"]))
        if "position" in body:
            try:
                updates["position"] = float(body["position"])
            except (TypeError, ValueError):
                raise TaskError(400, "position must be a number.") from None
        if "assignee" in body:
            updates["assignee"] = self._assignee(body["assignee"])
        for k in ("source", "added_by"):
            if k in body:
                updates[k] = str(body[k] or "")
        if "status" in body:
            if body["status"] not in ("open", "archived"):
                raise TaskError(400, "Status can be set to open or archived.")
            updates["status"] = body["status"]
        if "snoozed_until" in body:
            updates["snoozed_until"] = _iso(_d(body["snoozed_until"]))
        if area == "homelab" and (row["alarm"] or updates.get("alarm")):
            updates["alarm"] = 0
        alarm = bool(updates.get("alarm", row["alarm"]))
        if any(k in body for k in ("schedule", "repeat", "due")) or (updates.get("alarm") and not row["alarm"]):
            f = self._schedule_fields(body, row, alarm)
            cursor = row["cursor"]
            if "due" in body:
                # Moving the next date re-anchors the series there; done/skip history stays.
                cursor = None
                updates["snoozed_until"] = None
            elif (f["schedule_kind"] == "rrule" and self.serialize(row)["state"] != "overdue"
                  and (row["nominal_due"] is None or row["nominal_due"] >= (self.today() - timedelta(days=1)).isoformat())):
                # A rule edit must not invent a missed occurrence; one still pending
                # (overdue, or snoozed past its date) is kept as it is.
                floor = (self.today() - timedelta(days=1)).isoformat()
                cursor = max(cursor or "", floor) if (cursor or f["anchor_date"] < floor) else cursor
            nominal, due = self._derive(f, cursor)
            updates.update(f, cursor=cursor, nominal_due=nominal, due=due)
        if not updates:
            return self.serialize(row)
        updates["updated_at"] = self.now().isoformat(timespec="seconds")
        with self.store.tx() as db:
            db.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                       (*updates.values(), task_id))
        task = self.get(task_id)
        self._emit("archived" if updates.get("status") == "archived" else "updated", task)
        return task

    def archive(self, task_id: int) -> dict:
        return self.patch(task_id, {"status": "archived"})

    def _check_occurrence(self, row: dict, occurrence):
        if row["status"] != "open":
            raise TaskError(409, "already done", self.serialize(row))
        if occurrence not in (None, ""):
            want = str(occurrence).replace("-", "")
            if want != occurrence_key(row):
                raise TaskError(409, "already done", self.serialize(row))

    def _close(self, task_id: int, kind: str, done_by: str, source: str, occurrence, done_at, note: str) -> dict:
        with self.store.lock:
            row = self._row(task_id)
            self._check_occurrence(row, occurrence)
            now = self.now()
            when = datetime.fromisoformat(done_at) if done_at else now
            if when.tzinfo is None:
                when = when.replace(tzinfo=self.cfg.tz)
            today = now.date()
            prev = dict(row)
            updates = {"snoozed_until": None, "updated_at": now.isoformat(timespec="seconds")}
            if kind == "done":
                updates["last_done_at"] = when.isoformat(timespec="seconds")
            if row["schedule_kind"] == "none":
                if kind == "done":
                    updates["status"] = "done"
                else:   # skipping a one-off just clears its date
                    updates.update(anchor_date=None, nominal_due=None, due=None)
            else:
                cursor = sch.cursor_after(row["schedule_kind"], kind, nominal_due=_d(row["nominal_due"]),
                                          done_on=when.date(), today=today)
                nominal, due = self._derive(row, _iso(cursor))
                updates.update(cursor=_iso(cursor), nominal_due=nominal, due=due)
                if nominal is None:
                    updates["status"] = "done"   # a rule with an end has run out
            with self.store.tx() as db:
                db.execute("INSERT INTO completions(task_id, kind, done_at, nominal_due, done_by, source, note)"
                           " VALUES (?,?,?,?,?,?,?)",
                           (task_id, kind, when.isoformat(timespec="seconds"), row["nominal_due"],
                            str(done_by or ""), str(source or ""), str(note or "")))
                db.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                           (*updates.values(), task_id))
        task = self.get(task_id)
        task["previous"] = {"nominal_due": prev["nominal_due"], "occurrence": occurrence_key(prev)}
        task["closed"] = task["status"] != "open"
        self._emit("completed" if kind == "done" else "skipped", task)
        return task

    def complete(self, task_id: int, done_by="", source="", occurrence=None, done_at=None, note="") -> dict:
        return self._close(task_id, "done", done_by, source, occurrence, done_at, note)

    def skip(self, task_id: int, done_by="", source="", occurrence=None, note="") -> dict:
        return self._close(task_id, "skip", done_by, source, occurrence, None, note)

    def snooze(self, task_id: int, until=None, days=None, occurrence=None, done_by="", source="") -> dict:
        with self.store.lock:
            row = self._row(task_id)
            self._check_occurrence(row, occurrence)
            today = self.today()
            if until:
                target = _d(until)
            elif days:
                target = today + timedelta(days=int(days))
            else:
                target = sch.default_snooze(row["flex"], today)
            if target <= today:
                raise TaskError(400, "Snooze to a date after today.")
            with self.store.tx() as db:
                db.execute("UPDATE tasks SET snoozed_until=?, updated_at=? WHERE id=?",
                           (_iso(target), self.now().isoformat(timespec="seconds"), task_id))
        task = self.get(task_id)
        task["snoozed_by"] = done_by
        self._emit("snoozed", task)
        return task

    # ------------------------------------------------------------ reads
    def get(self, task_id: int) -> dict:
        return self.serialize(self._row(task_id))

    def completions(self, task_id: int | None = None, limit: int = 100) -> list[dict]:
        sql = ("SELECT c.*, t.title FROM completions c JOIN tasks t ON t.id=c.task_id"
               + (" WHERE c.task_id=?" if task_id else "") + " ORDER BY c.done_at DESC, c.id DESC LIMIT ?")
        return self.store.all(sql, ((task_id, limit) if task_id else (limit,)))

    def list(self, status="open", category=None, assignee=None, source=None, q=None, window="all",
             kind=None, area=None, done_days=None) -> list[dict]:
        """kind: recurring / oneoff (household tasks) or homelab. done_days adds
        the tasks finished in the last N days (the homelab board's Done column)."""
        sql, args = "SELECT * FROM tasks WHERE 1=1", []
        if kind == "recurring":
            sql += " AND area='household' AND schedule_kind != 'none'"
        elif kind == "oneoff":
            sql += " AND area='household' AND schedule_kind = 'none'"
        elif kind == "homelab":
            sql += " AND area='homelab'"
        if area:
            sql += " AND area=?"
            args.append(area)
        if done_days:
            since = (self.now() - timedelta(days=int(done_days))).isoformat(timespec="seconds")
            sql += " AND (status='open' OR (status='done' AND last_done_at >= ?))"
            args.append(since)
        elif status and status != "any":
            sql += " AND status=?"
            args.append(status)
        if category:
            sql += " AND lower(category)=lower(?)"
            args.append(category)
        if assignee == "unassigned":
            sql += " AND assignee IS NULL"
        elif assignee:
            sql += " AND assignee=?"
            args.append(self._assignee(assignee))
        if source:
            sql += " AND source=?"
            args.append(source)
        if q:
            sql += " AND (title LIKE ? OR notes LIKE ?)"
            args += [f"%{q}%", f"%{q}%"]
        today = self.today()
        rows = [self.serialize(r, today) for r in self.store.all(sql, args)]
        horizon = (today + timedelta(days=7)).isoformat()
        if window == "today":
            rows = [t for t in rows if t["state"] in ("due", "overdue")]
        elif window == "overdue":
            rows = [t for t in rows if t["overdue"]]
        elif window == "week":
            rows = [t for t in rows if t["state"] in ("due", "overdue") or (t["eff_due"] and t["eff_due"] <= horizon)]
        rank = {"overdue": 0, "due": 1, "upcoming": 2, "someday": 3, "done": 4}
        rows.sort(key=lambda t: (rank[t["state"]], t["eff_due"] or "9999", t["priority"], t["title"].lower()))
        return rows

    def open_tasks(self) -> list[dict]:
        """Open household tasks: everything that reminds, summarises or goes on
        HA's calendar starts here, so homelab tasks never notify anyone."""
        return self.list(status="open", area="household")

    def summary(self) -> dict:
        today = self.today()
        tasks = self.open_tasks()
        ws, we = weekend_window(today)
        weekend = [t for t in tasks if t["eff_due"] and ws.isoformat() <= t["eff_due"] <= we.isoformat()
                   and not t["overdue"]]
        return {
            "overdue": sum(t["overdue"] for t in tasks),
            "due_today": sum(t["state"] == "due" for t in tasks),
            "this_weekend": len(weekend),
            "p0_open": sum(t["alarm"] and t["state"] in ("due", "overdue") for t in tasks),   # alarms due (key kept for HA)
            "open": len(tasks),
            "next_up": [{"id": t["id"], "title": t["title"], "eff_due": t["eff_due"], "due_text": t["due_text"],
                         "priority": t["priority_label"], "state": t["state"]}
                        for t in tasks if t["eff_due"]][:5],
            "generated_at": self.now().isoformat(timespec="seconds"),
        }

    def projected(self, start: date, end: date) -> list[dict]:
        """Every open task occurrence in [start, end]: [{date, task, overdue}].

        Overdue tasks are placed on today so short look-ahead windows mention
        them. Repeating rrule tasks list each occurrence; others only the next.
        """
        today = self.today()
        out = []
        for t in self.open_tasks():
            eff = _d(t["eff_due"])
            if eff is None:
                continue
            first = today if t["overdue"] else eff
            if start <= first <= end:
                out.append({"date": first, "task": t, "overdue": t["overdue"]})
            s = t["schedule"]
            if t["schedule"]["kind"] == "rrule":
                for occ in sch.occurrences("rrule", anchor=_d(s["anchor_date"]), cursor=_d(t["nominal_due"]),
                                           rrule=s["rrule"], start=start, end=end):
                    d = sch.apply_flex(occ, s["flex"])
                    if d > first and start <= d <= end:
                        out.append({"date": d, "task": t, "overdue": False})
        out.sort(key=lambda x: (x["date"], x["task"]["priority"], x["task"]["title"].lower()))
        return out
