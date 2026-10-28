"""Environment → Config. Fails fast on values that would break scheduling."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# a scheme and host, with an optional port: nothing that could end the CSP directive
ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    send_to: str


@dataclass(frozen=True)
class Config:
    tz_name: str
    db_path: str
    api_token: str
    ha_url: str
    ha_token: str
    ha_tasks_user_id: str
    bot_url: str
    bot_token: str
    people: tuple[Person, ...]
    device_people: dict = field(hash=False)
    p0_send_to: str = "notify_all"
    digest_send_to: str = "notify_family"
    upcoming_calendars: tuple[str, ...] = ()
    ha_calendar_entity: str = "calendar.household_tasks"
    switch_tasks: dict = field(default_factory=dict, hash=False)   # entity_id -> task source key
    notify_enabled: bool = False
    digest_morning: str = "08:00"
    digest_evening: str = "20:30"
    spoken_fallback: str = "20:30"
    # Quiet = this HA switch is on (night mode): nothing is sent, pushed or spoken.
    # The clock window below is used only when HA's state can't be read.
    quiet_entity: str = ""
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    default_due_time: str = "17:30"   # new tasks without a time are due at this time
    p0_default_time: str = "17:30"
    p1_overdue_push: bool = True
    p1_overdue_push_time: str = "18:00"
    # Origins allowed to show the app in a frame (Home Assistant's addresses); none = never framed.
    frame_ancestors: tuple[str, ...] = ()
    calendar_days_ahead: int = 90
    # HA's persona script (script.era_generate_text, with custom_era) that writes
    # one-off tasks' reminder lines each morning. Blank = fixed lines for all.
    voice_text_script: str = ""
    log_level: str = "INFO"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def person(self, pid: str | None) -> Person | None:
        return next((p for p in self.people if p.id == pid), None)


def _bool(v: str, default: bool) -> bool:
    return default if not v.strip() else v.strip().lower() in ("1", "true", "yes", "on")


def _pairs(v: str) -> dict:
    out = {}
    for part in filter(None, (p.strip() for p in v.split(","))):
        k, _, val = part.partition(":")
        if k and val:
            out[k.strip()] = val.strip()
    return out


def load() -> Config:
    e = lambda k, d="": os.environ.get(k, d).strip()
    people = []
    for part in filter(None, (p.strip() for p in e("PEOPLE").split(","))):
        bits = part.split(":")
        if len(bits) != 3:
            raise SystemExit(f"PEOPLE entry {part!r} must be id:Name:send_to")
        people.append(Person(*[b.strip() for b in bits]))
    cfg = Config(
        tz_name=e("TASKS_TZ", "UTC"),
        db_path=e("DB_PATH", "/data/tasks.db"),
        api_token=e("TASKS_API_TOKEN"),
        ha_url=e("HA_URL").rstrip("/"),
        ha_token=e("HA_TOKEN"),
        ha_tasks_user_id=e("HA_TASKS_USER_ID"),
        bot_url=e("BOT_URL").rstrip("/"),
        bot_token=e("BOT_TOKEN"),
        people=tuple(people),
        device_people=_pairs(e("HA_DEVICE_PEOPLE")),
        p0_send_to=e("P0_SEND_TO", "notify_all"),
        digest_send_to=e("DIGEST_SEND_TO", "notify_family"),
        ha_calendar_entity=e("HA_CALENDAR_ENTITY", "calendar.household_tasks"),
        upcoming_calendars=tuple(filter(None, (c.strip() for c in e("UPCOMING_CALENDARS").split(",")))),
        switch_tasks={k: v for k, v in (p.split(":", 1) for p in filter(None, (x.strip() for x in e("HA_SWITCH_TASKS").split(","))) if ":" in p)},
        notify_enabled=_bool(e("NOTIFY_ENABLED"), False),
        digest_morning=e("DIGEST_MORNING", "08:00"),
        digest_evening=e("DIGEST_EVENING", "20:30"),
        spoken_fallback=e("SPOKEN_FALLBACK", "20:30"),
        quiet_start=e("QUIET_START", "22:00"),
        quiet_end=e("QUIET_END", "07:00"),
        quiet_entity=e("QUIET_ENTITY"),
        default_due_time=e("DEFAULT_DUE_TIME", "17:30"),
        p0_default_time=e("P0_DEFAULT_TIME", "17:30"),
        p1_overdue_push=_bool(e("P1_OVERDUE_PUSH"), True),
        p1_overdue_push_time=e("P1_OVERDUE_PUSH_TIME", "18:00"),
        calendar_days_ahead=int(e("CALENDAR_DAYS_AHEAD", "90") or 90),
        frame_ancestors=tuple(e("FRAME_ANCESTORS").replace(",", " ").split()),
        voice_text_script=e("VOICE_TEXT_SCRIPT"),
        log_level=e("LOG_LEVEL", "INFO").upper(),
    )
    problems = []
    if len(cfg.api_token) < 24:
        problems.append("TASKS_API_TOKEN must be set (at least 24 characters)")
    for k in ("digest_morning", "digest_evening", "p0_default_time", "p1_overdue_push_time", "default_due_time"):
        if not HHMM.match(getattr(cfg, k)):
            problems.append(f"{k.upper()} must be HH:MM")
    if bool(cfg.quiet_start) != bool(cfg.quiet_end) or any(v and not HHMM.match(v) for v in (cfg.quiet_start, cfg.quiet_end)):
        problems.append("QUIET_START and QUIET_END must both be HH:MM (or both blank)")
    if cfg.spoken_fallback and not HHMM.match(cfg.spoken_fallback):
        problems.append("SPOKEN_FALLBACK must be HH:MM or blank")
    if bad := [o for o in cfg.frame_ancestors if not ORIGIN.match(o)]:
        problems.append(f"FRAME_ANCESTORS takes origins like http://host:8123, not {', '.join(bad)}")
    ZoneInfo(cfg.tz_name)
    if problems:
        raise SystemExit("Config problems: " + "; ".join(problems))
    return cfg
