"""Text for digests, P0 nags, the dog-alarm hook and "what's coming up".

Each task appears in exactly one digest section, by precedence:
Alarms → Overdue → Today → Tomorrow (evening only) → This weekend (Thu-Sat only).
"""
from __future__ import annotations

from datetime import date, timedelta

from . import schedule as sch
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
    seen, out = set(), []

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


def render(secs: list[tuple[str, list[dict]]], today: date, kind: str, person_id: str | None = None) -> tuple[str, str]:
    """(title, body) for a digest; body is empty when there's nothing to say."""
    lead = "Good morning" if kind == "morning" else "This evening"
    total = sum(len(rows) for _, rows in secs)
    if not total:
        return "", ""
    lines = []
    for title, rows in secs:
        lines.append(f"{title}:")
        for t in order_for(person_id, rows):
            lines.append(f"• {t['title']}{_meta(t, today)}")
    head = f"{lead}: {total} task{'s' if total != 1 else ''}"
    return head, "\n".join(lines)


def p0_push(t: dict, today: date) -> tuple[str, str]:
    title = f"⚠️ {t['title']}"
    if t["overdue"]:
        n = t["days_overdue"]
        msg = f"Was due {n} day{'s' if n != 1 else ''} ago. Tap Done once it's done."
    else:
        msg = "Due today" + (f" at {t['schedule']['due_time']}" if t["schedule"]["due_time"] else "") + ". Tap Done once it's done."
    return title, msg


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


def p1_overdue_push(t: dict) -> tuple[str, str]:
    n = t["days_overdue"]
    return f"Overdue: {t['title']}", f"{n} day{'s' if n != 1 else ''} overdue (high priority). Snooze it if it can wait."


def _spoken_list(titles: list[str]) -> str:
    if len(titles) <= 1:
        return "".join(titles)
    return ", ".join(titles[:-1]) + " and " + titles[-1]


def p0_spoken(t: dict) -> str:
    if t["overdue"]:
        n = t["days_overdue"]
        when = f"was due {n} day{'s' if n != 1 else ''} ago"
    else:
        when = "is due today"
    return f"Reminder: {t['title']} {when}. Tap Done in the notification once it's done."


def dog_alarm(tasks: list[dict], first_today: bool) -> dict:
    """What the feed-dogs reminder should append to its speech."""
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
    parts += [p0_spoken(t) for t in p0]
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
# Each repeat of a nagging task's reminder is a step more passive-aggressive.
# HA's house persona writes the line when it can (NAG_TEXT_SCRIPT); these are
# what it is asked for, and the fixed lines used when it can't answer.
NAG_TONES = [
    "Warm and friendly: a light nudge.",
    "Cheerful, with a hint of teasing.",
    "Mildly passive-aggressive, like a polite office email that is 'just circling back'.",
    "Openly passive-aggressive ('as per my last reminder'), with an audible sigh.",
    "Exasperated and sarcastic, keeping score of how many reminders this has taken.",
    "Theatrically disappointed, laying on the guilt.",
]
ESCALATION_TONES = [
    "An official escalation: announce, smugly, that {others} {have} now been brought in, "
    "and that everyone will hear about it every hour until it's done.",
    "Full melodrama and maximum passive aggression, as if this were the greatest betrayal "
    "in household history, while staying affectionate.",
]
NAG_FALLBACK = [
    "Due now. Tap Done once it's done.",
    "Friendly reminder: {title}. Still waiting on that Done.",
    "Just circling back on {title}. No pressure. Some pressure.",
    "As per my last reminder: {title}. The Done button is right there.",
    "{title}, still. That's {elapsed}. The Done button misses you.",
    "Not to be dramatic, but {title} has now been ignored for {elapsed}.",
]
ESCALATION_FALLBACK = [
    "{title} still isn't done after {elapsed}, so {everyone} {have} been looped in. Whoever taps Done first wins.",
    "{elapsed} of {title} not being done. {everyone}, this is your sign. Tap Done.",
]


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


def nag(t: dict, step: int, minutes_late: int, escalated: bool, people: list[str]) -> dict:
    """The reminder for one step of a nagging task: {title, fallback, prompt}.
    step counts from 0 at the due time; escalated steps count from 0 again.
    people: who gets this one (names)."""
    who = t["assignee_name"] or "everyone"
    others = [n for n in people if n != t["assignee_name"]]
    fill = {"title": t["title"], "elapsed": elapsed_text(minutes_late), "everyone": _names(people),
            "have": "has" if len(people) == 1 else "have"}
    if escalated:
        line = ESCALATION_FALLBACK[min(step, len(ESCALATION_FALLBACK) - 1)]
        tone = ESCALATION_TONES[min(step, len(ESCALATION_TONES) - 1)].format(
            others=_names(others), have="has" if len(others) == 1 else "have")
        title = f"⚠️ {t['title']}"
    else:
        line = NAG_FALLBACK[min(step, len(NAG_FALLBACK) - 1)]
        tone = NAG_TONES[min(step, len(NAG_TONES) - 1)]
        title = t["title"]
    fallback = line.format(**fill)
    fallback = fallback[0].upper() + fallback[1:]
    due_time = t["schedule"]["due_time"] or ""
    late = f" It was due at {due_time}, {fill['elapsed']} ago." if minutes_late else f" It's due now ({due_time})."
    prompt = (f"Write a phone notification reminding {who} to do this task: {t['title']}.{late}"
              + (f" This goes to {_names(people)}." if escalated else "")
              + f" Tone: {tone} Playful, never mean, no swearing, and don't invent details about the task."
              " One or two short sentences, at most 35 words. Name the task and end by telling them to tap Done.")
    return {"title": title, "fallback": fallback, "prompt": prompt}
