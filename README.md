# Household tasks

One place for the household's chores, one-off to-dos and shopping lists, plus a board for homelab (software) projects. It works out when each task is due, reminds the right people at the right time (Home Assistant phone pushes, the family Telegram group, the house speakers), gives Home Assistant a calendar of what's coming up, and is the Telegram bot's list backend.

- **App:** `https://tasks.<your-tailnet>.ts.net` (Tailscale sidecar) and `http://<TASKS_BIND_ADDR>:8040` on the LAN
- **Runs on:** a Docker host, as the Dockge stack `/opt/stacks/tasks`
- **Built with:** Python 3.14, FastAPI and SQLite; React 19 and Vite on the shared design system [`@doshi-experiments/design-system`](https://github.com/doshi-experiments/design-system) 0.9.0 (Felt, signal red)
- **Talks to:** Home Assistant (`HA_URL`), the ingest-bot Telegram bot (`/opt/stacks/ingest-bot`)

## Using it

| Tab | What it's for |
|---|---|
| **One-off** | Things to do once. **Board** view: Low / Medium / High columns (High on top on a phone, where they stack); the **+** at the top of each column turns into a field: type a task, Enter adds it there and leaves the field open for the next, Esc cancels. Drag a card by its handle (or focus the handle, Space, arrows, Space) to reorder it or change its priority. **Table** view: sort by any heading, filter any column, change category and priority in place. |
| **Recurring** | Chores on a schedule. Same Board and Table views. **Done** moves a task to its next date. A column's **+** reads a schedule off the end of what you type (“water the plants every Saturday”); without one, the task repeats every week. |
| **Homelab** | Software to build, update or host, by project (Home Assistant, Tasks app, Ingest bot, Portfolio site, Infrastructure, New projects). A progress board: **Ideas → Next up → Doing → Done** (Done shows the last 14 days; dragging a card out of Done reopens it). Cards sort by priority within a column. The **+** on Ideas, Next up and Doing adds a Low task in that stage, in the project being shown (New projects under All). **Nothing here ever sends a reminder.** |
| **Shopping** | One list; every item carries a store, an aisle and a category. Left blank, all three follow from the title (`app/aisles.py`): milk goes to Real Canadian Superstore, Dairy & Eggs; shrubs to Home Depot, Garden Centre; a dining table to IKEA, Showroom. Categories are Groceries, Household, Pharmacy & Health, Pet Supplies, Home Improvement, Garden, Furniture & Decor, Electronics, Clothing and Other; Home Improvement and Garden default to Home Depot, Furniture & Decor to IKEA, Electronics to Best Buy, everything else to Superstore. Each store has its own aisles (Superstore, Costco, Home Depot and IKEA are mapped; any other store gets a general set). The store picker shows one store or all of them, with counts; the list is grouped under aisle headings (store and aisle when showing all, or category when sorted by category). Each row edits its store, aisle and category in place; moving an item to another store carries its aisle over. Every store picker ends with **New store…**, and telling the bot "buy tarp from canadian tire" adds one too. The add row's store, aisle and category start on Auto; a toast says where new items went. Tap an item to tick it off; Undo is right there. **Staples:** name a product once ("natrel 2% milk" on Telegram) and plain "milk" means it from then on, typos and capitals included; the product shows under the item. An item at Superstore or No Frills that nobody named a product for gets one **picked** from Loblaw's catalogue (the plainest product carrying its word: "2% Regular Milk" for milk), shown as "Picked: …"; it becomes the word's usual until someone names one, which replaces it without asking. **Prices:** an item at Superstore or No Frills whose product is matched to Loblaw's catalogue shows both stores' prices under it (sale end day, multi-buys, PC Optimum points), "Save $x at No Frills" with **Move** when the other store is cheaper, and a summary above the list (totals for items priced at both, and "Split the trip" when buying each item where it's cheapest saves at least $10). Prices are checked Thursday mornings and by **Check prices** (at most hourly). |
| **History** | What was done or skipped, by whom and from where (web, Telegram, phone, the Dog Meds switch). |

- **Show** (above both views): Due now, Next 7 days, This month or All, with counts. Overdue tasks always show.
- **Alarm on / Alarm off** on every household card and table row switches “alarm until done” in place (a daily critical push with the evening feed-the-dogs announcement, or at the task's own time, from its due date until it's done).
- **Snooze ▾** hides a dated task until Tomorrow, In 3 days, This weekend, Next week or a date you pick. It never counts as done and never changes the schedule.
- Confirmations are toasts, bottom right. **Done**, **Added** and **Archived** carry **Undo** for 8 seconds: after Done it puts the task back as it was (its date, and the history row goes; a switch-linked alarm task's switch comes back on if the alarm had already turned it on today, but cleared phone pushes aren't sent again), after Added it removes the task, after Archived it restores it. Archive no longer asks first.
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
| **Nagging** (Keep reminding on the task page, or `nag` through the API) | On the day it's due, from its time: a time-sensitive push with Done to the assignee's phone every `nag.every` minutes, and nothing in the Telegram group (an unassigned task pushes to everyone and posts in the group too). From `nag.escalate_at`: a **critical** push to everyone in `nag.escalate_to` and, now that others are pulled in, a message in the group, every `nag.escalate_every` minutes until someone taps Done. Each repeat is more passive-aggressive than the last, in the day's house voice (see **Voices** below), with a Done button in the same voice. The lines don't name the task: the phone push has the task as its title (⚠️ first for an escalation) and the Telegram group gets the line alone (⚠️ first for an escalation). Night mode holds the repeats but **not** the escalation. A day that ends without a Done is skipped at midnight (History: skipped, from "missed") so the next day starts fresh. Kept out of the morning and evening summaries, both calendar feeds (so HA's spoken briefings and summaries never read it) and the spoken feed-dogs line. |

Summaries go to the Telegram group (with Done buttons) and to each person's phone (their own tasks first). Assigned tasks notify that person; unassigned ones notify everyone.

**Voices (`app/voices.py`).** The house has one voice a day, picked at random by date: Gen Z, Shakespearean, Pirate, Mad scientist, NYC cabbie or Robot. Every reminder that day speaks in it, and each gets snippier the longer the task waits:
- alarm pushes and their Telegram message (due today, then 1, 2 and 3+ days overdue);
- the High-overdue push (1 day, 2 days, 3–6 days, a week or more);
- the spoken alarm line;
- nags and escalations;
- the summaries' opening line.

Alarm, overdue and spoken lines name the task, and the Telegram message is the line alone with no heading; the phone push keeps the task as its title. Done and Snooze buttons, on Telegram and on phones, use the voice's own labels ("Aye, 'tis done ⚓", "Belay that, tomorrow"). Every task carries the day's `voice`, so ingest-bot's Done GIF matches it.
- **Recurring tasks** use the fixed lines in `voices.VOICES`.
- **One-off tasks** get lines written once a day, from 05:00 (`prepare_lines`), by HA's persona script (`VOICE_TEXT_SCRIPT`, `script.era_generate_text` with `custom_era` set to the voice), and stored in `voice_lines`. The sends read the stored line and fall back to the fixed one, so nothing waits on HA at send time. If HA fails, the day uses the fixed lines; it isn't retried. A one-off task added after 05:00 uses the fixed lines that day.

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
| **Tasks** dashboard (Webpage, sidebar, `/household-tasks`) on `/local/tasks.html` | The whole app inside HA: the switcher page sends it to Tasks on the LAN when HA was opened on a LAN address, otherwise over Tailscale | `ha/www/tasks.html` |

These are templates with `<PLACEHOLDERS>`; `ha/README.md` lists them. The exact versions installed in this house, and the originals they replaced, live in `ha/local/` (kept out of git). The service uses its own non-admin HA user.

### Telegram (ingest-bot)

Telegram allows one program per bot token, so every Telegram message goes through ingest-bot's `POST /tasks-message`. Its task buttons call this service back. The bot uses this service for all lists (`LISTS_BACKEND=tasks`); see its README.

When a task is done, skipped, snoozed or archived anywhere else (the web app, a phone notification, the switch, a typed message or another Telegram message), every message from the last 7 days that still offers its buttons is edited: it keeps only the buttons that would still work (task open, same occurrence, not snoozed) and gets a line saying who closed it and where, like a tap does ("✅ Title (next …) — Sam, in the app"). Each `telegram_messages` row keeps the buttons it still offers (`buttons`, JSON); messages sent before 2026-10-26 have none and are left alone. The edit runs in `Scheduler._after_close` through the ledger (`telegram_tidy_<event>`; a dry run with `NOTIFY_ENABLED=false`). Night mode doesn't hold it: an edit is silent and pushes nothing. ingest-bot leaves the message a tap came from to its own tap handler. Undo doesn't put buttons back, just as it doesn't resend pushes.

### API (`app/web.py`)

Writes need `Authorization: Bearer $TASKS_API_TOKEN`, or a same-origin browser request with `X-Tasks-Request: 1`. `/hooks/*` is bearer only. Open: `/api/health`, `/calendar.ics`, `/calendar-reminders.ics`, the pages.

- **Tasks:** `GET/POST /api/tasks` (`?kind=recurring|oneoff|homelab&status&category&assignee&source&q&window&done_days`; `done_days` adds tasks finished in the last N days), `GET/PATCH/DELETE /api/tasks/{id}` (DELETE archives), `POST /api/tasks/{id}/complete|skip|snooze` (complete and skip return a `completion_id`), `POST /api/tasks/{id}/undo {completion_id}` (takes back the task's newest done or skip if nothing has changed it since; 409 otherwise), `POST /api/tasks/parse-schedule`. `POST /api/tasks` also takes `position` (board order) and `read_schedule: true` (read a schedule off the end of the title). PATCH sets `status` to open or archived, or to done only when restoring an archived task
- **Shopping:** `GET/POST /api/shopping`, `PATCH/DELETE /api/shopping/{id}`, `POST /api/shopping/{id}/buy|unbuy`, `POST /api/shopping/reorder`, `/api/shopping/lists`, `GET/POST /api/shopping/stores` (`{name}`; an existing name in any case returns that store). POST and PATCH take optional `category`, `store` and `aisle`, all lenient. Left out or blank on POST, they come from the title (`aisles.classify`): the category its words imply (else Groceries), that category's usual store, and that store's aisle for it (else `''`). Given, an unknown category coerces to Other, an unknown store is **created** (so any caller can introduce one), and an aisle that isn't in the item's store's set coerces to `''`. A PATCH that changes the store without an aisle keeps the aisle's name if the new store has it, else takes the new store's aisle for the same department (or the title's). The same item title at two stores is two items; at the same store it's a duplicate. `GET /api/bootstrap` carries the options under `shopping` (`item_categories`, `stores`, `aisles`, `default_aisles`, `defaults`) and `prices` (`enabled`, `stores`)
- **Staples:** POST `/api/shopping` items take an optional `product` (the specific product named: "Natrel 2%"). Each returned item carries `staple`, `product` (`label`, `code`, `catalogue_name`, `size`, `linked`, `tried`) and how it was read: `read_as` (the title was a near miss of a staple, now replaced by the staple's name), `learned` (this product became the staple's usual) and `ask_usual` (`{staple_id, product_id, staple, current, new}`: a different product than the usual went on this item only; ask whether it should become the usual). `POST /api/shopping/{id}/product {product}` corrects an item: on the usual (or a plain item) it changes or teaches the usual, on a one-off only that item (`usual_changed` says which). `GET /api/staples`, `POST /api/staples/{id}/usual {product_id}`
- **Prices:** `GET /api/prices` (`{enabled, running, stores, items: {item_id: {stores, cheapest, here, saving_cents, move_to}}, pricable, priced, complete, totals, split_saving_cents, last_refresh, status}`), `POST /api/prices/refresh` (the list only, in the background; 429 within an hour of the last press, 409 while one runs)
- **Nagging:** `POST`/`PATCH /api/tasks` take `nag: {every, escalate_at, escalate_every, escalate_to: [person ids]}` (minutes, 5–1440; `null` turns it off); homelab tasks never nag.
- **Views and admin:** `GET /api/summary`, `GET /api/upcoming?days=7` (tasks plus HA calendars), `GET /api/history`, `GET /api/digest/preview?kind=morning|evening|dog_alarm|p0`, `POST /api/admin/run`, `POST /api/admin/test-notify`
- **Hooks:** `POST /hooks/ha-action`, `POST /hooks/dog-alarm`; **feeds:** `GET /calendar.ics` (every open household task but nagging ones), `GET /calendar-reminders.ics` (upcoming tasks with their own time only)

Priorities are `high`, `medium`, `low` (stored 1–3); `critical` or the old `p0` means High with the alarm on. Homelab tasks also have a `stage` (`idea`, `next`, `doing`; done is the status) and never take the alarm. Categories have an `area` (`household` or `homelab`; `POST /api/categories {name, hint, area}`).

## Running it

```bash
cd /opt/stacks/tasks
docker compose up -d --build tasks          # deploy: code is baked into the image
docker compose restart tasks                # after a .env change only
docker compose logs --since=1h tasks | grep -E 'sent|dry-run|failed'
```

Offline tests (no network): build, then

```bash
docker run --rm --network none tasks-tasks python -m unittest discover tests
```

The design system's tarball is not committed here. Building the frontend needs it at `frontend/vendor/doshi-experiments-design-system-0.9.0.tgz`: check out the 0.9.0 release of the public [design-system repo](https://github.com/doshi-experiments/design-system), `git archive` it, then `npm pack`.

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
| `FRAME_ANCESTORS` | Origins allowed to show the app in a frame, space-separated (`http://host:8123`): every address Home Assistant is opened at. Empty = never framed (`X-Frame-Options: DENY`) |
| `VOICE_TEXT_SCRIPT` | HA's persona script that writes one-off tasks' reminder lines each morning (`script.era_generate_text`: takes `prompt`, `fallback_text`, `custom_era`; returns `{text, used_fallback}`). Blank = fixed lines for everything |
| `HA_SWITCH_TASKS`, `HA_CALENDAR_ENTITY`, `UPCOMING_CALENDARS` | Dog Meds switch mirror; the calendar to refresh; calendars for "what's coming up" |
| `PCX_API_KEY`, `PCX_STORES` | Loblaw prices: the static web key the chains' sites ship, and `banner:store id` pairs (`superstore`, `nofrills`, `wholesaleclub`; the first is searched when matching products). Store ids come from `GET https://api.pcexpress.ca/pcx-bff/api/v1/pickup-locations?bannerIds=<banner>`. Blank key = no prices (staples still work) |
| `PRICES_REFRESH`, `PRICES_SPLIT_MIN` | When prices are checked each week (`thu 07:00`, when the flyer week starts) and the saving that earns a "Split the trip" line (10, dollars) |

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
frontend/   React app; vendor/ is where the design-system tarball goes (not committed)
ha/         Home Assistant pieces this stack relies on (see above)
compose.yaml, Dockerfile, requirements.txt
```

## Change log

- **2026-11-02** — An assigned nagging task's repeats go to the assignee's phone only; the Telegram group hears it only from `nag.escalate_at`, when others are pulled in. Unassigned nagging tasks still post every repeat in the group. No new ledger kinds (repeats simply write no `nag_telegram` rows). Rollback: git revert.
- **2026-10-29 (b)** — Picked products. An open item at a Loblaw store with no product gets one picked (`Prices.autopick`, `prices.pick_plain`: in stock, carries every word of the title, typos and spacing allowed, fewest other words in its name, Loblaw's order on a tie) and priced, on add (within the same 8 s) and at every refresh. The pick becomes the word's usual (`staple_products.auto`, migrated on start); a named product replaces an automatic usual without `ask_usual`. A word nothing fits isn't searched again for a week (`prices.unpicked` in settings). A refresh skips a code and store priced in the last 30 minutes. Rollback: git revert (the column can stay).

- **2026-10-29** — Staples and Loblaw prices. **Staples** (`app/staples.py`): an item added with a `product` teaches its word ("milk" → Natrel 2%), and later plain "milk" gets that product. Titles match whatever their case, accents, plural or small typo (Damerau distance 1 up to 5 letters, 2 beyond, same first letter, ties refused), and a near miss is replaced by the staple's name and reported (`read_as`). A different product later goes on that item only, with `ask_usual` so the bot can ask; a correction (`POST /api/shopping/{id}/product`) changes the usual when the item was on it. New tables `staples`, `staple_products`; items gain `staple_id`, `product_id`. **Prices** (`app/pcx.py`, `app/prices.py`): a staple's product at a Loblaw store is matched once to the catalogue (search the first store, score brand, words, staple word and size; unsure = unlinked) and priced at every store in `PCX_STORES` by product code, through Loblaw's undocumented PC Express web API with the static key its sites ship, no login. That use is against Loblaw's terms; this is personal, at one request every 2 s, and a 401/403 pauses everything until the next start. Prices are only added (`price_obs`); a jump of more than 50% waits for the next check to agree. The weekly check runs as its own task, never in the reminder tick, and nothing is ever sent. The Shopping tab shows the product, both stores' prices, deals, Move, totals and Split the trip. Rollback: blank `PCX_API_KEY` and restart (prices off, staples stay), or `data/tasks-pre-staples-2026-10-29.db` + git revert.

- **2026-10-29** — Shopping items get their aisle, category and store from the title. Until now nothing set an aisle, and every item without a named store went to Superstore, garden and furniture included. The new `app/aisles.py` (pure, `tests/test_aisles.py`) reads a title into a department (word lists, the last noun wins, plurals, accents and near-miss typos), which gives the category, the category's usual store and each store's aisle. Four categories are new (Household, Garden, Furniture & Decor, Clothing). Home Depot, IKEA and Best Buy are seeded as stores, with aisle layouts for Home Depot and IKEA and more aisles at Superstore and Costco. On first start (`user_version` 1, `Store._fill_aisles`) every item that took the defaults was re-read: Groceries or Other items got the category their title implies, items at Superstore moved to that category's store, and blank aisles were filled. Categories, stores and aisles someone chose were kept. The shopping page's store filter is now a picker listing every store with counts (the segmented toggle couldn't hold more than three), the list has aisle headings, the add row starts on Auto, a toast says where new items went, and every store picker can add a store (`POST /api/shopping/stores`). Rollback: `data/tasks-pre-aisles-2026-10-29.db` + git revert.
- **2026-10-27** — One house voice a day for every reminder. The voice is picked per date (`voices.voice_of_day`), no longer per task, and every reminder speaks it: alarm pushes and messages, High-overdue pushes, spoken alarm lines, the summaries' opening line and nags. Each ladder gets snippier by days overdue. Alarm and overdue lines name the task, and their Telegram message is the line alone. Done and Snooze buttons on Telegram and phones use the voice's labels. Every task carries `voice` for ingest-bot's Done GIF. One-off tasks' lines are written each morning from 05:00 by HA's `script.era_generate_text`, which gained `custom_era` (`VOICE_TEXT_SCRIPT`), and stored in the new `voice_lines` table; recurring tasks use the fixed lines. Rollback: git revert; blank `VOICE_TEXT_SCRIPT` alone turns the HA lines off.
- **2026-10-27** — Nagging voices, take two: one voice per task per day (seeded by task and date) instead of per reminder; the plain voice is gone; the lines were rewritten not to name the task, so the Telegram group gets just the line while the phone push carries the task as its title; and the Done button (Telegram and phone) speaks in the day's voice (`done` in `digest.NAG_VOICES`).
- **2026-10-27** — Nagging tasks are quieter everywhere else and no longer ask HA for their words. The lines are fixed (`digest.NAG_VOICES`: seven voices, six repeats and two escalations each), with the voice picked at random per reminder and seeded by task and slot so the push, the Telegram message and any retry match. `NAG_TEXT_SCRIPT` and `HomeAssistant.write_text` are gone (the first real escalation timed out against HA while it was writing). The reminders have no heading: one line that names the task, ⚠️ first for an escalation. Nagging tasks are left out of the morning and evening summaries and of `/calendar.ics`, so HA's summary calendar, and the briefings and bedtime summary that read it aloud, don't mention them. Rollback: git revert.
- **2026-10-26** — Nagging from the task page. A Keep reminding section under Schedule sets it up: how often to repeat, and optionally a critical alert from a time, how often, and to whom (at least one person; everyone by default). A household task without a time of its own nags from the default time (17:30) instead of not at all.
- **2026-10-26** — Nagging tasks. A task's `nag` repeats its reminder (assignee's phone and the Telegram group) every N minutes from its time on the day it's due, then escalates to critical pushes for named people every M minutes from a set time until someone taps Done. The wording gets more passive-aggressive with each repeat, written by an HA script in the house's voice when `NAG_TEXT_SCRIPT` is set. Escalations go out in night mode (the one exception to quiet); a missed day is skipped at midnight. New columns `nag_every`, `escalate_at`, `escalate_every`, `escalate_to` (migrated on start); new ledger kinds `nag_*` and `escalate_*`, bucketed by slot time.
- **2026-10-26** — Closed elsewhere means gone from Telegram too. When a task is closed anywhere but its own Telegram button, the digests and nags that still offer it lose its buttons and gain a line saying who closed it and where (`Scheduler._tidy_telegram`, `digest.closed_line`, `Bot.update`). `telegram_messages` gains a `buttons` column (migrated on start); closes carry `closed_by` and `closed_via` on the task they return. Needs ingest-bot's `keep_text` edit of `/tasks-message` (its change log, 2026-10-26); without it the edit fails with a 400, harmlessly, in the ledger. Rollback: git revert (the column can stay).
- **2026-10-25** — One shopping list, split by store instead. "Everything Else" merged into Groceries on start (its items categorised Other, open and bought alike; the list row stays, archived) and items gained `category`, `store` and `aisle` columns plus a `stores` table (seeded with Real Canadian Superstore and Costco; new stores are created the first time an item names one). The shopping page's list toggle became a store filter (Superstore by default, All one tap away) over one flat list with a sort picker and quiet per-row pickers for store, aisle and category; the add form picks them for new items. Aisle sets are per store, with a generic set for new stores. A stale caller naming the archived list lands on Groceries, so the bot needed no change to keep working; store names it sends are passed through (see ingest-bot's own change log). Rollback: `data/tasks-pre-merge.bak.db` + git revert.
- **2026-10-24** — Tasks inside Home Assistant: a Webpage dashboard shows the whole app. `FRAME_ANCESTORS` lists the origins allowed to frame it (sent as `Content-Security-Policy: frame-ancestors`; without it, `X-Frame-Options: DENY` as before). HA serves a small switcher, `ha/www/tasks.html`, from its own address, so the dashboard opens Tasks on the LAN at home and over Tailscale away.
- **2026-10-24** — Undo and quick add. Confirmations are toasts everywhere (design system 0.9.0 adds a toast action); Done, Added and Archived have Undo, backed by `POST /api/tasks/{id}/undo` and a new `completions.undo` column (the task fields a done or skip changed, migrated on start). Archive no longer asks first. Priorities read Low, Medium, High in columns, pickers and filters, with High first once the board stacks on a phone. Each board column has a **+** that becomes a field (Enter adds at the top and stays open, Esc cancels); on Recurring it reads the schedule from the words via `schedule.split_phrase`. An empty board still shows its columns so the first task can be added there.
- **2026-10-19** — Design system 0.8.0: the pickers, toasts, snooze menu and alarm toggle now come from the design system (`Select`, `DateField`, `TimeField`, `ToastProvider`/`toast`, `MenuButton`, `ToggleButton` in its error tone). The app's `controls.jsx` and `toast.jsx` and their CSS are gone, along with a third of `tasks.css`. Picker fields are 44px, the same as text fields, and list options and calendar days are full 44px targets. The calendar in the snooze dialog's “Pick a date…” now opens over the dialog instead of behind it, and keyboard focus in a calendar stays within the allowed dates. Clear filters is a small ghost button.
- **2026-10-19** — Design system 0.7.1: buttons and toggles use its new `size="small"` (36px to the eye, 44px tap area) instead of this app's CSS override, which is gone. Rule from now on: UI changes go into the design system first.
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

## Licence

MIT, see [LICENSE](LICENSE).
