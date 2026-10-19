"""Task, shopping, digest and API behaviour against a throwaway database.

Run in the image: python -m unittest discover tests
"""
import asyncio
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app import digest, ics
from app.config import Config, Person
from app.store import Store
from app.tasks import TaskError, Tasks
from app.shopping import Shopping

TZ = ZoneInfo("UTC")
TOKEN = "t" * 32


def make_cfg(**kw):
    base = dict(tz_name="UTC", db_path=":memory:", api_token=TOKEN, ha_url="", ha_token="",
                ha_tasks_user_id="", bot_url="", bot_token="",
                people=(Person("alex", "Alex", "notify_alex"), Person("sam", "Sam", "notify_sam")),
                device_people={"dev-a": "alex"}, switch_tasks={"input_boolean.example_done_switch": "seed:dog_meds"})
    base.update(kw)
    return Config(**base)


class Clock:
    def __init__(self, when: datetime):
        self.when = when

    def __call__(self):
        return self.when

    def set(self, d: date, hh=10, mm=0):
        self.when = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.tmp.name) / "t.db"))
        self.cfg = make_cfg()
        self.clock = Clock(datetime(2026, 10, 19, 10, 0, tzinfo=TZ))  # Monday
        self.tasks = Tasks(self.store, self.cfg, self.clock)
        self.events = []
        self.tasks.listeners.append(lambda e, t: self.events.append((e, t["id"])))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class TaskBehaviour(Base):
    def dog_meds(self):
        return self.tasks.create({"title": "Dog medication", "category": "Dogs", "priority": "p0",
                                  "schedule": {"kind": "interval", "interval_n": 30, "interval_unit": "days"},
                                  "due": "2026-11-06", "source": "seed:dog_meds"})

    def test_p0_gets_default_time_and_follows_reality(self):
        t = self.dog_meds()
        self.assertEqual(t["schedule"]["due_time"], "17:30")
        self.assertEqual(t["eff_due"], "2026-11-06")
        self.clock.set(date(2026, 11, 9))
        self.assertEqual(self.tasks.get(t["id"])["state"], "overdue")
        done = self.tasks.complete(t["id"], "Alex", "telegram", occurrence="20261106")
        self.assertEqual(done["eff_due"], "2026-12-09")
        self.assertIn(("completed", t["id"]), self.events)

    def test_second_tap_is_409_not_a_skipped_occurrence(self):
        t = self.tasks.create({"title": "Mow", "schedule": {"kind": "rrule", "rrule": "FREQ=WEEKLY;BYDAY=SA"},
                               "due": "2026-10-19"})
        occ = t["occurrence"]
        self.assertEqual(occ, "20261024")
        self.tasks.complete(t["id"], "Alex", "ha_push", occurrence=occ)
        with self.assertRaises(TaskError) as e:
            self.tasks.complete(t["id"], "Sam", "ha_push", occurrence=occ)
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(len(self.tasks.completions(t["id"])), 1)
        self.assertEqual(self.tasks.get(t["id"])["nominal_due"], "2026-10-31")
        with self.assertRaises(TaskError):   # a stale digest button can't snooze the next one either
            self.tasks.snooze(t["id"], occurrence=occ)

    def test_skip_then_edit_does_not_resurrect_skipped(self):
        t = self.tasks.create({"title": "Water plants", "schedule": {"kind": "rrule", "rrule": "FREQ=WEEKLY;BYDAY=SA"},
                               "due": "2026-10-01"})
        self.assertEqual(t["nominal_due"], "2026-10-03")
        for _ in range(3):
            t = self.tasks.skip(t["id"], occurrence=t["occurrence"])
        self.assertEqual(t["nominal_due"], "2026-10-24")
        t = self.tasks.patch(t["id"], {"schedule": {"rrule": "FREQ=WEEKLY;BYDAY=SU"}})
        self.assertEqual(t["nominal_due"], "2026-10-25")
        self.assertNotEqual(t["state"], "overdue")

    def test_snoozed_fall_task_keeps_this_years_occurrence(self):
        t = self.tasks.create({"title": "Winterize", "priority": "p1", "schedule": {
            "kind": "rrule", "rrule": "FREQ=YEARLY;BYMONTH=9;BYMONTHDAY=21", "flex": "weekend", "anchor_date": "2026-09-21"}})
        self.assertEqual(t["nominal_due"], "2026-09-21")
        t = self.tasks.snooze(t["id"], until="2026-10-23")
        self.assertEqual((t["eff_due"], t["state"]), ("2026-10-23", "upcoming"))
        # the page re-sends the whole schedule on every save
        t = self.tasks.patch(t["id"], {"notes": "x", "schedule": dict(t["schedule"])})
        self.assertEqual(t["nominal_due"], "2026-09-21")   # still this year's, not next September
        self.assertEqual(t["eff_due"], "2026-10-23")
        self.clock.set(date(2026, 10, 24))
        t = self.tasks.complete(t["id"], occurrence=t["occurrence"])
        self.assertEqual(t["nominal_due"], "2027-09-21")
        self.assertEqual(t["eff_due"], "2027-09-24")       # Tuesday -> Friday

    def test_snooze_is_not_completion(self):
        t = self.dog_meds()
        self.clock.set(date(2026, 11, 6), 18)
        s = self.tasks.snooze(t["id"], occurrence=t["occurrence"])
        self.assertEqual(s["eff_due"], "2026-11-07")
        self.assertEqual(s["nominal_due"], "2026-11-06")
        self.assertEqual(self.tasks.completions(t["id"]), [])
        self.assertIn(("snoozed", t["id"]), self.events)

    def test_weekend_flex_and_one_off(self):
        t = self.tasks.create({"title": "Weed beds", "repeat": "every 2 weeks on the weekend", "due": "2026-10-20"})
        self.assertEqual(t["schedule"]["kind"], "interval")
        self.assertEqual(t["eff_due"], "2026-10-23")   # Tuesday -> Friday
        once = self.tasks.create({"title": "Call the insurer", "due": "2026-10-19", "priority": "high"})
        self.assertEqual((once["priority"], once["state"]), (1, "due"))
        self.assertTrue(self.tasks.complete(once["id"])["closed"])
        with self.assertRaises(TaskError):
            self.tasks.complete(once["id"])

    def test_moving_due_reanchors(self):
        t = self.dog_meds()
        t = self.tasks.patch(t["id"], {"due": "2026-11-02"})
        self.assertEqual(t["eff_due"], "2026-11-02")

    def test_high_medium_low_and_alarm(self):
        t = self.tasks.create({"title": "Meds", "priority": "critical"})
        self.assertEqual((t["priority"], t["priority_label"], t["alarm"], t["schedule"]["due_time"]), (1, "High", True, "17:30"))
        t = self.tasks.create({"title": "Rug", "priority": "low"})
        self.assertEqual((t["priority_label"], t["alarm"]), ("Low", False))
        t = self.tasks.patch(t["id"], {"alarm": True, "priority": "medium"})
        self.assertEqual((t["priority_label"], t["alarm"]), ("Medium", True))
        t = self.tasks.patch(t["id"], {"alarm": False})
        self.assertFalse(t["alarm"])

    def test_board_order_and_kind_filter(self):
        a = self.tasks.create({"title": "One-off A"})
        b = self.tasks.create({"title": "One-off B"})
        r = self.tasks.create({"title": "Mow", "repeat": "every saturday"})
        self.assertLess(a["position"], b["position"])          # new tasks go to the bottom
        moved = self.tasks.patch(b["id"], {"position": a["position"] - 512, "priority": "high"})
        self.assertEqual((moved["priority_label"], moved["position"]), ("High", a["position"] - 512))
        self.assertEqual({t["title"] for t in self.tasks.list(kind="oneoff")}, {"One-off A", "One-off B"})
        self.assertEqual([t["title"] for t in self.tasks.list(kind="recurring")], ["Mow"])

    def test_homelab_has_stages_and_never_reminds(self):
        self.clock.set(date(2026, 10, 23), 8)   # Friday
        h = self.tasks.create({"title": "Fix the backup job", "category": "Infrastructure", "priority": "critical",
                               "due": "2026-10-20"})
        self.assertEqual((h["area"], h["stage"], h["alarm"], h["schedule"]["due_time"]), ("homelab", "idea", False, None))
        chore = self.tasks.create({"title": "Gutters", "due": "2026-10-20"})
        self.assertEqual((chore["area"], chore["stage"]), ("household", None))
        # nothing that reminds or summarises sees it
        self.assertEqual([t["id"] for t in self.tasks.open_tasks()], [chore["id"]])
        self.assertEqual(self.tasks.summary()["overdue"], 1)
        secs = digest.sections(self.tasks.open_tasks(), self.clock().date(), "evening")
        self.assertNotIn(h["id"], [t["id"] for _, rows in secs for t in rows])
        proj = self.tasks.projected(self.clock().date(), self.clock().date() + timedelta(days=30))
        self.assertNotIn(h["id"], [p["task"]["id"] for p in proj])
        self.assertEqual([t["id"] for t in self.tasks.list(kind="homelab")], [h["id"]])
        self.assertEqual([t["id"] for t in self.tasks.list(kind="oneoff")], [chore["id"]])
        # stages move; household tasks have none; done shows for the Done column
        self.assertEqual(self.tasks.patch(h["id"], {"stage": "doing"})["stage"], "doing")
        with self.assertRaises(TaskError):
            self.tasks.patch(h["id"], {"stage": "shipped"})
        with self.assertRaises(TaskError):
            self.tasks.patch(chore["id"], {"stage": "doing"})
        self.tasks.complete(h["id"], done_by="Alex", source="web")
        self.assertEqual(self.tasks.list(kind="homelab"), [])
        self.assertEqual([t["status"] for t in self.tasks.list(kind="homelab", done_days=14)], ["done"])
        self.clock.set(date(2026, 11, 10), 8)
        self.assertEqual(self.tasks.list(kind="homelab", done_days=14), [])
        # reopening puts it back on the board
        self.assertEqual(self.tasks.patch(h["id"], {"status": "open", "stage": "next"})["stage"], "next")
        # moving between areas: a chore filed under a project, and back
        moved = self.tasks.patch(chore["id"], {"category": "Home Assistant"})
        self.assertEqual((moved["area"], moved["stage"]), ("homelab", "idea"))
        back = self.tasks.patch(chore["id"], {"category": "Repairs & Maintenance"})
        self.assertEqual((back["area"], back["stage"]), ("household", None))

    def test_old_p0_rows_migrate_to_high_with_alarm(self):
        import sqlite3
        path = str(Path(self.tmp.name) / "old.db")
        Store(path).close()                      # today's schema, then back to the old shape
        db = sqlite3.connect(path)
        db.execute("ALTER TABLE tasks DROP COLUMN alarm")
        db.execute("ALTER TABLE tasks DROP COLUMN position")
        db.execute("INSERT INTO tasks(id, title, category, priority, created_at, updated_at) VALUES "
                   "(1, 'Meds', 'Dogs', 0, 'x', 'x'), (2, 'Rug', 'Inbox', 3, 'x', 'x')")
        db.commit(); db.close()
        Store(path).close()
        db = sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT id, priority, alarm, position IS NOT NULL FROM tasks ORDER BY id").fetchall(),
                         [(1, 1, 1, 1), (2, 3, 0, 1)])
        db.close()

    def test_validation(self):
        for bad in ({"title": ""}, {"title": "x", "priority": "p9"}, {"title": "x", "category": "Nope"},
                    {"title": "x", "repeat": "whenever"}, {"title": "x", "assignee": "nobody"}):
            with self.assertRaises(TaskError, msg=bad):
                self.tasks.create(bad)

    def test_summary_projection_and_digest_dedupe(self):
        self.clock.set(date(2026, 10, 23), 8)   # Friday
        a = self.tasks.create({"title": "Meds", "priority": "p0", "due": "2026-10-22"})        # P0 overdue
        b = self.tasks.create({"title": "Gutters", "priority": "p1", "due": "2026-10-20"})     # overdue
        c = self.tasks.create({"title": "Weed", "repeat": "every weekend", "due": "2026-10-23"})  # due (weekend)
        d = self.tasks.create({"title": "Bins", "due": "2026-10-25", "assignee": "alex"})    # Sunday
        secs = digest.sections(self.tasks.open_tasks(), self.clock().date(), "morning")
        ids = [t["id"] for _, rows in secs for t in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([title for title, _ in secs], ["Alarms", "Overdue", "Today", "This weekend"])
        self.assertEqual(dict((k, [t["id"] for t in v]) for k, v in secs),
                         {"Alarms": [a["id"]], "Overdue": [b["id"]], "Today": [c["id"]], "This weekend": [d["id"]]})
        head, body = digest.render(secs, self.clock().date(), "morning", "alex")
        self.assertIn("4 tasks", head)
        s = self.tasks.summary()
        self.assertEqual((s["overdue"], s["p0_open"]), (2, 1))
        proj = self.tasks.projected(self.clock().date(), self.clock().date() + timedelta(days=14))
        weed = [p["date"].isoformat() for p in proj if p["task"]["id"] == c["id"]]
        self.assertEqual(weed[0], "2026-10-23")
        said = digest.dog_alarm(self.tasks.open_tasks(), first_today=True)
        self.assertTrue(said["verbatim"])
        self.assertIn("Meds", said["text"])
        self.assertIn("Gutters", said["text"])
        cal = ics.render(proj, self.clock(), TZ)
        self.assertIn("BEGIN:VEVENT", cal)
        self.assertIn("SUMMARY:Meds · alarm (overdue 1 day)", cal)
        self.assertTrue(all(len(l.encode()) <= 75 for l in cal.split("\r\n")))


class QuietHours(Base):
    """Quiet = HA night mode on; the 22:00-07:00 clock window only stands in
    when HA's state is unknown or stale."""
    def sched(self, night=None, read_at=None):
        from app.scheduler import Scheduler
        s = Scheduler(self.cfg, self.store, self.tasks, Shopping(self.store, self.clock), None, None)
        if night is not None:
            s.quiet_state = (night, read_at or self.clock())
        return s

    def at(self, hh, mm=0, day=date(2026, 10, 19)):
        return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)

    def test_night_mode_decides(self):
        def due(hh, mm, slot, night):
            return self.sched(night=night, read_at=self.at(hh, mm))._due_slot(self.at(hh, mm), slot)
        self.assertTrue(due(22, 30, "20:30", night=False))    # night mode off: fine late in the evening
        self.assertTrue(due(23, 3, "20:30", night=False))
        self.assertFalse(due(23, 31, "20:30", night=False))   # catch-up over
        self.assertFalse(due(21, 0, "20:30", night=True))     # night mode on: hold
        self.assertFalse(self.sched(night=False, read_at=self.at(2, 0)).quiet(self.at(2, 0)))

    def test_clock_window_when_ha_unknown_or_stale(self):
        s = self.sched()
        self.assertTrue(s.quiet(self.at(23, 0)))
        self.assertFalse(s.quiet(self.at(21, 0)))
        s = self.sched(night=False, read_at=self.at(20, 0))
        self.assertTrue(s.quiet(self.at(23, 0)))     # reading is 3 h old -> clock window

    def test_p0_waits_for_night_mode_to_end_that_day(self):
        s = self.sched(night=True, read_at=self.at(17, 30))
        self.assertFalse(s._due_slot(self.at(17, 30), "17:30", whole_day=True))
        s = self.sched(night=False, read_at=self.at(21, 15))
        self.assertTrue(s._due_slot(self.at(21, 15), "17:30", whole_day=True))   # hours later, same day
        self.assertFalse(s._due_slot(self.at(21, 15), "17:30"))                  # non-P0 slots still expire

    def test_alarms_go_out_with_the_feeding_announcement(self):
        import asyncio
        meds = self.tasks.create({"title": "Meds", "priority": "critical", "due": "2026-10-19"})          # default time
        early = self.tasks.create({"title": "Airport", "priority": "critical", "due": "2026-10-19",
                                   "schedule": {"due_time": "09:00"}})                                     # its own time
        s = self.sched(night=False, read_at=self.at(17, 30))
        self.assertTrue(s.with_announcement(meds) and not s.with_announcement(early))
        sent = lambda r: sorted({x["summary"].split(":")[0].replace("⚠️", "").strip() for x in r
                                 if x["status"] == "dry-run" and "→" in x["summary"]})
        self.assertEqual(sent(asyncio.run(s.p0_push(self.at(17, 30)))), ["Airport"])   # 17:30 alone no longer sends meds
        s.quiet_state = (False, self.at(19, 30))
        s.record(0, "dog_alarm_heard", "2026-10-19", "hook", True)                      # the announcement played
        self.assertEqual(sent(asyncio.run(s.p0_push(self.at(19, 30)))), ["Meds"])
        self.assertEqual(sent(asyncio.run(s.p0_push(self.at(19, 35)))), [])             # once a day
        # a day with no announcement: 20:30 stands in, but never while night mode is on
        s.store.db.execute("DELETE FROM notifications")
        s.quiet_state = (False, self.at(20, 0))
        self.assertFalse(s.announcement_due(self.at(20, 0)))
        s.quiet_state = (False, self.at(20, 30))
        self.assertTrue(s.announcement_due(self.at(20, 30)))
        s.quiet_state = (True, self.at(21, 0))
        self.assertFalse(s.announcement_due(self.at(21, 0)))

    def test_empty_digest_blocks_the_rest_of_the_day(self):
        import asyncio
        self.clock.set(date(2026, 10, 19), 20, 30)
        s = self.sched(night=False)
        self.assertEqual(asyncio.run(s.digest_job(self.clock(), "evening"))[0]["status"], "empty")
        self.tasks.create({"title": "Late arrival", "due": "2026-10-19"})
        self.clock.set(date(2026, 10, 19), 21, 0)
        s.quiet_state = (False, self.clock())
        self.assertEqual(asyncio.run(s.digest_job(self.clock(), "evening")), [])

    def test_new_tasks_default_to_1730(self):
        for body in ({"title": "a", "due": "2026-10-20"}, {"title": "b", "schedule": {"kind": "none", "due_time": None}},
                     {"title": "c", "repeat": "every saturday"}):
            self.assertEqual(self.tasks.create(body)["schedule"]["due_time"], "17:30", body)
        self.assertEqual(self.tasks.create({"title": "d", "repeat": "every saturday at 9am"})["schedule"]["due_time"], "09:00")


class ShoppingBehaviour(Base):
    def test_add_buy_dedupe_and_archive(self):
        shop = Shopping(self.store, self.clock)
        a = shop.add([{"title": "Milk", "list": "groceries"}, {"title": "milk", "list": "Groceries"},
                      {"title": "Light bulbs", "list": "Everything Else"}])
        self.assertEqual([x["duplicate"] for x in a], [False, True, False])
        with self.assertRaises(TaskError):
            shop.lists.archive("Groceries")
        shop.buy(a[0]["id"], "Alex")
        with self.assertRaises(TaskError):
            shop.buy(a[0]["id"], "Sam")
        self.assertEqual([i["title"] for i in shop.items()], ["Light bulbs"])
        shop.unbuy(a[0]["id"])
        self.assertEqual(len(shop.items("Groceries")), 1)


class Api(Base):
    def test_auth_hooks_and_occurrence_buttons(self):
        from fastapi.testclient import TestClient
        from app.web import create_app
        app = create_app(cfg=self.cfg, store=self.store, clock=self.clock, start_scheduler=False)
        with TestClient(app) as c:
            self.assertEqual(c.get("/api/health").status_code, 200)
            self.assertEqual(c.get("/api/tasks").status_code, 403)
            self.assertEqual(c.get("/api/tasks", headers={"X-Tasks-Request": "1"}).status_code, 200)
            self.assertEqual(c.post("/hooks/dog-alarm", json={}).status_code, 401)
            auth = {"Authorization": f"Bearer {TOKEN}"}
            r = c.post("/api/tasks", headers=auth, json={"title": "Meds", "priority": "p0", "due": "2026-10-19",
                                                         "source": "seed:dog_meds",
                                                         "schedule": {"kind": "interval", "interval_n": 30, "interval_unit": "days"}})
            t = r.json()["task"]
            said = c.post("/hooks/dog-alarm", headers=auth, json={}).json()
            self.assertTrue(said["verbatim"] and "Meds" in said["text"])
            act = f"TASK_DONE_{t['id']}_{t['occurrence']}"
            r1 = c.post("/hooks/ha-action", headers=auth, json={"action": act, "device": "dev-a"}).json()
            self.assertEqual(r1["task"]["eff_due"], "2026-11-18")
            r2 = c.post("/hooks/ha-action", headers=auth, json={"action": act, "device": "dev-a"}).json()
            self.assertTrue(r2.get("already"))
            hist = c.get("/api/history", headers=auth).json()["completions"]
            self.assertEqual([(h["done_by"], h["source"]) for h in hist], [("Alex", "ha_push")])
            p = c.post("/api/tasks/parse-schedule", headers=auth, json={"text": "every saturday"}).json()
            self.assertEqual((p["schedule"]["kind"], p["next"][0]), ("rrule", "2026-10-24"))
            self.assertEqual(c.post("/api/tasks/parse-schedule", headers=auth, json={"text": "sometimes"}).status_code, 400)
            self.assertIn("BEGIN:VCALENDAR", c.get("/calendar.ics").text)
            ran = c.post("/api/admin/run", headers=auth, json={"job": "digest_morning", "force": True}).json()
            self.assertTrue(all(r["status"] in ("dry-run", "empty") for r in ran["results"]))


if __name__ == "__main__":
    unittest.main()
