"""GET /calendar.ics — the task list as a calendar Home Assistant subscribes to.
GET /calendar-reminders.ics — only tasks with a time of their own, for HA's
spoken calendar reminders (30 and 10 minutes before).

Dates only (VALUE=DATE) or UTC times, so no VTIMEZONE is needed.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\r\n", r"\n").replace("\n", r"\n")


def _fold(line: str) -> str:
    raw = line.encode()
    if len(raw) <= 75:
        return line
    out, chunk = [], b""
    for ch in line:
        b = ch.encode()
        if len(chunk) + len(b) > (75 if not out else 74):
            out.append(chunk.decode())
            chunk = b""
        chunk += b
    out.append(chunk.decode())
    return "\r\n ".join(out)


def render(projected: list[dict], now: datetime, tz, name: str = "Household tasks") -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//household//tasks//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_esc(name)}"]
    for p in projected:
        t, d = p["task"], p["date"]
        summary = t["title"]
        if t["alarm"]:
            summary += " · alarm"
        if t["assignee_name"]:
            summary += f" · {t['assignee_name']}"
        if p["overdue"]:
            n = t["days_overdue"]
            summary += f" (overdue {n} day{'s' if n != 1 else ''})"
        desc = t["schedule_text"] + (f"\n{t['notes']}" if t["notes"] else "")
        lines += ["BEGIN:VEVENT", f"UID:task-{t['id']}-{d:%Y%m%d}@tasks", f"DTSTAMP:{stamp}"]
        due_time = t["schedule"]["due_time"]
        if due_time and not p["overdue"]:
            hh, mm = map(int, due_time.split(":"))
            start = datetime.combine(d, time(hh, mm), tz).astimezone(timezone.utc)
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{start + timedelta(minutes=30):%Y%m%dT%H%M%SZ}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        lines += [f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(desc)}", f"CATEGORIES:{_esc(t['category'])}",
                  "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
