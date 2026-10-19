# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this is

The household's task and shopping service, running live as the Dockge stack `/opt/stacks/tasks` on the household Docker host (its LAN address is `TASKS_BIND_ADDR` in `.env`). It sends real reminders to real phones, the family Telegram group and the house speakers. `README.md` is the source of truth for behaviour, configuration and the change log; read the section for a feature before changing it, and add a dated change-log entry for any behaviour change.

## Rules that matter here

- **This directory is production.** A deploy is `docker compose up -d --build tasks`. Commit before and after a change; git is the rollback.
- **Never print `.env` values.** List keys with `cut -d= -f1 .env`. `.env`, `data/` and anything with `.bak` in its name stay out of git (`.gitignore`).
- **Never send a notification to test something** (no `POST /api/admin/test-notify`, no forced `/api/admin/run` with `dry:false`, no completing or snoozing real tasks) without the user's go-ahead. Pushes are critical alerts on family phones and Telegram messages reach the whole family.
- **Homelab never notifies.** `Tasks.open_tasks()` returns household tasks only, and every reminder, summary, spoken line, the calendar feed and `/api/summary` read from it. A new notifying path must start there too, never from `Tasks.list()`.
- **Night mode is sacred.** Nothing may push or speak while HA's night-mode switch (`QUIET_ENTITY`) is on (`Scheduler.quiet`). Any new send path must go through `Scheduler.deliver` and a `_due_slot` check.
- **Try UI interactions on a scratch copy**, never the live data: back up `data/tasks.db` with the SQLite backup API, run a second container on another port with `DB_PATH` pointing at the copy and `NOTIFY_ENABLED=false HA_TOKEN= BOT_TOKEN= HA_SWITCH_TASKS=`, test there, then remove it.
- **Keep the ledger names.** Scheduler job and `notifications.kind` names still say `p0_push` / `p1_overdue`; renaming them would let today's reminders send twice.
- **Old priority words stay accepted.** The bot and HA may send `p0`–`p3` or `critical`; `parse_priority` maps them (`critical`/`p0` = High + alarm).

## Commands

```bash
docker compose build tasks && docker run --rm --network none tasks-tasks python -m unittest discover tests   # 35 offline tests
docker compose up -d --build tasks
docker compose logs --since=30m tasks | grep -E 'sent|dry-run|failed|WARNING'
T=$(grep ^TASKS_API_TOKEN= .env | cut -d= -f2-)
B=http://$(grep ^TASKS_BIND_ADDR= .env | cut -d= -f2-):8040
curl -s -H "Authorization: Bearer $T" "$B/api/digest/preview?kind=evening"   # what a summary would say
```

Visual checks: screenshots of the live pages with headless Chromium (a throwaway Node image with `chromium` and `puppeteer-core`, run with `--network host`) are the way to look at the UI here; set `localStorage` keys `tasks-me`, `tasks-view-<tab>`, `tasks-period-<tab>`, `tasks-appearance` before loading. Read-only page loads are fine on live; anything that clicks Done, Snooze or drags goes to the scratch copy.

## Architecture

- **`app/schedule.py`**: pure date rules. Kinds `none`, `interval` (from last done), `rrule` (fixed). `parse_phrase` turns words into a schedule; `apply_flex` does weekend flex (Mon–Thu → Friday); occurrences are identified by `nominal_due`, the next one comes from `cursor`. Unit-tested in `tests/test_schedule.py`. Areas: a category is `household` or `homelab`, and a task takes its category's area; homelab tasks add a `stage` (idea, next, doing).
- **`app/tasks.py`**: the task rows. Create, patch, complete, skip, snooze; `serialize` adds `state`, `eff_due`, `occurrence`, `schedule_text`. Listeners fire after commits (the scheduler uses them to clear pushes, flip the Dog Meds switch and refresh HA's calendar).
- **`app/scheduler.py`**: one asyncio minute tick. Alarm pushes, High-overdue pushes, morning and evening summaries, the spoken fallback. Every send goes through `deliver` and the `notifications` ledger (unique per task, kind, day and channel).
- **`app/web.py`**: FastAPI routes, auth middleware, hooks for HA, `/calendar.ics`, and the built SPA.
- **`app/store.py`**: SQLite schema; `_migrate` applies schema changes on start. Add new migrations there, never by hand.
- **`app/ha.py`, `app/bot.py`**: Home Assistant REST (notification hub script, speech, switches, calendars) and ingest-bot's `/tasks-message`.
- **`frontend/src`**: React. `main.jsx` (tabs and routes), `tasks.jsx` (page, period filter, shared actions), `board.jsx` (generic dnd-kit `Board`; `TaskBoard` = priority columns), `homelab.jsx` (the progress board), `table.jsx` (sort, filters, inline edits), `snooze.jsx`, `controls.jsx` (the app's Select, DateField and TimeField; use these, not native select/date/time inputs), `toast.jsx` (`toast(title, description)` for confirmations that outlive the page), `task-form.jsx` with `schedule-builder.jsx`, `shopping.jsx`, `history.jsx`, `celebrate.jsx`, `tasks.css`.

## Design

- Use the design system's components and tokens (`@doshi-experiments/design-system`, a private package: its tarball sits in `frontend/vendor/` on this host and is gitignored, never commit it; its README and `docs/identity.md` live at `/opt/stacks/design-system`). To upgrade, build a tarball from its repo (`git archive` + `npm pack`), swap the vendored file and the `package.json` path, and rebuild the lockfile in `node:24-slim`.
- Felt rules followed here: underline tabs for local navigation (no global header in this private app), segmented controls for two-way switches, raised pills for buttons, pressed-in for fields only (don't nest recessed surfaces), stitched dashed rules to group form sections. The signal (0.7) is a red gradient under white text and is only ever a fill; text in that hue uses `action-link`. Error red must always come with its tinted background and words (use an error `Badge`), never bare red text, so it can't be mistaken for the brand.
- Copy: sentence case, plain verbs, the action's name repeated in its outcome ("Done: …", "Snoozed … until …").
- Check phone width (390px) and dark mode for any layout change.

## Related systems

- **ingest-bot** (`/opt/stacks/ingest-bot`, its own CLAUDE.md): the Telegram bot. Its `app/tasks_client.py` is this service's client and list backend; its `tools/migrate_to_tasks.py` imported the old lists.
- **Home Assistant**: the objects described in `ha/` live in HA, not here. Change them through HA's config API or UI, then re-export the installed version into `ha/local/` (gitignored) and keep the `ha/` templates in step, with `<PLACEHOLDERS>` instead of this house's entity names, user ids or addresses.
- **No personal or house details in git** (this repo will be public): no people's or pets' names, places, accounts, LAN IPs, tailnet names, HA entity names or user ids in tracked files, test data included (tests use Alex and Sam, UTC). Commits are authored as `doshi-experiments` with the GitHub noreply address (repo-local git config). Addresses come from `.env` (`TASKS_BIND_ADDR`, `HA_URL`); before committing, `git grep -nE '([0-9]{1,3}\.){3}[0-9]{1,3}|ts\.net|@[a-z0-9-]+\.[a-z]{2,}'` and a search for the family's names should find nothing.
- **Teable / Vikunja**: the old list apps, frozen for rollback; this service replaced them.
