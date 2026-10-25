"""Schedule rules: pure functions with no database or clock of their own.

Three kinds of task:
  none      one-off; anchor_date is its due date (or NULL = someday)
  rrule     fixed calendar (RFC 5545 RRULE text, DTSTART = anchor_date); never drifts
  interval  every N days/weeks/months/years from when it was last done

A task's current occurrence is identified by its nominal_due. The *cursor* is
the date the next occurrence is computed from; done and skip move it, edits
never do, so editing a schedule after a skip can't bring skipped occurrences
back.

Weekend flex: the weekend is Fri-Sun. A nominal Mon-Thu date moves to the
coming Friday; Fri/Sat/Sun stay. Such a task is due all weekend and overdue
from the Monday after. Nothing is ever moved earlier.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrulestr

UNITS = ("days", "weeks", "months", "years")
WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1}
# Approximate season starts (equinoxes/solstices); RRULE takes one BYMONTHDAY.
SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}
SEASON_DAY = 21
MAX_GAP_DAYS = 400


class ScheduleError(ValueError):
    pass


# ---------------------------------------------------------------- occurrences

def _rule(rule: str, anchor: date):
    return rrulestr("RRULE:" + rule, dtstart=datetime.combine(anchor, time()))


def normalize_rrule(rule: str, anchor: date) -> str:
    """Validate an RRULE (without DTSTART) and return it in canonical form."""
    text = (rule or "").strip().upper()
    if text.startswith("RRULE:"):
        text = text[6:]
    if not text or "DTSTART" in text:
        raise ScheduleError("Give the repeat rule without a start date.")
    try:
        first = _rule(text, anchor).after(datetime.combine(anchor, time()), inc=True)
    except (ValueError, TypeError) as e:
        raise ScheduleError(f"That repeat rule isn't valid ({e}).") from None
    if first is None or (first.date() - anchor).days > MAX_GAP_DAYS:
        raise ScheduleError("That repeat rule has no date in the next year.")
    return text


def add_interval(d: date, n: int, unit: str) -> date:
    if unit not in UNITS or n < 1:
        raise ScheduleError("An interval needs a positive number of days, weeks, months or years.")
    return d + relativedelta(**{unit: n})


def next_nominal(kind: str, *, anchor: date | None, cursor: date | None, rrule: str | None = None,
                 interval_n: int | None = None, interval_unit: str | None = None) -> date | None:
    """The occurrence after `cursor` (or the first one, when no cursor)."""
    if kind == "none":
        return anchor
    if anchor is None:
        raise ScheduleError("A repeating task needs a start date.")
    if kind == "interval":
        return anchor if cursor is None else add_interval(cursor, interval_n or 0, interval_unit or "")
    if kind == "rrule":
        r = _rule(rrule or "", anchor)
        nxt = (r.after(datetime.combine(anchor, time()), inc=True) if cursor is None
               else r.after(datetime.combine(cursor, time()), inc=False))
        return nxt.date() if nxt else None
    raise ScheduleError(f"Unknown schedule kind {kind!r}.")


def occurrences(kind: str, *, anchor: date | None, cursor: date | None, rrule: str | None,
                start: date, end: date, limit: int = 200) -> list[date]:
    """Nominal rrule occurrences in [start, end], after the cursor. Others: []."""
    if kind != "rrule" or anchor is None:
        return []
    r = _rule(rrule or "", anchor)
    lo = max(start, cursor + timedelta(days=1) if cursor else anchor)
    out = []
    for dt in r.xafter(datetime.combine(lo, time()), count=limit, inc=True):
        if dt.date() > end:
            break
        out.append(dt.date())
    return out


# ---------------------------------------------------------------- flex and state

def apply_flex(nominal: date | None, flex: str) -> date | None:
    if nominal is None or flex != "weekend" or nominal.weekday() >= 4:
        return nominal
    return nominal + timedelta(days=4 - nominal.weekday())


def overdue_from(due: date, flex: str) -> date:
    """First day the task counts as overdue."""
    if flex == "weekend" and due.weekday() >= 4:
        return due + timedelta(days=7 - due.weekday())
    return due + timedelta(days=1)


def effective_due(due: date | None, snoozed_until: date | None) -> date | None:
    if due is None:
        return snoozed_until
    return max(due, snoozed_until) if snoozed_until else due


def state(eff_due: date | None, flex: str, today: date) -> str:
    """someday | upcoming | due | overdue."""
    if eff_due is None:
        return "someday"
    if today >= overdue_from(eff_due, flex):
        return "overdue"
    return "due" if today >= eff_due else "upcoming"


def days_overdue(eff_due: date | None, flex: str, today: date) -> int:
    if eff_due is None:
        return 0
    return max(0, (today - overdue_from(eff_due, flex)).days + 1)


def default_snooze(flex: str, today: date) -> date:
    if flex == "weekend":
        return today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    return today + timedelta(days=1)


def cursor_after(kind: str, action: str, *, nominal_due: date | None, done_on: date, today: date) -> date | None:
    """Where the cursor moves when an occurrence is done or skipped."""
    if kind == "interval":
        return done_on if action == "done" else today
    if kind == "rrule":
        if action == "skip" or nominal_due is None:
            return nominal_due or today
        return max(done_on, nominal_due)
    return None


# ---------------------------------------------------------------- phrases

def _num(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


_NUM = r"(\d+|" + "|".join(NUMBER_WORDS) + r")"
_UNIT = r"(day|week|month|year)s?"
_WD = (r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?"
       r"|sat(?:urday)?|sun(?:day)?)s?")
_MON = r"(" + "|".join(m[:3] + r"\w*" for m in MONTH_NAMES) + r")"
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"


def _weekday(token: str) -> str:
    for code, name in zip(WEEKDAY_CODES, WEEKDAY_NAMES):
        if name.startswith(token[:3]):
            return code
    raise ScheduleError(f"Unknown weekday {token!r}.")


def _month(token: str) -> int:
    for i, name in enumerate(MONTH_NAMES, 1):
        if name.startswith(token[:3]):
            return i
    raise ScheduleError(f"Unknown month {token!r}.")


def _time(m: re.Match) -> str:
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        raise ScheduleError("That time isn't valid.")
    return f"{h:02d}:{mi:02d}"


def parse_phrase(text: str) -> dict:
    """Turn a phrase like "every 30 days from done at 5:30pm" into a schedule.

    Returns {kind, rrule, interval_n, interval_unit, flex, due_time}. A phrase
    that names no calendar anchor ("every 30 days", "monthly") repeats from
    when the task was last done; one that names an anchor ("every Saturday",
    "monthly on the 1st", "yearly on Apr 15") is a fixed calendar rule.
    """
    t = " " + re.sub(r"[,.;!]", " ", (text or "").lower()) + " "
    t = re.sub(r"\s+", " ", t)
    out = {"kind": None, "rrule": None, "interval_n": None, "interval_unit": None, "flex": "exact", "due_time": None}

    m = re.search(r" at (\d{1,2})(?::(\d{2}))? ?(am|pm)? ", t)
    if m:
        out["due_time"] = _time(m)
        t = t[:m.start()] + " " + t[m.end():]
    m = re.search(r" (?:on|over|during|any time) (?:the )?weekends? | on weekends | weekend ", t)
    if m:
        out["flex"] = "weekend"
        t = t[:m.start()] + " " + t[m.end():]
    force_interval = False
    m = re.search(r" (?:counting )?(?:from|after|since) (?:when )?(?:it(?:'s| was| is)? |they(?:'re| were| are)? )?"
                  r"(?:last )?(?:done|given|completed|finished|did it|last time) ", t)
    if m:
        force_interval = True
        t = t[:m.start()] + " " + t[m.end():]
    fixed = False
    m = re.search(r" (?:fixed|on a fixed schedule|regardless) ", t)
    if m:
        fixed = True
        t = t[:m.start()] + " " + t[m.end():]
    t = re.sub(r"^ (?:repeat(?:s|ing)?|recurring) ", " ", t).strip()
    t = re.sub(r"^(?:once )", "", t)

    def interval(n: int, unit: str):
        unit = unit.rstrip("s") + "s"
        if fixed and not force_interval:
            freq = {"days": "DAILY", "weeks": "WEEKLY", "months": "MONTHLY", "years": "YEARLY"}[unit]
            return {**out, "kind": "rrule", "rrule": f"FREQ={freq}" + (f";INTERVAL={n}" if n > 1 else "")}
        return {**out, "kind": "interval", "interval_n": n, "interval_unit": unit}

    def rule(r: str):
        if force_interval:
            raise ScheduleError("A schedule tied to a day of the week or month can't also count from when it was done.")
        return {**out, "kind": "rrule", "rrule": r}

    simple = {"daily": (1, "days"), "every day": (1, "days"), "every other day": (2, "days"),
              "weekly": (1, "weeks"), "every week": (1, "weeks"), "biweekly": (2, "weeks"),
              "fortnightly": (2, "weeks"), "every other week": (2, "weeks"),
              "monthly": (1, "months"), "every month": (1, "months"), "every other month": (2, "months"),
              "quarterly": (3, "months"), "every quarter": (3, "months"),
              "twice a year": (6, "months"), "semiannually": (6, "months"), "semi-annually": (6, "months"),
              "yearly": (1, "years"), "annually": (1, "years"), "every year": (1, "years")}
    if t == "every" and out["flex"] == "weekend":   # "every weekend"
        return interval(1, "weeks")
    if t in simple:
        return interval(*simple[t])
    if m := re.fullmatch(rf"every {_NUM} {_UNIT}", t):
        return interval(_num(m.group(1)), m.group(2))
    if m := re.fullmatch(r"once a (day|week|month|year)", t):
        return interval(1, m.group(1))

    # weekdays: every saturday / every other sunday / every sat and sun / every 2 weeks on friday
    if m := re.fullmatch(rf"(?:every|each|on) (other )?((?:{_WD})(?:(?: and | & | |/)(?:{_WD}))*)", t):
        days = sorted({_weekday(d) for d in re.findall(_WD, m.group(2))}, key=WEEKDAY_CODES.index)
        return rule("FREQ=WEEKLY" + (";INTERVAL=2" if m.group(1) else "") + ";BYDAY=" + ",".join(days))
    if m := re.fullmatch(rf"(?:every {_NUM} weeks?|weekly|every week|biweekly|every other week) on ({_WD})", t):
        n = 2 if "other" in t or "biweekly" in t else (_num(m.group(1)) if m.group(1) else 1)
        return rule("FREQ=WEEKLY" + (f";INTERVAL={n}" if n > 1 else "") + f";BYDAY={_weekday(m.group(2))}")

    # day of month: monthly on the 1st / on the 15th of every month / monthly on the last day
    if m := re.fullmatch(rf"(monthly|every month|quarterly|every quarter|every {_NUM} months) on (?:the )?(?:{_ORD}|(last)(?: day)?)", t):
        n = 3 if m.group(1).startswith(("quarter", "every quarter")) else (_num(m.group(2)) if m.group(2) else 1)
        day = -1 if m.group(4) else int(m.group(3))
        if not (day == -1 or 1 <= day <= 31):
            raise ScheduleError("That day of the month isn't valid.")
        return rule("FREQ=MONTHLY" + (f";INTERVAL={n}" if n > 1 else "") + f";BYMONTHDAY={day}")
    if m := re.fullmatch(rf"(?:on )?the (?:{_ORD}|(last) day) of (?:every|each) month", t):
        day = -1 if m.group(2) else int(m.group(1))
        return rule(f"FREQ=MONTHLY;BYMONTHDAY={day}")

    # yearly: yearly on apr 15 / every year on 15 april / yearly on 04-15 / every april [15]
    if m := re.fullmatch(rf"(?:yearly|annually|every year) on (?:{_MON} {_ORD}|{_ORD} {_MON}|(\d{{1,2}})-(\d{{1,2}}))", t):
        if m.group(1):
            mon, day = _month(m.group(1)), int(m.group(2))
        elif m.group(4):
            mon, day = _month(m.group(4)), int(m.group(3))
        else:
            mon, day = int(m.group(5)), int(m.group(6))
        return rule(f"FREQ=YEARLY;BYMONTH={mon};BYMONTHDAY={day}")
    if m := re.fullmatch(rf"(?:every|each) {_MON}(?: {_ORD})?", t):
        return rule(f"FREQ=YEARLY;BYMONTH={_month(m.group(1))};BYMONTHDAY={int(m.group(2) or 1)}")

    # seasons: seasonally / every spring / every spring and fall
    if t in ("seasonally", "every season", "each season"):
        return rule(f"FREQ=YEARLY;BYMONTH=3,6,9,12;BYMONTHDAY={SEASON_DAY}")
    if m := re.fullmatch(r"(?:every|each) ((?:spring|summer|fall|autumn|winter)(?:(?: and | & |/)(?:spring|summer|fall|autumn|winter))*)", t):
        months = sorted({SEASONS[s] for s in re.findall(r"spring|summer|fall|autumn|winter", m.group(1))})
        return rule(f"FREQ=YEARLY;BYMONTH={','.join(map(str, months))};BYMONTHDAY={SEASON_DAY}")

    raise ScheduleError(f"I couldn't read the schedule {text!r}.")


def split_phrase(text: str) -> tuple[str, dict | None]:
    """Split "water the plants every Saturday" into ("water the plants", schedule).

    The longest run of trailing words that parse_phrase reads is the schedule;
    the rest is the title. -> (text, None) when no ending reads as one, or when
    nothing would be left for the title.
    """
    words = (text or "").split()
    for i in range(1, len(words)):
        try:
            schedule = parse_phrase(" ".join(words[i:]))
        except ScheduleError:
            continue
        return " ".join(words[:i]).rstrip(" ,;:-–—"), schedule
    return (text or "").strip(), None


# ---------------------------------------------------------------- descriptions

def _ordinal(n: int) -> str:
    if n == -1:
        return "last day"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fmt_date(d: date | None, today: date | None = None) -> str:
    if d is None:
        return "no date"
    if today is not None:
        delta = (d - today).days
        if delta == 0:
            return "today"
        if delta == 1:
            return "tomorrow"
        if delta == -1:
            return "yesterday"
    text = f"{d:%a} {d.day} {d:%b}"
    return text if today is None or d.year == today.year else f"{text} {d.year}"


def describe_rule(kind: str, rrule: str | None, interval_n: int | None, interval_unit: str | None, flex: str) -> str:
    if kind == "none":
        text = "once"
    elif kind == "interval":
        unit = (interval_unit or "days").rstrip("s")
        n = interval_n or 1
        text = f"every {unit if n == 1 else f'{n} {unit}s'} after it's done"
    else:
        parts = dict(p.split("=", 1) for p in (rrule or "").split(";") if "=" in p)
        freq, n = parts.get("FREQ", ""), int(parts.get("INTERVAL", 1))
        if freq == "WEEKLY" and "BYDAY" in parts:
            names = [WEEKDAY_NAMES[WEEKDAY_CODES.index(d)].capitalize() for d in parts["BYDAY"].split(",")]
            text = ("every other " if n == 2 else f"every {n} weeks on " if n > 2 else "every ") + " and ".join(names)
        elif freq == "MONTHLY" and "BYMONTHDAY" in parts:
            lead = "quarterly" if n == 3 else "monthly" if n == 1 else f"every {n} months"
            text = f"{lead} on the {_ordinal(int(parts['BYMONTHDAY']))}"
        elif freq == "YEARLY" and "BYMONTH" in parts:
            months = [int(x) for x in parts["BYMONTH"].split(",")]
            day = int(parts.get("BYMONTHDAY", 1))
            if day == SEASON_DAY and set(months) <= {3, 6, 9, 12}:
                names = [next(s for s, mo in SEASONS.items() if mo == x) for x in months]
                text = "seasonally" if len(months) == 4 else "every " + " and ".join(names)
            else:
                text = "yearly on " + ", ".join(f"{MONTH_NAMES[x - 1][:3].capitalize()} {day}" for x in months)
        else:
            unit = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}.get(freq, "time")
            text = f"every {unit}" if n == 1 else f"every {n} {unit}s"
            text += " (fixed)"
    if flex == "weekend":
        text += ", on a weekend"
    return text
