"""Text for digests, P0 nags, the dog-alarm hook and "what's coming up".

Each task appears in exactly one digest section, by precedence:
Alarms → Overdue → Today → Tomorrow (evening only) → This weekend (Thu-Sat only).
"""
from __future__ import annotations

import random
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
# Each repeat of a nagging task's reminder is a step more passive-aggressive, in
# one house voice for the whole day. The lines don't name the task (the phone
# push carries it as its title; the Telegram group gets the line alone), and
# the Done button speaks in the same voice. Placeholders: {who} (the assignee,
# or everyone), {elapsed} since it was due, and for escalations {everyone} who
# gets it and {have}.
NAG_VOICES = {
    "Gen Z": {
        "done": "Ate. Done 💅",
        "nag": [
            "{who}, it's time 💅 Do the thing and go be iconic.",
            "It's still just sitting there. Not a vibe, bestie.",
            "Not me checking in again after {elapsed}. Lowkey begging rn.",
            "Again?? I said what I said. It's literally one button.",
            "{elapsed} of leaving it on read. The disrespect is giving.",
            "{elapsed} and it's still not done. I need everyone to act normal. 😭",
        ],
        "escalate": [
            "Okay so this got ghosted for {elapsed}, so I added {everyone} to the chat. This is an intervention.",
            "{elapsed}. Still. {everyone}, this is giving main-character neglect. Someone tap it, fr fr.",
        ],
    },
    "Shakespearean": {
        "done": "'Tis done, forsooth",
        "nag": [
            "Hark, {who}! The appointed hour is come. Do the deed, and be thou blessed.",
            "Good {who}, doth it slip thy mind? One gentle tap would mend all.",
            "{elapsed} hath crept by on silent feet, and still it waits. I but inquire.",
            "Once more unto the breach, dear {who}! Methinks the button doth protest too little.",
            "{elapsed}! Is this neglect, or some deeper villainy? Justice cries out.",
            "Forsaken {elapsed}. Et tu, {who}? End this tragedy in one act.",
        ],
        "escalate": [
            "Alas! Unheeded {elapsed}, so I have summon'd {everyone} to court. Whoso tappeth first shall be knighted.",
            "{elapsed}! A plague upon this house! {everyone}, the fate of this deed rests with thee. Tap, ere I weep.",
        ],
    },
    "Pirate": {
        "done": "Aye, 'tis done ⚓",
        "nag": [
            "Ahoy, {who}! 'Tis time. Do the deed an' earn yer grog.",
            "Arr, it still be sittin' on deck, matey.",
            "{elapsed} at sea an' nary a sign of it. Just askin', savvy?",
            "As I bellowed afore! The button be right there, ye barnacle.",
            "{elapsed} adrift. The crew be whisperin' mutiny.",
            "{elapsed}! Even the parrot be ashamed o' ye, scallywag.",
        ],
        "escalate": [
            "All hands! Ignored for {elapsed}, so I've piped {everyone} aboard. First to tap gets the treasure.",
            "{elapsed} an' still undone! {everyone}, tap it or the lot o' ye walk the plank.",
        ],
    },
    "Mad scientist": {
        "done": "Eureka! Done 🧪",
        "nag": [
            "The experiment begins! Subject {who}, it is time. Record the result. Mwahaha.",
            "Observation: still incomplete. Fascinating. Proceed, for science.",
            "{elapsed} into the trial and no result. My notes grow concerned.",
            "Hypothesis: you saw my last reminder. Conclusion: press the button.",
            "{elapsed}! The data suggests deliberate avoidance. Press it before I publish.",
            "{elapsed} of silence. My assistant has fainted. The beakers weep. PRESS. IT.",
        ],
        "escalate": [
            "Containment breach! Unattended for {elapsed}, so I've summoned {everyone} to the lab. Whoever presses first saves the experiment.",
            "{elapsed}! The reactor of disappointment is going critical. {everyone}, press it before it blows!",
        ],
    },
    "NYC cabbie": {
        "done": "Yeah yeah, done 🚕",
        "nag": [
            "Yo {who}, it's time. Now's good. I got places to be.",
            "Still waitin' here. Meter's runnin', buddy.",
            "{elapsed} I'm idlin' out front. Just sayin'.",
            "Whaddya want, a written invitation? Button. Go.",
            "{elapsed}! I've seen the BQE move faster than this.",
            "{elapsed}? I drove to Jersey and back. Twice. Would ya tap the thing?",
        ],
        "escalate": [
            "Alright, it's been sittin' there {elapsed}, so I called in {everyone}. First one to tap gets the tip.",
            "{elapsed}. Unbelievable. {everyone}, tap it before I lean on this horn.",
        ],
    },
    "Robot": {
        "done": "TASK COMPLETE 🤖",
        "nag": [
            "BEEP. Scheduled task is due, {who}. Awaiting confirmation. Have a nice day.",
            "Status check: task incomplete. Please confirm. Thank you for your cooperation.",
            "Following up. Elapsed: {elapsed}. Compliance would be appreciated.",
            "Per previous transmission: button located. Awaiting input. Still awaiting input.",
            "{elapsed} without confirmation. Patience subroutine at 12%.",
            "{elapsed}. Still. Disappointment module fully engaged. This unit is fine.",
        ],
        "escalate": [
            "Escalation protocol initiated: task incomplete for {elapsed}. {everyone} {have} been notified. First to confirm wins.",
            "{elapsed} undone. This unit is not angry. This unit is disappointed. {everyone}: confirm.",
        ],
    },
}


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


def nag(t: dict, step: int, minutes_late: int, escalated: bool, people: list[str], seed: str = "") -> dict:
    """The reminder for one step of a nagging task: {title, line, telegram, done, voice}.
    title: the phone push's heading (the task, ⚠️ first when escalated) over line,
    the voiced text; telegram: all the group gets, the line alone (⚠️ first when
    escalated); done: the Done button's label in the same voice.
    step counts from 0 at the due time; escalated steps count from 0 again.
    people: who gets this one (names). seed picks the voice: one per task per
    day, so a day's reminders all speak the same way."""
    voice = random.Random(seed).choice(sorted(NAG_VOICES))
    v = NAG_VOICES[voice]
    lines = v["escalate" if escalated else "nag"]
    text = lines[min(step, len(lines) - 1)].format(
        who=t["assignee_name"] or "everyone", elapsed=elapsed_text(minutes_late),
        everyone=_names(people), have="has" if len(people) == 1 else "have")
    warn, line = "⚠️ " if escalated else "", text[0].upper() + text[1:]
    return {"title": warn + t["title"], "line": line, "telegram": warn + line, "done": v["done"], "voice": voice}
