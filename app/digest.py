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
# a house voice picked at random for each reminder. Fixed lines: {title}, {who}
# (the assignee, or everyone), {elapsed} since it was due, and for escalations
# {everyone} who gets it and {have}.
NAG_VOICES = {
    "Plain": {   # a polite office email, slowly losing its composure
        "nag": [
            "{title}: due now. Tap Done when it's done. Easy.",
            "Quick nudge on {title}. Should only take a second. Tap Done.",
            "Just circling back on {title}! No rush. (There is a little rush.) Tap Done.",
            "Per my last three reminders: {title}. The Done button is exactly where we left it.",
            "{elapsed} on {title}. I've started a spreadsheet. Tap Done so I can delete it.",
            "{elapsed}. I'm not upset about {title}. I'll just sit here quietly until someone taps Done.",
        ],
        "escalate": [
            "As {title} has been pending for {elapsed}, I've taken the liberty of cc'ing {everyone}. Tap Done whenever suits. Now suits.",
            "{elapsed} and counting on {title}. {everyone}, I'll keep sending these. I have nothing but time. Tap Done.",
        ],
    },
    "Gen Z": {
        "nag": [
            "{who}, it's {title} o'clock 💅 Tap Done and go be iconic.",
            "{title} is still just sitting there. Not a vibe. Tap Done, bestie.",
            "Not me checking on {title} again after {elapsed}. Lowkey begging. Tap Done.",
            "{title}. Again. I said what I said. It's literally one button. Tap Done.",
            "{elapsed} of leaving {title} on read?? The disrespect is giving. Tap Done.",
            "{elapsed} and {title} still isn't done. I need everyone to act normal. Tap Done. 😭",
        ],
        "escalate": [
            "Okay so {title} got ghosted for {elapsed}, so I added {everyone} to the chat. This is an intervention. Tap Done.",
            "{elapsed}. {title}. Still. {everyone}, this is giving main-character neglect. Someone tap Done, fr fr.",
        ],
    },
    "Shakespearean": {
        "nag": [
            "Hark, {who}! The hour of {title} is come. Tap Done, and be thou blessed.",
            "Good {who}, doth {title} slip thy mind? One gentle Done would mend all.",
            "{elapsed} hath crept by on silent feet, and {title} yet waits. I but inquire. Tap Done.",
            "Once more unto the breach: {title}! Methinks the Done button doth protest too little.",
            "{elapsed}! Is it neglect, or some deeper villainy? {title} cries out for justice. Tap Done.",
            "{title}, forsaken {elapsed}. Et tu, {who}? End this tragedy in one act: tap Done.",
        ],
        "escalate": [
            "Alas! {title} lies unheeded {elapsed}, so I have summon'd {everyone} to court. Whoso taps Done first shall be knighted.",
            "{elapsed}! A plague upon this house! {everyone}, the fate of {title} rests with thee. Tap Done, ere I weep.",
        ],
    },
    "Pirate": {
        "nag": [
            "Ahoy, {who}! {title} be due. Tap Done an' earn yer grog.",
            "Arr, {title} still be sittin' on deck. Tap Done, matey.",
            "{elapsed} at sea an' no sign o' {title}. Just askin', savvy? Tap Done.",
            "As I bellowed afore: {title}! The Done button be right there, ye barnacle.",
            "{elapsed} adrift with no {title}. The crew be whisperin' mutiny. Tap Done.",
            "{elapsed}! Even the parrot be ashamed o' {title}. Tap Done, ye scallywag.",
        ],
        "escalate": [
            "All hands! {title} be ignored for {elapsed}, so I've piped {everyone} aboard. First to tap Done gets the treasure.",
            "{elapsed} o' {title} undone! {everyone}, tap Done or the lot o' ye walk the plank.",
        ],
    },
    "Mad scientist": {
        "nag": [
            "The experiment begins! Subject {who}: {title} is due. Tap Done to record the result. Mwahaha.",
            "Observation: {title} remains incomplete. Fascinating. Tap Done, for science.",
            "{elapsed} into the trial and {title} is still pending. My notes grow concerned. Tap Done.",
            "Hypothesis: you saw my last reminder about {title}. Conclusion: tap Done.",
            "{elapsed}! The data suggests deliberate avoidance of {title}. Tap Done before I publish.",
            "{elapsed} of {title} ignored. My assistant has fainted. The beakers weep. TAP. DONE.",
        ],
        "escalate": [
            "Containment breach! {title} unattended for {elapsed}, so I've summoned {everyone} to the lab. Whoever taps Done saves the experiment.",
            "{elapsed}! The reactor of disappointment is going critical over {title}. {everyone}, tap Done before it blows!",
        ],
    },
    "NYC cabbie": {
        "nag": [
            "Yo {who}, {title}. Now's good. Tap Done, I got places to be.",
            "Still waitin' on {title}. Meter's runnin', buddy. Tap Done.",
            "{elapsed} I'm idlin' out front for {title}. Just sayin'. Tap Done.",
            "Whaddya want, a written invitation? {title}. Done button. Go.",
            "{elapsed}! I've seen the BQE move faster than {title}. Tap Done already.",
            "{elapsed} for {title}? I drove to Jersey and back. Twice. Tap Done, would ya?",
        ],
        "escalate": [
            "Alright, {title}'s been sittin' there {elapsed}, so I called in {everyone}. First one to tap Done gets the tip.",
            "{elapsed} of {title}. Unbelievable. {everyone}, tap Done before I lean on this horn.",
        ],
    },
    "Robot": {
        "nag": [
            "BEEP. {title} is due. Awaiting Done. Have a nice day.",
            "Status check: {title} incomplete. Please tap Done. Thank you for your cooperation.",
            "Following up on {title}. Elapsed: {elapsed}. Compliance would be appreciated. Tap Done.",
            "Per previous transmission: {title}. Done button located. Awaiting input. Still awaiting input.",
            "{elapsed} without {title}. Patience subroutine at 12%. Tap Done.",
            "{elapsed}. {title}. Still. Disappointment module fully engaged. This unit is fine. Tap Done.",
        ],
        "escalate": [
            "Escalation protocol initiated: {title} incomplete for {elapsed}. {everyone} {have} been notified. First to tap Done wins.",
            "{elapsed} of {title} undone. This unit is not angry. This unit is disappointed. {everyone}: tap Done.",
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
    """The reminder for one step of a nagging task: {text, voice}. There's no
    heading: every line names the task, and an escalation starts with ⚠️.
    step counts from 0 at the due time; escalated steps count from 0 again.
    people: who gets this one (names). seed picks the voice, so the same slot
    always says the same thing."""
    voice = random.Random(seed).choice(sorted(NAG_VOICES))
    lines = NAG_VOICES[voice]["escalate" if escalated else "nag"]
    text = lines[min(step, len(lines) - 1)].format(
        title=t["title"], who=t["assignee_name"] or "everyone", elapsed=elapsed_text(minutes_late),
        everyone=_names(people), have="has" if len(people) == 1 else "have")
    return {"text": ("⚠️ " if escalated else "") + text[0].upper() + text[1:], "voice": voice}
