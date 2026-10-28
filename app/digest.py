"""Text for digests, P0 nags, the dog-alarm hook and "what's coming up".

Each task appears in exactly one digest section, by precedence:
Alarms → Overdue → Today → Tomorrow (evening only) → This weekend (Thu-Sat only).
"""
from __future__ import annotations

from datetime import date, timedelta

from . import schedule as sch
from . import voices
from .tasks import weekend_window


def _meta(t: dict, today: date, show_person: bool = True) -> str:
    bits = []
    if t["priority"] == 1:
        bits.append("High")
    if show_person and t["assignee_name"]:
        bits.append(t["assignee_name"])
    if t["overdue"]:
        n = t["days_overdue"]
        bits.append(f"{n} day{'s' if n != 1 else ''} overdue")
    elif t["schedule"]["due_time"] and t["state"] == "due":
        bits.append(t["schedule"]["due_time"])
    return f" ({' · '.join(bits)})" if bits else ""


def sections(tasks: list[dict], today: date, kind: str) -> list[tuple[str, list[dict]]]:
    # a nagging task has its own reminders, so the summaries leave it out
    seen, out = {t["id"] for t in tasks if t["nag"]}, []

    def take(title, pred):
        rows = [t for t in tasks if t["id"] not in seen and pred(t)]
        seen.update(t["id"] for t in rows)
        if rows:
            out.append((title, rows))

    take("Alarms", lambda t: t["alarm"] and t["state"] in ("due", "overdue"))
    take("Overdue", lambda t: t["overdue"])
    take("Today", lambda t: t["state"] == "due")
    if kind == "evening":
        tomorrow = (today + timedelta(days=1)).isoformat()
        take("Tomorrow", lambda t: t["eff_due"] == tomorrow)
    if today.weekday() in (3, 4, 5):
        ws, we = weekend_window(today if today.weekday() >= 4 else today + timedelta(days=1))
        take("This weekend", lambda t: t["eff_due"] and ws.isoformat() <= t["eff_due"] <= we.isoformat())
    return out


def order_for(person_id: str | None, rows: list[dict]) -> list[dict]:
    """A person's own tasks first, then unassigned, then everyone else's."""
    if not person_id:
        return rows
    rank = lambda t: 0 if t["assignee"] == person_id else 1 if not t["assignee"] else 2
    return sorted(rows, key=rank)


def render(secs: list[tuple[str, list[dict]]], today: date, kind: str, person_id: str | None = None,
           voice: voices.Today | None = None) -> tuple[str, str]:
    """(title, body) for a digest; body is empty when there's nothing to say.
    The title is the day's voice opening the summary."""
    voice = voice or voices.Today(today)
    total = sum(len(rows) for _, rows in secs)
    if not total:
        return "", ""
    lines = []
    for title, rows in secs:
        lines.append(f"{title}:")
        for t in order_for(person_id, rows):
            lines.append(f"• {t['title']}{_meta(t, today)}")
    return voice.head(kind, total), "\n".join(lines)


def p0_push(t: dict, today: date, voice: voices.Today | None = None) -> tuple[str, str]:
    """(phone title, line) for an alarm task: the line names the task and is all
    the Telegram group gets."""
    voice = voice or voices.Today(today)
    n = t["days_overdue"] if t["overdue"] else 0
    return f"⚠️ {t['title']}", voice.line(t, "alarm", voices.alarm_step(n), late=voices.late_text(n))


CLOSED_VIA = {"web": "in the app", "ha_push": "from a phone notification", "switch": "with the switch",
              "telegram": "in Telegram", "missed": "not done that day"}


def closed_line(event: str, t: dict) -> str:
    """The line added under a Telegram message when one of its tasks is closed
    somewhere else, shaped like a button tap's ("✅ Title (next …) — Alex")."""
    nxt = "" if t.get("closed") or not t["eff_due"] else f" (next {t['due_text']})"
    if event == "completed":
        head = f"✅ {t['title']}{nxt}"
    elif event == "skipped":
        head = f"⏭️ {t['title']} skipped{nxt}"
    elif event == "snoozed":
        head = f"💤 {t['title']} snoozed until {t['due_text']}"
    else:
        head = f"🗄️ {t['title']} archived"
    by = t.get("closed_by") or ""
    by = "" if by in ("switch", "phone", "Tasks") else by   # stand-ins (hooks, roll-over) when no person is known
    who = ", ".join(x for x in (by, CLOSED_VIA.get(t.get("closed_via") or "", "")) if x)
    return head + (f" — {who}" if who else "")


def p1_overdue_push(t: dict, voice: voices.Today) -> tuple[str, str]:
    n = t["days_overdue"]
    return f"Overdue: {t['title']}", voice.line(t, "overdue", voices.overdue_step(n), late=voices.late_text(n))


def _spoken_list(titles: list[str]) -> str:
    if len(titles) <= 1:
        return "".join(titles)
    return ", ".join(titles[:-1]) + " and " + titles[-1]


def p0_spoken(t: dict, voice: voices.Today) -> str:
    n = t["days_overdue"] if t["overdue"] else 0
    return voice.line(t, "spoken", 1 if n else 0, late=voices.late_text(n))


def dog_alarm(tasks: list[dict], first_today: bool, voice: voices.Today) -> dict:
    """What the feed-dogs reminder should append to its speech; alarm lines
    in the day's voice."""
    p0 = [t for t in tasks if t["alarm"] and t["state"] in ("due", "overdue")]
    # a nagging task has its own reminders, so it isn't read out with the feeding
    rest = [t for t in tasks if not t["alarm"] and not t["nag"] and t["state"] in ("due", "overdue")]
    parts = []
    if first_today and rest:
        today_titles = [t["title"] for t in rest if not t["overdue"]][:6]
        overdue_titles = [t["title"] for t in rest if t["overdue"]][:4]
        if today_titles:
            parts.append(f"Also for today: {_spoken_list(today_titles)}.")
        if overdue_titles:
            parts.append(f"Overdue: {_spoken_list(overdue_titles)}.")
    parts += [p0_spoken(t, voice) for t in p0]
    return {"text": " ".join(parts), "verbatim": bool(p0), "first_today": first_today,
            "p0": [t["id"] for t in p0], "due_today": [t["id"] for t in rest] if first_today else []}


def upcoming_text(days: list[dict]) -> str:
    lines = []
    for day in days:
        if not day["tasks"] and not day["events"]:
            continue
        lines.append(day["label"])
        for e in day["events"]:
            when = "all day" if e["all_day"] else e["start"][11:16]
            lines.append(f"  {when} {e['summary']}")
        for t in day["tasks"]:
            lines.append(f"  • {t['title']} ({t['priority_label']}{' · ' + t['assignee_name'] if t['assignee_name'] else ''})")  # noqa
    return "\n".join(lines) or "Nothing on the calendar or the task list for that window."


def day_label(d: date, today: date) -> str:
    rel = sch.fmt_date(d, today)
    return rel.capitalize() if rel in ("today", "tomorrow") else rel


# ------------------------------------------------------------ nagging
# Each repeat of a nagging task's reminder is a step more passive-aggressive, in
# the day's voice (voices.VOICES). The lines don't name the task: the phone push
# carries it as its title and the Telegram group gets the line alone.


def _names(names: list[str]) -> str:
    return _spoken_list(names) or "everyone"


def elapsed_text(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minutes"
    h, m = divmod(minutes, 60)
    h += m >= 45
    half = " and a half" if 15 <= m < 45 else ""
    if h == 1:
        return f"an hour{half}"
    return f"{h}{half} hours"


def nag(t: dict, step: int, minutes_late: int, escalated: bool, people: list[str], voice: voices.Today) -> dict:
    """The reminder for one step of a nagging task: {title, line, telegram, done, voice}.
    title: the phone push's heading (the task, ⚠️ first when escalated) over line;
    telegram: all the group gets, the line alone (⚠️ first when escalated); done:
    the Done button's label in the day's voice. step counts from 0 at the due time;
    escalated steps count from 0 again. people: who gets this one (names)."""
    line = voice.line(t, "escalate" if escalated else "nag", step,
                      who=t["assignee_name"] or "everyone", elapsed=elapsed_text(minutes_late),
                      everyone=_names(people), have="has" if len(people) == 1 else "have")
    warn = "⚠️ " if escalated else ""
    return {"title": warn + t["title"], "line": line, "telegram": warn + line, "done": voice.done, "voice": voice.name}
