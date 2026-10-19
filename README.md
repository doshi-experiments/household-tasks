# Household tasks

One place for the household's chores, one-off to-dos and shopping lists, plus a board for homelab (software) projects. It works out when each task is due, reminds the right people at the right time (Home Assistant phone pushes, the family Telegram group, the house speakers), gives Home Assistant a calendar of what's coming up, and is the Telegram bot's list backend.

- **App:** `https://tasks.<your-tailnet>.ts.net` (Tailscale sidecar) and `http://<TASKS_BIND_ADDR>:8040` on the LAN
- **Runs on:** a Docker host, as the Dockge stack `/opt/stacks/tasks`
- **Built with:** Python 3.14, FastAPI and SQLite; React 19 and Vite on the private design system `@doshi-experiments/design-system` 0.7 (Felt, signal red)
- **Talks to:** Home Assistant (`HA_URL`), the ingest-bot Telegram bot (`/opt/stacks/ingest-bot`)

## Using it

| Tab | What it's for |
|---|---|
| **One-off** | Things to do once. **Board** view: High / Medium / Low columns; drag a card by its handle (or focus the handle, Space, arrows, Space) to reorder it or change its priority. **Table** view: sort by any heading, filter any column, change category and priority in place. |
| **Recurring** | Chores on a schedule. Same Board and Table views. **Done** moves a task to its next date. |
| **Homelab** | Software to build, update or host, by project (Home Assistant, Tasks app, Ingest bot, Portfolio site, Infrastructure, New projects). A progress board: **Ideas → Next up → Doing → Done** (Done shows the last 14 days; dragging a card out of Done reopens it). Cards sort by priority within a column. **Nothing here ever sends a reminder.** |
| **Shopping** | Groceries or Everything Else (the toggle picks which list you see, and new items go on it). Tap an item to tick it off; Undo is right there. |
| **History** | What was done or skipped, by whom and from where (web, Telegram, phone, the Dog Meds switch). |

- **Show** (above both views): Due now, Next 7 days, This month or All, with counts. Overdue tasks always show.
- **Alarm on / Alarm off** on every household card and table row switches “alarm until done” in place (a daily critical push with the evening feed-the-dogs announcement, or at the task's own time, from its due date until it's done).
- **Snooze ▾** hides a dated task until Tomorrow, In 3 days, This weekend, Next week or a date you pick. It never counts as done and never changes the schedule.
- **"I am"** (top right) is remembered per browser and is who gets credit for what you tick off.
- Done plays a short random dog moment (paw prints, a dog popping up, or hearts and bones). With reduced motion it's a simple fade.

Tasks can also be added and ticked off from the Telegram group in plain language (“water the plants every Saturday”, “gave the dogs their meds”, “what's coming up this week?”). The bot files anything software-related under Homelab on its own (“the morning briefing automation didn't fire”, “idea: self-host a recipe manager”) and sets its priority by impact: High when something running is broken or at risk, Medium for improving something in use, Low for ideas.

## How it works

### Schedules (`app/schedule.py`)

| Kind | Meaning | Phrases the parser understands |
|---|---|---|
| Once | One-off; no date means someday | — |
| After it's done (`interval`) | Every N days/weeks/months/years **from when it was last done**, so a late one moves the next one too | `every 30 days`, `monthly`, `quarterly`, `every 2 weeks` |
| On a calendar (`rrule`) | Fixed dates that never drift (RFC 5545 RRULE) | `every Saturday`, `every other sunday`, `monthly on the 1st`, `quarterly on the 7th`, `yearly on Apr 15`, `seasonally`, `every spring and fall` |

Add `on the weekend` (due any time Fri–Sun; a Mon–Thu date moves to Friday; overdue from Monday), `at 5:30pm`, `from done` (force "after it's done") or `fixed` (force calendar). New tasks without a time are due at **17:30**.

Under the hood: each occurrence is identified by its `nominal_due`; every Done/Snooze button carries it, so a second tap on another phone gets **409 "already done"** instead of closing the next one. A `cursor` (moved by done and skip) is what the next date is computed from, so editing a schedule after skipping never brings skipped dates back.

### Priorities and reminders (`app/scheduler.py`)

| | Reminders |
|---|---|
| **Alarm until done** (a switch on any task; dog meds has it) | A critical push to everyone, and the same in Telegram, both with Done / Snooze buttons, **with the first feed-the-dogs announcement of the evening** (when HA calls `/hooks/dog-alarm`; 20:30 on days it doesn't play). A task with a time of its own (anything but the 17:30 default) pushes at that time instead. Plus a spoken line at the end of every feed-dogs announcement. Repeats daily until done. |
| **High** | In the morning (08:00) and evening (20:30) summaries; once overdue, a time-sensitive push at 18:00 each day. |
| **Medium / Low** | In the morning and evening summaries, and spoken once in the first feed-dogs reminder of the day it's due. |

Summaries go to the Telegram group (with Done buttons) and to each person's phone (their own tasks first). Assigned tasks notify that person; unassigned ones notify everyone.

**Homelab tasks never notify:** they have no alarm or default time, and stay out of the summaries, pushes, speech, HA's calendar and sensor, and "what's coming up". A task's area comes from its category, so moving a chore into a Homelab project (or back) moves it in or out of all of that.

**Quiet:** nothing is sent, pushed or spoken while Home Assistant's night-mode switch (`QUIET_ENTITY`) is on. If HA can't be read, 22:00–07:00 stands in. A missed slot is caught up for 3 hours (an alarm for the rest of its day), then skipped. Every send is recorded in the `notifications` table, so a restart never sends twice.

### Home Assistant (`ha/`)

| In HA | What it does | In this repo |
|---|---|---|
| `calendar.household_tasks` (Remote Calendar on `/calendar.ics`, labelled for the summaries) | Tasks in spoken summaries and on dashboards; refreshed 15 s after any change | — (set up in the UI) |
| A second Remote Calendar on `/calendar-reminders.ics`, labelled **Reminder calendar** | Only tasks with a time of their own (not the 17:30 default), upcoming only: HA's calendar-reminders automation speaks them 30 and 10 minutes before (and pushes both phones) | — (set up in the UI) |
| `sensor.household_tasks` (REST, `/api/summary`) | Counts for dashboards | `ha/configuration-tasks.yaml` |
| `rest_command.tasks_action`, `tasks_dog_alarm`, `tasks_complete` | Phone buttons, the evening-reminder speech, the optional "done" switch | `ha/configuration-tasks.yaml` |
| Notification-actions automation | Forwards Done / Snooze taps on phone notifications | `ha/automations/` |
| Optional switch automation | An existing on/off helper doubles as a "done" switch for one alarm task | `ha/automations/` |
| Steps appended to an evening reminder | It ends with whatever Tasks says to add | `ha/automations/` |
| `script.tasks_announce` | Speaks a reminder (read exactly when an alarm is in it) | `ha/scripts/` |

These are templates with `<PLACEHOLDERS>`; `ha/README.md` lists them. The exact versions installed in this house, and the originals they replaced, live in `ha/local/` (kept out of git). The service uses its own non-admin HA user.

### Telegram (ingest-bot)

Telegram allows one program per bot token, so every Telegram message goes through ingest-bot's `POST /tasks-message`. Its task buttons call this service back. The bot uses this service for all lists (`LISTS_BACKEND=tasks`); see its README.

### API (`app/web.py`)

Writes need `Authorization: Bearer $TASKS_API_TOKEN`, or a same-origin browser request with `X-Tasks-Request: 1`. `/hooks/*` is bearer only. Open: `/api/health`, `/calendar.ics`, `/calendar-reminders.ics`, the pages.

- **Tasks:** `GET/POST /api/tasks` (`?kind=recurring|oneoff|homelab&status&category&assignee&source&q&window&done_days`; `done_days` adds tasks finished in the last N days), `GET/PATCH/DELETE /api/tasks/{id}` (DELETE archives), `POST /api/tasks/{id}/complete|skip|snooze`, `POST /api/tasks/parse-schedule`
- **Shopping:** `GET/POST /api/shopping`, `PATCH/DELETE /api/shopping/{id}`, `POST /api/shopping/{id}/buy|unbuy`, `POST /api/shopping/reorder`, `/api/shopping/lists`
- **Views and admin:** `GET /api/summary`, `GET /api/upcoming?days=7` (tasks plus HA calendars), `GET /api/history`, `GET /api/digest/preview?kind=morning|evening|dog_alarm|p0`, `POST /api/admin/run`, `POST /api/admin/test-notify`
- **Hooks:** `POST /hooks/ha-action`, `POST /hooks/dog-alarm`; **feeds:** `GET /calendar.ics` (every open household task), `GET /calendar-reminders.ics` (upcoming tasks with their own time only)

Priorities are `high`, `medium`, `low` (stored 1–3); `critical` or the old `p0` means High with the alarm on. Homelab tasks also have a `stage` (`idea`, `next`, `doing`; done is the status) and never take the alarm. Categories have an `area` (`household` or `homelab`; `POST /api/categories {name, hint, area}`).

## Running it

```bash
cd /opt/stacks/tasks
docker compose up -d --build tasks          # deploy: code is baked into the image
docker compose restart tasks                # after a .env change only
docker compose logs --since=1h tasks | grep -E 'sent|dry-run|failed'
```

Offline tests (35, no network): build, then

```bash
docker run --rm --network none tasks-tasks python -m unittest discover tests
```

The design system is a private package and is not in this repository. Building the frontend needs its tarball at `frontend/vendor/doshi-experiments-design-system-0.7.0.tgz` (from the design-system repo: `git archive` a release, then `npm pack`).

Frontend only (from `frontend/`, in the build's Node image):

```bash
docker run --rm -v "$PWD:/w" -w /w node:24-slim sh -c "npm ci && npx vite build"
```

### Configuration (`.env`, mode 600, never committed)

| Variable | Meaning |
|---|---|
| `TASKS_API_TOKEN` | Bearer for writes and hooks (HA and the bot hold it too) |
| `HA_URL`, `HA_TOKEN`, `HA_TASKS_USER_ID` | Home Assistant and the non-admin `tasks` user's token and id |
| `BOT_URL`, `BOT_TOKEN` | ingest-bot's `/tasks-message` (the bot's `HA_NOTIFY_TOKEN`) |
| `PEOPLE`, `HA_DEVICE_PEOPLE` | `id:Name:notify_target` per person; HA user id → person for phone taps |
| `NOTIFY_ENABLED` | `false` = compute and log only (`dry-*` ledger rows) |
| `P0_SEND_TO`, `DIGEST_SEND_TO` | Notification-hub targets for alarms and summaries |
| `DIGEST_MORNING`, `DIGEST_EVENING`, `P1_OVERDUE_PUSH(_TIME)`, `SPOKEN_FALLBACK` | Reminder times |
| `P0_DEFAULT_TIME`, `DEFAULT_DUE_TIME` | Default due times (17:30) |
| `QUIET_ENTITY`, `QUIET_START`, `QUIET_END` | Quiet = this HA switch on; the clock window is the fallback |
| `HA_SWITCH_TASKS`, `HA_CALENDAR_ENTITY`, `UPCOMING_CALENDARS` | Dog Meds switch mirror; the calendar to refresh; calendars for "what's coming up" |

### Data and backups

`data/tasks.db` is SQLite in WAL mode. Copy it safely with the backup API, for example:

```bash
docker exec tasks python -c "import sqlite3;s=sqlite3.connect('/data/tasks.db');d=sqlite3.connect('/data/tasks-$(date +%F).db');s.backup(d)"
```

Schema changes are made on start-up in `Store._migrate` (`app/store.py`).

## Layout

```
app/        FastAPI app, scheduler, schedule rules, HA and bot clients, calendar feed
tests/      offline unit and API tests
frontend/   React app; vendor/ is where the private design-system tarball goes (not committed)
ha/         Home Assistant pieces this stack relies on (see above)
compose.yaml, Dockerfile, requirements.txt
```

## Change log

- **2026-10-19** — Saving a task closes it: Save (or Add) goes back to the task's tab and a toast confirms ("Saved: …", with "Moved to Homelab" or the next date when that applies); archiving does the same. Toasts are Base UI's (`frontend/src/toast.jsx`), bottom right, gone after 4 s.
- **2026-10-19** — `/calendar-reminders.ics`: upcoming household tasks with a time of their own (not the 17:30 default), for a second HA Remote Calendar labelled Reminder calendar, so HA's existing calendar reminders speak them 30 and 10 minutes before. Tasks gain `own_time`.
- **2026-10-19** — Alarms go out with the evening feed-the-dogs announcement: the first `/hooks/dog-alarm` call of the day sends every due alarm at the default time (once a day, ledger `dog_alarm_heard`); without an announcement, `SPOKEN_FALLBACK` (20:30) stands in; never in night mode. Alarm tasks with their own time (not 17:30) keep it. `alarm_at` on each task says which.
- **2026-10-19** — UI round 4: an Alarm on/off toggle on household cards and a new Alarm column in the table (with a filter); the app's own dropdowns, date picker (calendar popover, keyboard friendly) and half-hour time picker replace the browser's (`frontend/src/controls.jsx`, Base UI Select and Popover); buttons and toggles 36px (34px on cards); drag handles centred on the card text; the table's filter count is gone (Clear filters sits in the filter row, so the table doesn't move); the "choose who you are" note is gone; the shopping toggle now shows one list at a time and adds to it.
- **2026-10-19** — Homelab tab: a progress board (Ideas → Next up → Doing → Done) for software projects, grouped by project with a filter. Tasks and categories gain an `area`; homelab tasks have a `stage` and never notify (`Tasks.open_tasks()` is household-only). The edit form switches to Project, Priority and Stage for them; either form can move a task between household and Homelab. Board drags with the keyboard now jump a whole column per Left/Right press. The Telegram bot files and prioritises homelab work itself (see its README).
- **2026-10-19** — Design system 0.7.0 (signal red): primary buttons are a raspberry-to-brick gradient with white text, links and focus are brick red. Overdue is now an error badge (tinted background and words) instead of red text and a red card edge, so it never reads as the brand colour; the shopping tick uses the signal gradient.
- **2026-10-19** — Repo created; README and CLAUDE.md written. `ha/` holds placeholder templates; house-specific exports and network addresses stay out of git (`ha/local/`, `.env`'s `TASKS_BIND_ADDR`).
- **2026-10-19** — The summary row is gone; the period filter is a "Show" dropdown with counts, plus a red "N overdue · N alarms due" note when there are any.
- **2026-10-19** — UI round 3: one raised "Snooze ▾" menu (table and cards, dated tasks only); cards show Snooze + Done and the title opens details; period filter shared by board and table; click-to-sort headers; the edit form's schedule is a stitched group rather than a recessed well.
- **2026-10-19** — UI round 2 and design system 0.6.0 "Felt": tabs One-off · Recurring · Shopping · History; Board (drag and drop via `@dnd-kit`, order saved in `tasks.position`) and Table (column filters, inline category and priority) on both task tabs; snooze durations; the dog celebration. Priorities became High / Medium / Low + `alarm` (old P0 rows migrated on start); `?kind=` filter; shorter schedule wording.
- **2026-10-18** — Quiet follows HA night mode (clock window as fallback). New tasks default to 17:30. Incident fixed: an evening summary went out at 23:03 because a catch-up window was still open and an "empty" slot didn't block a later send.
- **2026-10-18** — Lists migrated from Teable, HA to-do lists, Mealie and the Google check reminders (`ingest-bot/tools/migrate_to_tasks.py`); ingest-bot switched to this service for all lists.
- **2026-10-18** — Dog-meds cutover: the old HA helpers' automations turned off; the feed-dogs reminder and the Dog Meds switch wired to this service; notifications on.
- **2026-10-18** — Home Assistant (calendar, sensor, rest commands, notification actions, announce script) and Telegram (`/tasks-message`, task buttons) connected.
- **2026-10-18** — Stack created.
